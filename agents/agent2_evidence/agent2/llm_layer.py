#!/usr/bin/env python3
"""Agent 2, LLM layer on top of the rules.

Every fact unit of the record (segment.py: line / sentence / list item, exact spans) is shown to the model with
its id, document, section and the rule layer's guess as a hint. The model returns, for the units that state a
fact about the patient (or a relative), structured facts: concept key, value, unit, certainty, subject, status
(observed / current / past / stopped / planned / declined), a date if the text gives one, and optionally a shorter
exact quote inside the unit. Units not returned are dropped. Spans never come from free LLM text: a quote is
accepted only if it is an exact substring of its unit, otherwise the whole unit is the span.

Development: OpenRouter gpt-oss-120b.  Final: Claude Haiku 4.5 through the Message Batches API with prompt
caching (static instructions + examples, and per patient the candidate-trial criteria). Switching models changes
behaviour, so re-check (and re-tune) on dev after the switch; test stays blind.

Relevance modes:
  --relevance all        keep every fact about the patient (drop only non-facts: headings, scheduling, admin)
  --relevance criteria   the prompt also carries the criteria of the top candidate trials (plan.py) and the model
                         keeps only facts that could bear on one of them (fewer evidence, recall risk)

Checks after the model: known concept, enums, value type per concept type, unit conversion, date <= as_of, quote
inside the unit. Invalid or missing answers are re-asked in the next round (max 2 more rounds) with the problem
shown; still invalid -> the rule facts for that unit (extracted_by "rule").

Usage (package root):
  python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider openrouter --out runs/dev_oss_all --limit 2
  --provider openrouter (default model openai/gpt-oss-120b, needs OPENROUTER_API_KEY)
  --provider anthropic | anthropic-batch (default model claude-haiku-4-5-20251001, needs ANTHROPIC_API_KEY)
  --provider mock (no network)     --dry-run (print the first request, call nothing)
Outputs in --out: evidence.jsonl (③), log.jsonl (plan + checks per patient), answers.jsonl (raw answers and
problems per request), usage.json (tokens, cache tokens, cost estimate), cache/ (responses, batch ids).
"""
import argparse, collections, json, os, re, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R  # noqa: E402
import plan as PL  # noqa: E402
import prompts as P  # noqa: E402
from backends import Backend  # noqa: E402  (also loads .env)
from tracing import Tracer  # noqa: E402
from segment import units as segment_units  # noqa: E402
from extract import Extractor, load_concepts, concept_list, self_check, age_on, annotate, behavior_advice, sex_from_pronouns, CONFIRMED_DOCS, ORDER_RE  # noqa: E402

CERTAINTY = {"confirmed", "reported", "suspected"}
SUBJECT = {"patient", "family"}
STATUS = {"observed", "current", "past", "stopped", "planned", "declined"}
NUMERIC_TYPES = {"lab", "vital", "measurement"}
BOOL_TYPES = {"condition", "drug", "procedure", "behavior"}
FREE_VALUE = {"lab_other", "symptom_finding", "cancer_stage", "tumor_marker", "biomarker", "hcg", "hepatitis_b",
              "hepatitis_c", "hiv", "blood_pressure", "ecog", "pulmonary_function", "islet_autoantibodies", "visual_acuity"}
# a number key with a qualitative result ("HBV DNA not detected", "protein trace"): kept as that word (common format
# 9: "not detected", "trace" are stored as written), the same shape the rules give; "undetectable" -> "not detected"
QUALITATIVE_RE = re.compile(r"(?:not\s+detected|undetect(?:able|ed)|below\s+(?:the\s+)?(?:lower\s+)?(?:limit\s+of\s+)?"
                            r"(?:detection|quantification)|negative|positive|detected|trace|non-?reactive|reactive|[1-4]\+)",
                            re.I)
NOT_DETECTED_RE = re.compile(r"undetect|below\s", re.I)
# Child-Pugh written as a class letter: "A" / "class A" / "Child-Pugh A" -> "class A" (as the rules); "B7" -> score 7
CHILD_PUGH_VALUE_RE = re.compile(r"(?:child[- ]?pugh\s*)?(?:class\s*)?([ABC])\s*-?\s*(\d{1,2})?", re.I)


def qualitative_written(c, text):
    """The word must stand next to the key's own name in the unit ("HBV DNA not detected", "negative for HBV DNA"),
    so a stray word on another key (eGFR "negative") is re-asked instead of stored."""
    names = {n for n in (c.get("aliases") or []) + [c.get("name") or "", c["key"].replace("_", " ")] if len(n) >= 2}
    for n in sorted(names, key=len, reverse=True):
        for m in re.finditer(r"(?<![A-Za-z0-9])" + re.escape(n).replace(r"\ ", r"[\s-]*") + r"(?![A-Za-z])", text, re.I):
            # same clause: up to ; | newline, or a comma / full stop followed by a space or the end
            after = re.split(r"[;|\n]|[,.](?=\s|$)", text[m.end():m.end() + 80], maxsplit=1)[0]
            q = QUALITATIVE_RE.search(after)
            if q:
                pre = after[:q.start()]
                if not re.search(r"\d", pre):
                    if len(pre) <= 30:                       # "HBV DNA level remained below the limit of detection"
                        return True
                elif re.fullmatch(r"[\s:=-]*[<≤]\s*[\d.,]+\s*[A-Za-z/^0-9.*]*\s*[(\[]?\s*", pre):
                    return True                              # "HBV DNA: <10 IU/mL (not detected)"
            before = text[max(0, m.start() - 40):m.start()]
            if re.search(QUALITATIVE_RE.pattern + r"\s+(?:for|of)\s*$", before, re.I):
                return True
    return False
DEFAULT_MODEL = {"openrouter": "openai/gpt-oss-120b", "anthropic": "claude-haiku-4-5-20251001",
                 "anthropic-batch": "claude-haiku-4-5-20251001", "mock": "mock",
                 "replay": "openai/gpt-oss-120b"}
ROUNDS = 3
# source.span = the whole unit (sentence / line / list item); the model's quote is kept in detail.quote.
# On dev (20 patients) unit spans beat quote spans on recall and IoU: the model often quotes only part of a unit.
SPAN_MODE = os.environ.get("AGENT2_SPAN", "unit")
# concepts the rules read reliably (number next to a known alias, demographics, serology): when every rule fact of a
# unit is one of these and the unit has no negation / family / suspicion / plan / report cue, the unit is not sent
# to the model at all (saves about a fifth of the units and their output tokens, i.e. latency)
RULE_SAFE = {"hemoglobin", "platelet_count", "wbc", "anc", "creatinine", "egfr", "creatinine_clearance",
             "bilirubin_total", "ast", "alt", "albumin", "inr", "hba1c", "glucose", "potassium", "sodium", "tsh",
             "free_t4", "total_t3", "triglycerides", "ldl_cholesterol", "total_cholesterol",
             "urine_protein_creatinine_ratio", "urine_albumin_creatinine_ratio", "crp", "lipase", "body_weight",
             "body_height", "bmi", "blood_pressure", "heart_rate", "body_temperature", "spo2", "respiratory_rate",
             "sex", "birth_date", "nationality", "age", "hepatitis_b", "hepatitis_c", "hiv", "lvef", "qtc", "ecog",
             "karnofsky"}
CUE_RE = re.compile("|".join(r.pattern for r in (R.FAMILY_RE, R.SUSPECT_RE, R.PLAN_RE, R.DECLINED_RE, R.REPORTED_RE))
                    + r"|\b(?:no|not|denies|never|without|stopped|discontinued|held|previous|prior|baseline)\b", re.I)


GENERIC_RULE = {"symptom_finding", "lab_other", "diagnosis", "medication", "procedure", "treatment_plan"}


def rule_keeps(u):
    """Rule facts worth keeping even when the model drops the unit: an explicit denial, a specific concept, or a
    drug / procedure found by the lexicons (the model sometimes drops real facts in a long drop list)."""
    return [f for f in u["rule_facts"]
            if f["value"] is False or f["concept"] not in GENERIC_RULE or
            (f["concept"] == "medication" and (f.get("lexicon") or u["section"] == "meds" or
                                               u["doc"]["type"] == "medication_record" or R.DOSE_RE.search(u["text"]))) or
            (f["concept"] == "procedure" and (f.get("lexicon") or u["section"] == "psh")) or
            (f["concept"] == "treatment_plan" and f.get("lexicon")) or          # options / plans named by lexicon
            (f["concept"] == "symptom_finding" and SCORE_RE.search(u["text"]))]  # "CAT 20", "mMRC 2", "NYHA III"


# a clinical score or count: acronym + number ("CAT 20", "mMRC 2", "DAS28-CRP 5.1", "NYHA III", "2 exacerbations")
SCORE_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9-]{1,9}\s*(?:score\s*)?[:=]?\s*(?:\d+(?:\.\d+)?(?:/\d+)?|[IV]{1,4})\b|"
                      r"\d+\s+(?:episodes?|exacerbations?|admissions?|hospitali[sz]ations?|relapses?|flares?|attacks?)\b)")


def rule_missing(u, llm_facts):
    """Specific rule facts the model's answer for this unit left out (e.g. TSH and T3 in a sentence where the
    model only wrote TRAb). Added next to the model's facts; generic and negated rule facts are not added,
    the model's reading of those wins."""
    have = {f["concept"] for f in llm_facts}
    return [f for f in u["rule_facts"] if f["concept"] not in GENERIC_RULE and f["concept"] not in have
            and f["value"] is not False]


def ok_conflict(u):
    """'ok' cannot be right when the unit denies something but no rule fact is false."""
    body = R.LABEL_RE.sub("", u["text"], count=1)
    return bool(R.NEG_CUE.search(body)) and not any(f["value"] is False for f in u["rule_facts"])


NONFACT_RE = re.compile(r"\s*(?:\d{1,2}[.)]?|[A-Za-z]{1,4}[.:]?|(?:[A-Z][\w/&-]*\s*){1,6}(?:panel|differential|chemistry|"
                       r"serology|urinalysis|coagulation|other|marker|markers|labs?|results?)?\s*(?:\([^)]*\))?[.:]?)\s*", re.I)


def non_fact(u):
    """Headings and list numbers with nothing the rules found: 'CBC with differential', 'Comprehensive metabolic
    panel', 'HPI', '1.'. Not sent to the model (Haiku answers such units with a bare id or ok anyway)."""
    t = u["text"]
    if u["rule_facts"] or re.search(r"\d\s*[A-Za-z%/]|[<>=]", t):
        return False
    if re.fullmatch(r"\s*\d{1,2}[.)]?\s*|\s*[A-Za-z]{1,4}[.:]?\s*", t):
        return True
    return u["doc"]["type"] == "lab_result" and len(t.split()) <= 6 and not re.search(
        r"\b(?:negative|positive|reactive|detected|pending|normal|abnormal|trace|none|within|range|ranges|unremarkable)\b", t, re.I)


def rule_only(u):
    fs = u["rule_facts"]
    return bool(fs) and all(f["concept"] in RULE_SAFE for f in fs) and not CUE_RE.search(u["text"])


# ------------------------------------------------------------------ validation

PREWARM_MIN = 4


def doc_hash(d):
    """What identifies a document version for the update path: its text, date and type."""
    import hashlib
    return hashlib.sha1(json.dumps([d["text"], d.get("date"), d.get("type")], ensure_ascii=False).encode()).hexdigest()[:16]


def write_manifest(patients, path):
    """docs.jsonl next to evidence.jsonl: which document versions the evidence was extracted from (update.py reads it)."""
    with open(path, "w", encoding="utf-8") as f:
        for p in patients:
            f.write(json.dumps({"patient_id": p["patient_id"], "as_of": p["as_of"],
                                "docs": {d["doc_id"]: doc_hash(d) for d in p["documents"]}}) + "\n")


def _shares_word(a, b):
    """True when a and b share a content word (first 4 letters) or an acronym."""
    def ws(x):
        return {w.lower()[:4] for w in re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", x)} | set(re.findall(r"\b[A-Z0-9]{2,6}\b", x))
    if ws(a) & ws(b):
        return True
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z]+", a)).upper()   # "delirium tremens" ~ "DTs"
    return any(len(m) >= 2 and m in initials for m in re.findall(r"\b([A-Z]{2,6})s?\b", b))


def check_fact(f, unit_text, concepts, as_of):
    """Returns (clean fact or None, problems)."""
    if not isinstance(f, dict):
        return None, ["fact is not an object"]
    ck = f.get("concept")
    c = concepts.get(ck.replace("\xa0", " ").strip() if isinstance(ck, str) else ck)
    if not c and isinstance(ck, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,40}", ck.strip()):
        # a concept the model made up ("adherence"): keep the fact as a generic finding named by it
        f = dict(f, concept="symptom_finding", term=f"{ck.strip().replace('_', ' ')}: {f.get('term') or f.get('value')}",
                 value=f.get("value") if isinstance(f.get("value"), bool) else True)
        c = concepts["symptom_finding"]
    if not c:
        return None, [f"unknown concept {f.get('concept')!r}"]
    probs, k, t = [], c["key"], c.get("type")
    out = {"concept": k}
    v, unit = f.get("value"), f.get("unit")
    if isinstance(v, (list, dict)) or isinstance(unit, (list, dict)):
        return None, [f"{k}: value and unit must be single values"]
    if unit is not None and not isinstance(unit, str):
        unit = str(unit)
    qual = None
    if t in NUMERIC_TYPES and k not in FREE_VALUE and isinstance(v, str):
        s = v.replace("\xa0", " ").strip()
        if k == "child_pugh" and (m := CHILD_PUGH_VALUE_RE.fullmatch(s)):
            w = R.CHILD_PUGH_RE.search(unit_text)
            if not w or w.group(1).upper() != m.group(1).upper():
                probs.append(f"{k}: class {m.group(1).upper()!r} is not written as Child-Pugh in this unit")
            elif m.group(2):
                v = int(m.group(2))
            else:
                qual = "class " + m.group(1).upper()
        elif QUALITATIVE_RE.fullmatch(s):
            if qualitative_written(c, unit_text):
                qual = "not detected" if NOT_DETECTED_RE.search(s) else re.sub(r"\s+", " ", s.lower())
            else:
                probs.append(f"{k}: {s!r} is not written next to {c.get('name') or k} in this unit; give the number "
                             f"as written, or leave this fact out")
    if qual is not None:
        out.update(value=qual, unit=None, value_type="categorical")
    elif probs:
        pass
    elif t in NUMERIC_TYPES and k not in FREE_VALUE:
        if isinstance(v, bool):
            probs.append(f"{k}: value {v!r} is not a number; a qualitative result is given as the word written "
                         f"(\"not detected\", \"trace\")")
        if isinstance(v, str):
            try:
                sign = re.match(r"\s*(<=|>=|≤|≥|<|>)", v)
                v = float(v.replace(",", "").lstrip("<>=≤≥~ "))
                if sign and not f.get("comparator"):          # "<10" written in the value: keep the "<"
                    f = dict(f, comparator={"≤": "<=", "≥": ">="}.get(sign.group(1), sign.group(1)))
            except ValueError:
                probs.append(f"{k}: value {v!r} is not a number")
        if not probs and (isinstance(v, bool) or not isinstance(v, (int, float))):
            probs.append(f"{k}: value {v!r} is not a number")
        if not probs and isinstance(v, (int, float)) and v < 0:
            probs.append(f"{k}: a negative value is a change, not a measurement; give it as symptom_finding with "
                         f"the change in term (e.g. 'weight loss 5 kg')")
        if not probs:
            v2, u2, ok = R.convert(v, unit, c)
            out.update(value=v2, unit=u2, value_type="numeric")
            if not ok:
                out["unit_written"] = unit
    elif t in BOOL_TYPES and k not in FREE_VALUE:
        if not isinstance(v, bool):
            probs.append(f"{k}: value must be true or false, got {v!r}")
        out.update(value=v, unit=None, value_type="boolean")
    else:
        if isinstance(v, (int, float)) and not isinstance(v, bool) and unit and c.get("unit"):
            v, unit, _ = R.convert(v, unit, c)
        out.update(value=v, unit=unit or c.get("unit"),
                   value_type="numeric" if isinstance(v, (int, float)) and not isinstance(v, bool)
                   else "boolean" if isinstance(v, bool) else "date" if k == "birth_date" else "categorical")
    for fld, allowed, default in (("certainty", CERTAINTY, "confirmed"), ("subject", SUBJECT, "patient"),
                                  ("status", STATUS, "observed")):
        val = f.get(fld) or default
        if isinstance(val, str):
            val = val.replace("\xa0", " ").strip().lower()
        if val not in allowed:
            probs.append(f"{fld} {val!r} must be one of {sorted(allowed)}")
        out[fld] = val
    for fld in ("date", "start"):
        d = f.get(fld)
        if d:
            try:
                if date.fromisoformat(d) > date.fromisoformat(as_of):
                    probs.append(f"{fld} {d} is after the judgment date {as_of}")
            except (TypeError, ValueError):
                probs.append(f"{fld} {d!r} is not YYYY-MM-DD")
        out[fld] = d or None
    term = f.get("term")
    out["term"] = term if isinstance(term, str) and term else None
    if k == "social_history" and out.get("value") is not True:
        # the model sometimes puts the words in "value" ("Guardian: mother." -> value "mother"): keep one shape
        if out.get("value") not in (None, False, "") and not out["term"]:
            out["term"] = str(out["value"])
        if out.get("value") is not False:
            out.update(value=True, value_type="boolean", unit=None)
    if k == "social_history" and not out["term"]:
        out["term"] = (out.get("quote") or unit_text)[:80]
    # "term": "no cough", "value": true  ->  cough false (the denial belongs in the value, not in the term)
    if out["term"] and out.get("value") is True and k in ("symptom_finding", "diagnosis", "medication", "procedure"):
        pos_part, neg_part = R.clause_polarity(out["term"])
        if neg_part and not pos_part:
            out["value"] = False
            out["term"] = R.NEG_CUE.sub("", out["term"], count=1).strip(" ,.") or out["term"]
            out["fixed"] = "double_negative"
    comp = f.get("comparator")
    out["comparator"] = comp if comp in ("<", ">", "<=", ">=") else None
    q = f.get("quote")
    out["quote"] = q if isinstance(q, str) and q.strip() and q in unit_text else None
    # a fact that belongs to another unit (the model shifted the id: "Endocrine clinic, new referral." answered with
    # the HPI's palpitations and weight loss): its quote is not here and its term shares no word with the unit
    if (k in ("symptom_finding", "diagnosis", "procedure", "medication", "treatment_plan", "social_history")
            and isinstance(q, str) and q.strip() and not out["quote"] and out["term"] and not _shares_word(out["term"], unit_text)):
        probs.append(f"{k} {out['term']!r}: neither the quote nor the term is in this unit; give each fact on the unit "
                     f"that states it")
    # "Denies any prior systemic therapy for liver cancer" came back as diagnosis = false ["prior systemic therapy for
    # hepatocellular carcinoma"]: a denied treatment is a treatment fact, never a denied disease
    if out["concept"] == "diagnosis" and out["term"] and re.match(   # the term names a treatment, not a disease
            r"\s*(?:(?:any|prior|previous|systemic|first-line|second-line|adjuvant|neoadjuvant|targeted|local)\s+)*"
            r"(?:therap\w*|treatment|chemo\w*|immunotherap\w*|radiotherap\w*|radiation|surgery|resection|"
            r"transplant\w*|ablation|embolization|TACE)(?![\w-])", out["term"], re.I):   # not "chemo-induced ..."
        out["concept"] = ("procedure" if re.search(r"surgery|resection|transplant|ablation|embolization|TACE|"
                                                   r"radiotherap|radiation", out["term"], re.I) else "medication")
        out["fixed"] = "treatment_not_diagnosis"
    # "Alcohol use disorder: abstinent since 09-25" came back as alcohol true, current: a habit the patient has
    # stopped is true with status "past" (prompt rule: a past smoker is smoking true, past), never "current"
    if (out["concept"] in ("smoking", "alcohol", "substance_use") and out.get("value") is True and out["status"] == "current"
            and re.search(r"\b(?:abstinent|abstinence|quit|stopped|former(?:ly)?|ex-?\s?(?:smoker|drinker)|none since|"
                          r"no longer|gave up)\b", " ".join(x for x in (out["term"], out["quote"]) if x), re.I)):
        out["status"] = "past"
        if out.get("start"):                     # "abstinent since 09-25": the date it stopped, not a start
            out["date"], out["start"] = out.get("date") or out["start"], None
        out["fixed"] = "habit_stopped_is_past"
    # a former habit is true + past ("Remains abstinent from smoking since 2020" came back as smoking false, past, while
    # "quit 2020" of the same patient was true, past): false would read as "never smoked"
    if (out["concept"] in ("smoking", "alcohol", "substance_use") and out.get("value") is False
            and re.search(r"\b(?:abstinent|abstinence|quit|stopped|former(?:ly)?|ex-?\s?(?:smoker|drinker)|gave up|"
                          r"no longer)\b", " ".join(x for x in (out["term"], out["quote"], unit_text) if x), re.I)
            and not re.search(r"\bnever\b|\bnon-?(?:smoker|drinker)\b|\b0 pack", unit_text, re.I)):
        out.update(value=True, status="past")
        out["fixed"] = "former_habit_is_true_past"
    if out["concept"] in ("medication", "procedure") and out["status"] in ("planned", "declined") and out.get("value") is True:
        out["concept"] = "treatment_plan"        # rule 6: not received
    # an order in the note ("Start prednisolone 60 mg/m2/day.") is a treatment given, whatever the model said
    if (out["concept"] == "treatment_plan" and out["status"] == "planned"
            and ORDER_RE.match(R.LABEL_RE.sub("", unit_text, count=1)) and not R.PLAN_RE.search(unit_text)):
        out.update(concept="medication", status="current", value=True)
        out["fixed"] = "order_is_given"
    return (None if probs else out), probs


# ------------------------------------------------------------------ units and prompts

def candidate_units(p, ex):
    out = []
    for d in p["documents"]:
        secs = R.sections(d["text"])
        for u in segment_units(d["text"]):
            s, e = u["span"]
            t = d["text"][s:e]
            sec = R.section_at(secs, s)
            facts = annotate(ex.unit_facts(t, d, sec), t, d["text"][u["parent"][0]:u["parent"][1]], d, sec)
            out.append({"uid": len(out) + 1, "doc": d, "span": (s, e), "text": t, "section": sec,
                        "parent": u["parent"], "rule_facts": facts})
    return out


def hint(facts):
    """Rule guess shown to the model, with its non-default marks: 'diagnosis=false[arthritis]',
    'diagnosis=true[disease]/suspected', 'treatment_plan=true[statin]/planned'."""
    out = []
    for f in facts[:4]:
        v = str(f["value"]).lower() if isinstance(f["value"], bool) else f["value"]
        h = f"{f['concept']}={v}"
        if f["concept"] in GENERIC_RULE and f.get("term"):
            h += f"[{f['term'][:30]}]"
        for mark in (f.get("certainty") if f.get("certainty") not in (None, "confirmed") else None,
                     "family" if f.get("subject") == "family" else None, (f.get("extra") or {}).get("status")):
            if mark:
                h += "/" + mark
        out.append(h)
    return "; ".join(out) or "-"


def unit_line(u):
    return (f"u{u['uid']} | {u['doc']['doc_id']}, {u['doc']['type']}, {u['doc'].get('date')} | {u['section'] or '-'} | "
            f"{u['text'].replace(chr(10), ' ')} | hint: {hint(u['rule_facts'])}"
            + (f" | your previous answer was invalid: {'; '.join(u['problems'][:3])}" if u.get("problems") else ""))


def units_text(chunk):
    lines, shown = [], set()
    for u in chunk:
        if u["parent"] != u["span"] and (u["doc"]["doc_id"], u["parent"]) not in shown:   # list items: sentence once
            shown.add((u["doc"]["doc_id"], u["parent"]))
            lines.append(f"   (sentence in {u['doc']['doc_id']}: "
                         f"{u['doc']['text'][u['parent'][0]:u['parent'][1]].replace(chr(10), ' ')})")
        lines.append(unit_line(u))
    return P.UNITS.format(units="\n".join(lines))


def chunks_by_document(units, size):
    """Chunks of at most `size` units that do not split a document unless it alone is larger."""
    out, cur = [], []
    for doc_id in dict.fromkeys(u["doc"]["doc_id"] for u in units):
        du = [u for u in units if u["doc"]["doc_id"] == doc_id]
        if cur and len(cur) + len(du) > size:
            out.append(cur)
            cur = []
        while len(du) > size:
            out.append(du[:size])
            du = du[size:]
        cur += du
    if cur:
        out.append(cur)
    return out


def parse_answer(text):
    """{"units": [...]} from the model answer. A truncated answer (output limit reached mid-JSON) still yields every
    unit object that was written completely; the rest of the request is re-asked. Returns (items, truncated)."""
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        obj = json.loads(text[text.find("{"):text.rfind("}") + 1])
        units = obj.get("units") if isinstance(obj, dict) else None
        if isinstance(units, list):
            drop = obj.get("drop")
            return units, (drop if isinstance(drop, list) else None), False
    except ValueError:
        pass
    m = re.search(r'"units"\s*:\s*\[', text)
    if not m:
        raise ValueError("no units array in the answer")
    dec, pos, items = json.JSONDecoder(), m.end(), []
    while True:
        while pos < len(text) and text[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(text) or text[pos] == "]":
            break
        try:
            item, pos = dec.raw_decode(text, pos)
        except ValueError:
            break                                   # cut off here
        items.append(item)
    if not items:
        raise ValueError("answer cut off before the first complete unit")
    return items, None, True


def degenerate(text, source=""):
    """Signs that generation broke down: runs of non-breaking spaces or of whitespace (seen with gpt-oss, where the
    rest of the answer was lost). A shortened quote ("No ... vomiting") is not a breakdown: such a quote is not a
    substring of its unit, so check_fact drops the quote and keeps the fact."""
    return (text.count("\xa0") >= 8 + source.count("\xa0")
            or bool(re.search(r"\xa0{3,}|(\s)\1{40,}", text)))


# ------------------------------------------------------------------ run

class PatientState:
    def __init__(self, p, ex, planner, a, only_docs=None):
        """only_docs: extract these documents only (update path); the plan still comes from the whole record, so the
        prompt's criteria part is the same as in the first extraction and its cache can be reused."""
        self.p = p
        self.checks = collections.Counter()
        self.plan = planner.plan(p, a.k) if planner else None
        self.units = candidate_units(p if only_docs is None else
                                     dict(p, documents=[d for d in p["documents"] if d["doc_id"] in only_docs]), ex)
        # uid -> ("llm", facts) | ("ok", None) hint accepted | ("rule", None) not sent | ("fallback", None)
        self.answers = {}
        self.pending = []
        for u in self.units:
            if non_fact(u) and not os.environ.get("AGENT2_SEND_HEADINGS"):   # env: replay of older answers
                self.answers[u["uid"]] = ("llm", [])
                self.checks["units_not_sent_heading"] += 1
            elif a.send_all or not rule_only(u):
                self.pending.append(u)
            else:
                self.answers[u["uid"]] = ("rule", None)
        self.checks["units_rule_only"] = len(self.units) - len(self.pending)
        self.seconds = 0.0
        self.criteria = ""
        if a.relevance == "criteria" and self.plan:
            lines = []
            for tid, _ in self.plan["candidate_trials"][:a.k_criteria]:
                lines += [f"{tid}: {c}" for c in planner.crit_by_trial[tid]]
            self.criteria = P.PATIENT_CRITERIA.format(criteria="\n".join(lines[:a.max_criteria]))


def run(patients, ex, concepts, concept_text, planner, backend, a, answers_log, only_docs=None):
    states = [PatientState(p, ex, planner, a, (only_docs or {}).get(p["patient_id"]) if only_docs is not None else None)
              for p in patients]
    static_by_asof = {}
    for rnd in range(ROUNDS):
        reqs, index = [], {}
        for st in states:
            if not st.pending:
                continue
            as_of = st.p["as_of"]
            static = static_by_asof.setdefault(as_of, P.static_part(as_of, concept_text, a.relevance))
            size = max(10, a.chunk >> rnd)          # retries go in smaller requests (faster, fewer timeouts)
            for i, ch in enumerate(chunks_by_document(st.pending, size)):
                cid = f"{st.p['patient_id']}-r{rnd}-c{i}"
                reqs.append({"custom_id": cid, "static": static, "patient": st.criteria, "units": units_text(ch),
                             # gpt-oss counts its hidden reasoning in max_tokens: leave room for it
                             "max_tokens": min(16000, 4000 + 150 * len(ch))})
                index[cid] = (st, ch)
        if not reqs:
            break
        if a.dry_run:
            r = reqs[0]
            print(r["static"], "=====", r["patient"], "=====", r["units"], sep="\n")
            print(f"\n--- dry run: {len(states)} patients, {sum(len(s.units) for s in states)} units, {len(reqs)} requests "
                  f"in round 1; static part {len(r['static'])} chars (~{len(r['static']) // 4} tokens), "
                  f"patient part ~{len(r['patient']) // 4} tokens, units part ~{len(r['units']) // 4} tokens")
            return None
        print(f"round {rnd + 1}: {len(reqs)} requests", flush=True)
        if rnd == 0:
            # the static part is shared by every request: write its cache once before the burst. A patient's
            # criteria part is written first too when several requests share it (--prewarm auto): otherwise every
            # parallel request writes its own copy at 1.25x (live run v13.4, cold cache: 7.7k tokens written per
            # request, $0.17 per patient instead of about $0.08), for about a second more per patient
            n_by_part = collections.Counter(r["patient"] for r in reqs)
            backend.prewarm([(r["static"], r["patient"] if (a.prewarm == "on" or (a.prewarm == "auto" and
                             n_by_part[r["patient"]] >= PREWARM_MIN)) else "") for r in reqs])
        results = backend.run(reqs)
        failed = sum(isinstance(results.get(r["custom_id"]), Exception) or results.get(r["custom_id"]) is None for r in reqs)
        if rnd == 0 and failed == len(reqs) and not backend.no_temperature:
            sys.exit("STOP: every request of round 1 failed, nothing is written. First error:\n  "
                     + (backend.errors[0] if backend.errors else "unknown"))
        if failed:
            print(f"  WARNING: {failed}/{len(reqs)} requests failed (retried next round). First error: "
                  f"{backend.errors[0] if backend.errors else '?'}", flush=True)
        for st in states:
            st.pending = []
        for cid, (st, ch) in index.items():
            res = results.get(cid)
            rec = {"custom_id": cid, "units": [u["uid"] for u in ch]}
            if isinstance(res, Exception) or res is None:
                backend.tracer.mark(cid, "request_failed", repr(res))
                st.checks["request_failed"] += 1
                rec["error"] = repr(res)
                st.pending += ch
                answers_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            rec["answer"] = res
            try:
                if degenerate(res, " ".join(u["text"] for u in ch)):
                    raise ValueError("degenerate answer (repeated spaces or '...')")
                got, drop, truncated = parse_answer(res)
                if truncated:
                    st.checks["truncated_answer_salvaged"] += 1
                    rec["truncated"] = True
                backend.tracer.mark(cid, "truncated" if truncated else "ok")
            except Exception as e:  # noqa: BLE001
                st.checks["bad_json"] += 1
                rec["error"] = f"bad json: {e}"
                backend.tracer.mark(cid, "bad_json", str(e))
                for u in ch:
                    u["problems"] = ["the previous answer was broken; answer again in plain JSON with ASCII spaces"]
                st.pending += ch
                answers_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            by_uid = {u["uid"]: u for u in ch}
            seen, problems = set(), {}
            for item in got:
                uid = item.get("u") if isinstance(item, dict) else None
                if isinstance(uid, str) and uid.lstrip("u").isdigit():
                    uid = int(uid.lstrip("u"))
                if uid not in by_uid:
                    st.checks["unknown_unit_id"] += 1
                    continue
                u = by_uid[uid]
                seen.add(uid)
                if not item.get("facts") and not u["rule_facts"]:
                    # {"u": N} or ok on a unit without any hint: the model found nothing there (Haiku's habit)
                    st.answers[uid] = ("llm", [])
                    st.checks["no_hint_bare_or_ok_as_drop"] += 1
                    continue
                if not item.get("ok") and not item.get("facts"):
                    # {"u": N} alone on a unit with a hint is not a valid answer: ask again
                    st.checks["bare_unit_answer"] += 1
                    seen.discard(uid)
                    continue
                if item.get("ok") is True and not item.get("facts") and ok_conflict(u):
                    st.checks["ok_rejected_negation"] += 1
                    item = {"facts": []}
                    probs_ok = ["the unit denies something ('no ...', 'without ...') but the hint has no false fact: "
                                "give the facts, with value false for each denied item"]
                elif item.get("ok") is True and not item.get("facts"):
                    if u["rule_facts"]:
                        u.pop("problems", None)
                        st.answers[uid] = ("ok", None)
                        continue
                    item = {"facts": []}
                    probs_ok = ["you answered ok but this unit has no hint; give the facts"]
                elif not item.get("facts"):
                    probs_ok = []
                else:
                    probs_ok = []
                clean, probs = [], list(probs_ok)
                for f in item.get("facts") or []:
                    cf, pr = check_fact(f, u["text"], concepts, st.p["as_of"])
                    probs += pr
                    if cf and (adv := behavior_advice(cf["concept"], u["text"], u["section"], [cf.get("quote"), cf.get("term")])):
                        cf.update(concept="treatment_plan", value=True, value_type="boolean", unit=None, term=adv,
                                  status="planned", fixed="behavior_advice")
                    if cf:
                        fx = cf.pop("fixed", None)
                        if fx:
                            st.checks[f"llm_fixed_{fx}"] += 1
                        clean.append(cf)
                if probs:
                    st.checks["invalid_unit"] += 1
                    u["problems"] = probs
                    problems[uid] = probs
                    st.pending.append(u)
                else:
                    u.pop("problems", None)
                    st.answers[uid] = ("llm", clean)
            dropped = {int(str(x).lstrip("u")) for x in (drop or []) if str(x).lstrip("u").isdigit()}
            for u in ch:
                if u["uid"] in seen:
                    continue
                if u["uid"] in dropped:
                    if rule_keeps(u):                              # safety net: keep what the rules are sure of
                        st.answers[u["uid"]] = ("kept", None)
                        st.checks["dropped_but_rule_kept"] += 1
                    else:
                        st.answers[u["uid"]] = ("llm", [])        # the model says: no fact here
                else:                                            # not covered (cut off, broken, forgotten): ask again
                    st.checks["unit_not_covered"] += 1
                    st.pending.append(u)
            rec["problems"] = problems
            answers_log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        answers_log.flush()
        if rnd < ROUNDS - 1:
            for st in states:
                if st.pending and len(st.pending) < a.min_retry:
                    # a few leftover units are not worth another full round of waiting: use the rule facts
                    st.checks["small_rest_to_rules"] += len(st.pending)
                    for u in st.pending:
                        st.answers[u["uid"]] = ("fallback", None)
                    st.pending = []
                if st.pending:
                    st.checks[f"retry_round_{rnd + 2}"] += len(st.pending)
    return states


def finalize(st):
    p = st.p
    for u in st.pending:                         # still invalid -> rule facts
        st.answers[u["uid"]] = ("fallback", None)
        st.checks["fallback_rules"] += 1
    evs = []
    for u in st.units:
        kind, facts = st.answers.get(u["uid"], ("fallback", None))
        d = u["doc"]
        _, how = R.resolve_date(u["text"], d.get("date"), p["as_of"])
        by = {"llm": "llm", "ok": "llm"}.get(kind, "rule")
        extra_rule = rule_missing(u, facts) if (kind == "llm" and facts) else []
        if facts is None:                        # rule facts: not sent, accepted hint ("ok"), kept, or fallback
            src = rule_keeps(u) if kind == "kept" else u["rule_facts"]
            facts = [{"concept": f["concept"], "value": f["value"], "unit": f["unit"], "value_type": f["value_type"],
                      "term": f["term"], "comparator": f["extra"].get("comparator"), "certainty": f.get("certainty"),
                      "subject": f.get("subject"), "status": f["extra"].get("status")} for f in src]
        facts = list(facts) + [{"concept": f["concept"], "value": f["value"], "unit": f["unit"],
                                "value_type": f["value_type"], "term": f["term"], "by": "rule",
                                "comparator": f["extra"].get("comparator"), "certainty": f.get("certainty"),
                                "subject": f.get("subject")} for f in extra_rule]
        if extra_rule:
            st.checks["rule_facts_added_to_llm"] += len(extra_rule)
        for f in facts:
            s, e = u["span"]
            if f.get("quote") and SPAN_MODE == "quote":
                off = u["text"].find(f["quote"])
                s, e = s + off, s + off + len(f["quote"])
            # a masked date ([**2-9**]) stays unknown even if the model reconstructed one (common format 8)
            obs = None if how in ("masked", "implausible") else (f.get("date") or d.get("date"))
            ev = {"evidence_id": None, "patient_id": p["patient_id"], "concept": f["concept"], "value": f["value"],
                  "unit": f.get("unit"), "value_type": f.get("value_type"), "observed_date": obs,
                  "certainty": f.get("certainty") or "confirmed", "subject": f.get("subject") or "patient",
                  "source": {"doc_id": d["doc_id"], "doc_type": d["type"], "author_role": d.get("author_role"),
                             "span": [s, e], "text": d["text"][s:e]},
                  "extracted_by": f.get("by", by)}
            if f.get("term"):
                ev["term"] = f["term"]
            detail = {k: f[k] for k in ("status", "start", "comparator", "unit_written", "quote") if f.get(k)}
            if detail:
                ev["detail"] = detail
            evs.append(ev)
    for ev in list(evs):                         # age from the date of birth, computed in code
        if ev["concept"] == "birth_date" and isinstance(ev["value"], str):
            try:
                dob = date.fromisoformat(ev["value"])
            except ValueError:
                continue
            evs.append({**ev, "concept": "age", "value": age_on(dob, date.fromisoformat(p["as_of"])), "unit": "years",
                        "value_type": "numeric", "observed_date": p["as_of"], "extracted_by": "rule",
                        "detail": {"derived_from": "birth_date"}})
    sx = sex_from_pronouns(p, evs)
    if sx:
        evs.append(sx)
    evs, sc = self_check(evs, p, p["as_of"])
    st.checks.update(sc)
    for i, ev in enumerate(evs, 1):
        ev["evidence_id"] = f"{p['patient_id']}-EV{i:03d}"
    kinds = collections.Counter(st.answers.get(u["uid"], ("fallback", None))[0] for u in st.units)
    kept = sum(1 for u in st.units if st.answers.get(u["uid"], ("", None))[1] or
               st.answers.get(u["uid"], ("", None))[0] in ("ok", "rule", "fallback"))
    st.checks.update({f"units_{k}": v for k, v in kinds.items() if k in ("ok",)})
    log = {"patient_id": p["patient_id"], "n_units": len(st.units), "units_with_facts": kept,
           "n_evidence": len(evs), "seconds": round(st.seconds, 1), "checks": dict(st.checks),
           "plan": {"candidate_trials": st.plan["candidate_trials"], "trigger_concepts": st.plan["trigger_concepts"]}
           if st.plan else None}
    return evs, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", required=True)
    ap.add_argument("--concepts", default=os.path.join(HERE, "concepts.json"))
    ap.add_argument("--trials")
    ap.add_argument("--criteria-ref")
    ap.add_argument("--k", type=int, default=20, help="candidate trials in the plan")
    ap.add_argument("--k-criteria", type=int, default=10, help="trials whose criteria go into the prompt (criteria mode)")
    ap.add_argument("--max-criteria", type=int, default=250, help="cap on criteria lines in the prompt")
    ap.add_argument("--relevance", choices=["all", "criteria"], default="criteria")
    ap.add_argument("--provider", choices=["openrouter", "anthropic", "anthropic-batch", "mock", "replay"], default="openrouter")
    ap.add_argument("--model")
    ap.add_argument("--chunk", type=int, default=15, help="units per request (retries use half, then a quarter)")
    ap.add_argument("--workers", type=int, default=16, help="parallel requests (not batch)")
    ap.add_argument("--min-retry", type=int, default=5,
                    help="re-ask only when at least this many units of a patient are left; fewer -> rule facts")
    ap.add_argument("--online", action="store_true",
                    help="one patient at a time, all its requests in parallel; logs seconds per patient (service latency)")
    ap.add_argument("--send-all", action="store_true", help="send rule-only units to the model too")
    ap.add_argument("--ttl", choices=["5m", "1h"], help="prompt cache TTL (default 5m direct calls, 1h batch)")
    ap.add_argument("--prewarm", choices=["auto", "on", "off"], default="auto",
                    help="anthropic: write each patient's criteria cache before its parallel requests (less cache "
                         "writing cost, about a second more per patient). auto: when the patient has "
                         f"{PREWARM_MIN}+ requests in round 1")
    ap.add_argument("--cache-dir", help="response cache (default <out>/cache); share it between runs to reuse answers")
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, help="only the first N patients (smoke test)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.relevance == "criteria" and not (a.trials and a.criteria_ref):
        ap.error("--relevance criteria needs --trials and --criteria-ref")
    a.model = a.model or DEFAULT_MODEL[a.provider]
    os.makedirs(a.out, exist_ok=True)
    concepts = load_concepts(a.concepts)                 # team list + Agent 2 overlay
    clist = concept_list(concepts)
    concept_text = "\n".join(f"{c['key']} | {c['type']} | {c.get('unit') or '-'} | {c['name']}" for c in clist)
    ex = Extractor(load_concepts(a.concepts))
    planner = None
    if a.trials and a.criteria_ref:
        L = lambda f: [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]  # noqa: E731
        planner = PL.Planner(L(a.trials), L(a.criteria_ref))
    patients = [json.loads(x) for x in open(a.patients, encoding="utf-8") if x.strip()][:a.limit]
    backend = None if a.dry_run else Backend(a.provider, a.model, a.cache_dir or os.path.join(a.out, "cache"),
                                             workers=a.workers, ttl=a.ttl)
    if backend is not None:
        run_id = os.environ.get("AGENT2_RUN_ID") or f"{os.path.basename(os.path.normpath(a.out))}-{time.strftime('%Y%m%d-%H%M%S')}"
        backend.tracer = Tracer.create(run_id, a.provider, backend.model or a.model, label=os.environ.get("AGENT2_TRACE_LABEL"),
                                       version=os.environ.get("AGENT2_VERSION", "v14.12"))
        if backend.tracer.enabled:
            print(f"  tracing: on (session {run_id}, content={backend.tracer.content})", flush=True)
    t_all = time.time()
    with open(os.path.join(a.out, "answers.jsonl"), "a", encoding="utf-8") as alog:
        if a.online and not a.dry_run:
            states = []
            for p in patients:
                t0 = time.time()
                st = run([p], ex, concepts, concept_text, planner, backend, a, alog)[0]
                st.seconds = time.time() - t0
                print(f"  {p['patient_id']}: {st.seconds:.1f} s", flush=True)
                states.append(st)
        else:
            states = run(patients, ex, concepts, concept_text, planner, backend, a, alog)
    if states is None:
        return
    wall = time.time() - t_all
    results = [finalize(st) for st in states]
    n = 0
    with open(os.path.join(a.out, "evidence.jsonl"), "w", encoding="utf-8") as fe, \
            open(os.path.join(a.out, "log.jsonl"), "w", encoding="utf-8") as fl:
        for evs, log in results:
            for ev in evs:
                fe.write(json.dumps(ev, ensure_ascii=False) + "\n")
            fl.write(json.dumps(log, ensure_ascii=False) + "\n")
            backend.tracer.patient_result(log)
            n += len(evs)
            print(f"  {log['patient_id']}: {log['n_evidence']} evidence from {log['units_with_facts']}/{log['n_units']} "
                  f"units, checks {log['checks']}")
    usage = dict(backend.report(), provider=a.provider, model=a.model, relevance=a.relevance,
                 patients=len(patients), evidence=n, wall_seconds=round(wall, 1), chunk=a.chunk, workers=a.workers,
                 online=a.online, reasoning_effort=os.environ.get("REASONING_EFFORT") if a.provider == "openrouter" else None)
    if a.online:
        secs = sorted(st.seconds for st in states)
        usage["patient_seconds"] = {"p50": round(secs[len(secs) // 2], 1),
                                    "p90": round(secs[min(len(secs) - 1, int(len(secs) * 0.9))], 1),
                                    "max": round(secs[-1], 1)}
    json.dump(usage, open(os.path.join(a.out, "usage.json"), "w"), indent=1)
    write_manifest(patients, os.path.join(a.out, "docs.jsonl"))
    print(f"{n} evidence ({n / max(1, len(patients)):.1f} per patient) -> {a.out}/evidence.jsonl")
    print("usage:", json.dumps(usage))
    backend.tracer.finish()


if __name__ == "__main__":
    main()
