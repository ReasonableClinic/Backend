#!/usr/bin/env python3
"""Validate a patients.jsonl file against the shared ② Patient Record format (v0.5).

Usage: python3 schemas/validate_patients.py patients.jsonl [--strict]
Exit code 1 if any ERROR. WARNings are consistency hints.
"""
import json, re, sys
from datetime import date

DOC_TYPES = {"registration", "clinic_note", "lab_result", "medication_record", "imaging_report",
             "pathology_report", "patient_interview", "discharge_summary"}
ROLES = {"physician", "nurse", "lab", "pharmacy", "patient", "clerk"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# words that only appear in trial criteria, not in clinical notes (stage 1 must not copy criteria wording)
CRITERIA_PHRASES = [r"\binclusion criteria\b", r"\bexclusion criteria\b", r"\beligib", r"\bwithin \d+ days (before|prior to) (enrollment|randomi)",
                    r"\bprior to enrollment\b", r"\bat screening\b"]


def parse(d):
    return date.fromisoformat(d)


def age_on(dob, day):
    return day.year - dob.year - ((day.month, day.day) < (dob.month, dob.day))


def months_on(dob, day):
    return (day.year - dob.year) * 12 + day.month - dob.month - (day.day < dob.day)


def check(p, errors, warns):
    pid = p.get("patient_id", "?")
    E = lambda m: errors.append(f"{pid}: {m}")
    W = lambda m: warns.append(f"{pid}: {m}")
    for k in ("patient_id", "as_of", "summary", "documents"):
        if k not in p:
            E(f"missing field '{k}'")
    extra = set(p) - {"patient_id", "as_of", "nationality", "summary", "documents"}
    if extra:
        E(f"unexpected fields {sorted(extra)} (labels/variant info must not be in agent input)")
    if not ISO.match(p.get("as_of", "")):
        E("as_of not YYYY-MM-DD"); return
    as_of = parse(p["as_of"])
    if not re.match(r"^(SYN|TREC)-", pid):
        W("patient_id should start with SYN- or TREC-")

    seen, prev = set(), None
    dob, sex = None, None
    for i, d in enumerate(p.get("documents", []), 1):
        did = d.get("doc_id", "")
        if did != f"{pid}-D{i:02d}":
            E(f"doc_id '{did}' should be {pid}-D{i:02d}")
        if did in seen:
            E(f"duplicate doc_id {did}")
        seen.add(did)
        if d.get("type") not in DOC_TYPES:
            E(f"{did}: bad type {d.get('type')}")
        if d.get("author_role") not in ROLES:
            E(f"{did}: bad author_role {d.get('author_role')}")
        if not ISO.match(d.get("date", "")):
            E(f"{did}: date not YYYY-MM-DD"); continue
        dd = parse(d["date"])
        if dd > as_of:
            E(f"{did}: date {d['date']} after as_of")
        if prev and dd < prev:
            E(f"{did}: documents not sorted by date")
        prev = dd
        txt = d.get("text", "")
        if not txt.strip():
            E(f"{did}: empty text")
        for pat in CRITERIA_PHRASES:
            if re.search(pat, txt, re.I):
                W(f"{did}: criteria-like wording '{pat}'")
        if d.get("type") == "registration":
            m = re.search(r"DOB (\d{4}-\d{2}-\d{2})", txt)
            if m:
                dob = parse(m.group(1))
            m = re.match(r"\s*(Male|Female)", txt)
            if m:
                sex = m.group(1).lower()

    if dob is None:
        W("no registration document with 'DOB YYYY-MM-DD'")
    else:
        if dob > as_of:
            E("DOB after as_of")
        s = p.get("summary", "")
        m = re.search(r"(\d+)-year-old", s)
        if m and int(m.group(1)) != age_on(dob, as_of):
            E(f"summary age {m.group(1)} != age at as_of {age_on(dob, as_of)}")
        m = re.search(r"(\d+)-month-old", s)
        if m and int(m.group(1)) != months_on(dob, as_of):
            E(f"summary age {m.group(1)} months != {months_on(dob, as_of)} months at as_of")
        for d in p.get("documents", []):
            for m in re.finditer(r"(?<![A-Za-z0-9.])(\d+)\s?(?:-year-old|yo\b|-yo\b|M\b(?!/)|F\b(?!/))", d.get("text", "")):
                stated = int(m.group(1))
                actual = age_on(dob, parse(d["date"]))
                if 1 < stated < 110 and abs(stated - actual) > 0 and m.group(0)[-1] in "MFdoy":
                    if stated != actual:
                        W(f"{d['doc_id']}: stated age {stated} vs {actual} on {d['date']}")
    if sex:
        s = p.get("summary", "").lower()
        female = re.search(r"\b(woman|female|girl|she)\b", s)
        male = re.search(r"\b(man|male|boy|he)\b", s)
        if (sex == "male" and female and not male) or (sex == "female" and male and not female):
            E(f"summary sex conflicts with registration ({sex})")


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    import os
    if not os.path.exists(sys.argv[1]):
        print(f"No file {sys.argv[1]}: nothing was generated (see FAIL/STOP messages above)."); sys.exit(1)
    errors, warns, n = [], [], 0
    ids = set()
    for ln, line in enumerate(open(sys.argv[1]), 1):
        if not line.strip():
            continue
        try:
            p = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"line {ln}: invalid JSON ({e})"); continue
        n += 1
        if p.get("patient_id") in ids:
            errors.append(f"line {ln}: duplicate patient_id {p.get('patient_id')}")
        ids.add(p.get("patient_id"))
        check(p, errors, warns)
    for e in errors:
        print("ERROR", e)
    for w in warns:
        print("WARN ", w)
    print(f"{n} patients checked: {len(errors)} errors, {len(warns)} warnings")
    sys.exit(1 if errors or ("--strict" in sys.argv and warns) else 0)


if __name__ == "__main__":
    main()
