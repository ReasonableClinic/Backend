"""Put externally produced LLM answers into the Agent 3 cache.

  python3 -m agent3.ingest --results batch_results.jsonl   # Message Batches API results file
  python3 -m agent3.ingest --replies-dir replies/          # one <custom_id>.txt (raw reply) per request

custom_id is the cache key written by `--llm export`. After ingesting, re-run with
`--llm replay --model <same model>`; the pairs then score exactly as if called live.
"""
import argparse
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def save(cache, key, reply, meta):
    with open(os.path.join(cache, key + ".json"), "w", encoding="utf-8") as f:
        json.dump(dict(meta, reply=reply), f, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(HERE, "runs", "llm_cache"))
    ap.add_argument("--results")
    ap.add_argument("--replies-dir")
    a = ap.parse_args()
    meta = {}
    req = os.path.join(a.cache, "export_requests.jsonl")
    if os.path.exists(req):
        for line in open(req, encoding="utf-8"):
            r = json.loads(line)
            meta[r["custom_id"]] = dict(r.get("meta", {}), model=r["params"]["model"])
    n = bad = 0
    if a.results:
        for line in open(a.results, encoding="utf-8"):
            r = json.loads(line)
            res = r.get("result", {})
            if res.get("type") != "succeeded":
                bad += 1
                continue
            text = "".join(b.get("text", "") for b in res["message"]["content"] if b.get("type") == "text")
            save(a.cache, r["custom_id"], text, meta.get(r["custom_id"], {}))
            n += 1
    if a.replies_dir:
        for fn in sorted(os.listdir(a.replies_dir)):
            if fn.endswith(".txt"):
                key = fn[:-4]
                save(a.cache, key, open(os.path.join(a.replies_dir, fn), encoding="utf-8").read(), meta.get(key, {}))
                n += 1
    print(f"ingested {n} replies into {a.cache}" + (f", {bad} failed requests skipped" if bad else ""))


if __name__ == "__main__":
    main()
