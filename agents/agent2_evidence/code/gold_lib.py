"""Shared helpers for stage 2 (gold labeling). Common format v0.4."""
import json, os, re, sys
from datetime import date

STATUS_REASONS = {
    "PASS": {"VALID"},
    "FAIL": {"VIOLATED"},
    "UNKNOWN": {"MISSING", "EXPIRED", "UNSUPPORTED"},
    "CONFLICT": {"CONFLICT"},
}
DEFAULT_REASON = {"PASS": "VALID", "FAIL": "VIOLATED", "CONFLICT": "CONFLICT"}
ACTIONS = {"none", "patient_question", "med_record_check", "lab_check", "med_history_check",
           "clinician_confirmation", "new_test"}
NEEDS_EVIDENCE = {("PASS", "VALID"), ("FAIL", "VIOLATED"), ("CONFLICT", "CONFLICT"),
                  ("UNKNOWN", "EXPIRED"), ("UNKNOWN", "UNSUPPORTED")}
ACTIVE = {"RECRUITING", "NOT_YET_RECRUITING"}
KOREA = {"South Korea", "Korea, Republic of"}


def load_jsonl(paths):
    out = []
    for p in paths if isinstance(paths, (list, tuple)) else [paths]:
        with open(p, encoding="utf-8") as f:
            out.extend(json.loads(l) for l in f if l.strip())
    return out


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def load_id_maps(paths):
    m = {}
    for p in paths:
        m.update(json.load(open(p, encoding="utf-8")))
    return m


# ---------------------------------------------------------------- patient facts

def dob_sex(patient):
    for d in patient["documents"]:
        if d["type"] == "registration":
            m = re.search(r"DOB (\d{4}-\d{2}-\d{2})", d["text"])
            s = re.match(r"\s*(Male|Female)", d["text"])
            return (date.fromisoformat(m.group(1)) if m else None, s.group(1).upper() if s else None)
    return None, None


def age_years(dob, on):
    return (on - dob).days / 365.25


AGE_PATTERNS = [
    re.compile(r"\b(\d{1,3})\s*-?\s*(year|yr|month|week|day)s?\s*-?\s*old\b", re.I),
    re.compile(r"\b(\d{1,3})\s*(?:yo|y/o|y\.o\.)(?![a-z])", re.I),
    re.compile(r"\b(\d{1,3})\s?(?=[MF]\b)"),
    re.compile(r"\b(\d{1,3})\s*-?\s*(year)s?\s+(?=man|woman|male|female)", re.I),
]
UNIT_YEARS = {"year": 1, "yr": 1, "month": 1 / 12, "week": 1 / 52.18, "day": 1 / 365.25}
SEX_RE = re.compile(r"\b(?:\d{1,3}\s?(?:yo|y/o|y\.o\.)?\s?(?P<abbr>[MF])\b|(?P<f>woman|female|girl|lady|she|her)\b|(?P<m>man|male|boy|gentleman|he|his)\b)", re.I)


def text_age_sex(patient):
    """Fallback for records without a registration DOB (e.g. TREC topics): '45-year-old man', '74M', '55yo woman'."""
    text = " ".join([patient.get("summary") or ""] + [d["text"] for d in patient["documents"]])[:2000]
    age = None
    for pat in AGE_PATTERNS:
        m = pat.search(text)
        if m:
            unit = (m.group(2).lower() if m.lastindex and m.lastindex >= 2 and m.group(2) else "year")
            age = int(m.group(1)) * UNIT_YEARS.get(unit, 1)
            break
    sex = None
    m = SEX_RE.search(text)
    if m:
        if m.group("abbr"):
            sex = "MALE" if m.group("abbr") == "M" else "FEMALE"
        else:
            sex = "FEMALE" if m.group("f") else "MALE"
    return age, sex


def structured_check(patient, trial):
    """Age/sex from ⓪ (not always repeated in the criteria text). Returns list of problems."""
    dob, sex = dob_sex(patient)
    probs = []
    a = age_years(dob, date.fromisoformat(patient["as_of"])) if dob else None
    if a is None and sex is None:
        a, sex = text_age_sex(patient)
    if a is not None:
        if trial.get("min_age") is not None and a < trial["min_age"]:
            probs.append(f"age {a:.1f} < min_age {trial['min_age']}")
        if trial.get("max_age") is not None and a > trial["max_age"] + 1:   # '75 Years' = until 76th birthday
            probs.append(f"age {a:.1f} > max_age {trial['max_age']}")
    if sex and trial.get("sex") in ("MALE", "FEMALE") and trial["sex"] != sex:
        probs.append(f"sex {sex} != {trial['sex']}")
    return probs


# ---------------------------------------------------------------- evidence spans

SPACES = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]")
ELLIPSIS = re.compile(r"\s*(?:\.\.\.|\u2026)\s*")


def locate(doc_text, quote):
    """Exact match first, then whitespace/case-insensitive (non-breaking spaces count as spaces),
    then a quote shortened with '...' is matched as its pieces in order (span covers first to last piece).
    Returns (start, end) or None."""
    i = doc_text.find(quote)
    if i >= 0:
        return i, i + len(quote)
    q = SPACES.sub(" ", quote).strip()
    pieces = [p_ for p_ in ELLIPSIS.split(q) if len(p_.strip()) >= 3] or ([q] if not ELLIPSIS.fullmatch(q) else [])
    if not pieces:
        return None
    pat = r"[\s\S]{0,300}?".join(re.escape(re.sub(r"\s+", " ", p_.strip())).replace(r"\ ", r"\s+") for p_ in pieces)
    m = re.search(pat, SPACES.sub(" ", doc_text), re.I)
    return (m.start(), m.end()) if m else None


def build_gold_evidence(criteria_out, patient):
    """criteria_out[*]['evidence'] = [{'doc_id','quote'}] -> gold_evidence list + ids per criterion.
    Returns (gold_evidence, {criterion_id: [G..]}, problems)."""
    docs = {d["doc_id"]: d for d in patient["documents"]}
    gold, key2id, per_crit, probs = [], {}, {}, []
    for c in criteria_out:
        ids = []
        evs = c.get("evidence") or []
        for ev in (evs if isinstance(evs, list) else []):
            if not isinstance(ev, dict):
                probs.append(f"{c['criterion_id']}: evidence must be objects with doc_id and quote")
                continue
            d = docs.get(ev.get("doc_id"))
            if not d:
                probs.append(f"{c['criterion_id']}: unknown doc_id {ev.get('doc_id')}")
                continue
            span = locate(d["text"], ev.get("quote", ""))
            if not span:
                probs.append(f"{c['criterion_id']}: quote not found in {d['doc_id']}: {ev.get('quote', '')[:60]!r}")
                continue
            key = (d["doc_id"], span)
            if key not in key2id:
                gid = f"G{len(gold) + 1:02d}"
                key2id[key] = gid
                gold.append({"gold_ev_id": gid, "concept": None, "value": None, "unit": None,
                             "observed_date": d["date"], "doc_id": d["doc_id"], "span": list(span),
                             "text": d["text"][span[0]:span[1]]})
            ids.append(key2id[key])
        per_crit[c["criterion_id"]] = ids
    return gold, per_crit, probs


# ---------------------------------------------------------------- labels

def check_criterion(c):
    s, r, a = c.get("expected_status"), c.get("reason"), c.get("expected_action")
    probs = []
    bad = [k for k, v in (("expected_status", s), ("reason", r), ("expected_action", a)) if not isinstance(v, str)]
    if bad:   # e.g. the model answered a list such as ["PASS", "FAIL"]
        return [f"{c.get('criterion_id')}: {', '.join(bad)} must be a single string value"]
    if s not in STATUS_REASONS:
        probs.append(f"{c.get('criterion_id')}: bad status {s}")
    elif r not in STATUS_REASONS[s]:
        probs.append(f"{c.get('criterion_id')}: reason {r} not allowed with {s}")
    if a not in ACTIONS:
        probs.append(f"{c.get('criterion_id')}: bad action {a}")
    elif s in ("PASS", "FAIL") and a != "none":
        probs.append(f"{c.get('criterion_id')}: {s} must have action none")
    elif s in ("UNKNOWN", "CONFLICT") and a == "none":
        probs.append(f"{c.get('criterion_id')}: {s} needs an action other than none")
    return probs


def admin_ids(criteria_rows):
    """ids of criteria flagged "administrative": true (classify_admin.py)."""
    return frozenset(c["criterion_id"] for c in criteria_rows if c.get("administrative"))


def criterion_type(criterion_id):
    """'NCT..-I03' -> inclusion, '-E01' -> exclusion, '-U..' (no heading in the source) -> treated as inclusion."""
    m = re.search(r"-([IEU])\d", criterion_id or "")
    return "exclusion" if m and m.group(1) == "E" else "inclusion"


def trial_label(criteria, structured_problems=(), admin_ids=frozenset()):
    """Trial-level label from criterion-level judgments (common format v0.5 rule, aligned with TREC assessors):
    - any FAIL, or age/sex outside the trial range         -> ineligible
    - an inclusion criterion UNKNOWN or CONFLICT            -> potential
    - an exclusion criterion CONFLICT, or UNKNOWN with
      EXPIRED / UNSUPPORTED (there is a hint to follow up)  -> potential
    - otherwise                                             -> eligible
      (exclusion criteria UNKNOWN / MISSING = not mentioned anywhere in the record do not block eligibility;
       they stay UNKNOWN at criterion level for information acquisition)
    - administrative inclusion criteria (consent, willingness, contraception agreement, research samples;
      "administrative": true in criteria.jsonl, ids in admin_ids) that are UNKNOWN / MISSING do not block either
    criteria: gold criterion dicts with criterion_id, expected_status, reason."""
    if structured_problems or any(c["expected_status"] == "FAIL" for c in criteria):
        return "ineligible"
    for c in criteria:
        st, rs = c["expected_status"], c.get("reason")
        if criterion_type(c["criterion_id"]) == "inclusion":
            if st == "CONFLICT" or (st == "UNKNOWN" and not (rs == "MISSING" and c["criterion_id"] in admin_ids)):
                return "potential"
        elif st == "CONFLICT" or (st == "UNKNOWN" and rs != "MISSING"):
            return "potential"
    return "eligible"


def trial_label_strict(criteria, structured_problems=()):
    """Previous rule (any UNKNOWN -> potential). Kept for comparison."""
    st = [c["expected_status"] for c in criteria]
    if structured_problems or "FAIL" in st:
        return "ineligible"
    return "potential" if any(s in ("UNKNOWN", "CONFLICT") for s in st) else "eligible"


STALE_MONTHS = 12     # status not verified for longer: last within its label tier + briefing warning
DROP_MONTHS = 24      # longer: not recommended at all


def months_since_verified(trial, as_of):
    """Months between ⓪ status_verified ("YYYY-MM") and as_of; None if unknown."""
    v = trial.get("status_verified")
    if not v:
        return None
    y, m = map(int, v.split("-")[:2])
    d = date.fromisoformat(as_of)
    return (d.year - y) * 12 + (d.month - m)


def ranking(golds, trials_by_id):
    """Common format v0.5 6.4. Only eligible / potential trials, ordered by:
    label (eligible first) -> stale status (> 12 months unverified goes last within its label) -> fewer UNKNOWN/CONFLICT
    -> Korean recruiting site -> RECRUITING before NOT_YET -> newer status_verified.
    Trials unverified for > 24 months are left out."""
    def key(g):
        t = trials_by_id.get(g["trial_id"], {})
        n_open = sum(c["expected_status"] in ("UNKNOWN", "CONFLICT") for c in g["criteria"])
        kr = any(s.get("country") in KOREA and (s.get("status") in ACTIVE if s.get("status") else t.get("overall_status") in ACTIVE)
                 for s in t.get("sites", []))
        age = months_since_verified(t, g["as_of"])
        return (g["trial_label"] != "eligible", age is not None and age > STALE_MONTHS, n_open, not kr,
                t.get("overall_status") != "RECRUITING",
                "".join(chr(255 - ord(ch)) for ch in (t.get("status_verified") or "")))
    keep = [g for g in golds if g["trial_label"] in ("eligible", "potential")
            and not ((months_since_verified(trials_by_id.get(g["trial_id"], {}), g["as_of"]) or 0) > DROP_MONTHS)]
    return [g["trial_id"] for g in sorted(keep, key=key)]


def ranking_rows(golds, trials_by_id):
    by_p = {}
    for g in golds:
        by_p.setdefault(g["patient_id"], []).append(g)
    rows = []
    for pid, gs in by_p.items():
        src = "human_verified" if all(g["label_source"] == "human_verified" for g in gs) else "llm"
        rec = [g for g in gs if g["trial_label"] in ("eligible", "potential")]
        ages = {g["trial_id"]: months_since_verified(trials_by_id.get(g["trial_id"], {}), g["as_of"]) for g in rec}
        rows.append({"patient_id": pid, "as_of": gs[0]["as_of"], "ranking": ranking(gs, trials_by_id),
                     "stale_trials": sorted(t for t, m in ages.items() if m is not None and STALE_MONTHS < m <= DROP_MONTHS),
                     "dropped_stale_trials": sorted(t for t, m in ages.items() if m is not None and m > DROP_MONTHS),
                     "label_source": src})
    return rows


# ---------------------------------------------------------------- LLM

FATAL_ERRORS = {"AuthenticationError", "PermissionDeniedError", "NotFoundError"}
PACKAGES = {"anthropic": ("anthropic", "ANTHROPIC_API_KEY"), "openai": ("openai", "OPENAI_API_KEY"),
            "openrouter": ("openai", "OPENROUTER_API_KEY")}
OPENROUTER_URL = "https://openrouter.ai/api/v1"
TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "150"))   # socket timeout (resets whenever the server sends anything)
# Hard wall-clock limit per request. OpenRouter keeps idle connections alive by sending whitespace, so the socket
# timeout alone never fires on a request that hangs; this deadline always does.
DEADLINE = float(os.environ.get("LLM_DEADLINE", "240"))


def preflight(provider):
    module, key = PACKAGES[provider]
    try:
        __import__(module)
    except ImportError:
        sys.exit(f"STOP: the '{module}' package is not installed for this Python ({sys.executable}).\n"
                 f"Install it with:  {sys.executable} -m pip install {module}")
    if not os.environ.get(key):
        sys.exit(f"STOP: environment variable {key} is not set. Put {key}=... in .env (see .env.example) or export it.")


def _call_llm(provider, model, prompt, temperature, max_tokens=32000):
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(timeout=TIMEOUT, max_retries=0)
        kw = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
        try:
            r = client.messages.create(temperature=temperature, **kw)
        except (TypeError, anthropic.BadRequestError) as e:
            if "temperature" not in str(e).lower():
                raise
            r = client.messages.create(**kw)
        text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        return text, {"input_tokens": r.usage.input_tokens, "output_tokens": r.usage.output_tokens}
    if provider in ("openai", "openrouter"):
        from openai import OpenAI
        if provider == "openrouter":
            client = OpenAI(base_url=OPENROUTER_URL, api_key=os.environ["OPENROUTER_API_KEY"], timeout=TIMEOUT, max_retries=0)
            # usage.include -> OpenRouter returns the real charged cost; reasoning effort for gpt-oss style models
            extra = {"usage": {"include": True}, "reasoning": {"effort": os.environ.get("REASONING_EFFORT", "medium")}}
            # default: OpenRouter's own routing (cheap providers first). OPENROUTER_SORT=throughput|latency|price to force one
            if os.environ.get("OPENROUTER_SORT"):
                extra["provider"] = {"sort": os.environ["OPENROUTER_SORT"]}
        else:
            client, extra = OpenAI(timeout=TIMEOUT, max_retries=0), {}
        kw = dict(model=model, messages=[{"role": "user", "content": prompt}], max_tokens=max_tokens,
                  response_format={"type": "json_object"}, temperature=temperature, extra_body=extra or None)
        for _ in range(3):   # drop options the model/provider rejects, one at a time
            try:
                r = client.chat.completions.create(**{k: v for k, v in kw.items() if v is not None})
                break
            except Exception as e:
                msg = str(e).lower()
                dropped = next((k for k in ("response_format", "temperature", "max_tokens") if k in msg and k in kw), None)
                if not dropped or type(e).__name__ in FATAL_ERRORS:
                    raise
                kw.pop(dropped)
        u = r.usage
        extra_u = getattr(u, "model_extra", None) or {}
        details = getattr(u, "completion_tokens_details", None)
        usage = {"input_tokens": u.prompt_tokens, "output_tokens": u.completion_tokens,
                 "reasoning_tokens": getattr(details, "reasoning_tokens", 0) or 0,
                 "cost": extra_u.get("cost")}
        choice = r.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            raise RuntimeError(f"empty answer (finish_reason={choice.finish_reason}); "
                               "reasoning may have used up max_tokens")
        return text, usage
    raise ValueError(f"unknown provider {provider}")


def parse_json(text):
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text[text.find("{"):text.rfind("}") + 1])


class LLMDeadlineError(Exception):
    """The request did not finish within LLM_DEADLINE seconds (it is abandoned and counted as a failed attempt)."""


import threading as _threading  # noqa: E402


def call_llm(provider, model, prompt, temperature, max_tokens=32000):
    """_call_llm with a hard wall-clock deadline. A request that runs past it is abandoned in a daemon thread
    (its result is ignored) and LLMDeadlineError is raised, so one hung connection cannot stall a run."""
    box = {}

    def run():
        try:
            box["ok"] = _call_llm(provider, model, prompt, temperature, max_tokens)
        except BaseException as e:  # noqa: BLE001
            box["err"] = e

    t = _threading.Thread(target=run, daemon=True)
    t.start()
    t.join(DEADLINE)
    if t.is_alive():
        raise LLMDeadlineError(f"no answer within {DEADLINE:.0f}s (request abandoned)")
    if "err" in box:
        raise box["err"]
    return box["ok"]
