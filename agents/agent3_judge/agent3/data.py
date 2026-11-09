"""Loaders for the common-format files (②, ⓪, ①, ③, ④) and small helpers."""
import json
import re
from collections import defaultdict
from datetime import date


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# Agent 2 v14.9 rules read lab reference lines ("RBC 3.41 (3.90-5.10 M/uL)") as "45M"-style age + sex.
# Fixed in v14.12, but the frozen test kit still has such lines: never take age / sex from a lab line.
LAB_LINE_RX = re.compile(r"\d\s*[KM]/[uµμ]L\b|[KM]/[uµμ]L\)", re.I)
AGE_WORDS_RX = re.compile(r"year[s-]? ?old|\byo\b|y/o|\bmale\b|\bfemale\b|\bman\b|\bwoman\b|\bboy\b|\bgirl\b|\bDOB\b", re.I)


def demographic_ok(e):
    t = e["source"]["text"]
    if e["source"]["doc_type"] == "lab_result":
        return False
    return not (LAB_LINE_RX.search(t) and not AGE_WORDS_RX.search(t))


def registration_first(e):
    """Sort key: registration documents first, then newest."""
    return (e["source"]["doc_type"] == "registration", e.get("observed_date") or "")


def days_before(as_of, d):
    """as_of - d in days (positive = in the past). None when d is missing."""
    if not d:
        return None
    try:
        return (date.fromisoformat(as_of) - date.fromisoformat(d[:10])).days
    except ValueError:
        return None


class Dataset:
    """Everything Agent 3 reads, indexed for lookup."""

    def __init__(self, patients, trials, criteria, evidence):
        self.patients = {p["patient_id"]: p for p in read_jsonl(patients)}
        self.trials = {t["trial_id"]: t for t in read_jsonl(trials)}
        self.criteria_by_trial = defaultdict(list)
        for c in read_jsonl(criteria):
            self.criteria_by_trial[c["trial_id"]].append(c)
        self.evidence = defaultdict(list)
        self.evidence_by_id = {}
        for e in read_jsonl(evidence):
            self.evidence[e["patient_id"]].append(e)
            self.evidence_by_id[e["evidence_id"]] = e

    def as_of(self, patient_id):
        return self.patients[patient_id]["as_of"]

    def patient_sex(self, patient_id):
        """'male' / 'female' / None from the sex evidence (newest confirmed first)."""
        evs = [e for e in self.evidence[patient_id] if e["concept"] == "sex" and e["subject"] == "patient"
               and demographic_ok(e)]
        # the registration line ("Female. DOB 1997-03-14.") is what the gold cites
        evs.sort(key=registration_first, reverse=True)
        for e in evs:
            v = str(e["value"]).lower()
            if v in ("male", "female"):
                return v, e
        return None, None

    def patient_age(self, patient_id):
        """(age in years as a float, evidence) at as_of.

        Exact age from the date of birth when the record has one (an infant born 2026-06-28 is
        0.26 years at 2026-10-01, where the rounded age evidence says 0); otherwise the newest
        stated age. Registration documents come first; lab lines are never used (demographic_ok).
        """
        as_of = date.fromisoformat(self.as_of(patient_id))
        mine = sorted((e for e in self.evidence[patient_id] if e["subject"] == "patient" and demographic_ok(e)),
                      key=registration_first, reverse=True)
        for e in mine:
            if e["concept"] == "birth_date" and isinstance(e["value"], str):
                try:
                    dob = date.fromisoformat(e["value"][:10])
                except ValueError:
                    continue
                years = as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))
                anniv = date(dob.year + years, dob.month, min(dob.day, 28 if dob.month == 2 else dob.day))
                frac = (as_of - anniv).days / 365.25
                return round(years + frac, 3), e
        evs = [e for e in mine if e["concept"] == "age" and isinstance(e["value"], (int, float))]
        evs.sort(key=registration_first, reverse=True)
        return (float(evs[0]["value"]), evs[0]) if evs else (None, None)
