"""입력 파일들 → EvidenceGraph.

  trials    ⓪ trials.jsonl      (trial_id, title, min_age, max_age, sex …)
  criteria  ① criteria.jsonl    (①-b 포함)
  patient   ② patients.jsonl    의 한 줄 (documents[] 로 document 노드)
  evidence  ③ evidence.jsonl    (Agent 2 출력, patient_id 로 거른다)
  verdicts  ④ 모양의 Agent 3 출력: {patient_id, trial_id, criteria:[{criterion_id, status|expected_status, reason,
              supporting_evidence|evidence_ids, expected_action, note?}]}

환자 1명의 후보 시험 전부를 그래프 하나에 넣는다. 같은 evidence_id 는 노드 하나 → 여러 verdict 가 공유.
"""
import json
from .graph import EvidenceGraph

VERDICT_FIELDS = ("status", "reason", "expected_action", "note", "rationale", "confidence")


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def cited_evidence_ids(cv):
    """판정 한 줄이 인용한 evidence_id 들 (supporting_evidence | evidence_ids | evidence, 문자열 또는 {evidence_id})."""
    out = []
    for eid in (cv.get("supporting_evidence") or cv.get("evidence_ids") or cv.get("evidence") or []):
        out.append(eid.get("evidence_id") if isinstance(eid, dict) else eid)
    return out


def evidence_id_mismatch(verdicts, evidence, patient=None):
    """사전 점검: Agent 3 판정이 인용한 evidence_id 중 근거 파일에 없는 것. 근거 파일 버전이 판정과 안 맞으면 커진다."""
    have = {e.get("evidence_id") for e in evidence}
    cited = {eid for v in verdicts if not patient or v.get("patient_id") == patient
             for cv in v.get("criteria", []) for eid in cited_evidence_ids(cv)}
    missing = sorted(cited - have)
    return {"cited": len(cited), "missing": len(missing), "ratio": round(len(missing) / len(cited), 4) if cited else 0.0,
            "examples": missing[:10]}


def evidence_from_agent3_graphs(graph_dir):
    """Agent 3 의 graph/{pid}.json 안의 근거 노드(ev:)와 출처(src:)를 ③ 근거 모양으로 되돌린다.

    주의: Agent 3 그래프에는 판정이 '인용한' 근거만 들어 있다. 환자의 근거 전체(evidence_*.jsonl)가 아니므로
    검사 3(같은 개념의 더 최근 근거)·검사 4(인용되지 않은 충돌 근거)는 불완전하다. 근거 파일이 있으면 그걸 쓸 것.
    """
    import glob, os
    out = []
    for p in sorted(glob.glob(os.path.join(graph_dir, "*.json"))):
        g = json.load(open(p, encoding="utf-8"))
        nodes = {n["id"]: n for n in g["nodes"]}
        src_of = {}
        for a, rel, b in g["edges"]:
            if rel == "derived_from" and a.startswith("ev:"):
                src_of[a] = nodes.get(b)
        for nid, n in nodes.items():
            if n.get("kind") != "evidence":
                continue
            s = src_of.get(nid) or {}
            out.append({"patient_id": g["patient_id"], "evidence_id": nid[3:], "concept": n.get("concept"), "term": n.get("term"),
                        "value": n.get("value"), "unit": n.get("unit"), "observed_date": n.get("observed_date"),
                        "certainty": n.get("certainty"), "subject": n.get("subject", "patient"),
                        "detail": {"status": n.get("status")} if n.get("status") else None,
                        "source": {"doc_id": s.get("doc_id"), "doc_type": s.get("doc_type"), "span": s.get("span"), "text": s.get("text")}})
    return out


def build_graph(patient: dict, trials: list, criteria: list, evidence: list, verdicts: list, as_of=None) -> EvidenceGraph:
    pid = patient["patient_id"]
    g = EvidenceGraph(pid, as_of or patient.get("as_of"))
    g.add_node(f"patient:{pid}", "patient", patient_id=pid, age=patient.get("age"), sex=patient.get("sex"),
               summary=patient.get("summary"))

    # ② documents
    for d in patient.get("documents", []):
        g.add_node(f"doc:{d['doc_id']}", "document", doc_id=d["doc_id"], doc_type=d.get("type"), date=d.get("date"),
                   author_role=d.get("author_role"))

    # ③ evidence (환자 것만)
    for ev in evidence:
        if ev.get("patient_id") not in (None, pid):
            continue
        nid = f"ev:{ev['evidence_id']}"
        g.add_node(nid, "evidence", evidence_id=ev["evidence_id"], concept=ev.get("concept"), term=ev.get("term"),
                   value=ev.get("value"), unit=ev.get("unit"), value_type=ev.get("value_type"),
                   observed_date=ev.get("observed_date"), certainty=ev.get("certainty"), subject=ev.get("subject", "patient"),
                   detail=ev.get("detail"), text=(ev.get("source") or {}).get("text"), span=(ev.get("source") or {}).get("span"))
        src = ev.get("source") or {}
        if src.get("doc_id"):
            did = f"doc:{src['doc_id']}"
            if did not in g.nodes:
                g.add_node(did, "document", doc_id=src["doc_id"], doc_type=src.get("doc_type"), date=None, author_role=src.get("author_role"))
            g.add_edge(nid, "from", did)

    # ⓪ ① 후보 시험과 기준 (판정이 있는 시험만)
    wanted = {v["trial_id"] for v in verdicts if v.get("patient_id") in (None, pid)}
    tmap = {t["trial_id"]: t for t in trials}
    for tid in wanted:
        t = tmap.get(tid, {"trial_id": tid})
        g.add_node(f"trial:{tid}", "trial", trial_id=tid, title=t.get("title") or t.get("brief_title"),
                   min_age=t.get("min_age"), max_age=t.get("max_age"), sex=t.get("sex"), status=t.get("status"))
    for c in criteria:
        if c["trial_id"] not in wanted:
            continue
        cid = f"crit:{c['criterion_id']}"
        g.add_node(cid, "criterion", crit_type=c.get("type"), **{k: c.get(k) for k in (
            "criterion_id", "trial_id", "original_text", "concept", "term", "operator", "value", "unit",
            "time_window", "answerable_by", "administrative", "logic_group", "inline_relation", "parse_status", "complex")})
        g.add_edge(f"trial:{c['trial_id']}", "has_criterion", cid)
    # logic_group → in_group 엣지 (같은 group_id 끼리)
    groups = {}
    for c in g.of_type("criterion"):
        lg = c.get("logic_group")
        if isinstance(lg, dict) and lg.get("group_id"):
            groups.setdefault(lg["group_id"], []).append((c["id"], lg.get("relation", "OR"), lg.get("role")))
    for gid, members in groups.items():
        parent = next((m for m in members if m[2] == "parent"), members[0])
        for m in members:
            if m[0] != parent[0]:
                g.add_edge(parent[0], "in_group", m[0], group_id=gid, relation=parent[1])

    # ④ verdicts (Agent 3)
    for v in verdicts:
        if v.get("patient_id") not in (None, pid):
            continue
        for k, cv in enumerate(v.get("criteria", [])):
            crit = f"crit:{cv['criterion_id']}"
            if crit not in g.nodes:            # 기준 파일에 없는 ID 는 그래프에 못 붙인다 → 기록만
                g.history.append({"event": "verdict_without_criterion", "criterion_id": cv["criterion_id"]})
                continue
            vid = f"verdict:{cv['criterion_id']}#1"
            g.add_node(vid, "verdict", criterion_id=cv["criterion_id"], trial_id=v["trial_id"],
                       status=cv.get("status") or cv.get("expected_status"), reason=cv.get("reason"),
                       expected_action=cv.get("expected_action") or cv.get("action"), note=cv.get("note") or cv.get("rationale"),
                       missing_fact=cv.get("missing_fact"), rule_tags=cv.get("rule_tags"), judged_by=cv.get("judged_by"),
                       by="agent3", verified=None, original_status=cv.get("status") or cv.get("expected_status"))
            g.add_edge(vid, "judges", crit)
            for eid in cited_evidence_ids(cv):
                enid = f"ev:{eid}"
                if enid in g.nodes:
                    g.add_edge(vid, "supported_by", enid)
                else:                            # 존재하지 않는 근거 ID — verify 의 검사 1 이 잡도록 흔적만 남긴다
                    g.nodes[vid].setdefault("missing_evidence_ids", []).append(eid)
    return g
