"""Agent 1 — Trial Parsing Agent.

입력: NCT 번호 하나, 또는 (질환명, 환자 나이·성별)
출력: ⓪ Trial + ①(a+b) Criterion 목록 (공통 형식 v0.5) + 단계별 로그

단계 (plan → retrieve → split → window → structure → link → verify → finalize)
  plan       입력 해석, 캐시 확인                                   코드
  retrieve   ClinicalTrials.gov API (도구). 나이·성별·치료목적 필터     도구
  split      기준 원문 → ①-a  (ctgov_to_common.split_criteria)        규칙
  window     time_window (time_window.extract)                        규칙
  structure  concept/term/operator/value/unit/answerable_by  (LLM)   LLM
  link       administrative, 여러 줄 logic_group (postprocess)         규칙
  verify     사전 키·단위·형식 검사 → 실패 줄 LLM 재시도 → 그래도 안 되면 free_text   자기 검증
  finalize   캐시 저장, 사전 밖 개념 제안

원칙: 모르는 건 free_text 로 솔직하게 둔다. criterion_id 는 split 결과를 그대로 쓴다.
"""
from __future__ import annotations
import json, os, re, sys, time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ctgov_to_common as cc          # ⓪ 변환, ①-a 분할, 스크리닝 플래그
import time_window as tw              # time_window 규칙
import structure_llm as sl            # LLM 구조화 (프롬프트·검증)
import postprocess as pp              # 여러 줄 logic_group
import check_concepts as chk          # 단위 변환 가능 여부
import retrieve                       # API 도구

BATCH = 15
ADMIN_HINT = re.compile(r"\b(informed consent|consent form|willing(ness)? to|able to (comply|attend|complete|understand)|"
                        r"comply with|adhere to|study procedures|protocol requirements|contracept|donat(e|ion) (blood|sperm)|"
                        r"in the opinion of the investigator|investigator'?s? (judgment|discretion|opinion)|"
                        r"legally authorized representative)", re.I)

HEADER_IN_TEXT = re.compile(r"\b(inclusion|exclusion) criteria\s*:", re.I)   # 분할 후에도 남은 제목 = 규칙 분할 실패
LLM_SPLIT_MIN_CHARS = 200
# term 이 개체 자체가 아닌 바구니 (allergy=알레르기 원인, metastasis=부위 …) — 별칭 전환 대상에서 뺀다
TERM_NOT_ENTITY = {"allergy", "metastasis", "biomarker", "tumor_marker", "cancer_stage", "lab_other"}


@dataclass
class Step:
    name: str
    status: str = "ok"          # ok | skipped | failed | pending
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Result:
    trials: list = field(default_factory=list)       # ⓪
    criteria: list = field(default_factory=list)     # ①
    log: list = field(default_factory=list)          # Step 목록
    proposals: Counter = field(default_factory=Counter)   # 사전 밖 개념 제안
    def to_dict(self):
        return {"trials": self.trials, "criteria": self.criteria,
                "log": [s.__dict__ for s in self.log], "concept_proposals": dict(self.proposals)}


class TrialParsingAgent:
    def __init__(self, concepts_path=HERE.parent / "concepts.json", cache_dir=HERE.parent / "cache",
                 model="claude-sonnet-5-5", use_llm=True, today=None):
        self.concepts = json.load(open(concepts_path, encoding="utf-8"))
        self.allowed = [c["key"] for c in self.concepts]
        self.allowed_set = set(self.allowed)
        self.cmap = {c["key"]: c for c in self.concepts}
        self.alias = {}                       # 별칭 → 키 (바구니 키 제외). 제안이 별칭이면 그 키로 돌린다
        self.alias_cb = {}                    # 그중 condition/behavior 키만. 바구니 term 이 별칭이면 그 키로 돌린다
        for c in self.concepts:
            if c["key"] not in sl.BUCKETS:
                for a in [c["key"].replace("_", " ")] + (c.get("aliases") or []):
                    self.alias.setdefault(a.lower(), c["key"])
                    if c.get("type") in ("condition", "behavior"):
                        self.alias_cb.setdefault(a.lower(), c["key"])
        self.cache_dir = Path(cache_dir); self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model, self.use_llm = model, use_llm
        self.today = today or date.today()
        self._client = None
        self.overrides = {}
        op = HERE.parent / "time_window_overrides.json"
        if op.exists():
            self.overrides = json.load(open(op, encoding="utf-8"))

    # ------------------------------------------------------------------ 공개 API
    def run(self, nct_id=None, condition=None, term="", age=None, sex=None, saved=None, max_trials=10) -> Result:
        res = Result()
        t0 = time.time()
        # 1. plan
        if nct_id:
            plan = f"NCT 조회: {nct_id}"
        elif condition:
            plan = f"검색: cond={condition!r} term={term!r} age={age} sex={sex} → 상위 {max_trials}건"
        elif saved:
            plan = f"저장된 응답 사용: {saved}"
        else:
            raise ValueError("nct_id, condition, saved 중 하나는 필요")
        res.log.append(Step("plan", detail=plan, seconds=time.time() - t0))

        # 2. retrieve (도구)
        t0 = time.time()
        try:
            if saved:
                studies = retrieve.load_saved(saved)
            elif nct_id:
                cached = self._cache_get(nct_id)
                if cached:
                    res.trials.append(cached["trial"]); res.criteria.extend(cached["criteria"])
                    res.log.append(Step("retrieve", "skipped", f"캐시 적중: {nct_id}", time.time() - t0))
                    res.log.append(Step("finalize", detail="캐시 결과 반환"))
                    return res
                studies = [retrieve.fetch_study(nct_id)]
            else:
                studies = retrieve.search_studies(condition, term)
        except Exception as e:
            res.log.append(Step("retrieve", "failed", f"{type(e).__name__}: {str(e)[:200]}", time.time() - t0))
            return res
        fetched_at = self.today.isoformat()
        kept = []
        for st in studies:
            t = cc.to_trial(st, fetched_at)
            flags, hard = cc.screen(t, self.today)
            if hard:
                continue
            if age is not None or sex:
                if not self._fits(t, age, sex):
                    continue
            t["screen_flags"] = flags
            kept.append((st, t))
        kept = kept[:max_trials] if condition else kept
        res.log.append(Step("retrieve", detail=f"응답 {len(studies)}건 → 필터 후 {len(kept)}건", seconds=time.time() - t0))

        all_rows = []
        for st, t in kept:
            cached = self._cache_get(t["trial_id"]) if not saved else None
            if cached:
                res.trials.append(cached["trial"]); res.criteria.extend(cached["criteria"]); continue
            rows = self._parse_trial(t, res)
            res.trials.append(t); res.criteria.extend(rows); all_rows.extend(rows)
            if self._cacheable(rows):         # split_only·LLM 실패 결과는 캐시하지 않음 (다음 실행에서 다시 구조화)
                self._cache_put(t, rows)

        # 8. finalize
        res.log.append(Step("finalize", detail=f"시험 {len(res.trials)}건, 기준 {len(res.criteria)}줄, "
                                               f"structured {sum(c['parse_status']=='structured' for c in res.criteria)}줄, "
                                               f"사전 밖 제안 {sum(res.proposals.values())}줄/{len(res.proposals)}종"))
        return res

    # ------------------------------------------------------------------ 시험 하나 처리
    def _parse_trial(self, trial, res: Result):
        tid = trial["trial_id"]
        # 3. split
        t0 = time.time()
        rows = cc.split_criteria(tid, trial["eligibility_text"])
        split_by, note = "rule", ""
        if self.use_llm and self._needs_llm_split(trial["eligibility_text"], rows):
            llm_rows, dropped = self._llm_split(tid, trial["eligibility_text"])
            if llm_rows:
                note = f" ← 규칙 {len(rows)}줄을 LLM 이 다시 분할" + (f" (원문에 없는 조각 {dropped}개 버림)" if dropped else "")
                rows, split_by = llm_rows, "llm"
            else:
                note = " (LLM 분할 실패 — 규칙 결과 유지)"
        trial["split_by"] = split_by
        for r in rows:
            r["administrative"] = bool(ADMIN_HINT.search(r["original_text"]))   # 1차: 규칙. LLM 이 보강
            r["term"] = None; r["concept_proposed"] = None; r["inline_relation"] = None
        res.log.append(Step(f"split:{tid}", detail=f"{len(rows)}줄 (unknown {sum(r['type']=='unknown' for r in rows)}), split_by={split_by}{note}", seconds=time.time() - t0))
        # 4. window
        t0 = time.time(); n = 0
        for r in rows:
            ov = self.overrides.get(r["criterion_id"])
            if ov:
                w = ov["time_window"]
            else:
                w, _flags = tw.extract(r["original_text"])
            if w:
                r["time_window"] = {"anchor": "as_of", "max_days_before": w.get("max_days_before"), "min_days_before": w.get("min_days_before")}
                n += 1
        res.log.append(Step(f"window:{tid}", detail=f"{n}줄", seconds=time.time() - t0))
        # 5. structure (LLM)
        t0 = time.time()
        todo = [r for r in rows if not r["administrative"]]
        if self.use_llm and todo:
            ok, failed = self._structure(todo)
            if failed:
                for r in todo:
                    r["_llm_failed"] = True
            res.log.append(Step(f"structure:{tid}", "ok" if not failed else "failed",
                                f"LLM {len(todo)}줄 → 성공 {ok}, 실패 묶음 {failed}", time.time() - t0))
        else:
            res.log.append(Step(f"structure:{tid}", "pending" if todo else "skipped",
                                "LLM 비활성(use_llm=False) — split_only 로 둠" if todo else "행정 항목만", time.time() - t0))
        for r in rows:
            if r["administrative"]:
                r.update(concept=None, term=None, operator=None, value=None, unit=None, answerable_by=["patient"])
            r["parse_status"] = "structured" if r.get("concept") else ("free_text" if (r["administrative"] or self.use_llm) else "split_only")
        # 6. link
        t0 = time.time()
        for r in rows:
            lg = r.get("logic_group")
            r["inline_relation"] = lg["relation"] if isinstance(lg, dict) else None
            r["logic_group"] = None
        groups = pp.build_groups(rows)
        for r in rows:
            if r["criterion_id"] in groups:
                gid, rel, role = groups[r["criterion_id"]]
                r["logic_group"] = {"group_id": gid, "relation": rel, "role": role}
        res.log.append(Step(f"link:{tid}", detail=f"여러 줄 묶음 {len({g[0] for g in groups.values()})}개", seconds=time.time() - t0))
        # 7. verify (자기 검증)
        t0 = time.time()
        problems = self._verify(rows)
        retried = 0
        if problems and self.use_llm:
            bad = [r for r in rows if r["criterion_id"] in problems]
            self._structure(bad)                      # 한 번 더
            still = self._verify(bad)
            for r in bad:
                if r["criterion_id"] in still:        # 그래도 안 맞으면 솔직하게 free_text
                    r.update(concept=None, term=None, operator=None, value=None, unit=None, parse_status="free_text")
                    r["verify_note"] = still[r["criterion_id"]]
            for r in bad:                             # 재시도 결과로 상태를 다시 매긴다
                if r["criterion_id"] not in still:
                    r["parse_status"] = "structured" if r.get("concept") else "free_text"
            retried = len(bad)
            problems = still
        res.log.append(Step(f"verify:{tid}", "ok" if not problems else "failed",
                            f"재시도 {retried}줄, 남은 문제 {len(problems)}줄 → free_text", time.time() - t0))
        for r in rows:
            if r.get("concept_proposed"):
                res.proposals[r["concept_proposed"]] += 1
        return rows

    # ------------------------------------------------------------------ 내부
    def _structure(self, rows):
        client = self._llm()
        ok, failed = 0, 0
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            try:
                arr = sl.parse_json_array(sl.call_claude(client, self.model, sl.build_user_msg(batch, self.allowed)))
            except SystemExit:
                raise
            except Exception:
                failed += 1; continue
            byid = {o.get("criterion_id"): o for o in arr if isinstance(o, dict)}
            for r in batch:
                o = byid.get(r["criterion_id"])
                if not o:
                    continue
                o = sl.validate(o, r["original_text"], self.allowed_set, keep_bucket=True)
                self._resolve_alias(o)
                for k in ("concept", "term", "concept_proposed", "operator", "value", "unit", "logic_group", "answerable_by", "complex", "change"):
                    r[k] = o.get(k)
                if o.get("concept") == "administrative" or (o.get("concept_proposed") == "administrative"):
                    r["administrative"] = True
                ok += 1
        return ok, failed

    def _resolve_alias(self, o):
        """사전 별칭으로 더 구체적인 키가 있으면 그 키로 돌린다 (exists/not_exists 만).
        - 제안이 별칭:                      concept_proposed "breastfeeding"  → pregnancy
        - 바구니 term 중 하나가 condition/behavior 키의 별칭: diagnosis["breastfeeding"] → pregnancy"""
        if o.get("operator") not in ("exists", "not_exists"):
            return
        cp = o.get("concept_proposed")
        if cp and not o.get("concept") and self.alias.get(cp.replace("_", " ")):
            o["concept"], o["concept_proposed"] = self.alias[cp.replace("_", " ")], None
        elif o.get("concept") in sl.BUCKETS and o.get("concept") not in TERM_NOT_ENTITY and o.get("term"):
            k = next((self.alias_cb[t.lower()] for t in o["term"] if t.lower() in self.alias_cb), None)
            if k:
                o["concept"], o["term"] = k, None

    def _needs_llm_split(self, text, rows):
        """규칙 분할이 1~2줄인데 원문이 길거나, 줄 안에 Inclusion/Exclusion 제목이 남아 있으면 LLM 에게 분할을 맡긴다."""
        if not 1 <= len(rows) <= 2:
            return False
        return len(text or "") >= LLM_SPLIT_MIN_CHARS or any(HEADER_IN_TEXT.search(r["original_text"]) for r in rows)

    def _llm_split(self, tid, text):
        """원문 → 항목별 ①-a. criterion_id 는 {NCT}-I01 / E01 / U01 규칙으로 새로 매긴다. (줄 목록, 버린 수)"""
        try:
            arr = sl.parse_json_array(sl.call_claude(self._llm(), self.model, "Eligibility text:\n" + text, system=sl.SPLIT_SYSTEM))
        except SystemExit:
            raise
        except Exception:
            return [], 0
        items, dropped = sl.validate_split(arr, text)
        rows, n = [], Counter()
        for it in items:
            n[it["type"]] += 1
            letter = {"inclusion": "I", "exclusion": "E", "unknown": "U"}[it["type"]]
            rows.append({"trial_id": tid, "criterion_id": f"{tid}-{letter}{n[it['type']]:02d}",
                         "type": it["type"], "original_text": cc.clean(it["text"]), "cohort": None,
                         "parse_status": "split_only", "concept": None, "operator": None, "value": None, "unit": None,
                         "time_window": None, "logic_group": None, "answerable_by": None})
        return rows, dropped

    def _verify(self, rows):
        """사전 키·단위·형식 검사. {criterion_id: 문제 설명}"""
        bad = {}
        for r in rows:
            c = r.get("concept")
            if not c:
                continue
            if c not in self.allowed_set:
                bad[r["criterion_id"]] = f"사전에 없는 키 {c}"; continue
            if c in sl.BUCKETS and not r.get("term"):
                bad[r["criterion_id"]] = f"term 없음 (바구니 키 {c})"; continue
            op = r.get("operator")
            if op in chk.NUMERIC_OPS:
                v = r.get("value")
                if v is None or (op == "between" and not (isinstance(v, list) and len(v) == 2)):
                    bad[r["criterion_id"]] = f"{op} 인데 value 형식 오류"; continue
                u, cu = r.get("unit"), self.cmap[c].get("unit")
                if u and cu and not self._unit_ok(self.cmap[c], u) and not re.search(r"ULN|fold", u, re.I):
                    bad[r["criterion_id"]] = f"단위 {u} → {cu} 변환 불가"
        return bad

    def _unit_ok(self, concept, u):
        """chk.unit_ok + 표기 차이('^', 공백, 대소문자) 무시: 'mL/min/1.73 m^2' == 'mL/min/1.73m2'."""
        if chk.unit_ok(concept, u):
            return True
        n = lambda x: re.sub(r"[\s^]", "", x or "").lower()   # noqa: E731
        return n(u) in {n(concept.get("unit"))} | {n(a) for a in (concept.get("alt_units") or {})}

    def _fits(self, t, age, sex):
        lo, hi = t.get("min_age"), t.get("max_age")
        if age is not None:
            if lo is not None and age < lo: return False
            if hi is not None and age > hi: return False
        ts = (t.get("sex") or "ALL").upper()
        return not sex or ts == "ALL" or ts == sex.upper()

    def _llm(self):
        if self._client is None:
            if not os.environ.get("ANTHROPIC_API_KEY"):
                sys.exit("ANTHROPIC_API_KEY 환경변수가 없습니다.")
            import anthropic
            self._client = anthropic.Anthropic(default_headers={"accept-encoding": "gzip, deflate"})
        return self._client

    def _cacheable(self, rows):
        failed = any([r.pop("_llm_failed", False) for r in rows])
        return self.use_llm and not failed and not any(r["parse_status"] == "split_only" for r in rows)

    def _cache_get(self, tid):
        p = self.cache_dir / f"{tid}.json"
        if not p.exists():
            return None
        d = json.load(open(p, encoding="utf-8"))
        if any(r.get("parse_status") == "split_only" for r in d["criteria"]):
            return None                       # 구조화 안 된 옛 캐시는 무시
        return d

    def _cache_put(self, trial, rows):
        json.dump({"trial": trial, "criteria": rows}, open(self.cache_dir / f"{trial['trial_id']}.json", "w", encoding="utf-8"), ensure_ascii=False)

    # 기존 ①-b 결과(dev/test)를 캐시로 적재 — 548개 시험은 다시 LLM 을 부르지 않게
    def import_structured(self, trials_jsonl, criteria_jsonl):
        trials = {json.loads(l)["trial_id"]: json.loads(l) for l in open(trials_jsonl, encoding="utf-8") if l.strip()}
        rows_by = {}
        for l in open(criteria_jsonl, encoding="utf-8"):
            if l.strip():
                r = json.loads(l); rows_by.setdefault(r["trial_id"], []).append(r)
        n = 0
        for tid, t in trials.items():
            if tid in rows_by:
                self._cache_put(t, rows_by[tid]); n += 1
        return n
