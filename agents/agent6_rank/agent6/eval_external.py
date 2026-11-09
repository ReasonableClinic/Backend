"""External regression for tumour/cancer wording (TrialGPT's TREC 2021·2022 and SIGIR patients).

  python3 -m agent6.eval_external [tests/external/tumour_wording_cases.json] [--show 5]

No Agent 3 graphs exist for these patients, so this tests Agent 6's patient-sentence rules only: for every
(patient, trial) pair a minimal graph is built from the curated diagnosis evidence (term, value, subject; all
certainty=confirmed) and the trial's title/conditions, then keyinfo.patient_facts writes the patient sentences.

Groups and targets:
  benign         benign tumour or tumour-like finding (pituitary adenoma, lipoma, polyps ...): cancer named = 0
  hard_negative  "cancer" in the record but not the patient's diagnosis (biopsy negative, husband's cancer): = 0
  malignant      biopsy-confirmed cancer (positive control): the cancer trials keep their cancer name (not hidden)
The same pairs are also written with the cancer_hidden rule switched off, to show what the rule prevents.
"""
import argparse, json, os
from collections import Counter

from . import keyinfo as KI
from .graph import Graph

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(HERE, "tests", "external", "tumour_wording_cases.json")


def graph_for(case, tid):
    nodes = [{"id": f"trial:{tid}", "kind": "trial"}, {"id": f"label:{tid}", "kind": "trial_decision", "label": "potential"}]
    for k, d in enumerate(case["diagnoses"], 1):
        nodes.append({"id": f"ev:{case['patient_id']}-EV{k:03d}", "kind": "evidence", "concept": "diagnosis",
                      "term": d["term"], "value": d["value"], "certainty": "confirmed", "subject": d["subject"]})
    return Graph({"patient_id": case["patient_id"], "as_of": "2026-10-01", "version": 1, "nodes": nodes,
                  "edges": [[f"trial:{tid}", "labelled", f"label:{tid}"]]})


def item_for(tid):
    return {"trial_id": tid, "label": "potential", "open_criteria": [], "stale": False, "kr_recruiting": False,
            "kr_sites": 0, "review_flags": [], "months_since_verified": 1, "status_verified": "2026-09"}


def run(cases, protect=True):
    orig = KI.cancer_hidden
    if not protect:
        KI.cancer_hidden = lambda g, trial: False
    try:
        res, examples = Counter(), []
        for c in cases:
            for t in c["trials"]:
                g = graph_for(c, t["nct"])
                trial = {"title": t["title"], "conditions": t["conditions"]}
                facts = KI.patient_facts(g, item_for(t["nct"]), trial, 1)
                text = " ".join(f["ko"] for f in facts)
                named = KI.names_cancer(text)
                cancer_trial = any(KI.names_cancer(n) for n, _ in KI.studied_names(trial))
                grp = c["group"]
                res[(grp, "pairs")] += 1
                res[(grp, "cancer_named")] += named
                res[(grp, "cancer_trial")] += cancer_trial
                res[(grp, "cancer_trial_named")] += cancer_trial and named
                res[(grp, "eligible_pairs")] += t["label"] == "eligible"
                res[(grp, "eligible_cancer_named")] += t["label"] == "eligible" and named
                if named and grp != "malignant" and len(examples) < 8:
                    examples.append((c["patient_id"], c["note_ko"], t["nct"], t["label"],
                                     next(f["ko"] for f in facts if f["id"].endswith(".studies"))))
        return res, examples
    finally:
        KI.cancer_hidden = orig


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases", nargs="?", default=DEFAULT)
    ap.add_argument("--show", type=int, default=4)
    a = ap.parse_args(argv)
    data = json.load(open(a.cases, encoding="utf-8"))
    cases = data["cases"]
    for protect in (False, True):
        res, ex = run(cases, protect)
        tag = "with cancer_hidden rule" if protect else "rule off (a6-0.2.5)  "
        b = res[("benign", "cancer_named")] + res[("hard_negative", "cancer_named")]
        bp = res[("benign", "pairs")] + res[("hard_negative", "pairs")]
        be = res[("benign", "eligible_cancer_named")] + res[("hard_negative", "eligible_cancer_named")]
        bep = res[("benign", "eligible_pairs")] + res[("hard_negative", "eligible_pairs")]
        mt, mn = res[("malignant", "cancer_trial")], res[("malignant", "cancer_trial_named")]
        print(f"{tag} | no-cancer patients: cancer named in {b}/{bp} pairs (eligible-labelled {be}/{bep}) | "
              f"cancer patients: cancer trials still named {mn}/{mt}")
        if not protect and a.show:
            for e in ex[:a.show]:
                print(f"    {e[0]} ({e[1]}) {e[2]} [{e[3]}]: {e[4]}")
    return res


if __name__ == "__main__":
    main()
