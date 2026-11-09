"""Readability numbers for briefing folders (patient briefings by default), to compare template vs LLM.

  python3 -m agent6.readability runs/brief_dev runs/brief_llm_dev [--audience patient]

Per folder, over fact sentences (rule sentences are the same in both and are left out):
  sentences/briefing, mean chars/sentence, share of sentences over 60 chars, share with an English word (3+ Latin
  letters in a row), the same outside parentheses (main figure: "만성 폐쇄성 폐질환(COPD)" is a wanted gloss, not
  untranslated text), share of sentences that repeat another sentence in the same file.
Proxy only. Korean has no validated readability formula comparable to Flesch; final judgement is human (CDC Clear
Communication Index checklist, DESIGN_BASIS.md 3장).
"""
import argparse, glob, json, os, re
from collections import Counter

LATIN = re.compile(r"[A-Za-z]{3,}")
PARENS = re.compile(r"\([^()]*\)")


def stats(folder, audience):
    n_doc, sents, dup = 0, [], 0
    for f in glob.glob(os.path.join(folder, f"*.{audience}.json")):
        doc = json.load(open(f, encoding="utf-8"))
        n_doc += 1
        texts = [s["text"] for s in doc["sentences"] if s.get("kind") == "fact"]
        c = Counter(texts)
        dup += sum(v - 1 for v in c.values() if v > 1)
        sents += texts
    if not sents:
        return {"briefings": n_doc}
    L = [len(t) for t in sents]
    return {"briefings": n_doc, "sent_per_briefing": round(len(sents) / max(n_doc, 1), 1),
            "mean_chars": round(sum(L) / len(L), 1), "over_60": round(sum(x > 60 for x in L) / len(L), 3),
            "english": round(sum(bool(LATIN.search(t)) for t in sents) / len(sents), 3),
            "english_outside_parens": round(sum(bool(LATIN.search(PARENS.sub("", t))) for t in sents) / len(sents), 3),
            "repeated": round(dup / len(sents), 3)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--audience", default="patient")
    a = ap.parse_args(argv)
    for d in a.folders:
        print(d, json.dumps(stats(d, a.audience), ensure_ascii=False))


if __name__ == "__main__":
    main()
