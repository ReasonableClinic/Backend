"""Run Agent 3 over patient-trial pairs.

  python3 -m agent3.run --split dev --llm none                       # code rules only (baseline)
  python3 -m agent3.run --split dev --llm anthropic --model claude-sonnet-5-5
  python3 -m agent3.run --split dev --llm replay --model claude-sonnet-5-5   # re-score saved replies

Partial re-judgment (feedback loop):
  --changes changes.jsonl     Agent 2 update (new/changed/removed evidence): re-judge only the
                              criteria that cited removed/changed evidence, and the UNKNOWN /
                              CONFLICT criteria of patients with added concepts
  --rejudge flags.jsonl       Agent 4 flags {patient_id, trial_id, criterion_id, issue, detail}:
                              re-judge those criteria once, with the flag shown to the model
Both need --prev <previous agent3_out.jsonl>; everything else is copied from it.

Outputs in --out:
  agent3_out.jsonl            one line per pair (criteria + trial label), scored by eval/score_dev.py
  graph/{patient_id}.json     Evidence Graph
  run_meta.json               versions, model, token usage
"""
import argparse
import json
import os
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import VERSION
from .aggregate import counts, trial_label
from .data import Dataset, read_jsonl, write_jsonl
from .graph import Graph
from .llm import Judge, LLMError
from .postcheck import check
from .prompt import PROMPT_VERSION, SYSTEM, patient_block, trial_block
from .rules import default_action, judge_by_rule, trial_prefilter
from .structured import apply_logic_groups, judge_structured, load_concepts

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# newest evidence file per (split, kind): dev Haiku v14.12 (Agent 2 kit 2026-10-27), dev rules and test v14.9
# (test evidence is frozen), TREC / TrialGPT v14.7
EVIDENCE_FILES = {
    ("dev", "haiku"): "evidence_dev_haiku_v14_12.jsonl", ("dev", "rules"): "evidence_dev_rules_v14_9.jsonl",
    ("dev_variants", "haiku"): "evidence_dev_variants_haiku_v14_12.jsonl", ("dev_variants", "rules"): "evidence_dev_variants_rules_v14_9.jsonl",
    ("test", "haiku"): "evidence_test_haiku_v14_9.jsonl", ("test", "rules"): "evidence_test_rules_v14_9.jsonl",
    ("trec", "haiku"): "evidence_trec_haiku_v14_7.jsonl", ("trec", "rules"): "evidence_trec_rules_v14_7.jsonl",
    ("trialgpt", "haiku"): "evidence_trialgpt_haiku_v14_7.jsonl", ("trialgpt", "rules"): "evidence_trialgpt_rules_v14_7.jsonl",
}


def default_paths(split, evidence_kind):
    ev = os.path.join(HERE, "agent3_kit", EVIDENCE_FILES.get((split, evidence_kind),
                                                            f"evidence_{split}_{evidence_kind}.jsonl"))
    if split in ("trec", "trialgpt"):           # external validation sets (eval_tools_v1)
        d = os.path.join(HERE, "eval_tools", "trec" if split == "trec" else "trialgpt/data")
        return {"patients": os.path.join(d, "patients.jsonl"), "trials": os.path.join(d, "trials.jsonl"),
                "criteria": os.path.join(d, "criteria.jsonl"), "evidence": ev,
                "pairs": os.path.join(d, "trial_candidates.jsonl")}
    d = os.path.join(HERE, "data", split)
    return {
        "patients": os.path.join(d, "input", "patients.jsonl"),
        "trials": os.path.join(d, "reference", "trials.jsonl"),
        "criteria": os.path.join(d, "reference", "criteria.jsonl"),
        "evidence": ev,
        "pairs": os.path.join(d, "gold", "gold.jsonl") if split == "dev" else os.path.join(d, "input", "pairs.jsonl"),
    }


def read_pairs(path):
    """(patient_id, trial_id) from gold.jsonl rows, pairs.jsonl ({patient_id, trial_ids}) or
    trial_candidates.jsonl ({base_id, trial_ids})."""
    out = []
    for p in read_jsonl(path):
        pid = p.get("patient_id") or p.get("base_id")
        if "trial_id" in p:
            out.append((pid, p["trial_id"]))
        else:
            out.extend((pid, t) for t in p.get("trial_ids", []))
    return out


def unknown(cid, crit, tag, note):
    return {"criterion_id": cid, "applicable": True, "status": "UNKNOWN", "reason": "MISSING", "evidence_ids": [],
            "action": default_action(crit["original_text"], bool(crit.get("administrative"))),
            "judged_by": tag, "rule_tags": [tag], "derived_from": None, "missing_fact": None, "note": note}


class Agent3:
    def __init__(self, ds, judge, chunk=30, policy=None, concepts=None):
        self.ds, self.judge, self.chunk = ds, judge, chunk
        self.policy = policy or {}
        self.salt = ""
        self.concepts = concepts if concepts is not None else load_concepts()

    def judge_pair(self, patient_id, trial_id, only=None, hints=None, prev=None):
        """Judge one pair. `only`: criterion ids to (re)judge; the rest are copied from `prev`."""
        ds = self.ds
        trial = ds.trials[trial_id]
        crits = ds.criteria_by_trial[trial_id]
        by_id = {c["criterion_id"]: c for c in crits}
        prev_res = {r["criterion_id"]: r for r in (prev or {}).get("criteria", []) + (prev or {}).get("not_applicable", [])}
        results, todo, code_hints = {}, [], {}
        for c in crits:
            cid = c["criterion_id"]
            if only is not None and cid not in only and cid in prev_res:
                results[cid] = prev_res[cid]
                continue
            r = judge_by_rule(c, ds, patient_id)                 # text rules: age, sex, impossible, consent
            if r is None:                                        # ①-b: numeric / categorical code judgment
                r, hint = judge_structured(c, ds, patient_id, self.concepts, self.policy)
                if hint:
                    code_hints[cid] = hint
            if r:
                results[cid] = r
            else:
                todo.append(c)

        cohort = (prev or {}).get("cohort_assignment")
        if todo and self.judge is None:
            for c in todo:
                results[c["criterion_id"]] = unknown(c["criterion_id"], c, "no_llm", "code-only run")
        elif todo:
            ptext = patient_block(ds, patient_id)
            for i in range(0, len(todo), self.chunk):
                part = todo[i:i + self.chunk]
                ttext = trial_block(trial, part, crits, hints, code_hints)
                ids = [c["criterion_id"] for c in part]
                try:
                    obj = self.judge.judge([PROMPT_VERSION, patient_id, trial_id, json.dumps(hints or {}, sort_keys=True)]
                                           + ([self.salt] if self.salt else []),
                                           SYSTEM, ptext, ttext, ids)
                except LLMError as ex:
                    print(f"  ! {patient_id} {trial_id}: {ex}", file=sys.stderr)
                    obj = {"results": []}
                cohort = obj.get("cohort_assignment") or cohort
                got = {r.get("criterion_id"): r for r in obj.get("results", []) if isinstance(r, dict)}
                for c in part:
                    r = got.get(c["criterion_id"])
                    if r is None:
                        results[c["criterion_id"]] = unknown(c["criterion_id"], c, "pc:llm_missing", "no LLM answer")
                        continue
                    r["judged_by"] = "llm"
                    r["applicable"] = r.get("applicable", True) is not False
                    results[c["criterion_id"]] = check(r, c, ds, patient_id, trial, self.policy)

        apply_logic_groups(results, crits)                       # OR groups, parent lines (①-b dev v2)
        ordered = [results[c["criterion_id"]] for c in crits]
        applicable = [r for r in ordered if r.get("applicable", True)]
        not_app = [r for r in ordered if not r.get("applicable", True)]
        pre = trial_prefilter(trial, ds, patient_id)
        label, why = trial_label(applicable, by_id, pre)
        return {
            "patient_id": patient_id, "trial_id": trial_id, "as_of": ds.as_of(patient_id),
            "trial_label": label, "label_why": why[:12], "cohort_assignment": cohort,
            "counts": counts(applicable), "criteria": applicable, "not_applicable": not_app,
            "agent3_version": VERSION, "prompt_version": PROMPT_VERSION,
            "model": None if self.judge is None else f"{self.judge.provider}:{self.judge.model}",
        }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default="dev")
    ap.add_argument("--evidence-kind", default="haiku", choices=["haiku", "rules"])
    for k in ("patients", "trials", "criteria", "evidence", "pairs"):
        ap.add_argument("--" + k)
    ap.add_argument("--llm", default="none", choices=["none", "mock", "export", "anthropic", "openai", "replay"])
    ap.add_argument("--model", default=os.environ.get("AGENT3_MODEL", "claude-sonnet-5-5"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--cache", default=os.path.join(HERE, "runs", "llm_cache"))
    ap.add_argument("--workers", type=int, default=4, help="patients judged in parallel")
    ap.add_argument("--temperature", type=float, default=None,
                    help="omit for models that fix it (Claude Sonnet 5.5 rejects temperature)")
    ap.add_argument("--chunk", type=int, default=30, help="criteria per LLM call")
    ap.add_argument("--limit", type=int, default=None, help="first N pairs only (smoke test)")
    ap.add_argument("--patient", action="append", help="only these patient ids")
    ap.add_argument("--list-inference", default="strict", choices=["strict", "allow"],
                    help="PASS from absence in a complete list (memo 2.4); strict = dev gold")
    ap.add_argument("--blanket", default="on", choices=["off", "on"],
                    help="organ-system blanket negation -> PASS (team rule A1, agreed 2026-10-23); off = dev gold before A1")
    ap.add_argument("--concepts", default=os.path.join(HERE, "data", "dev", "reference", "concepts.json"),
                    help="team concepts.json (①-b keys, units, alt_units)")
    ap.add_argument("--default-window", default="on", choices=["on", "off"],
                    help="6.3 default freshness for numeric criteria without a window (labs 30 d, imaging 90 d)")
    ap.add_argument("--salt", default="", help="extra cache-key part, e.g. r2 for a reproducibility re-run (D3) of the same prompt")
    ap.add_argument("--prev")
    ap.add_argument("--changes")
    ap.add_argument("--rejudge")
    a = ap.parse_args(argv)

    paths = default_paths(a.split, a.evidence_kind)
    for k in paths:
        if getattr(a, k):
            paths[k] = getattr(a, k)
    out = a.out or os.path.join(HERE, "runs", f"{a.split}_{a.llm}_{a.evidence_kind}")
    os.makedirs(out, exist_ok=True)

    ds = Dataset(paths["patients"], paths["trials"], paths["criteria"], paths["evidence"])
    judge = None if a.llm == "none" else Judge(a.llm, a.model, a.cache, temperature=a.temperature)
    policy = {"list_inference": a.list_inference, "blanket_negation": a.blanket, "default_window": a.default_window == "on"}
    agent = Agent3(ds, judge, a.chunk, policy, load_concepts(a.concepts))
    agent.salt = a.salt

    pairs = read_pairs(paths["pairs"])
    if a.patient:
        pairs = [p for p in pairs if p[0] in a.patient]
    if a.limit:
        pairs = pairs[:a.limit]

    prev = {}
    if a.prev:
        prev = {(r["patient_id"], r["trial_id"]): r for r in read_jsonl(a.prev)}
    only = {}                                   # (pid, tid) -> set of criterion ids to re-judge
    hints = defaultdict(dict)
    if a.changes:
        for ch in read_jsonl(a.changes):
            gone = set(ch.get("removed", [])) | set(ch.get("changed", []))
            for (pid, tid), r in prev.items():
                if pid != ch["patient_id"]:
                    continue
                s = only.setdefault((pid, tid), set())
                for c in r["criteria"]:
                    if gone & set(c.get("evidence_ids", [])):
                        s.add(c["criterion_id"])
                    elif ch.get("added_concepts") and c["status"] in ("UNKNOWN", "CONFLICT"):
                        s.add(c["criterion_id"])
    if a.rejudge:
        for f in read_jsonl(a.rejudge):
            k = (f["patient_id"], f["trial_id"])
            only.setdefault(k, set()).add(f["criterion_id"])
            hints[k][f["criterion_id"]] = f"{f.get('issue')}: {f.get('detail', '')}"
    if a.changes or a.rejudge:
        if not prev:
            ap.error("--changes/--rejudge need --prev")
        pairs = [p for p in pairs if p in prev]

    by_patient = defaultdict(list)
    for p in pairs:
        by_patient[p[0]].append(p)

    def run_patient(pid):
        rows = []
        for (_, tid) in by_patient[pid]:            # sequential per patient: the 1st call warms the prompt cache
            k = (pid, tid)
            if (a.changes or a.rejudge) and k not in only:
                rows.append(prev[k])
                continue
            rows.append(agent.judge_pair(pid, tid, only.get(k), hints.get(k), prev.get(k)))
        return pid, rows

    results = {}
    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        for pid, rows in ex.map(run_patient, list(by_patient)):
            results[pid] = rows
            print(f"  {pid}: " + ", ".join(f"{r['trial_id']}={r['trial_label']}" for r in rows), file=sys.stderr)

    out_rows = [r for p in pairs for r in results[p[0]] if r["trial_id"] == p[1]]
    write_jsonl(os.path.join(out, "agent3_out.jsonl"), out_rows)
    for pid, rows in results.items():
        gpath = os.path.join(out, "graph", f"{pid}.json")
        g = Graph.load(gpath) if (a.prev and os.path.exists(gpath)) else Graph(pid, ds.as_of(pid))
        for r in rows:
            crits = {c["criterion_id"]: c for c in ds.criteria_by_trial[r["trial_id"]]}
            changed = only.get((pid, r["trial_id"]))
            if (a.changes or a.rejudge) and not changed:
                continue
            sel = [c for c in r["criteria"] + r["not_applicable"] if changed is None or c["criterion_id"] in changed]
            g.add_pair(ds.trials[r["trial_id"]], crits, sel, ds, r["trial_label"], r["label_why"])
        g.save(gpath)
    meta = {"agent3_version": VERSION, "prompt_version": PROMPT_VERSION, "llm": a.llm, "salt": a.salt,
            "model": a.model if judge else None, "policy": policy, "evidence": paths["evidence"], "pairs": len(out_rows),
            "usage": judge.usage if judge else None}
    with open(os.path.join(out, "run_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print(f"wrote {len(out_rows)} pairs to {out}", file=sys.stderr)
    return out


if __name__ == "__main__":
    main()
