"""Agent 3 — 판정 — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. The frozen package in this folder is not changed; run()
calls its own CLI in a subprocess with the same commands reproduce.sh uses. Inputs and outputs are files in the common
format (schemas/common_format_v0.5.md); never import another agent's internals.

    python3 -m agents.agent3_judge.run --input patients=... --input pairs=... --input criteria=... --input evidence=... \
        --out runs/a3
Default --llm replay: saved answers in runs/llm_cache/ (replay_pack.zip) only; a miss fails, no API call is made.
config {"llm": "anthropic"} calls the API (key from .env through common/env_setup).
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent3"
VERSION = "a3-0.3.1 + p07 + claude-sonnet-5-5"
INPUTS = ["patients", "pairs", "criteria", "evidence"]
OPTIONAL = ["trials", "concepts"]
OUTPUTS = ["judgments", "graph", "meta"]


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
    config = config or {}
    load_env()
    inputs, out_dir = _prepare(inputs, out_dir)
    llm = config.get("llm", "replay")
    args = ["-m", "agent3.run", "--split", config.get("split", "dev"), "--llm", llm,
            "--model", config.get("model", "claude-sonnet-5-5"), "--out", out_dir]
    for k in ("patients", "pairs", "criteria", "evidence", "trials", "concepts"):
        if k in inputs:
            args += ["--" + k, inputs[k]]
    _cli(args, os.path.join(out_dir, "agent3.log"))
    out = {"judgments": os.path.join(out_dir, "agent3_out.jsonl"), "graph": os.path.join(out_dir, "graph"),
           "meta": os.path.join(out_dir, "run_meta.json")}
    usage = json.load(open(out["meta"], encoding="utf-8")).get("usage", {})
    if llm == "replay" and usage.get("calls"):
        raise RuntimeError(f"agent3: replay made {usage['calls']} API calls")
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
