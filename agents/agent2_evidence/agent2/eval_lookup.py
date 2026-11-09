"""How often does EvidenceIndex.for_criterion return the gold supporting evidence of a criterion (top k)?"""
import json, sys, collections
sys.path.insert(0, "agent2")
from evidence_index import EvidenceIndex
ev, k = sys.argv[1], int(sys.argv[2])
ix = EvidenceIndex(ev, "data/dev/input/patients.jsonl")
crit = {c["criterion_id"]: c for c in map(json.loads, open(sys.argv[4] if len(sys.argv) > 4 else "data/dev/reference/criteria.jsonl"))}
n = hit = 0; per = collections.Counter(); miss = []; size = []
for g in map(json.loads, open("data/dev/gold/gold.jsonl")):
    gev = {e["gold_ev_id"]: e for e in g["gold_evidence"]}
    for c in g["criteria"]:
        if not c["supporting_evidence"]:
            continue
        n += 1
        hits = ix.for_criterion(g["patient_id"], crit[c["criterion_id"]], k)
        ok = any(any(h["source"]["doc_id"] == gev[i]["doc_id"] and
                     min(h["source"]["span"][1], gev[i]["span"][1]) > max(h["source"]["span"][0], gev[i]["span"][0])
                     for h in hits) for i in c["supporting_evidence"])
        hit += ok; per[c["expected_status"]] += ok; per["n_" + c["expected_status"]] += 1
        size.append(len(hits))
        if not ok: miss.append((crit[c["criterion_id"]]["original_text"][:80], gev[c["supporting_evidence"][0]]["text"][:60]))
size.sort()
print(f"returned per criterion: median {size[len(size)//2]}, p90 {size[int(len(size)*0.9)]}, max {size[-1]}")
print(f"top-{k}: criteria whose gold evidence is among the returned evidence: {hit}/{n} = {hit/n:.3f}",
      {s: f"{per[s]}/{per['n_'+s]}" for s in ("PASS", "FAIL", "UNKNOWN", "CONFLICT") if per['n_'+s]})
for m in miss[:int(sys.argv[3]) if len(sys.argv) > 3 else 0]: print("  miss:", m)
