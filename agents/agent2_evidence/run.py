"""Agent 2 — 근거 추출 — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. The frozen package in this folder is not changed; run()
calls its own CLI in a subprocess with the same commands reproduce.sh uses. Inputs and outputs are files in the common
format (schemas/common_format_v0.5.md); never import another agent's internals.

    python3 -m agents.agent2_evidence.run --input patients=... --input trials=... --input criteria=... \
        --input evidence=data/dev/evidence/evidence_dev_haiku_v14_12.jsonl --out runs/a2
Default: the frozen evidence file (v14.12) is checked and passed on as is. Agent 2 keeps no LLM answer cache, so a
re-extraction needs a key: config {"provider": "anthropic"} (or another llm_layer.py provider) runs agent2/llm_layer.py.
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent2"
VERSION = "v14.12"
INPUTS = ["patients", "trials", "criteria"]
OPTIONAL = ["evidence"]                 # the frozen evidence file to pass on (default mode)
OUTPUTS = ["evidence"]


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
    out = {"evidence": os.path.join(out_dir, "evidence.jsonl")}
    if config.get("provider"):          # re-extraction with the LLM (key needed); output folder is the package's own
        ext = os.path.join(out_dir, "extract")
        _cli([os.path.join("agent2", "llm_layer.py"), "--patients", inputs["patients"], "--trials", inputs["trials"],
              "--criteria-ref", inputs["criteria"], "--provider", config["provider"], "--out", ext],
             os.path.join(out_dir, "agent2.log"))
        src = os.path.join(ext, "evidence.jsonl")
    else:
        src = config.get("evidence") or inputs.get("evidence")
        if not src:
            raise ValueError("agent2: give the frozen evidence file (input or config 'evidence') or config 'provider'")
    pids = {json.loads(l)["patient_id"] for l in open(inputs["patients"], encoding="utf-8") if l.strip()}
    rows = [json.loads(l) for l in open(src, encoding="utf-8") if l.strip()]
    bad = [r.get("evidence_id") for r in rows if not r.get("evidence_id") or r.get("patient_id") not in pids]
    if bad:
        raise ValueError(f"agent2: {len(bad)} evidence rows without an id or for another patient set, e.g. {bad[:3]}")
    shutil.copyfile(src, out["evidence"])
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
