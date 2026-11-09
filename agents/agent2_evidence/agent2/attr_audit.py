"""Step 2 audit table: gold evidence sentences that carry a negation / family / suspicion / plan cue, with the
facts our runs produced on them and the criterion that used them (text + expected status)."""
import json, re, sys, collections
NEG = re.compile(r"\b(no|not|denies|denied|never|without|negative|non-?reactive|none|NKDA|undetectable|absent|ruled out)\b", re.I)
FAM = re.compile(r"\b(mother|father|sister|brother|sibling|aunt|uncle|grand\w*|cousin|family history|FHx|relative'?s?|parents?|son|daughter)\b", re.I)
SUS = re.compile(r"\b(suspect\w*|possible|possibly|probable|presumed|presumptive|likely|features of|rule out|r/o|concern for|cannot exclude|under work-?up|query|suggestive|consistent with)\b|\?", re.I)
PLAN = re.compile(r"\b(plan\w*|discuss\w*|consider\w*|option\w*|recommend\w*|will|would|candidate|referr\w*|scheduled|start|starting|declined|refused|pending|awaiting|not yet)\b", re.I)
run = sys.argv[1]
crit = {c["criterion_id"]: c for c in map(json.loads, open("data/dev/reference/criteria.jsonl"))}
pred = collections.defaultdict(list)
for e in map(json.loads, open(run)):
    pred[e["source"]["doc_id"]].append(e)
rows, seen = [], set()
for g in map(json.loads, open("data/dev/gold/gold.jsonl")):
    use = collections.defaultdict(list)
    for c in g["criteria"]:
        for ev in c["supporting_evidence"]:
            use[ev].append((c["criterion_id"], c["expected_status"]))
    for e in g["gold_evidence"]:
        if e["gold_ev_id"] not in use:
            continue
        cues = [n for n, rx in (("neg", NEG), ("fam", FAM), ("sus", SUS), ("plan", PLAN)) if rx.search(e["text"])]
        if not cues:
            continue
        k = (g["patient_id"], e["doc_id"], tuple(e["span"]))
        s, t = e["span"]
        facts = [p for p in pred[e["doc_id"]] if p["patient_id"] == g["patient_id"] and
                 min(t, p["source"]["span"][1]) > max(s, p["source"]["span"][0])]
        if k in seen:
            for r in rows:
                if r["key"] == k:
                    r["criteria"] += [(cid, st, crit[cid]["original_text"][:110]) for cid, st in use[e["gold_ev_id"]]]
            continue
        seen.add(k)
        rows.append({"key": k, "pid": g["patient_id"], "doc": e["doc_id"], "text": e["text"], "cues": cues,
                     "criteria": [(cid, st, crit[cid]["original_text"][:110]) for cid, st in use[e["gold_ev_id"]]],
                     "facts": [{"c": p["concept"], "v": p["value"], "cert": p["certainty"], "subj": p["subject"],
                                "st": (p.get("detail") or {}).get("status"), "term": p.get("term"), "by": p["extracted_by"]}
                               for p in facts]})
json.dump(rows, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
print(len(rows), "cue sentences;", collections.Counter(c for r in rows for c in r["cues"]))
