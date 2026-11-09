#!/usr/bin/env bash
# Rebuild the shipped dev_out/ (template briefings + ranking) with this package's code and frozen glossary.
# Needs the dev kit (for_agent456_v6) next to this folder; run_dev.sh does the work, this copies its outputs.
set -euo pipefail
cd "$(dirname "$0")/.."
env -u AGENT6_GLOSSARY bash run_dev.sh
rm -rf dev_out && mkdir -p dev_out
cp -r runs/brief_dev dev_out/briefing
cp runs/rank_dev/ranking.jsonl dev_out/ranking.jsonl
python3 - <<'PY'
import glob, json
docs = [json.load(open(p, encoding="utf-8")) for p in glob.glob("dev_out/briefing/*.patient.json")]
print("dev_out:", len(docs), "patient briefings | glossary sha256", sorted({d["glossary"]["sha256"] for d in docs}),
      "| evidence", sorted({(d.get("evidence") or {}).get("sha256") for d in docs}))
PY
