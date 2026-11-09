"""LLM briefings (clinician + patient) that keep BRIEFING_FORMAT.md: every sentence carries graph refs.

  python3 -m agent6.brief_llm --ranking runs/rank_dev/ranking.jsonl --graphs G1 G2 \
      --trials K/dev/reference/trials.jsonl --out runs/brief_llm_dev [--model claude-sonnet-5-5] [--dry-run]

How grounding is kept by construction
  1. Code turns the graph into a numbered fact pack per patient: each fact has an id (T1.label, T1.i2 ...), the refs
     it stands for, a template Korean sentence (`ko`) and the raw detail (`detail`: criterion text, note, missing_fact).
  2. The LLM only rewrites/groups facts and must cite fact ids per sentence. Code maps fact ids -> refs. The LLM never
     writes a node id, so it cannot invent one.
  3. Fixed sentences (rules.py: research_not_treatment, randomized, placebo, voluntary ...) are inserted by code,
     verbatim, never by the LLM.
  4. Each draft is checked with check_grounding.check + check_content.check, plus "required facts cited" (trial label;
     open exclusion count; review flags). On failure: one retry with the problems listed; still failing -> that
     trial falls back to the template sentences (logged in <out>/llm_log.jsonl). So the output always passes.
  5. Clinician: LLM summary per trial on top, then the template detail lines (brief_clinician.trial_section) as is.

API key: ANTHROPIC_API_KEY from the environment or a .env file in the working directory (never printed or written).
Endpoint: AGENT6_API_BASE (default https://api.anthropic.com). Responses are cached in <out>/../.llm_cache (do not
ship it). --dry-run uses a fake LLM that returns each fact's template sentence: tests the whole path without a key.
"""
import argparse, hashlib, json, os, re, sys, time, urllib.error, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import brief_clinician as BC
from . import VERSION
from . import check_content, check_grounding
from . import glossary as GL
from .keyinfo import closing_rules, design_rules, opening_rules, patient_facts, site_lines
from . import keyinfo as KI
from .graph import Graph
from .rank import read_jsonl
from .review import FLAG_KO
from .rules import BANNED, FIXED

PROMPT_VERSION = {"patient": "pb10", "clinician": "cb04"}
DEFAULT_MODEL = "claude-sonnet-5-5"

COMMON_RULES = """규칙 (모두 지킬 것):
- 사실 묶음(facts)에 있는 내용만 쓴다. 묶음에 없는 의학 지식, 효과, 위험, 일정, 기관 이름을 덧붙이지 않는다.
- 문장마다 근거로 쓴 사실 id를 "facts"에 모두 적는다. 여러 사실을 한 문장에 묶으면 그 id를 모두 적는다.
- 숫자, 날짜, 약 이름, 검사 이름, 단위는 detail에 적힌 값 그대로 쓴다. 새로 계산하거나 반올림하지 않는다.
- 기준일(as_of) {as_of}를 오늘로 본다. 다른 현재 날짜는 무시한다. 경과일이 필요하면 detail의 days_before만 쓴다.
- 시험 판정 eligible도 확정이 아니다. eligible은 "지금 기록으로는 조건이 맞을 가능성이 높습니다", potential은 "아직 확인이 필요한 조건이 있습니다"의 뜻으로 쓴다.
- 제외 기준 PASS는 "제외 사유 없음"이다. "충족"이라고 쓰지 않는다.
- 미확인(UNKNOWN)·기록 충돌(CONFLICT) 조건을 맞았다거나 문제없다고 쓰지 않는다.
- 다음 표현은 쓰지 않는다: {banned}
- 고정 안내 문구(연구라는 사실, 시험 단계, 비교 방식, 무작위 배정, 위약, 눈가림, 자발적 참여, 철회, 의료진에게 물어볼 것)는 코드가 따로 넣으므로 쓰지 않는다.
- 시험이 환자에게 효과가 있을 것처럼 쓰지 않는다. "이 시험은 ~을(를) 연구 대상으로 합니다"처럼 시험이 무엇을 연구하는지만 쓴다. 효과는 아직 확인되지 않았다.
- required가 true인 사실은 반드시 어느 문장에선가 인용한다.
- 사실 하나는 문장 하나에만 쓴다. 한 사실을 여러 문장으로 나누지 않는다 (문장의 근거 링크가 그 사실 전체를 가리키기 때문).
- 출력은 JSON 하나만: {{"sentences": [{{"trial": "T1", "text": "...", "facts": ["T1.label", ...]}}]}}. trial은 그 문장이 다루는 시험의 T 번호.
- T1·T2 같은 T 번호와 사실 id는 내부 표시다. 문장(text)에는 쓰지 않는다. 시험은 환자용은 "<번호>번 시험", 의료진용은 시험 번호(NCT)로 가리킨다."""

AUDIENCE_RULES = {
    "patient": """읽는 사람: 환자와 보호자. 의학 지식이 없는 성인.
- 쉬운 한국어, 한 문장에 한 가지 내용, 문장은 짧게 (대략 60자 이내). 존댓말.
- 괄호 밖에 영어를 쓰지 않는다. 예외: detail에 적힌 한국어 이름 안의 영어(HER2, IgA 등)와, untranslated 원어의 괄호 병기.
- 시험마다 첫 문장은 "<번호>번 시험 — <판정>" 형태로 쓰고 T*.label을 인용한다. 공식 제목과 시험 번호(NCT)는 쓰지 않는다.
- 질환·진단 이름: detail의 conditions_ko / diagnosis_ko 중 한국어 이름은 글자 그대로 쓴다 (검토된 용어집). untranslated에 있는 영어 이름만 쉬운 한국어로 옮기되, 반드시 원어를 글자 그대로 괄호에 병기한다 (예: 중증 근무력증(Myasthenia Gravis)). Neoplasm·Tumor는 "종양"으로 옮기고, cancer·carcinoma·malignant가 원어에 있을 때만 "암"으로 옮긴다.
- 원어를 옮길 때 원어에 있는 병기·등급·단계·부위·범위는 한국어 이름에도 빠뜨리지 않는다 (stage, grade, BCLC B, pT3N2a, multifocal, OD/OS 등). 예: multifocal hepatocellular carcinoma BCLC B → 다발성 간세포암 BCLC B기(multifocal hepatocellular carcinoma BCLC B).
- HR+, ER+, PR+ 같은 약어는 한국어로 풀어 쓴다. 예: HR+/HER2- breast cancer → 호르몬 수용체 양성·HER2 음성 유방암(HR+/HER2- breast cancer). 유전자·표지자 이름(HER2, PIK3CA, KRAS, EGFR, BRAF, IgA 등)은 그대로 쓴다.
- 약 이름은 병명 안에 있어도 원어 그대로 쓴다. 한국어로 소리 나는 대로 옮기지 않는다. 예: Insufficient Response to Methotrexate or Leflunomide → Methotrexate 또는 Leflunomide에 충분히 반응하지 않는 상태(Insufficient Response to Methotrexate or Leflunomide).
- 조사는 바로 앞 한국어 글자에 맞춰 고른다 (을/를, 이/가). "을(를)"처럼 두 가지를 같이 쓰지 않는다.
- 시험마다 이 순서로 쓴다: 판정(T*.label) → 무엇을 연구하는지(T*.studies, T*.enroll) → 기록에서 맞는 조건(T*.confirmed) → 남은 확인(T*.route_*) → 제외 기준 개수(T*.excl) → 모집(T*.kr, T*.stale).
- 남은 확인은 누가 확인하는지와 개수만 쓴다(route_ask_you: 직접 답할 질문, route_records: 진료 기록, route_tests: 검사, route_doctor: 담당 의사 판단). 기준의 내용(검사 이름, 수치, 기간, 동의·보험 같은 절차)은 쓰지 않는다. 내용은 의료진이 설명한다. 추측(아마 맞을 것)은 쓰지 않는다.
- T*.studies가 "담당 의료진이 먼저 설명드립니다" 문장이면, 그 시험에 대해서는 질환 이름, 암, 종양, 항암 같은 말을 어디에도 쓰지 않는다 (환자 기록에 확정된 암 진단이 없는 경우다).
- T*.confirmed는 "기록의 진단이 대상 조건과 맞는다"는 뜻일 뿐이다. 참여할 수 있다는 뜻으로 쓰지 않는다.
- 제외 기준 미확인은 개수만 쓴다 (T*.excl).
- 참여를 권하거나 기대를 키우는 말을 쓰지 않는다.""",
    "clinician": """읽는 사람: 연구 담당 의료진.
- 시험마다 2~5문장 요약: 판정과 남은 항목 수, 판정을 막는 포함 기준과 필요한 정보, 기록 충돌, 재확인 표시, 모집 상태.
- 재확인 표시는 flag_* 사실이 있을 때만 쓴다. 모집 상태 미확인(stale)은 재확인 표시가 아니다. 사실 묶음에 없는 표시·판단·권고를 만들지 않는다.
- 간결한 한국어. 기준·검사·약 이름은 영어 원어를 그대로 써도 된다. 세부 판정 목록은 코드가 뒤에 붙이므로 하나씩 나열하지 않는다.""",
}


# ---------- fact pack ----------

def _excl(g, d):
    return g.nodes.get(f"crit:{d['criterion_id']}", {}).get("type") == "exclusion"


def fact_pack(g, item, trial, n, audience):
    if audience == "patient":
        facts = patient_facts(g, item, trial, n)    # shared with the template writer (keyinfo.py)
        for f in facts:   # pb08: the LLM writes who checks and how many, not the criterion contents
            if ".route_" in f["id"]:
                f["detail"] = {"who": f["detail"].get("who"), "count": len(f["detail"].get("items", []))}
        return facts
    tid = item["trial_id"]
    T = f"T{n}"
    lab = g.label(tid)
    title = trial.get("title") or tid
    flags = item.get("review_flags", [])
    pending = [f["criterion_id"] for f in flags if f["flag"] == "llm_missing"]
    decs = g.decisions(tid)
    open_ = [d for d in decs if d["status"] in ("UNKNOWN", "CONFLICT")]
    incl = [d for d in open_ if not _excl(g, d)]
    excl = [d for d in open_ if _excl(g, d)]
    facts = []

    def F(fid, refs, ko, detail, required=False):
        facts.append({"id": f"{T}.{fid}", "refs": sorted(set(refs)), "ko": ko, "detail": detail, "required": required})

    label_word = "pending (판정 미완료)" if pending else item["label"]
    if audience == "patient":
        ko = (f"{n}. {title} — 기록 검토가 아직 끝나지 않아, 조건이 맞는지 아직 말씀드릴 수 없습니다." if pending else
              f"{n}. {title} — 지금 기록으로는 조건이 맞을 가능성이 높습니다." if item["label"] == "eligible" else
              f"{n}. {title} — 아직 확인이 필요한 조건이 있습니다.")
    else:
        ko = f"시험 판정: {item['label']}" + (f" (남은 항목 {len(item['open_criteria'])}개)" if item["open_criteria"] else "")
    pend_refs = [g.decision(f"crit:{c}")["id"] for c in pending]
    F("label", [f"trial:{tid}", lab["id"]] + pend_refs, ko,
      {"title": title, "label": label_word, "conditions": trial.get("conditions"), "phases": trial.get("phases"),
       "interventions": [i for a in trial.get("arms") or [] for i in a.get("interventions", [])][:6],
       "open_inclusion": len(incl), "open_exclusion": len(excl)}, True)
    for k, d in enumerate(incl, 1):
        crit = g.nodes[f"crit:{d['criterion_id']}"]
        det = {"criterion": crit.get("text"), "status": d["status"], "reason": d.get("reason"),
               "next_action": d.get("action"), "missing_info": d.get("missing_fact")}
        if audience == "clinician":
            det["note"] = d.get("note")
            det["criterion_id"] = d["criterion_id"]
        ko = (
              f"{d['criterion_id']} 미확인 ({BC.REASON_KO.get(d.get('reason'), '')})" +
              (f": {d['missing_fact']}" if d.get("missing_fact") else ""))
        F(f"i{k}", [crit["id"], d["id"]], ko, det)
    if excl:
        if audience == "patient":
            F("excl", [d["id"] for d in excl], f"참여 전에 의료진이 확인할 항목이 {len(excl)}개 남아 있습니다.",
              {"open_exclusion_count": len(excl)}, True)
        else:
            conf = [d for d in excl if d["status"] == "CONFLICT"]
            F("excl", [d["id"] for d in excl], f"제외 기준 미확인 {len(excl)}개" + (f" (기록 충돌 {len(conf)}개)" if conf else ""),
              {"open_exclusion_count": len(excl), "conflict": [{"criterion_id": d["criterion_id"], "note": d.get("note")}
                                                              for d in conf]}, True)
    if audience == "clinician":
        for fl in ("llm_missing", "note_negates"):
            ids = [f["criterion_id"] for f in flags if f["flag"] == fl]
            if ids:
                F(f"flag_{fl}", [g.decision(f"crit:{c}")["id"] for c in ids], f"{FLAG_KO[fl]}: " + ", ".join(ids),
                  {"flag": FLAG_KO[fl], "criteria": ids}, True)
    if item["kr_sites"] > 0:
        F("kr", [f"trial:{tid}"], f"국내 {item['kr_sites']}곳에서 모집 중입니다." if audience == "patient"
          else f"국내 모집 기관 {item['kr_sites']}곳", {"kr_sites": item["kr_sites"]})
    elif audience == "clinician":   # a6-0.4.13
        F("kr", [f"trial:{tid}"], BC.no_kr_line(trial), {"kr_sites": 0, "countries": BC.site_countries(trial)})
    if audience == "clinician" and BC.arms_line(trial):
        F("arms", [f"trial:{tid}"], BC.arms_line(trial), {"arms": trial.get("arms")})
    if item["stale"]:
        F("stale", [f"trial:{tid}"], "모집 상태가 최근에 확인되지 않아, 지금도 모집 중인지 확인이 필요합니다." if audience == "patient"
          else f"모집 상태가 {item['months_since_verified']}개월 동안 확인되지 않음 (status_verified {item['status_verified']})",
          {"months_since_verified": item["months_since_verified"]}, True)
    return facts


def fixed_after(trial, tid):
    return design_rules(trial, tid)


# ---------- LLM ----------

def load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
        if m and m.group(1) not in os.environ:
            os.environ[m.group(1)] = m.group(2).strip().strip("'\"")


class LLM:
    def __init__(self, model, cache_dir, dry_run=False):
        self.model, self.cache_dir, self.dry = model, cache_dir, dry_run
        os.makedirs(cache_dir, exist_ok=True)
        self.base = os.environ.get("AGENT6_API_BASE", "https://api.anthropic.com").rstrip("/")
        self.key = os.environ.get("ANTHROPIC_API_KEY")
        if not dry_run and not self.key:
            sys.exit("ANTHROPIC_API_KEY not set (environment or .env). Use --dry-run to test without a key.")
        self.usage = Counter()

    def __call__(self, system, user, pack):
        if self.dry:
            return json.dumps({"sentences": [{"trial": f["id"].split(".")[0], "text": f["ko"], "facts": [f["id"]]}
                                             for f in pack]}, ensure_ascii=False)
        h = hashlib.sha256(json.dumps([self.model, os.environ.get("AGENT6_TEMPERATURE"), system, user]).encode()).hexdigest()[:24]
        cp = os.path.join(self.cache_dir, h + ".json")
        if os.path.exists(cp):
            self.usage["cache_hit"] += 1
            return json.load(open(cp, encoding="utf-8"))["text"]
        req_body = {"model": self.model, "max_tokens": 4096, "system": system,
                    "messages": [{"role": "user", "content": user}]}
        if os.environ.get("AGENT6_TEMPERATURE"):   # off by default: Sonnet 5.5 does not take temperature
            req_body["temperature"] = float(os.environ["AGENT6_TEMPERATURE"])
        body = json.dumps(req_body).encode()
        for attempt in range(5):
            req = urllib.request.Request(self.base + "/v1/messages", data=body, method="POST", headers={
                "x-api-key": self.key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    res = json.load(r)
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529) and attempt < 4:
                    time.sleep(2 ** attempt * 3)
                    continue
                raise RuntimeError(f"API error {e.code}: {e.read()[:300]!r}")
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
                # a6-0.4.11: network errors (timeout, reset) are retried like 5xx instead of going straight to the
                # template fallback (v6 LLM run: 2 trial sections lost to "Operation timed out")
                if attempt < 4:
                    time.sleep(2 ** attempt * 3)
                    continue
                raise RuntimeError(f"network error after 5 tries: {e}")
        text = "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text")
        u = res.get("usage", {})
        self.usage["input_tokens"] += u.get("input_tokens", 0)
        self.usage["output_tokens"] += u.get("output_tokens", 0)
        self.usage["calls"] += 1
        json.dump({"model": self.model, "text": text}, open(cp, "w", encoding="utf-8"), ensure_ascii=False)
        return text


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    return json.loads(m.group(0))["sentences"]


# ---------- assemble + check ----------

_STAGE = re.compile(r"(?i)(?<![A-Za-z0-9])(BCLC\s*[0A-D]|stage\s*([0IV]+|[0-4])([A-C])?|grade\s*([1-4])([ab])?|p?T[0-4][a-c]?N[0-3][a-c]?(?:M[01])?)(?![A-Za-z0-9])")
_ROMAN = {"0": "0", "I": "1", "II": "2", "III": "3", "IV": "4"}
_ABBR = re.compile(r"(?<![A-Za-z0-9])(?:HR|ER|PR)[+-]")


def qualifier_missing(term, text):
    """a6-0.4.11/0.4.11: a stage/grade written in the original term must also appear outside that original (literal, or
    Korean "4기" / "2등급"). The original itself is removed from the text first, so the parenthesised gloss does not count."""
    rest = text.replace(term, " ")
    miss = []
    for m in _STAGE.finditer(term):
        tok = m.group(1)
        ok = re.sub(r"\s+", "", tok).lower() in re.sub(r"\s+", "", rest).lower()
        if not ok and m.group(2):
            n = _ROMAN.get(m.group(2).upper(), m.group(2))
            ok = (n + (m.group(3) or "").upper() + "기") in rest or (m.group(2).upper() + (m.group(3) or "").upper() + "기") in rest
        if not ok and m.group(4):
            ok = (m.group(4) + (m.group(5) or "") + "등급") in rest
        if not ok:
            miss.append(tok)
    return miss


def abbreviation_left(term, text):
    """HR+/ER+/PR+ left as is outside the parenthesised original (patient text)."""
    return _ABBR.findall(text.replace(term, " "))


def assemble(draft, packs, audience):
    """draft sentences -> {T: [sentence]} with refs from fact ids; problems for unknown ids / required facts."""
    by_id = {f["id"]: f for fs in packs.values() for f in fs}
    out, probs = {T: [] for T in packs}, []
    for s in draft:
        T = s.get("trial") or (s.get("facts") or ["?."])[0].split(".")[0]
        fids = [x for x in s.get("facts", []) if x in by_id]
        bad = [x for x in s.get("facts", []) if x not in by_id]
        if bad:
            probs.append(f"없는 사실 id {bad}")
        if T not in out:
            probs.append(f"없는 시험 번호 {T}")
            continue
        if not fids:
            probs.append(f"사실 id 없는 문장: {s.get('text', '')[:40]}")
            continue
        refs = sorted({r for x in fids for r in by_id[x]["refs"]})
        text = KI.fix_josa(s["text"].strip())   # a6-0.4.11: 을(를) after a Korean name -> 을 / 를
        if re.search(r"(?<![A-Za-z0-9])T\d+(?![0-9A-Za-z])", text):   # internal pack labels leaking into the text ("T1은 …")
            probs.append(f"{T}: 내부 번호(T*)를 문장에 씀: {text[:40]}")
        for x in fids:   # a term outside the glossary must stay in the sentence verbatim (parenthesised gloss recommended;
            #            only presence is checked, not position nor whether it was translated)
            for term in (by_id[x].get("detail") or {}).get("untranslated", []):
                if term.lower() not in text.lower():
                    probs.append(f"{T}: 원어 병기 없음 '{term}' (사전 밖 용어는 원어를 괄호에 함께 쓸 것): {text[:40]}")
                elif audience == "patient":
                    miss = qualifier_missing(term, text)
                    if miss:
                        probs.append(f"{T}: 원어의 병기·등급을 한국어에 쓰지 않음 {miss}: {text[:40]}")
                    ab = abbreviation_left(term, text)
                    if ab:
                        probs.append(f"{T}: 약어를 풀지 않음 {ab}: {text[:40]}")
        out[T].append({"text": text, "refs": refs, "kind": "fact", "facts": fids})
    for T in out:   # a fact split over several sentences would give each sentence the whole fact's refs
        seen = {}
        for s in out[T]:
            for x in s["facts"]:
                seen[x] = seen.get(x, 0) + 1
        dup = sorted(x for x, k in seen.items() if k > 1)
        if dup:
            probs.append(f"{T}: 한 사실을 여러 문장에 씀 {dup} (사실 하나는 문장 하나에)")
    for T, fs in packs.items():
        cited = {x for s in out[T] for x in s["facts"]}
        miss = [f["id"] for f in fs if f["required"] and f["id"] not in cited]
        if miss:
            probs.append(f"{T}: 필수 사실 미인용 {miss}")
    return out, probs


def sentence_problems(sents, g, trials, audience, ranking, flags=None):
    doc = {"audience": audience, "ranking": ranking, "sentences": sents, "as_of": g.as_of}
    r = check_grounding.check(doc, g)
    probs = [f"근거 없는 문장 #{i}" for i in r["unlinked"]] + [f"없는 ID {x}" for x in r["bad_refs"]]
    probs += [f"금지 표현 '{w}': {sents[i]['text'][:50]}" for i, w in r["banned"]]
    probs += [f"순위에 없는 시험 {x}" for x in r["trials_not_ranked"]]
    probs += [f"{k} {v!r}: {sents[i]['text'][:60]}" for i, k, v in check_content.check(doc, g, trials, flags)]
    return probs


def build(pid, r, g, trials, audience, llm, top):
    items = r["items"][:top] if audience == "patient" else r["items"]
    packs = {f"T{n}": fact_pack(g, it, trials.get(it["trial_id"], {}), n, audience) for n, it in enumerate(items, 1)}
    log = {"patient_id": pid, "audience": audience, "prompt": PROMPT_VERSION[audience], "model": llm.model,
           "tries": 0, "fallback": [], "problems": []}
    by_T = {}
    if items:
        system = COMMON_RULES.format(as_of=g.as_of, banned=", ".join(BANNED)) + "\n\n" + AUDIENCE_RULES[audience]
        payload = {"as_of": g.as_of, "trials": [{"T": T, "facts": [{k: f[k] for k in ("id", "ko", "detail", "required")}
                                                                     for f in fs]} for T, fs in packs.items()]}
        user = "사실 묶음:\n" + json.dumps(payload, ensure_ascii=False, indent=1)
        flat = [f for fs in packs.values() for f in fs]
        probs = None
        for attempt in range(2):
            log["tries"] += 1
            msg = user if probs is None else user + "\n\n이전 답의 문제 (모두 고쳐서 전체를 다시 쓸 것):\n- " + "\n- ".join(probs[:30])
            try:
                draft = parse(llm(system, msg, flat))
                by_T, probs = assemble(draft, packs, audience)
                for T, ss in by_T.items():
                    probs += [f"{T}: {p}" for p in sentence_problems(ss, g, trials, audience, [i["trial_id"] for i in items],
                                                                       check_content.flags_by_trial([r]))]
            except Exception as e:  # noqa: BLE001 - any bad reply -> retry, then template fallback
                by_T, probs = {}, [f"응답 처리 실패: {e}"]
            if not probs:
                break
        log["problems"] = probs or []
        for T in packs:
            bad = not by_T.get(T) or any(p.startswith(T + ":") or p.startswith("응답") for p in (probs or []))
            if bad:   # template fallback for this trial: always grounded
                by_T[T] = [{"text": f["ko"], "refs": f["refs"], "kind": "fact"} for f in packs[T]]
                log["fallback"].append(T)
    sents = []
    if audience == "patient":
        sents += opening_rules(g)
        if not items:
            sents.append(BC.S("지금 기록으로는 조건이 맞을 가능성이 있는 시험을 찾지 못했습니다.",
                              [f"label:{t['id'][6:]}" for t in g.trials()] or ["rule:ask_clinician"]))
        for n, it in enumerate(items, 1):
            sents += [{k: v for k, v in s.items() if k != "facts"} for s in by_T[f"T{n}"]]
            sents += fixed_after(trials.get(it["trial_id"], {}), it["trial_id"])
            sents += site_lines(it, trials.get(it["trial_id"], {}))   # a6-0.4.13
        sents += closing_rules()
    else:
        sents.append(BC.S(f"환자 {pid}, 기준일 {g.as_of}", [], "meta"))
        if not items:
            sents.append(BC.S("추천할 시험 없음 (eligible·potential 없음)", [], "meta"))
        for n, it in enumerate(items, 1):
            t = trials.get(it["trial_id"], {})
            detail = BC.trial_section(g, it, t)
            sents.append(detail[0])                                        # heading
            sents += [{k: v for k, v in s.items() if k != "facts"} for s in by_T[f"T{n}"]]
            sents.append(BC.S("세부 판정", [f"trial:{it['trial_id']}"], "heading"))
            sents += detail[2:] if len(detail) > 2 else []                 # skip template label line (summary has it)
        for tid in r["dropped_stale_trials"]:
            sents.append(BC.S(f"{tid}: " + FIXED["rule:dropped_stale"], [f"trial:{tid}", "rule:dropped_stale"]))
        sents += BC.near_miss_section(g, r.get("near_miss", []), trials)
    also = (sorted(r["dropped_stale_trials"]) + [x["trial_id"] for x in r.get("near_miss", [])]) if audience == "clinician" else []
    # out-of-glossary terms cited in LLM sentences: translated or left as the original (the code cannot tell which)
    llm_terms = sorted({t for T, ss in by_T.items() if T not in log["fallback"] for s_ in ss
                        for x in s_.get("facts", []) for f in packs.get(T, []) if f["id"] == x
                        for t in (f.get("detail") or {}).get("untranslated", [])}) if items and not llm.dry else []
    log["llm_translated_terms"] = llm_terms
    doc = {"llm_translated_terms": llm_terms, "also_mentioned": also, "patient_id": pid, "as_of": g.as_of, "audience": audience, "graph_file": f"{pid}.json",
           "ranking": [i["trial_id"] for i in items] if audience == "patient" else r["ranking"], "sentences": sents,
           "generator": {"agent6": VERSION, "model": None if llm.dry else llm.model, "prompt": PROMPT_VERSION[audience],
                         "dry_run": llm.dry}, "glossary": GL.usage(sents)}
    return doc, log


def write(doc, out):
    base = os.path.join(out, f"{doc['patient_id']}.{doc['audience']}")
    json.dump(doc, open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if doc["audience"] == "patient":
        md = "\n\n".join(s["text"] for s in doc["sentences"])
    else:
        md = "\n".join(("## " if s["kind"] == "heading" else "") + s["text"] for s in doc["sentences"])
    open(base + ".md", "w", encoding="utf-8").write(md + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ranking", required=True)
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--audience", choices=["patient", "clinician", "both"], default="both")
    ap.add_argument("--model", default=os.environ.get("AGENT6_MODEL", DEFAULT_MODEL))
    ap.add_argument("--top", type=int, default=5, help="trials in the patient briefing")
    ap.add_argument("--patient", action="append")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--cache", help="default: <out>/../.llm_cache")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--evidence", nargs="*", default=[], help="Agent 2 evidence jsonl (cancer-diagnosis check)")
    a = ap.parse_args(argv)
    KI.load_evidence(a.evidence, a.graphs)
    load_dotenv()
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    os.makedirs(a.out, exist_ok=True)
    llm = LLM(a.model, a.cache or os.path.join(os.path.dirname(os.path.abspath(a.out)), ".llm_cache"), a.dry_run)
    jobs = []
    for r in read_jsonl(a.ranking):
        if a.patient and r["patient_id"] not in a.patient:
            continue
        path = next((os.path.join(d, f"{r['patient_id']}.json") for d in a.graphs
                     if os.path.exists(os.path.join(d, f"{r['patient_id']}.json"))), None)
        if path:
            for aud in (["patient", "clinician"] if a.audience == "both" else [a.audience]):
                jobs.append((r, path, aud))

    def job(x):
        r, path, aud = x
        g = Graph.load(path)
        doc, log = build(r["patient_id"], r, g, trials, aud, llm, a.top)
        doc["evidence"] = KI.EVIDENCE_INFO
        write(doc, a.out)
        return log

    with ThreadPoolExecutor(max(1, a.workers)) as ex:
        logs = list(ex.map(job, jobs))
    with open(os.path.join(a.out, "llm_log.jsonl"), "w", encoding="utf-8") as f:
        for l in logs:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    fb = sum(len(l["fallback"]) for l in logs)
    print(f"{len(logs)} briefings -> {a.out} | model {'dry-run' if a.dry_run else a.model} | "
          f"retried {sum(l['tries'] > 1 for l in logs)}, trial sections on template fallback {fb} | usage {dict(llm.usage)}")


if __name__ == "__main__":
    main()
