#!/usr/bin/env bash
# a6-0.4.14 dev with the LLM. Needs ANTHROPIC_API_KEY in the environment or in ./.env (never commit it).
#   MODEL=claude-sonnet-5-5 bash run_llm.sh            # all 55 patients x 2 audiences (~110 calls, cached)
#   PATIENTS="SYN-0019 SYN-0013" bash run_llm.sh       # a few patients first
#   AGENT6_GLOSSARY=none bash run_llm.sh               # no-glossary condition -> runs/brief_llm_dev_noglossary
set -euo pipefail
K=${K:-for_agent456_v6}
# Agent 3 outputs and graphs: A3, G and EV can be set together (e.g. kit for_agent456_v6 = Agent 3 a3-0.3.1 on Agent 2
# v14.12). They must come from the same Agent 3 run; the evidence check stops otherwise. test stays at v14.9 (a6-0.4.0).
[ -d "$K" ] || unzip -q "$K.zip"
D="$K/dev"; T="$D/reference/trials.jsonl"
G=${G:-"$D/agent3_out_a031/graph $D/agent3_out_a031_variants/graph"}
EV=${EV:-"$D/evidence/evidence_dev_haiku_v14_12.jsonl $D/evidence/evidence_dev_variants_haiku_v14_12.jsonl"}   # the files Agent 3 read (rules files reuse ids)
MODEL=${MODEL:-claude-sonnet-5-5}; WORKERS=${WORKERS:-4}
# a6-0.4.11: the no-glossary condition gets its own folders, so it never overwrites the glossary run, and is compared
# with template briefings made in the same condition.
if [ "${AGENT6_GLOSSARY:-}" = none ]; then SUFFIX=_noglossary; else SUFFIX=""; fi
OUT=${OUT:-runs/brief_llm_dev$SUFFIX}; TPL=runs/brief_dev$SUFFIX
[ -f runs/rank_dev/ranking.jsonl ] || env -u AGENT6_GLOSSARY bash run_dev.sh >/dev/null
if [ ! -d "$TPL" ]; then   # template briefings in the same glossary condition, for the readability comparison
  python3 -m agent6.brief_patient   --evidence $EV --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$T" --out "$TPL" >/dev/null
  python3 -m agent6.brief_clinician --evidence $EV --ranking runs/rank_dev/ranking.jsonl --graphs $G --trials "$T" --out "$TPL" >/dev/null
fi
SEL=""; for p in ${PATIENTS:-}; do SEL="$SEL --patient $p"; done
python3 -m agent6.brief_llm --evidence $EV --model "$MODEL" --workers "$WORKERS" --ranking runs/rank_dev/ranking.jsonl \
    --graphs $G --trials "$T" --out "$OUT" $SEL | tee "$OUT.gen.txt"
{
  echo "# a6-0.4.14 LLM briefing dev run ($(date +%F)), glossary ${AGENT6_GLOSSARY:-on}"
  echo; echo "model $MODEL, prompts $(python3 -c 'from agent6.brief_llm import PROMPT_VERSION as P; print("patient", P["patient"], "/ clinician", P["clinician"])')"; echo
  echo '```'
  cat "$OUT.gen.txt"
  python3 -m agent6.check_grounding "$OUT" --evidence $EV --graphs $G
  python3 -m agent6.check_content   "$OUT" --ranking runs/rank_dev/ranking.jsonl --evidence $EV --graphs $G --trials "$T"
  echo "-- template fallback reasons (llm_log.jsonl, dev only)"
  python3 - "$OUT/llm_log.jsonl" <<'PY'
import json, re, sys, collections
c, ex = collections.Counter(), {}
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    for T in r["fallback"]:
        for p in r["problems"]:
            if p.startswith(T + ":") or p.startswith("응답"):
                k = re.sub(r"^T\d+: ", "", p)
                k = re.split(r"[:'(\[]", k)[0].strip()
                c[(r["audience"], k)] += 1
                ex.setdefault((r["audience"], k), f'{r["patient_id"]} {p[:110]}')
for (aud, k), n in c.most_common():
    print(f"{aud:9} {n:3}  {k}  | e.g. {ex[(aud, k)]}")
print("fallback trial sections:", sum(len(json.loads(l)["fallback"]) for l in open(sys.argv[1], encoding="utf-8")))
PY
  echo "-- dual reference (graph vs gold)"
  python3 -m agent6.eval_dual "$OUT" --graphs $G --trials "$T" --gold-dir "$D/gold"
  echo "-- update response (template should be unaffected_stable 100%)"
  python3 -m agent6.eval_update "$OUT" --graphs $G --data "$D"
  echo "-- readability (patient, fact sentences): template vs LLM"
  python3 -m agent6.readability "$TPL" "$OUT"
  echo "-- readability (clinician)"
  python3 -m agent6.readability "$TPL" "$OUT" --audience clinician
  echo '```'
} > "$OUT/SUMMARY.md"
rm -f "$OUT.gen.txt"
cat "$OUT/SUMMARY.md"
