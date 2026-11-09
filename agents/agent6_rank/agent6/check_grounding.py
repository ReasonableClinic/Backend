"""Check briefings: every sentence is tied to the graph (or a fixed rule), refs exist, patient text keeps the rules.

  python3 -m agent6.check_grounding runs/brief_dev --graphs K/dev/agent3_out_a031/graph [--strict]

Per file: sentences, unlinked (no ref, kind fact/heading), bad refs (id not in the graph, not a rule:/gloss:, and not an ev: id of the --evidence files), and for
audience=patient: missing required rule sentences, banned phrases, and trial ids that are not in the ranking.
Target: unlinked 0, bad refs 0, banned 0. `meta` sentences (patient id, date) are allowed without refs.
Exit code 1 with --strict when any file fails. This checks links, not truth: a linked sentence can still misstate
its node (for that, compare numbers/dates in the text with the node, or use a second-model or human check).
"""
import argparse, glob, json, os, re, sys

from . import keyinfo as KI
from .graph import Graph
from .glossary import ids as gloss_ids
from .rules import BANNED, FIXED, REQUIRED


def check(doc, g):
    GLOSS = gloss_ids()
    ids = set(g.nodes) | KI.outside_evidence_ids(g.patient_id)   # Agent 2 rows outside the graph (same version)
    unlinked, bad, banned = [], [], []
    for i, s in enumerate(doc["sentences"]):
        if s.get("kind") == "meta":
            continue
        if not s.get("refs"):
            unlinked.append(i)
        for r in s.get("refs", []):
            if not (r in ids or r in FIXED or r in GLOSS):
                bad.append((i, r))
        if doc.get("audience") == "patient":
            banned += [(i, w) for w in BANNED if w in s["text"]]
    missing_rules = []
    if doc.get("audience") == "patient":
        used = {r for s in doc["sentences"] for r in s.get("refs", [])}
        missing_rules = [r for r in REQUIRED if r not in used]
    stray = sorted(set(re.findall(r"NCT\d{8}", " ".join(s["text"] for s in doc["sentences"]))) - set(doc.get("ranking", [])) - set(doc.get("also_mentioned", [])))
    return {"sentences": len(doc["sentences"]), "unlinked": unlinked, "bad_refs": bad, "banned": banned,
            "missing_rules": missing_rules, "trials_not_ranked": stray}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--evidence", nargs="*", default=[], help="Agent 2 evidence jsonl: their ev: ids are valid refs")
    a = ap.parse_args(argv)
    KI.load_evidence(a.evidence, a.graphs)
    fails = tot = 0
    agg = {"sentences": 0, "unlinked": 0, "bad_refs": 0, "banned": 0, "missing_rules": 0, "trials_not_ranked": 0}
    for f in sorted(glob.glob(os.path.join(a.folder, "*.json"))):
        doc = json.load(open(f, encoding="utf-8"))
        gp = next(os.path.join(d, doc["graph_file"]) for d in a.graphs if os.path.exists(os.path.join(d, doc["graph_file"])))
        r = check(doc, Graph.load(gp))
        tot += 1
        for k in agg:
            agg[k] += r[k] if k == "sentences" else len(r[k])
        bad = any(r[k] for k in ("unlinked", "bad_refs", "banned", "missing_rules"))
        fails += bad
        if bad:
            print(f"  ! {os.path.basename(f)}: " + ", ".join(f"{k} {r[k][:3]}" for k in ("unlinked", "bad_refs", "banned", "missing_rules") if r[k]))
    print(f"{tot} briefings, {fails} failing | " + ", ".join(f"{k} {v}" for k, v in agg.items()))
    if a.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
