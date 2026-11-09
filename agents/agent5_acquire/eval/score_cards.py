"""Score cards against the dev gold (④ expected_status / reason / expected_action).

  python3 eval/score_cards.py runs/dev_cards_all/cards.jsonl [--gold ../agent3_final/data/dev/gold/gold.jsonl]

Build the cards with --include-ineligible for this, or rows of ineligible trials count as not covered.

Two gold groups: 표 1번 rows (UNKNOWN/EXPIRED·UNSUPPORTED) and boundary rows taken from the lookup half
(CONFLICT, MISSING whose expected_action is new_test / clinician_confirmation; gold does not say whether a row
blocks the trial, so this group counts non-blocking rows the cards leave out on purpose).

  coverage    gold rows that got a card item (the rest: what Agent 3 said instead)
  type        card type vs gold expected_action, on covered rows
  asked       card items by their gold group; PASS/FAIL means the record already settles it (Agent 3 / 4)
"""
import argparse
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent5.cards import MISSING_TAKEN, OWNED  # noqa: E402
from agent5.data import AGENT3, read_jsonl  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards")
    ap.add_argument("--gold", default=os.path.join(AGENT3, "data/dev/gold/gold.jsonl"))
    ap.add_argument("--agent3", help="Agent 3 output, to say what it gave for uncovered gold rows")
    a = ap.parse_args()

    gold = {(g["patient_id"], g["trial_id"], c["criterion_id"]): c
            for g in read_jsonl(a.gold) for c in g["criteria"]}
    items = {(c["patient_id"], i["trial_id"], i["criterion_id"]): (c, i)
             for c in read_jsonl(a.cards) for i in c["items"]}
    a3 = {}
    if a.agent3:
        a3 = {(r["patient_id"], r["trial_id"], c["criterion_id"]): c for r in read_jsonl(a.agent3) for c in r["criteria"]}

    def scope(g):
        if g["expected_status"] == "UNKNOWN" and g["reason"] in OWNED:
            return "표 1번 EXPIRED/UNSUPPORTED"
        if g["expected_status"] == "CONFLICT" or (g["reason"] == "MISSING" and g.get("expected_action") in MISSING_TAKEN):
            return "boundary CONFLICT, MISSING new_test/clinician"
        return None

    out = [f"# Agent 5 cards vs gold: `{a.cards}`", ""]
    for name in ("표 1번 EXPIRED/UNSUPPORTED", "boundary CONFLICT, MISSING new_test/clinician"):
        rows = [k for k, g in gold.items() if scope(g) == name]
        covered = [k for k in rows if k in items]
        missed = Counter(f"{a3[k]['status']}/{a3[k].get('reason')}/{a3[k].get('action')}" if k in a3 else "?"
                         for k in rows if k not in items)
        agree = sum(items[k][0]["type"] == gold[k].get("expected_action") for k in covered)
        conf = Counter((gold[k].get("expected_action"), items[k][0]["type"]) for k in covered)
        out.append(f"## gold {name}: {len(rows)} rows")
        out.append(f"- coverage: {len(covered)} / {len(rows)} have a card"
                   + (f" ({100 * len(covered) / len(rows):.1f}%)" if rows else ""))
        if missed:
            out.append("  - not covered, Agent 3 said: " + ", ".join(f"{k} {v}" for k, v in missed.most_common(6)))
        if covered:
            out += [f"- type: {agree} / {len(covered)} card types match gold expected_action "
                    f"({100 * agree / len(covered):.1f}%)", "", "| gold expected_action | card type | n |",
                    "| --- | --- | --- |"]
            out += [f"| {e} | {t} | {n} |" for (e, t), n in conf.most_common()]
        out.append("")

    asked = Counter()
    for k in items:
        g = gold.get(k)
        asked["not in gold" if g is None else (scope(g) or f"gold {g['expected_status']}/{g['reason']}")] += 1
    out.append(f"## asked: {len(items)} card items by gold")
    out += [f"- {k}: {v}" for k, v in asked.most_common()]
    print("\n".join(out))


if __name__ == "__main__":
    main()
