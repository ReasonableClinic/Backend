"""Agent 1 — 기준 구조화 (CT.gov) — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. Keep the original code in this folder as it is and
call it from here (a function call or a subprocess). Inputs and outputs are files in the common format
(schemas/common_format_v0.5.md); never import another agent's internals.
"""
import argparse, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent1"
VERSION = "①-b dev v2 final / test v1"
INPUTS = ['trial_ids']       # required input keys (README table)
OUTPUTS = ['trials', 'criteria', 'concepts']


def run(inputs, out_dir, config=None):
    """inputs: {key: path}; out_dir: folder to write into; config: dict (model, run_id, flags ...).
    Returns {output key: path} for the files written."""
    load_env()
    missing = [k for k in INPUTS if k not in inputs]
    if missing:
        raise ValueError(f"{AGENT}: missing inputs {missing}")
    os.makedirs(out_dir, exist_ok=True)
    raise NotImplementedError(f"{AGENT}: connect the original code here (see README.md)")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
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
