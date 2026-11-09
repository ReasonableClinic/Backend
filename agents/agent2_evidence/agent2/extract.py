#!/usr/bin/env python3
"""Agent 2 (Evidence Extraction), stage 1: rule extractor with a provisional concept list.

Pipeline per patient:  plan (which concepts to look for) -> segment documents into fact units -> extract
(rules: numeric labs/vitals, serology, demographics, behaviors, conditions, drugs, procedures, oncology markers,
with negation / family / certainty / plan cues) -> dates and units -> self-check -> ③ objects.

Usage (package root):
  python3 agent2/extract.py --patients data/dev/input/patients.jsonl --out runs/dev_v1
Outputs: <out>/evidence.jsonl (③, one per line), <out>/log.jsonl (plan + per-patient self-check counts).
"""
import argparse, collections, json, os, re, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rules as R  # noqa: E402
from segment import units as segment_units  # noqa: E402
import plan as PL  # noqa: E402

DEFAULT_PLAN = ["demographics", "vitals", "labs", "performance_status", "pregnancy", "contraception", "smoking",
                "alcohol", "substance_use", "allergy", "diagnosis", "medication", "procedure", "oncology",
                "family_history", "treatment_plan"]
GENERIC = {"symptom_finding", "diagnosis", "medication", "procedure", "lab_other", "treatment_plan", "social_history"}
CONFIRMED_DOCS = {"lab_result", "imaging_report", "pathology_report"}
RANGES = {"hemoglobin": (2, 25), "platelet_count": (1, 2000), "wbc": (0.1, 500), "anc": (0, 100),
          "creatinine": (0.1, 20), "egfr": (1, 200), "bilirubin_total": (0, 50), "ast": (1, 10000),
          "alt": (1, 10000), "albumin": (0.5, 7), "inr": (0.5, 15), "hba1c": (3, 20), "glucose": (10, 2000),
          "potassium": (1, 10), "sodium": (90, 200), "body_weight": (1, 400), "body_height": (40, 250),
          "bmi": (8, 90), "heart_rate": (20, 250), "body_temperature": (30, 45), "spo2": (40, 100),
          "lvef": (5, 90), "qtc": (250, 700)}


AGE_RE = re.compile(r"(?<![\d.,\-–/])\b(?P<n2>\d{1,3})\s?(?-i:(?P<sx>[MF]))\b(?!\s*(?:walk|run|distance|/))|\b(?P<n>\d{1,3})\s*-?\s*(?P<u>years?|yrs?|y|months?|mos?|weeks?|wks?|days?)"
                    r"(?:\s*-?\s*(?:old|/o|o)\b|(?=\s+(?:man|woman|male|female|boy|girl|gentleman|lady)\b))", re.I)
# a sex word shortly after the age, allowing a few descriptors: "60-year-old Spanish man", "3-day-old Asian female infant"
SEX_AFTER = re.compile(r"(?:\s+(?:[A-Z][\w-]*|obese|healthy|postmenopausal|pregnant|previously|otherwise|white|black|"
                       r"african-american|g\d+p\d+))*\s+(man|woman|male|female|gentleman|lady|boy|girl|M|F)\b", re.I)
REPORTER_RE = re.compile(r"\b(?:mother|father|wife|husband|spouse|parents?|daughter|son|sister|brother|caregiver)\s+"
                         r"(?:notes?|reports?|says|states|present|corroborates|checks|has been checking|is concerned|"
                         r"brought|accompanies|describes)\b", re.I)
ORDER_RE = re.compile(r"(?:start|started|initiate|initiated|begin|began|commence|commenced)\s+(?!to\b)", re.I)

# scheduling / administrative sentences and bare headings: not facts about the patient
NOISE_RE = re.compile(r"^(?:follow[- ]?up|f/u|return|rtc|next visit|routine labs|labs? (?:drawn|ordered|reviewed)|"
                      r"(?-i:[A-Z][A-Z &/-]+)(?:\s*\([^)]*\))?\.?$|history and physical|data reviewed|plan$|signed|dictated)|"
                      r"\b(?:ordered|will review|to review|scheduled for|recheck in|repeat \w+ in)\b", re.I)


def load_concepts(path, overlay=None):
    """The team's concept list (concepts.json) with Agent 2's overlay (concepts_agent2.json next to it, if any):
    extra or dropped aliases and keys Agent 2 never emits. Keys are never renamed."""
    concepts = {c["key"]: dict(c) for c in json.load(open(path, encoding="utf-8"))}
    overlay = overlay or os.path.join(os.path.dirname(os.path.abspath(path)), "concepts_agent2.json")
    if os.path.exists(overlay):
        ov = json.load(open(overlay, encoding="utf-8"))
        for k, drop in ov.get("drop_aliases", {}).items():
            if k in concepts:
                concepts[k]["aliases"] = [a for a in concepts[k].get("aliases") or [] if a not in drop]
        for k, add in ov.get("add_aliases", {}).items():
            if k in concepts:
                concepts[k]["aliases"] = list(dict.fromkeys((concepts[k].get("aliases") or []) + add))
        for k, alt in ov.get("add_alt_units", {}).items():
            if k in concepts:
                concepts[k]["alt_units"] = {**alt, **(concepts[k].get("alt_units") or {})}
        for k, lim in ov.get("ratio_below", {}).items():
            if k in concepts:
                concepts[k]["ratio_below"] = lim
        for k in ov.get("skip", []):
            concepts.pop(k, None)
        for k, to in ov.get("emit_as", {}).items():          # an answer under k is stored under `to`
            if to in concepts:
                concepts[k] = concepts[to]
    return concepts


def concept_list(concepts):
    """Distinct concepts for the prompt (keys written under another key appear once)."""
    return list({c["key"]: c for c in concepts.values()}.values())


def age_on(dob, on):
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


_DIAG_HEAD = re.compile(r"syndrome|disease|disorder|failure|insufficiency|infection|infarction|deficiency|injury|"
                        r"remission|relapse|progression|lesions?|mass|nodules?|cancer|carcinoma|tumou?r|fibrosis|"
                        r"arthritis|dermatitis|hepatitis|nephritis|nephropathy|neuropathy|retinopathy|cardiomyopathy|"
                        r"an(?:a)?emia|fibrillation|pneumonia|sinusitis|pancreatitis|ulcer|degeneration|detachment",
                        re.I)
_DIAG_STOP = re.compile(r"(?:no|not|without|denies|of|on|with|and|or|the|a|an|in|to|for|from|presumed|possible|probable|"
                        r"likely|suspected|suspect|rule|out|history|hx|pmh|dx|known|new|prior|previous|recent|status|"
                        r"post|s/p|diagnosis|diagnosed|is|was|has|had|by|at|as|per|since|cm|mm|x)$", re.I)
_NOT_DIAG = re.compile(r"diagnos\w*|prognos\w*", re.I)


def diag_phrases(t):
    """(start, term) per condition in t, with the words that name it ("minimal change disease", "Graves disease",
    "nephrotic syndrome", "chronic kidney disease"), not the bare lexicon word ("disease", "syndrome")."""
    spans = []
    for m in R.DIAG_RE.finditer(t):
        if _NOT_DIAG.fullmatch(m.group(0)):
            continue                                       # "Diagnosis: ..." is a label, not a condition
        if re.match(r"\s+(?:symptoms?|signs?|features|tendenc\w+|mood)\b", t[m.end():], re.I) and re.fullmatch(
                r"\w+(?:ive|ic|al|ous|ary)", m.group(0), re.I):
            continue                                       # "mild depressive symptoms (GDS 6)": a finding, not a diagnosis
        s, e = m.start(), m.end()
        if _DIAG_HEAD.fullmatch(m.group(0)):               # take up to 3 naming words before the head
            for _ in range(3):
                w = re.search(r"([A-Za-z][\w'/-]*)\s+$", t[:s])
                if not w or _DIAG_STOP.match(w.group(1)) or re.search(r"[,;:(.]\s*$", t[:w.start(1)][-2:] or "x"):
                    if w and not _DIAG_STOP.match(w.group(1)):
                        s = w.start(1)
                    break
                s = w.start(1)
        spans.append((s, e))
    spans.sort(key=lambda x: (x[0], -x[1]))
    out = []
    for s, e in spans:                                     # a word inside a longer name is that name
        if out and s >= out[-1][0] and e <= out[-1][1]:
            continue
        if out and s <= out[-1][0] and e >= out[-1][1]:
            out[-1] = (s, e)
            continue
        out.append((s, e))
    return [(s, t[s:e]) for s, e in out]


THERAPY_DENIED = re.compile(r"\b(?:no|denies|denied|without|never (?:had|received|been on|on))\b\s+(?:any\s+)?(?P<what>(?:(?:prior|previous|"
                            r"systemic|targeted|adjuvant|neoadjuvant|cytotoxic|anti-?cancer|local|lipid-lowering|"
                            r"antihypertensive|biologic|antiviral|antithyroid|hormonal|immunosuppressive)\s+)*(?:therapy|treatment|"
                            r"chemotherapy|chemo|immunotherapy|radiotherapy|radiation(?: therapy)?|surgery))\b", re.I)


def denied_items(neg_part, covered=()):
    """'no new flashes or floaters since surgery.' -> ['new flashes', 'floaters'] (up to the time anchor). Only a
    plain list denial ("no / denies / without X or Y"), not a verb denial ("not indicated", "not documented")."""
    m = re.match(r"\s*(?:no|denies|denied|without)\s+", neg_part or "", re.I)
    if not m:
        return []
    body = re.split(r"\b(?:since|after|before|until|following|for|because|due to|while|with|on|in)\b|[.;:()]",
                    neg_part[m.end():], maxsplit=1)[0]
    items = [x.strip(" ,.") for x in re.split(r",|\bor\b|\band\b|\bnor\b", body)]
    cov = [c.lower() for c in covered if c]
    out = []
    for x in items:
        if R.POS_HEAD.match(x):
            break                                         # "no hematuria, normal C3, normal renal function"
        if re.fullmatch(r"[A-Za-z][A-Za-z -]{2,38}", x) and not R.NEG_CUE.search(x) and not any(
                x.lower() in c or c in x.lower() for c in cov):
            out.append(x)
    return out[:4]


BEHAVIORS = ("smoking", "alcohol", "substance_use")
_BEHAV_WORD = {"smoking": r"smok|tobacco|cigar|vap", "alcohol": r"alcohol|etoh|drink", "substance_use": r"drug|substance"}


def behavior_advice(concept, t, section, where=None):
    """Advice about a behavior ("no smoking", "avoid alcohol", "smoking cessation advised", "outpatient alcohol program")
    as a plan term, or None when the unit states the patient's own habit ("No smoking." in the social history).
    `where`: the fact's own term or quote; when it is found elsewhere in the unit ("Alcohol use disorder: abstinent
    since 09-25, ..., outpatient alcohol program arranged"), the fact is that other statement and stays."""
    if concept not in BEHAVIORS:
        return None
    word = _BEHAV_WORD[concept]
    hits = [m for m in R.BEHAV_SERVICE_RE.finditer(t) if re.search(word, m.group(0), re.I)]
    advice_ctx = section == "plan" or bool(R.ADVICE_RE.search(t)) or bool(R.PLAN_RE.search(t))
    if advice_ctx and section not in ("social", "family"):
        hits += [m for m in R.BEHAV_ADVICE_RE.finditer(t) if re.search(word, m.group(0), re.I)]
    if not hits:
        return None
    for w in [x for x in (where or []) if isinstance(x, str) and len(x) > 2]:
        i = t.lower().find(w.lower())
        if i >= 0:
            m = next((m for m in hits if m.start() < i + len(w) and i < m.end()), None)
            return m.group(0) if m else None
    return hits[0].group(0)


def annotate(facts, t, ctx, doc, section):
    """Rule-level attributes for the facts of one unit, in place: certainty, subject, and planned / declined
    treatments turned into treatment_plan. Shared by the rule pipeline and the LLM layer (hints, accepted hints,
    fallbacks), so both read the cues the same way."""
    family = doc["type"] != "registration" and (
        section == "family" or bool(R.FAMILY_RE.search(ctx) and not REPORTER_RE.search(ctx))
        or bool(R.OTHER_PERSON_RE.search(ctx)))
    sus_cues = [m.start() for m in R.SUSPECT_RE.finditer(t)]
    order = bool(ORDER_RE.match(R.LABEL_RE.sub("", t, count=1)))       # "Start prednisolone ..." = given
    planned = not order and (bool(R.PLAN_RE.search(t)) or section == "plan" and not re.search(
        r"\b(?:on|continue|continuing|since|started|taking|received|completed|underwent|had|s/p|status post|"
        r"done|performed|given)\b", t, re.I))
    declined = bool(R.DECLINED_RE.search(t))
    reported = doc.get("author_role") == "patient" or doc["type"] == "patient_interview" or bool(R.REPORTED_RE.search(ctx))
    for f in facts:
        if (adv := behavior_advice(f["concept"], t, section, [f.get("term")])):
            f.update(concept="treatment_plan", value=True, value_type="boolean", term=adv)
            f.setdefault("extra", {})["status"] = "planned"
        if f["concept"] in ("medication", "procedure") and (planned or declined) and f["value"] is True:
            f["concept"] = "treatment_plan"
            f["extra"]["status"] = "declined" if declined else "planned"
        # suspicion only for conditions whose term comes after the cue in the same clause
        # ("acute pancreatitis, likely alcohol-related": pancreatitis is confirmed)
        tpos = f.get("pos")
        suspected = f["concept"] in ("diagnosis", "symptom_finding") and any(
            c <= (tpos if tpos is not None else len(t)) and not re.search(r"[;.]", t[c:tpos or c]) for c in sus_cues)
        f["certainty"] = ("suspected" if suspected else "confirmed" if doc["type"] in CONFIRMED_DOCS
                          else "reported" if reported else "confirmed")
        f["subject"] = ("family" if family and f["concept"] in ("diagnosis", "symptom_finding", "cancer_stage", "pregnancy",
                                                               "medication", "procedure") else "patient")
    return facts


def sex_from_pronouns(p, evs):
    """When no evidence states the sex, infer it from pronouns if they clearly agree ('A 57-year old farmer ...
    He experiences ...'). One evidence on the first pronoun, marked detail.derived_from = 'pronouns'."""
    if any(e["concept"] == "sex" for e in evs):
        return None
    counts, first = {"male": 0, "female": 0}, {}
    for d in p["documents"]:
        for m in re.finditer(r"\b(he|him|his|she|her|hers)\b", d["text"], re.I):
            # skip pronouns about a relative or another person in the same sentence
            sent_start = max(d["text"].rfind(". ", 0, m.start()), d["text"].rfind("\n", 0, m.start())) + 1
            if R.FAMILY_RE.search(d["text"][sent_start:m.end()]) or REPORTER_RE.search(d["text"][sent_start:m.end() + 30]):
                continue
            sx = "male" if m.group(1).lower() in ("he", "him", "his") else "female"
            counts[sx] += 1
            first.setdefault(sx, (d, m))
    sx = max(counts, key=counts.get)
    other = "female" if sx == "male" else "male"
    if counts[sx] < 2 or counts[sx] < 3 * counts[other]:
        return None
    d, m = first[sx]
    return {"evidence_id": None, "patient_id": p["patient_id"], "concept": "sex", "value": sx, "unit": None,
            "value_type": "categorical", "observed_date": d.get("date"), "certainty": "confirmed", "subject": "patient",
            "source": {"doc_id": d["doc_id"], "doc_type": d["type"], "author_role": d.get("author_role"),
                       "span": [m.start(), m.end()], "text": d["text"][m.start():m.end()]},
            "extracted_by": "rule", "detail": {"derived_from": "pronouns", "pronoun_counts": counts}}


class Extractor:
    def __init__(self, concepts):
        self.concepts = concepts
        # values only for concepts with a unit or an old free-value key; biomarker / visual acuity are words
        self.numeric = R.build_numeric_matchers(c for c in concept_list(concepts)
                                                if c["key"] not in ("biomarker", "islet_autoantibodies", "visual_acuity",
                                                                    "hiv", "hepatitis_b", "hepatitis_c"))
        global LAB_MATCHERS, LAB_CONCEPTS
        LAB_MATCHERS, LAB_CONCEPTS = self.numeric, concepts

    # ---------------------------------------------------------- facts from one unit
    def unit_facts(self, t, doc, section):
        """List of fact dicts (concept, value, value_type, unit, term, extra) for unit text t."""
        facts = []
        dtype = doc["type"]

        def add(concept, value, vtype, unit=None, term=None, **extra):
            facts.append({"concept": concept, "value": value, "value_type": vtype, "unit": unit,
                          "term": term, "extra": extra})

        if dtype == "registration":
            if m := re.search(r"\bDOB\s*:?\s*(\d{4}-\d{2}-\d{2})", t):
                add("birth_date", m.group(1), "date")
                self._dob = date.fromisoformat(m.group(1))
            if m := re.match(r"\s*(Male|Female|M|F)\b", t):
                add("sex", "male" if m.group(1)[0] == "M" else "female", "categorical")
            if m := re.search(r"Nationality\s*:?\s*([A-Z][\w ,.]+?)\s*\.?$", t):
                add("nationality", m.group(1), "categorical")
            if not facts:
                add("social_history", True, "boolean", term=t[:60])   # occupation, guardian, living situation
            return facts

        # age / sex written in notes: '45M', '58-year-old man', '55yo woman', '70 y/o', '3-day-old female infant'
        if m := AGE_RE.search(t):
            n = int(m.group("n") or m.group("n2"))
            unit = (m.group("u") or "y").lower()
            years = n / 365.25 if unit.startswith("d") else n / 52.18 if unit.startswith("w") else \
                n / 12 if unit.startswith("mo") else n
            if years < 120:
                add("age", round(years, 2) if years < 2 else n, "numeric", "years")
                sx = m.group("sx") or (SEX_AFTER.match(t, m.end()) or [None, None])[1]
                if sx:
                    add("sex", "male" if re.match(r"(?:M|man|male|gentleman|boy)\b", sx, re.I) else "female",
                        "categorical")

        # numeric labs / vitals / measurements
        for key, val, unit, extra in R.numeric_values(t, self.numeric):
            c = self.concepts[key]
            v2, u2, ok = R.convert(val, unit, c) if isinstance(val, (int, float)) else (val, unit or c.get("unit"), True)
            if not ok and c.get("type") == "lab" and (unit or "").lower() in DOSE_UNITS:
                continue                                  # "calcium carbonate 500 mg": a dose, not a lab value
            if not ok:
                extra["unit_written"] = unit
            for rk in ("ref_low", "ref_high"):            # reference limits in the same unit as the value
                if rk in extra:
                    extra[rk] = R.convert(extra[rk], unit, c)[0] if ok else extra[rk]
            add(key, v2, "numeric" if isinstance(v2, (int, float)) else "categorical", u2, **extra)
            if key == "blood_pressure" and "systolic" in extra:   # ①-b criteria ask for systolic_bp / diastolic_bp
                for k2, part in (("systolic_bp", "systolic"), ("diastolic_bp", "diastolic")):
                    if k2 in self.concepts:
                        add(k2, int(extra[part]) if float(extra[part]).is_integer() else extra[part], "numeric", "mmHg")
        if m := R.ECOG_RE.search(t):
            add("ecog", int(m.group(1)), "numeric")
        if m := R.KPS_RE.search(t):
            add("karnofsky", int(m.group(1)), "numeric", "%")
        # ①-b scales written with a class letter or roman numeral, and facts criteria ask for under another key
        if "nyha_class" in self.concepts and (m := R.NYHA_RE.search(t)):
            add("nyha_class", {"I": 1, "II": 2, "III": 3, "IV": 4}.get(m.group(1), None) or int(m.group(1)), "numeric",
                self.concepts["nyha_class"].get("unit"), written=m.group(0))
        if "child_pugh" in self.concepts and (m := R.CHILD_PUGH_RE.search(t)):
            if m.group(2):
                add("child_pugh", int(m.group(2)), "numeric", self.concepts["child_pugh"].get("unit"),
                    child_pugh_class=m.group(1).upper())
            else:
                add("child_pugh", "class " + m.group(1).upper(), "categorical", None)
        if "proptosis_exophthalmometry" in self.concepts and (m := R.HERTEL_RE.search(t)):
            vals = [float(x) for x in m.groups() if x]
            add("proptosis_exophthalmometry", max(vals), "numeric", "mm", written=m.group(0))
        if "ctsi" in self.concepts and (m := R.CTSI_RE.search(t)):
            add("ctsi", int(m.group(1)), "numeric", self.concepts["ctsi"].get("unit"))
        if m := R.VIRAL_UNDETECTED_RE.search(t):
            key = ("hbv_dna" if re.match(r"HBV", m.group(1), re.I) else "hiv_viral_load" if re.match(r"HIV", m.group(1), re.I)
                   else None)
            if key in self.concepts:
                if m.group(2):
                    add(key, float(m.group(2)) if "." in m.group(2) else int(m.group(2)), "numeric",
                        self.concepts[key].get("unit"), comparator="<")
                else:
                    add(key, "not detected", "categorical", None)
        if "menopausal_status" in self.concepts and (m := R.MENOPAUSE_RE.search(t)) and not R.term_negated(t, m.start()):
            st = "premenopausal" if re.match(r"pre", m.group(1), re.I) else \
                "perimenopausal" if re.match(r"peri", m.group(1), re.I) else "postmenopausal"
            add("menopausal_status", st, "categorical", None)
            if st == "postmenopausal" and "childbearing_potential" in self.concepts:
                add("childbearing_potential", False, "boolean", None, derived_from="menopausal_status")

        # qualitative serology / tests
        for m in R.SEROLOGY_RE.finditer(t):
            name, res = m.group("name"), m.group("res").lower()
            if re.search(r"DNA|RNA|viral load", name, re.I):
                continue          # "HBV DNA not detected" is a suppressed viral load, not "no hepatitis B"
            key = ("hepatitis_b" if re.search(r"HB|hepatitis B", name, re.I)
                   else "hepatitis_c" if re.search(r"HCV|hepatitis C", name, re.I)
                   else "hiv" if re.search(r"HIV", name, re.I) else "hcg" if re.search(r"hCG|pregnancy", name, re.I)
                   else "lab_other")
            if key == "lab_other" and dtype not in CONFIRMED_DOCS and not re.search(r"culture|PCR|ANA|TRAb|C3|ketones", name):
                continue
            pos = res in ("reactive", "positive", "detected") or res.endswith("+")
            add(key, pos if res not in ("trace", "indeterminate") else res, "boolean" if res not in ("trace", "indeterminate") else "categorical",
                term=name)
            if key == "hcg" and res not in ("trace", "indeterminate") and not any(f["concept"] == "pregnancy" for f in facts):
                add("pregnancy", pos, "boolean", term="pregnancy test", derived_from="hcg")   # criteria ask "pregnancy"

        # behaviors, allergy, pregnancy, contraception
        neg = bool(R.NEG_START.search(t)) or bool(re.search(r"\b(?:never|non-?)[- ]?smok|\b0 pack", t, re.I))
        # behaviors: the denial is read per term ("She does not smoke, drink alcohol, or use illicit drugs")
        past_habit = re.search(r"\b(?:ex-?\s?|former(?:ly)?|quit|abstinent|stopped|gave up|used to)\b", t, re.I)
        if m := R.SMOKE_RE.search(t):
            add("smoking", not (neg or R.term_negated(t, m.start())), "boolean", term=m.group(0))
            if past_habit and facts[-1]["value"]:
                facts[-1]["extra"]["status"] = "past"     # "Remains abstinent from smoking since 2020": a former smoker
        if (m := R.ALC_RE.search(t)) and section != "family":
            add("alcohol", not (R.term_negated(t, m.start()) or bool(re.search(
                r"\b(?:no|denies|never|none)\b[^.;]{0,15}\b(?:alcohol|drink)|\balcohol\b[^.;]{0,10}\bnone\b", t, re.I))),
                "boolean", term="alcohol")
            if past_habit and facts[-1]["value"]:
                facts[-1]["extra"]["status"] = "past"     # "abstinent since 09-25"
        if m := R.SUBST_RE.search(t):
            add("substance_use", not (neg or R.term_negated(t, m.start())), "boolean", term=m.group(0))
        if R.ALLERGY_RE.search(t) or section == "allergy":
            add("allergy", not bool(re.search(r"NKDA|NKA|\bno\b[^.;]{0,20}allerg|\bnone\b", t, re.I)), "boolean",
                term=(R.ALLERGY_RE.search(t) or re.search(r".{1,40}", t)).group(0))
        if R.PREG_RE.search(t):
            add("pregnancy", not bool(re.search(r"\bnot\b[^.;]{0,10}pregnan|\bnon-?pregnan|\bno\b[^.;]{0,10}pregnan|"
                                               r"hCG negative|pregnancy test negative|not (?:breast|lactat)", t, re.I)),
                "boolean", term=R.PREG_RE.search(t).group(0))
        if (m := R.CONTRA_RE.search(t)) and not (m.group(0).lower().startswith("abstinen") and re.search(
                r"abstinen\w*\s+(?:from\s+)?(?:smok|alcohol|drink|tobacco|substance|drug)|(?:alcohol|smok\w*|drink\w*)"
                r"[^.;]{0,30}abstinen|abstinent since", t, re.I)):
            add("contraception", not neg, "boolean", term=R.CONTRA_RE.search(t).group(0))

        # oncology
        if (m := R.STAGE_RE.search(t)) and not re.search(r"Child[- ]Pugh|NYHA|Mayo", m.group(0), re.I):
            add("cancer_stage", m.group(0), "categorical")
        if (mz := measurable(t)) and dtype not in ("registration", "lab_result"):
            add("measurable_disease", True, "boolean", term=f"{mz[1]} {mz[0]:g} mm", size_mm=mz[0])
        if R.METS_RE.search(t):
            add("metastasis", not neg, "boolean", term=R.METS_RE.search(t).group(0))
        if (m := R.MARKER_RE.search(t)) and (dtype == "pathology_report" or re.search(
                r"positive|negative|wild|mutat|fusion|amplif|\d+%|[0-3]\+|high|low|detected|TPS|CPS", t, re.I)):
            add(self.concepts.get("tumor_marker", {}).get("key", "tumor_marker"), True, "categorical", term=m.group(0))

        # drugs, procedures, diagnoses
        drug = R.DRUG_RE.search(t)
        if not drug and dtype != "registration":
            # an order names the drug right after the verb even when the lexicon does not know it
            drug = re.match(r"\s*(?:[A-Za-z /]+:\s*)?(?:start|started|initiate|initiated|begin|commence)\s+"
                            r"([A-Za-z][a-z]{3,})", t, re.I)
            if drug and re.match(r"(?:with|the|on|to|and|a)\b", drug.group(1), re.I):
                drug = None
        dose = R.DOSE_RE.search(t)
        proc = R.PROC_RE.search(t)
        diag = R.DIAG_RE.search(t)
        med_heading = bool(re.fullmatch(r"(?:recently |previously )?(?:stopped|discontinued|held|current|home|active|"
                                        r"past|prior|other)(?: (?:medications?|meds|drugs))?\s*:?|(?:recently |previously )?"
                                        r"(?:stopped|discontinued)|(?:current |home |active )?(?:medications?|meds)\s*:?",
                                        t.strip(), re.I))   # "Recently stopped" / "Current medications:" is a heading
        if not med_heading and (drug or (dose and section == "meds") or dtype == "medication_record"
                                or (section == "meds" and t.strip())):
            term = drug.group(drug.lastindex or 0) if drug else t.split()[0] if t.split() else t
            if drug:
                med_neg = R.term_negated(t, drug.start(drug.lastindex or 0))
            else:                                 # "Recently stopped: none." / "No OTC supplements"
                pos_part, neg_part = R.clause_polarity(t)
                med_neg = neg or bool(neg_part and not pos_part)
            add("medication", not med_neg, "boolean", term=term)
            facts[-1]["lexicon"] = bool(drug) or dtype == "medication_record"
            facts[-1]["pos"] = drug.start(drug.lastindex or 0) if drug else 0
        if proc or section == "psh":
            not_done = bool(proc and re.search(re.escape(proc.group(0)) + r"\s+(?:is\s+|was\s+)?(?:not\s+(?:indicated|needed|"
                                               r"required|done|performed)|deferred|declined)", t, re.I))
            add("procedure", not ((R.term_negated(t, proc.start()) if proc else neg) or not_done), "boolean",
                term=proc.group(0) if proc else t[:40])
            if not_done:
                facts[-1]["extra"]["status"] = "past"
            facts[-1]["lexicon"] = bool(proc)
            facts[-1]["pos"] = proc.start() if proc else 0
        serology = any(f["concept"] in ("hepatitis_b", "hepatitis_c", "hiv") for f in facts)
        if (diag or section in ("pmh", "family")) and not (serology and dtype in CONFIRMED_DOCS):
            # one fact per distinct condition term, each with its own polarity ("Psoriasis, no arthritis")
            seen_terms, any_match = set(), False
            for start, term in diag_phrases(t):
                any_match = True
                if term.lower() in seen_terms or (term == "RA" and re.search(
                        r"GLP-?1\s*RA|\d\s*%\s*(?:on\s+)?RA\b|SpO2|room air", t, re.I)):
                    continue                     # "GLP-1 RA" (drug class), "98% RA" (room air): not arthritis
                seen_terms.add(term.lower())
                add("diagnosis", not R.term_negated(t, start), "boolean", term=term)
                facts[-1]["pos"] = start
                if len(seen_terms) >= 4:
                    break
            if not any_match and (section in ("pmh", "family") or not diag):
                add("diagnosis", not neg, "boolean", term=t[:40])

        # a denied treatment: "Denies any prior systemic therapy for liver cancer" (a trial needs "no prior systemic
        # therapy"), "no chemotherapy or radiation so far"
        for m in THERAPY_DENIED.finditer(t):
            if not any(f["concept"] in ("medication", "procedure") and f["value"] is False for f in facts):
                add("procedure" if re.search(r"radi|surg|resect|transplant", m.group("what"), re.I) else "medication",
                    False, "boolean", term=m.group("what").strip())
        # findings denied next to a lexicon fact: "Reports no new flashes or floaters since surgery" gave only the
        # surgery; the denied findings come out too
        if facts and not med_heading and dtype in ("clinic_note", "discharge_summary", "patient_interview") and not any(
                f["value"] is False for f in facts):
            _, neg_part = R.clause_polarity(t)
            for item in ([] if re.search(r"\bif\s+(?:no|not)\b", t, re.I) else
                         denied_items(neg_part, [f.get("term") for f in facts])):
                add("medication" if (R.DRUG_RE.search(item) or re.search(
                    r"thinners?|anticoagul\w*|medications?|drugs?|steroids?|supplements?|antibiotics?", item, re.I))
                    else "symptom_finding", False, "boolean", term=item)
        # findings: imaging / pathology sentences, exam and narrative symptom statements
        if not facts and not med_heading and (dtype in ("imaging_report", "pathology_report", "clinic_note",
                                                        "discharge_summary", "patient_interview")) and not NOISE_RE.search(t) and re.search(r"[a-z]{3}", t):
            pos_part, neg_part = R.clause_polarity(t)
            if pos_part:
                add("symptom_finding", True, "boolean", term=pos_part[:60])
            if neg_part:
                add("symptom_finding", False, "boolean", term=neg_part[:60])
            if not pos_part and not neg_part:
                add("symptom_finding", not neg, "boolean", term=t[:60])
        if not facts and (dtype == "lab_result" or re.match(r"\s*[A-Za-z][\w -]{0,20}:\s*[<>]?\d", t)) and \
                re.search(r"\d|negative|positive|reactive|detected|pending", t):
            # a result line ("Ca: 9.2mg/dl", "MPO-ANCA: 153 EU") also when it sits inside a note
            add("lab_other", True, "categorical", term=t[:60])   # kept only if the plan asks for it
        return facts

    # ---------------------------------------------------------- one patient
    def patient(self, p, plan=None):
        self._dob = None
        as_of = p["as_of"]
        out, checks = [], collections.Counter()
        for d in p["documents"]:
            text = d["text"]
            secs = R.sections(text)
            for u in segment_units(text):
                s, e = u["span"]
                t = text[s:e]
                section = R.section_at(secs, s)
                facts = self.unit_facts(t, d, section)
                if plan is not None and facts:
                    hits = PL.relevant(text[u["parent"][0]:u["parent"][1]] if u["level"] == "item" else t, plan["vocab"])
                    kept = [f for f in facts if f["concept"] not in GENERIC or hits or f.get("lexicon")]
                    checks["plan_filtered"] += len(facts) - len(kept)
                    facts = kept
                    for f in facts:
                        if f["concept"] in GENERIC:
                            f["extra"]["plan_terms"] = hits[:5]
                if not facts:
                    continue
                obs, how = R.resolve_date(t, d.get("date"), as_of)
                checks[f"date_{how}"] += 1
                annotate(facts, t, text[u["parent"][0]:u["parent"][1]], d, section)
                for f in facts:
                    concept, cert = f["concept"], f["certainty"]
                    ev = {"evidence_id": None, "patient_id": p["patient_id"], "concept": concept,
                          "value": f["value"], "unit": f["unit"], "value_type": f["value_type"],
                          "observed_date": obs, "certainty": cert,
                          "subject": f["subject"],
                          "source": {"doc_id": d["doc_id"], "doc_type": d["type"], "author_role": d.get("author_role"),
                                     "span": [s, e], "text": t},
                          "extracted_by": "rule"}
                    if f["term"]:
                        ev["term"] = f["term"]
                    if f["extra"]:
                        ev["detail"] = f["extra"]
                    out.append(ev)
        # derived age from DOB (computed at as_of with code)
        for ev in list(out):
            if ev["concept"] == "birth_date":
                dob = date.fromisoformat(ev["value"])
                out.append({**ev, "concept": "age", "value": age_on(dob, date.fromisoformat(as_of)),
                            "unit": "years", "value_type": "numeric", "observed_date": as_of,
                            "detail": {"derived_from": "birth_date", "as_of": as_of}})
        sx = sex_from_pronouns(p, out)
        if sx:
            out.append(sx)
        out, sc = self_check(out, p, as_of)
        checks.update(sc)
        for i, ev in enumerate(out, 1):
            ev["evidence_id"] = f"{p['patient_id']}-EV{i:03d}"
        return out, checks


NOISE_CONCEPTS = ("symptom_finding", "diagnosis", "lab_other", "procedure", "treatment_plan")
_DEPT = re.compile(r"(?:[A-Za-z&/-]+\s+){0,3}(?:clinic|care|health|service|consult(?:ation)?|referral|follow-?up|team|"
                   r"department|ward|unit|[a-z]*logy|[a-z]*ics)(?:\s*[,.]?\s*(?:new referral|follow-?up|visit|"
                   r"consult(?:ation)?|clinic|note))?\.?", re.I)
_PANEL = re.compile(r"(?:routine|cbc|chemistry|lab(?:oratory)?)\s+panel\b[^.]{0,90}\.?|(?-i:[A-Z][A-Z ]*PANEL\b.{0,90})", re.I)
# social history said in a note ("Lives with both parents, father is guardian and present.")
SOCIAL_RE = re.compile(r"\b(?:guardian|lives (?:with|alone)|living (?:with|alone)|married|divorced|widowed|occupation|"
                       r"works as|employed|unemployed|retired|student|caregiver|care partner|housing|homeless|willing to travel|"
                       r"able to travel|transportation)\b", re.I)
_FILLER = re.compile(r"(?:hospital|post-?op(?:erative)?) day \d+|continue (?:current )?(?:therapy|treatment|plan)|"
                     r"seen and examined|see (?:above|below)|as above", re.I)


def noise_reason(ev, doc_text=None):
    """Why a generic evidence is noise for Agent 3, or None. Review of v13.3.1: guardian, occupation and other
    registration lines, department headers ("Pediatric nephrology."), panel headers and filler lines were
    coming out as findings, diagnoses or lab results."""
    if ev["concept"] == "medication" and re.fullmatch(
            r"(?:dispensed|max(?:imum)?|since|started|starting|current|currently|take|takes|taking|using|uses|daily|prn|dose|doses|"
            r"refill\w*|supply|then|and|or)", (ev.get("term") or "").strip(" .:"), re.I) and not re.search(
            r":\s*\S", ev["source"]["text"]):     # "Current (inpatient): IV D5 ..." is a list label + drugs, kept
        return "medication_fragment"     # "dispensed 28 days.", "max 2 doses/day": a piece of the drug line before it
    if ev["concept"] not in NOISE_CONCEPTS:
        return None
    t = ev["source"]["text"].strip()
    first_line = doc_text is None or ev["source"]["span"][0] <= max(0, doc_text.find("\n") if "\n" in doc_text
                                                                     else len(doc_text))
    if first_line and len(t) <= 45 and not re.search(r"\d", t) and _DEPT.fullmatch(t):
        return "department"
    if ev["concept"] == "lab_other" and ev["value"] is True and _PANEL.fullmatch(t):
        return "panel_header"
    if len(t) <= 40 and _FILLER.fullmatch(t.rstrip(". ")):
        return "filler"
    return None


LAB_MATCHERS = LAB_CONCEPTS = None
DOSE_UNITS = {"mg", "g", "mcg", "ug", "µg", "iu", "units", "tab", "tabs", "tablets", "ml", "meq"}
LAB_LINE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z0-9 ,'()\-/]{0,48}?)\s*[:=]?\s*(?P<op><=|>=|<|>)?\s*"
                      r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
                      r"(?P<unit>%|(?:x\s?)?10\^?\d+/(?:L|uL|µL)|(?:mg|g|ug|µg|ng|pg|mmol|umol|µmol|nmol|pmol|mEq|IU|mIU|U|mU|"
                      r"kU|cells|copies|fL|sec)(?:/[a-zA-Z0-9.^µ]+)*)(?![A-Za-z])")
REF_AFTER = re.compile(r"\s*(?:[HL]\s*)?[(\[]\s*(?:ref(?:erence)?(?:\s+range)?\s*:?\s*|normal\s*:?\s*)?"
                       r"(?P<lo>\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(?P<hi>\d+(?:\.\d+)?)", re.I)


def lab_values(evs, concepts=None):
    """A lab line written as a value ("Calcium 8.5 mg/dL (ref 8.8-10.8)") but extracted as `lab_other = true`
    (the model, or a rule that saw no alias) becomes that number: the specific concept when a dictionary alias
    and its unit fit ("calcium" 8.5 mg/dL), else `lab_other` with the number, unit, analyte name and reference
    range. Agent 3's code step and x ULN criteria need the number. Returns the count changed."""
    n = 0
    for ev in evs:
        if ev["concept"] != "lab_other" or ev.get("subject", "patient") != "patient":
            continue
        if isinstance(ev["value"], str):           # ">300", "0.048 (low)" written as a string
            sm = re.fullmatch(r"\s*(<=|>=|<|>)?\s*(\d+(?:\.\d+)?)\s*(?:\([^)]{0,12}\))?\s*", ev["value"])
            if sm:
                val = float(sm.group(2))
                ev.update(value=int(val) if val.is_integer() and "." not in sm.group(2) else val, value_type="numeric")
                if sm.group(1):
                    ev.setdefault("detail", {})["comparator"] = sm.group(1)
                n += 1
            continue
        if ev["value"] is not True:
            continue
        t = ev["source"]["text"]
        if LAB_MATCHERS and concepts is not None:
            got = R.numeric_values(t, LAB_MATCHERS)
            if got:
                key, val, unit, extra = got[0]
                c = concepts.get(key) or {}
                v2, u2, ok = R.convert(val, unit, c)
                head = re.match(r"\s*([A-Za-z][^\d]{0,40}?)\s*[:=]?\s*(?:<=|>=|<|>)?\s*\d", t)
                if ok and unit and head and c.get("type") == "lab" and key != "lab_other" and not isinstance(v2, str):
                    ev.update(concept=key, value=v2, unit=u2, value_type="numeric", term=head.group(1).strip())
                    d = ev.setdefault("detail", {})
                    d.update({k: v for k, v in extra.items() if k in ("ref_low", "ref_high", "comparator")})
                    d["unit_written"] = unit
                    n += 1
                    continue
        m = LAB_LINE.match(t)
        if not m or re.search(r"ratio|index|score", m.group("name"), re.I):
            continue
        raw = m.group("num").replace(",", "")
        val = float(raw)
        val = int(val) if val.is_integer() and "." not in raw else val
        ev.update(value=val, unit=m.group("unit"), value_type="numeric", term=m.group("name").strip(" ,:"))
        d = ev.setdefault("detail", {})
        if m.group("op"):
            d["comparator"] = m.group("op")
        rr = REF_AFTER.match(t, m.end())
        if rr:
            d["ref_low"], d["ref_high"] = float(rr.group("lo")), float(rr.group("hi"))
        n += 1
    return n


LESION_RE = re.compile(r"\b(?:mass(?:es)?|lesions?|nodules?|tumou?rs?|metasta\w*|mets|adenopathy|lymph nodes?|nodes|"
                       r"implants?|deposits?|viable tumou?r)\b", re.I)
NOT_TUMOR_RE = re.compile(r"\b(?:cysts?|stones?|calcul\w*|thyroid|goiter|fibroids?|hemangioma|benign|polyps?|aneurysm|"
                          r"scar|kidney|liver span|spleen|prostate volume|ovary|uterus|effusion|collection|pseudocyst)\b", re.I)
SIZE_RE = re.compile(r"(?<![\d.])(\d{1,2}(?:\.\d)?)\s*(?:x\s*\d{1,2}(?:\.\d)?\s*)?(cm|mm)\b")
SIZE_LIST_RE = re.compile(r"\((\d{1,2}(?:\.\d)?(?:\s*,\s*\d{1,2}(?:\.\d)?)+)\s*(cm|mm)\)")


def measurable(t):
    """A tumour lesion with a written size in a note or report -> (largest size in mm, term) for
    `measurable_disease`. RECIST measurability (>= 10 mm, imaging age) is Agent 3's call; this only marks the
    sentence that gives the size. None when no tumour lesion with a size is written or the sentence is negated."""
    if not LESION_RE.search(t) or NOT_TUMOR_RE.search(t) or re.match(r"\s*(?:no|without|negative for)\b", t, re.I):
        return None
    if re.search(r"\b(?:tender|reactive|shotty|no (?:palpable )?mass(?:es)?)\b", t, re.I):
        return None                                   # an exam finding or a reactive node, not a tumour lesion
    t = re.sub(r"(?:=|sum(?: of diameters)?|baseline|total)\s*:?\s*\d+(?:\.\d)?\s*(?:cm|mm)", " ", t, flags=re.I)
    sizes = [float(x) * (10 if u == "cm" else 1) for x, u in SIZE_RE.findall(t)]
    for grp, u in SIZE_LIST_RE.findall(t):
        sizes += [float(x) * (10 if u == "cm" else 1) for x in re.findall(r"\d+(?:\.\d)?", grp)]
    if not sizes:
        return None
    return max(sizes), LESION_RE.search(t).group(0)


MD_AFTER_VALUE = re.compile(r"\s*(?:[A-Za-zµ%][A-Za-z0-9µ%/^.]*(?:/1\.73\s?m2)?\s*)?,?\s*"
                            r"(?:(?:baseline|initial|pre-?treatment|at diagnosis)\s*)?"
                            r"(?:(?:on|dated|drawn|from|checked|measured)\s+(?P<m1>\d{1,2})/(?P<d1>\d{1,2})(?![\d/])"
                            r"|\(\s*(?:on\s+)?(?P<m2>\d{1,2})/(?P<d2>\d{1,2})\s*\))", re.I)
MD_HEADER = re.compile(r"\s*[A-Za-z][A-Za-z0-9 /&-]{0,30}?\s*\(\s*(?P<m>\d{1,2})/(?P<d>\d{1,2})\s*\)\s*:")
FUTURE_RE = re.compile(r"\b(?:keep|scheduled|schedule|planned|plan|due|next|repeat|recheck|follow[- ]?up|will|booked|"
                       r"appointment|to be)\b", re.I)


def _num_forms(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return []
    forms = {str(v), f"{v:g}", f"{v:,}" if isinstance(v, int) else f"{v:,g}"}
    if isinstance(v, float) and v.is_integer():
        forms |= {str(int(v)), f"{int(v):,}"}
    return sorted(forms, key=len, reverse=True)


MD = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")


def fix_md_dates(evs, doc_dates):
    """A value written with a month/day and no year ("eGFR 59 on 8/5.", "CRP 14 mg/L (06/10)") was measured that
    day, not on the document date. Only the date right after the value counts (an older value's date in a
    parenthesis does not move the current value), a future step ("keep sleep study on 9/15") is not a measurement,
    and only evidence still carrying the document date (or none) is changed. Year: the document's, the year before
    when that would fall after the document date. Returns the count changed."""
    from datetime import date as _d
    n = 0
    for ev in evs:
        dd = doc_dates.get(ev["source"]["doc_id"])
        if not dd:
            continue
        t = ev["source"]["text"]
        if ev.get("observed_date") not in (None, dd):
            # a month/day the model read as month/year ("(03/26)" -> 2026-03-01) is the same date mistake
            o = ev.get("observed_date") or ""
            if not any(o in (f"20{int(m.group(2)):02d}-{int(m.group(1)):02d}-01", f"{dd[:4]}-{int(m.group(1)):02d}-01")
                       for m in MD.finditer(t) if 1 <= int(m.group(1)) <= 12):
                continue
        hd = MD_HEADER.match(t)
        if hd and _num_forms(ev["value"]) and not FUTURE_RE.search(t[:hd.end()]):
            # "Lipids (06/10): LDL-C 124": the panel's date heads the line and dates every value in it
            y, mo, da = int(dd[:4]), int(hd.group("m")), int(hd.group("d"))
            try:
                obs = _d(y, mo, da)
                if obs.isoformat() > dd:
                    obs = _d(y - 1, mo, da)
                if obs.isoformat() != ev.get("observed_date"):
                    ev["observed_date"] = obs.isoformat()
                    ev.setdefault("detail", {})["date_from"] = hd.group(0).strip()
                    n += 1
            except ValueError:
                pass
            continue
        for f in _num_forms(ev["value"]):
            for m in re.finditer(r"(?<![\d.,])" + re.escape(f) + r"(?![\d.])", t):
                g = MD_AFTER_VALUE.match(t, m.end())
                if not g:
                    continue
                mo, da = int(g.group("m1") or g.group("m2")), int(g.group("d1") or g.group("d2"))
                clause = re.split(r"[.;]", t[:m.start()])[-1]
                if FUTURE_RE.search(clause + t[m.end():g.end()]):
                    break
                y = int(dd[:4])
                try:
                    obs = _d(y, mo, da)
                    if obs.isoformat() > dd:
                        obs = _d(y - 1, mo, da)
                except ValueError:
                    break
                if obs.isoformat() != ev.get("observed_date"):
                    ev["observed_date"] = obs.isoformat()
                    ev.setdefault("detail", {})["date_from"] = t[g.start():g.end()].strip()
                    n += 1
                break
            else:
                continue
            break
    return n


QUALITATIVE = {"hiv", "hepatitis_b", "hepatitis_c"}
QUAL_WORDS = {"negative": False, "non-reactive": False, "nonreactive": False, "not detected": False,
              "positive": True, "reactive": True, "detected": True}
STAGE_OK = re.compile(r"stage|^\s*[cpyr]?T[0-4xis]|\bBCLC\b|\bISS\b|Gleason|Ann Arbor|FIGO|Binet|\bRai\b|limited|extensive|"
                      r"^\s*[0IV]+[ABC]?\d?\s*$", re.I)
CONSENT_RE = re.compile(r"will provide (?:written )?informed consent|able to (?:give|provide) (?:written )?informed consent", re.I)
BP_KEYS = {"blood_pressure", "systolic_bp", "diastolic_bp"}
PENDING_RE = re.compile(r"\bpending\b|\bordered\b|awaiting (?:the )?results?|\bsent (?:to|for|out)\b|specimens? sent|"
                        r"results? (?:not yet|to follow)", re.I)
RESULT_RE = re.compile(r"negative|positive|non-?reactive|\breactive|not detected|\bdetected|undetect|normal|abnormal|"
                       r"\d+(?:\.\d+)?\s*(?:%|[a-zA-Zµ]+/[a-zA-Z0-9.^µ]+|x10)", re.I)
TEST_WORD_RE = re.compile(r"Ag/Ab|antibod|antigen|screen|\btest|PCR|culture|serolog|QuantiFERON|IGRA|panel|level|report|"
                          r"EEG|biopsy result|laborator", re.I)
NOT_RECORDED_RE = re.compile(r"not (?:recorded|documented|specified|stated|known|available)|\bunknown\b|unrecorded", re.I)
LAB_LIKE = {"lab_other", "biomarker", "hcg", "hepatitis_b", "hepatitis_c", "hiv", "hbv_dna", "hiv_viral_load"}
COUNSEL_RE = re.compile(r"counsel|advis|discuss|recommend|educat|reviewed|explained", re.I)


def post_fix(evs, docs=None):
    """Evidence-level corrections shared by the rule and the model paths (and by postfix.py on a finished file).
    Returns (kept evidence, Counter)."""
    c, out = collections.Counter(), []
    spans = collections.Counter((e["source"]["doc_id"], tuple(e["source"]["span"])) for e in evs)
    for ev in evs:
        t = ev["source"]["text"]
        if ev["concept"] in QUALITATIVE | {"hcg"} and isinstance(ev["value"], str) and ev["value"].strip().lower() in QUAL_WORDS:
            ev.update(value=QUAL_WORDS[ev["value"].strip().lower()], value_type="boolean")   # "negative" -> false
            c["fix_qualitative_word"] += 1
        if ev["concept"] in QUALITATIVE and isinstance(ev["value"], (int, float)) and not isinstance(ev["value"], bool):
            # "HIV 1/2 Ag/Ab negative": the 1 is the virus type, not a value
            neg = re.search(r"non-?reactive|negative|not detected|undetect", t, re.I)
            pos = re.search(r"(?<!non-)(?<!non)reactive|positive|detected", t, re.I)
            if neg or pos:
                ev.update(value=not neg, value_type="boolean", unit=None)
                c["fix_qualitative_value"] += 1
            else:
                c["drop_qualitative_number"] += 1
                continue
        if ev["concept"] == "cancer_stage" and isinstance(ev["value"], str) and not STAGE_OK.search(ev["value"]):
            # "Grade 2 neuropathy", "ALBI grade 2", "GOLD 3", "moderately severe": not a cancer stage. Dropped when
            # another evidence covers the same place, else kept as a finding so the sentence stays citable
            if spans[(ev["source"]["doc_id"], tuple(ev["source"]["span"]))] > 1:
                c["drop_not_a_stage"] += 1
                continue
            ev.update(concept="symptom_finding", term=f'{ev["source"]["text"][:60].strip()}', value=True,
                      value_type="boolean")
            c["fix_not_a_stage"] += 1
        ctx = t
        if docs and ev["source"]["doc_id"] in docs:              # the clause right after: "...ordered; specimens sent, results pending"
            d, e0 = docs[ev["source"]["doc_id"]], ev["source"]["span"][1]
            m = re.match(r"[^.\n]{0,90}", d[e0:])
            ctx = t + (m.group(0) if m else "")
        if (ev["value"] is True or (ev["value"] is None and ev["concept"] in LAB_LIKE)) and PENDING_RE.search(ctx) and not RESULT_RE.search(re.sub(r"HIV[- ]?1/2|Ag/Ab", " ", t)) and (
                ev["concept"] in LAB_LIKE or (ev["concept"] in ("diagnosis", "symptom_finding") and TEST_WORD_RE.search(t))):
            # a test that was ordered or sent but has no result yet: "pending", never a positive finding
            # ("Hepatitis B, hepatitis C and HIV screening ordered; specimens sent, results pending")
            if ev["concept"] in ("diagnosis", "symptom_finding"):
                ev.update(concept="lab_other", term=ev.get("term") or t[:60])
            ev.update(value="pending", value_type="categorical", unit=None)
            ev.setdefault("detail", {})["status"] = "pending"
            c["fix_pending_test"] += 1
        if ev["value"] is False and NOT_RECORDED_RE.search(t) and not re.search(r"\b(?:no|denies|never|without)\b", t, re.I):
            ev.update(value=None, value_type="categorical")      # "product not recorded": unknown, not "no"
            c["fix_not_recorded_null"] += 1
        if CONSENT_RE.search(t):
            # TREC / TrialGPT summaries end with "The patient will provide informed consent, and will comply with the
            # trial protocol without any practical issues.": one positive social fact ("without ... issues" is not
            # a negation), the evidence for consent / compliance criteria
            if ev["concept"] != "social_history" or ev["value"] is not True:
                ev.update(concept="social_history", value=True, value_type="boolean", unit=None,
                          term="will provide informed consent and comply with the protocol")
                ev.setdefault("detail", {}).pop("status", None)
                c["fix_consent_statement"] += 1
        if ev["concept"] in BP_KEYS and ev.get("unit") not in (None, "mmHg"):
            ev["unit"] = "mmHg"                       # "134/74 mm Hg" was read as unit "mm"
            c["fix_bp_unit"] += 1
        if ev["concept"] == "contraception" and ev["value"] is True and COUNSEL_RE.search(t):
            # "Counselled on effective contraception while on methimazole": advice, not current use
            ev.update(concept="treatment_plan", term=ev.get("term") or "contraception", value_type="boolean")
            ev.setdefault("detail", {})["status"] = "planned"
            c["fix_counsel_is_plan"] += 1
        out.append(ev)
    return out, c


def self_check(evs, p, as_of, concepts=None):
    """Span text equals the document slice, value in a plausible range, date <= as_of, no duplicates."""
    docs = {d["doc_id"]: d["text"] for d in p["documents"]}
    keep, seen, c = [], set(), collections.Counter()
    c["fix_lab_value"] += lab_values(evs, concepts if concepts is not None else LAB_CONCEPTS)
    c["fix_md_date"] += fix_md_dates(evs, {d["doc_id"]: d.get("date") for d in p["documents"]})
    evs, c2 = post_fix(evs, docs)
    c.update(c2)
    # a medication fragment ("started 2026-09-16 (dispensed 28 days)", "max 2 doses/day") is a piece of the drug item
    # just before it: it takes that drug's name and keeps its own date (Agent 3 uses it for "started < 1 month ago")
    meds = sorted((x for x in evs if x["concept"] == "medication"),
                  key=lambda x: (x["source"]["doc_id"], x["source"]["span"][0]))
    for i, ev in enumerate(meds):                   # in reading order, so "..., max 3 g/day, started 2026-09." chains
        if noise_reason(ev, None) != "medication_fragment":
            continue
        s0, d0 = ev["source"]["span"][0], ev["source"]["doc_id"]
        prev = [m for m in meds[:i] if m["source"]["doc_id"] == d0 and 0 <= s0 - m["source"]["span"][1] <= 3
                and re.fullmatch(r"[\s,;.]*", docs[d0][m["source"]["span"][1]:s0])
                and noise_reason(m, None) != "medication_fragment"]
        if prev:
            ev.update(term=prev[-1].get("term"), value=prev[-1]["value"])
            if re.search(r"not taken|stopped|discontinued|held|no longer", ev["source"]["text"], re.I):
                ev.setdefault("detail", {})["status"] = "stopped"     # "since 2012 (not taken recently)"
            ev.setdefault("detail", {})["fragment_of"] = (prev[-1].get("detail") or {}).get(
                "fragment_of") or prev[-1]["source"]["text"][:80]
            c["medication_fragment_joined"] += 1
    for ev in evs:
        s, e = ev["source"]["span"]
        if docs[ev["source"]["doc_id"]][s:e] != ev["source"]["text"]:
            c["drop_span_mismatch"] += 1
            continue
        if ev["source"]["doc_type"] == "registration" and ev["concept"] in NOISE_CONCEPTS:
            # "Guardian: mother.", "Retired factory worker.", "Lives with husband." are social history, not findings
            ev.update(concept="social_history", value=True, value_type="boolean", unit=None,
                      term=ev.get("term") or ev["source"]["text"])
            c["relabel_social_history"] += 1
        elif (ev["concept"] == "symptom_finding" and ev["value"] is True and SOCIAL_RE.search(ev.get("term") or "")
              and not noise_reason(ev, docs[ev["source"]["doc_id"]])):
            ev.update(concept="social_history", value_type="boolean", unit=None)
            c["relabel_social_history"] += 1
        why = noise_reason(ev, docs[ev["source"]["doc_id"]])
        if why:
            c[f"drop_noise_{why}"] += 1
            continue
        lo_hi = RANGES.get(ev["concept"])
        if lo_hi and isinstance(ev["value"], (int, float)) and not (lo_hi[0] <= ev["value"] <= lo_hi[1]):
            c["flag_value_range"] += 1
            ev.setdefault("detail", {})["check"] = "value outside plausible range"
        if ev["observed_date"] and ev["observed_date"] > as_of:
            c["fix_date_after_as_of"] += 1
            ev["observed_date"] = None
        key = (ev["source"]["doc_id"], tuple(ev["source"]["span"]), ev["concept"], json.dumps(ev["value"]),
               None if ev["concept"] == "social_history" else ev.get("term"))   # one social line, one evidence
        if key in seen:
            c["drop_duplicate"] += 1
            continue
        seen.add(key)
        keep.append(ev)
    return keep, c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", required=True)
    ap.add_argument("--concepts", default=os.path.join(HERE, "concepts.json"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--trials", help="reference trials.jsonl (with --criteria-ref: plan from candidate trials)")
    ap.add_argument("--criteria-ref", help="reference criteria.jsonl (①-a now, ①-b later)")
    ap.add_argument("--k", type=int, default=20, help="candidate trials per patient for the plan")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ex = Extractor(load_concepts(a.concepts))
    planner = None
    if a.trials and a.criteria_ref:
        L = lambda f: [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]  # noqa: E731
        planner = PL.Planner(L(a.trials), L(a.criteria_ref))
    n = 0
    tot = collections.Counter()
    with open(os.path.join(a.out, "evidence.jsonl"), "w", encoding="utf-8") as fe, \
            open(os.path.join(a.out, "log.jsonl"), "w", encoding="utf-8") as fl:
        for line in open(a.patients, encoding="utf-8"):
            if not line.strip():
                continue
            p = json.loads(line)
            pl = planner.plan(p, a.k) if planner else None
            evs, checks = ex.patient(p, pl)
            for ev in evs:
                fe.write(json.dumps(ev, ensure_ascii=False) + "\n")
            by = collections.Counter(ev["concept"] for ev in evs)
            fl.write(json.dumps({"patient_id": p["patient_id"], "plan": {"default": DEFAULT_PLAN, **({"candidate_trials": pl["candidate_trials"],
                                 "trigger_concepts": pl["trigger_concepts"], "vocab_size": len(pl["vocab"])} if pl else {})}, "n_evidence": len(evs),
                                 "by_concept": by, "checks": checks}, ensure_ascii=False) + "\n")
            n += len(evs)
            tot.update(checks)
    from llm_layer import write_manifest
    write_manifest([json.loads(x) for x in open(a.patients, encoding="utf-8") if x.strip()], os.path.join(a.out, "docs.jsonl"))
    print(f"{n} evidence -> {a.out}/evidence.jsonl; checks {dict(tot)}")


if __name__ == "__main__":
    main()
