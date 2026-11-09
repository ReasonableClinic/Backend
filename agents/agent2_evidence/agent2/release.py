#!/usr/bin/env python3
"""Check a finished Agent 2 run and turn it into the evidence file of the Agent 3 kit.

Same steps for dev and test, so the test run follows a procedure already tried on dev:

  1. format checks that need no gold: every patient present, `source.text == document[span]`, no date after
     `as_of`, no duplicate `evidence_id`, ids in the `<patient>-EVnnn` form, required fields present
  2. optional: keep the ids of an earlier kit file for the same facts (`--old`, carry_ids.py) -> changes file
  3. optional, dev only: scores against the gold (`--gold`), never used for test (blind)
  4. writes `<out>` and `<out without .jsonl>.report.md`

    python3 agent2/release.py --evidence runs/dev_haiku_v15/evidence.jsonl --patients data/dev/input/patients.jsonl \
        --old agent3_kit/evidence_dev_haiku_v14_9.jsonl --gold data/dev/gold/gold.jsonl \
        --criteria data/dev/reference_1b/criteria.jsonl --out agent3_kit/evidence_dev_haiku_v15.jsonl

Exit status 1 when a format check fails (the file is still written, the report says what failed).
"""
import argparse, collections, io, json, os, re, subprocess, sys
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import carry_ids  # noqa: E402

REQUIRED = ("evidence_id", "patient_id", "concept", "value", "observed_date", "certainty", "subject", "source")
ID_RE = re.compile(r"^(?P<pid>.+)-EV\d{3,}$")


def L(path):
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]


def checks(evs, patients):
    docs = {d["doc_id"]: d["text"] for p in patients for d in p["documents"]}
    as_of = {p["patient_id"]: p["as_of"] for p in patients}
    bad = collections.defaultdict(list)
    seen = set()
    for e in evs:
        miss = [k for k in REQUIRED if k not in e]
        if miss:
            bad["missing_field"].append((e.get("evidence_id"), miss))
            continue
        m = ID_RE.match(e["evidence_id"])
        if not m or m.group("pid") != e["patient_id"]:
            bad["bad_id"].append(e["evidence_id"])
        if e["evidence_id"] in seen:
            bad["duplicate_id"].append(e["evidence_id"])
        seen.add(e["evidence_id"])
        s = e["source"]
        if s.get("doc_id") not in docs:
            bad["unknown_doc"].append(e["evidence_id"])
        elif docs[s["doc_id"]][s["span"][0]:s["span"][1]] != s["text"]:
            bad["span_mismatch"].append(e["evidence_id"])
        if e["patient_id"] not in as_of:
            bad["unknown_patient"].append(e["evidence_id"])
        elif e["observed_date"] and e["observed_date"] > as_of[e["patient_id"]]:
            bad["date_after_as_of"].append(e["evidence_id"])
    have = {e["patient_id"] for e in evs}
    for p in patients:
        if p["patient_id"] not in have:
            bad["patient_without_evidence"].append(p["patient_id"])
    return bad


def run_quiet(argv):
    """Run one of the scoring scripts and return its printed lines."""
    r = subprocess.run([sys.executable] + argv, cwd=ROOT, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip().splitlines()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", required=True, help="evidence.jsonl of the run")
    ap.add_argument("--patients", required=True)
    ap.add_argument("--out", required=True, help="kit file to write")
    ap.add_argument("--old", help="earlier kit file of the same patients: keep its ids for the same facts")
    ap.add_argument("--gold", help="dev only: gold.jsonl for scoring (never for test)")
    ap.add_argument("--criteria", help="①-b criteria.jsonl, with --gold for the concept check")
    ap.add_argument("--usage", help="usage.json of the run (default: next to --evidence)")
    a = ap.parse_args()
    if a.gold and "test" in os.path.abspath(a.gold).split(os.sep):
        sys.exit("STOP: test gold is blind; release.py does not score test")

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    patients = L(a.patients)
    evs = L(a.evidence)
    lines = [f"# Agent 2 release report: `{os.path.basename(a.out)}`", "",
             f"- run: `{a.evidence}`", f"- patients: `{a.patients}` ({len(patients)})"]
    usage = a.usage or os.path.join(os.path.dirname(a.evidence), "usage.json")
    if os.path.exists(usage):
        u = json.load(open(usage, encoding="utf-8"))
        lines.append(f"- model `{u.get('model')}`, provider `{u.get('provider')}`, calls {u.get('calls')}, "
                     f"{u.get('wall_seconds')} s, estimated ${u.get('estimated_cost_usd')}")

    changes = None
    if a.old:
        evs, changes = carry_ids.carry(L(a.old), evs)
        cpath = os.path.splitext(a.out)[0] + ".changes.jsonl"
        with open(cpath, "w", encoding="utf-8") as f:
            for c in changes:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        lines += [f"- ids carried from `{a.old}`: kept {sum(c['kept'] for c in changes)}, added "
                  f"{sum(len(c['added']) for c in changes)}, removed {sum(len(c['removed']) for c in changes)}, "
                  f"changed {sum(len(c['changed']) for c in changes)} -> `{os.path.basename(cpath)}`"]

    bad = checks(evs, patients)
    per = collections.Counter(e["patient_id"] for e in evs)
    lines += ["", "## Format checks (no gold needed)", "",
              f"- evidence {len(evs)}, per patient median {sorted(per.values())[len(per) // 2] if per else 0}, "
              f"min {min(per.values()) if per else 0}, max {max(per.values()) if per else 0}"]
    names = ("missing_field", "bad_id", "duplicate_id", "unknown_doc", "span_mismatch", "unknown_patient",
             "date_after_as_of", "patient_without_evidence")
    for k in names:
        lines.append(f"- {k}: {len(bad.get(k, []))}" + (f" (first: {bad[k][:5]})" if bad.get(k) else ""))
    by_by = collections.Counter(e.get("extracted_by") for e in evs)
    lines.append(f"- extracted_by: {dict(by_by)}")
    lines.append(f"- top concepts: {collections.Counter(e['concept'] for e in evs).most_common(12)}")

    if a.gold:
        lines += ["", "## Scores (dev gold)", "", "```"]
        tmp = os.path.splitext(a.out)[0] + ".tmp.jsonl"
        with open(tmp, "w", encoding="utf-8") as f:
            for e in evs:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        lines += run_quiet(["code/eval_evidence.py", "--gold", a.gold, "--pred", tmp, "--misses", "0"])
        if a.criteria:
            lines += run_quiet(["code/eval_concepts.py", "--gold", a.gold, "--criteria", a.criteria,
                                "--concepts", os.path.join(HERE, "concepts.json"), "--pred", tmp])[:3]
            lines += run_quiet(["agent2/eval_lookup.py", tmp, "12", "0", a.criteria])[-2:]
        os.remove(tmp)
        lines.append("```")

    with open(a.out, "w", encoding="utf-8") as f:
        for e in evs:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    rpath = os.path.splitext(a.out)[0] + ".report.md"
    open(rpath, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\n-> {a.out}, {rpath}")
    sys.exit(1 if any(bad.get(k) for k in names) else 0)


if __name__ == "__main__":
    main()
