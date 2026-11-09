"""One command from team outputs to the demo data the web page and the API serve. No API calls.

  python -m pipeline.build_demo                 # stage -> Agent 6 + Agent 5 cards per state -> bundle + manifest
  python -m pipeline.build_demo --run-loop      # first re-run the update loop from saved answers (run_loop.py --llm replay)

Per state (config.STATES):
  1. stage     Agent 3 output + graph + Agent 2 evidence + patient record for that state
  2. Agent 6   ranking, clinician and patient briefings (template sentences), check_grounding, check_content
  3. Agent 5   a5u cards (EXPIRED·UNSUPPORTED) and a5j cards (MISSING·lookup)
  4. bundle    data/<pid>.<state>.json in the web demo v1 format (bundle.py), data/index.json, data/manifest.json

The staging, Agent 6 calls and bundle format follow the web demo v1 scripts (stage.py, build_state.sh,
build_bundle.py), moved here so the whole chain runs from one place and on Windows too.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid

from . import VERSION, bundle, config as C

RUN_ID = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def rel(path):
    return os.path.relpath(path, C.PROJ).replace(os.sep, "/")


STAGES = []      # one row per agent call of this build, for the manifest (QA C8 hash chain, timing)


def hashes(paths):
    out = {}
    for p in paths:
        files = sorted(glob.glob(os.path.join(p, "*"))) if os.path.isdir(p) else [p]
        out.update({rel(f): sha(f) for f in files if os.path.isfile(f)})
    return out


def run(title, cmd, cwd, state=None, inputs=(), outputs=()):
    print(f"   - {title}", flush=True)
    t0 = time.perf_counter()
    r = subprocess.run(cmd, cwd=cwd, env=dict(os.environ, PYTHONIOENCODING="utf-8"), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode:
        sys.stdout.write(r.stdout[-3000:] + r.stderr[-3000:])
        sys.exit(f"   ! failed: {title}")
    STAGES.append({"stage": title, "state": state, "run_id": RUN_ID, "seconds": round(time.perf_counter() - t0, 2),
                   "llm_calls": 0, "inputs": hashes(inputs), "outputs": hashes(outputs)})
    return r.stdout


def stage(pid, state, source):
    d = os.path.join(C.BUILD, pid, state)
    if os.path.isdir(d):
        shutil.rmtree(d)
    os.makedirs(os.path.join(d, "graph"))
    if source == "dev":
        write_jl(os.path.join(d, "agent3_out.jsonl"), [r for r in jl(os.path.join(C.A3_RUN, "agent3_out.jsonl"))
                                                       if r["patient_id"] == pid])
        shutil.copy(os.path.join(C.A3_RUN, "graph", pid + ".json"), os.path.join(d, "graph"))
        ev = os.path.join(d, f"evidence_{pid}_haiku.jsonl")
        write_jl(ev, [e for e in jl(C.EVIDENCE) if e["patient_id"] == pid])
        # v14.12 has no sidecar; Agent 6 checks the id series, so record what the file is
        with open(ev[:-6] + ".run_meta.json", "w", encoding="utf-8") as f:
            json.dump({"id_series": "haiku", "id_prefix": "EV", "source": os.path.basename(C.EVIDENCE)}, f)
        write_jl(os.path.join(d, "patients.jsonl"), [p for p in jl(C.PATIENTS) if p["patient_id"] == pid])
        meta = {"agent3": rel(C.A3_RUN), "agent2": C.EVIDENCE_LABEL, "answers": [], "new_docs": []}
    else:
        shutil.copy(os.path.join(C.LOOP, "a3_rejudge", "agent3_out.jsonl"), d)
        shutil.copy(os.path.join(C.LOOP, "a3_rejudge", "graph", pid + ".json"), os.path.join(d, "graph"))
        ev = os.path.join(d, f"evidence_{pid}_haiku_upd.jsonl")
        shutil.copy(os.path.join(C.LOOP, "a2_upd", "evidence.jsonl"), ev)
        shutil.copy(os.path.join(C.LOOP, "a2_upd", "run_meta.json"), ev[:-6] + ".run_meta.json")
        shutil.copy(os.path.join(C.LOOP, "answers", "patients.jsonl"), d)
        answered = os.path.join(C.LOOP, "answered.jsonl")
        if not os.path.exists(answered):
            sys.exit(f"missing {answered}: run  python scripts/run_loop.py --cards-only  in {rel(C.A5)}")
        shutil.copy(answered, d)
        link_answer_evidence(os.path.join(d, "graph", pid + ".json"), ev, jl(answered),
                             jl(os.path.join(C.LOOP, "a2_upd", "changes.jsonl")))
        meta = {"agent3": rel(os.path.join(C.LOOP, "a3_rejudge")),
                "agent2": "update.py re-extraction of the answer document (loop a2_upd)",
                "answers": jl(C.LOOP_ANSWERS), "new_docs": jl(os.path.join(C.LOOP, "answers", "new_docs.jsonl"))}
    with open(os.path.join(d, "stage.json"), "w", encoding="utf-8") as f:
        json.dump({"patient_id": pid, "state": state, "source": source, **meta}, f, ensure_ascii=False, indent=1)
    return d, ev


def link_answer_evidence(graph_path, ev_path, answered, changes):
    """Put the evidence Agent 2 read from the patient's answer into the graph and tie it to the answered criterion.

    Agent 3 adds only the evidence its decisions cite; when the re-judged decision cites none, the answer document
    would not appear on the screen at all (QA 2-2). The edge is [ev, "answers", crit]: the patient gave this as the
    answer to that criterion's card (also drawn to its newest decision node, where the screen shows evidence chips).
    It is not a judgment: the decision nodes and Agent 3's edges are left as they are."""
    with open(graph_path, encoding="utf-8") as f:
        g = json.load(f)
    ids = {n["id"] for n in g["nodes"]}
    edges = {tuple(e) for e in g["edges"]}
    added_ids = {x for c in changes for x in c.get("added", [])}
    latest = {}                                   # (trial, criterion) -> newest decision node
    for n in g["nodes"]:
        if n["kind"] == "decision":
            k = (n.get("trial_id"), n.get("criterion_id"))
            if k not in latest or (n.get("round") or 0) > (latest[k].get("round") or 0):
                latest[k] = n
    crit_of = {}
    for a in answered:
        crit_of.setdefault(a["doc_id"], []).append((a["trial_id"], a["criterion_id"]))

    def node(n):
        if n["id"] not in ids:
            g["nodes"].append(n)
            ids.add(n["id"])

    def edge(*e):
        if e not in edges:
            g["edges"].append(list(e))
            edges.add(e)

    linked = 0
    for e in jl(ev_path):
        src = e.get("source") or {}
        if e["evidence_id"] not in added_ids or src.get("doc_id") not in crit_of:
            continue
        ev_id, span = "ev:" + e["evidence_id"], src.get("span") or [0, 0]
        src_id = f"src:{src['doc_id']}:{span[0]}-{span[1]}"
        cid = "concept:" + e["concept"] + (":" + e["term"].lower() if e.get("term") else "")
        node({"id": ev_id, "kind": "evidence", "concept": e["concept"], "term": e.get("term"), "value": e.get("value"),
              "unit": e.get("unit"), "observed_date": e.get("observed_date"), "certainty": e.get("certainty"),
              "subject": e.get("subject"), "status": (e.get("detail") or {}).get("status")})
        node({"id": src_id, "kind": "source", "doc_id": src["doc_id"], "doc_type": src.get("doc_type"), "span": span,
              "text": src.get("text")})
        node({"id": cid, "kind": "concept", "concept": e["concept"], "term": e.get("term")})
        edge(cid, "observed_as", ev_id)
        edge(ev_id, "derived_from", src_id)
        for tid, crit in crit_of[src["doc_id"]]:
            # on the newest decision too, so the screen shows the answer as a chip on that row (evidence chips are
            # the edges into a decision); "answers" is not "supports": Agent 3 did not cite it
            for target in ("crit:" + crit, latest.get((tid, crit), {}).get("id")):
                if target in ids:
                    edge(ev_id, "answers", target)
                    linked += 1
    with open(graph_path, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=1)
    print(f"   - answer evidence linked to the answered criteria: {linked} edge(s)")


def agents(d, ev, state):
    g, P = os.path.join(d, "graph"), os.path.join(d, "patients.jsonl")
    a3 = os.path.join(d, "agent3_out.jsonl")
    out6, rank = os.path.join(d, "a6", "briefing"), os.path.join(d, "a6", "ranking.jsonl")
    os.makedirs(out6, exist_ok=True)
    py = sys.executable
    run("Agent 6 rank", [py, "-m", "agent6.rank", "--agent3", a3, "--trials", C.TRIALS, "--out", rank], C.A6,
        state, [a3, C.TRIALS], [rank])
    for who in ("clinician", "patient"):
        run(f"Agent 6 {who} briefing", [py, "-m", f"agent6.brief_{who}", "--evidence", ev, "--ranking", rank,
                                        "--graphs", g, "--trials", C.TRIALS, "--out", out6], C.A6,
            state, [ev, rank, g], [out6])
    checks = {
        "check_grounding": run("Agent 6 check_grounding", [py, "-m", "agent6.check_grounding", out6, "--evidence", ev,
                                                           "--graphs", g], C.A6, state, [out6, ev, g]
                               ).strip().splitlines()[-1:],
        "check_content": run("Agent 6 check_content", [py, "-m", "agent6.check_content", out6, "--ranking", rank,
                                                       "--evidence", ev, "--graphs", g, "--trials", C.TRIALS],
                             C.A6, state, [out6, rank, ev, g]).strip().splitlines()[-1:]}
    common = ["--agent3", a3, "--split", "dev", "--patients", P, "--criteria", C.CRITERIA, "--evidence", ev]
    a5u, a5j = os.path.join(d, "a5u"), os.path.join(d, "a5j")
    run("Agent 5 a5u cards", [py, "-m", "agent5.run", "cards", *common, "--out", a5u], C.A5,
        state, [a3, P, C.CRITERIA, ev], [os.path.join(a5u, "cards.jsonl")])
    answered = os.path.join(d, "answered.jsonl")
    extra = ["--answered", answered] if os.path.exists(answered) else []
    run("Agent 5 a5j cards", [py, "-m", "agent5.lookup_run", "cards", *common, *extra, "--out", a5j], C.A5,
        state, [a3, P, C.CRITERIA, ev] + extra[1:], [os.path.join(a5j, "cards.jsonl")])
    return checks


def _json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def scrub(obj):
    """No local paths in what the API serves (QA S5): paths under the project become relative, others a file name."""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    if isinstance(obj, str) and (os.path.isabs(obj) or obj[1:3] == ":\\"):
        p = os.path.normpath(obj)
        inside = os.path.normcase(p).startswith(os.path.normcase(C.PROJ) + os.sep)
        return rel(p) if inside else os.path.basename(p)
    return obj


def loop_llm_calls():
    """LLM calls the answered state cost when the update loop ran (read from its usage records, not typed in)."""
    a2 = _json(os.path.join(C.LOOP, "a2_upd", "usage.json")) or {}
    a3 = (_json(os.path.join(C.LOOP, "a3_rejudge", "run_meta.json")) or {}).get("usage")
    if isinstance(a3, str):                       # a3-0.3.1 writes its usage dict as a string
        import ast
        try:
            a3 = ast.literal_eval(a3)
        except (ValueError, SyntaxError):
            a3 = {}
    return {"agent2": a2.get("calls"), "agent3": (a3 or {}).get("calls"),
            "source": "loop a2_upd/usage.json, a3_rejudge/run_meta.json"}


def versions():
    sys.path.insert(0, C.A5)
    from agent5 import VERSION as A5U          # noqa: E402
    from agent5.lookup_run import LOOKUP_VERSION  # noqa: E402
    a3 = _json(os.path.join(C.A3_RUN, "run_meta.json"))
    return {"backend": VERSION,
            "agent2": {"evidence": os.path.basename(C.EVIDENCE),
                       "loop_update": _json(os.path.join(C.LOOP, "a2_upd", "run_meta.json"))},
            "agent3": {k: a3.get(k) for k in ("agent3_version", "prompt_version", "model", "llm")},
            "agent4": "not in the demo bundle (Agent 3 graph format is the screen format, 11/04 decision)",
            "agent5": {"a5u": A5U, "a5j": LOOKUP_VERSION}, "agent6": os.path.basename(C.A6),
            "briefing": "template sentences (no LLM)", "web": C.WEB_LABEL}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-loop", action="store_true",
                    help="first redo the after-answer cards of the update loop (run_loop.py --cards-only, no API)")
    a = ap.parse_args()
    for need in (C.A3_RUN, C.EVIDENCE, C.LOOP, C.A6, C.TRIALS, *C.TRANSLATIONS):
        if not os.path.exists(need):
            sys.exit(f"missing: {need}")
    if a.run_loop:
        print("== update loop (cards only)")
        run("run_loop.py --cards-only", [sys.executable, os.path.join("scripts", "run_loop.py"), "--cards-only"], C.A5)

    built, checks = [], {}
    t0 = time.perf_counter()
    for pid, state, source in C.STATES:
        print(f"== {pid} {state} ({source})", flush=True)
        d, ev = stage(pid, state, source)
        checks[f"{pid}.{state}"] = agents(d, ev, f"{pid}.{state}")
        built.append((pid, state, d))

    print("== bundle", flush=True)
    os.makedirs(C.OUT, exist_ok=True)
    for f in glob.glob(os.path.join(C.OUT, "*.json")):     # no stale bundles from an earlier STATES list
        os.remove(f)
    index = bundle.write_all(built, C.OUT, C.A6, C.TRIALS)
    for t in C.TRANSLATIONS:                                # the screen reads these from data/ as well
        shutil.copyfile(t, os.path.join(C.OUT, os.path.basename(t)))
    inputs = hashes([*C.TRANSLATIONS, C.EVIDENCE, os.path.join(C.A3_RUN, "agent3_out.jsonl"),
                     os.path.join(C.LOOP, "a3_rejudge", "agent3_out.jsonl"), os.path.join(C.LOOP, "a2_upd", "evidence.jsonl"),
                     os.path.join(C.LOOP, "answered.jsonl"), C.LOOP_ANSWERS, C.TRIALS, C.CRITERIA])
    manifest = {"built_at": datetime.datetime.now().isoformat(timespec="seconds"), "run_id": RUN_ID,
                "seconds": round(time.perf_counter() - t0, 2),
                "llm_calls": {"this_build": sum(s["llm_calls"] for s in STAGES),
                              "update_loop_run": loop_llm_calls(),
                              "note": "this build runs only Agent 6 (template sentences) and Agent 5 (rules); the "
                                      "answered state was made by the update loop, whose calls are counted separately"},
                "states": [{"patient_id": p, "state": s, "source": src} for p, s, src in C.STATES],
                "versions": versions(), "inputs_sha256": inputs, "stages": STAGES, "agent6_checks": checks,
                "outputs_sha256": {f: sha(os.path.join(C.OUT, f)) for f in sorted(os.listdir(C.OUT)) if f.endswith(".json")
                                   and f != "manifest.json"},
                "note": "SYN-0010 after = update loop (answer -> Agent 2 Haiku -> Agent 3 re-judge of the answered "
                        "criterion -> cards; answered criteria get no new patient question). Synthetic dev patients only."}
    with open(os.path.join(C.OUT, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(scrub(manifest), f, ensure_ascii=False, indent=1)
    print(json.dumps({"index": index, "checks": checks}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
