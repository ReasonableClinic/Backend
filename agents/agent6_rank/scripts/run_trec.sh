#!/usr/bin/env bash
# Agent 6 on the team's Agent 3 TREC 2021 run (70 patients, 100 pairs)
set -euo pipefail
T3=${T3:?set T3 to the agent3_final folder (agent3_v3.zip)}; R=$T3/runs/trec_sonnet55_p07_v3; TR=$T3/eval_tools/trec/trials.jsonl; O=${O:-runs/trec_a6}
rm -rf $O; mkdir -p $O
python3 -m agent6.rank --agent3 $R/agent3_out.jsonl --trials $TR --out $O/ranking.jsonl
EV=${EV:-"$T3/agent3_kit/evidence_trec_haiku_v14_7.jsonl"}   # only the file(s) the Agent 3 TREC run read; the check stops otherwise
python3 -m agent6.brief_clinician --evidence $EV --ranking $O/ranking.jsonl --graphs $R/graph --trials $TR --out $O/brief
python3 -m agent6.brief_patient --evidence $EV --ranking $O/ranking.jsonl --graphs $R/graph --trials $TR --out $O/brief
python3 -m agent6.check_grounding $O/brief --evidence $EV --graphs $R/graph
python3 -m agent6.check_content $O/brief --evidence $EV --graphs $R/graph --trials $TR
python3 -m agent6.brief_llm --dry-run --evidence $EV --ranking $O/ranking.jsonl --graphs $R/graph --trials $TR --out $O/brief_dry >/dev/null
python3 -m agent6.check_grounding $O/brief_dry --evidence $EV --graphs $R/graph
python3 -m agent6.check_content $O/brief_dry --evidence $EV --graphs $R/graph --trials $TR
python3 -m agent6.mutation_test $O/brief --graphs $R/graph --trials $TR
python3 -m agent6.readability $O/brief
python3 - "$T3/eval_tools/trec/qrels_sample.jsonl" "$O/ranking.jsonl" <<'PY'
import json, sys, collections
q = {(r["patient_id"], r["trial_id"]): r["trial_label"] for r in map(json.loads, open(sys.argv[1]))}
c = collections.Counter()
for r in map(json.loads, open(sys.argv[2])):
    for t in r["ranking"]: c[("ranked", q.get((r["patient_id"], t)))] += 1
    for t in r["dropped_stale_trials"]: c[("dropped_stale", q.get((r["patient_id"], t)))] += 1
    for x in r["near_miss"]: c[("near_miss", q.get((r["patient_id"], x["trial_id"])))] += 1
print("vs TREC qrels:", ", ".join(f"{k[0]}/{k[1]} {v}" for k, v in sorted(c.items())))
PY
