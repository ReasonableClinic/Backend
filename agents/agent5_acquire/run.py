"""Agent 5 — 정보 획득 — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. The frozen package in this folder is not changed; run()
calls its own CLI in a subprocess with the same commands reproduce.sh uses. Inputs and outputs are files in the common
format (schemas/common_format_v0.5.md); never import another agent's internals.

    python3 -m agents.agent5_acquire.run --input judgments=<Agent 4 agent3_out.jsonl> --input patients=... \
        --input criteria=... --input evidence=... --out runs/a5
Cards only (no answers, no API): a5u-0.2.0 (python3 -m agent5.run cards) and a5j-0.3.1 (python3 -m agent5.lookup_run
cards). cards.jsonl joins both with "_part": "a5u" / "a5j". The update loop (answers -> Agent 2 -> 3 -> 4) stays
scripts/run_loop.py; its patients file is the output key patients_after so it never replaces the pipeline's patients.
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent5"
VERSION = "a5u-0.2.0 + a5j-0.3.1"
INPUTS = ["judgments", "patients", "criteria", "evidence"]
OPTIONAL = ["answered"]                 # answered.jsonl from the update loop (a5j --answered)
OUTPUTS = ["cards", "cards_a5u", "cards_a5j", "patients_after"]


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
    log = os.path.join(out_dir, "agent5.log")
    common = ["--agent3", inputs["judgments"], "--split", config.get("split", "dev"), "--patients", inputs["patients"],
              "--criteria", inputs["criteria"], "--evidence", inputs["evidence"]]
    a5u, a5j = os.path.join(out_dir, "a5u"), os.path.join(out_dir, "a5j")
    _cli(["-m", "agent5.run", "cards", *common, "--out", a5u], log)
    extra = ["--answered", inputs["answered"]] if "answered" in inputs else []
    _cli(["-m", "agent5.lookup_run", "cards", *common, *extra, "--out", a5j], log)
    out = {"cards": os.path.join(out_dir, "cards.jsonl"), "cards_a5u": os.path.join(a5u, "cards.jsonl"),
           "cards_a5j": os.path.join(a5j, "cards.jsonl")}
    with open(out["cards"], "w", encoding="utf-8") as f:
        for part in ("a5u", "a5j"):
            for line in open(out["cards_" + part], encoding="utf-8"):
                if line.strip():
                    f.write(json.dumps({**json.loads(line), "_part": part}, ensure_ascii=False) + "\n")
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
