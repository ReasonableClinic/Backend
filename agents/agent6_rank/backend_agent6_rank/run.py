"""Agent 6 — 추천 순위, 브리핑 — pipeline entry point (backend: agents/agent6_rank/run.py).

Put the kit's `agent6/` package next to this file (agents/agent6_rank/agent6/). config {"llm": true, "model": "claude-sonnet-5-5"} adds LLM briefings (needs ANTHROPIC_API_KEY); default off.

  python3 agents/agent6_rank/run.py --input judgments=runs/agent3_dev/agent3_out.jsonl \
      --input graph=runs/agent3_dev/graph --input trials=data/dev/reference/trials.jsonl --out runs/agent6_dev
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (ROOT, os.path.dirname(HERE), HERE):     # backend root, kit root (agent6/ beside this folder), here
    if p not in sys.path:
        sys.path.insert(0, p)
try:
    from common.env_setup import load_env  # noqa: E402
except ImportError:                         # outside the backend repo
    def load_env():
        return None

AGENT = "agent6"
VERSION = "a6-0.4.11"
INPUTS = ["judgments", "graph", "trials"]
OUTPUTS = ["ranking", "briefing"]


def run(inputs, out_dir, config=None):
    load_env()
    missing = [k for k in INPUTS if k not in inputs]
    if missing:
        raise ValueError(f"{AGENT}: missing inputs {missing}")
    from agent6 import brief_clinician, brief_patient, check_grounding, rank
    os.makedirs(out_dir, exist_ok=True)
    rk = os.path.join(out_dir, "ranking.jsonl")
    br = os.path.join(out_dir, "briefing")
    graphs = inputs["graph"] if isinstance(inputs["graph"], list) else [inputs["graph"]]
    judg = inputs["judgments"] if isinstance(inputs["judgments"], list) else [inputs["judgments"]]
    rank.main(["--agent3", *judg, "--trials", inputs["trials"], "--out", rk])
    ev = inputs.get("evidence") or []
    ev = [ev] if isinstance(ev, str) else ev          # optional: Agent 2 evidence (cancer-diagnosis check)
    common = ["--ranking", rk, "--graphs", *graphs, "--trials", inputs["trials"], "--out", br] + (["--evidence", *ev] if ev else [])
    config = config or {}
    if config.get("llm"):
        from agent6 import brief_llm
        brief_llm.main(common + ["--model", config.get("model", brief_llm.DEFAULT_MODEL)]
                       + (["--dry-run"] if config.get("dry_run") else []))
    else:
        brief_clinician.main(common)
        brief_patient.main(common)
    from agent6 import check_content
    check_grounding.main([br, "--graphs", *graphs] + (["--evidence", *ev] if ev else []))
    check_content.main([br, "--ranking", rk, "--graphs", *graphs, "--trials", inputs["trials"]] + (["--evidence", *ev] if ev else []))
    return {"ranking": rk, "briefing": br}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", default=[], metavar="KEY=PATH")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", help="JSON string or path")
    a = ap.parse_args()
    inputs = {}
    for x in a.input:
        k, v = x.split("=", 1)
        inputs[k] = v if k not in inputs else ([inputs[k]] if isinstance(inputs[k], str) else inputs[k]) + [v]
    cfg = {}
    if a.config:
        cfg = json.load(open(a.config)) if os.path.isfile(a.config) else json.loads(a.config)
    print(json.dumps(run(inputs, a.out, cfg), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
