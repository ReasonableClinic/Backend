"""Freeze the glossary before test scoring: record its sha256 in agent6/GLOSSARY_FREEZE.json.

  python3 scripts/freeze_glossary.py            # write the freeze record (refuses if one exists and differs)
  python3 scripts/freeze_glossary.py --check    # verify the file still matches

After freezing, every briefing run checks the hash (agent6/glossary.py) and stops if the file was edited.
Each briefing also records glossary {mode, sha256} so the scored outputs show which table they used.
"""
import argparse, csv, datetime, json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from agent6 import glossary as GL  # noqa: E402

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--check", action="store_true")
a = ap.parse_args()
path = GL.DEFAULT
rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
rec = {"file": os.path.basename(path), "sha256": GL.sha256(path), "rows": len(rows),
       "reviewed": sum(r.get("status") == "reviewed" for r in rows), "frozen_at": str(datetime.date.today())}
if a.check:
    fz = json.load(open(GL.FREEZE, encoding="utf-8")) if os.path.exists(GL.FREEZE) else None
    ok = bool(fz) and fz["sha256"] == rec["sha256"]
    print(("OK " if ok else "MISMATCH ") + json.dumps(fz, ensure_ascii=False))
    sys.exit(0 if ok else 1)
if os.path.exists(GL.FREEZE) and json.load(open(GL.FREEZE))["sha256"] != rec["sha256"]:
    sys.exit("a different freeze record exists; remove agent6/GLOSSARY_FREEZE.json deliberately to re-freeze")
json.dump(rec, open(GL.FREEZE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("frozen", json.dumps(rec, ensure_ascii=False))
