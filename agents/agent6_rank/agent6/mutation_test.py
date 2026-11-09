"""Mutation test for check_content: in each non-meta sentence change one date (the day) or else one number, and count
how often check_content flags the changed sentence. Detection rate, not a guarantee.

  python3 -m agent6.mutation_test runs/brief_dev --graphs G1 G2 --trials K/dev/reference/trials.jsonl [--seed 0]
"""
import argparse, glob, json, os, random, re

from .check_content import ID_RE, check_sentence
from .graph import Graph
from .rank import read_jsonl


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args(argv)
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    rnd = random.Random(a.seed)
    res = {"date": [0, 0], "number": [0, 0]}
    for f in sorted(glob.glob(os.path.join(a.folder, "*.json"))):
        doc = json.load(open(f, encoding="utf-8"))
        g = Graph.load(next(os.path.join(d, doc["graph_file"]) for d in a.graphs
                            if os.path.exists(os.path.join(d, doc["graph_file"]))))
        for s in doc["sentences"]:
            if s.get("kind") == "meta":
                continue
            t = s["text"]
            masked = ID_RE.sub(lambda m: "#" * len(m.group()), t)
            dm = re.search(r"\d{4}-\d{2}-(\d{2})", masked)
            if dm:
                nd = f"{(int(dm.group(1)) % 28) + 1:02d}"
                s2 = dict(s, text=t[:dm.start(1)] + nd + t[dm.end(1):])
                res["date"][1] += 1
                res["date"][0] += any(p[0] in ("date", "quote") for p in check_sentence(s2, g, trials, doc["as_of"], doc.get("ranking")))
                continue
            ms = [m for m in re.finditer(r"(?<![\d.])\d+(?![\d.])", masked)
                  if not (m.start() == len(masked) - len(masked.lstrip()) and masked[m.end():m.end() + 2] == ". ")]
            if ms:
                m = rnd.choice(ms)
                nv = str(int(m.group()) + rnd.choice([1, 2, 7, 10]))
                s2 = dict(s, text=t[:m.start()] + nv + t[m.end():])
                res["number"][1] += 1
                res["number"][0] += any(p[0] in ("number", "date", "quote") for p in check_sentence(s2, g, trials, doc["as_of"], doc.get("ranking")))
    print("mutation detection | " + ", ".join(f"{k} {x}/{n} ({x / n:.1%})" if n else f"{k} 0/0" for k, (x, n) in res.items()))


if __name__ == "__main__":
    main()
