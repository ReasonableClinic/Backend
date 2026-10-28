"""Orchestrator (deterministic, no LLM deciding the order): runs the agents in a fixed order through their
run(inputs, out_dir, config) entry points, passes one RUN_ID to all of them (tracing sessions line up), and writes a
manifest. Agents that are not connected yet (run.py still raises NotImplementedError) are reported and skipped, so this
file can be used from day one.

    python3 -m pipeline.run_pipeline --data data/dev --evidence data/dev/evidence/evidence_dev_haiku_v14_12.jsonl \
        --out runs/pipeline_dev [--only agent3,agent4] [--loop 2]

The agent-5 loop (answers -> agent2 update -> agent3 partial re-judge -> agent4) runs at most --loop times and stops
early when no judgment changes. It is wired once agents 2-5 are connected.
"""
import argparse, importlib, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402
from pipeline.manifest import Manifest  # noqa: E402

ORDER = ["agent3", "agent4", "agent5", "agent6"]       # agent1 and agent2 outputs are inputs today (zips)
MODULES = {"agent1": "agents.agent1_criteria.run", "agent2": "agents.agent2_evidence.run", "agent3": "agents.agent3_judge.run",
           "agent4": "agents.agent4_verify.run", "agent5": "agents.agent5_acquire.run", "agent6": "agents.agent6_rank.run"}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data/dev")
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", help="comma list of agents to run (default: all in ORDER)")
    ap.add_argument("--loop", type=int, default=0, help="agent-5 loop rounds (0 = off)")
    ap.add_argument("--run-id")
    a = ap.parse_args()
    load_env()
    run_id = a.run_id or os.environ.get("RUN_ID") or f"pipeline-{time.strftime('%Y%m%d-%H%M%S')}"
    os.environ["RUN_ID"] = run_id                      # every agent's tracer uses this session id
    m = Manifest(run_id, a.out)
    files = {"patients": f"{a.data}/input/patients.jsonl", "pairs": f"{a.data}/input/pairs.jsonl",
             "trials": f"{a.data}/reference/trials.jsonl", "criteria": f"{a.data}/reference/criteria.jsonl",
             "evidence": a.evidence}
    for k, p in files.items():
        if not os.path.exists(p):
            sys.exit(f"STOP: input {k} not found: {p}")
        m.input(k, p)
    todo = a.only.split(",") if a.only else ORDER
    cur = dict(files)
    for agent in todo:
        mod = importlib.import_module(MODULES[agent])
        out_dir = os.path.join(a.out, agent)
        need = [k for k in mod.INPUTS if k not in cur]
        if need:
            print(f"  {agent}: waiting for {need} from an earlier stage; skipped")
            m.data["stages"].append({"agent": agent, "version": mod.VERSION, "skipped": f"no input {need}"})
            continue
        t0 = time.time()
        try:
            outs = mod.run({k: v for k, v in cur.items() if k in mod.INPUTS or k in getattr(mod, "OPTIONAL", [])}, out_dir,
                           {"run_id": run_id})
        except NotImplementedError as e:
            print(f"  {agent}: not connected yet ({e}); skipped")
            m.data["stages"].append({"agent": agent, "version": mod.VERSION, "skipped": "not connected"})
            continue
        m.stage(agent, mod.VERSION, {k: cur[k] for k in mod.INPUTS if k in cur}, outs, round(time.time() - t0, 1))
        cur.update(outs)
        if "judgments" in outs and os.path.exists(outs["judgments"]):
            n = m.check_ids(agent, outs["judgments"], cur["evidence"])
            print(f"  {agent}: {n} evidence ids cited, all present")
    print("manifest ->", m.write())


if __name__ == "__main__":
    main()
