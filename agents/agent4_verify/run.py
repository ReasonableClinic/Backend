"""Agent 4 — 검증 — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. The frozen package in this folder is not changed; run()
calls its own CLI in a subprocess with the same commands reproduce.sh uses. Inputs and outputs are files in the common
format (schemas/common_format_v0.5.md); never import another agent's internals.

    python3 -m agents.agent4_verify.run --input judgments=<agent3_out.jsonl> --input evidence=... --input patients=... \
        --input criteria=... --input trials=... --out runs/a4
No LLM. The Agent 3 graph/ folder must sit next to the judgments file (Agent 3 run() writes it there); Agent 4 adds its
rounds (dec:...:r2, by agent4) on top of it.
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent4"
VERSION = "v2"
INPUTS = ["judgments", "evidence", "patients", "criteria", "trials"]
OUTPUTS = ["judgments", "graph", "report"]


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
    _cli(["-m", "agent4", "--patients", inputs["patients"], "--trials", inputs["trials"], "--criteria", inputs["criteria"],
          "--evidence", inputs["evidence"], "--verdicts", inputs["judgments"], "--out", out_dir],
         os.path.join(out_dir, "agent4.log"), env={"PYTHONPATH": HERE})
    return {"judgments": os.path.join(out_dir, "agent3_out.jsonl"), "graph": os.path.join(out_dir, "graph"),
            "report": os.path.join(out_dir, "verify_report.json")}


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
