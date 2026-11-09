#!/usr/bin/env python3
"""Score Agent 2 (Evidence Extraction) output (③) against the gold evidence in gold.jsonl (④).

Gold side: every gold_evidence item that some criterion uses as supporting_evidence (decoy_evidence is reported
separately once variants exist). Matching is by document and character span:
  hit   = a predicted evidence with the same doc_id whose span overlaps the gold span
  exact = overlap / union of the two spans >= --iou (default 0.5)
Gold evidence only covers what the judged criteria needed, so extra predictions are not errors in themselves;
the report gives recall (main), the number of predictions per patient, and, where gold concept/value are filled,
concept and value agreement on the hits.

Usage:
  python3 eval_evidence.py --gold data/dev/gold/gold.jsonl --pred runs/agent2_dev/evidence.jsonl
  python3 eval_evidence.py ... --by doc_type        # recall per document type (needs --patients)
pred file: ③ objects, one per line, each with patient_id and source.doc_id / source.span.
"""
import argparse, collections, json


def load(p):
    return [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]


def overlap(a, b):
    return max(0, min(a[1], b[1]) - max(a[0], b[0]))


def same_value(bv, gv):
    """Gold value vs evidence value: numbers within rounding, "stage IV" vs "IV", true vs "positive"."""
    if isinstance(gv, bool) or isinstance(bv, bool):
        norm = {"positive": True, "detected": True, "present": True, "negative": False, "not detected": False,
                "absent": False}
        bv = norm.get(bv.strip().lower(), bv) if isinstance(bv, str) else bv
        gv = norm.get(gv.strip().lower(), gv) if isinstance(gv, str) else gv
        return bv == gv
    if isinstance(gv, (int, float)) and isinstance(bv, (int, float)):
        return abs(bv - gv) <= max(1e-6 * max(1, abs(gv)), 0.051 if abs(gv) < 10 else 0.5)
    if isinstance(gv, str) and isinstance(bv, str):
        f = lambda x: x.lower().replace("stage", "").replace(" ", "")  # noqa: E731
        return f(bv) == f(gv)
    return bv == gv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--patients", help="patients.jsonl, for --by doc_type")
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--by", choices=["doc_type", "patient"], help="break recall down")
    ap.add_argument("--disagree", type=int, default=0, help="print this many concept/value disagreements")
    ap.add_argument("--misses", type=int, default=15, help="print this many missed gold evidence")
    a = ap.parse_args()

    gold = {}
    for g in load(a.gold):
        used = {e for c in g["criteria"] for e in c.get("supporting_evidence", [])}
        for e in g["gold_evidence"]:
            if e["gold_ev_id"] in used:
                key = (g["patient_id"], e["doc_id"], tuple(e["span"]))
                gold.setdefault(key, e)
    pred = collections.defaultdict(list)
    for p in load(a.pred):
        src = p.get("source") or {}
        if src.get("doc_id") and src.get("span"):
            pred[(p["patient_id"], src["doc_id"])].append(p)
    doc_type = {}
    if a.patients:
        for pt in load(a.patients):
            for d in pt["documents"]:
                doc_type[d["doc_id"]] = d["type"]

    hits = exact = 0
    concept_ok = concept_n = value_ok = value_n = 0
    any_c = any_v = any_vn = 0          # any overlapping evidence (not only the best-overlap one) agrees
    disagree = []
    groups = collections.defaultdict(lambda: [0, 0])
    missed = []
    for (pid, doc, span), e in gold.items():
        cands = pred.get((pid, doc), [])
        best, best_iou = None, 0.0
        for p in cands:
            s = p["source"]["span"]
            ov = overlap(span, s)
            if ov:
                iou = ov / (max(span[1], s[1]) - min(span[0], s[0]))
                if iou > best_iou:
                    best, best_iou = p, iou
        g_key = doc_type.get(doc, "?") if a.by == "doc_type" else pid
        groups[g_key][1] += 1
        if best is None:
            missed.append((pid, doc, e["text"]))
            continue
        hits += 1
        groups[g_key][0] += 1
        exact += best_iou >= a.iou
        if e.get("concept"):
            concept_n += 1
            concept_ok += best.get("concept") == e["concept"]
            if e.get("value") is not None:
                value_n += 1
                bv, gv = best.get("value"), e["value"]
                value_ok += same_value(bv, gv)
            ov_c = [p for p in cands if overlap(span, p["source"]["span"]) and p.get("concept") == e["concept"]]
            any_c += bool(ov_c)
            if e.get("value") is not None:
                any_vn += 1
                okv = any(same_value(p.get("value"), e["value"]) for p in ov_c)
                any_v += okv
            else:
                okv = True
            if not ov_c or not okv:
                disagree.append((pid, e["text"][:70], e["concept"], e.get("value"),
                                 sorted({(p["concept"], json.dumps(p.get("value"))[:30]) for p in cands
                                         if overlap(span, p["source"]["span"])})[:4]))
    n = len(gold)
    n_pred = sum(len(v) for v in pred.values())
    n_pat = len({k[0] for k in gold})
    print(f"gold evidence (used by criteria): {n} in {n_pat} patients; predictions: {n_pred} "
          f"({n_pred / max(1, len({k[0] for k in pred})):.1f} per patient)")
    print(f"recall (any overlap): {hits}/{n} = {hits / max(1, n):.3f}")
    print(f"recall (span IoU >= {a.iou}): {exact}/{n} = {exact / max(1, n):.3f}")
    if concept_n:
        print(f"concept agreement on hits: {concept_ok}/{concept_n} = {concept_ok / concept_n:.3f}")
    if value_n:
        print(f"value agreement on hits:   {value_ok}/{value_n} = {value_ok / value_n:.3f}")
    if concept_n:
        print(f"concept agreement, any evidence at the span: {any_c}/{concept_n} = {any_c / concept_n:.3f}")
    if any_vn:
        print(f"value agreement, any same-concept evidence at the span: {any_v}/{any_vn} = {any_v / any_vn:.3f}")
    for d in disagree[:a.disagree]:
        print("  DIFF", d)
    if a.by:
        print(f"\nrecall by {a.by}:")
        for k, (h, t) in sorted(groups.items(), key=lambda kv: -kv[1][1]):
            print(f"  {k:<22} {h}/{t} = {h / t:.2f}")
    if missed and a.misses:
        print(f"\nmissed (first {a.misses}):")
        for pid, doc, text in missed[:a.misses]:
            print(f"  {doc}: {text[:100]}")


if __name__ == "__main__":
    main()
