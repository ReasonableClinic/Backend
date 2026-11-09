"""Evidence Graph: the shared reasoning state (Yesung page, Agent 3).

One file per patient: graph/{patient_id}.json. Nodes and edges:

  trial      --has_criterion-->  criterion
  criterion  --requires-->       concept          (the concept/term of each cited evidence)
  evidence   --supports | contradicts | insufficient_for | expired_for | conflicts_on--> decision
  evidence   --derived_from-->   source           (document + span: Agent 4 re-reads it)
  calc       --computes-->       decision         (age, days before as_of)
  criterion  --decided_as-->     decision         (status, reason, by, round)

Agent 4 adds `verification` nodes (verifies --> decision); Agent 5 adds evidence nodes and Agent 3
re-judges only the criteria linked to them (see run.py --changes). Every decision keeps its
`round`, so re-judgments add a new decision node instead of overwriting history.
"""
import json
import os

EDGE_BY_STATUS = {"PASS": "supports", "FAIL": "supports", "CONFLICT": "conflicts_on"}


class Graph:
    def __init__(self, patient_id, as_of):
        self.g = {"patient_id": patient_id, "as_of": as_of, "version": 0, "nodes": {}, "edges": []}

    @classmethod
    def load(cls, path):
        obj = cls("", "")
        with open(path, encoding="utf-8") as f:
            obj.g = json.load(f)
        obj.g["nodes"] = {n["id"]: n for n in obj.g["nodes"]}
        obj.g["edges"] = [tuple(e) for e in obj.g["edges"]]
        return obj

    def node(self, nid, **attrs):
        self.g["nodes"].setdefault(nid, {"id": nid}).update(attrs)
        return nid

    def edge(self, a, rel, b):
        e = (a, rel, b)
        if e not in self.g["edges"]:
            self.g["edges"].append(e)

    def next_round(self, trial_id, criterion_id):
        rounds = [n.get("round", 0) for n in self.g["nodes"].values()
                  if n.get("kind") == "decision" and n.get("criterion_id") == criterion_id and n.get("trial_id") == trial_id]
        return max(rounds, default=0) + 1

    def add_pair(self, trial, crits_by_id, results, ds, label, why, agent="agent3"):
        tid = trial["trial_id"]
        self.node(f"trial:{tid}", kind="trial", title=trial.get("title"))
        for r in results:
            c = crits_by_id[r["criterion_id"]]
            cn = self.node(f"crit:{c['criterion_id']}", kind="criterion", type=c["type"], text=c["original_text"],
                           administrative=c.get("administrative"), cohort=c.get("cohort"))
            self.edge(f"trial:{tid}", "has_criterion", cn)
            rnd = self.next_round(tid, c["criterion_id"])
            dn = self.node(f"dec:{tid}:{c['criterion_id']}:r{rnd}", kind="decision", trial_id=tid,
                           criterion_id=c["criterion_id"], status=r["status"], reason=r["reason"],
                           action=r["action"], applicable=r.get("applicable", True), by=agent,
                           judged_by=r.get("judged_by"), round=rnd, rule_tags=r.get("rule_tags", []),
                           note=r.get("note"), missing_fact=r.get("missing_fact"), derived_from=r.get("derived_from"))
            self.edge(cn, "decided_as", dn)
            rel = EDGE_BY_STATUS.get(r["status"]) or {"EXPIRED": "expired_for", "UNSUPPORTED": "insufficient_for"}.get(r["reason"], "supports")
            for eid in r.get("evidence_ids", []):
                e = ds.evidence_by_id[eid]
                en = self.node(f"ev:{eid}", kind="evidence", concept=e["concept"], term=e.get("term"), value=e["value"],
                               unit=e.get("unit"), observed_date=e.get("observed_date"), certainty=e["certainty"],
                               subject=e["subject"], status=(e.get("detail") or {}).get("status"))
                kn = self.node(f"concept:{e['concept']}" + (f":{(e.get('term') or '').lower()}" if e.get("term") else ""),
                               kind="concept", concept=e["concept"], term=e.get("term"))
                sn = self.node(f"src:{e['source']['doc_id']}:{e['source']['span'][0]}-{e['source']['span'][1]}",
                               kind="source", doc_id=e["source"]["doc_id"], doc_type=e["source"]["doc_type"],
                               span=e["source"]["span"], text=e["source"]["text"])
                self.edge(cn, "requires", kn)
                self.edge(kn, "observed_as", en)
                self.edge(en, "derived_from", sn)
                self.edge(en, rel, dn)
            if r.get("calc"):
                calc = self.node(f"calc:{tid}:{c['criterion_id']}", kind="calculation", **r["calc"])
                self.edge(calc, "computes", dn)
        self.node(f"label:{tid}", kind="trial_decision", label=label, why=why, by=agent)
        self.edge(f"trial:{tid}", "labelled", f"label:{tid}")

    def save(self, path):
        self.g["version"] += 1
        out = dict(self.g, nodes=list(self.g["nodes"].values()), edges=[list(e) for e in self.g["edges"]])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
