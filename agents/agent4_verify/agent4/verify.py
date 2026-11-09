"""Agent 4 — Verifier. LLM 없음. 그래프를 순회하며 Agent 3 판정을 검사하고, 통과하지 못한 확정 판정을 내린다(격하만, 승격 없음).

검사 (verdict 가 PASS/FAIL 일 때)
  1 grounding   supported_by 엣지가 없다 / 존재하지 않는 evidence_id 를 가리킨다        → UNKNOWN / UNSUPPORTED
  2 relevance   근거의 concept(+term) 이 기준의 concept(+term) 과 다르다                  → UNKNOWN / UNSUPPORTED
  3 expiry      근거 측정일이 as_of − time_window.max_days_before 보다 이전이다            → UNKNOWN / EXPIRED
  4 conflict    같은 개념의 근거들이 서로 다른 값을 말한다 (둘 다 유효 기간 안)              → CONFLICT / CONFLICT
격하된 판정은 새 verdict 노드로 만들고 downgraded_from 엣지로 원본에 연결한다. 원본은 지우지 않는다.
다음 행동(expected_action)은 규칙표: 이유 × answerable_by.
시험 판정은 공통 형식 6.1 규칙으로 다시 계산한다.
"""
import re
from datetime import date
from collections import Counter

STATUS_FINAL = ("PASS", "FAIL")
BUCKETS = {"diagnosis", "medication", "procedure", "symptom_finding", "biomarker", "metastasis", "allergy",
           "lab_other", "treatment_plan", "social_history", "imaging_finding"}
DEFAULT_WINDOW_DAYS = {"lab_result": 30, "imaging": 90}       # 6.3: 기준에 기간이 없고 '현재 상태' 를 묻는 검사·영상
# 확정 판정인데 노트가 스스로 불확실하다고 적은 경우 (Agent 3 v2 postcheck 에서 옮김; + borderline, no longer met)
HEDGE_RX = re.compile(r"\barguable\b|\bdebatable\b|\bunclear\b|\buncertain\b|\bnot certain\b|\bambiguous\b|\bborderline\b|\bno longer met\b|"
                      r"\bcannot (?:be )?(?:confirm|verif|determin|establish)|\bpartly settled\b|\bmay or may not\b|"
                      r"\bnot (?:fully|clearly|explicitly) (?:settled|established|documented|confirmed)\b", re.I)
# 기준 개념 → 그 판정의 근거로 인정하는 개념들 (Agent 3 의 정당한 우회: 나이←생년월일, 임신←성별 등)
_CLIN = {"diagnosis", "symptom_finding", "metastasis", "procedure", "imaging_finding", "lab_other", "biomarker", "medication", "allergy", "comorbidity"}
CONCEPT_FAMILY = {"age": {"birth_date", "age", "sex"}, "birth_date": {"age", "birth_date"}, "pregnancy": {"sex", "age", "birth_date", "pregnancy", "diagnosis"},
                  "sex": {"sex"}, "diagnosis": _CLIN, "metastasis": _CLIN, "symptom_finding": _CLIN, "procedure": _CLIN, "imaging_finding": _CLIN,
                  "medication": _CLIN, "allergy": _CLIN, "biomarker": _CLIN, "comorbidity": _CLIN}
_LAB = {"blood_pressure", "calcium", "egfr", "creatinine", "hepatitis_b", "hepatitis_c", "hiv", "ast", "alt", "anc", "hemoglobin", "platelet_count",
        "wbc", "bilirubin_total", "inr", "albumin", "fev1", "fev1_fvc_ratio", "fvc", "dlco", "lab_other", "cancer_stage", "menopausal_status"}
CONCEPT_FAMILY["diagnosis"] |= _LAB; CONCEPT_FAMILY["comorbidity"] |= _LAB; CONCEPT_FAMILY["lab_other"] = _CLIN | _LAB
CONCEPT_FAMILY["prior_treatment_lines"] = {"medication", "procedure", "diagnosis", "cancer_stage", "treatment_plan"}
CONCEPT_FAMILY["treatment_plan"] = _CLIN | {"treatment_plan"}
CONCEPT_FAMILY["pulmonary_function"] = {"fev1", "fev1_fvc_ratio", "fvc", "dlco", "pulmonary_function"}
CONCEPT_FAMILY["blood_pressure_percentile"] = {"blood_pressure", "age", "birth_date"}
CONCEPT_FAMILY["medication"] |= {"menopausal_status", "sex"}
ACTION_PRIORITY = ("med_record_check", "med_history_check", "patient_question", "lab_check", "new_test", "clinician_confirmation")


def _d(s):
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def decide_action(reason: str, answerable_by) -> str:
    """이유 × 누가 답할 수 있나 → 다음 행동. LLM 이 고르지 않는다."""
    ab = set(answerable_by or [])
    if reason == "EXPIRED":
        return "new_test"
    if reason == "CONFLICT":
        return "clinician_confirmation"
    if reason == "MISSING":
        if "med_record" in ab:
            return "med_record_check"
        if "patient" in ab:
            return "patient_question"
        if "lab" in ab:
            return "lab_check"
        return "clinician_confirmation"
    if reason == "UNSUPPORTED":
        if "clinician" in ab:
            return "clinician_confirmation"
        if "patient" in ab:
            return "patient_question"
        return "clinician_confirmation"
    return "none"


def _terms_match(crit_terms, ev_term):
    if not crit_terms:
        return True
    if not ev_term:
        return False
    e = ev_term.lower()
    return any(t.lower() in e or e in t.lower() for t in crit_terms if t)


def _effective_value(ev):
    """불리언 근거에서 detail.status 가 stopped/past 면 '지금은 아니다' 로 본다 (투약 중단, 과거 병력)."""
    v = ev.get("value")
    st = (ev.get("detail") or {}).get("status")
    d = ev.get("detail") or {}
    if isinstance(v, bool) and (st == "stopped" or (st == "past" and d.get("end"))):
        return False                           # 종료일이 있는 과거만 '지금은 아님'. 종료일 없는 '과거 병력'(만성질환 이력)은 여전히 있는 것으로 본다
    return v


def _values_conflict(a, b):
    va, vb = _effective_value(a), _effective_value(b)
    if va is None or vb is None:
        return False
    if isinstance(va, bool) or isinstance(vb, bool):
        return bool(va) != bool(vb)
    try:
        fa, fb = float(va), float(vb)
        if a.get("unit") and b.get("unit") and str(a["unit"]).lower() != str(b["unit"]).lower():
            return False                       # 단위가 다르면 환산 전엔 충돌이라 단정하지 않음
        if (fa == 0 or fb == 0) and a.get("concept") in _LAB:
            return False                       # 검사값 0 은 추출 오류일 가능성이 커서 충돌로 보지 않음
        tol = 0.05 * max(abs(fa), abs(fb), 1e-9)
        return abs(fa - fb) > tol
    except (TypeError, ValueError):
        # 표기만 다른 문자열(stage IV / stage IVA, ER+ / 95%)은 충돌이 아니다. 범주값이 서로 포함 관계가 아니고 둘 다 범주형일 때만.
        if a.get("value_type") != "categorical" or b.get("value_type") != "categorical":
            return False
        x, y = str(va).strip().lower(), str(vb).strip().lower()
        return x != y and x not in y and y not in x


def _threshold_side(op, thr, x):
    """기준 임계값에 대해 값 x 가 어느 쪽인지: True/False, 평가 불가면 None."""
    try:
        if op == "between" and isinstance(thr, (list, tuple)) and len(thr) == 2:
            return float(thr[0]) <= x <= float(thr[1])
        t = float(thr)
        return {">": x > t, ">=": x >= t, "<": x < t, "<=": x <= t, "==": x == t}.get(op)
    except (TypeError, ValueError):
        return None


class Verifier:
    def __init__(self, graph, default_windows=False, conflict_days=1, numeric_conflict_days=1):
        self.g = graph
        self.as_of = _d(graph.as_of)
        self.default_windows = default_windows
        self.conflict_days = conflict_days
        self.numeric_conflict_days = numeric_conflict_days
        self.report = {"checked": 0, "downgraded": Counter(), "conflict_edges": 0, "details": []}

    # ---- 검사 4: 근거끼리 충돌 엣지 (판정과 무관하게 그래프 전체에서 먼저 만든다) --------------------
    def build_conflict_edges(self):
        by = {}
        for ev in self.g.of_type("evidence"):
            if ev.get("subject", "patient") != "patient" or ev.get("certainty") == "suspected":
                continue
            key = (ev.get("concept"), (ev.get("term") or "").lower())
            by.setdefault(key, []).append(ev)
        n = 0
        for key, evs in by.items():
            for i in range(len(evs)):
                for j in range(i + 1, len(evs)):
                    a, b = evs[i], evs[j]
                    if not _values_conflict(a, b):
                        continue
                    da, db = _d(a.get("observed_date")), _d(b.get("observed_date"))
                    numeric = not isinstance(a.get("value"), bool) and isinstance(a.get("value"), (int, float))
                    if da and db and abs((da - db).days) > (self.numeric_conflict_days if numeric else self.conflict_days):
                        continue                   # 날짜가 다른 수치는 경과(변화)이지 충돌이 아님 → 최신 값 우선
                    self.g.add_edge(a["id"], "conflicts_with", b["id"], by="agent4")
                    n += 1
        self.report["conflict_edges"] = n
        return n

    # ---- 개별 검사 ---------------------------------------------------------------------------------
    def check_grounding(self, v):
        evs = self.g.evidence_of(v["id"])
        if v.get("missing_evidence_ids"):
            return "UNSUPPORTED", f"존재하지 않는 근거 ID {v['missing_evidence_ids']}"
        if not evs:
            return "UNSUPPORTED", "근거 없음 (supported_by 0)"
        return None, None

    def check_relevance(self, v, crit):
        """인용한 근거 중 하나라도 기준과 같은 개념 '계열'이면 통과. 용어(term)가 달라도 같은 계열이면 통과(Agent 3 의 동의어·상위어 판단 존중).
        계열이 전혀 다르면(예: 기준=혈액검사, 근거=가족력) 격하."""
        cc = crit.get("concept")
        if not cc:
            return None, None                      # free_text 기준은 개념 비교 불가 → 통과 (LLM 판정 영역)
        # 목록에 없는 개념: 검사 수치(_LAB)면 자기 자신만, 그 밖의 측정·등급 개념(LVEF, Child-Pugh, NYHA…)은 관련 진단·병력 근거도 인정
        fam = (CONCEPT_FAMILY[cc] if cc in CONCEPT_FAMILY else ({cc} if cc in _LAB else {cc} | _CLIN)) | {cc}
        evs = self.g.evidence_of(v["id"])
        ok = [ev for ev in evs if (ev.get("subject", "patient") == "patient" or cc == "family_history") and ev.get("concept") in fam]
        if not ok:
            got = sorted({str(ev.get("concept")) + (f"[{ev.get('term')}]" if ev.get("term") else "") for ev in evs})
            return "UNSUPPORTED", f"근거 개념 불일치: 기준 {cc}{crit.get('term') or ''} ↔ 근거 {got}"
        return None, None

    def _window_days(self, crit, evs):
        tw = crit.get("time_window") or {}
        if tw.get("max_days_before"):
            return int(tw["max_days_before"]), "criterion"
        if self.default_windows:
            for ev in evs:
                doc = self.g.document_of(ev["id"]) or {}
                if ev.get("value_type") == "numeric" and doc.get("doc_type") in DEFAULT_WINDOW_DAYS:
                    return DEFAULT_WINDOW_DAYS[doc["doc_type"]], "default"
        return None, None

    def _same_concept_evidence(self, crit):
        """환자 그래프 전체에서 이 기준의 개념(+term)과 같은 근거 — 판정이 인용하지 않은 더 최근 값도 포함."""
        cc = crit.get("concept")
        if not cc:
            return []
        return [ev for ev in self.g.of_type("evidence")
                if ev.get("concept") == cc and ev.get("subject", "patient") == "patient"
                and (cc not in BUCKETS or _terms_match(crit.get("term"), ev.get("term")))]

    def check_note(self, v):
        """노트-상태 불일치: 확정(PASS/FAIL)을 내렸는데 노트가 스스로 불확실하다고 적었다 (Agent 3 인계 README)."""
        m = HEDGE_RX.search(v.get("note") or "")
        return ("UNSUPPORTED", f"확정 판정인데 노트가 불확실: '{m.group(0)}'") if m else (None, None)

    def check_expiry(self, v, crit):
        evs = [ev for ev in self.g.evidence_of(v["id"]) if ev.get("concept") == crit.get("concept")] or self.g.evidence_of(v["id"])
        days, src = self._window_days(crit, evs)
        if not days or not self.as_of:
            return None, None
        if evs and all(ev.get("value") is False for ev in evs):
            return None, None                      # '없음' 근거는 만료로 보지 않는다 (사람 검수 정답이 PASS 로 인정)
        dated = [(ev, _d(ev.get("observed_date"))) for ev in evs + self._same_concept_evidence(crit)]
        dated = [(ev, d) for ev, d in dated if d]
        if not dated:
            return None, None                      # 날짜 없음 → 만료 판단 불가 (TREC 규칙)
        newest = max(d for _, d in dated)          # 인용한 근거가 아니라 같은 개념의 가장 최근 값 기준
        age = (self.as_of - newest).days
        if age > days:
            return "EXPIRED", f"가장 최근 근거 {newest} 는 as_of {self.as_of} 기준 {age}일 전 > 허용 {days}일 ({src})"
        return None, None

    def check_missing_but_stale(self, crit):
        """Agent 3 이 MISSING 으로 둔 기준에 대해, 환자에게 같은 개념의 근거가 있고 전부 기준의 기간보다 오래됐으면 사유 문장을 돌려준다."""
        tw = (crit.get("time_window") or {}).get("max_days_before")
        if not tw or not self.as_of:
            return None
        evs = [(ev, _d(ev.get("observed_date"))) for ev in self._same_concept_evidence(crit)]
        evs = [(ev, d) for ev, d in evs if d]
        if not evs:
            return None
        newest = max(d for _, d in evs)
        age = (self.as_of - newest).days
        return f"MISSING 이지만 같은 개념 근거가 있음: 가장 최근 {newest} 는 {age}일 전 > 허용 {int(tw)}일" if age > int(tw) else None

    def check_conflict(self, v, crit):
        """인용한 근거가 다른 근거와 모순이고, 그 모순이 이 기준의 판정을 실제로 뒤집을 때만 충돌.
        수치는 기준 임계값의 양쪽에 걸릴 때, 불리언은 있음/없음이 갈릴 때. 임계값을 평가할 수 없으면 충돌로 단정하지 않는다."""
        op, thr = crit.get("operator"), crit.get("value")
        unit_ok = str(crit.get("unit") or "").lower() not in ("xuln", "x uln")
        for ev in self.g.evidence_of(v["id"]):
            others = self.g.out(ev["id"], "conflicts_with") + self.g.inn(ev["id"], "conflicts_with")
            real = []
            for o in others:
                ov = self.g.nodes[o]
                a, b = _effective_value(ev), _effective_value(ov)
                if isinstance(a, bool) or isinstance(b, bool):
                    real.append(ov)
                else:
                    try:
                        sa, sb = _threshold_side(op, thr, float(a)), _threshold_side(op, thr, float(b))
                    except (TypeError, ValueError):
                        continue
                    if unit_ok and sa is not None and sb is not None and sa != sb:
                        real.append(ov)
            if real:
                return "CONFLICT", f"근거 {ev['evidence_id']} 가 {[x['evidence_id'] for x in real]} 와 충돌 (기준 판정을 뒤집음)"
        return None, None

    # ---- 격하 --------------------------------------------------------------------------------------
    def downgrade(self, v, crit, reason, why, check, action=None):
        status = "CONFLICT" if reason == "CONFLICT" else "UNKNOWN"
        n = 1 + sum(1 for x in self.g.of_type("verdict") if x["criterion_id"] == v["criterion_id"])
        nid = f"verdict:{v['criterion_id']}#{n}"
        new = self.g.add_node(nid, "verdict", criterion_id=v["criterion_id"], trial_id=v["trial_id"], status=status, reason=reason,
                              expected_action=action or decide_action(reason, crit.get("answerable_by")), by="agent4", verified=True,
                              original_status=v.get("original_status") or v["status"], downgrade_check=check, downgrade_reason=why,
                              note=why, missing_fact=v.get("missing_fact"), judged_by=v.get("judged_by"), rule_tags=v.get("rule_tags"))
        v["downgrade_reason"] = why
        self.g.add_edge(nid, "judges", f"crit:{v['criterion_id']}")
        for ev in self.g.evidence_of(v["id"]):       # 근거 연결은 유지 — 왜 내렸는지 따라갈 수 있어야 함
            self.g.add_edge(nid, "supported_by", ev["id"], kept_from=v["id"])
        self.g.add_edge(nid, "downgraded_from", v["id"], check=check)
        v["verified"] = False
        self.report["downgraded"][check] += 1
        self.report["details"].append({"criterion_id": v["criterion_id"], "trial_id": v["trial_id"], "from": v["status"],
                                       "to": f"{status}/{reason}", "check": check, "why": why, "action": new["expected_action"]})
        self.g.history.append({"event": "downgrade", "verdict": v["id"], "new": nid, "check": check})
        return new

    # ---- 전체 실행 ---------------------------------------------------------------------------------
    def run(self):
        self.build_conflict_edges()
        for v in list(self.g.current_verdicts()):
            if v.get("by") != "agent3":
                continue
            crit = self.g.node(f"crit:{v['criterion_id']}")
            self.report["checked"] += 1
            if v["status"] not in STATUS_FINAL:
                v["verified"] = True                 # UNKNOWN/CONFLICT 는 이미 보수적
                if not v.get("expected_action") or v.get("expected_action") == "none":
                    if v.get("reason") and v.get("reason") != "VALID":     # Agent 3 이 고른 행동은 존중, 비었을 때만 규칙표
                        v["expected_action"] = decide_action(v["reason"], crit.get("answerable_by"))
                if v.get("reason") == "MISSING" and not crit.get("administrative"):
                    why = self.check_missing_but_stale(crit)               # 기록은 있는데 오래됨 → 이유만 EXPIRED 로 바로잡음
                    if why:
                        self.downgrade(v, crit, "EXPIRED", why, "reclass_expired")
                continue
            if crit.get("administrative"):
                v["verified"] = True; continue       # 행정 항목은 시험 판정에서 빠지므로 검사 대상 아님
            for check, fn in (("grounding", lambda: self.check_grounding(v)),
                              ("relevance", lambda: self.check_relevance(v, crit)),
                              ("note", lambda: self.check_note(v)),
                              ("expiry", lambda: self.check_expiry(v, crit)),
                              ("conflict", lambda: self.check_conflict(v, crit))):
                reason, why = fn()
                if reason:
                    self.downgrade(v, crit, reason, why, check, action="clinician_confirmation" if check == "note" else None)
                    break
            else:
                v["verified"] = True
        self.report["downgraded"] = dict(self.report["downgraded"])
        self.report["trial_verdicts"] = {t["trial_id"]: trial_verdict(self.g, t["trial_id"]) for t in self.g.of_type("trial")}
        return self.report


# ---- 시험 판정 (공통 형식 6.1) ---------------------------------------------------------------------
LLM_MISSING = "pc:llm_missing"


def is_llm_missing(v):
    """Agent 3 가 LLM 답을 못 받은 줄 (judged_by 또는 rule_tags 에 pc:llm_missing)."""
    return v.get("judged_by") == LLM_MISSING or LLM_MISSING in (v.get("rule_tags") or [])


def trial_verdict(g, trial_id):
    t = g.node(f"trial:{trial_id}") or {}
    p = g.node(f"patient:{g.patient_id}") or {}
    pending = []
    # 나이·성별
    try:
        if p.get("age") is not None:
            if t.get("min_age") is not None and p["age"] < float(t["min_age"]):
                return {"label": "ineligible", "why": "age < min_age", "pending": [], "label_why": ["age < min_age"]}
            if t.get("max_age") is not None and p["age"] > float(t["max_age"]):
                return {"label": "ineligible", "why": "age > max_age", "pending": [], "label_why": ["age > max_age"]}
    except (TypeError, ValueError):
        pass
    if p.get("sex") and t.get("sex") and str(t["sex"]).upper() not in ("ALL", "") and str(p["sex"]).upper()[:1] != str(t["sex"]).upper()[:1]:
        return {"label": "ineligible", "why": "sex", "pending": [], "label_why": ["sex"]}

    crits = [g.node(c) for c in g.out(f"trial:{trial_id}", "has_criterion")]
    # logic_group OR: 자식 중 하나라도 PASS 면 그룹 통과
    group_pass = set()
    for c in crits:
        members = g.out(c["id"], "in_group")
        if members:
            rel = next((e.get("relation") for e in g.edges if e["src"] == c["id"] and e["rel"] == "in_group"), "OR")
            sts = [vm.get("status") for vm in (g.verdict_for(g.node(m)["criterion_id"]) or {} for m in members) if not is_llm_missing(vm)]
            if rel == "OR" and "PASS" in sts:
                group_pass.update(members); group_pass.add(c["id"])
    # label_why 는 Agent 3 aggregate.trial_label 과 같은 모양: "FAIL <cid>", "<status>/<reason> <cid>", "NOT_JUDGED <cid>"
    label, fails, why = "eligible", [], []
    for c in crits:
        v = g.verdict_for(c["criterion_id"])
        if not v:
            continue
        st, rs, ty = v["status"], v.get("reason"), (c.get("crit_type") or "I")[:1].upper()
        if st == "FAIL":
            fails.append(c["criterion_id"]); continue
        if is_llm_missing(v):
            # LLM 답이 없어 판정되지 않은 기준: 제외 기준·OR 그룹·행정 항목이어도 eligible 로 두지 않는다 (Agent 3 a031 #5 와 같은 규칙)
            label = "potential"; pending.append(c["criterion_id"]); why.append(f"NOT_JUDGED {c['criterion_id']}"); continue
        if c["id"] in group_pass:
            continue
        if ty in ("I", "U"):
            if st in ("UNKNOWN", "CONFLICT") and not (c.get("administrative") and rs == "MISSING"):
                label = "potential"; pending.append(c["criterion_id"]); why.append(f"{st}/{rs} {c['criterion_id']}")
        else:  # E
            if st == "CONFLICT" or (st == "UNKNOWN" and rs in ("EXPIRED", "UNSUPPORTED")):
                label = "potential"; pending.append(c["criterion_id"]); why.append(f"{st}/{rs} {c['criterion_id']}")
    if fails:
        return {"label": "ineligible", "why": fails[0], "pending": [], "label_why": [f"FAIL {x}" for x in fails]}
    return {"label": label, "why": None, "pending": pending, "label_why": why}


def verify(graph, **kw):
    """편의 함수: verify(graph) → (graph, report)"""
    r = Verifier(graph, **kw).run()
    return graph, r
