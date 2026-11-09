"""Agent 1 — 기준 구조화 (CT.gov) — pipeline entry point.

pipeline/ calls run(inputs, out_dir, config) and nothing else. The frozen package in this folder is not changed; run()
calls its own CLI in a subprocess with the same commands reproduce.sh uses. Inputs and outputs are files in the common
format (schemas/common_format_v0.5.md); never import another agent's internals.

    python3 -m agents.agent1_criteria.run --input trial_ids=<file: one NCT id per line> --out runs/a1
Cache only by default: a trial that is not in cache/ (replay_pack) stops the run instead of calling CT.gov and the LLM.
config {"allow_network": true} lets the package fetch and structure new trials (API key needed).
"""
import argparse, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from common.env_setup import load_env  # noqa: E402

AGENT = "agent1"
VERSION = "agent1 (캐시 200)"
INPUTS = ["trial_ids"]                  # text file, one NCT id per line
OUTPUTS = ["trials", "criteria", "concepts"]


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
    """Structure each trial with the package (python3 -m agent1 --nct <id>) and collect trials.jsonl / criteria.jsonl."""
    config = config or {}
    load_env()
    inputs, out_dir = _prepare(inputs, out_dir)
    ids = [x.strip() for x in open(inputs["trial_ids"], encoding="utf-8") if x.strip() and not x.startswith("#")]
    log = os.path.join(out_dir, "agent1.log")
    trials, criteria = [], []
    uncached = [n for n in ids if not os.path.exists(os.path.join(HERE, "cache", n + ".json"))]
    if uncached and not config.get("allow_network"):    # checked before the package could call CT.gov or the LLM
        raise RuntimeError(f"agent1: not in cache/ {uncached[:5]}; set config allow_network to fetch them")
    for nct in ids:
        one = os.path.join(out_dir, "per_trial", nct)
        _cli(["-m", "agent1", "--nct", nct, "--out", one], log)
        trials += open(os.path.join(one, "trials.jsonl"), encoding="utf-8").readlines()
        criteria += open(os.path.join(one, "criteria.jsonl"), encoding="utf-8").readlines()
    out = {"trials": os.path.join(out_dir, "trials.jsonl"), "criteria": os.path.join(out_dir, "criteria.jsonl"),
           "concepts": os.path.join(out_dir, "concepts.json")}
    open(out["trials"], "w", encoding="utf-8").writelines(trials)
    open(out["criteria"], "w", encoding="utf-8").writelines(criteria)
    shutil.copyfile(os.path.join(HERE, "concepts.json"), out["concepts"])
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
