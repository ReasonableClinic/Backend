"""Read an Evidence Graph (graph/<patient_id>.json, written by Agent 3, rounds added by Agent 4).

  from agent6.graph import Graph
  g = Graph.load("K/dev/agent3_out_a031/graph/SYN-0003.json")
  for d in g.decisions("NCT06997874"):          # latest round per criterion
      print(d["criterion_id"], d["status"], d["reason"], d["action"])
      for ev, src in g.support(d["id"]):         # evidence -> source sentence
          print("   ", ev["value"], ev["observed_date"], src["doc_id"], src["text"])

Node kinds: trial, criterion, decision, trial_decision, evidence, concept, source, calculation.
Edges [from, type, to]: trial has_criterion crit, crit decided_as dec, trial labelled label, crit requires concept,
concept observed_as ev, ev derived_from src, ev supports dec, ev insufficient_for dec, calc computes dec.
Every node id is a valid reference for a briefing sentence (agent6.check_grounding).
"""
import json
from collections import defaultdict


class Graph:
    def __init__(self, data):
        self.data = data
        self.patient_id, self.as_of = data["patient_id"], data["as_of"]
        self.nodes = {n["id"]: n for n in data["nodes"]}
        self.out, self.inc = defaultdict(list), defaultdict(list)
        for a, t, b in data["edges"]:
            self.out[(a, t)].append(b)
            self.inc[(b, t)].append(a)

    @classmethod
    def load(cls, path):
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def trials(self):
        return [n for n in self.nodes.values() if n["kind"] == "trial"]

    def label(self, trial_id):
        ids = self.out[(f"trial:{trial_id}", "labelled")]
        return self.nodes[ids[-1]] if ids else None

    def criteria(self, trial_id):
        return [self.nodes[c] for c in self.out[(f"trial:{trial_id}", "has_criterion")]]

    def decision(self, criterion_node_id):
        """Latest round (Agent 4 adds r2, r3 ... with by = agent4)."""
        decs = [self.nodes[d] for d in self.out[(criterion_node_id, "decided_as")]]
        return max(decs, key=lambda d: d.get("round", 1)) if decs else None

    def decisions(self, trial_id, applicable_only=True):
        out = []
        for c in self.criteria(trial_id):
            d = self.decision(c["id"])
            if d and (d.get("applicable", True) or not applicable_only):
                out.append(d)
        return out

    def support(self, decision_id, kind="supports"):
        """[(evidence node, source node or None)] for `supports` (or `insufficient_for`)."""
        res = []
        for e in self.inc[(decision_id, kind)]:
            srcs = self.out[(e, "derived_from")]
            res.append((self.nodes[e], self.nodes[srcs[0]] if srcs else None))
        return res

    def calculations(self, decision_id):
        return [self.nodes[c] for c in self.inc[(decision_id, "computes")]]
