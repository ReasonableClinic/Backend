#!/usr/bin/env bash
# Re-compute the reported numbers with no API key and no network (saved LLM answers are replayed).
#   bash reproduce.sh [replay folder]          default: ./replay  (replay_pack.zip unpacked there)
#   TRIALTRACE_TEST_DIR=<test_pack unpacked> bash reproduce.sh     also runs the test step
# Works on a copy in _repro/ (repo files + replay pack laid over them), so the repo itself is not changed.
# Every line: step, metric, expected, actual, OK / DIFF. Exit code 1 if any line is DIFF. See REPRODUCE.md.
set -uo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
REPLAY=$(cd "${1:-$ROOT/replay}" 2>/dev/null && pwd) || { echo "no replay folder: unzip replay_pack.zip -d replay"; exit 2; }
[ -f "$REPLAY/MANIFEST.txt" ] || { echo "$REPLAY has no MANIFEST.txt (not replay_pack)"; exit 2; }
PY=${PYTHON:-python3}
export TRIALTRACE_WEB=$(cd "${TRIALTRACE_WEB:-$ROOT/../Healthcare-web}" 2>/dev/null && pwd) \
  || { echo "web screen repo not found: git clone https://github.com/ReasonableClinic/Healthcare-web.git next to this repo (or set TRIALTRACE_WEB)"; exit 2; }
if [ -n "${TRIALTRACE_TEST_DIR:-}" ]; then
  TD=$(cd "$TRIALTRACE_TEST_DIR" 2>/dev/null && pwd) || { echo "TRIALTRACE_TEST_DIR not found: $TRIALTRACE_TEST_DIR"; exit 2; }
fi
"$PY" -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { echo "Python 3.11+ needed"; exit 2; }

# no keys, no network: any API call fails instead of being made
unset ANTHROPIC_API_KEY OPENROUTER_API_KEY OPENAI_API_KEY LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY LANGFUSE_HOST
export http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 HTTP_PROXY=http://127.0.0.1:9 \
       HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9 no_proxy= NO_PROXY= PYTHONIOENCODING=utf-8

W=$ROOT/_repro; L=$W/logs
rm -rf "$W"; mkdir -p "$W"
(cd "$ROOT" && tar cf - --exclude=./.git --exclude=./_repro --exclude=./replay --exclude=./build --exclude='*.zip' .) | (cd "$W" && tar xf -)
cp -R "$REPLAY/." "$W/"
mkdir -p "$L"
D=$W/data/dev
FAILS=0; KNOWN=0
row() {  # step metric expected actual [known-difference note]
  local ok=OK
  if [ "$3" != "$4" ]; then
    if [ -n "${5:-}" ] && [ "$4" = "${5%%|*}" ]; then ok="KNOWN (${5#*|})"; KNOWN=$((KNOWN + 1)); else ok=DIFF; FAILS=$((FAILS + 1)); fi
  fi
  printf '%-8s %-44s %-24s %-24s %s\n' "$1" "$2" "$3" "$4" "$ok"
}
py() { "$PY" - "$@"; }
printf '%-8s %-44s %-24s %-24s %s\n' step metric expected actual result

# ---------- Agent 1 ----------
cd "$W/agents/agent1_criteria"
"$PY" -m agent1 --nct NCT05428488 --out runs/repro_one > "$L/agent1_one.log" 2>&1
"$PY" -m agent1 --saved tests/fixtures/ctgov_response_gastric_HER2.json --no-llm --out runs/repro_offline > "$L/agent1_offline.log" 2>&1
row agent1 "NCT05428488 from cache (no API)" "캐시 적중" "$(grep -q '캐시 적중: NCT05428488' "$L/agent1_one.log" && echo 캐시 적중 || echo miss)"
row agent1 "offline trials / criteria lines" "19 / 525" "$(wc -l < runs/repro_offline/trials.jsonl | tr -d ' ') / $(wc -l < runs/repro_offline/criteria.jsonl | tr -d ' ')"
row agent1 "cache rows = dev criteria rows" "3831/3856" "$(py "$D/reference/criteria.jsonl" <<'PY'
import glob, json, sys
c = {r["criterion_id"]: r for f in glob.glob("cache/*.json") for r in json.load(open(f, encoding="utf-8"))["criteria"]}
dev = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
print(f"{sum(c.get(r['criterion_id']) == r for r in dev)}/{len(dev)}")
PY
)" "3796/3856|REPRODUCE.md 5.1"

# ---------- Agent 2 ----------
cd "$W/agents/agent2_evidence"
"$PY" code/eval_evidence.py --gold "$D/gold/gold.jsonl" --pred "$D/evidence/evidence_dev_haiku_v14_12.jsonl" \
  --patients "$D/input/patients.jsonl" --misses 0 > "$L/agent2_evidence.log" 2>&1
"$PY" code/eval_concepts.py --gold "$D/gold/gold.jsonl" --criteria "$D/reference/criteria.jsonl" \
  --concepts "$D/reference/concepts.json" --pred "$D/evidence/evidence_dev_haiku_v14_12.jsonl" > "$L/agent2_concepts.log" 2>&1
num() { grep -m1 -F "$1" "$2" | sed -E "s|.*$3.*|\1|"; }
row agent2 "recall (any overlap)" "1.000" "$(num 'recall (any overlap)' "$L/agent2_evidence.log" '= ([0-9.]+)')"
row agent2 "concept at gold span (any evidence)" "0.904" "$(num 'concept agreement, any evidence' "$L/agent2_evidence.log" '= ([0-9.]+)')" "0.896|REPRODUCE.md 5.2"
row agent2 "value at gold span (same concept)" "0.859" "$(num 'value agreement, any same-concept' "$L/agent2_evidence.log" '= ([0-9.]+)')" "0.851|REPRODUCE.md 5.2"
row agent2 "numeric criteria code check" "89/89" "$(num 'agrees with gold' "$L/agent2_concepts.log" 'agrees with gold ([0-9]+/[0-9]+).*')" "88/88|REPRODUCE.md 5.2"

# ---------- Agent 3 (replay) ----------
cd "$W/agents/agent3_judge"
mkdir -p data/dev agent3_kit
cp -R "$D/input" "$D/reference" "$D/gold" data/dev/
cp "$D"/evidence/evidence_dev_haiku_v14_12.jsonl "$D"/evidence/evidence_dev_variants_haiku_v14_12.jsonl agent3_kit/
M=claude-sonnet-5-5
"$PY" -m agent3.run --split dev --llm replay --model $M --evidence agent3_kit/evidence_dev_haiku_v14_12.jsonl \
  --out runs/repro_dev > "$L/agent3_dev.log" 2>&1
"$PY" -m agent3.run --split dev --llm replay --model $M --patients data/dev/input/patients_variants.jsonl \
  --pairs data/dev/gold/gold_variants.jsonl --evidence agent3_kit/evidence_dev_variants_haiku_v14_12.jsonl \
  --out runs/repro_var > "$L/agent3_var.log" 2>&1
"$PY" eval/score_dev.py runs/repro_dev/agent3_out.jsonl --evidence agent3_kit/evidence_dev_haiku_v14_12.jsonl \
  --md runs/repro_dev/score_gold.md > /dev/null 2>&1
"$PY" eval/score_dev.py runs/repro_var/agent3_out.jsonl --gold data/dev/gold/gold_variants.jsonl \
  --evidence agent3_kit/evidence_dev_variants_haiku_v14_12.jsonl --md runs/repro_var/score_gold.md > /dev/null 2>&1
md() { grep -m1 -F "| $1 |" "$2" 2>/dev/null | awk -F'|' '{gsub(/[ *]/, "", $3); print $3}'; }
calls() { py "$1" <<'PY'
import json, sys
u = json.load(open(sys.argv[1]))["usage"]; print(f"{u['calls']} calls, {u['cache_hits']} hits")
PY
}
row agent3 "dev base: API calls (replay)" "0 calls, 61 hits" "$(calls runs/repro_dev/run_meta.json 2>/dev/null)"
row agent3 "dev variants: API calls (replay)" "0 calls, 113 hits" "$(calls runs/repro_var/run_meta.json 2>/dev/null)"
row agent3 "dev base out = official run (bytes)" "same" "$(cmp -s runs/repro_dev/agent3_out.jsonl runs/dev_a031_v10_kit1412_p07/agent3_out.jsonl && echo same || echo differ)"
row agent3 "dev variants out = official run (bytes)" "same" "$(cmp -s runs/repro_var/agent3_out.jsonl runs/dev_variants_a031_v10_kit1412_p07/agent3_out.jsonl && echo same || echo differ)"
row agent3 "strict match base / variants" "83.9% / 82.8%" "$(md '기준 상태 일치 (엄격)' runs/repro_dev/score_gold.md) / $(md '기준 상태 일치 (엄격)' runs/repro_var/score_gold.md)"
row agent3 "trial label match base / variants" "87.0% / 89.0%" "$(md '시험 판정 일치' runs/repro_dev/score_gold.md) / $(md '시험 판정 일치' runs/repro_var/score_gold.md)"

# ---------- Agent 4 v2 ----------
cd "$W/agents/agent4_verify"
A4=runs/repro_dev
PYTHONPATH=. "$PY" -m agent4 --patients "$D/input/patients.jsonl" --trials "$D/reference/trials.jsonl" \
  --criteria "$D/reference/criteria.jsonl" --evidence "$D/evidence/evidence_dev_haiku_v14_12.jsonl" \
  --verdicts "$D/agent3_out_a031/agent3_out.jsonl" --out $A4 > "$L/agent4_dev.log" 2>&1
a4sum() { py "$1" <<'PY'
import json, os, sys
d = sys.argv[1]
t = json.load(open(os.path.join(d, "verify_report.json")))["total"]
rows = [json.loads(l) for l in open(os.path.join(d, "agent3_out.jsonl"), encoding="utf-8")]
cr = [c for r in rows for c in r["criteria"]]
changed = sum(1 for c in cr if "original_status" in c and (c["original_status"], c.get("original_reason")) != (c["status"], c.get("reason")))
conf0 = sum(1 for c in cr if c.get("original_status", c["status"]) == "CONFLICT")
conf1 = sum(1 for c in cr if c["status"] == "CONFLICT")
labels = sum(1 for r in rows if r.get("agent3_trial_label", r["trial_label"]) != r["trial_label"])
print(t["checked"], changed, f"{conf0}->{conf1}", labels, t["evidence_id_mismatch"])
PY
}
read -r a4n a4c a4f a4l a4m <<< "$(a4sum $A4 2>/dev/null)"
row agent4 "verdicts checked" "1044" "${a4n:-}"
row agent4 "verdicts changed" "8" "${a4c:-}"
row agent4 "CONFLICT before->after" "0->3" "${a4f:-}"
row agent4 "trial labels changed" "0" "${a4l:-}"
row agent4 "evidence_id_mismatch" "0" "${a4m:-}"

# ---------- Agent 5 (a5u + a5j) on the Agent 4 output ----------
cd "$W/agents/agent5_acquire"
A4OUT=$W/agents/agent4_verify/$A4/agent3_out.jsonl
C5=(--split dev --patients "$D/input/patients.jsonl" --criteria "$D/reference/criteria.jsonl" --evidence "$D/evidence/evidence_dev_haiku_v14_12.jsonl")
"$PY" -m agent5.lookup_run cards --agent3 "$A4OUT" "${C5[@]}" --out runs/repro_lookup > "$L/agent5_lookup.log" 2>&1
"$PY" -m agent5.lookup_run cards --agent3 "$A4OUT" "${C5[@]}" --include-ineligible --out runs/repro_lookup_all > "$L/agent5_lookup_all.log" 2>&1
"$PY" -m agent5.run cards --agent3 "$A4OUT" "${C5[@]}" --out runs/repro_a5u > "$L/agent5_a5u.log" 2>&1
"$PY" eval/score_lookup.py runs/repro_lookup_all/cards.jsonl --gold "$D/gold/gold.jsonl" > "$L/agent5_score.log" 2>&1
S5=runs/repro_lookup/summary.md
row agent5 "a5j cards (patients)" "167 (patients 15)" "$(grep -m1 -F '| cards |' $S5 | awk -F'|' '{gsub(/^ +| +$/, "", $3); print $3}')"
row agent5 "cards for patient / clinician-site" "114 / 53" "$(grep -m1 -F 'cards for the patient' $S5 | awk -F'|' '{gsub(/^ +| +$/, "", $3); print $3}')"
row agent5 "gold MISSING lookup rows with a card" "80.9%" "$(grep -m1 'coverage:' "$L/agent5_score.log" | sed -E 's/.*\(([0-9.]+%)\).*/\1/')"
row agent5 "gold unowned new_test/clinician rows" "72.0%" "$(grep -A1 'gold unowned MISSING' "$L/agent5_score.log" | grep -m1 coverage | sed -E 's/.*\(([0-9.]+%)\).*/\1/')"

# ---------- Agent 6 a6-0.4.14 ----------
cd "$W/agents/agent6_rank"
K="$W/data" bash run_dev.sh > "$L/agent6_dev.log" 2>&1
env -u AGENT6_GLOSSARY "$PY" -m unittest discover -s tests > "$L/agent6_tests.log" 2>&1
row agent6 "unit tests" "Ran 46, OK" "$(grep -m1 '^Ran' "$L/agent6_tests.log" | awk '{print "Ran", $2}'), $(grep -m1 -E '^(OK|FAILED)' "$L/agent6_tests.log")"
row agent6 "ranking exact order / same first trial" "41/55, 43/55" "$(grep -m1 '4. ranking' "$L/agent6_dev.log" | sed -E 's/.*: ([0-9]+) patients, exact order ([0-9]+), same first trial ([0-9]+).*/\2\/\1, \3\/\1/')"
row agent6 "grounding + content checks failing" "0 0 0 0" "$(grep -E 'briefings, [0-9]+ failing' "$L/agent6_dev.log" | sed -E 's/.*briefings, ([0-9]+) failing.*/\1/' | tr '\n' ' ' | sed 's/ $//')"
row agent6 "a6_error (clinician, patient)" "0 0" "$(grep -oE 'a6_error [0-9]+' "$L/agent6_dev.log" | awk '{print $2}' | tr '\n' ' ' | sed 's/ $//')"

# ---------- demo (integration final pipeline) ----------
cd "$W"
"$PY" -m pipeline.build_demo > "$L/demo.log" 2>&1
demo=$(py <<'PY'
import glob, json
jl = lambda p: [json.loads(l) for l in open(p, encoding="utf-8")]
b = {r["trial_id"]: r for r in jl("build/SYN-0010/before/agent3_out.jsonl")}
a = {r["trial_id"]: r for r in jl("build/SYN-0010/after/agent3_out.jsonl")}
key = lambda c: (c["status"], c.get("reason"), c.get("action"))
ch = [f"{c['criterion_id']}->{c['status']}/{c.get('reason')}" for t in a for c in a[t]["criteria"]
      if key(c) != key({x["criterion_id"]: x for x in b[t]["criteria"]}[c["criterion_id"]])]
labels = sum(b[t]["trial_label"] != a[t]["trial_label"] for t in b)
cards = lambda s: sum(len(jl(f"build/SYN-0010/{s}/{p}/cards.jsonl")) for p in ("a5u", "a5j"))
fails = sum(int(l.split(" failing")[0].split()[-1]) for v in json.load(open("data/manifest.json"))["agent6_checks"].values()
            for k in v.values() for l in k)
# same bundles as the integration final build (Release copy in results/), apart from paths, build time and file hashes
def strip(x):
    x = dict(x); x.pop("meta", None)
    if "briefing" in x:
        x["briefing"] = {k: {**v, "evidence": {**v.get("evidence", {}), "sha256": None}} for k, v in x["briefing"].items()}
    return x
same = all(strip(json.load(open(f"data/{n}", encoding="utf-8"))) == strip(json.load(open(f"results/integration_final_data/{n}", encoding="utf-8")))
           for n in ("SYN-0010.before.json", "SYN-0010.after.json", "SYN-0017.before.json"))
print(f"{len(ch)}|{';'.join(ch)}|{labels}|{cards('before')}->{cards('after')}|{fails}|{'same' if same else 'differ'}")
PY
)
IFS='|' read -r dn dlist dlab dcards dfail dsame <<< "$demo"
row demo "SYN-0010 verdicts changed by the answer" "1" "${dn:-}"
row demo "changed verdict" "NCT05428488-E09->UNKNOWN/MISSING" "${dlist:-}"
row demo "SYN-0010 trial labels changed" "0" "${dlab:-}"
row demo "SYN-0010 cards before->after (a5u+a5j)" "24->24" "${dcards:-}"
row demo "Agent 6 checks failing (3 states)" "0" "${dfail:-}"
row demo "bundles = integration final data" "same" "${dsame:-}"
row demo "translations copied from Healthcare-web" "same same" "$(for f in ko.json card_ko.json; do cmp -s "$W/data/$f" "$TRIALTRACE_WEB/data/$f" && printf same || printf differ; [ $f = ko.json ] && printf ' '; done)"

# ---------- test (optional) ----------
if [ -n "${TRIALTRACE_TEST_DIR:-}" ]; then
  TS=$TD/synthetic_test_v11; TE=$TD/evidence_v14_9; TR=$TD/agent3_a3-0.3.0_test
  EVT="$TE/evidence_test_haiku_v14_9.jsonl $TE/evidence_test_variants_haiku_v14_9.jsonl"
  cd "$W/agents/agent3_judge"
  "$PY" eval/score_dev.py "$TR/test_v10_kit149_p07/agent3_out.jsonl" --gold "$TS/gold/gold.jsonl" \
    --criteria "$TS/reference/criteria.jsonl" --evidence "$TE/evidence_test_haiku_v14_9.jsonl" --md "$L/agent3_test.md" > /dev/null 2>&1
  row test "Agent 3 a3-0.3.0 strict match" "80.2%" "$(md '기준 상태 일치 (엄격)' "$L/agent3_test.md")"
  row test "Agent 3 trial label match" "75.6%" "$(md '시험 판정 일치' "$L/agent3_test.md")"
  row test "Agent 3 PASS<->FAIL errors" "12 (0.7%)" "$(grep -m1 -F '반대 방향 오류' "$L/agent3_test.md" | awk -F'|' '{gsub(/[*]/, "", $3); gsub(/^ +| +$/, "", $3); print $3}')"
  cd "$W/agents/agent4_verify"
  for s in "test:patients" "test_variants:patients_variants"; do
    PYTHONPATH=. "$PY" -m agent4 --patients "$TS/input/${s#*:}.jsonl" --trials "$TS/reference/trials.jsonl" \
      --criteria "$TS/reference/criteria.jsonl" --evidence "$TE/evidence_${s%%:*}_haiku_v14_9.jsonl" \
      --verdicts "$TR/${s%%:*}_v10_kit149_p07/agent3_out.jsonl" --out "runs/repro_${s%%:*}" > "$L/agent4_${s%%:*}.log" 2>&1
  done
  read -r t4n t4c t4f t4l t4m <<< "$(a4sum runs/repro_test 2>/dev/null)"
  read -r v4n v4c v4f v4l v4m <<< "$(a4sum runs/repro_test_variants 2>/dev/null)"
  row test "Agent 4 v2 checked / changed (base)" "1778 / 48" "${t4n:-} / ${t4c:-}"
  row test "Agent 4 v2 checked / changed (variants)" "2123 / 56" "${v4n:-} / ${v4c:-}"
  row test "Agent 4 v2 evidence_id_mismatch" "0 0" "${t4m:-} ${v4m:-}"
  A6T=$W/extra/agent6_a6-0.4.0
  SC="$PY $D/eval/eval_variants.py --data $TS --pred \$PRED --ranking \$RANKING"
  a6t() {  # name, agent3 outputs, graphs
    (cd "$A6T" && A3="$2" G="$3" TR="$TS/reference/trials.jsonl" EV="$EVT" O="runs/$1" SCORE_CMD="$SC" bash run_test.sh > "$L/a6_$1.log" 2>&1)
    local s=$A6T/runs/$1/SUMMARY.txt
    echo "$(grep -m1 '4. ranking' "$s" | sed -E 's/.*: ([0-9]+) patients, exact order ([0-9]+), same first trial ([0-9]+).*/\2\/\1, \3\/\1/')|$(grep -oE '"english_outside_parens": [0-9.]+' "$s" | awk '{printf "%.1f%% ", $2*100}' | sed 's/ $//')|$(grep -cE 'briefings, 0 failing' "$s")|$(grep -m1 -o 'MANIFEST OK' "$s")"
  }
  IFS='|' read -r r6 e6 f6 m6 <<< "$(a6t repro_a3 "$TR/test_v10_kit149_p07/agent3_out.jsonl $TR/test_variants_v10_kit149_p07/agent3_out.jsonl" \
                                          "$TR/test_v10_kit149_p07/graph $TR/test_variants_v10_kit149_p07/graph")"
  row test "a6-0.4.0 package = MANIFEST.sha256" "MANIFEST OK" "${m6:-}"
  row test "a6-0.4.0 ranking exact / first (A3)" "39/64, 50/64" "${r6:-}"
  row test "a6-0.4.0 English outside parens" "6.8% 22.9%" "${e6:-}"
  row test "a6-0.4.0 check lines with 0 failing (A3)" "4" "${f6:-}"
  G4=$W/agents/agent4_verify/runs
  IFS='|' read -r r6 e6 f6 m6 <<< "$(a6t repro_a4 "$G4/repro_test/agent3_out.jsonl $G4/repro_test_variants/agent3_out.jsonl" \
                                          "$G4/repro_test/graph $G4/repro_test_variants/graph")"
  row test "a6-0.4.0 ranking exact / first (A3+A4)" "35/64, 49/64" "${r6:-}"
  row test "a6-0.4.0 English outside parens (A3+A4)" "6.8% 22.4%" "${e6:-}"
  row test "a6-0.4.0 check lines with 0 failing (A3+A4)" "4" "${f6:-}"
else
  echo "test     (skipped: set TRIALTRACE_TEST_DIR to the unpacked test_pack)"
fi

echo
echo "logs and outputs: $W  (logs/ = full output of every step)"
(( KNOWN > 0 )) && echo "KNOWN lines: $KNOWN (the frozen version gives this value; the expected value is an older report number, REPRODUCE.md 5장)"
if (( FAILS > 0 )); then echo "DIFF lines: $FAILS"; exit 1; fi
echo "no unexplained differences"
