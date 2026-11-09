#!/usr/bin/env bash
# a6-0.4.0 test run, for the synthesis owner (합성 담당). No API key needed (template briefings).
# Runs the frozen package once on test, in two glossary conditions, and writes ONLY aggregate lines to
# $O/SUMMARY.txt. Return SUMMARY.txt; keep everything else (briefings, full logs) on your side.
#
#   A3="<agent3 test out .jsonl ...>" G="<agent3 test graph folder ...>" TR=<test reference trials.jsonl> \
#   EV="<Agent 2 test evidence v14.9 .jsonl that the Agent 3 test run read (LLM extraction; not the rules files)>" [SCORE_CMD='<ranking scorer, may use $RANKING>'] [GOLD=<gold dir>] \
#   bash run_test.sh
set -euo pipefail
cd "$(dirname "$0")"
: "${A3:?set A3 to the Agent 3 test output jsonl file(s)}"
: "${G:?set G to the Agent 3 test graph folder(s)}"
: "${TR:?set TR to the test reference trials.jsonl}"
: "${EV:?set EV to the Agent 2 test evidence files the Agent 3 test run read (v14.9)}"
GLOSSARY_SHA=06fc5ffa26d3e447baa02050401cfbec94c07a17da1656ce6917637826d032fe
O=${O:-runs/test_a6}
rm -rf "$O"; mkdir -p "$O"
S="$O/SUMMARY.txt"
agg() { grep -v '^  !' | tee -a "$S"; }      # per-file failure lines stay in the full log, not in SUMMARY
log() { tee -a "$O/full.log"; }

{
echo "# a6-0.4.0 test run $(date +%F)"
# 1. the package is the frozen one
sha256sum -c --quiet MANIFEST.sha256 || { echo "STOP: package files differ from MANIFEST.sha256"; exit 1; }
echo "package files: MANIFEST OK ($(wc -l < MANIFEST.sha256) files)"
python3 scripts/freeze_glossary.py --check >/dev/null || { echo "STOP: glossary freeze check failed"; exit 1; }
echo "glossary freeze: OK"
[ "$(sha256sum agent6/glossary.csv | cut -d' ' -f1)" = "$GLOSSARY_SHA" ] || { echo "STOP: glossary sha256 differs"; exit 1; }
echo "glossary sha256: $GLOSSARY_SHA"
# 2. test evidence is fixed at v14.9 (the content check in agent6.keyinfo.load_evidence also matches it to the graphs)
for f in $EV; do case "$(basename "$f")" in *v14_9*|*v14.9*) ;; *) echo "STOP: $f is not v14.9"; exit 1;; esac; done
echo "evidence files: $(for f in $EV; do basename "$f"; done | tr '\n' ' ')"
env -u AGENT6_GLOSSARY python3 -m unittest discover -s tests 2>&1 | grep -E "^(Ran|OK|FAILED)"
} 2>&1 | log | agg

cat $A3 > "$O/a3_test_all.jsonl"
python3 -m agent6.rank --agent3 $A3 --trials "$TR" --out "$O/ranking.jsonl" 2>&1 | log | agg
if [ -n "${SCORE_CMD:-}" ]; then
  echo "## ranking score" | agg
  RANKING="$O/ranking.jsonl" PRED="$O/a3_test_all.jsonl" bash -c "$SCORE_CMD" 2>&1 | log | tail -3 | agg
fi

for COND in glossary none; do
  B="$O/brief_$COND"
  if [ "$COND" = none ]; then export AGENT6_GLOSSARY=none; else unset AGENT6_GLOSSARY; fi
  {
  echo "## condition: $COND"
  python3 -m agent6.brief_clinician --evidence $EV --ranking "$O/ranking.jsonl" --graphs $G --trials "$TR" --out "$B"
  python3 -m agent6.brief_patient   --evidence $EV --ranking "$O/ranking.jsonl" --graphs $G --trials "$TR" --out "$B"
  python3 - "$B" <<'PY'
import glob, json, sys
d = json.load(open(sorted(glob.glob(sys.argv[1] + "/*.patient.json"))[0], encoding="utf-8"))
print("recorded agent6:", d.get("agent6"), "| glossary:", d["glossary"]["mode"], d["glossary"]["sha256"], "| evidence:", (d.get("evidence") or {}).get("sha256"),
      "checked graph ev nodes", (d.get("evidence") or {}).get("graph_ev_nodes_checked"))
PY
  echo "check_grounding:"; python3 -m agent6.check_grounding "$B" --evidence $EV --graphs $G
  echo "check_content:";   python3 -m agent6.check_content   "$B" --ranking "$O/ranking.jsonl" --evidence $EV --graphs $G --trials "$TR"
  echo "mutation_test:";   python3 -m agent6.mutation_test   "$B" --graphs $G --trials "$TR"
  echo "readability:";     python3 -m agent6.readability     "$B"
  if [ -n "${GOLD:-}" ]; then echo "eval_dual:"; python3 -m agent6.eval_dual "$B" --graphs $G --trials "$TR" --gold-dir "$GOLD"; fi
  } 2>&1 | log | agg
done
unset AGENT6_GLOSSARY
echo "done -> return $S only" | agg
