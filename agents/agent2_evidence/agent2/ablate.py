import json,subprocess,sys,collections,tempfile,os
E=[json.loads(l) for l in open(sys.argv[1])]
def score(rows):
    f=tempfile.NamedTemporaryFile("w",delete=False,suffix=".jsonl")
    for r in rows: f.write(json.dumps(r)+"\n")
    f.close()
    o=subprocess.run(["python3","code/eval_evidence.py","--gold","data/dev/gold/gold.jsonl","--pred",f.name,"--misses","0"],capture_output=True,text=True).stdout
    os.unlink(f.name); return [l for l in o.splitlines() if l.startswith("recall")]
print("all",len(E),score(E))
for k,v in collections.Counter((e["concept"]) for e in E).most_common(12):
    rest=[e for e in E if e["concept"]!=k]
    print(f"-{k:18}{v:5}",score(rest)[0])
