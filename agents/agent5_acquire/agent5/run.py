"""Agent 5 (EXPIRED / UNSUPPORTED part).

  # 1) cards from an Agent 3 run (no API)
  python3 -m agent5.run cards --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl --split dev \
      --out runs/dev_cards
  #    variants: add --variants

  # 2) answers -> new documents -> patients file for Agent 2 update.py
  python3 -m agent5.run answer --cards runs/dev_cards/cards.jsonl --answers answers.jsonl --split dev \
      --out runs/dev_answers
"""
import argparse
import json
import os
from collections import Counter

from . import VERSION
from .answers import apply_answers
from .cards import build_cards
from .data import default_paths, read_jsonl, write_jsonl


def summary_md(cards, stats, src):
    t = Counter(c["type"] for c in cards)
    unlock = sum(1 for c in cards if c["priority"]["last_blocker_of"])
    s = Counter(i["scope"] for c in cards for i in c["items"])
    lines = [f"# Agent 5 cards (EXPIRED / UNSUPPORTED) `{VERSION}`", "", f"Agent 3 input: `{src}`", "",
             "| | |", "| --- | --- |",
             f"| Agent 3 UNKNOWN/EXPIRED·UNSUPPORTED rows (표 1번) | {stats.get('owned_rows', 0)} |",
             f"| + boundary rows: CONFLICT, blocking MISSING with new_test / clinician_confirmation | "
             f"{stats.get('boundary_rows', 0)} |",
             f"| skipped (trial already ineligible) | {stats.get('skipped_ineligible_rows', 0)} |",
             f"| handed to record lookup (Agent 3 asked for med_record / med_history / lab check) | "
             f"{stats.get('handoff_lookup', 0)} |",
             f"| cards | {len(cards)} (patients {stats.get('patients', 0)}) |",
             f"| new_test / clinician_confirmation / patient_question | {t['new_test']} / "
             f"{t['clinician_confirmation']} / {t['patient_question']} |",
             f"| card items: 표 1번 / boundary | {s['owned']} / {s['boundary']} |",
             f"| cards that are the last blocker of a trial | {unlock} |", "", "## Top card per patient", ""]
    seen = set()
    for c in cards:
        if c["patient_id"] not in seen:
            seen.add(c["patient_id"])
            lines.append(f"- `{c['card_id']}` {c['title']} (trials {', '.join(c['priority']['blocking_trials']) or '-'})")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cards")
    c.add_argument("--agent3", required=True)
    a = sub.add_parser("answer")
    a.add_argument("--cards", required=True)
    a.add_argument("--answers", required=True)
    for p in (c, a):
        p.add_argument("--split", default="dev")
        p.add_argument("--variants", action="store_true")
        for k in ("patients", "criteria", "evidence"):
            p.add_argument("--" + k)
        p.add_argument("--out", required=True)
    c.add_argument("--include-ineligible", action="store_true",
                   help="also cards for trials that already have a FAIL (answers cannot change them)")
    args = ap.parse_args(argv)

    paths = default_paths(args.split, args.variants)
    for k in paths:
        if getattr(args, k):
            paths[k] = getattr(args, k)
    patients = {p["patient_id"]: p for p in read_jsonl(paths["patients"])}
    os.makedirs(args.out, exist_ok=True)

    if args.cmd == "cards":
        cards, handoff, stats = build_cards(read_jsonl(args.agent3), read_jsonl(paths["criteria"]),
                                   read_jsonl(paths["evidence"]), {k: v["as_of"] for k, v in patients.items()},
                                   include_ineligible=args.include_ineligible)
        write_jsonl(os.path.join(args.out, "cards.jsonl"), cards)
        write_jsonl(os.path.join(args.out, "handoff_record_lookup.jsonl"), handoff)
        md = summary_md(cards, stats, args.agent3)
        with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
            f.write(md)
        print(md)
    else:
        new, problems = apply_answers(patients, read_jsonl(args.cards), read_jsonl(args.answers))
        for msg in problems:
            print("  !", msg)
        touched = {n["patient_id"] for n in new}
        write_jsonl(os.path.join(args.out, "patients.jsonl"), patients.values())
        write_jsonl(os.path.join(args.out, "new_docs.jsonl"), new)
        print(f"{len(new)} new documents for {len(touched)} patients -> {args.out}/patients.jsonl")
    with open(os.path.join(args.out, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"agent5_version": VERSION, "cmd": args.cmd, "paths": paths,
                   **({"agent3": args.agent3} if args.cmd == "cards" else {"answers": args.answers})}, f, indent=1)


if __name__ == "__main__":
    main()
