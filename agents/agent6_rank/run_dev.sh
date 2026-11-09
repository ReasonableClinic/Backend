#!/usr/bin/env bash
# a6-0.4.14 dev, no API: rank (+review flags) -> score -> template briefings -> grounding + content checks
#                        -> LLM path in dry-run (fake LLM) -> same checks -> readability.
set -euo pipefail
K=${K:-for_agent456_v6}
# Agent 3 outputs and graphs: A3, G and EV can be set together (e.g. kit for_agent456_v6 = Agent 3 a3-0.3.1 on Agent 2
# v14.12). They must come from the same Agent 3 run; the evidence check stops otherwise. test stays at v14.9 (a6-0.4.0).
[ -d "$K" ] || unzip -q "$K.zip"
D="$K/dev"; T="$D/reference/trials.jsonl"
A3=${A3:-"$D/agent3_out_a031/agent3_out.jsonl $D/agent3_out_a031_variants/agent3_out.jsonl"}
G=${G:-"$D/agent3_out_a031/graph $D/agent3_out_a031_variants/graph"}
# Agent 2 evidence for the cancer-diagnosis check only. It must be the files the Agent 3 run read (the check stops
# otherwise). Default (a6-0.4.11~) = kit for_agent456_v6: Agent 3 a3-0.3.1 on Agent 2 v14.12 haiku. The old default
# (v5: a3-0.3.0 on v14.9) still runs with K=for_agent456_v5 A3=... G=... EV=... . test stays at v14.9 (a6-0.4.0).
EV=${EV:-"$D/evidence/evidence_dev_haiku_v14_12.jsonl $D/evidence/evidence_dev_variants_haiku_v14_12.jsonl"}   # the files Agent 3 read (rules files reuse ids)
mkdir -p runs
cat $A3 > runs/a3_dev_all.jsonl
env -u AGENT6_GLOSSARY python3 -m unittest discover -s tests 2>&1 | tail -1
# AGENT6_GLOSSARY=none bash run_dev.sh  -> the "no glossary" condition (briefings record glossary.mode)
python3 -m agent6.rank --agent3 $A3 --trials "$T" --out runs/rank_dev/ranking.jsonl
python3 "$D/eval/eval_variants.py" --data "$D" --pred runs/a3_dev_all.jsonl --ranking runs/rank_dev/ranking.jsonl | tail -1
python3 -m agent6.brief_clinician --evidence $EV --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$T" --out runs/brief_dev
python3 -m agent6.brief_patient   --evidence $EV --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$T" --out runs/brief_dev
python3 -m agent6.check_grounding runs/brief_dev --evidence $EV --graphs $G
python3 -m agent6.check_content   runs/brief_dev --ranking runs/rank_dev/ranking.jsonl --evidence $EV --graphs $G --trials "$T"
python3 -m agent6.brief_llm --dry-run --evidence $EV --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$T" --out runs/brief_dry
python3 -m agent6.check_grounding runs/brief_dry --evidence $EV --graphs $G
python3 -m agent6.check_content   runs/brief_dry --ranking runs/rank_dev/ranking.jsonl --evidence $EV --graphs $G --trials "$T"
python3 -m agent6.mutation_test   runs/brief_dev --graphs $G --trials "$T"
python3 -m agent6.eval_dual       runs/brief_dev --graphs $G --trials "$T" --gold-dir "$D/gold"
python3 -m agent6.eval_update     runs/brief_dev --graphs $G --data "$D"
python3 -m agent6.eval_external --show 0
python3 -m agent6.readability runs/brief_dev
