#!/usr/bin/env bash
# Baseline end to end on dev (no LLM, no API): rank -> score -> briefings -> grounding check.
set -euo pipefail
K=${K:-for_agent456_v6}
[ -d "$K" ] || unzip -q "$K.zip"
A3=${A3:-"$K/dev/agent3_out_a031/agent3_out.jsonl $K/dev/agent3_out_a031_variants/agent3_out.jsonl"}
G=${G:-"$K/dev/agent3_out_a031/graph $K/dev/agent3_out_a031_variants/graph"}
mkdir -p runs
cat $A3 > runs/a3_dev_all.jsonl
python3 -m agent6.rank --agent3 $A3 --trials "$K/dev/reference/trials.jsonl" --out runs/rank_dev/ranking.jsonl
python3 "$K/dev/eval/eval_variants.py" --data "$K/dev" --pred runs/a3_dev_all.jsonl --ranking runs/rank_dev/ranking.jsonl | tail -1
python3 -m agent6.brief_clinician --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$K/dev/reference/trials.jsonl" --out runs/brief_dev
python3 -m agent6.brief_patient --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$K/dev/reference/trials.jsonl" --out runs/brief_dev
python3 -m agent6.check_grounding runs/brief_dev --graphs $G
