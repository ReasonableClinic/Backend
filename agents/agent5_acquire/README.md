# Agent 5 — Information (MISSING / 기록 찾기 담당, 준상) `a5j-0.3.1`

> **backend 파이프라인 진입점 (`run.py`, 레포 루트에서 dev 한 줄):**
> `python3 -m agents.agent5_acquire.run --input judgments=runs/a4/agent3_out.jsonl --input patients=data/dev/input/patients.jsonl --input criteria=data/dev/reference/criteria.jsonl --input evidence=data/dev/evidence/evidence_dev_haiku_v14_12.jsonl --out runs/a5   # a5u + a5j 카드`
> 전체는 `python3 -m pipeline.run_pipeline` (REPRODUCE.md). 아래는 받은 패키지의 원래 README입니다.

## a5j-0.3.1 (11/08): QA 요청 반영 (답한 기준 다시 묻지 않기)

| QA 요청 | 반영 |
| --- | --- |
| 2-3 이미 답한 기준에 환자 카드를 새로 내지 말 것 | `lookup_run cards --answered answered.jsonl`. 답한 기준이 아직 UNKNOWN이면 환자 카드 대신 의료진 카드 1장: type `answered_review`, route `ask_clinician`, 제목 `[답 받음·의료진 확인 중] <기준>`, `answer_docs`에 답 문서 |
| 갱신 고리에서 쓰기 | `run_loop.py`가 3단계 뒤 `answered.jsonl`(환자, 시험, 기준, 카드, 답 문서)을 쓰고 7단계에 넘김. `--cards-only`: 끝난 실행 폴더에서 7단계만 다시(API 없음) |
| 결과 (SYN-0010) | 답 후 `[기록 찾기] Patient with untreated active tuberculosis` 환자 카드 → `[답 받음·의료진 확인 중]` 의료진 카드. 카드 수 21 → 21, 다른 카드 변화 없음. 0.3.0 결과는 `cards_after_a5j030/`, `LOOP_SUMMARY_a5j030.md`에 보관 |

- `--answered`를 주지 않으면 0.3.0과 결과가 같습니다 (dev 채점 영향 없음). 테스트 17개 통과.
- 판정이 MISSING으로 나오는 것 자체(QA 2-1)는 Agent 3 쪽입니다.

## a5j-0.3.0 (11/06): 웹 화면 요청 반영

| 요청 (웹 화면 데모 v1·제안, 11/05~06) | 반영 |
| --- | --- |
| 5번 / 5-1 담당 미정 MISSING (시험을 막지 않는 새 검사·의사 확인) | 본 파트가 맡음 (`scope: unowned`). 카드 종류는 Agent 3 action 그대로, **의료진용**(`audience: clinician`, `route: ask_clinician`) |
| 5-2 `card_id` 고정 | `<환자>:<종류>:L-<카드의 첫 기준 ID>` (예: `SYN-0010:lab_check:L-NCT05428488-E09`). 실행이 바뀌어도 같은 카드는 같은 ID |
| 5-4 행정 기준 질문 | 기준이 모두 `administrative`인 카드는 **연구기관 확인**(`audience: clinician`, `route: ask_site`, 제목 "[행정 확인]") |
| 재판정 범위 (a5j 5-③, 웹 요청 6) | `run_loop.py` 기본값을 `--scope card`로: **답한 카드의 기준만** Agent 3 `--rejudge`로 다시 판정 (`--scope changes`는 예전 방식) |
| 5-3 한국어 질문 문장 | 미반영 (방식 결정 필요) |

dev 기본 (Agent 4 이후):

| | 0.2.0 | 0.3.0 |
| --- | --- | --- |
| 카드 (환자 수) | 148 (15) | 175 (16) |
| 환자에게 가는 카드 / 의료진·연구기관 카드 | 148 / 0 | 120 / 55 |
| 환자 1명당 환자용 카드 | 9.9 | 7.5 |
| 정답 MISSING 기록 찾기·환자 질문 줄 중 카드 | 71.8% | 80.9% (새로 맡은 의사 확인 카드가 덮는 줄 포함) |
| 정답 MISSING 새 검사·의사 확인 줄 중 카드 (새로 맡은 구역) | - | 72.0% (131/182, 시험을 막는 줄은 a5u) |
| a5u 카드와 중복 | 0 | 0 |

- 0.3.0에서 "시험을 막는지" 계산을 a5u(`cards.py`)와 같게 맞춤 (이미 ineligible인 시험도 같은 방식). 맞추기 전에는 중복 12건이 생겼음.
- 답 형식 추가: 의사 확인 `{"card_id","criterion_id","decision","comment"}`, 새 검사 `{"card_id","date","result"}` (a5u와 같음).

운주의 `agent5_a5u-0.2.0`(EXPIRED·UNSUPPORTED 담당, 설명은 [README_a5u.md](README_a5u.md)) 위에 준상 담당 부분을 얹은 폴더입니다. 운주 파일(`agent5/cards.py`, `answers.py`, `data.py`, `run.py`)은 고치지 않았고, 새 파일만 추가했습니다.

| 새 파일 | 하는 일 |
| --- | --- |
| `agent5/lookup.py` | Agent 3 출력 → 기록 찾기·환자 질문 카드 |
| `agent5/lookup_answers.py` | 카드 답 → 새 기록 문서 (Agent 2 `update.py` 입력) |
| `agent5/lookup_run.py` | 실행 CLI (`cards`, `answer`) |
| `eval/score_lookup.py` | 정답 expected_action과 비교 |
| `tests/test_lookup.py` | 범위·경계·병합·답 변환 테스트 (운주 테스트 데이터 재사용) |
| `sample/SYN-0016/` | 운주 zip에서 꺼낸 SYN-0016 한 명분 (Agent 3 출력, 근거, 환자 기록) |

## 맡는 범위 (운주와 합의한 경계)

| Agent 3 판정 | Agent 3 action | 담당 |
| --- | --- | --- |
| UNKNOWN / MISSING | `med_record_check`, `med_history_check`, `lab_check`, `patient_question` | **준상 (여기)** |
| UNKNOWN / EXPIRED·UNSUPPORTED | 기록 찾기 3종 (운주의 `handoff_record_lookup.jsonl`과 같은 규칙으로 여기서 다시 계산) | **준상 (여기)** |
| UNKNOWN / MISSING, 시험을 막음 | `new_test`, `clinician_confirmation` | 운주 |
| UNKNOWN / MISSING, 시험을 안 막음 | `new_test`, `clinician_confirmation` | 담당 없음 (개수만 셈) |
| CONFLICT, UNKNOWN / EXPIRED·UNSUPPORTED (그 외) | | 운주 |

`tests/test_lookup.py`가 운주 카드와 겹치는 줄이 없는지, 넘겨받는 줄이 운주 handoff와 같은지 확인합니다.

## 카드

- 카드 종류 = Agent 3 action 그대로 (정답 `expected_action`과 바로 채점).
- 묶기: `lab_check`는 같은 개념(①-b `concept`)끼리, 나머지는 같은 질문(missing_fact)끼리 시험이 달라도 카드 하나.
- 우선순위: 시험의 마지막 걸림돌 → 걸린 시험 수. 시험을 막지 않는 **제외 기준** 줄도 남기되(`safety_check_of`, "예"면 그 시험이 ineligible로 바뀜) 맨 뒤로.
- `route` (4차 회의 데모 방식):
  - `ask_patient`: 환자 질문 카드
  - `agent2_reread`: 근거가 하나도 안 나온 문서(`unread_docs`)가 있으면 Agent 2에 먼저 넘김
  - `upload_request`: 더 읽을 문서가 없으면 기록 업로드 요청
- `card_id`는 `환자:종류:L번호`. 운주 카드(`환자:종류:번호`)와 겹치지 않습니다.

## 답 형식 (`answers_lookup.jsonl`)

```json
{"card_id": "SYN-0016:med_record_check:L02", "date": "2026-02-19", "doc_type": "discharge_summary", "text": "..."}
{"card_id": "SYN-0016:med_record_check:L05", "not_found": true, "comment": "..."}
{"card_id": "SYN-0016:patient_question:L06", "answer": "No."}
```

- `doc_type` 생략 시: `lab_check` → `lab_result`, 기록·과거력 → `clinic_note`. 환자 답 → `patient_interview` (운주와 같음).
- `as_of` 이후 날짜는 거부. 기존 마지막 문서보다 이른 날짜는 경고(문서 번호 순서 ≠ 날짜 순서 문제).
- `not_found`는 문서를 만들지 않고 `not_found.jsonl`에 남깁니다 → 다음에 환자 질문이나 의사 확인으로 넘길지 정해야 함.

## 실행

```bash
python -m unittest discover -s tests

# agent3_final 없이: SYN-0016 샘플 (criteria.jsonl이 없어서 기준 원문·개념은 비어 있음)
python -m agent5.lookup_run cards --agent3 sample/SYN-0016/agent3_out.jsonl --patients sample/SYN-0016/patients.jsonl --evidence sample/SYN-0016/evidence.jsonl --out runs/sample_lookup
python -m agent5.lookup_run answer --cards runs/sample_lookup/cards.jsonl --answers examples/answers_lookup_SYN-0016.jsonl --patients sample/SYN-0016/patients.jsonl --evidence sample/SYN-0016/evidence.jsonl --out runs/sample_lookup_answers

# agent3_final을 이 폴더 옆(../agent3_final)에 두면: dev 전체
python -m agent5.lookup_run cards --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl --split dev --out runs/dev_lookup
python -m agent5.lookup_run cards --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl --split dev --include-ineligible --out runs/dev_lookup_all
python eval/score_lookup.py runs/dev_lookup_all/cards.jsonl --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl
```

그다음 Agent 2 `update.py` → Agent 3 `--changes` 재판정은 [README_a5u.md](README_a5u.md) 3·4단계와 같습니다.

## 샘플 결과 (SYN-0016, ineligible 제외)

카드 6장: 기록 찾기 4, 과거력 확인 1, 환자 질문 1. 시험을 막는 카드 2장(NCT06979375-I02 진단일, I05 중앙판독 심초음파, 둘 다 운주 쪽에서 넘어온 UNSUPPORTED), 나머지 4장은 제외 기준 안전 확인. 이 환자는 모든 문서에서 근거가 나와서 `agent2_reread`는 0장, 기록 카드는 전부 `upload_request`.

## 갱신 고리 한 번에 돌리기 (`scripts/run_loop.py`, 데모 환자 SYN-0010)

카드 → 답 → Agent 2 부분 재추출 → Agent 3 부분 재판정 → Agent 4 재검증 → 카드 다시 만들기를 명령 하나로 돌립니다. 결과는 `runs/loop_<환자>_<llm>/LOOP_SUMMARY.md`.

```bash
# 1회만: ../agent3_a3-0.3.1/.env.example 을 .env 로 복사하고 ANTHROPIC_API_KEY= 뒤에 키 입력 (Agent 2도 이 파일을 읽음)
python -m pip install anthropic             # 1회만: Agent 2 Haiku 경로에 필요
python scripts/run_loop.py                  # Agent 2 Haiku 재추출 + Agent 3 API 재판정 (답한 카드 기준만, 데모용 결과)
python scripts/run_loop.py --scope changes  # 예전 방식: Agent 2 changes가 가리키는 기준 전부 재판정
python scripts/run_loop.py --llm replay     # 마지막 API 실행을 저장된 답으로 다시 (비용 없음)
python scripts/run_loop.py --a2 rules       # Agent 2를 API 없이 규칙으로 (연결 확인용)
```

- 필요한 폴더(노션 zip을 이 폴더 옆에 풀어 둔 상태): `../agent3_a3-0.3.1`, `../agent3_final`(data, agent3_kit), `../agent2_v14_15`, `../agent4_v1`
- Agent 2 재추출은 Haiku가 기본입니다. 근거 파일이 Haiku 계열이라 같은 계열로 이어야 하고(11/03 ID 계열 결정), 데모 장면의 답을 정확히 읽어야 하기 때문입니다 (Agent 2·6 담당 답변, 11/04).
- 참고: v14.13 규칙 경로는 "QuantiFERON … negative"에서 진단 TB = true 근거를 만들었지만, v14.15 규칙 경로는 만들지 않습니다(QuantiFERON = false 하나만).
- 답: `examples/answers_loop_SYN-0010.jsonl` (카드 `SYN-0010:lab_check:L01`, NCT05428488-E09 결핵 검사, 가상 답 "QuantiFERON 음성")
- Agent 3이 LLM 실패로 채운 줄(`pc:llm_missing`)은 카드를 만들지 않습니다 (실제 MISSING이 아님).

replay로 연결 확인 중 발견 (Agent 4 담당 전달):
- Agent 3 a3-0.3.1은 LLM 실패 시 NCT02714634를 potential(NOT_JUDGED)로 두는데, **Agent 4가 시험 판정을 다시 계산하면서 eligible로 바꿈**. Agent 4 `trial_verdict`가 `pc:llm_missing`을 보지 않고 제외 기준 MISSING을 비차단으로 처리하기 때문.

## Agent 4 출력으로 카드 만들기 (a5j-0.2.0)

`agent5/from_graph.py`가 Agent 4 출력(`graph_<pid>.json` + `verify_report.json`)을 Agent 3 출력 모양으로 바꿔 줍니다. 기준마다 가장 마지막 판정(`#n`이 가장 큰 verdict), 시험 라벨은 Agent 4가 다시 계산한 `trial_verdicts`, 기준·근거는 그래프 노드에서 읽습니다. 운주 파트(`cards.py`)도 같은 변환으로 돌릴 수 있습니다.

```bash
python -m agent5.lookup_run cards --graphs ../agent4_v1/runs/dev_a031 --split dev --out runs/dev_lookup_a4
python -m agent5.lookup_run cards --graphs ../agent4_v1/runs/dev_a031 --split dev --include-ineligible --out runs/dev_lookup_a4_all
python eval/score_lookup.py runs/dev_lookup_a4_all/cards.jsonl
```

변환 확인: a3-0.3.1 출력과 비교해 바뀐 판정 41건(상태 40 + 이유 1), 바뀐 시험 라벨 3쌍 = Agent 4 노션 보고와 일치.

| | a3-0.3.0 기본 | a3-0.3.1 기본 | **Agent 4 이후 기본** | a3-0.3.1 변형 |
| --- | --- | --- | --- | --- |
| 카드 (환자 수) | 136 (15) | 142 (14) | **148 (15)** | 216 (27) |
| 기록 찾기 / 과거력 / 검사 결과 / 환자 질문 | 28 / 40 / 4 / 64 | 25 / 57 / 2 / 58 | 27 / 59 / 2 / 60 | 40 / 74 / 7 / 95 |
| 시험 차단 카드 / 안전 확인 카드 | 19 / 104 | 14 / 114 | 15 / 119 | 16 / 171 |
| 정답 MISSING 줄 중 카드 생성 | 69.5% | 72.1% | 71.8% | 71.0% |
| 카드 종류 = 정답 | 67.0% | 68.8% | 68.6% | 70.5% |
| 불필요 질문 (정답 PASS·FAIL) | 62 / 327 | 58 / 322 | 58 / 321 | 99 / 607 |
| a5u 카드와 중복 | 0 | 0 | 0 | - |

- Agent 4가 바꾼 판정 41건은 전부 CONFLICT(24)·UNSUPPORTED+의사 확인(15)·EXPIRED+새 검사(2) → **모두 a5u 영역**. 본 파트 카드로 직접 들어온 것 0건.
- 카드가 6장 늘어난 이유: Agent 4가 시험 3쌍을 potential로 내리면서 그 시험의 MISSING 줄이 다시 대상이 됨.
- Agent 4는 dev 기본만 실행됨 (변형은 a3-0.3.1 출력으로만 측정).

## dev 결과 (Agent 3 a3-0.3.0 v10 출력, 근거 키트 v14.12)

| | 기본 54쌍 | 변형 100쌍 |
| --- | --- | --- |
| 대상 줄: MISSING 기록 찾기·환자 질문 / a5u handoff | 307 / 20 | 590 / 36 |
| 제외: 이미 ineligible인 시험 | 191 | 403 |
| 담당 미정 MISSING (비차단 검사·의사 확인) | 112 | 222 |
| 카드 (환자 수) | 136 (15명) | 222 (26명) |
| 기록 찾기 / 과거력 / 검사 결과 / 환자 질문 | 28 / 40 / 4 / 64 | 45 / 55 / 9 / 113 |
| 시험 차단 카드 / 안전 확인 카드 | 19 / 104 | 24 / 168 |
| 시험의 마지막 걸림돌 카드 | 2 | 1 |
| route: 환자 질문 / Agent 2 재추출 / 업로드 요청 | 64 / 0 / 72 | 113 / 0 / 109 |

정답 비교 (`--include-ineligible`):

| | 기본 | 변형 |
| --- | --- | --- |
| 정답 MISSING 기록 찾기·환자 질문 중 카드 생성 | 182 / 262 (69.5%) | 410 / 569 (72.1%) |
| 카드 종류 = 정답 expected_action | 122 / 182 (67.0%) | 288 / 410 (70.2%) |
| 정답 handoff 줄 중 카드 생성 | 2 / 7 | 11 / 18 |
| 카드 항목 중 정답이 이미 PASS·FAIL | 62 / 327 | 106 / 626 |

- a5u 카드와 중복 0건, handoff 줄 a5u와 일치 (기본 20, 변형 36).
- 종류 불일치는 대부분 정답 `med_history_check`인데 Agent 3이 `patient_question`(기본 22, 변형 30). 카드 종류가 Agent 3 action을 따르므로 Agent 3 쪽 문제.
- 카드가 안 생긴 정답 줄: Agent 3이 PASS로 확정(38 / 77)하거나 의사 확인·검사로 보냄(a5u 영역).
- 근거 키트: v14.9 haiku 파일이 노션 키트(v14.12)에 없어 v14.12 사용. Agent 3 출력이 가리키는 근거 ID 중 기본 38/1180, 변형 59/2240이 v14.12에 없음 → 해당 카드의 근거 표시만 빠짐, 카드 수·채점에는 영향 없음.

## 고리 확인 (SYN-0010, API 없이 Agent 3 판정 직전까지)

1. 카드 `SYN-0010:lab_check:L01` "[검사 결과 찾기] Result of the pending QuantiFERON-TB (IGRA)" (NCT02714634-E06, 시험 차단)에 가상 답: 2026-09-20 QuantiFERON 음성 (`examples/answers_lookup_dev_SYN-0010.jsonl`)
2. `agent5.lookup_run answer` → `SYN-0010-D09` (lab_result)
3. Agent 2 `update.py --provider rules` (`../agent2_v14_13`) → 새 문서만 재추출, 근거 2개 (EV300 `lab_other` QuantiFERON = false, EV301 `diagnosis` TB = **true**), `changes.jsonl`
4. Agent 3 `--changes --llm replay` → 영향받는 기준 5개만 재판정 대상으로 잡힘. 캐시에 답이 없어 판정은 못 함

```bash
cd ../agent3_final
python -m agent3.run --split dev --llm anthropic --evidence ../산학협력프로젝트/runs/loop_SYN-0010/a2_upd/evidence.jsonl --patients ../산학협력프로젝트/runs/loop_SYN-0010/patients_new.jsonl --prev ../산학협력프로젝트/runs/loop_SYN-0010/agent3_prev.jsonl --changes ../산학협력프로젝트/runs/loop_SYN-0010/a2_upd/changes.jsonl --patient SYN-0010 --out ../산학협력프로젝트/runs/loop_SYN-0010/a3_rejudge_api
```

`runs/loop_SYN-0010/a3_rejudge`, `a3_rejudge_api` 폴더의 판정은 LLM 호출 실패(캐시 없음, API 401) 결과라 사용 금지.

발견한 것:
- **Agent 2:** "QuantiFERON 음성" 문장에서 `diagnosis` TB = true 근거가 같이 나옴 (부정 표현 처리 누락 의심, rules 경로)
- **Agent 3:** LLM 답이 없을 때 제외 기준이 UNKNOWN/MISSING으로 채워지고, 제외 MISSING은 시험을 막지 않아서 NCT02714634가 potential → **eligible**로 바뀜. 실제 판정이 아니라 답 누락의 부작용. LLM 실패를 eligible로 집계하지 않도록 Agent 3·4에 전달 필요

## 정할 것

1. `not_found` 다음 단계: 환자 질문 / 의사 확인 중 어디로 넘길지 (운주와).
2. 시험을 막지 않는 MISSING의 의사 확인·검사 줄(운주 dev 기본 42줄): 브리핑에 "확인 권장"으로 보일지.
3. 환자 질문 카드가 운주 쪽(UNSUPPORTED)과 같은 질문일 때 한 장으로 합칠지.
4. Agent 4가 붙으면 입력을 Evidence Graph의 `status == UNKNOWN` 노드로 바꾸기.
