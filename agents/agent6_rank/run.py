"""Agent 6 — 추천 순위·브리핑 — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. The frozen package in this folder is not changed; run()
calls its own CLI in a subprocess with the same commands reproduce.sh uses. Inputs and outputs are files in the common
format (schemas/common_format_v0.5.md); never import another agent's internals.

    python3 -m agents.agent6_rank.run --input judgments=<agent3_out.jsonl> --input graph=<graph/> --input trials=... \
        [--input evidence=...] --out runs/a6
No LLM: ranking, template briefings (clinician + patient), then check_grounding and check_content with --strict; any
failing briefing stops the run. Give it the Agent 4 graph: briefings read the last round of each decision.
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent6"
VERSION = "a6-0.4.14"
INPUTS = ["judgments", "graph", "trials"]
OPTIONAL = ["evidence"]
OUTPUTS = ["ranking", "briefing", "checks"]


def _cli(args, log, env=None):
    """Run the package CLI from its own folder; its output goes to log. Raises if it fails."""
    with open(log, "a", encoding="utf-8") as f:
        f.write("$ " + " ".join(args) + "\n"); f.flush()
        subprocess.run([sys.executable, *args], cwd=HERE, stdout=f, stderr=subprocess.STDOUT, check=True,
                       env=dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {})))


def _prepare(inputs, out_dir):
    missing = [k for k in INPUTS if k not in inputs]
    if missing:
        raise ValueError(f"{AGENT}: missing inputs {missing}")
    os.makedirs(out_dir, exist_ok=True)
    return {k: os.path.abspath(v) for k, v in inputs.items()}, os.path.abspath(out_dir)


def run(inputs, out_dir, config=None):
    load_env()
    inputs, out_dir = _prepare(inputs, out_dir)
    log = os.path.join(out_dir, "agent6.log")
    ev = ["--evidence", inputs["evidence"]] if "evidence" in inputs else []
    g, t = ["--graphs", inputs["graph"]], ["--trials", inputs["trials"]]
    out = {"ranking": os.path.join(out_dir, "ranking.jsonl"), "briefing": os.path.join(out_dir, "briefing"),
           "checks": log}
    _cli(["-m", "agent6.rank", "--agent3", inputs["judgments"], *t, "--out", out["ranking"]], log)
    for who in ("brief_clinician", "brief_patient"):
        _cli(["-m", "agent6." + who, *ev, "--ranking", out["ranking"], *g, *t, "--out", out["briefing"]], log)
    _cli(["-m", "agent6.check_grounding", out["briefing"], *ev, *g, "--strict"], log)
    _cli(["-m", "agent6.check_content", out["briefing"], "--ranking", out["ranking"], *ev, *g, *t, "--strict"], log)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", action="append", default=[], metavar="KEY=PATH")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config", help="JSON string or path")
    a = ap.parse_args()
    inputs = dict(x.split("=", 1) for x in a.input)
    cfg = {}
    if a.config:
        cfg = json.load(open(a.config)) if os.path.isfile(a.config) else json.loads(a.config)
    print(json.dumps(run(inputs, a.out, cfg), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
