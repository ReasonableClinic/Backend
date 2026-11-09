#!/usr/bin/env python3
"""Check the inputs of a run before spending on the model: patients, trials and ①-b criteria fit together.

    python3 agent2/preflight_inputs.py --patients data/test/input/patients.jsonl \
        --trials data/test/reference_1b/trials.jsonl --criteria data/test/reference_1b/criteria.jsonl \
        [--criteria-a data/test/reference/criteria.jsonl]

Prints OK or STOP lines; exit status 1 on any STOP. Reads no gold.
"""
import argparse, collections, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def L(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", required=True)
    ap.add_argument("--trials", required=True)
    ap.add_argument("--criteria", required=True, help="①-b criteria.jsonl")
    ap.add_argument("--criteria-a", help="①-a criteria.jsonl of the same set: ids and text must not change")
    ap.add_argument("--concepts", default=os.path.join(HERE, "concepts.json"))
    a = ap.parse_args()
    stop = []
    P, T, C = L(a.patients), L(a.trials), L(a.criteria)
    keys = {c["key"] for c in json.load(open(a.concepts, encoding="utf-8"))}
    docs = sum(len(p["documents"]) for p in P)
    chars = sum(len(d["text"]) for p in P for d in p["documents"])
    print(f"patients {len(P)}, documents {docs}, characters {chars}, as_of {sorted({p['as_of'] for p in P})}")
    if len({p["patient_id"] for p in P}) != len(P):
        stop.append("duplicate patient_id")
    bad_docs = [d.get("doc_id") for p in P for d in p["documents"] if not d.get("text") or not d.get("doc_id")]
    if bad_docs:
        stop.append(f"documents without doc_id or text: {bad_docs[:5]}")
    tids = {t.get("trial_id") or t.get("nct_id") for t in T}
    filled = [c for c in C if c.get("concept")]
    structured = sum(1 for c in C if c.get("parse_status") == "structured")
    print(f"trials {len(T)}, criteria {len(C)}, with concept {len(filled)}, structured {structured}")
    if not filled:
        stop.append("criteria have no ①-b concept: is this the ①-a file?")
    unknown = collections.Counter(c["concept"] for c in filled if c["concept"] not in keys)
    if unknown:
        stop.append(f"concepts not in concepts.json: {unknown.most_common(8)}")
    no_trial = {c["criterion_id"].rsplit("-", 1)[0] for c in C} - tids
    if no_trial:
        stop.append(f"criteria of trials missing from trials.jsonl: {sorted(no_trial)[:5]} ({len(no_trial)})")
    if a.criteria_a:
        A = {c["criterion_id"]: c["original_text"] for c in L(a.criteria_a)}
        B = {c["criterion_id"]: c["original_text"] for c in C}
        if set(A) != set(B):
            stop.append(f"criterion ids differ from ①-a: {len(set(A) ^ set(B))}")
        changed = sum(1 for k in A if k in B and A[k] != B[k])
        if changed:
            stop.append(f"original_text changed in {changed} criteria")
        else:
            print("criterion ids and text same as ①-a")
    est = 1.94 * chars / 132876
    print(f"estimate (dev v14 rate, Haiku 4.5 batch): about ${est:.1f}, {int(19 * chars / 132876)} min")
    for s in stop:
        print("STOP:", s)
    print("OK" if not stop else "")
    sys.exit(1 if stop else 0)


if __name__ == "__main__":
    main()
