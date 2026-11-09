#!/usr/bin/env python3
"""①-b 구조화 (v0.5): concept / term / operator / value / unit / logic_group / answerable_by 를 Claude API로 채운다.

개념 키 방식 (Agent 2와 동일):
  - 검사·활력·점수·인구 항목  → concepts.json의 구체 키 (anc, egfr, hba1c, ecog, age ...)
  - 질환·약물·시술·증상·바이오마커 → 바구니 키 + term:  diagnosis / medication / procedure / symptom_finding /
                                      biomarker / metastasis / allergy  +  "term": ["acute pancreatitis"]
  - concept 는 반드시 concepts.json 안의 키. 목록 밖 키를 내면 concept_proposed 로 따로 모으고 concept 는 null.
  - time_window 는 fill_time_window.py 가 채운 값을 그대로 둔다.
  - administrative == true 인 행은 LLM을 부르지 않고 concept="administrative" 로 둔다.

준비:
  pip3 install anthropic           export ANTHROPIC_API_KEY=...   (키는 환경변수로만)

사용법:
  python3 fill_time_window.py --criteria <ref>/dev/reference/criteria.jsonl --out out/dev      # 먼저
  python3 fill_structure.py --out out/dev --dry-run
  python3 fill_structure.py --out out/dev --limit 60
  python3 fill_structure.py --out out/dev --candidates <ref>/dev/gold/trial_candidates.jsonl    # 라벨 시험 먼저, 이어서 전체
  python3 fill_structure.py --out out/dev --labeled-only --candidates ...                       # 라벨 시험만

입력:  out/<name>/criteria.jsonl (fill_time_window 결과), concepts.json
출력:  out/<name>/criteria.jsonl          ①-b 채워서 덮어씀 (criterion_id·original_text 불변)
       out/<name>/structure_cache.jsonl   호출 결과 캐시 (중단 후 이어서)
       out/<name>/structure_review.csv    검수용 표
       out/<name>/concepts_unlisted.json  목록 밖 키 제안 빈도 → concepts.json 에 추가할지 판단
"""
import argparse, csv, json, os, re, sys, time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BATCH = 15
OPERATORS = [">=", "<=", ">", "<", "==", "between", "in", "exists", "not_exists"]
ANSWERABLE = ["patient", "lab", "med_record", "clinician"]
BUCKETS = ["diagnosis", "medication", "procedure", "symptom_finding", "biomarker", "metastasis", "allergy",
           "treatment_plan", "tumor_marker", "cancer_stage", "lab_other", "social_history"]

SYSTEM = """You convert clinical-trial eligibility criteria into a fixed JSON structure for a patient-matching system.
Return ONLY a JSON array, one object per input criterion, same order, same "criterion_id". No prose.

The patient side was extracted with the SAME dictionary (ALLOWED list below). Your output is matched against it, so:
  - "concept" MUST be a key from ALLOWED. Never invent a key.
  - Measurable quantities (labs, vitals, scores, age, performance status) use their specific key: "anc", "egfr", "hba1c",
    "ecog", "age", "lvef", "systolic_bp", "child_pugh", "nyha_class" ...
  - Diseases, drugs, drug classes, procedures, symptoms and genetic/tumor markers use a BUCKET key plus "term":
      diagnosis       (any disease / condition / history of disease; also "active infection", "autoimmune disease")
      medication      (drug, drug class, vaccine, therapy such as chemotherapy / immunotherapy / radiotherapy)
      procedure       (surgery, transplant, dialysis, biopsy, radiotherapy as a procedure)
      symptom_finding (symptom or exam/imaging finding)
      biomarker       (EGFR/KRAS/BRAF mutation, HER2, MSI-H, BRCA, ALK, MGMT, PD-L1 when no % given)
      metastasis      (any metastasis; term says the site: ["brain"], ["CNS"], ["bone"])
      allergy         (hypersensitivity to a drug or class)
    "term" is a list of 1-4 short noun phrases naming the entity as written ("acute pancreatitis", "anti-PD-1 therapy",
    "live vaccine"). Include the obvious synonym only if the text gives it. Never put a negation, time word or number in term.
  - If no key fits at all, set "concept": null and put your best snake_case suggestion in "concept_proposed".

Each object:
{
 "criterion_id": "...",
 "concept": ALLOWED key or null,
 "term": list of strings (required for bucket keys, null for specific keys),
 "concept_proposed": snake_case string or null (only when concept is null),
 "operator": one of [">=", "<=", ">", "<", "==", "between", "in", "exists", "not_exists"] or null.
     Numeric thresholds -> comparison. "History of X" / "has X" / "receiving X" -> "exists". "No prior X" / "absence of X" ->
     "not_exists". For an EXCLUSION criterion describe the condition that triggers exclusion ("Pregnant" -> pregnancy/exists);
     the matcher knows the type and flips the result.
     When the text names a condition AND defines it with a number, encode the number: "CKD defined by eGFR < 20" ->
     egfr / < / 20. "Cirrhosis (Child-Pugh > 6 points)" -> child_pugh / > / 6. Never collapse such a criterion to "exists".
     If the threshold is a CHANGE from an earlier value ("decrease", "reduction", "from baseline"), keep the quantity key,
     add "change": true, and set the operator/value on the change amount.
 "value": number, [low, high] for "between", list of category labels for "in", or null. Only literals that appear in the
     text; never a negation or comparison phrase. For "exists"/"not_exists" value is null (the entity is in "term").
 "unit": unit as written, ASCII ("10^9/L", "mg/dL", "kg/m^2", "xULN", "%", "years"); null for scores and booleans.
 "logic_group": null, or {"group_id": "<criterion_id>-G1", "relation": "AND"|"OR"} when the criterion is an explicit list
     of alternatives ("A, or B, or C") or conjuncts that must be tracked together.
 "answerable_by": non-empty list from ["patient","lab","med_record","clinician"]. Labs/vitals -> ["lab"]; diagnoses,
     surgeries, prior treatments -> ["med_record"] plus "patient" when a patient could reliably answer (prior immunotherapy,
     smoking, pregnancy); investigator-judgment wording -> ["clinician"].
 "complex": true if the criterion bundles several independent tests. Then encode the MOST OBJECTIVELY TESTABLE one
     (numeric > graded scale > named diagnosis > judgement; ties -> the one written first, except an arm that merely exempts
     a subgroup: "Males, or nonpregnant females" -> pregnancy/not_exists) and set logic_group so the rest can be recovered.
}
Rules: never guess a threshold or label not in the text. Do not add other fields."""


SPLIT_SYSTEM = """You split clinical-trial eligibility text into individual criteria.
Return ONLY a JSON array, one object per criterion, in the original order. No prose.
Each object: {"type": "inclusion" | "exclusion" | "unknown", "text": "..."}
  - "type" comes from the nearest preceding Inclusion/Exclusion header; "unknown" if there is no header.
  - Split items joined by commas, semicolons, dashes or bullets when each is a separate requirement
    ("Active Graves Disease, Currently pregnant, Taking Steroids" -> three objects).
  - Copy each "text" verbatim from the input. No rewording, no added words. Drop the headers themselves
    ("Inclusion Criteria:") and stray bullet characters."""


def _norm_text(s):
    return re.sub(r"\s+", " ", re.sub(r"[\\*•]", "", s or "")).strip(" -;,.").lower()


def validate_split(arr, text):
    """LLM 분할 결과 검사: type 확인, 원문에 그대로 있는 조각만 남긴다. (남긴 것, 버린 수)"""
    src, kept, dropped = _norm_text(text), [], 0
    for o in arr if isinstance(arr, list) else []:
        t = o.get("text") if isinstance(o, dict) else None
        ty = o.get("type") if isinstance(o, dict) else None
        if not isinstance(t, str) or not _norm_text(t) or _norm_text(t) not in src:
            dropped += 1; continue
        kept.append({"type": ty if ty in ("inclusion", "exclusion") else "unknown", "text": t.strip(" -")})
    return kept, dropped


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def build_user_msg(batch, allowed):
    lines = ["ALLOWED concept keys: " + ", ".join(allowed), "", "Criteria:"]
    for c in batch:
        tw = c.get("time_window")
        twtxt = f"  [time_window already set: max={tw.get('max_days_before')} min={tw.get('min_days_before')}]" if tw else ""
        lines.append(json.dumps({"criterion_id": c["criterion_id"], "type": c["type"], "cohort": c.get("cohort"),
                                 "text": c["original_text"]}, ensure_ascii=False) + twtxt)
    return "\n".join(lines)


def parse_json_array(text):
    m = re.search(r"\[.*\]", text.strip(), re.S)
    if not m:
        raise ValueError("no JSON array in response")
    return json.loads(m.group(0))


def cause_chain(e):
    parts, cur, depth = [], e, 0
    while cur is not None and depth < 8:
        parts.append(f"{type(cur).__module__}.{type(cur).__name__}: {str(cur)[:300]}")
        cur, depth = cur.__cause__, depth + 1
    return "\n    ← ".join(parts)


def fatal(client, e):
    import anthropic
    if isinstance(e, anthropic.AuthenticationError):
        hint = "→ ANTHROPIC_API_KEY가 거부됐습니다."
    elif isinstance(e, anthropic.NotFoundError):
        hint = "→ 모델명 확인: --list-models"
    else:
        hint = ("→ 요청을 보내지 못했습니다. 밑단 예외가 TypeError: process() ... 이면\n"
                "   python3 -m pip install -U 'brotli>=1.1.0'")
    sys.exit(f"\n{type(e).__name__} (base_url={client.base_url})\n  {cause_chain(e)}\n{hint}")


def call_claude(client, model, user_msg, retries=4, system=None):
    import anthropic
    FATAL = (anthropic.APIConnectionError, anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError)
    for i in range(retries):
        try:
            r = client.messages.create(model=model, max_tokens=6000, system=system or SYSTEM,
                                       messages=[{"role": "user", "content": user_msg}])
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
        except anthropic.APITimeoutError as e:
            transient = e
        except FATAL as e:
            fatal(client, e)
        except (TypeError, AttributeError, ImportError) as e:
            import traceback; traceback.print_exc()
            sys.exit(f"\nSDK 호출 오류: {e}\n→ python3 -m pip install -U anthropic")
        except Exception as e:
            transient = e
        wait = 2 ** i * 3
        print(f"  API 오류({transient.__class__.__name__}: {str(transient)[:200]}), {wait}s 후 재시도", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError("API 호출 반복 실패")


def validate(o, text, allowed_set, keep_bucket=False):
    """keep_bucket=True: term 없는 바구니 키도 concept 를 남겨 둔다 (호출 쪽 verify 가 재시도)."""
    o["operator"] = o.get("operator") if o.get("operator") in OPERATORS else None
    ab = o.get("answerable_by") or []
    o["answerable_by"] = [a for a in ab if a in ANSWERABLE] or None
    c = o.get("concept")
    c = re.sub(r"[^a-z0-9_]", "_", c.strip().lower()) if isinstance(c, str) and c.strip() else None
    if c and c not in allowed_set:          # 목록 밖 키 → 제안으로 돌리고 concept 는 비움
        o["concept_proposed"] = o.get("concept_proposed") or c
        c = None
    cp = o.get("concept_proposed")
    cp = re.sub(r"[^a-z0-9_]", "_", cp.strip().lower()) if isinstance(cp, str) and cp.strip() and not c else None
    if cp in allowed_set:                   # 제안이 이미 사전 키면 제안이 아니다
        c, cp = cp, None
    o["concept"], o["concept_proposed"] = c, cp
    t = o.get("term")
    if isinstance(t, str):
        t = [t]
    o["term"] = [str(x).strip() for x in t if str(x).strip()][:4] if isinstance(t, list) and t else None
    if c in BUCKETS and not o["term"]:      # 바구니 키인데 term 이 없으면 쓸 수 없다 — 제안이 아니라 검증 문제
        o["concept_proposed"], o["verify_note"] = None, "term 없음"
        if not keep_bucket:
            o["concept"] = None
    lg = o.get("logic_group")
    if not (isinstance(lg, dict) and lg.get("relation") in ("AND", "OR")):
        o["logic_group"] = None
    if o["operator"] == "in" and isinstance(o.get("value"), list) and text:
        low = text.lower()
        if any(isinstance(v, str) and not all(w in low for w in re.findall(r"[a-z0-9]+", v.lower())) for v in o["value"]):
            o["operator"] = None
    if o["operator"] in (None, "exists", "not_exists"):
        o["value"], o["unit"] = None, None
    o["change"] = bool(o.get("change"))
    o["complex"] = bool(o.get("complex"))
    return o


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="fill_time_window.py 가 쓴 폴더 (예: out/dev)")
    ap.add_argument("--candidates", default="", help="trial_candidates.jsonl: 라벨 대상 시험을 먼저 처리")
    ap.add_argument("--labeled-only", action="store_true", help="라벨 대상 시험만 처리")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--pause", type=float, default=0.5)
    a = ap.parse_args()

    OUT = Path(a.out)
    crit_p = OUT / "criteria.jsonl"
    if not crit_p.exists():
        sys.exit(f"{crit_p} 가 없습니다. fill_time_window.py 를 먼저 실행하세요.")
    crit = load_jsonl(crit_p)
    concepts = json.load(open(HERE / "concepts.json", encoding="utf-8"))
    allowed = [x["key"] for x in concepts]
    allowed_set = set(allowed)
    print(f"concepts.json 키 {len(allowed)}개")

    labeled = set()
    if a.candidates:
        labeled = set(t for k in load_jsonl(a.candidates) for t in k.get("trial_ids", []))
    cache_p = OUT / "structure_cache.jsonl"
    cache = {o["criterion_id"]: o for o in load_jsonl(cache_p)} if cache_p.exists() else {}

    # 행정 항목은 LLM 없이 처리
    for c in crit:
        if c.get("administrative") and c["criterion_id"] not in cache:
            cache[c["criterion_id"]] = {"criterion_id": c["criterion_id"], "concept": "administrative", "term": None,
                                        "concept_proposed": None, "operator": None, "value": None, "unit": None,
                                        "logic_group": None, "answerable_by": ["patient"], "complex": False,
                                        "change": False, "model": "rule:administrative"}
    todo = [c for c in crit if c["criterion_id"] not in cache and (not a.labeled_only or c["trial_id"] in labeled)]
    todo.sort(key=lambda c: (0 if c["trial_id"] in labeled else 1))   # 라벨 시험 먼저
    if a.limit:
        todo = todo[:a.limit]
    print(f"전체 {len(crit)}줄 (라벨 시험 {sum(c['trial_id'] in labeled for c in crit)}줄), 캐시 {len(cache)}줄, "
          f"이번에 {len(todo)}줄 → {-(-len(todo)//BATCH)}회 호출")

    if a.dry_run:
        print("\n--- SYSTEM ---\n" + SYSTEM + "\n--- USER (첫 묶음) ---\n" + build_user_msg(todo[:BATCH], allowed))
        return
    if todo:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("ANTHROPIC_API_KEY 환경변수가 없습니다.")
        import anthropic
        client = anthropic.Anthropic(default_headers={"accept-encoding": "gzip, deflate"})
        try:
            available = [m.id for m in client.models.list(limit=100).data]
        except Exception as e:
            fatal(client, e)
        if a.list_models:
            print("\n".join(available)); return
        if a.model not in available:
            sys.exit(f"모델 '{a.model}' 사용 불가. 사용 가능: {', '.join(available)}")

        failed = []
        with open(cache_p, "a", encoding="utf-8") as cf:
            for i in range(0, len(todo), BATCH):
                batch = todo[i:i + BATCH]
                try:
                    arr = parse_json_array(call_claude(client, a.model, build_user_msg(batch, allowed)))
                except Exception as e:
                    failed.append(i // BATCH); print(f"  묶음 {i//BATCH} 실패: {e}", file=sys.stderr); continue
                byid = {o.get("criterion_id"): o for o in arr if isinstance(o, dict)}
                for c in batch:
                    o = byid.get(c["criterion_id"])
                    if not o:
                        continue
                    o = validate(o, c["original_text"], allowed_set)
                    o["model"] = a.model
                    cache[c["criterion_id"]] = o
                    cf.write(json.dumps(o, ensure_ascii=False) + "\n")
                cf.flush()
                print(f"  {min(i+BATCH, len(todo))}/{len(todo)}")
                time.sleep(a.pause)
        print(f"실패 묶음 {len(failed)}/{-(-len(todo)//BATCH)}" + (" — 같은 명령 재실행으로 재시도" if failed else ""))

    # merge back (criterion_id, original_text, time_window, administrative 등은 그대로)
    n, concept_counter, unlisted, rows = 0, Counter(), Counter(), []
    for c in crit:
        o = cache.get(c["criterion_id"])
        if not o:
            continue
        for k in ("concept", "term", "operator", "value", "unit", "logic_group", "answerable_by", "complex", "change"):
            c[k] = o.get(k)
        c["concept_proposed"] = o.get("concept_proposed")
        c["parse_status"] = "structured" if c["concept"] else "free_text"
        n += 1
        if c["concept"]:
            concept_counter[c["concept"]] += 1
        if c["concept_proposed"]:
            unlisted[c["concept_proposed"]] += 1
        rows.append([c["criterion_id"], c["type"], "A" if c.get("administrative") else "", c["parse_status"], c["concept"],
                     ";".join(c["term"] or []), c["concept_proposed"] or "", c["operator"],
                     json.dumps(c["value"], ensure_ascii=False) if c["value"] is not None else "", c["unit"],
                     ";".join(c["answerable_by"] or []), "Y" if c["complex"] else "", c["original_text"]])
    with open(crit_p, "w", encoding="utf-8") as f:
        for c in crit:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump({k: v for k, v in unlisted.most_common()}, open(OUT / "concepts_unlisted.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    with open(OUT / "structure_review.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["criterion_id", "type", "admin", "parse_status", "concept", "term", "concept_proposed", "operator",
                    "value", "unit", "answerable_by", "complex", "original_text"])
        w.writerows(rows)
    ns = sum(1 for c in crit if c.get("parse_status") == "structured")
    print(f"\n{n}줄 반영. structured {ns}/{len(crit)} ({ns/len(crit):.0%}), concept 키 {len(concept_counter)}종, "
          f"목록 밖 제안 {sum(unlisted.values())}줄/{len(unlisted)}종 → concepts_unlisted.json")
    print("상위 concept:", ", ".join(f"{k}({v})" for k, v in concept_counter.most_common(25)))


if __name__ == "__main__":
    main()
