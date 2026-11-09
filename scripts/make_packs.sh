#!/usr/bin/env bash
# Build the two Release zips from the frozen packages (team-internal; evaluators only unpack the zips).
#   S=~/Downloads/stage1_patients bash scripts/make_packs.sh [out folder]
# replay_pack.zip -> Backend Release  : unpacked over the repo root (same paths as the repo), dev only.
# test_pack.zip   -> data-eval Release: unpacked anywhere, TRIALTRACE_TEST_DIR points at it.
# Each zip carries MANIFEST.txt (path, size, sha256). The script stops if a key, an ID map or a test patient ID
# ends up in replay_pack, or a key in test_pack.
set -euo pipefail
S=${S:-$HOME/Downloads/stage1_patients}
INTEG_ZIP=${INTEG_ZIP:-$HOME/Downloads/통합_최종.zip}     # integration final (11/09), replaces backend-0.1.1
OUT=$(mkdir -p "${1:-dist}" && cd "${1:-dist}" && pwd)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
R=$TMP/replay; T=$TMP/test; X=$TMP/src
mkdir -p "$R" "$T" "$X"

# source zips, frozen versions (sha256 first 12 characters)
check() { [ "$(shasum -a 256 "$S/$1" | cut -c1-12)" = "$2" ] || { echo "STOP: $1 is not $2"; exit 1; }; }
check agent1_workspace/received/agent1.zip c456417035d0
check agent2_workspace/received/agent3_test_kit_v14_9.zip 28b920646792
check agent3_workspace/received/agent3_a3-0.3.1.zip 74c01e9adcb2
check agent5_workspace/received/agent5_a5j-0.3.1.zip bec3d9a02ad6
check agent6_workspace/received/agent6_a6-0.4.0.zip 96e9a3c9f352
[ "$(shasum -a 256 "$INTEG_ZIP" | cut -c1-12)" = a2456c45e1cf ] || { echo "STOP: $INTEG_ZIP is not 통합 최종 (a2456c45e1cf)"; exit 1; }
check handoff/for_agent456_v6.zip d353b4d75b4d
up() { mkdir -p "$X/$1"; unzip -q "$2" -d "$X/$1"; rm -rf "$X/$1/__MACOSX"; }
up a1 "$S/agent1_workspace/received/agent1.zip"
up a2t "$S/agent2_workspace/received/agent3_test_kit_v14_9.zip"
up a3 "$S/agent3_workspace/received/agent3_a3-0.3.1.zip"
up a3t "$S/agent3_workspace/received/agent3_test_v10_kit149_p07.zip"
up a5 "$S/agent5_workspace/received/agent5_a5j-0.3.1.zip"
up a6t "$S/agent6_workspace/received/agent6_a6-0.4.0.zip"
up be "$INTEG_ZIP"
up kit "$S/handoff/for_agent456_v6.zip"
up test "$S/handoff/synthetic_test_v11.zip"
KIT=$X/kit/for_agent456_v6; A3=$X/a3/agent3_a3-0.3.1
clean() { find "$1" \( -name .DS_Store -o -name __pycache__ -o -name '*.bak' \) -prune -exec rm -rf {} +; }

# test patient IDs (base + variants)
python3 - "$X/test/synthetic_test_v11/input" > "$TMP/test_ids.txt" <<'PY'
import json, sys
for f in ("patients.jsonl", "patients_variants.jsonl"):
    for line in open(f"{sys.argv[1]}/{f}", encoding="utf-8"):
        print(json.loads(line)["patient_id"])
PY

# ---------- replay_pack (paths = repo paths) ----------
mkdir -p "$R/data" "$R/agents/agent1_criteria" "$R/agents/agent3_judge" "$R/agents/agent5_acquire" \
         "$R/results" "$R/extra"
cp -R "$KIT/dev" "$R/data/dev"
cp "$KIT/README.md" "$R/data/dev/KIT_README_for_agent456_v6.md"
cp -R "$X/a1/agent1/cache" "$X/a1/agent1/runs" "$R/agents/agent1_criteria/"
cp -R "$A3/runs" "$R/agents/agent3_judge/"
cp -R "$X/a5/runs" "$R/agents/agent5_acquire/"
mkdir -p "$R/results/integration_final_data"; cp "$X"/be/data/*.json "$R/results/integration_final_data/"
cp -R "$X/a6t/agent6_a6-0.4.0" "$R/extra/agent6_a6-0.4.0"     # frozen Agent 6 for the test step (code only)
rm -rf "$R/extra/agent6_a6-0.4.0/runs"

# Agent 3 cache files and outputs that touch a test patient go to test_pack
mkdir -p "$T/agent3_llm_cache_test"
python3 - "$R/agents/agent3_judge/runs" "$TMP/test_ids.txt" "$T/agent3_llm_cache_test" <<'PY'
import os, re, shutil, sys
runs, ids, dst = sys.argv[1], open(sys.argv[2]).read().split(), sys.argv[3]
pat = re.compile(r"\b(" + "|".join(map(re.escape, ids)) + r")\b")
moved = 0
for base, _, files in os.walk(runs):
    for f in files:
        p = os.path.join(base, f)
        if pat.search(open(p, encoding="utf-8", errors="ignore").read()):
            rel = os.path.relpath(p, runs)
            out = os.path.join(dst, os.path.basename(p)) if rel.startswith("llm_cache" + os.sep) else os.path.join(dst, "_runs", rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.move(p, out)
            moved += 1
print(f"moved {moved} Agent 3 files with test patient IDs to test_pack")
PY
clean "$R"

# ---------- test_pack ----------
cp -R "$X/test/synthetic_test_v11" "$T/"
cp "$S/stage2/runs/agent6_test_scores_1031/ranking_gold_variants_test_v9_built.jsonl" \
   "$T/synthetic_test_v11/gold/ranking_gold_variants.jsonl"      # eval_variants.py reads this name
mkdir -p "$T/evidence_v14_9"
cp "$X"/a2t/agent3_kit/evidence_test_haiku_v14_9.jsonl "$X"/a2t/agent3_kit/evidence_test_variants_haiku_v14_9.jsonl \
   "$X/a2t/TEST_KIT_README.md" "$T/evidence_v14_9/"
cp -R "$X/a3t" "$T/agent3_a3-0.3.0_test"
mkdir -p "$T/scores"
cp -R "$S/stage2/runs/agent3_test_scores_1027" "$S/stage2/runs/agent6_test_scores_1031" "$T/scores/"
clean "$T"

# ---------- checks ----------
KEYS='sk-ant-|sk-or-|sk-lf-|pk-lf-'
for d in "$R" "$T"; do
  if grep -rIlE "$KEYS" "$d"; then echo "STOP: key-like string above"; exit 1; fi
  if find "$d" \( -name '.env' -o -name 'id_map*' -o -name '*private*' -o -name 'patients_eval*' -o -name 'topics_eval*' \
       -o -iname '*langfuse*' \) | grep .; then echo "STOP: forbidden file above"; exit 1; fi
done
if grep -rIlwFf "$TMP/test_ids.txt" "$R" | grep .; then echo "STOP: test patient ID in replay_pack"; exit 1; fi
if find "$R" -path '*gold*' -name '*test*' | grep .; then echo "STOP: test gold in replay_pack"; exit 1; fi
echo "checks: no keys, no ID maps, no test patient IDs in replay_pack"

manifest() {
  ( cd "$1" && find . -type f ! -name MANIFEST.txt | sed 's|^\./||' | LC_ALL=C sort | while read -r f; do
      printf '%s\t%s\t%s\n' "$(shasum -a 256 "$f" | cut -d' ' -f1)" "$(wc -c < "$f" | tr -d ' ')" "$f"; done ) > "$1/MANIFEST.txt.body"
  { echo "# $2  built $(date +%F)  files $(wc -l < "$1/MANIFEST.txt.body" | tr -d ' ')"
    echo "# sha256<TAB>bytes<TAB>path"; cat "$1/MANIFEST.txt.body"; } > "$1/MANIFEST.txt"
  rm "$1/MANIFEST.txt.body"
}
manifest "$R" replay_pack; manifest "$T" test_pack
rm -f "$OUT/replay_pack.zip" "$OUT/test_pack.zip"
( cd "$R" && zip -qrX "$OUT/replay_pack.zip" . )
( cd "$T" && zip -qrX "$OUT/test_pack.zip" . )
for z in replay_pack test_pack; do
  echo "$z.zip  $(du -h "$OUT/$z.zip" | cut -f1)  sha256 $(shasum -a 256 "$OUT/$z.zip" | cut -d' ' -f1)"
done
