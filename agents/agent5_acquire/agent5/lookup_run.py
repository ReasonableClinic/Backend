"""Agent 5 (MISSING / record-lookup part, 준상).

  # 1) cards from an Agent 3 run (no API)
  python -m agent5.lookup_run cards --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl --split dev \
      --out runs/dev_lookup
  #    variants: add --variants. From Agent 4 instead of Agent 3 (verdicts after verification):
  python -m agent5.lookup_run cards --graphs ../agent4_v1/runs/dev_a031 --split dev --out runs/dev_lookup_a4
  #    Without agent3_final, pass --patients / --evidence (and --criteria if you have it):
  python -m agent5.lookup_run cards --agent3 sample/SYN-0016/agent3_out.jsonl --patients sample/SYN-0016/patients.jsonl \
      --evidence sample/SYN-0016/evidence.jsonl --out runs/sample_lookup

  # 2) answers -> new documents -> patients file for Agent 2 update.py
  python -m agent5.lookup_run answer --cards runs/sample_lookup/cards.jsonl --answers examples/answers_lookup_SYN-0016.jsonl \
      --patients sample/SYN-0016/patients.jsonl --evidence sample/SYN-0016/evidence.jsonl --out runs/sample_lookup_answers
"""
import argparse
import json
import os
from collections import Counter

from . import VERSION
from .data import default_paths, read_jsonl, write_jsonl
from .from_graph import load_graphs
from .lookup import build_lookup_cards
from .lookup_answers import apply_lookup_answers

LOOKUP_VERSION = "a5j-0.3.1"


def summary_md(cards, stats, src):
    t = Counter(c["type"] for c in cards)
    unlock = sum(1 for c in cards if c["priority"]["last_blocker_of"])
    safety = sum(1 for c in cards if c["priority"]["safety_check_of"])
    lines = [f"# Agent 5 lookup cards (MISSING) `{LOOKUP_VERSION}` (on {VERSION})", "", f"Agent 3 input: `{src}`", "",
             "| | |", "| --- | --- |",
             f"| Agent 3 UNKNOWN/MISSING rows with a lookup / patient_question action | {stats.get('missing_rows', 0)} |",
             f"| + EXPIRED·UNSUPPORTED rows with a lookup action (handoff from a5u) | {stats.get('handoff_rows', 0)} |",
             f"| skipped (trial already ineligible) | {stats.get('skipped_ineligible_rows', 0)} |",
             f"| skipped (Agent 3 LLM call failed, pc:llm_missing) | {stats.get('not_judged', 0)} |",
             f"| MISSING new_test / clinician that block (운주, a5u) | {stats.get('taken_by_a5u', 0)} |",
             f"| + MISSING new_test / clinician that do not block (unowned until 0.2.0, here from 0.3.0) | "
             f"{stats.get('unowned_rows', 0)} |",
             f"| already answered (no new question, clinician reviews the answer) | {stats.get('answered_rows', 0)} |",
             f"| cards | {len(cards)} (patients {stats.get('patients', 0)}) |",
             "| med_record_check / med_history_check / lab_check / patient_question / clinician_confirmation / new_test | "
             + " / ".join(str(t[k]) for k in ("med_record_check", "med_history_check", "lab_check", "patient_question",
                                               "clinician_confirmation", "new_test")) + " |",
             "| route: ask_patient / ask_site / ask_clinician / agent2_reread / upload_request | "
             + " / ".join(str(stats.get(f"route:{k}", 0)) for k in ("ask_patient", "ask_site", "ask_clinician",
                                                                    "agent2_reread", "upload_request")) + " |",
             f"| cards for the patient / for the clinician or site | {sum(c['audience'] == 'patient' for c in cards)} / "
             f"{sum(c['audience'] == 'clinician' for c in cards)} |",
             f"| cards that are the last blocker of a trial | {unlock} |",
             f"| cards that only check an exclusion (safety) | {safety} |", "", "## Cards", ""]
    for c in cards:
        pr = c["priority"]
        trials = (", ".join(pr["blocking_trials"]) or ("safety " + ", ".join(pr["safety_check_of"])
                                                         if pr["safety_check_of"] else "ineligible trial"))
        lines.append(f"- `{c['card_id']}` {c['title']} ({c['route']}; {trials})")
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cards")
    src = c.add_mutually_exclusive_group(required=True)
    src.add_argument("--agent3", help="Agent 3 output (agent3_out.jsonl)")
    src.add_argument("--graphs", help="Agent 4 output folder (graph_<pid>.json + verify_report.json)")
    c.add_argument("--include-ineligible", action="store_true",
                   help="also cards for trials that already have a FAIL (answers cannot change them)")
    c.add_argument("--answered", help="answered.jsonl from run_loop.py (patient_id, trial_id, criterion_id, doc_id): "
                                      "no new question for these, one clinician card '답 받음·의료진 확인 중' instead")
    a = sub.add_parser("answer")
    a.add_argument("--cards", required=True)
    a.add_argument("--answers", required=True)
    for p in (c, a):
        p.add_argument("--split", default="dev")
        p.add_argument("--variants", action="store_true")
        for k in ("patients", "criteria", "evidence"):
            p.add_argument("--" + k)
        p.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    paths = default_paths(args.split, args.variants)
    for k in paths:
        if getattr(args, k):
            paths[k] = getattr(args, k)
    patients = {p["patient_id"]: p for p in read_jsonl(paths["patients"])}
    os.makedirs(args.out, exist_ok=True)

    if args.cmd == "cards":
        if args.graphs:                                   # Agent 4: verdicts, criteria and evidence all in the graphs
            rows, criteria, evidence, _ = load_graphs(args.graphs)
        else:
            rows, evidence = read_jsonl(args.agent3), read_jsonl(paths["evidence"])
            criteria = read_jsonl(paths["criteria"]) if os.path.exists(paths["criteria"]) else []
            if not criteria:
                print("  ! no criteria.jsonl: criterion type from the id, no criterion text / concept")
        answered = {(x["patient_id"], x["trial_id"], x["criterion_id"]): x["doc_id"]
                    for x in (read_jsonl(args.answered) if args.answered else [])}
        cards, stats = build_lookup_cards(rows, criteria, evidence, patients, include_ineligible=args.include_ineligible,
                                          answered=answered)
        write_jsonl(os.path.join(args.out, "cards.jsonl"), cards)
        md = summary_md(cards, stats, args.graphs or args.agent3)
        with open(os.path.join(args.out, "summary.md"), "w", encoding="utf-8") as f:
            f.write(md)
        print(md)
    else:
        new, not_found, problems = apply_lookup_answers(patients, read_jsonl(args.cards), read_jsonl(args.answers))
        for msg in problems:
            print("  !", msg)
        write_jsonl(os.path.join(args.out, "patients.jsonl"), patients.values())
        write_jsonl(os.path.join(args.out, "new_docs.jsonl"), new)
        write_jsonl(os.path.join(args.out, "not_found.jsonl"), not_found)
        touched = {n["patient_id"] for n in new}
        print(f"{len(new)} new documents for {len(touched)} patients, {len(not_found)} not found -> {args.out}")
    with open(os.path.join(args.out, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump({"agent5_version": VERSION, "lookup_version": LOOKUP_VERSION, "cmd": args.cmd, "paths": paths,
                   **({"agent3": args.agent3, "graphs": args.graphs, "answered": args.answered} if args.cmd == "cards"
                      else {"answers": args.answers})},
                  f, indent=1)


if __name__ == "__main__":
    main()
