#!/usr/bin/env python3
"""Look up Agent 2 evidence (③) for a trial criterion (①). For Agent 3 (Eligibility Reasoner).

Two modes, chosen per criterion:
  structured  the criterion has a ①-b `concept`: evidence of that concept, filtered by `time_window`
              (max_days_before / min_days_before counted back from as_of) when the evidence has a date
  text        ①-a only (no concept yet): evidence whose term or sentence shares content words with the
              criterion text, plus concept triggers (age, sex, pregnancy, smoking, ...), ranked by overlap

Both return the newest evidence first and never drop evidence because of its value: a false fact
("No prior malignancy") or a family fact is exactly what a criterion may need. Agent 3 decides.

Library use:
    from evidence_index import EvidenceIndex
    ix = EvidenceIndex("runs/dev_haiku_v12/evidence.jsonl", patients="data/dev/input/patients.jsonl")
    hits = ix.for_criterion("SYN-0001", criterion_dict, k=12)
    print(ix.render(hits))          # compact lines for an LLM prompt

Command line (look at what Agent 3 would see):
    python3 agent2/evidence_index.py --evidence runs/dev_haiku_v12/evidence.jsonl --patients data/dev/input/patients.jsonl --criteria data/dev/reference/criteria.jsonl --patient SYN-0001 --criterion NCT05003986-E05
"""
import argparse, collections, json, math, re
from datetime import date, timedelta

STOP = set("""a an the and or of in on at to for with without by from as is are was were be been not no any all
than that this these those who which within prior previous current patient patients subject subjects participant
participants study trial must have has had history known other including include included exclude excluded
criteria criterion inclusion exclusion following documented evidence diagnosis diagnosed confirmed defined
clinically significant screening baseline visit day days week weeks month months year years time least more less
investigator opinion may could would should will can treatment treated therapy receive received receiving
dose doses agent agents drug drugs medication medications condition disease disorder active acute chronic
age aged male female women men level levels normal upper lower limit test result results""".split())
TRIGGERS = {  # criterion words -> concepts worth returning even without word overlap
    r"\bage[sd]?\b|years? (?:old|of age)|\badults?\b|\bchild": ["age", "birth_date"],
    r"\b(?:males?|females?|women|men|sex|gender)\b": ["sex"],
    r"leukocyt|leukopen|white (?:blood )?cell": ["wbc"], r"neutropen|neutrophil": ["anc"],
    r"thrombocytop|platelet": ["platelet_count"], r"an(?:a)?emi|hemoglobin|haemoglobin": ["hemoglobin"],
    r"renal|kidney|creatinine": ["creatinine", "egfr", "creatinine_clearance"],
    r"hepatic|liver function|transaminase|aminotransferase": ["ast", "alt", "bilirubin_total"],
    r"hyperthyroid|hypothyroid|thyroid|graves|\bgd\b": ["tsh", "free_t4", "total_t3"],
    r"triglycerid|\btg\b|lipid": ["triglycerides", "ldl_cholesterol", "total_cholesterol"],
    r"diabet|glycemic|hba1c|glucose": ["hba1c", "glucose"],
    r"proteinuri|albuminuri|nephrotic": ["urine_protein_creatinine_ratio", "urine_albumin_creatinine_ratio", "albumin"],
    r"pancreatit|\bap\b": ["lipase"],
    r"pregnan|lactat|breast.?feed|childbearing": ["pregnancy", "hcg", "contraception"],
    r"contracep": ["contraception"], r"smok|tobacco": ["smoking"], r"alcohol": ["alcohol"],
    r"allerg|hypersensitiv": ["allergy"], r"ecog|performance status": ["ecog"], r"karnofsky": ["karnofsky"],
    r"hepatitis b|\bhbv\b|hbsag": ["hepatitis_b"], r"hepatitis c|\bhcv\b": ["hepatitis_c"], r"\bhiv\b": ["hiv"],
    r"\bstage\b|tnm": ["cancer_stage"], r"metasta": ["metastasis"], r"nationalit|resident|korea": ["nationality"],
    r"weight|bmi|body mass": ["body_weight", "bmi"], r"blood pressure|hypertension": ["blood_pressure"],
    r"ejection fraction|lvef": ["lvef"], r"\bqtc?\b": ["qtc"],
}


BASKETS = {"diagnosis", "medication", "procedure", "symptom_finding", "lab_other", "treatment_plan", "biomarker",
           "tumor_marker", "metastasis", "allergy", "social_history"}
EMIT_AS = {"tumor_marker": "biomarker"}            # Agent 2 writes these keys under another one (concepts_agent2.json)
RELATED = {                                         # ①-b key -> evidence keys that answer the same question
    "blood_pressure": {"systolic_bp", "diastolic_bp"}, "systolic_bp": {"blood_pressure"}, "diastolic_bp": {"blood_pressure"},
    "pulmonary_function": {"fev1", "fvc", "dlco", "fev1_fvc_ratio"}, "fev1": {"pulmonary_function"},
    "fvc": {"pulmonary_function"}, "dlco": {"pulmonary_function"}, "fev1_fvc_ratio": {"pulmonary_function", "fev1", "fvc"},
    "pregnancy": {"hcg", "sex", "age", "menopausal_status", "childbearing_potential", "contraception"},
    "childbearing_potential": {"sex", "age", "menopausal_status", "pregnancy", "procedure"},
    "contraception": {"sex", "age", "menopausal_status", "childbearing_potential"},
    "biomarker": {"pd_l1_expression"}, "pd_l1_expression": {"biomarker"},
    "measurable_disease": {"metastasis", "diagnosis"}, "metastasis": {"cancer_stage"}, "cancer_stage": {"metastasis"},
    "prior_treatment_lines": {"medication", "procedure"}, "hepatitis_b": {"hbv_dna"}, "hbv_dna": {"hepatitis_b"},
    "hiv": {"hiv_viral_load", "cd4_count"}, "egfr": {"creatinine", "creatinine_clearance"},
    "creatinine_clearance": {"creatinine", "egfr"}, "ecog": {"karnofsky"}, "karnofsky": {"ecog"},
    "substance_use": {"alcohol"}, "body_weight": {"bmi"}, "bmi": {"body_weight", "body_height"},
    "diagnosis": {"symptom_finding"}, "symptom_finding": {"diagnosis"}, "medication": {"treatment_plan"},
    "procedure": {"treatment_plan"}, "treatment_plan": {"medication", "procedure"},
}


def words(text):
    return {w[:6] for w in re.findall(r"[a-z][a-z0-9\-]{2,}", (text or "").lower()) if w not in STOP}


def alias_triggers(concepts_path):
    """Criterion words -> concept, from the aliases and names in the concept list ('TG' -> triglycerides)."""
    out = {}
    try:
        concepts = json.load(open(concepts_path, encoding="utf-8"))
    except OSError:
        return out
    for c in concepts:
        for a in (c.get("aliases") or []) + [c.get("name") or ""]:
            a = a.strip()
            if len(a) < 2 or a.lower() in ("t", "k", "na", "ps", "ef", "hr", "rr"):
                continue
            rx = r"(?<![\w-])" + re.escape(a) + r"(?![\w-])"
            out.setdefault(rx if len(a) > 3 else "(?-i:" + rx + ")", []).append(c["key"])
    return out


class EvidenceIndex:
    def __init__(self, evidence_path, patients=None, concepts=None):
        import os
        self.triggers = dict(TRIGGERS)
        self.triggers.update(alias_triggers(concepts or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                     "concepts.json")))
        self.by_patient = collections.defaultdict(list)
        for line in open(evidence_path, encoding="utf-8"):
            if line.strip():
                e = json.loads(line)
                self.by_patient[e["patient_id"]].append(e)
        self.as_of = {}
        if patients:
            for line in open(patients, encoding="utf-8"):
                if line.strip():
                    p = json.loads(line)
                    self.as_of[p["patient_id"]] = p["as_of"]

    # ---------------------------------------------------------------- lookup
    def for_criterion(self, patient_id, criterion, k=12, max_basket=40):
        """Evidence for one criterion. With ①-b: every evidence of the criterion's concept and its related keys
        (time window marked, not dropped); for basket concepts (diagnosis, medication, ...) the ones whose term or
        sentence shares words with the criterion's `term`s and text come first; plus the best text matches over the
        whole record, because the gold often decides from a neighbouring fact ("Male." for a pregnancy criterion).
        Without ①-b: text matches only. Specific-concept hits are all returned; the rest is capped at k."""
        evs = self.by_patient.get(patient_id, [])
        text = criterion.get("original_text", "")
        if not criterion.get("concept"):
            hits = self._text_match(evs, text, k)
            for e in hits:
                e.setdefault("_mode", "text")
            return sorted(hits, key=lambda e: e.get("observed_date") or "", reverse=True)
        key = EMIT_AS.get(criterion["concept"], criterion["concept"])
        targets = {key} | RELATED.get(key, set())
        same = [e for e in evs if e["concept"] in targets]
        if key in BASKETS:
            # every distinct fact of the basket, word-matching ones first: "immunosuppressants" must still reach
            # "prednisolone" (Agent 3's LLM judges the synonym). One evidence per (concept, term, value), the newest.
            terms = " ".join(t for t in (criterion.get("term") or []) if isinstance(t, str))
            tw = words(terms + " " + text)
            def score(e):
                ew = words(" ".join([e.get("term") or "", e["source"]["text"]]))
                return len(tw & ew) / math.sqrt(len(ew) + 1)
            newest = {}
            for e in sorted(same, key=lambda e: e.get("observed_date") or ""):
                newest[(e["concept"], (e.get("term") or e["source"]["text"][:40]).lower(), json.dumps(e["value"]))] = e
            same = sorted(newest.values(), key=score, reverse=True)[:max_basket]
        same = self._time_filter(same, patient_id, criterion.get("time_window"))
        seen = {e["evidence_id"] for e in same}
        extra = [e for e in self._text_match(evs, text + " " + " ".join(criterion.get("term") or []), k)
                 if e["evidence_id"] not in seen][:max(3, k - len(same)) if key in BASKETS else 3]
        out = [dict(e, _mode="structured") for e in same] + [dict(e, _mode="text") for e in extra]
        out.sort(key=lambda e: e.get("observed_date") or "", reverse=True)
        return out

    def _time_filter(self, hits, patient_id, tw):
        if not tw or patient_id not in self.as_of:
            return hits
        ref = date.fromisoformat(self.as_of[patient_id])
        out = []
        for e in hits:
            d = e.get("observed_date")
            if not d:
                out.append(e)                      # undated evidence is kept; Agent 3 decides (UNKNOWN / EXPIRED)
                continue
            d = date.fromisoformat(d)
            if tw.get("max_days_before") is not None and d < ref - timedelta(days=tw["max_days_before"]):
                e = dict(e, _outside_window="too old")
            if tw.get("min_days_before") is not None and d > ref - timedelta(days=tw["min_days_before"]):
                e = dict(e, _outside_window="too recent")
            out.append(e)                          # marked, not dropped: "expired" is itself information
        return out

    def _text_match(self, evs, text, k):
        cw = words(text)
        want = {c for rx, cs in self.triggers.items() if re.search(rx, text, re.I) for c in cs}
        scored = []
        for e in evs:
            ew = words(" ".join([e.get("term") or "", e["concept"].replace("_", " "), e["source"]["text"]]))
            s = len(cw & ew) / math.sqrt(len(ew) + 1) + (2.0 if e["concept"] in want else 0.0)
            if s > 0:
                scored.append((s, e))
        scored.sort(key=lambda x: -x[0])
        return [dict(e, _score=round(s, 2)) for s, e in scored[:k]]

    # ---------------------------------------------------------------- display
    @staticmethod
    def render(hits):
        """One line per evidence, for an LLM prompt or a log."""
        lines = []
        for e in hits:
            v = e["value"]
            v = "yes" if v is True else "NO" if v is False else v
            comp = (e.get("detail") or {}).get("comparator")
            if comp and e["value_type"] == "numeric":
                v = f"{comp}{v}"                        # "TSH <0.01", not "TSH 0.01"
            what = e["concept"] + (f"[{e['term']}]" if e.get("term") else "")
            unit = f" {e['unit']}" if e.get("unit") and e["value_type"] == "numeric" else ""
            det = e.get("detail") or {}
            if "ref_high" in det or "ref_low" in det:          # for criteria written in x ULN / x LLN
                unit += f" (ref {det.get('ref_low', '')}-{det.get('ref_high', '')})"
            marks = [m for m in (e["certainty"] if e["certainty"] != "confirmed" else None,
                                 "FAMILY" if e["subject"] == "family" else None,
                                 (e.get("detail") or {}).get("status"), e.get("_outside_window")) if m]
            lines.append(f"[{e['evidence_id']}] {e.get('observed_date') or 'no date'} {e['source']['doc_type']}: "
                         f"{what} = {v}{unit}" + (f" ({', '.join(marks)})" if marks else "")
                         + f' | "{e["source"]["text"][:120]}"')
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--patients")
    ap.add_argument("--criteria")
    ap.add_argument("--patient", required=True)
    ap.add_argument("--criterion", help="omit to print all evidence of the patient (what Agent 3 gets before ①-b)")
    ap.add_argument("--k", type=int, default=12)
    a = ap.parse_args()
    ix = EvidenceIndex(a.evidence, a.patients)
    if not a.criterion:
        evs = sorted(ix.by_patient.get(a.patient, []), key=lambda e: (e["source"]["doc_id"], e["source"]["span"][0]))
        print(f"{a.patient}: {len(evs)} evidence\n")
        print(ix.render(evs))
        return
    crit = next(json.loads(l) for l in open(a.criteria, encoding="utf-8") if a.criterion in l
                and json.loads(l)["criterion_id"] == a.criterion)
    hits = ix.for_criterion(a.patient, crit, a.k)
    print(f"{crit['criterion_id']} ({crit['type']}): {crit['original_text']}")
    print(f"mode: {'structured' if crit.get('concept') else 'text'}, {len(hits)} evidence\n")
    print(ix.render(hits))


if __name__ == "__main__":
    main()
