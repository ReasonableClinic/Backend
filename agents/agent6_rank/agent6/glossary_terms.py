"""Glossary term extractor, frozen version gt-1.0.0 (Agent 6). Standalone: Python 3.9+, standard library only.

  python3 glossary_terms.py --trials trials.jsonl [more.jsonl ...] --glossary glossary.csv --out terms.csv

Reads ONLY trial records (fields `conditions` and `condition_mesh`). Writes every term that the glossary does not
cover, one row per term, sorted alphabetically. The output holds the term and whether it came from free-text
conditions and/or MeSH — no trial ids, no per-trial mapping, no counts. Columns follow agent6/glossary.csv so the file
can be drafted (ko, abbr, kind) and reviewed (status) in place.

Matching is the same as agent6/glossary.py: case-insensitive, HTML entities unescaped, whitespace collapsed.
"""
import argparse, csv, hashlib, html, json, os, re, sys

TOOL_VERSION = "gt-1.0.0"
FIELDS = ["en", "ko", "abbr", "kind", "source", "dev_used", "status", "note", "title_exception"]


def key(term):
    return re.sub(r"\s+", " ", html.unescape(term or "")).strip().lower()


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trials", required=True, nargs="+")
    ap.add_argument("--glossary", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    known = {key(r["en"]) for r in csv.DictReader(open(a.glossary, encoding="utf-8-sig")) if r.get("en")}
    terms, n_trials = {}, 0
    for p in a.trials:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                t = json.loads(line)
                n_trials += 1
                for field, src in (("conditions", "condition"), ("condition_mesh", "mesh")):
                    for term in t.get(field) or []:
                        k = key(term)
                        if k and k not in known:
                            terms.setdefault(k, [term, set()])[1].add(src)
    rows = [{"en": term, "ko": "", "abbr": "", "kind": "", "source": "+".join(sorted(srcs)), "dev_used": "",
             "status": "draft", "note": "", "title_exception": ""}
            for _, (term, srcs) in sorted(terms.items())]
    with open(a.out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"{TOOL_VERSION} | trials read {n_trials} | terms not in glossary {len(rows)} -> {a.out}")
    print(f"tool sha256 {sha256(os.path.abspath(__file__))} | glossary sha256 {sha256(a.glossary)}")


if __name__ == "__main__":
    sys.exit(main())
