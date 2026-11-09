"""Baseline patient briefing: fixed rule sentences + template sentences from the graph. No LLM.

  python3 -m agent6.brief_patient --ranking runs/rank_dev/ranking.jsonl --graphs K/dev/agent3_out_a031/graph \
      --trials K/dev/reference/trials.jsonl --out runs/brief_dev

Trial facts (randomisation, placebo, Korean sites) come from trials.jsonl and are referenced by the trial node
(`trial:<id>`), which stands for that trial's ⓪ record. Everything about the patient is referenced by decision ids.
Wording is a draft: replace with the team's text (and, if this is ever used with real patients, IRB-reviewed text).
"""
import argparse, json, os

from . import keyinfo as KI
from . import VERSION
from .graph import Graph
from .rank import read_jsonl
from . import glossary as GL
from .keyinfo import closing_rules, design_rules, opening_rules, patient_facts, site_lines
from .rules import FIXED

ACTION_KO = {"new_test": "검사", "lab_check": "검사 결과 확인", "patient_question": "몇 가지 질문",
             "med_record_check": "진료 기록 확인", "med_history_check": "과거 병력 확인",
             "clinician_confirmation": "담당 의사 확인"}


def S(text, refs, kind="fact"):
    return {"text": text, "refs": sorted(set(refs)), "kind": kind}


def fixed(rid):
    return S(FIXED[rid], [rid], "rule")


def trial_lines(g, item, trial, n):
    """Template sentences for one trial: label, what it studies, design rules, size, what the record shows, what is
    left to check (grouped by who can answer), exclusion count, Korean sites, recruitment check."""
    facts = patient_facts(g, item, trial, n)
    out, design = [], design_rules(trial, item["trial_id"])
    for f in facts:
        out.append(S(f["ko"], f["refs"]))
        if f["id"].endswith((".studies",)) or (f["id"].endswith(".label") and not any(x["id"].endswith(".studies") for x in facts)):
            out += design
    out += site_lines(item, trial)   # a6-0.4.13: no Korean site -> rule:no_kr_site + 모집 국가
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ranking", required=True)
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--evidence", nargs="*", default=[], help="Agent 2 evidence jsonl (cancer-diagnosis check)")
    a = ap.parse_args(argv)
    KI.load_evidence(a.evidence, a.graphs)
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    os.makedirs(a.out, exist_ok=True)
    n_out = 0
    for r in read_jsonl(a.ranking):
        pid = r["patient_id"]
        path = next((os.path.join(d, f"{pid}.json") for d in a.graphs if os.path.exists(os.path.join(d, f"{pid}.json"))), None)
        if not path:
            continue
        g = Graph.load(path)
        items = r["items"][:a.top]
        sents = opening_rules(g)
        if not items:
            sents.append(S("지금 기록으로는 조건이 맞을 가능성이 있는 시험을 찾지 못했습니다.",
                           [f"label:{t['id'][6:]}" for t in g.trials()] or ["rule:ask_clinician"]))
        for n, it in enumerate(items, 1):
            sents += trial_lines(g, it, trials.get(it["trial_id"], {}), n)
        sents += closing_rules()
        doc = {"patient_id": pid, "as_of": g.as_of, "audience": "patient", "graph_file": os.path.basename(path),
               "ranking": [i["trial_id"] for i in items], "sentences": sents, "glossary": GL.usage(sents),
               "evidence": KI.EVIDENCE_INFO, "agent6": VERSION}
        with open(os.path.join(a.out, f"{pid}.patient.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        with open(os.path.join(a.out, f"{pid}.patient.md"), "w", encoding="utf-8") as f:
            f.write("\n\n".join(s["text"] for s in sents) + "\n")
        n_out += 1
    print(f"{n_out} patient briefings -> {a.out}")


if __name__ == "__main__":
    main()
