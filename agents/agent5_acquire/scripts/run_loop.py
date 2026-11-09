"""One patient through the whole update loop: card -> answer -> Agent 2 -> Agent 3 -> Agent 4 -> cards again.

  python scripts/run_loop.py                       # SYN-0010, Agent 3 with the API (key from ../agent3_a3-0.3.1/.env)
  python scripts/run_loop.py --llm replay          # repeat the last API run from the saved answers (no cost)
  python scripts/run_loop.py --a2 rules            # Agent 2 without the API (rules path, only for wiring checks)

Agent 2 re-extracts with Haiku by default: the evidence file is the Haiku series, and the rules path reads
"QuantiFERON ... negative" as diagnosis TB = true. Both agents read the key from ../agent3_a3-0.3.1/.env.

Expects the team packages next to this folder (as unpacked from Notion):
  ../agent3_a3-0.3.1   ../agent3_final (data/, agent3_kit/)   ../agent2_v14_15   ../agent4_v1
Writes runs/loop_<patient>_<llm>/ and LOOP_SUMMARY.md there. Nothing outside runs/ is changed.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJ = os.path.dirname(ROOT)
A3 = os.path.join(PROJ, "agent3_a3-0.3.1")
DATA = os.path.join(PROJ, "agent3_final", "data", "dev")
KIT = os.path.join(PROJ, "agent3_final", "agent3_kit")
A2 = os.path.join(PROJ, "agent2_v14_15")
A2_CACHE = os.path.join(ROOT, "runs", "a2_cache")      # Haiku answers, so --llm replay can repeat a real run for free
A4 = os.path.join(PROJ, "agent4_v1")
A3_PREV = os.path.join(A3, "runs", "dev_a031_v10_kit1412_p07", "agent3_out.jsonl")
EVIDENCE = os.path.join(KIT, "evidence_dev_haiku_v14_12.jsonl")

sys.path.insert(0, ROOT)
from agent5.data import read_jsonl, write_jsonl  # noqa: E402


def step(title, cmd, cwd=ROOT):
    print(f"\n== {title}\n   {' '.join(os.path.relpath(c, ROOT) if os.path.isabs(c) else c for c in cmd)}", flush=True)
    # one key file for both: Agent 2 reads the same .env as Agent 3 (search order in agent2/env_setup.py)
    env = dict(os.environ, PYTHONIOENCODING="utf-8", AGENT2_ENV_FILE=os.path.join(A3, ".env"))
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode:
        sys.exit(f"   ! failed: {title}")


def key_ready():
    """True when ANTHROPIC_API_KEY is in the shell or has a value in ../agent3_a3-0.3.1/.env (the value is never printed)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return True
    path = os.path.join(A3, ".env")
    if not os.path.isfile(path):
        return False
    for line in open(path, encoding="utf-8"):
        k, _, v = line.strip().partition("=")
        if k.strip() == "ANTHROPIC_API_KEY" and v.strip().strip("'\""):
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patient", default="SYN-0010")
    ap.add_argument("--answers", default=os.path.join(ROOT, "examples", "answers_loop_SYN-0010.jsonl"))
    ap.add_argument("--llm", default="anthropic", choices=["anthropic", "replay"])
    ap.add_argument("--scope", default="card", choices=["card", "changes"],
                    help="what Agent 3 re-judges: card (default) = only the criteria of the answered cards; "
                         "changes = every criterion Agent 2's changes.jsonl points to (all UNKNOWN when a concept is new)")
    ap.add_argument("--a2", default="haiku", choices=["haiku", "rules"],
                    help="Agent 2 re-extraction: haiku (default, same series as the evidence file; rules reads "
                         "'QuantiFERON negative' as TB = true)")
    ap.add_argument("--cards-only", action="store_true",
                    help="redo only step 7 (Agent 5 cards after the answer) on an existing run folder; no API")
    a = ap.parse_args()
    pid = a.patient
    if a.a2 == "haiku" and a.llm == "anthropic" and not a.cards_only:
        try:
            import anthropic  # noqa: F401
        except ImportError:
            sys.exit("Agent 2 Haiku needs the anthropic package:  python -m pip install anthropic")
    for need in (A3_PREV, EVIDENCE, os.path.join(A2, "agent2", "update.py"), os.path.join(A4, "agent4", "verify.py")):
        if not os.path.exists(need):
            sys.exit(f"missing: {need}")
    if a.llm == "anthropic" and not a.cards_only and not key_ready():
        sys.exit("No API key. Copy ../agent3_a3-0.3.1/.env.example to .env and put your key after ANTHROPIC_API_KEY=\n"
                 "(or run with --llm replay to check the wiring without the API)")

    out = os.path.join(ROOT, "runs", f"loop_{pid}_{a.llm}" + ("_a2rules" if a.a2 == "rules" else "")
                       + ("_changes" if a.scope == "changes" else ""))
    os.makedirs(out, exist_ok=True)
    p = lambda *x: os.path.join(out, *x)  # noqa: E731
    if a.cards_only:                       # steps 1-6 already ran: only redo the after-cards (no API, no Agent 2/3/4)
        if not os.path.exists(p("a4_after", "verify_report.json")):
            sys.exit(f"--cards-only needs a finished run in {out}")
        write_answered(p)
        cards_after(p)
        return summary(pid, a, out)

    # inputs for this patient only
    write_jsonl(p("agent3_prev.jsonl"), [r for r in read_jsonl(A3_PREV) if r["patient_id"] == pid])
    write_jsonl(p("patients_old.jsonl"), [x for x in read_jsonl(os.path.join(DATA, "input", "patients.jsonl")) if x["patient_id"] == pid])
    write_jsonl(p("a2_old", "evidence.jsonl"), [e for e in read_jsonl(EVIDENCE) if e["patient_id"] == pid])
    ref = {k: os.path.join(DATA, "reference", f"{k}.jsonl") for k in ("trials", "criteria")}

    step("1. Agent 4 before the answer", [sys.executable, "-m", "agent4", "--patients", p("patients_old.jsonl"),
         "--trials", ref["trials"], "--criteria", ref["criteria"], "--evidence", p("a2_old", "evidence.jsonl"),
         "--verdicts", p("agent3_prev.jsonl"), "--out", p("a4_before")], cwd=A4)
    step("2. Agent 5 cards (before)", [sys.executable, "-m", "agent5.lookup_run", "cards", "--graphs", p("a4_before"),
         "--patients", p("patients_old.jsonl"), "--out", p("cards_before")])
    step("3. answer -> new document", [sys.executable, "-m", "agent5.lookup_run", "answer", "--cards",
         p("cards_before", "cards.jsonl"), "--answers", a.answers, "--patients", p("patients_old.jsonl"),
         "--evidence", p("a2_old", "evidence.jsonl"), "--out", p("answers")])
    write_answered(p)
    provider = "rules" if a.a2 == "rules" else ("anthropic" if a.llm == "anthropic" else "replay")
    step(f"4. Agent 2 partial re-extraction ({a.a2}, provider {provider})", [sys.executable,
         os.path.join(A2, "agent2", "update.py"), "--patients", p("answers", "patients.jsonl"), "--old", p("a2_old"),
         "--old-patients", p("patients_old.jsonl"), "--trials", ref["trials"], "--criteria-ref", ref["criteria"],
         "--provider", provider, "--cache-dir", A2_CACHE, "--out", p("a2_upd")])
    # Agent 3 updates graph/<pid>.json in place when it exists; without it the graph holds only the re-judged criteria
    os.makedirs(p("a3_rejudge", "graph"), exist_ok=True)
    shutil.copyfile(os.path.join(os.path.dirname(A3_PREV), "graph", f"{pid}.json"), p("a3_rejudge", "graph", f"{pid}.json"))
    if a.scope == "card":
        # Agent 3 --rejudge shows the note to the model as a flag on its previous judgment, so it only states the fact
        answered = {x["card_id"] for x in read_jsonl(a.answers)}
        write_jsonl(p("rejudge.jsonl"), [
            {"patient_id": c["patient_id"], "trial_id": i["trial_id"], "criterion_id": i["criterion_id"],
             "issue": "new_record", "detail": "a new document answering this criterion was added to the record"}
            for c in read_jsonl(p("cards_before", "cards.jsonl")) if c["card_id"] in answered for i in c["items"]])
        scope_args = ["--rejudge", p("rejudge.jsonl")]
    else:
        scope_args = ["--changes", p("a2_upd", "changes.jsonl")]
    step(f"5. Agent 3 partial re-judge (--llm {a.llm}, scope {a.scope})", [sys.executable, "-m", "agent3.run",
         "--split", "dev", "--llm", a.llm, "--patients", p("answers", "patients.jsonl"), "--trials", ref["trials"],
         "--criteria", ref["criteria"], "--pairs", os.path.join(DATA, "input", "pairs.jsonl"),
         "--concepts", os.path.join(DATA, "reference", "concepts.json"), "--evidence", p("a2_upd", "evidence.jsonl"),
         "--prev", p("agent3_prev.jsonl"), *scope_args, "--patient", pid, "--out", p("a3_rejudge")], cwd=A3)
    step("6. Agent 4 after the answer", [sys.executable, "-m", "agent4", "--patients", p("answers", "patients.jsonl"),
         "--trials", ref["trials"], "--criteria", ref["criteria"], "--evidence", p("a2_upd", "evidence.jsonl"),
         "--verdicts", p("a3_rejudge", "agent3_out.jsonl"), "--out", p("a4_after")], cwd=A4)
    cards_after(p)
    summary(pid, a, out)


def write_answered(p):
    """Which criteria the patient answered, and in which new document: Agent 5 asks them no new question afterwards."""
    doc_of = {(n["patient_id"], n["card_id"]): n["doc_id"] for n in read_jsonl(p("answers", "new_docs.jsonl"))}
    write_jsonl(p("answered.jsonl"), [
        {"patient_id": c["patient_id"], "trial_id": i["trial_id"], "criterion_id": i["criterion_id"],
         "card_id": c["card_id"], "doc_id": doc_of[(c["patient_id"], c["card_id"])]}
        for c in read_jsonl(p("cards_before", "cards.jsonl")) if (c["patient_id"], c["card_id"]) in doc_of
        for i in c["items"]])


def cards_after(p):
    step("7. Agent 5 cards (after)", [sys.executable, "-m", "agent5.lookup_run", "cards", "--graphs", p("a4_after"),
         "--patients", p("answers", "patients.jsonl"), "--answered", p("answered.jsonl"), "--out", p("cards_after")])


def summary(pid, a, out):
    p = lambda *x: os.path.join(out, *x)  # noqa: E731
    answered = {x["card_id"] for x in read_jsonl(a.answers)}
    cards_before = read_jsonl(p("cards_before", "cards.jsonl"))
    target = {(i["trial_id"], i["criterion_id"]) for c in cards_before if c["card_id"] in answered for i in c["items"]}
    prev = {r["trial_id"]: r for r in read_jsonl(p("agent3_prev.jsonl"))}
    new = {r["trial_id"]: r for r in read_jsonl(p("a3_rejudge", "agent3_out.jsonl"))}
    tv = {k: json.load(open(p(k, "verify_report.json"), encoding="utf-8"))["patients"][pid]["trial_verdicts"]
          for k in ("a4_before", "a4_after")}
    ch = read_jsonl(p("a2_upd", "changes.jsonl"))[0]
    added = [e for e in read_jsonl(p("a2_upd", "evidence.jsonl")) if e["evidence_id"] in ch["added"]]

    lines = [f"# Update loop: {pid} (Agent 2 {a.a2}, Agent 3 --llm {a.llm}, re-judge scope {a.scope})", "",
             f"- answered cards: {', '.join(sorted(answered))}",
             f"- target criteria: {', '.join(f'{t} {c}' for t, c in sorted(target))}",
             f"- new document(s): {', '.join(ch['docs']['new'])}; new evidence: "
             + "; ".join(f"{e['evidence_id']} {e['concept']}[{e.get('term')}]={e['value']}" for e in added), ""]
    failed, rows = 0, []
    for tid, r in new.items():
        pc = {c["criterion_id"]: c for c in prev[tid]["criteria"]}
        for c in r["criteria"]:
            o = pc.get(c["criterion_id"])
            if not o or (o["status"], o.get("reason"), o.get("evidence_ids")) == (c["status"], c.get("reason"), c.get("evidence_ids")):
                continue
            if c.get("judged_by") == "pc:llm_missing":
                failed += 1
            mark = " **(target)**" if (tid, c["criterion_id"]) in target else ""
            rows.append(f"| {tid} | {c['criterion_id']}{mark} | {o['status']}/{o.get('reason')} | {c['status']}/{c.get('reason')} "
                        f"| {c.get('judged_by')} | {(c.get('note') or '')[:90]} |")
    lines += ["## Criteria that changed (Agent 3)", "", "| trial | criterion | before | after | judged_by | note |",
              "| --- | --- | --- | --- | --- | --- |"] + (rows or ["| - | none | | | | |"]) + [""]
    lines += ["## Trial labels (after Agent 4)", "", "| trial | before | after |", "| --- | --- | --- |"]
    lines += [f"| {t} | {tv['a4_before'][t]['label']} | {tv['a4_after'].get(t, {}).get('label')} |" for t in tv["a4_before"]]
    def by_crit(cards):
        return {(i["trial_id"], i["criterion_id"]): c["title"] for c in cards for i in c["items"]
                if c["type"] != "answered_review"}
    cards_after = read_jsonl(p("cards_after", "cards.jsonl"))
    kb, ka = by_crit(cards_before), by_crit(cards_after)
    review = [c["title"] for c in cards_after if c["type"] == "answered_review"]
    lines += ["", f"## Cards: {len(cards_before)} before -> {len(cards_after)} after", "",
              "- answered, no question left for the patient: "
              + (", ".join(f"{c} {kb[(t, c)]}" for t, c in sorted(kb) if (t, c) not in ka) or "none"),
              "- answered, clinician reviews the answer: " + (", ".join(review) or "none"),
              "- new: " + (", ".join(f"{c} {ka[(t, c)]}" for t, c in sorted(ka) if (t, c) not in kb) or "none")]
    lab_b = {t: v["label"] for t, v in tv["a4_before"].items()}
    a3_lab = {t: r["trial_label"] for t, r in new.items()}
    odd = [t for t, l in tv["a4_after"].items() if l["label"] == "eligible" and a3_lab.get(t) != "eligible"]
    if odd:
        lines += ["", f"> Agent 4 labels {', '.join(odd)} eligible but Agent 3 says {', '.join(a3_lab[t] for t in odd)} "
                  f"(before: {', '.join(lab_b.get(t, '-') for t in odd)}). Check pc:llm_missing handling in Agent 4."]
    if failed:
        lines += ["", f"> {failed} re-judged criteria have no LLM answer (pc:llm_missing). "
                  "Not a real result: run again with the API (--llm anthropic)."]
    md = "\n".join(lines) + "\n"
    open(p("LOOP_SUMMARY.md"), "w", encoding="utf-8").write(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
