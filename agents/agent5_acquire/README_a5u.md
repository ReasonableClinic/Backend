# Agent 5 — Information (EXPIRED / UNSUPPORTED 담당)

4차 회의 'Agent 4 역할' 표 1번에서 운주가 맡은 부분입니다. 기록을 더 뒤져도 답이 안 나오는 UNKNOWN을 받아서 새 검사를 안내하거나 의사·환자에게 직접 묻고, 받은 답을 기록 문서로 바꿔 Agent 2 → Agent 3 재판정으로 넘깁니다.

| Agent 3 판정 | 카드 | 받는 사람 |
| --- | --- | --- |
| UNKNOWN / EXPIRED | `new_test` 검사 안내 (무엇을, 언제 이후 결과가 필요한지) | 환자 |
| UNKNOWN / UNSUPPORTED | `clinician_confirmation` 의사 확인 | 의료진 |
| UNKNOWN / UNSUPPORTED | `patient_question` 환자 질문 | 환자 |

- **준상 쪽과의 경계에서 가져온 것 (a5u-0.2.0)**: 끝이 같은 카드(검사 안내·의사 확인)로 나는 줄은 여기서 맡습니다.
  - CONFLICT → 의사 확인 (표에 담당이 비어 있음)
  - UNKNOWN / MISSING인데 Agent 3이 `new_test`나 `clinician_confirmation`을 붙인 줄 중 **시험 판정을 막는 것**. 제외 기준의 MISSING과 행정 항목 MISSING은 Agent 3 집계에서 시험을 막지 않아서(물어봐도 판정이 안 바뀜) 뺍니다.
- 나머지 UNKNOWN / MISSING(기록 찾기, 환자 질문)은 Agent 5의 다른 절반(준상)이 맡습니다.
- 카드 종류는 Agent 3의 `action`을 따릅니다. Agent 3이 EXPIRED·UNSUPPORTED에 기록 찾기(`med_record_check`, `med_history_check`, `lab_check`)를 붙였으면 카드를 만들지 않고 `handoff_record_lookup.jsonl`로 준상 쪽에 넘깁니다. dev 정답도 이런 줄의 절반쯤은 기록 찾기로 둡니다. `action`이 없으면 ①-b `answerable_by`를 따릅니다.
- 이미 FAIL이 있는 시험(ineligible)은 답이 와도 판정이 안 바뀌니 기본으로 빼고(`--include-ineligible`로 포함), 같은 검사는 시험이 달라도 카드 하나, 의사 확인은 시험마다 카드 하나로 묶습니다.
- 우선순위: 답이 좋으면 시험이 바로 eligible이 되는 카드(그 시험의 마지막 걸림돌)가 먼저, 다음은 걸려 있는 시험 수.

Python 3.9+, 외부 패키지 없음, API 호출 없음. 데이터는 옆 폴더 `../agent3_final`(for_agent3_v10 + 키트 v14.9)을 읽습니다.

## 실행

```bash
# 1) 카드 만들기
python3 -m agent5.run cards --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl --split dev --out runs/dev_cards
python3 -m agent5.run cards --agent3 ../agent3_final/runs/dev_variants_v10_kit149_p07/agent3_out.jsonl --split dev --variants --out runs/dev_variants_cards
#    -> cards.jsonl, handoff_record_lookup.jsonl, summary.md

# 2) 답 -> 기록 문서 (환자 파일 전체를 새로 씀)
python3 -m agent5.run answer --cards runs/dev_cards/cards.jsonl --answers examples/answers_dev_SYN-0016.jsonl --split dev --out runs/demo_SYN-0016
#    -> patients.jsonl, new_docs.jsonl

# 3) Agent 2 부분 재추출 (agent2_v14_11의 update.py; --provider rules는 API 없이 규칙만)
python3 agent2/update.py --patients runs/demo_SYN-0016/patients.jsonl --old <지난 Agent 2 실행 폴더> \
    --old-patients ../agent3_final/data/dev/input/patients.jsonl --trials ... --criteria-ref ... --provider anthropic --out <새 폴더>

# 4) Agent 3 부분 재판정 (바뀐 근거·개념에 걸린 기준만)
cd ../agent3_final && python3 -m agent3.run --split dev --llm anthropic --evidence <새 폴더>/evidence.jsonl \
    --patients <2의 patients.jsonl> --prev <이전 agent3_out.jsonl> --changes <새 폴더>/changes.jsonl --out <출력>

# 평가와 테스트
python3 eval/score_cards.py runs/dev_cards_all/cards.jsonl --agent3 ../agent3_final/runs/dev_v10_kit149_p07/agent3_out.jsonl
python3 -m unittest discover -s tests
```

`answers.jsonl` 한 줄 (형식은 `agent5/answers.py` 맨 위):

```json
{"card_id": "SYN-0016:new_test:02", "date": "2026-09-22", "result": "Transthoracic echocardiogram: LVEF 32%."}
{"card_id": "SYN-0016:clinician_confirmation:01", "criterion_id": "NCT06979375-I03", "decision": "met", "comment": "..."}
{"card_id": "SYN-0017:patient_question:03", "answer": "Yes, an archival tumor block is available."}
```

답 문서는 `as_of`(2026-10-01) 이전 날짜로만 씁니다. 그 뒤 날짜 검사 결과는 미래 기록이 되므로 받지 않고 알려 줍니다. 검사 → `lab_result`/`imaging_report`, 의사 확인 → `clinic_note`(physician), 환자 답 → `patient_interview`(patient).

## dev 결과 (Agent 3 a3-0.3.0 v10 출력 기준, a5u-0.2.0, 2026-10-27)

| | 기본 54쌍 | 변형 100쌍 |
| --- | --- | --- |
| Agent 3 UNKNOWN/EXPIRED·UNSUPPORTED (표 1번) | 100 | 184 |
| + 경계에서 가져온 줄 (CONFLICT, 시험을 막는 MISSING 검사·의사 확인) | 28 | 67 |
| 빠짐: 이미 ineligible인 시험 | 69 | 148 |
| 준상 쪽으로 넘김 (기록 찾기 action) | 11 | 16 |
| 카드 (환자 수) | 32 (14명) | 50 (26명) |
| new_test / 의사 확인 / 환자 질문 | 13 / 16 / 3 | 22 / 26 / 2 |
| 카드 항목: 표 1번 / 경계 | 34 / 14 | 59 / 28 |
| 시험의 마지막 걸림돌인 카드 | 5 | 12 |

정답과 비교 (`--include-ineligible`로 만든 카드):

| | 기본 | 변형 |
| --- | --- | --- |
| **카드 종류가 정답 `expected_action`과 일치: 표 1번** | **21 / 25 (84.0%)** | **44 / 50 (88.0%)** |
| **카드 종류가 정답 `expected_action`과 일치: 경계** | **26 / 29 (89.7%)** | **51 / 56 (91.1%)** |
| 정답 EXPIRED·UNSUPPORTED 줄 중 카드가 생긴 비율 | 25 / 54 (46.3%) | 50 / 102 (49.0%) |
| 카드 항목 중 정답이 이미 PASS·FAIL인 것 | 38 / 108 | 70 / 215 |

- 정답의 경계 줄(CONFLICT, MISSING 검사·의사 확인) 중 카드가 생긴 비율은 16~19%로 낮은데, 대부분 시험을 막지 않는 제외 기준 MISSING이라 일부러 뺀 것입니다. 정답은 시험을 막는지를 따로 적지 않아 이 비율에 그대로 들어갑니다.

- 종류가 다른 경우는 정답이 EXPIRED인 ECOG·Child-Pugh에 `patient_question`, 7·14일 창 혈액검사에 `lab_check`를 둔 것(우리는 Agent 3대로 `new_test`)이 대부분입니다.
- 아래 두 줄은 Agent 5가 아니라 앞단(Agent 3 판정, Agent 4 검증) 문제입니다. 정답 EXPIRED·UNSUPPORTED를 Agent 3이 MISSING(15)이나 PASS(12)로 낸 경우, 반대로 정답이 PASS·FAIL인데 Agent 3이 UNSUPPORTED로 남긴 경우(p07의 보수적 판정, v3 보고 3장)입니다.

## 고리 확인 (API 없이, SYN-0016)

1. 카드 `SYN-0016:new_test:02` "lvef: 마지막 2026-01-01(273일 전), 2026-07-03 이후 결과 필요"에 답: 2026-09-22 심초음파 LVEF 32%
2. `agent5.run answer` → `SYN-0016-D09`(imaging_report), `D10`(의사 확인 clinic_note)
3. Agent 2 `update.py --provider rules` → 새 근거 5개(`lvef = 32 %` 포함), `changes.jsonl`
4. Agent 3 `--changes --llm replay` → **NCT06979375-I04 UNKNOWN/EXPIRED → PASS/VALID** (코드 판정: `lvef = 32 % vs < 50 -> met`)

LLM이 다시 판정해야 하는 기준(의사 확인을 받은 I03 등)은 캐시에 답이 없어 이 확인에서는 UNKNOWN으로 남았습니다. `--llm anthropic`으로 돌려야 결과가 나옵니다.

## 정해야 할 것

1. **준상에게 알릴 경계**: 이쪽이 가져간 것은 CONFLICT와 시험을 막는 MISSING 중 `new_test`·`clinician_confirmation`입니다. 반대로 EXPIRED·UNSUPPORTED인데 Agent 3이 기록 찾기를 고른 줄은 `handoff_record_lookup.jsonl`로 넘깁니다. 시험을 막지 않는 제외 기준 MISSING의 의사 확인(기본 42줄)은 아무도 안 묻는 상태이니, 브리핑에 "확인 권장"으로라도 보일지 정해야 합니다.
2. **의사 확인 답의 형식**: Agent 2가 "Investigator review … meets this criterion" 문장을 `symptom_finding`으로 뽑습니다. Agent 3이 이 문서를 근거로 PASS를 낼지는 API로 한 번 확인이 필요하고, 안 되면 Agent 2·3과 전용 개념(예: `investigator_assessment`)을 정해야 합니다. CONFLICT 카드의 답은 어느 기록이 맞는지를 적는 형식이라 같이 정합니다.
3. **입력**: Agent 4가 생기면 Agent 3 jsonl 대신 Evidence Graph의 `status == UNKNOWN` 노드를 읽도록 바꿉니다.
4. **문구**: 카드 제목은 한국어 틀, 내용(기준 원문·`missing_fact`)은 영어 그대로입니다. 환자용 쉬운 문장은 웹 화면 담당과 정한 뒤 LLM으로 붙일지 결정합니다.
