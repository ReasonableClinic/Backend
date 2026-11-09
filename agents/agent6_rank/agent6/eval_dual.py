"""Dual-reference scoring of briefings: the same briefing against the graph (Agent 6's own job) and against dev gold
(the whole pipeline). Splits "Agent 6 misstated the graph" from "the graph itself was wrong upstream".

  python3 -m agent6.eval_dual runs/brief_dev --graphs G1 G2 --trials K/dev/reference/trials.jsonl --gold-dir K/dev/gold

Sentence level (fact sentences that cite at least one dec: or label: node):
  a6_error        check_content flags the sentence (number / date / verdict word vs its own nodes)
  upstream_error  sentence is faithful to the graph, but a cited decision status or trial label differs from gold
  ok              faithful to the graph and the cited nodes agree with gold
Trial level (trials the briefing covers): label right vs gold; trials gold ranks that the briefing leaves out.
Coverage (recall of open criteria = UNKNOWN/CONFLICT, inclusion and exclusion, of covered trials):
  vs graph  open criteria in the graph that some sentence cites (Agent 6 completeness)
  vs gold   open criteria in gold that some sentence cites *and* the graph shows as open (what the reader is told)
upstream_error is "any cited node wrong", so a patient sentence that bundles many exclusion decisions counts once;
"cited decisions wrong" gives the per-decision rate.
"""
import argparse, glob, json, os
from collections import Counter, defaultdict

from .check_content import check_sentence
from .graph import Graph
from .rank import read_jsonl

OPEN = ("UNKNOWN", "CONFLICT")


def load_gold(gold_dir):
    gold, grank = {}, {}
    for f in ("gold.jsonl", "gold_variants.jsonl"):
        p = os.path.join(gold_dir, f)
        if os.path.exists(p):
            for r in read_jsonl(p):
                gold[(r["patient_id"], r["trial_id"])] = {"label": r["trial_label"],
                                                          "crit": {c["criterion_id"]: c["expected_status"] for c in r["criteria"]}}
    for f in ("ranking_gold.jsonl", "ranking_gold_variants.jsonl"):
        p = os.path.join(gold_dir, f)
        if os.path.exists(p):
            for r in read_jsonl(p):
                grank[r["patient_id"]] = r["ranking"]
    return gold, grank


def score_doc(doc, g, trials, gold, grank, top=5):
    pid = doc["patient_id"]
    res = Counter()
    cited = set()
    for s in doc["sentences"]:
        if s.get("kind") not in ("fact", "heading"):
            continue
        refs = s.get("refs", [])
        cited |= set(refs)
        decs = [g.nodes[r] for r in refs if r.startswith("dec:") and r in g.nodes]
        labs = [g.nodes[r] for r in refs if r.startswith("label:") and r in g.nodes]
        if not decs and not labs:
            continue
        res["sentences"] += 1
        if check_sentence(s, g, trials, doc.get("as_of") or g.as_of, doc.get("ranking")):
            res["a6_error"] += 1
            continue
        wrong = False
        for d in decs:
            gs = gold.get((pid, d["trial_id"]), {}).get("crit", {}).get(d["criterion_id"])
            res["dec_refs"] += 1
            res["dec_refs_wrong"] += gs is not None and gs != d["status"]
            wrong |= gs is not None and gs != d["status"]
        for l in labs:
            tid = l["id"].split(":", 1)[1]
            gl = gold.get((pid, tid), {}).get("label")
            wrong |= gl is not None and gl != l.get("label")
        res["upstream_error" if wrong else "ok"] += 1
    covered = doc.get("ranking", [])
    for tid in covered:
        res["trials"] += 1
        lab = g.label(tid)
        gl = gold.get((pid, tid), {}).get("label")
        res["trial_label_right"] += int(gl is not None and lab is not None and gl == lab.get("label"))
        res["trial_not_in_gold_ranking"] += int(tid not in grank.get(pid, []))
        for d in g.decisions(tid):
            hit = d["id"] in cited
            if d["status"] in OPEN:
                res["open_graph"] += 1
                res["open_graph_cited"] += hit
            gs = gold.get((pid, tid), {}).get("crit", {}).get(d["criterion_id"])
            if gs in OPEN:   # told to the reader as open = cited and shown as UNKNOWN/CONFLICT
                res["open_gold"] += 1
                res["open_gold_cited"] += hit and d["status"] in OPEN
    gr = grank.get(pid, [])
    res["gold_trials_left_out"] += sum(1 for t in (gr[:top] if doc["audience"] == "patient" else gr) if t not in covered)
    return res


def report(agg):
    n = max(agg["sentences"], 1)
    lines = [f"sentences citing dec/label {agg['sentences']}: ok {agg['ok']} ({agg['ok'] / n:.1%}), "
             f"upstream_error {agg['upstream_error']} ({agg['upstream_error'] / n:.1%}), a6_error {agg['a6_error']} ({agg['a6_error'] / n:.1%}); "
             f"cited decisions wrong vs gold {agg['dec_refs_wrong']}/{agg['dec_refs']} ({agg['dec_refs_wrong'] / max(agg['dec_refs'], 1):.1%})",
             f"trials {agg['trials']}: label right vs gold {agg['trial_label_right']}, not in gold ranking "
             f"{agg['trial_not_in_gold_ranking']}, gold-ranked trials left out {agg['gold_trials_left_out']}",
             f"open-criteria coverage: vs graph {agg['open_graph_cited']}/{agg['open_graph']}"
             f" ({agg['open_graph_cited'] / max(agg['open_graph'], 1):.1%}), vs gold {agg['open_gold_cited']}/{agg['open_gold']}"
             f" ({agg['open_gold_cited'] / max(agg['open_gold'], 1):.1%})"]
    return "\n  ".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--gold-dir", required=True)
    ap.add_argument("--json", help="write per-briefing rows here")
    a = ap.parse_args(argv)
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    gold, grank = load_gold(a.gold_dir)
    agg = defaultdict(Counter)
    rows = []
    for f in sorted(glob.glob(os.path.join(a.folder, "*.json"))):
        doc = json.load(open(f, encoding="utf-8"))
        gp = next(os.path.join(d, doc["graph_file"]) for d in a.graphs if os.path.exists(os.path.join(d, doc["graph_file"])))
        r = score_doc(doc, Graph.load(gp), trials, gold, grank)
        agg[doc["audience"]].update(r)
        rows.append({"file": os.path.basename(f), **r})
    for aud in sorted(agg):
        print(f"[{aud}] " + report(agg[aud]))
    if a.json:
        json.dump(rows, open(a.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
