"""Agent 4 output (graph_<pid>.json + verify_report.json) -> the inputs cards.py / lookup.py already read.

Agent 4 (agent4_v1) keeps every verdict of Agent 3 and adds a new verdict node when it downgrades one
(`verdict:<criterion_id>#2`, `downgraded_from` -> #1). The verdict that counts is the highest #n per criterion. Trial
labels after the downgrades are in verify_report.json (`trial_verdicts`: label, why, pending), recomputed with common
format 6.1, so blocking criteria come from there instead of Agent 3's label_why.

Returned rows have the Agent 3 shape (patient_id, trial_id, as_of, trial_label, label_why, criteria[...]) so both halves of
Agent 5 run on them unchanged. Criteria and evidence are rebuilt from the graph nodes, so no other file is needed for
cards; the answer step still needs patients.jsonl for the documents.
"""
import glob
import json
import os
from collections import defaultdict

CRIT_TYPE = {"inclusion": "inclusion", "exclusion": "exclusion", "I": "inclusion", "E": "exclusion"}


def _num(node_id):
    return int(node_id.rsplit("#", 1)[1]) if "#" in node_id else 0


def load_graphs(graph_dir, report_path=None):
    """Returns (rows, criteria, evidence, as_of_by_patient)."""
    report_path = report_path or os.path.join(graph_dir, "verify_report.json")
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)["patients"]
    rows, criteria, evidence, as_of = [], {}, [], {}
    for path in sorted(glob.glob(os.path.join(graph_dir, "graph_*.json"))):
        with open(path, encoding="utf-8") as f:
            g = json.load(f)
        pid = g["patient_id"]
        as_of[pid] = g.get("as_of")
        nodes = {n["id"]: n for n in g["nodes"]}
        out = defaultdict(lambda: defaultdict(list))
        for e in g["edges"]:
            out[e["src"]][e["rel"]].append(e["dst"])

        docs = {n["id"]: n for n in nodes.values() if n["type"] == "document"}
        for n in nodes.values():
            if n["type"] == "criterion":
                criteria[n["criterion_id"]] = {
                    "criterion_id": n["criterion_id"], "trial_id": n.get("trial_id"),
                    "type": CRIT_TYPE.get(n.get("crit_type"), n.get("crit_type")), "original_text": n.get("original_text"),
                    "concept": n.get("concept"), "term": n.get("term"), "time_window": n.get("time_window"),
                    "answerable_by": n.get("answerable_by"), "administrative": n.get("administrative")}
            elif n["type"] == "evidence":
                d = docs.get((out[n["id"]].get("from") or [None])[0]) or {}
                evidence.append({
                    "evidence_id": n["id"].split(":", 1)[1], "patient_id": pid, "concept": n.get("concept"),
                    "term": n.get("term"), "value": n.get("value"), "unit": n.get("unit"),
                    "observed_date": n.get("observed_date"),
                    "source": {"doc_id": d.get("id", "doc:").split(":", 1)[1], "doc_type": d.get("doc_type"),
                               "text": n.get("text")}})

        latest = {}
        for n in nodes.values():
            if n["type"] == "verdict" and _num(n["id"]) >= _num(latest.get(n["criterion_id"], {"id": "#-1"})["id"]):
                latest[n["criterion_id"]] = n
        by_trial = defaultdict(list)
        for cid, v in latest.items():
            ev_ids = [x.split(":", 1)[1] for x in out[v["id"]].get("supported_by", [])]
            by_trial[v["trial_id"]].append({
                "criterion_id": cid, "status": v["status"], "reason": v.get("reason"),
                "action": v.get("expected_action"), "evidence_ids": ev_ids, "missing_fact": v.get("missing_fact"),
                "note": v.get("note"), "judged_by": v.get("judged_by"), "verified_by": v.get("by"),
                "original_status": v.get("original_status"),
                "downgrade_check": v.get("downgrade_check")})

        tv = report.get(pid, {}).get("trial_verdicts", {})
        for tid, crits in sorted(by_trial.items()):
            t = tv.get(tid, {})
            status = {c["criterion_id"]: c for c in crits}
            if t.get("label") == "ineligible":
                why = [f"FAIL {t['why']}"] if t.get("why") else []
            else:
                why = [f"{status[c]['status']}/{status[c]['reason']} {c}" for c in t.get("pending", []) if c in status]
            rows.append({"patient_id": pid, "trial_id": tid, "as_of": g.get("as_of"),
                         "trial_label": t.get("label", "potential"), "label_why": why, "criteria": crits})
    return rows, list(criteria.values()), evidence, as_of
