#!/usr/bin/env python3
"""Concept-level check of Agent 2 evidence against the ①-b criteria and the gold (④), before gold_evidence has its
concept / value filled.

For every gold criterion decided PASS or FAIL whose ①-b row is structured:
  hit        Agent 2 has evidence of the criterion's concept at a gold supporting span (same document, overlap)
  any        Agent 2 has evidence of that concept anywhere in the record
For numeric criteria (operator >=, <=, >, <, ==, between on a concept with a unit) it also does what Agent 3's code
step will do: take the newest evidence of the concept, compare it with the threshold, turn the result into
PASS / FAIL (an exclusion's condition met = FAIL) and compare with the gold status.

    python3 code/eval_concepts.py --gold data/dev/gold/gold.jsonl --criteria data/dev/reference_1b/criteria.jsonl \
        --concepts agent2/concepts.json --pred runs/X/evidence.jsonl [--show 20]
"""
import argparse, collections, json, sys, os



def load_concepts(path):
    """Team concepts.json + Agent 2 overlay (concepts_agent2.json next to it): only the key mapping is needed here."""
    concepts = {c["key"]: c for c in json.load(open(path, encoding="utf-8"))}
    ov = os.path.join(os.path.dirname(os.path.abspath(path)), "concepts_agent2.json")
    if os.path.exists(ov):
        for k, to in json.load(open(ov, encoding="utf-8")).get("emit_as", {}).items():
            if to in concepts:
                concepts[k] = concepts[to]
    return concepts

BASKETS = {"diagnosis", "medication", "procedure", "symptom_finding", "lab_other", "treatment_plan", "biomarker",
           "tumor_marker", "metastasis", "allergy", "social_history"}
NUMERIC_OPS = {">=", "<=", ">", "<", "==", "between"}


def L(path):
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]


def holds(op, v, ref):
    if op == "between":
        lo, hi = ref
        return lo <= v <= hi
    return {">=": v >= ref, "<=": v <= ref, ">": v > ref, "<": v < ref, "==": v == ref}[op]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", required=True)
    ap.add_argument("--criteria", required=True)
    ap.add_argument("--concepts", required=True)
    ap.add_argument("--pred", required=True)
    ap.add_argument("--show", type=int, default=0)
    a = ap.parse_args()
    concepts = load_concepts(a.concepts)
    crit = {c["criterion_id"]: c for c in L(a.criteria)}
    by_pat = collections.defaultdict(list)
    for e in L(a.pred):
        by_pat[e["patient_id"]].append(e)
    ov = lambda x, y: x[0] < y[1] and y[0] < x[1]  # noqa: E731
    stat = collections.Counter()
    by_concept = collections.defaultdict(collections.Counter)
    code = collections.Counter()
    misses, code_wrong = [], []
    for g in L(a.gold):
        evs = by_pat[g["patient_id"]]
        gev = {x["gold_ev_id"]: x for x in g["gold_evidence"]}
        for k in g["criteria"]:
            c = crit.get(k["criterion_id"])
            if not c or c.get("parse_status") != "structured" or not c.get("concept") or k["expected_status"] not in ("PASS", "FAIL"):
                continue
            key = concepts.get(c["concept"], {}).get("key", c["concept"])
            sup = [gev[x] for x in k["supporting_evidence"] if x in gev]
            kind = "basket" if key in BASKETS else "specific"
            same = [e for e in evs if e["concept"] == key]
            hit = any(e["source"]["doc_id"] == s["doc_id"] and ov(e["source"]["span"], s["span"]) for e in same for s in sup)
            stat[(kind, "n")] += 1
            stat[(kind, "any")] += bool(same)
            if sup:
                stat[(kind, "with_span")] += 1
                stat[(kind, "hit")] += hit
                by_concept[key]["n"] += 1
                by_concept[key]["hit"] += hit
                if not hit:
                    misses.append((g["patient_id"], c["criterion_id"], key, k["expected_status"], c["original_text"][:90],
                                   " | ".join(s["text"][:70] for s in sup)))
            # what Agent 3's code step would decide
            if (kind == "specific" and c.get("operator") in NUMERIC_OPS and c.get("value") is not None
                    and not c.get("change") and not c.get("complex")):
                code["n"] += 1
                vals = [e for e in same if isinstance(e["value"], (int, float)) and not isinstance(e["value"], bool)
                        and e["subject"] == "patient"]
                if not vals:
                    code["no_value"] += 1
                    continue
                e = max(vals, key=lambda x: x.get("observed_date") or "")
                uln = (c.get("unit") or "").replace(" ", "").lower() in ("xuln", "×uln", "timesuln")
                if uln:                                   # "< 1.25 x ULN": value / the lab's upper reference limit
                    hi = (e.get("detail") or {}).get("ref_high")
                    if not hi:
                        code["uln_no_ref"] += 1
                        continue
                    e = dict(e, value=e["value"] / hi)
                    ref = c["value"]
                elif e["unit"] and c.get("unit") and e["unit"] != c["unit"]:
                    alt = concepts.get(key, {}).get("alt_units") or {}
                    if c["unit"] in alt and e["unit"] == concepts[key].get("unit"):
                        ref = c["value"] if c["operator"] != "between" else c["value"]
                        f = alt[c["unit"]]
                        ref = [r * f for r in ref] if isinstance(ref, list) else ref * f
                    else:
                        code["unit_mismatch"] += 1
                        code_wrong.append(("UNIT", g["patient_id"], c["criterion_id"], key, e["value"], e["unit"],
                                           c["operator"], c["value"], c["unit"], k["expected_status"]))
                        continue
                else:
                    ref = c["value"]
                try:
                    met = holds(c["operator"], e["value"], ref)
                except Exception:  # noqa: BLE001
                    code["bad_ref"] += 1
                    continue
                status = ("FAIL" if met else "PASS") if c["type"] == "exclusion" else ("PASS" if met else "FAIL")
                code["decided"] += 1
                code["agree"] += status == k["expected_status"]
                if status != k["expected_status"]:
                    code_wrong.append(("DIFF", g["patient_id"], c["criterion_id"], key, e["value"], e["unit"],
                                       c["operator"], c["value"], c["unit"], k["expected_status"], e["source"]["text"][:60],
                                       c["original_text"][:80]))
    for kind in ("specific", "basket"):
        n, w = stat[(kind, "n")], stat[(kind, "with_span")]
        print(f"{kind:8s} criteria {n}: concept present in record {stat[(kind, 'any')] / max(1, n):.3f}; "
              f"at a gold span {stat[(kind, 'hit')]}/{w} = {stat[(kind, 'hit')] / max(1, w):.3f}")
    print(f"numeric code check: {code['n']} criteria, value found {code['n'] - code['no_value']}, decided {code['decided']}, "
          f"agrees with gold {code['agree']}/{code['decided']}, unit mismatch {code['unit_mismatch']}, "
          f"x ULN without a reference range {code['uln_no_ref']}")
    low = sorted(((v["hit"] / v["n"], k, v["n"]) for k, v in by_concept.items() if v["n"] >= 3))[:12]
    print("lowest concept hit rates:", [(k, f"{r:.2f}", n) for r, k, n in low])
    for m in misses[:a.show]:
        print("MISS", m)
    for w in code_wrong[:a.show]:
        print("CODE", w)


if __name__ == "__main__":
    main()
