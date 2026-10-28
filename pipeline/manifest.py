"""Run record (manifest): what went into a run and what came out, so mixed versions are caught before they spread.

    m = Manifest(run_id, out_dir)
    m.input("evidence", path)                 # sha256 of each input file
    m.stage("agent3", version, inputs, outputs, seconds)
    m.check_ids("agent3", judgments_path, evidence_path)   # every evidence id the judgments cite exists
    m.write()                                 # <out_dir>/manifest.json

Lesson of 2026-10-26/27: Agent 3 output made with evidence v14.7 was shipped next to evidence v14.9, and the v14.12
re-extraction changed 552 evidence ids that Agent 3 output still pointed to. check_ids stops that at run time.
"""
import hashlib, json, os, time


def sha256(path, n=16):
    if os.path.isdir(path):
        h = hashlib.sha256()
        for root, _, files in sorted(os.walk(path)):
            for f in sorted(files):
                h.update(open(os.path.join(root, f), "rb").read())
        return h.hexdigest()[:n]
    return hashlib.sha256(open(path, "rb").read()).hexdigest()[:n]


class Manifest:
    def __init__(self, run_id, out_dir):
        self.run_id, self.out_dir = run_id, out_dir
        self.data = {"run_id": run_id, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "inputs": {}, "stages": [], "checks": []}

    def input(self, name, path):
        self.data["inputs"][name] = {"path": path, "sha256": sha256(path)}

    def stage(self, agent, version, inputs, outputs, seconds=None):
        self.data["stages"].append({"agent": agent, "version": version, "seconds": seconds,
                                    "inputs": {k: {"path": p, "sha256": sha256(p)} for k, p in inputs.items() if os.path.exists(p)},
                                    "outputs": {k: {"path": p, "sha256": sha256(p)} for k, p in outputs.items() if os.path.exists(p)}})

    def check_ids(self, agent, judgments_path, evidence_path):
        """Every evidence id cited in a judgments file (agent3_out.jsonl shape) must exist in the evidence file."""
        ids = {json.loads(l)["evidence_id"] for l in open(evidence_path, encoding="utf-8") if l.strip()}
        cited = [i for l in open(judgments_path, encoding="utf-8") if l.strip()
                 for c in json.loads(l).get("criteria", []) for i in (c.get("evidence_ids") or [])]
        missing = sorted({i for i in cited if i not in ids})
        self.data["checks"].append({"agent": agent, "check": "evidence_ids_exist", "cited": len(cited), "missing": len(missing),
                                    "examples": missing[:10]})
        if missing:
            raise SystemExit(f"STOP: {agent} cites {len(missing)} evidence ids not in {evidence_path} "
                             f"(e.g. {missing[:3]}): judgments and evidence come from different versions")
        return len(cited)

    def write(self):
        os.makedirs(self.out_dir, exist_ok=True)
        self.data["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        p = os.path.join(self.out_dir, "manifest.json")
        json.dump(self.data, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return p
