# Agent 3 — Eligibility Reasoner

> **backend 파이프라인 진입점 (`run.py`, 레포 루트에서 dev 한 줄):**
> `python3 -m agents.agent3_judge.run --input patients=data/dev/input/patients.jsonl --input pairs=data/dev/input/pairs.jsonl --input criteria=data/dev/reference/criteria.jsonl --input evidence=data/dev/evidence/evidence_dev_haiku_v14_12.jsonl --out runs/a3   # --llm replay, API 호출 0`
> 전체는 `python3 -m pipeline.run_pipeline` (REPRODUCE.md). 아래는 받은 패키지의 원래 README입니다.

환자-임상시험 쌍마다 기준 하나하나를 **PASS / FAIL / UNKNOWN / CONFLICT**로 판정하고, 판정마다 Agent 2의 근거 ID를 붙이고, 공통 형식 6.1 규칙으로 시험 판정(eligible / potential / ineligible)을 집계한 뒤, Agent 4~6과 웹 화면이 함께 쓰는 **Evidence Graph**를 남깁니다 (예성 페이지 기준 설계).

- 입력: ② 환자 기록, ⓪ 시험, ① 기준, ③ 근거(Agent 2 v13.7)
- 출력: `agent3_out.jsonl`(④ Gold와 같은 어휘), `graph/{patient_id}.json`, `run_meta.json`
- 버전: 코드 **`a3-0.3.1`**, 프롬프트 `p07` + `claude-sonnet-5-5` (2026-10-31, `docs/a031_notes.md`, `FREEZE_a3-0.3.1.json`). 이전 고정판 `a3-0.3.0`(2026-10-25, `docs/v3_report.md`)의 test 결과가 마지막 순수 test 점수. v2는 `a3-0.2.0` + `p06` (2026-10-23, `docs/v2_notes.md`).
- 데이터: `for_agent3_v10`, 근거 dev **v14.12** (Agent 2 `agent2_v14_13.zip`의 `agent3_kit/`), test v14.9(고정), TREC·TrialGPT v14.7

> **a3-0.3.1에서 바뀐 것 (2026-10-31, `docs/a031_notes.md`)**
> - 측정일: 새 검사·영상·병리 보고서에 같은 값이 다시 나오면 새 측정 (5차 회의 6.3 보완) + 검사 30일 기본 창(병리 제외)
> - 같은 개념의 최신 값이 단어("not detected")면 오래된 숫자로 판정하지 않음, 나이·성별은 등록 문서 우선(검사 줄 무시)
> - LLM 답이 없는 기준(`pc:llm_missing`)이 있으면 시험은 eligible이 아니라 potential (`NOT_JUDGED`), 과거 진단·시술 action → `med_history_check`
> - API 키는 **`.env`** 에서: `cp .env.example .env` 후 `ANTHROPIC_API_KEY=` 뒤에 키를 적고 `bash scripts/run_dev.sh`. 셸 export가 있으면 그것이 우선
> - **dev 실행 (근거 v14.12, 2026-11-01)**: 기본 기준 일치 83.9%·반대 방향 2·시험 판정 87.0%, 변형 82.8%·반대 방향 **0**·시험 판정 89.0% (`runs/dev_a031_v10_kit1412_p07/`, `runs/dev_variants_a031_v10_kit1412_p07/`, 비교는 `docs/a031_notes.md`)
> - 실행 중 고친 것: API 시간 초과 재시도(멈추지 않음), 접두어 없는 근거 ID("EV047") 복원

> **v3에서 바뀐 것 (2026-10-25, `docs/v3_notes.md`)**
> - **Agent 3은 자기 판정을 검증하지 않음**: 후검사 격하(근거 없는 확정·가족력·계획·의심·판단 용어·모호 노트·창 밖 수치) 제거 → Agent 4 검사 1~4로 책임 이전 (`handoff_agent4/`). 남은 것은 어휘 정리 + 팀 정책 스위치만
> - 데이터 `for_agent3_v7`(정답 dev_v7) + Agent 2 키트 v14.7; ①-b dev 행정 5행 `administrative:false`(안건 3)
> - `--blanket on` 기본(A1) + A1 범위 규칙(`pc:blanket_out_of_scope`: 급성 사건·시술·삼출액 등은 일괄 부정으로 PASS하지 않음)
> - 프롬프트는 **p07 유지**. p08~p10은 시도 후 미채택(반대 방향 오류, `docs/v3_report.md` 3장); `AGENT3_PROMPT=p06|p08|p09|p10`으로 재현만 가능
> - `--salt`(재현성 재실행용 캐시 키). `export/`의 Batches 요청 파일은 p08용이라 참고만
> - 3번 "후검사(코드)" 단계는 v3부터 격하 없음 (아래 처리 흐름 설명은 v2 기준) v1은 `a3-0.1.0` + `p04` + `claude-sonnet-5-5` (2026-10-08, 결과는 `runs_v1/`)

> **v2에서 바뀐 것 (2026-10-23, `docs/v2_notes.md`)**
> - 데이터: `for_agent3_v5`(①-b dev v2 확정본, dev 정답 dev_v6, 개념 사전 138개) + Agent 2 키트 v14.6(dev 근거 v14.3, TREC·TrialGPT 근거 v14.6) + `eval_tools_v1`
> - `agent3/structured.py`: ①-b 수치·범주 기준 코드 판정 (단위 환산 `alt_units`, x ULN = 값/`ref_high`, `time_window` → EXPIRED, 측정일 = 값이 처음 나온 날). dev 정답과 62/63 일치, 반대 방향 0
> - `logic_group`(dev v2 의미): OR 묶음에서 하나라도 PASS면 나머지도 PASS, parent 줄 = 자기 조건 AND 자식 결과
> - `complex` 줄·값 없음·x ULN 참고 범위 없음·측정 조건("fasting")은 코드가 확정하지 않고 LLM에 계산 결과를 힌트로 넘김 (프롬프트 `CODE CHECK` 줄)
> - LLM 캐시 키에 프롬프트 내용 해시 포함 (v1은 근거 파일을 바꿔도 옛 답을 재사용하는 버그)
> - `--split trec|trialgpt`로 외부 검증 세트 실행, `eval/to_gold_draft.py`로 팀 채점 스크립트 형식 변환
> - 채점기에 D2 "정답 eligible 재현율" 추가

> **다시 시작할 때 (1단계 마무리 메모, 2026-10-08)**
> - v1 결과: `runs/dev_sonnet55_p04/` (dev 54쌍, 기준 일치 81.5%, 반대 방향 오류 3건 0.3%, 시험 판정 일치 83.3%). 답은 `runs/llm_cache/`에 있어 `--llm replay`로 비용 없이 재현됩니다.
> - 남은 반대 방향 오류 3건은 정답 확인이 필요한 사례입니다(`docs/v1_review.md`). 합성 담당에게 전달하세요.
> - 다음에 할 일: 팀 결정(일괄 부정·목록 추론·행정 항목 행동) 반영 → TrialGPT·TREC 검증 → ①-b 수치 판정 → Agent 4·5·6 연결 (`docs/NEXT_STEPS.md`).
> - 노션과 대화에 노출된 API 키는 폐기하고 새 키를 환경 변수로만 쓰세요.

## 빠른 시작

Python 3.9 이상, 외부 패키지 없음.

```bash
# 1) LLM 없이 (코드 규칙만): 기준선
python3 -m agent3.run --split dev --llm none
python3 eval/score_dev.py runs/dev_none_haiku/agent3_out.jsonl

# 2) Claude로 실제 판정 (키는 .env 또는 환경 변수로만)
cp .env.example .env                    # a3-0.3.1: .env에 ANTHROPIC_API_KEY=새 키 (노션에 적힌 키는 폐기)
python3 -m agent3.run --split dev --llm anthropic --model claude-sonnet-5-5 --out runs/dev_sonnet55_p04 --workers 8
python3 eval/score_dev.py runs/dev_sonnet55_p04/agent3_out.jsonl

# 3) 같은 답으로 다시 채점 (코드·후검사만 바꿨을 때, API 호출 없음)
python3 -m agent3.run --split dev --llm replay --model claude-sonnet-5-5 --out runs/dev_sonnet55_p04_replay

# 테스트
python3 -m unittest discover -s tests
```

다른 방식으로 모델을 부를 때:

| `--llm` | 쓰임 |
| --- | --- |
| `anthropic` | Claude Messages API. 환자 근거 블록에 프롬프트 캐시를 걸어 같은 환자의 두 번째 시험부터 재사용 |
| `openai` | OpenAI 호환 엔드포인트 (vLLM의 gpt-oss-120b 등). `OPENAI_BASE_URL`, `OPENAI_API_KEY` |
| `export` | API를 부르지 않고 요청을 `<cache>/export_requests.jsonl`(Message Batches 형식)로 저장. 결과 파일을 `python3 -m agent3.ingest --results 결과.jsonl`로 넣은 뒤 `--llm replay` |
| `replay` | 캐시에 있는 답만 사용. 없으면 실패 |
| `mock` | 모든 LLM 기준을 UNKNOWN으로. 파이프라인 점검용 |

모든 LLM 답은 `runs/llm_cache/`에 모델·프롬프트 버전·쌍·기준 ID로 저장되어, 같은 설정으로 다시 돌리면 비용이 들지 않습니다. 프롬프트를 고치면 `agent3/prompt.py`의 `PROMPT_VERSION`을 올리세요(캐시 키가 바뀜).

## 처리 흐름

```
기준 1개 ─▶ 1. 코드 판정 ─(못 정하면)─▶ 2. LLM 판정 ─▶ 3. 후검사(코드) ─▶ 4. 6.1 집계 ─▶ 5. Evidence Graph
            나이·성별·불가능 조건·동의류       시험 단위로 한 번에           판정을 더 조심스럽게만 바꿈
```

1. **코드 판정** (`agent3/rules.py`): 순수 나이 기준(생년월일로 as_of 기준 정확한 나이), 순수 성별 기준, 성별상 불가능한 조건(남성의 임신 제외 기준 등 → PASS/VALID), 동의·순응·의지 같은 행정 항목(→ UNKNOWN/MISSING). dev 정답 기준 82개를 이 단계에서 정하며 정답과 82/82 일치.
2. **LLM 판정** (`agent3/prompt.py`): 환자 근거 전체(줄마다 근거 ID, 날짜, as_of 기준 경과일, 확실성, 가족력·계획 표시)와 시험 기준 목록을 넣고, 남은 기준을 JSON으로 판정. 규칙은 공통 형식 6.3과 Agent 3 메모 2장을 그대로 옮김. 기준이 30개를 넘으면 나눠 부름.
3. **후검사** (`agent3/postcheck.py`): 모두 PASS/FAIL을 UNKNOWN 쪽으로만 바꾸므로 새 반대 방향 오류를 만들지 않음.
   - 근거 ID가 없거나 다른 환자 것이면 → UNKNOWN/MISSING (근거 없는 확정 판정 차단)
   - 가족력만으로 본인 기준 판정, 계획·거부 근거만으로 판정, 의심 진단만으로 진단 인정 → UNKNOWN/UNSUPPORTED
   - 판단 표현("clinically significant" 등) FAIL인데 정도가 기록되지 않음 → UNKNOWN/UNSUPPORTED + clinician_confirmation
   - 기준의 "within N days"보다 오래된 수치만 인용 → UNKNOWN/EXPIRED
   - 상태·이유·행동 어휘 정리 (PASS→VALID/none 등)
   - 팀 미결 규칙 스위치: `--list-inference strict|allow`, `--blanket off|on` (기본은 현재 dev 정답과 같은 strict/off)
4. **집계** (`agent3/aggregate.py`): 공통 형식 6.1 그대로. 시험의 min/max age·sex 범위 밖이면 ineligible.
5. **그래프** (`agent3/graph.py`): trial → criterion → concept → evidence → source, calculation, decision(상태·이유·행동·회차). Agent 4는 `verification` 노드를 붙이고, 재판정은 회차를 올려 새 decision 노드를 추가함(이력 보존).

## 출력 한 줄 (`agent3_out.jsonl`)

```json
{"patient_id": "SYN-0016", "trial_id": "NCT06935370", "as_of": "2026-10-01",
 "trial_label": "ineligible", "label_why": ["FAIL NCT06935370-E01", "FAIL NCT06935370-E02"], "cohort_assignment": null,
 "counts": {"PASS": 5, "FAIL": 2, "UNKNOWN": 7, "CONFLICT": 0},
 "criteria": [{"criterion_id": "NCT06935370-E02", "applicable": true, "status": "FAIL", "reason": "VIOLATED",
   "evidence_ids": ["SYN-0016-EV085"], "action": "none", "judged_by": "llm", "rule_tags": ["drug_class"],
   "derived_from": null, "missing_fact": null, "note": "Spironolactone is also a potassium-sparing diuretic and is currently taken."}],
 "not_applicable": [], "agent3_version": "a3-0.1.0", "prompt_version": "p02", "model": "dryrun-subagent"}
```

- `not_applicable`: 환자가 속하지 않는 코호트 기준. 집계와 채점에서 빠짐
- `rule_tags`: `age_rule`, `impossible`, `admin`, `list_inference`, `blanket_negation`, 후검사 흔적 `pc:*`, Verifier용 표시 `flag:possible_conflict`
- `missing_fact`: UNKNOWN·CONFLICT일 때 결정에 필요한 사실 한 줄 (Agent 5 질문 재료)

## 피드백 루프 (Agent 4·5와 연결)

```bash
# Agent 4(Verifier)가 되돌린 기준만 한 번 더 판정 (플래그 내용이 프롬프트에 표시됨)
python3 -m agent3.run --split dev --llm anthropic --out runs/X --prev runs/X/agent3_out.jsonl --rejudge flags.jsonl
#   flags.jsonl 한 줄: {"patient_id", "trial_id", "criterion_id", "issue", "detail"}

# Agent 2가 새 정보를 반영해 근거를 갱신했을 때 (changes.jsonl, 공통 형식 5.2)
python3 -m agent3.run --split dev --llm anthropic --evidence 새근거.jsonl --out runs/X --prev runs/X/agent3_out.jsonl --changes changes.jsonl
```

바뀌지 않은 기준은 이전 결과를 그대로 쓰고, 그래프에는 바뀐 기준만 다음 회차 decision으로 추가됩니다.

## 현재 결과

### v2 (dev, 2026-10-23, 정답 dev_v6, 같은 채점기로 v1 다시 채점)

| 실행 | 기준 일치 (엄격) | 반대 방향 오류 | 확정 정답을 UNKNOWN으로 | 정답 UNKNOWN을 확정 | 시험 판정 일치 | eligible 재현율 (D2) |
| --- | --- | --- | --- | --- | --- | --- |
| v1 코드만 (근거 v13.7) | 53.5% | 0 | 492 / 535 | 0 | 29.6% | 0 / 5 |
| v1 Sonnet 5.5 + p04 (근거 v13.7) | 82.5% | 0 | 114 | 27 | 83.3% | 1 / 5 |
| v2 코드만 (①-b, 근거 v14.3) | 59.1% | 0 | 432 / 535 | 0 | 40.7% | 0 / 5 |
| v2 Sonnet 5.5 + p05 | 81.2% | 1 | 132 | 36 | 88.9% | 3 / 5 |
| **v2 Sonnet 5.5 + p06 (엄격 정책)** | **83.0%** | **0** | 129 | 29 | **87.0%** | **3 / 5** |
| v2 p06 + 관대 정책 (`--blanket on --list-inference allow`, replay) | 78.1% (관대 채점 85.7%) | 1 | 80 | 62 | 87.0% | 3 / 5 |

- 근거 귀속(인용한 근거가 정답 근거와 겹침) v1 74.8% → v2 p06 81.6%. 근거 없는 확정 판정 0.
- v2 코드 판정(①-b 수치·범주)은 dev 정답과 62/63 일치. 남은 1건은 `docs/v2_notes.md`의 정답 확인 요청.
- p05 → p06: 정상 소견에서 "질환 없음"을 추론한 PASS(ECMO 아님, 패혈증 없음 등 36건)에 `normal_finding_inference` 태그를 달게 하고, 엄격 정책에서는 UNKNOWN으로 내림 (팀 결정 A2).
- 관대 정책의 반대 방향 오류 1건은 목록 추론 PASS(허용 치료 목록에만 있음)인데 정답은 FAIL — A2를 엄격으로 둔 근거.
- dev 1회 실행: 호출 61회, 입력 16만 + 캐시 쓰기 43만 + 캐시 읽기 94만, 출력 24만 토큰.

### 외부 검증 (p07 = p06 + 동의 진술 규칙, 2026-10-23)

| 검증 | 합격 기준 | v2 | 정답 생성기 기준선 |
| --- | --- | --- | --- |
| TrialGPT 기준 단위 1,014개 | 반대 방향 오류 ≤ 1% | **0.39% (4건)** | 0.5% |
| TrialGPT "기록에 없는 제외 = not excluded" 정확도 (참고) | 기준선보다 높게 | 0.746 (선정 0.795, 제외 0.719) | 0.757 (0.79, 0.74) |
| TREC 시험 단위 100쌍 | "TREC 제외인데 eligible" ≤ 5% | **4% (2 / 50)** | 6% / 4% |
| TREC 확정 판정만 정확도 / κ (참고) | | 0.788 / 0.435 (potential 48쌍) | 0.754 / 0.433 (39쌍) |

- TrialGPT 결과 `runs/trialgpt_sonnet55_p07/trialgpt_compare.json`, TREC `runs/trec_sonnet55_p07/trec_compare.json`, 불일치 `trec_disagreements.csv`.
- TrialGPT의 "included → not enough information" 41건은 정답 생성기와 같은 수. 선정 기준에서 기록에 있는 사실을 놓치는 문제는 남아 있음.

### v1 (dev, 2026-10-08, 정답 dev_v4)

| 실행 | 기준 일치 | 상태+이유 | 반대 방향 오류 | 확정 정답을 UNKNOWN으로 | 시험 판정 일치 | UNKNOWN 행동 일치 |
| --- | --- | --- | --- | --- | --- | --- |
| 코드만 (`--llm none`) | 52.5% | 48.2% | 0 | 502 / 545 | 29.6% | 37.7% |
| Sonnet 5.5 + p02 | 81.4% | 72.8% | 6 (0.6%) | 120 | 85.2% | 53.9% |
| Sonnet 5.5 + p03 | 79.7% | 75.8% | 6 (0.6%) | 125 | 81.5% | 57.0% |
| **Sonnet 5.5 + p04 (v1)** | **81.5%** | **78.1%** | **3 (0.3%)** | 123 | 83.3% | 56.0% |

- 54쌍, 정답 기준 1,057개. 근거 없는 확정 판정은 모든 실행에서 0건, 시험 단위의 eligible/potential → ineligible과 ineligible → eligible도 0건.
- v1 dev 1회 실행: LLM 호출 63회, 입력 약 13만 + 캐시 쓰기 42만 + 캐시 읽기 97만 토큰, 출력 약 23만 토큰, 약 4분(동시 8명).
- p02 → p04 변경: 제외 기준에서 기록에 관련 신호가 전혀 없으면 UNSUPPORTED가 아니라 MISSING(6.1에서 시험을 막지 않음), 자기 설명과 판정이 어긋나지 않게 하는 규칙. p03의 "급성 사건 당시 값으로 판정" 규칙은 정답이 시험 안에서도 기준마다 달라(입원 시 값 vs 현재 값) 뺐습니다.
- 정답이 eligible인 5쌍 중 4쌍을 potential로 냅니다. 대부분 정답은 PASS나 MISSING인데 모델이 UNSUPPORTED로 둔 기준 1~2개 때문입니다(2단계 개선 과제).
- Sonnet 5.5는 `temperature`를 받지 않아 같은 프롬프트라도 실행마다 조금 다를 수 있습니다. 비교할 때는 같은 실행을 2회 이상 보거나 `--llm replay`로 고정된 답을 쓰세요.
- `runs/dryrun_*`는 API 키가 생기기 전 하위 에이전트로 프롬프트를 점검한 기록입니다.

## 폴더

```
agent3/        rules.py 코드 판정 · prompt.py 프롬프트 · llm.py 모델 호출·캐시 · postcheck.py 후검사
               aggregate.py 6.1 · graph.py Evidence Graph · run.py 실행 · ingest.py 외부 답 넣기
eval/          score_dev.py dev 채점 (엄격·관대·반대 방향·근거 귀속·시험 혼동)
tests/         단위·종단 테스트 17개
data/dev       for_agent3_v2의 dev (입력·시험·기준·정답·점검표)
data/test      test 환자 입력만 (정답 없음, 개발 중 열지 않기)
agent3_kit/    Agent 2 근거 v13.7 (haiku, rules)
agent2/        evidence_index.py, 임시 개념 목록
docs/          공통 형식 v0.5, Agent 2 안내, Agent 3 메모, 다음 단계
runs/          실행 결과
```

남은 작업 순서는 `docs/NEXT_STEPS.md`에 있습니다.
