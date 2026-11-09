"""Count evidence that says true for something its own sentence denies ('Resp: no cough' -> cough true)."""
import json, re, sys, collections
sys.path.insert(0, "agent2")
import rules as R
P = {d["doc_id"]: d["text"] for p in map(json.loads, open("data/dev/input/patients.jsonl")) for d in p["documents"]}
c = collections.Counter(); ex = []
for e in map(json.loads, open(sys.argv[1])):
    if e["concept"] not in ("diagnosis", "symptom_finding", "medication", "procedure") or e["value"] is not True:
        continue
    c["true facts"] += 1
    t = e["source"]["text"]
    term = (e.get("term") or "").strip()
    body = R.LABEL_RE.sub("", t, count=1)
    if not R.NEG_CUE.search(body):
        continue
    c["true facts in a sentence with a denial"] += 1
    key = re.split(r"[\s,;:]+", term)[0] if term else ""
    i = t.lower().find(term.lower()[:25]) if term else -1
    if i < 0 and key:
        i = t.lower().find(key.lower())
    tp = R.clause_polarity(term) if term else ("", "")
    if term and tp[1] and not tp[0]:              # the term itself is a denial: "no cough or dyspnea" = true
        c["FLIP: term is a denial"] += 1
        ex.append(f'{e["concept"]}={e["value"]} [{term[:30]}] by {e["extracted_by"]} | {t[:90]}')
    elif i >= 0 and R.term_negated(t, i):
        c["FLIP: term inside a denial"] += 1
        ex.append(f'{e["concept"]}={e["value"]} [{term[:30]}] by {e["extracted_by"]} | {t[:90]}')
    elif i < 0:
        whole_neg = R.clause_polarity(t)
        if whole_neg[1] and not whole_neg[0]:
            c["FLIP: whole sentence denied"] += 1
            ex.append(f'{e["concept"]}={e["value"]} [{term[:30]}] by {e["extracted_by"]} | {t[:90]}')
print(dict(c))
for x in ex[:int(sys.argv[2]) if len(sys.argv) > 2 else 0]:
    print("  ", x)
