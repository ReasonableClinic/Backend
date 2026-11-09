"""Evidence Graph — 환자 1명의 후보 시험 전체를 담는 근거 추적 그래프 (provenance graph).

노드 5종
  trial     ⓪  {trial_id, title, min_age, max_age, sex}
  criterion ①  {criterion_id, trial_id, type, original_text, concept, term, operator, value, unit, time_window,
                answerable_by, administrative, logic_group, parse_status}
  evidence  ③  {evidence_id, concept, term, value, unit, value_type, observed_date, certainty, subject, detail}
  document  ②  {doc_id, doc_type, date, author_role}
  verdict   ④  {criterion_id, trial_id, status, reason, expected_action, verified, original_status, note, by}

엣지 6종 (src → dst)
  has_criterion    trial → criterion
  in_group         criterion ↔ criterion   (①-b logic_group, relation 속성 AND/OR)
  judges           verdict → criterion
  supported_by     verdict → evidence
  from             evidence → document
  conflicts_with   evidence ↔ evidence     (Agent 4 가 만든다)
  downgraded_from  verdict(new) → verdict(old)   (Agent 4 가 만든다)

노드 id 규칙: trial:NCT…, crit:NCT…-I01, ev:<evidence_id>, doc:<doc_id>, verdict:<criterion_id>#<n>
같은 evidence 노드가 여러 verdict 에 연결된다 — 이것이 표가 아니라 그래프인 이유.
"""
import json
from collections import defaultdict


class EvidenceGraph:
    def __init__(self, patient_id: str, as_of: str):
        self.patient_id = patient_id
        self.as_of = as_of
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self._out = defaultdict(list)   # src → [(rel, dst, edge)]
        self._in = defaultdict(list)    # dst → [(rel, src, edge)]
        self.history: list[dict] = []   # 갱신 로그

    # ---- 구성 -----------------------------------------------------------------------------------
    def add_node(self, nid: str, ntype: str, **attrs):
        if nid in self.nodes:
            self.nodes[nid].update(attrs)
        else:
            self.nodes[nid] = {"id": nid, "type": ntype, **attrs}
        return self.nodes[nid]

    def add_edge(self, src: str, rel: str, dst: str, **attrs):
        if src not in self.nodes or dst not in self.nodes:
            raise KeyError(f"edge {src} -{rel}-> {dst}: 노드 없음")
        for r, d, _ in self._out[src]:
            if r == rel and d == dst:
                return
        e = {"src": src, "rel": rel, "dst": dst, **attrs}
        self.edges.append(e)
        self._out[src].append((rel, dst, e))
        self._in[dst].append((rel, src, e))
        return e

    def remove_edge(self, src, rel, dst):
        self.edges = [e for e in self.edges if not (e["src"] == src and e["rel"] == rel and e["dst"] == dst)]
        self._out[src] = [t for t in self._out[src] if not (t[0] == rel and t[1] == dst)]
        self._in[dst] = [t for t in self._in[dst] if not (t[0] == rel and t[1] == src)]

    # ---- 조회 -----------------------------------------------------------------------------------
    def out(self, nid, rel=None):
        return [d for r, d, _ in self._out.get(nid, []) if rel is None or r == rel]

    def inn(self, nid, rel=None):
        return [s for r, s, _ in self._in.get(nid, []) if rel is None or r == rel]

    def of_type(self, ntype):
        return [n for n in self.nodes.values() if n["type"] == ntype]

    def node(self, nid):
        return self.nodes.get(nid)

    def current_verdicts(self):
        """격하로 대체되지 않은(= downgraded_from 의 대상이 아닌) 판정만."""
        replaced = {e["dst"] for e in self.edges if e["rel"] == "downgraded_from"}
        return [v for v in self.of_type("verdict") if v["id"] not in replaced]

    def verdict_for(self, criterion_id):
        cid = f"crit:{criterion_id}"
        vs = [self.nodes[s] for s in self.inn(cid, "judges")]
        replaced = {e["dst"] for e in self.edges if e["rel"] == "downgraded_from"}
        vs = [v for v in vs if v["id"] not in replaced]
        return vs[0] if vs else None

    def evidence_of(self, verdict_id):
        return [self.nodes[d] for d in self.out(verdict_id, "supported_by") if d in self.nodes]

    def document_of(self, evidence_id):
        ds = self.out(evidence_id, "from")
        return self.nodes[ds[0]] if ds else None

    def chain(self, verdict_id):
        """verdict → evidence → document 사슬을 사람이 읽는 형태로 (화면·브리핑용)."""
        v = self.nodes[verdict_id]
        out = {"verdict": v, "criterion": self.nodes.get(f"crit:{v['criterion_id']}"), "evidence": []}
        for ev in self.evidence_of(verdict_id):
            out["evidence"].append({"evidence": ev, "document": self.document_of(ev["id"])})
        return out

    # ---- 전파 -----------------------------------------------------------------------------------
    def affected_by_evidence(self, evidence_ids):
        """근거가 바뀌면 다시 봐야 하는 verdict·criterion·trial 집합 (전체 재실행 대신 이 범위만)."""
        verdicts, criteria, trials = set(), set(), set()
        for eid in evidence_ids:
            nid = eid if eid.startswith("ev:") else f"ev:{eid}"
            for vid in self.inn(nid, "supported_by"):
                verdicts.add(vid)
            for other in self.out(nid, "conflicts_with") + self.inn(nid, "conflicts_with"):
                for vid in self.inn(other, "supported_by"):
                    verdicts.add(vid)
        for vid in verdicts:
            for cid in self.out(vid, "judges"):
                criteria.add(cid)
                for tid in self.inn(cid, "has_criterion"):
                    trials.add(tid)
        return {"verdicts": sorted(verdicts), "criteria": sorted(criteria), "trials": sorted(trials)}

    def affected_by_concept(self, concept, term=None):
        """새 개념의 근거가 추가됐을 때 다시 판정할 기준 (UNKNOWN/MISSING 이던 것)."""
        out = []
        for c in self.of_type("criterion"):
            if c.get("concept") != concept:
                continue
            if term and c.get("term") and not any(term.lower() in t.lower() or t.lower() in term.lower() for t in c["term"]):
                continue
            out.append(c["id"])
        return out

    # ---- 저장 -----------------------------------------------------------------------------------
    def to_dict(self):
        return {"patient_id": self.patient_id, "as_of": self.as_of,
                "nodes": list(self.nodes.values()), "edges": self.edges, "history": self.history}

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    @classmethod
    def load(cls, path):
        d = json.load(open(path, encoding="utf-8"))
        g = cls(d["patient_id"], d["as_of"])
        for n in d["nodes"]:
            g.nodes[n["id"]] = n
        for e in d["edges"]:
            g.add_edge(e["src"], e["rel"], e["dst"], **{k: v for k, v in e.items() if k not in ("src", "rel", "dst")})
        g.history = d.get("history", [])
        return g

    def stats(self):
        from collections import Counter
        nt = Counter(n["type"] for n in self.nodes.values())
        et = Counter(e["rel"] for e in self.edges)
        shared = sum(1 for ev in self.of_type("evidence") if len(self.inn(ev["id"], "supported_by")) >= 2)
        return {"nodes": dict(nt), "edges": dict(et), "evidence_shared_by_2plus_verdicts": shared}
