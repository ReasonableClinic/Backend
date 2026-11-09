#!/usr/bin/env python3
"""agent3_out.jsonl -> gold_draft.jsonl (+ gold_draft_notes.jsonl) for the external scorers in eval_tools/.

  python3 eval/to_gold_draft.py runs/trialgpt_X/agent3_out.jsonl --out runs/trialgpt_X
  cd eval_tools/trialgpt && python3 trialgpt_eval.py compare --run ../../runs/trialgpt_X
  cd eval_tools/trec && python3 compare_trec.py --run ../../runs/trec_X --qrels qrels_sample.jsonl --criteria criteria.jsonl

Format (eval_tools_v1 README 2): one line per pair with trial_label and, per criterion, expected_status and
reason; criteria the agent marked applicable=false are listed in gold_draft_notes.jsonl as not_applicable.
"""
import argparse
import json
import os


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pred")
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="gold_draft.jsonl", help="gold_draft.jsonl or gold_draft.run2.jsonl")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    notes = {}
    with open(a.pred, encoding="utf-8") as f, open(os.path.join(a.out, a.name), "w", encoding="utf-8") as g:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            g.write(json.dumps({
                "patient_id": r["patient_id"], "trial_id": r["trial_id"], "trial_label": r["trial_label"],
                "criteria": [{"criterion_id": c["criterion_id"], "expected_status": c["status"], "reason": c["reason"]}
                             for c in r["criteria"]],
            }, ensure_ascii=False) + "\n")
            for c in r.get("not_applicable", []):
                notes.setdefault(r["patient_id"], []).append(c["criterion_id"])
    with open(os.path.join(a.out, "gold_draft_notes.jsonl"), "w", encoding="utf-8") as g:
        for pid, ids in notes.items():
            g.write(json.dumps({"patient_id": pid, "not_applicable": ids}) + "\n")
    print(f"wrote {a.name} ({len(notes)} patients with not_applicable notes) to {a.out}")


if __name__ == "__main__":
    main()
