import json,sys
gold_p,pred_p=sys.argv[1],sys.argv[2]
pats={d["doc_id"]:d for p in map(json.loads,open("data/dev/input/patients.jsonl")) for d in p["documents"]}
pred={}
for r in map(json.loads,open(pred_p)): pred.setdefault((r["patient_id"],r["source"]["doc_id"]),[]).append(r["source"]["span"])
seen=set()
for g in map(json.loads,open(gold_p)):
    used={e for c in g["criteria"] for e in c["supporting_evidence"]}
    for e in g["gold_evidence"]:
        k=(g["patient_id"],e["doc_id"],tuple(e["span"]))
        if e["gold_ev_id"] not in used or k in seen: continue
        seen.add(k); s,t=e["span"]; best=None;bi=0
        for a,b in pred.get(k[:2],[]):
            ov=max(0,min(t,b)-max(s,a))
            if ov:
                i=ov/(max(t,b)-min(s,a))
                if i>bi: bi,best=i,(a,b)
        if bi<0.5:
            txt=pats[e["doc_id"]]["text"]
            print(f"{bi:.2f} G:{e['text'][:90]!r}\n     P:{txt[best[0]:best[1]][:90]!r}" if best else f"MISS {e['text'][:90]!r}")
