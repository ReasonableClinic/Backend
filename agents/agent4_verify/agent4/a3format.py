"""EvidenceGraph(Agent 4 내부) → Agent 3 형식 출력 두 가지.

  to_agent3_graph(g, base)     graph/<pid>.json — Agent 3 의 agent3/graph.py 와 같은 모양
  to_agent3_out_row(g, row)    agent3_out.jsonl 한 줄 — 기준 판정에 격하 반영, 시험 판정 다시 계산

Agent 3 그래프 형식
  nodes [{id, kind, …}]   kind: trial, criterion, decision, evidence, concept, source, calculation, trial_decision
  edges [[a, rel, b]]
  trial     --has_criterion--> criterion --decided_as--> dec:<trial>:<crit>:r<n>
  criterion --requires--> concept --observed_as--> evidence --derived_from--> src:<doc_id>:<start>-<end>
  evidence  --supports | insufficient_for | expired_for | conflicts_on--> decision
  trial     --labelled--> label:<trial> (trial_decision)
Agent 4 가 더하는 것
  dec:…:r<n+1>  by: agent4, downgraded_from: 바로 앞 라운드 id, downgrade_check, downgrade_reason, original_status
  [new, downgraded_from, old], [ev, conflicts_with, ev]
  label:<trial> 은 다시 계산한 값(by: agent4)으로 바꾸고 Agent 3 값은 agent3_label/agent3_why 로 남긴다.
base(Agent 3 graph/<pid>.json)가 있으면 그 노드·엣지를 그대로 두고 위만 더한다. 없으면 내부 그래프에서 r1 부터 만든다.
"""
import copy
from collections import Counter
from .verify import trial_verdict

EDGE_BY_STATUS = {"PASS": "supports", "FAIL": "supports", "CONFLICT": "conflicts_on"}


def evidence_rel(status, reason):
    """Agent 3 graph.add_pair 와 같은 규칙: 판정 상태·이유 → 근거→판정 엣지 이름."""
    return EDGE_BY_STATUS.get(status) or {"EXPIRED": "expired_for", "UNSUPPORTED": "insufficient_for"}.get(reason, "supports")


class _A3Graph:
    def __init__(self, base, patient_id, as_of):
        base = copy.deepcopy(base) if base else {"patient_id": patient_id, "as_of": as_of, "version": 0, "nodes": [], "edges": []}
        self.meta = {k: v for k, v in base.items() if k not in ("nodes", "edges")}
        self.nodes = {n["id"]: n for n in base["nodes"]}
        self.edges = [list(e) for e in base["edges"]]
        self._seen = {tuple(e) for e in self.edges}

    def node(self, nid, **attrs):
        if nid not in self.nodes:                  # 이미 있는 노드(Agent 3 것)는 덮어쓰지 않는다
            self.nodes[nid] = {"id": nid, **attrs}
        return nid

    def edge(self, a, rel, b):
        if (a, rel, b) not in self._seen:
            self._seen.add((a, rel, b))
            self.edges.append([a, rel, b])

    def latest_round(self, trial_id, criterion_id):
        return max((n.get("round", 0) for n in self.nodes.values() if n.get("kind") == "decision"
                    and n.get("trial_id") == trial_id and n.get("criterion_id") == criterion_id), default=0)

    def to_dict(self):
        return dict(self.meta, version=self.meta.get("version", 0) + 1, nodes=list(self.nodes.values()), edges=self.edges)


def _add_evidence(a3, g, ev):
    """근거 노드 + 출처 노드(src:<doc>:<span>) + 개념 노드. 개념 노드 id 를 돌려준다."""
    eid = ev["id"]
    a3.node(eid, kind="evidence", concept=ev.get("concept"), term=ev.get("term"), value=ev.get("value"), unit=ev.get("unit"),
            observed_date=ev.get("observed_date"), certainty=ev.get("certainty"), subject=ev.get("subject", "patient"),
            status=(ev.get("detail") or {}).get("status"))
    doc = g.document_of(eid)
    if doc:
        span = ev.get("span")
        sid = f"src:{doc['doc_id']}:{span[0]}-{span[1]}" if isinstance(span, (list, tuple)) and len(span) == 2 else f"src:{doc['doc_id']}"
        a3.node(sid, kind="source", doc_id=doc["doc_id"], doc_type=doc.get("doc_type"), span=span, text=ev.get("text"))
        a3.edge(eid, "derived_from", sid)
    if not ev.get("concept"):
        return None
    kn = a3.node(f"concept:{ev['concept']}" + (f":{ev['term'].lower()}" if ev.get("term") else ""),
                 kind="concept", concept=ev["concept"], term=ev.get("term"))
    a3.edge(kn, "observed_as", eid)
    return kn


def _verdict_round(v):
    return int(v["id"].rsplit("#", 1)[1])


def to_agent3_graph(g, base=None):
    a3 = _A3Graph(base, g.patient_id, g.as_of)
    dec_of = {}                                    # 내부 verdict id → Agent 3 decision id
    for v in sorted(g.of_type("verdict"), key=_verdict_round):     # 원본(#1) 먼저, 격하(#2…) 나중
        tid, cid = v["trial_id"], v["criterion_id"]
        crit = g.node(f"crit:{cid}") or {}
        trial = g.node(f"trial:{tid}") or {}
        cn = a3.node(f"crit:{cid}", kind="criterion", type=crit.get("crit_type"), text=crit.get("original_text"),
                     administrative=crit.get("administrative"), cohort=None)
        a3.node(f"trial:{tid}", kind="trial", title=trial.get("title"))
        a3.edge(f"trial:{tid}", "has_criterion", cn)
        evs = g.evidence_of(v["id"])
        if v.get("by") == "agent4":
            old = dec_of[g.out(v["id"], "downgraded_from")[0]]
            rnd = a3.latest_round(tid, cid) + 1
            dn = a3.node(f"dec:{tid}:{cid}:r{rnd}", kind="decision", trial_id=tid, criterion_id=cid, status=v["status"],
                         reason=v["reason"], action=v.get("expected_action"), applicable=True, by="agent4",
                         judged_by=f"agent4:{v.get('downgrade_check')}", round=rnd, rule_tags=v.get("rule_tags") or [],
                         note=v.get("note"), missing_fact=v.get("missing_fact"), derived_from=None,
                         downgraded_from=old, downgrade_check=v.get("downgrade_check"),
                         downgrade_reason=v.get("downgrade_reason"), original_status=v.get("original_status"))
            a3.edge(dn, "downgraded_from", old)
        else:
            rnd = a3.latest_round(tid, cid)
            if rnd:                                # base 에 Agent 3 판정이 이미 있다 → 그 마지막 라운드가 원본
                dec_of[v["id"]] = f"dec:{tid}:{cid}:r{rnd}"
                continue
            dn = a3.node(f"dec:{tid}:{cid}:r1", kind="decision", trial_id=tid, criterion_id=cid, status=v["status"],
                         reason=v.get("reason"), action=v.get("expected_action"), applicable=True, by="agent3",
                         judged_by=v.get("judged_by"), round=1, rule_tags=v.get("rule_tags") or [], note=v.get("note"),
                         missing_fact=v.get("missing_fact"), derived_from=None)
        dec_of[v["id"]] = dn
        a3.edge(cn, "decided_as", dn)
        rel = evidence_rel(v["status"], v.get("reason"))
        for ev in evs:
            kn = _add_evidence(a3, g, ev)
            if kn:
                a3.edge(cn, "requires", kn)
            a3.edge(ev["id"], rel, dn)
    for e in g.edges:
        if e["rel"] == "conflicts_with":
            _add_evidence(a3, g, g.node(e["src"])); _add_evidence(a3, g, g.node(e["dst"]))
            a3.edge(e["src"], "conflicts_with", e["dst"])
    for t in g.of_type("trial"):
        tid, tv = t["trial_id"], trial_verdict(g, t["trial_id"])
        prev = a3.nodes.get(f"label:{tid}") or {}
        a3.nodes[f"label:{tid}"] = {"id": f"label:{tid}", "kind": "trial_decision", "label": tv["label"], "why": tv["label_why"],
                                    "by": "agent4", "agent3_label": prev.get("label"), "agent3_why": prev.get("why")}
        a3.edge(f"trial:{tid}", "labelled", f"label:{tid}")
    return a3.to_dict()


def to_agent3_out_row(g, row):
    """입력 판정 한 줄(agent3_out.jsonl 모양) → 격하를 반영하고 시험 판정을 다시 계산한 줄. 원래 값은 original_*/agent3_* 로 남긴다."""
    out = copy.deepcopy(row)
    for cv in out.get("criteria", []):
        v = g.verdict_for(cv["criterion_id"])
        if not v or v.get("trial_id") != row["trial_id"]:
            continue
        sk = "status" if "status" in cv or "expected_status" not in cv else "expected_status"
        ak = "action" if "action" in cv or "expected_action" not in cv else "expected_action"
        if v.get("by") == "agent4":
            cv.update({"original_status": cv.get(sk), "original_reason": cv.get("reason"), "original_action": cv.get(ak),
                       sk: v["status"], "reason": v["reason"], ak: v.get("expected_action"), "by": "agent4",
                       "downgrade_check": v.get("downgrade_check"), "downgrade_reason": v.get("downgrade_reason")})
        elif v.get("expected_action") and not cv.get(ak):
            cv[ak] = v["expected_action"]          # Agent 3 이 비워 둔 행동을 규칙표로 채운 경우
    tv = trial_verdict(g, row["trial_id"])
    sk_of = lambda cv: cv.get("status") or cv.get("expected_status")
    out.update(agent3_trial_label=row.get("trial_label"), agent3_label_why=row.get("label_why"),
               trial_label=tv["label"], label_why=tv["label_why"], verified_by="agent4",
               counts={s: Counter(sk_of(cv) for cv in out.get("criteria", []))[s] for s in ("PASS", "FAIL", "UNKNOWN", "CONFLICT")})
    return out
