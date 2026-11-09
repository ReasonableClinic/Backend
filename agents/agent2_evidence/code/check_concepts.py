#!/usr/bin/env python3
"""Check concepts.json and the ①-b fields of criteria.jsonl before they are used for gold evidence and variants.

concepts.json: a list of concepts (common format v0.5, 8장 "개념 키"):
  {"key": "free_t4", "name": "Free thyroxine", "type": "lab", "unit": "ng/dL",
   "code": {"system": "LOINC", "code": "3024-7"},
   "aliases": ["FT4", "free T4"],                       optional: words used in records
   "alt_units": {"pmol/L": 0.0777}}                     optional: other unit -> multiply to get `unit`

Checks (offline):
  concepts   key snake_case and unique, name present, type known, lab has a unit, code system known,
             code format + check digit (LOINC mod 10, SNOMED CT Verhoeff), duplicate codes
  criteria   (with --criteria) every ①-b concept exists, operator/value/unit consistent, time_window keys,
             unit convertible to the concept unit, structured rows have a concept
  ids        (with --ref-criteria) criterion ids and original_text unchanged against the file the gold was made on
Online (with --online): looks each code up in public NLM services and prints the official name next to ours
  LOINC and ICD-10-CM: clinicaltables.nlm.nih.gov, RxNorm: rxnav.nlm.nih.gov. SNOMED CT is format-checked only.

Usage (stage2 folder):
  python3 check_concepts.py --concepts ../ctgov_v2/concepts.json --criteria ../ctgov_v2/criteria.jsonl --ref-criteria ../ctgov_v1/criteria.jsonl
  python3 check_concepts.py --concepts ../ctgov_v2/concepts.json --online
Exit code 1 when there are errors (warnings do not fail).
"""
import argparse, collections, json, re, sys, urllib.parse, urllib.request

TYPES = {"lab", "vital", "drug", "condition", "procedure", "demographic", "measurement", "behavior", "other"}
SYSTEMS = {"LOINC", "RxNorm", "SNOMED CT", "ICD-10", "ICD-10-CM"}
OPERATORS = {">=", "<=", ">", "<", "==", "between", "in", "exists", "not_exists"}
NUMERIC_OPS = {">=", "<=", ">", "<", "between"}
KEY_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")


# ---------------------------------------------------------------- code formats

def loinc_ok(code):
    """LOINC 'nnnnn-c': mod 10 check digit (Luhn variant used by LOINC)."""
    m = re.fullmatch(r"(\d{1,7})-(\d)", code or "")
    if not m:
        return False
    digits = [int(d) for d in m.group(1)]
    total = 0
    for i, d in enumerate(reversed(digits)):      # double every other digit starting from the rightmost
        if i % 2 == 0:
            d *= 2
            d = d // 10 + d % 10
        total += d
    return (10 - total % 10) % 10 == int(m.group(2))


_V_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
        [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
        [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
        [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_V_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
        [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
        [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def snomed_ok(code):
    """SNOMED CT concept id: 6-18 digits, partition '00'/'10' for concepts, Verhoeff check digit."""
    if not re.fullmatch(r"\d{6,18}", code or ""):
        return False
    c = 0
    for i, d in enumerate(reversed(code)):
        c = _V_D[c][_V_P[i % 8][int(d)]]
    return c == 0 and code[-3:-1] in ("00", "10")


def code_problems(system, code):
    if system == "LOINC":
        return [] if loinc_ok(code) else [f"LOINC code {code!r} has a bad format or check digit"]
    if system == "SNOMED CT":
        return [] if snomed_ok(code) else [f"SNOMED CT id {code!r} has a bad format, partition or check digit"]
    if system == "RxNorm":
        return [] if re.fullmatch(r"\d{1,8}", code or "") else [f"RxNorm RXCUI {code!r} should be digits"]
    if system in ("ICD-10", "ICD-10-CM"):
        return [] if re.fullmatch(r"[A-TV-Z]\d[0-9A-Z](\.[0-9A-Z]{1,4})?", code or "") else [f"ICD-10 code {code!r} has a bad format"]
    return [f"unknown code system {system!r}"]


# ---------------------------------------------------------------- online lookup

def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "concept-check/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def official_name(system, code):
    q = urllib.parse.quote(code)
    try:
        if system == "LOINC":
            d = _get(f"https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms={q}&df=LOINC_NUM,LONG_COMMON_NAME&maxList=5")
            for num, name in d[3] or []:
                if num == code:
                    return name
            return None
        if system == "ICD-10-CM" or system == "ICD-10":
            d = _get(f"https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search?sf=code&terms={q}&maxList=5")
            for c, name in d[3] or []:
                if c == code:
                    return name
            return None
        if system == "RxNorm":
            d = _get(f"https://rxnav.nlm.nih.gov/REST/rxcui/{q}/properties.json")
            return ((d.get("properties") or {}).get("name"))
    except Exception as e:  # noqa: BLE001
        return f"(lookup failed: {type(e).__name__})"
    return "(no online check for this system)"


# ---------------------------------------------------------------- checks

def load_concepts(path):
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, dict):     # {"key": {...}} is also accepted
        d = [dict(v, key=k) for k, v in d.items()]
    return d


def check_concepts(concepts, err, warn):
    keys = collections.Counter(c.get("key") for c in concepts)
    for k, n in keys.items():
        if n > 1:
            err(f"concept key {k!r} appears {n} times")
    codes = collections.defaultdict(list)
    for c in concepts:
        k = c.get("key")
        if not isinstance(k, str) or not KEY_RE.match(k):
            err(f"{k!r}: key must be snake_case")
        if not c.get("name"):
            err(f"{k}: name missing")
        t = c.get("type")
        if t is None:
            warn(f"{k}: type missing (one of {sorted(TYPES)})")
        elif t not in TYPES:
            err(f"{k}: unknown type {t!r}")
        if t in ("lab", "vital", "measurement") and not c.get("unit"):
            warn(f"{k}: {t} concept without a default unit")
        if t in ("condition", "drug", "procedure") and c.get("unit"):
            warn(f"{k}: {t} concept has a unit {c.get('unit')!r} (expected none)")
        code = c.get("code")
        if code is None:
            if t not in ("demographic", "other", "behavior"):
                warn(f"{k}: no code")
        elif not isinstance(code, dict) or not code.get("system") or not code.get("code"):
            err(f"{k}: code must be {{\"system\", \"code\"}}")
        else:
            for p in code_problems(code["system"], str(code["code"])):
                err(f"{k}: {p}")
            codes[(code["system"], str(code["code"]))].append(k)
            if code["system"] == "LOINC" and t not in (None, "lab", "vital", "measurement"):
                warn(f"{k}: LOINC code on a {t} concept")
            if code["system"] == "RxNorm" and t not in (None, "drug"):
                warn(f"{k}: RxNorm code on a {t} concept")
        alt = c.get("alt_units") or {}
        if not isinstance(alt, dict) or any(not isinstance(v, (int, float)) or v <= 0 for v in alt.values()):
            err(f"{k}: alt_units must map unit -> positive factor")
        if not isinstance(c.get("aliases", []), list):
            err(f"{k}: aliases must be a list")
    for (system, code), ks in codes.items():
        if len(ks) > 1:
            warn(f"{system} {code} is used by several keys: {', '.join(ks)}")


def unit_ok(concept, unit):
    if unit in (None, ""):
        return True
    norm = lambda u: (u or "").replace(" ", "").lower()  # noqa: E731
    return norm(unit) == norm(concept.get("unit")) or norm(unit) in {norm(u) for u in (concept.get("alt_units") or {})}


def check_criteria(criteria, by_key, err, warn):
    used = collections.Counter()
    for c in criteria:
        cid = c.get("criterion_id")
        st = c.get("parse_status")
        k = c.get("concept")
        if st == "structured" and not k:
            err(f"{cid}: parse_status structured but no concept")
        if not k:
            continue
        used[k] += 1
        if k not in by_key:
            err(f"{cid}: concept {k!r} is not in concepts.json")
            continue
        op, val, unit = c.get("operator"), c.get("value"), c.get("unit")
        if op not in OPERATORS:
            err(f"{cid}: bad operator {op!r}")
        elif op == "between" and not (isinstance(val, list) and len(val) == 2 and all(isinstance(v, (int, float)) for v in val) and val[0] <= val[1]):
            err(f"{cid}: between needs value [low, high]")
        elif op in NUMERIC_OPS - {"between"} and not isinstance(val, (int, float)):
            err(f"{cid}: operator {op} needs a numeric value, got {val!r}")
        elif op in ("exists", "not_exists") and val not in (None, True, False):
            warn(f"{cid}: {op} usually has value null")
        if op in NUMERIC_OPS and by_key[k].get("type") in ("lab", "vital", "measurement") and not unit_ok(by_key[k], unit):
            err(f"{cid}: unit {unit!r} cannot be converted to {k} ({by_key[k].get('unit')!r}); add it to alt_units")
        tw = c.get("time_window")
        if tw is not None:
            if not isinstance(tw, dict) or set(tw) - {"anchor", "max_days_before", "min_days_before"}:
                err(f"{cid}: time_window keys must be anchor / max_days_before / min_days_before")
            else:
                for f in ("max_days_before", "min_days_before"):
                    if tw.get(f) is not None and (not isinstance(tw[f], (int, float)) or tw[f] < 0):
                        err(f"{cid}: time_window.{f} must be a non-negative number of days")
                if tw.get("max_days_before") is not None and tw.get("min_days_before") is not None \
                        and tw["min_days_before"] > tw["max_days_before"]:
                    err(f"{cid}: min_days_before > max_days_before")
        ab = c.get("answerable_by")
        if ab is not None and (not isinstance(ab, list) or set(ab) - {"patient", "lab", "med_record", "clinician"}):
            err(f"{cid}: answerable_by must be a list of patient / lab / med_record / clinician")
    unused = [k for k in by_key if k not in used]
    if unused:
        warn(f"{len(unused)} concepts are not used by any criterion: {', '.join(sorted(unused)[:15])}{' ...' if len(unused) > 15 else ''}")
    n_struct = sum(1 for c in criteria if c.get("parse_status") == "structured")
    print(f"criteria: {len(criteria)} rows, {n_struct} structured, {sum(used.values())} with a concept, {len(used)} concepts used")


def check_ids(criteria, ref, err, warn):
    new = {c["criterion_id"]: c for c in criteria}
    trials = {c["trial_id"] for c in criteria}
    old = {c["criterion_id"]: c for c in ref if c["trial_id"] in trials}
    missing, added = sorted(set(old) - set(new)), sorted(set(new) - set(old))
    changed = [k for k in set(old) & set(new) if (old[k]["original_text"] or "").strip() != (new[k]["original_text"] or "").strip()]
    for k in missing[:20]:
        err(f"criterion id removed or renumbered: {k}")
    for k in added[:20]:
        err(f"new criterion id not in the reference file: {k}")
    for k in sorted(changed)[:20]:
        err(f"original_text changed for {k}")
    print(f"ids: {len(old)} reference rows for these trials, {len(missing)} missing, {len(added)} new, {len(changed)} text changed")
    if missing or added or changed:
        print("     -> gold pairs on these trials must be relabeled, or ①-b must keep the reference split")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--concepts", required=True)
    ap.add_argument("--criteria", help="criteria.jsonl with ①-b fields")
    ap.add_argument("--ref-criteria", help="criteria.jsonl the gold was made on (ids must not change)")
    ap.add_argument("--online", action="store_true", help="look codes up in NLM services and print official names")
    a = ap.parse_args()
    errors, warnings = [], []
    err, warn = errors.append, warnings.append

    concepts = load_concepts(a.concepts)
    by_key = {c.get("key"): c for c in concepts}
    print(f"concepts: {len(concepts)} ({dict(collections.Counter(c.get('type') for c in concepts))})")
    check_concepts(concepts, err, warn)
    if a.criteria:
        criteria = [json.loads(line) for line in open(a.criteria, encoding="utf-8")]
        check_criteria(criteria, by_key, err, warn)
        if a.ref_criteria:
            ref = [json.loads(line) for line in open(a.ref_criteria, encoding="utf-8")]
            check_ids(criteria, ref, err, warn)
    if a.online:
        print("\nonline lookup (compare the official name with ours):")
        for c in concepts:
            code = c.get("code")
            if isinstance(code, dict) and code.get("system") in ("LOINC", "RxNorm", "ICD-10", "ICD-10-CM"):
                print(f"  {c['key']:<28} {code['system']} {code['code']:<10} ours: {c.get('name')!s:<35} official: {official_name(code['system'], str(code['code']))}")
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print(f"\n{len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
