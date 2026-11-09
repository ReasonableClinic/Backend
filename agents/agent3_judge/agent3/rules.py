"""Deterministic judgments and text patterns.

Code decides only what it can decide without reading meaning into the record:
  - pure age criteria ("Age >= 18 years", "18-65 years of age") from the date of birth
  - pure sex criteria ("Male or female")
  - sex-impossible conditions (pregnancy exclusion for a man; "Men who do not agree to use
    condoms" for a woman) -> PASS/VALID with the sex evidence (common format 6.3)
  - consent / compliance / willingness items -> UNKNOWN/MISSING (memo 2.1)
Everything else goes to the LLM; the patterns below are also used by the post-checks.
"""
import re

# ------------------------------------------------------------------ patterns
JUDGMENT_RX = re.compile(
    r"clinically (?:significant|relevant|meaningful)|\bsignificant\b|uncontrolled|poorly controlled|"
    r"\bsevere\b|\bunstable\b|\badequate\b|\bsuitable\b|investigator'?s? (?:judg|opinion|discretion)|"
    r"(?:in the|per) (?:opinion|judg[e]?ment) of|as judged by|deemed by|may (?:interfere|compromise|increase the risk)|"
    r"would (?:interfere|compromise|make)|unsuitable",
    re.I)

CONSENT_RX = re.compile(
    r"informed consent|consent form|\bICF\b|willing(?:ness)? to|able to (?:understand|comply|complete|attend|read)|"
    r"comply with|compliance with|\bcooperat|follow[- ]up (?:requirements|visits|procedures)|study visits|"
    r"(?:participation|participating|participate) in (?:another|any other|other)|"
    r"employees? of|legal (?:guardian|representative)|unable or unwilling|unwilling",
    re.I)

# items that look administrative but the gold judges from the record (sex, tissue on file)
NOT_PURE_ADMIN_RX = re.compile(
    r"pregnan|lactat|breast-?feed|nursing|childbearing|child-bearing|child bearing|wocbp|contracept|"
    r"birth control|condom|sperm|ovum|oocyte|\begg\b|abstin|tissue|specimen|sample|biopsy|"
    r"caregiver|partner|tuberculosis",
    re.I)

FEMALE_RX = re.compile(
    r"pregnan|lactat|breast-?feed|nursing (?:mother|women)|childbearing|child-bearing|child bearing|wocbp|"
    r"\bwom[ae]n\b|\bfemales?\b|menopaus|menstrua|\boocytes?\b|\bova\b|\begg\b|\bhcg\b",
    re.I)
MALE_RX = re.compile(r"\bmen\b|\bmales?\b|\bsperm\b|\bcondoms?\b|\bpartners?\b|vasectom|prostat|testic", re.I)

# conditional phrasing: the whole criterion applies only to one sex
FEMALE_CONDITIONAL_RX = re.compile(
    r"^\s*(?:\d+\.\s*)?(?:for (?:female|wom[ae]n)|if (?:the subject is )?(?:a )?female|female (?:participants?|subjects?|patients?) "
    r"(?:of|who)|wom[ae]n of child|wocbp|females? of child|for wocbp)", re.I)
MALE_CONDITIONAL_RX = re.compile(
    r"^\s*(?:\d+\.\s*)?(?:for (?:male|men)\b|if (?:the subject is )?(?:a )?male\b|male (?:participants?|subjects?|patients?)\b|men who|males? who)",
    re.I)

PURE_SEX_RX = re.compile(
    r"^\s*(?:\d+\.\s*)?(?:(?:participants?|patients?|subjects?)\s*(?:of|:)?\s*)?(?:males?|men)\s*(?:or|and|/|,)\s*(?:females?|women)"
    r"(?:\s*(?:participants?|patients?|subjects?))?\.?\s*$|no restriction on (?:gender|sex)|without (?:gender|sex) restriction",
    re.I)

LAB_RX = re.compile(
    r"\bcount\b|\blevels?\b|\bULN\b|mg/dl|g/dl|mmol|μmol|umol|egfr|creatinine|bilirubin|\bAST\b|\bALT\b|"
    r"hemoglobin|haemoglobin|platelet|neutrophil|\bINR\b|hba1c|a1c|serolog|\bPCR\b|antigen|antibod|"
    r"\bQTc?\b|\bECG\b|LVEF|ejection fraction|\bFEV1\b|\bFVC\b|DLCO|lipase|potassium|sodium|albumin|"
    r"glucose|triglycer|cholesterol|\bTSH\b|\bT4\b|\bT3\b|UACR|UPCR|proteinuria|clearance",
    re.I)
MED_RX = re.compile(
    r"\btreat(?:ed|ment)\b|therap(?:y|ies)|\bdrugs?\b|medication|\breceived?\b|\bprior\b|\bprevious(?:ly)?\b|"
    r"\buse of\b|\btaking\b|inhibitor|agonist|antagonist|steroid|vaccine|chemotherap|radiotherap|surgery|"
    r"transplant|dose",
    re.I)
PATIENT_RX = re.compile(r"pregnan|lactat|breast|willing|agree|consent|smok|alcohol|tobacco|drug abuse|substance", re.I)

WINDOW_RX = re.compile(
    r"within (?:the )?(?:past |last |previous |prior )?(\d+(?:\.\d+)?)\s*(days?|weeks?|months?|years?)", re.I)
UNIT_DAYS = {"day": 1, "week": 7, "month": 30.4, "year": 365.25}

CONSENT_STATEMENT_RX = re.compile(r"(?:provide|give|sign)\w* (?:written )?informed consent|comply with the (?:trial|study) protocol", re.I)

FAMILY_RX = re.compile(r"family history|first[- ]degree relative|\brelatives?\b|\bsibling|\bparent", re.I)


def default_action(text, admin=False):
    """Best guess at how an unresolved criterion would be checked (v0.5 action vocabulary)."""
    if JUDGMENT_RX.search(text) and re.search(r"investigator|opinion|judg", text, re.I):
        return "clinician_confirmation"
    if admin or PATIENT_RX.search(text):
        return "patient_question"
    if LAB_RX.search(text):
        return "lab_check"
    if MED_RX.search(text):
        return "med_history_check"
    return "patient_question"


def window_days(text):
    """Largest 'within N units' window in the criterion, in days (None when absent)."""
    out = None
    for n, unit in WINDOW_RX.findall(text):
        d = float(n) * UNIT_DAYS[unit.lower().rstrip("s")]
        out = d if out is None else max(out, d)
    return out


# ------------------------------------------------------------------ age
_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"\s*(years?|yrs?|months?|weeks?|days?)?"
AGE_FILLER = set("""
age aged ages years year yrs yr old older younger adults adult participants participant patients patient subjects
subject male males female females men women or and to of at the time signing signed informed consent form icf
screening inclusive both must be is are with without no restriction on gender sex between from than equal
greater less over above under below least visit enrollment enrolment day baseline legal in countries where it
who have has aged were was study entry randomization randomisation registration sign
""".split())


def _to_years(v, unit):
    unit = (unit or "years").lower()
    if unit.startswith("month"):
        return float(v) / 12
    if unit.startswith("week"):
        return float(v) / 52.18
    if unit.startswith("day"):
        return float(v) / 365.25
    return float(v)


def parse_age_bounds(text):
    """(lo, lo_inclusive, hi, hi_inclusive, spans) for an age criterion, or None.

    Only fires when the text talks about age ("age", "years old", "years of age", "aged",
    "adults"), so "ANC >= 1.5" never looks like an age.
    """
    t = text.replace("≥", ">=").replace("≤", "<=").replace(">/=", ">=").replace("</=", "<=").replace("–", "-")
    if not re.search(r"\bage[ds]?\b|years?\s*(?:old|of age)|year-old|\badults?\b|years? or (?:older|above|over|more)", t, re.I):
        return None
    lo = hi = None
    lo_inc = hi_inc = True
    spans = []

    def take(m):
        spans.append(m.span())

    m = re.search(r"between\s+" + _NUM + _UNIT + r"\s*(?:and|to|-)\s*" + _NUM + _UNIT, t, re.I) or \
        re.search(_NUM + _UNIT + r"\s*(?:to|-|and)\s*(?:<=?\s*)?" + _NUM + r"\s*(years?|months?)", t, re.I) or \
        re.search(r">=\s*" + _NUM + _UNIT + r"\s*(?:to|-|and)\s*<=\s*" + _NUM + _UNIT, t, re.I)
    if m:
        g = m.groups()
        u2 = g[3] if len(g) > 3 else None
        lo, hi = _to_years(g[0], g[1] or u2), _to_years(g[2], u2 or g[1])
        take(m)
    else:
        m = re.search(_NUM + _UNIT + r"\s*<=\s*age\s*<=\s*" + _NUM + _UNIT, t, re.I)
        if m:
            lo, hi = _to_years(m.group(1), m.group(2)), _to_years(m.group(3), m.group(4))
            take(m)
    if lo is None:
        for rx, inc in ((r"(?:>=|at least|greater than or equal to|greater or equal to|equal to or (?:greater|older) than|aged? of)\s*" + _NUM + _UNIT, True),
                        (r"(?:>|over|above|older than|greater than)\s*" + _NUM + _UNIT, False)):
            m = re.search(rx, t, re.I)
            if m:
                lo, lo_inc = _to_years(m.group(1), m.group(2)), inc
                take(m)
                break
        if lo is None:
            m = re.search(_NUM + _UNIT + r"\s*(?:of age\s*)?(?:or|and) (?:older|above|over|more)", t, re.I)
            if m:
                lo = _to_years(m.group(1), m.group(2))
                take(m)
        for rx, inc in ((r"(?:<=|at most|no older than|less than or equal to)\s*" + _NUM + _UNIT, True),
                        (r"(?:<|under|below|younger than|less than)\s*" + _NUM + _UNIT, False)):
            m = re.search(rx, t, re.I)
            if m and (not spans or m.start() >= spans[0][1] or m.end() <= spans[0][0]):
                hi, hi_inc = _to_years(m.group(1), m.group(2)), inc
                take(m)
                break
        if lo is None and hi is None:
            m = re.search(r"\baged?\s+" + _NUM + _UNIT, t, re.I) or re.search(r"\bage\s*(?:>=|>)\s*" + _NUM, t, re.I)
            if not m:
                return None
    if lo is None and hi is None:
        return None
    return lo, lo_inc, hi, hi_inc, spans


def is_pure_age(text, spans):
    """True when, apart from the age phrase, the criterion only has filler words."""
    rest = text
    for a, b in sorted(spans, reverse=True):
        rest = rest[:a] + " " + rest[b:]
    words = re.findall(r"[a-z]+", rest.lower())
    return all(w in AGE_FILLER for w in words)


def age_in_range(age, lo, lo_inc, hi, hi_inc):
    """Whole-year bounds compare completed years ("18 to 75 years" includes 75.6); fractional
    bounds (months, weeks) compare the exact age."""
    def a(bound):
        return int(age) if float(bound).is_integer() else age
    if lo is not None and (a(lo) < lo or (not lo_inc and a(lo) <= lo)):
        return False
    if hi is not None and (a(hi) > hi or (not hi_inc and a(hi) >= hi)):
        return False
    return True


# ------------------------------------------------------------------ code judgments
def _result(cid, status, reason, evidence, action, tags, note):
    return {"criterion_id": cid, "applicable": True, "status": status, "reason": reason,
            "evidence_ids": [e["evidence_id"] for e in evidence if e], "action": action,
            "judged_by": "rule", "rule_tags": tags, "derived_from": None, "missing_fact": None,
            "note": note, "calc": None}


def judge_by_rule(crit, ds, patient_id):
    """A result dict when code can decide the criterion, else None."""
    text = crit["original_text"]
    cid = crit["criterion_id"]
    ctype = crit["type"]
    sex, sex_ev = ds.patient_sex(patient_id)
    age, age_ev = ds.patient_age(patient_id)

    # 1. pure age criterion
    b = parse_age_bounds(text)
    if b and age is not None:
        lo, lo_inc, hi, hi_inc, spans = b
        if is_pure_age(text, spans):
            inside = age_in_range(age, lo, lo_inc, hi, hi_inc)
            # an exclusion criterion describes the excluded group ("Age below 18 years")
            ok = inside if ctype != "exclusion" else not inside
            r = _result(cid, "PASS" if ok else "FAIL", "VALID" if ok else "VIOLATED", [age_ev], "none",
                        ["age_rule"], f"age {age:.2f} y vs [{lo}, {hi}]")
            r["calc"] = {"name": "age_at_as_of", "value": age, "lo": lo, "hi": hi}
            return r

    # 2. pure sex criterion
    if PURE_SEX_RX.search(text) and sex_ev:
        return _result(cid, "PASS", "VALID", [sex_ev], "none", ["sex_rule"], f"sex {sex}; any sex allowed")

    # 3. condition that cannot apply to this patient's sex (6.3 impossible condition)
    if sex == "male" and FEMALE_RX.search(text) and not MALE_RX.search(text):
        if ctype == "exclusion" or FEMALE_CONDITIONAL_RX.search(text):
            return _result(cid, "PASS", "VALID", [sex_ev], "none", ["impossible", "sex_rule"],
                           "applies only to women; patient is male")
    if sex == "female" and MALE_RX.search(text) and not FEMALE_RX.search(text):
        if ctype == "exclusion" or MALE_CONDITIONAL_RX.search(text):
            return _result(cid, "PASS", "VALID", [sex_ev], "none", ["impossible", "sex_rule"],
                           "applies only to men; patient is female")

    # 4. consent / compliance / willingness: not knowable from the record (memo 2.1), unless the record
    #    itself states it ("will provide informed consent, and will comply with the trial protocol":
    #    a social_history line in TREC / TrialGPT summaries; TrialGPT experts count it as met, 38/39)
    admin = crit.get("administrative")
    if (admin is True or admin is None) and CONSENT_RX.search(text) and not NOT_PURE_ADMIN_RX.search(text):
        if admin is True or len(text) < 220:
            stated = [e for e in ds.evidence[patient_id] if e["concept"] == "social_history" and e["value"] is True
                      and CONSENT_STATEMENT_RX.search(e["source"]["text"])]
            if stated and not re.search(r"investigator|opinion|judg", text, re.I):
                return _result(cid, "PASS", "VALID", [stated[0]], "none", ["admin", "consent_stated"],
                               "record states the patient will consent and comply")
            action = "clinician_confirmation" if re.search(r"investigator|opinion|judg", text, re.I) else "patient_question"
            return _result(cid, "UNKNOWN", "MISSING", [], action, ["admin"],
                           "consent/compliance item: not decidable from the record")
    return None


def trial_prefilter(trial, ds, patient_id):
    """Trial-level age/sex check (6.1 rule 1). Returns a list of reasons the patient is out of range."""
    out = []
    age, _ = ds.patient_age(patient_id)
    sex, _ = ds.patient_sex(patient_id)
    if age is not None:
        if trial.get("min_age") is not None and age < trial["min_age"]:
            out.append(f"age {age:.2f} < min_age {trial['min_age']}")
        if trial.get("max_age") is not None and age > trial["max_age"] + 0.999:
            out.append(f"age {age:.2f} > max_age {trial['max_age']}")
    if sex and trial.get("sex") in ("MALE", "FEMALE") and trial["sex"].lower() != sex:
        out.append(f"sex {sex} vs trial {trial['sex']}")
    return out
