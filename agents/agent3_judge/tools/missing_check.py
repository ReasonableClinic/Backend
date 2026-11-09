#!/usr/bin/env python3
"""Agent 3 left a criterion UNKNOWN/MISSING but the gold decided it: is the fact in Agent 2's evidence?

For every such criterion (dev, gold PASS/FAIL) lists the gold supporting sentences, the Agent 2 evidence at those
places (id, concept, value), and whether `EvidenceIndex.for_criterion` returns any of them. Classes:

  in_lookup        Agent 2 evidence at a gold place and `for_criterion` returns it   -> Agent 3 had it in view
  agent2_only      Agent 2 evidence at a gold place, not returned by `for_criterion` -> lookup / prompt input
  no_gold_place    the gold cites no sentence (decided from neighbours or silence)   -> judging rule
  agent2_missing   the gold cites a sentence and Agent 2 has nothing there          -> Agent 2

    python3 code/missing_check.py --agent3 runs/X/agent3_out.jsonl --gold data/dev/gold/gold.jsonl \
        --evidence agent3_kit/evidence_dev_haiku_v14_9.jsonl --criteria data/dev/reference_1b/criteria.jsonl \
        --patients data/dev/input/patients.jsonl --out missing_check.csv
"""
import argparse, collections, csv, json, os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent2"))
from evidence_index import EvidenceIndex  # noqa: E402


def L(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent3", required=True, help="agent3_out.jsonl")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--criteria", required=True, help="①-b criteria.jsonl")
    ap.add_argument("--patients", required=True)
    ap.add_argument("--out", default="missing_check.csv")
    ap.add_argument("--reasons", default="MISSING", help="comma-separated Agent 3 reasons to check (e.g. MISSING,UNSUPPORTED)")
    a = ap.parse_args()
    reasons = set(a.reasons.split(","))
    crit = {c["criterion_id"]: c for c in L(a.criteria)}
    ix = EvidenceIndex(a.evidence, a.patients)
    by_pat = collections.defaultdict(list)
    for e in L(a.evidence):
        by_pat[e["patient_id"]].append(e)
    gold = {(g["patient_id"], g["trial_id"]): g for g in L(a.gold)}
    rows, cls = [], collections.Counter()
    for r in L(a.agent3):
        g = gold.get((r["patient_id"], r["trial_id"]))
        if not g:
            continue
        gc = {c["criterion_id"]: c for c in g["criteria"]}
        gev = {e["gold_ev_id"]: e for e in g["gold_evidence"]}
        for c in r["criteria"]:
            k = gc.get(c["criterion_id"])
            if not k or k["expected_status"] not in ("PASS", "FAIL"):
                continue
            if c.get("status") != "UNKNOWN" or c.get("reason") not in reasons:
                continue
            sup = [gev[x] for x in k.get("supporting_evidence", []) if x in gev]
            at = [e for e in by_pat[r["patient_id"]] for s in sup
                  if e["source"]["doc_id"] == s["doc_id"] and e["source"]["span"][0] < s["span"][1]
                  and s["span"][0] < e["source"]["span"][1]]
            seen = set()
            at = [e for e in at if not (e["evidence_id"] in seen or seen.add(e["evidence_id"]))]
            cr = crit.get(c["criterion_id"], {"criterion_id": c["criterion_id"]})
            got = {e["evidence_id"] for e in ix.for_criterion(r["patient_id"], cr)} if cr.get("original_text") else set()
            hit = [e for e in at if e["evidence_id"] in got]
            kind = ("no_gold_place" if not sup else "agent2_missing" if not at else
                    "in_lookup" if hit else "agent2_only")
            cls[kind] += 1
            rows.append({
                "class": kind, "patient_id": r["patient_id"], "criterion_id": c["criterion_id"],
                "type": cr.get("type"), "gold": k["expected_status"], "agent3": f"{c.get('status')}/{c.get('reason')}",
                "criterion": (cr.get("original_text") or "")[:200], "concept_1b": cr.get("concept"),
                "gold_sentences": " | ".join(s["text"][:90] for s in sup),
                "agent2_at_gold": " ; ".join(f"{e['evidence_id']} {e['concept']}={json.dumps(e['value'], ensure_ascii=False)[:30]}"
                                            for e in at[:6]),
                "returned_by_for_criterion": " ".join(e["evidence_id"] for e in hit[:6]),
                "agent3_cited": " ".join(c.get("evidence_ids") or []),
            })
    with open(a.out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["class"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda x: (x["class"], x["patient_id"], x["criterion_id"])))
    print(f"{len(rows)} criteria: {dict(cls)} -> {a.out}")


if __name__ == "__main__":
    main()
