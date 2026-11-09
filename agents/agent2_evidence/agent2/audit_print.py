import json, sys
L = json.load(open("runs/audit_llm.json"))
Rr = {json.dumps(r["key"]): r for r in json.load(open("runs/audit_rule.json"))}
want = set(sys.argv[1].split(","))
only = len(sys.argv) > 2 and sys.argv[2] == "only"


def fs(fl):
    out = []
    for f in fl:
        s = f'{f["c"]}={str(f["v"])[:12]}'
        if f["cert"] != "confirmed": s += "/" + f["cert"][:4]
        if f["subj"] == "family": s += "/FAM"
        if f["st"] and f["st"] != "observed": s += "/" + f["st"]
        if f["term"]: s += "[" + f["term"][:28] + "]"
        if f["by"] == "rule": s += "(r)"
        out.append(s)
    return "; ".join(out)


n = 0
for r in L:
    cues = set(r["cues"])
    if not cues & want or (only and cues - want):
        continue
    n += 1
    print(f'#{n} {r["doc"]} [{",".join(r["cues"])}] {r["text"][:160]!r}')
    for cid, st, ct in r["criteria"][:2]:
        print(f'    crit {cid} {st}: {ct}')
    print("    LLM :", fs(r["facts"])[:420])
    print("    RULE:", fs(Rr[json.dumps(r["key"])]["facts"])[:220])
