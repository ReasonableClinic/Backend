# 에이전트 3 개발 메모: TrialGPT 검증과 dev 정답 점검에서 얻은 교훈

작성 2026-10-06 (2026-10-08 갱신), 합성 데이터·정답 담당 → 에이전트 3(Eligibility Reasoner) 담당.
함께 보낼 파일: `for_agent3_v10.zip`, `agent3_kit_v14_9.zip` (5장)

## 1. 무엇을 확인했나

### 1.1 TrialGPT 기준 단위 검증

- 데이터는 NCBI TrialGPT-Criterion-Annotations입니다. 의사 판정 1,014행, 환자 53명, 환자-임상시험 쌍 105개입니다.
- 비교 대상은 정답 생성기(gpt-oss-120b + `prompt_label_gold.md`)입니다.

| 지표 | 결과 |
| --- | --- |
| 데이터에 함께 들어 있는 GPT-4 판정의 정확도 | 0.873. 논문 값과 같아서 라벨 대응이 맞음을 확인 |
| 정답 생성기 정확도, 엄격 채점 (run1 / run2) | 0.449 / 0.432 |
| 정답 생성기 정확도, "기록에 없는 제외 기준 = 해당 없음"으로 채점 | 0.757 / 0.745 (포함 0.79, 제외 0.74) |
| 반대 방향 오류 (의사는 충족인데 정답 생성기는 미충족, 또는 그 반대) | 5 / 1,014 (0.5%) |
| 양쪽 모두 확정 판정을 낸 174행의 일치율 | 97% |

- 점수 차이는 대부분 정답 생성기가 UNKNOWN을 낸 행에서 나옵니다. TrialGPT 의사들은 기록에 없는 제외 기준을 "제외 아님"으로 봅니다. 공통 형식 규칙은 이를 UNKNOWN/MISSING으로 둡니다. 이 차이는 규칙의 차이이고 오류는 아닙니다.
- 진짜 놓침도 있었습니다. 의사가 포함 기준을 "충족"으로 본 행 가운데 41행에서 정답 생성기는 UNKNOWN을 냈고, 그중 34행이 MISSING이었습니다. 예를 들어 기록에 "known to have hypertension"이 있는데도 고혈압 포함 기준을 UNKNOWN으로 판정했습니다.

### 1.2 dev 정답 "놓친 사실" 점검

- 대상은 dev 정답에서 UNKNOWN/MISSING으로 남은 의학적 기준 428행입니다.
- 각 행을 환자 기록 전체와 다시 대조했고, 결과는 `for_agent3_v10.zip`의 `dev/gold/audit_dev_missing.csv`에 있습니다.

| 분류 | 행 수 | 예 |
| --- | --- | --- |
| 1. 기록이 그 질환을 직접 부정하거나 직접 보여 줌 | 30 (PASS 26, FAIL 4) | "No prior malignancy" ↔ 악성종양 병력 제외 기준, 복용 중인 spironolactone ↔ 칼륨보존 이뇨제 제외 기준 |
| 2. 장기계 일괄 부정이 해당 만성 질환을 덮음 | 38 (PASS) | "No other cardiac, pulmonary, hepatic, renal, autoimmune or neurologic history" ↔ 간질성 폐질환·뇌전증·심장 아밀로이드증 병력 |
| 3. 추론으로만 알 수 있음 | 76 | 정리된 투약 목록에 없으니 그 약을 쓰지 않음, 치료 이력에 TACE만 있으니 전신 치료 없음 |
| 그대로 둠 | 284 | 점검 중 기각된 제안 1건 포함 |

- `for_agent3_v10.zip`의 dev 정답(`dev/gold/gold.jsonl`, dev_v8)에는 1번 분류 30행이 반영되어 있습니다. 2번은 팀 확인 후 반영합니다(3장).
- Agent 3 v1 검토(2026-10-08)에서 지적된 정답 5행도 고쳤습니다(`stage2/runs/gold_fixes_dev_1008.csv`). 시험 판정은 그대로입니다.
  - SYN-0007 × NCT07267169-I07·I08: PASS → FAIL. 시점을 현재 값(as_of)으로 통일 (I05·I09와 같은 기준)
  - SYN-0003 × NCT06997874-I04 "PPV is planned": PASS → UNKNOWN/UNSUPPORTED + `clinician_confirmation` (이미 시행함)
  - SYN-0004 × NCT06110130-I04: FAIL → PASS (I03과 OR 선택지, 환자는 I03 충족)
  - SYN-0004 × NCT06110130-I07: FAIL → PASS ("Subjects without diabetes" 조건, 환자는 당뇨)
- 2026-10-09 재검토: Agent 3 v1이 UNKNOWN으로 낸 행 중 정답이 너무 관대했던 9행을 PASS → UNKNOWN으로 고쳤습니다 (기록에 명시되지 않은 항목, 판단 표현, 90일 지난 영상). 시험 판정은 그대로입니다.
- 1·2를 반영해도 임상시험 단위 라벨은 하나도 바뀌지 않습니다. 바뀌는 것은 기준 단위 정답뿐입니다.

## 2. 에이전트 3에 바로 적용할 규칙

### 2.1 반대 방향 오류를 최우선으로 막기

추천 시스템에서 가장 위험한 오류는 맞는 환자를 탈락시키거나 맞지 않는 환자를 적격으로 내는 것입니다. 정답 생성기가 0.5% 수준이므로 이보다 나빠지지 않게 하세요.

- 판단을 담은 말("clinically significant", "uncontrolled", "in the investigator's judgment", "severe")만 근거로 FAIL을 내지 않습니다. 기록에 그 정도가 직접 적혀 있을 때만 FAIL입니다.
- 행정 기준(동의, 순응 의지, 피임 동의, 연구용 검체)은 판정하지 않습니다. `criteria.jsonl`의 `"administrative": true` 기준은 UNKNOWN/MISSING으로 둡니다. action은 동의·의지처럼 환자가 답할 수 있는 항목은 `patient_question`, "investigator's judgment"처럼 의료진이 정할 항목은 `clinician_confirmation`입니다 (dev 정답과 같음).
  - 보충 (2026-10-23, v2 요청 답변): `administrative: true`는 "기록에 없어도(MISSING) 시험 판정을 막지 않는다"는 뜻이지, 무조건 MISSING이라는 뜻이 아닙니다. 기록이 그 항목을 다루면 판정합니다: 성별·나이상 해당할 수 없음(남성에게 여성 피임 조항, 폐경 후 여성 등) → PASS, 조직·검체가 있음(TURBT, PD-L1 검사 시행) → PASS, 장기 피임법 시행 중(임플란트) → PASS. 반대로 앞으로의 "동의·의지"(피임에 동의, 참여 의지)는 현재 피임 중이어도 기록에 동의가 없으면 UNKNOWN/MISSING + `patient_question`입니다. 플래그는 그대로 둡니다. dev_v8에서 정답 3행을 이 기준으로 고쳤습니다(NCT07379333-E28는 남성도 해당하는 조항, NCT07113262-I05·NCT07762105-I07은 동의 미기재).
  - NCT05428488-I05 (DAS28, "CRP dated less than 7 days from baseline")는 dev_v8에서 UNKNOWN/EXPIRED + `new_test`로 고쳤습니다. 기준 시점의 7일 조건은 as_of 기준 `time_window`로 보고, 21일 전 값은 기간 밖입니다 (v2 코드 판정이 맞음).
- 예외: TrialGPT 환자 요약은 모두 "The patient will provide informed consent, and will comply with the trial protocol without any practical issues."로 끝나고, TrialGPT 의사 판정은 동의·순응 기준을 이 문장으로 "해당함"(inclusion 38/39)으로 봅니다. TrialGPT에서는 이 문장의 근거(`social_history = true`)를 인용해 동의·순응 기준을 PASS로 판정합니다. 합성 dev·test에는 이런 문장이 없으므로 위 규칙(UNKNOWN/MISSING) 그대로입니다.
- 출처가 다른 기록끼리 엇갈리면 CONFLICT입니다 (공통 형식 6.3, 2026-10-23 추가). 예: 진료 기록 "No prior malignancy" vs 외부 기록 "2022년 대장암 절제". 외부 기록이 더 구체적이어도 FAIL로 정하지 말고 CONFLICT / `clinician_confirmation`으로 두세요. 바뀔 수 있는 측정값(검사·활력징후·영상)만 최근 값이 이전 값을 대신합니다. 변형 세트의 conflict 문제가 이 규칙으로 채점됩니다.
- 기준 문장의 "other"는 시험 대상 질환을 빼고 읽습니다. 만성 편두통 시험의 "cluster headache or other primary headaches"는 편두통 자체를 뜻하지 않습니다(점검에서 실제로 잘못 제안된 사례).
- 의심은 진단이 아닙니다. 가족력은 환자 병력이 아닙니다. 계획이나 권고("plan to start", "Options discussed", 관리 목록의 "no smoking")는 받은 치료나 환자 상태가 아닙니다.

### 2.2 명시적 부정은 PASS (놓친 사실의 주원인)

| 기록 | 판정 |
| --- | --- |
| 그 질환을 직접 부정: "no pancreatitis", "No stroke or TIA", "No prior malignancy", "No prior immunotherapy" | PASS / VALID. 평생 부정은 "최근 N개월 이내 X"도 덮음 |
| 장기계 일괄 부정: "No other cardiac, pulmonary, ... history" | 그 계통 만성 질환의 병력·진단 기준에 PASS (공통 형식 6.3 추가 제안, 3장) |
| 아무 언급 없음 | UNKNOWN / MISSING (지금 규칙 유지) |
| 기준이 A·B·C를 나열하는데 A만 부정 | UNKNOWN. 나머지가 일괄 부정으로 덮일 때만 PASS |
| 진찰 소견의 음성("no ascites" on exam) | 현재 상태 기준에는 PASS, "병력" 기준에는 해당하지 않음 |

장기계 일괄 부정은 다음 기준에는 쓰지 않습니다.

- 검사·심전도·영상 수치
- 기간 안의 급성 사건
- 약물, 시술, 감염
- 연구자 판단 기준

### 2.3 에이전트 2 근거 사용법 (`agent3_kit_v14_9.zip`, 근거 v14.9, ①-b 반영)

- 일괄 부정 문장은 계통마다 근거 하나씩 나옵니다: `diagnosis[cardiac history] = false`, `diagnosis[autoimmune history] = false` 등. 이것을 그 계통 만성 질환 기준의 PASS 근거로 쓰되(2.2), `term`에 "other"가 붙은 경우가 있으니 원문(`source.text`)도 함께 보세요.
- 계획 속 권고("no smoking", "smoking cessation advised")는 `treatment_plan`(`detail.status: planned`)으로 나옵니다. 흡연·음주 여부는 사회력 근거로 판정하세요.
- 과거 습관은 `value: true` + `detail.status: past`입니다("Ex-smoker", "quit 2020", "abstinent from smoking since 2020"). "Alcohol use disorder: abstinent since 09-25"는 진단(`current`)과 음주(`past`) 두 근거로 나뉩니다. "현재 흡연·음주" 기준은 `status`까지 보고 판정하세요. `value: false`는 "한 적 없음"입니다.
- 받은 적 없는 치료는 `medication`/`procedure` `false`로 나옵니다("Denies any prior systemic therapy" → `medication[prior systemic therapy] = false`).
- 근거가 많습니다(환자당 약 240개). 기준과 관련된 근거만 골라 판정 프롬프트에 넣는 것이 정확도에 유리할 수 있습니다.

### 2.4 추론으로만 알 수 있는 경우 (3번 분류)

"정리된 투약 목록(MEDICATIONS reconciled)에 없고 최근 중단 약도 없다", "치료 이력이 완전하게 적혀 있다" 같은 경우입니다.

- dev 정답은 이 경우를 UNKNOWN/MISSING(엄격)으로 둡니다.
- 채점할 때는 `audit_dev_missing.csv`의 `3_inferred` 행을 "PASS도 허용"으로 보는 관대 점수를 함께 냅니다.
- 에이전트 3이 이런 행에 PASS를 낼 때는 `derived_from`에 근거(투약 목록 문서 등)를 남겨 주세요. 에이전트 4가 확인할 수 있어야 합니다.

## 3. 공통 형식 6.3에 추가 제안 (팀 확인 필요)

> 장기계 일괄 부정("No other cardiac, pulmonary, hepatic, renal, autoimmune or neurologic history")은 그 계통 만성 질환의 병력·진단 기준에 대한 명시적 부정으로 본다(PASS/VALID). 검사 수치, 기간 안의 급성 사건, 약물, 시술, 감염, 연구자 판단 기준에는 적용하지 않는다. 투약 목록이나 치료 이력의 "없음"에서 추론한 판정은 정답에서 UNKNOWN/MISSING으로 두고, 채점 때 PASS도 허용하는 관대 점수를 함께 보고한다.

## 4. 평가 방법과 목표

| 평가 | 방법 | 목표 |
| --- | --- | --- |
| TrialGPT 기준 단위 | `stage2/trec_eval/trialgpt/trialgpt_eval.py`: `build`로 만든 `data/` 입력을 에이전트 3에 넣고, 출력을 `gold_draft.jsonl` 형식으로 저장한 뒤 `compare --run <폴더>` | 반대 방향 오류 ≤ 1% (합격 기준). "기록에 없는 제외 기준 = 해당 없음" 점수는 정답 생성기 0.757보다 높게 (참고) |
| TREC 임상시험 단위 | `stage2/trec_eval/compare_trec.py` | TREC 제외인데 에이전트 3이 eligible로 낸 비율 ≤ 5% |
| dev 정답 | `for_agent3_v10.zip`의 `dev/gold/gold.jsonl`과 기준 단위 상태 일치율, 엄격·관대(`3_inferred` 허용) 두 가지 | 반대 방향 오류(PASS↔FAIL) 0건 지향 |

- 개발과 조정은 dev와 TrialGPT·TREC로만 합니다.
- test는 버전을 고정한 뒤 한 번만 돌립니다. test 정답은 `for_agent3_v10.zip`에 없고 합성 데이터·정답 담당이 채점합니다.

## 5. `for_agent3_v10.zip`과 `agent3_kit_v14_9.zip`

두 파일은 담긴 내용이 다르고, 에이전트 3에는 둘 다 필요합니다. `for_agent3_v10.zip`은 판정할 문제와 채점용 정답이고, `agent3_kit_v14_9.zip`은 판정할 때 쓸 근거입니다.

|  | `for_agent3_v10.zip` | `agent3_kit_v14_9.zip` |
| --- | --- | --- |
| 만든 쪽 | 합성 데이터·정답 담당 | 에이전트 2 담당 |
| 역할 | 에이전트 3의 입력 원본과 채점용 정답 | 에이전트 3이 판정할 때 쓰는 근거 |
| 공통 형식에서 | ②(환자 기록), ①(임상시험 기준), ④(정답) | ③(근거 객체) |

**`for_agent3_v10.zip`에 들어 있는 것**

- dev·test 환자 기록과 판정할 쌍 목록 `pairs.jsonl` (`dev/input/`, `test/input/`)
- 임상시험 정보와 기준 목록 (`dev/reference/`, `test/reference/`). dev·test 기준 모두 ①-b(`concept`·`operator`·`value`·`time_window` 등)가 채워져 있고 (dev v2 확정본, test v1 + 합성 담당 단위 정리 5행·`fix_note`) 개념 사전은 `reference/concepts.json`
- dev 정답(dev_v10)과 점검표 (`dev/gold/`). 정답 근거 706개에 `concept`·`term`·`value`·`unit`·`status`가 채워져 있어 에이전트 2 근거와 개념 단위로 비교 가능
- 이 메모, 공통 형식 문서
- test 정답은 빠져 있음

**`agent3_kit_v14_9.zip`에 들어 있는 것**

- `for_agent3_v10.zip`의 dev 환자 20명에서 뽑은 근거 v14.7: `evidence_dev_haiku_v14_9.jsonl`(Haiku 4.5, 4,901개), `evidence_dev_rules_v14_9.jsonl`(규칙만). ①-b 개념 사전(`concepts.json`)을 쓰고, 기준별 근거 선별 `for_criterion`이 ①-b 개념으로 동작함. v14와 ID는 거의 같음(Haiku 8개 제거, 19개 추가). 새 개념 `measurable_disease`는 크기가 적힌 병변 문장에 붙고, RECIST 측정 가능 판단은 에이전트 3이 함
- 근거를 조회하는 코드 `agent2/evidence_index.py`, 임시 개념 목록
- 사용 안내 문서 `AGENT2_OUTPUT_FOR_AGENT3.md`
- TREC 환자 75명 근거 `evidence_trec_haiku_v14_7.jsonl`(v14.3에서 혈압 단위 4개만 "mmHg"로 수정, 근거 ID 그대로), `evidence_trec_rules_v14_7.jsonl` (`eval_tools_v1.zip`의 TREC 표본 70명 포함)
- TrialGPT 환자 53명 근거 `evidence_trialgpt_haiku_v14_7.jsonl`(693개), `evidence_trialgpt_rules_v14_7.jsonl`(515개, 대체용). `eval_tools_v1.zip`의 TrialGPT 환자 53명과 같음. 이제 TrialGPT도 원문만이 아니라 이 근거로 판정할 수 있음
- test 근거는 별도 파일 `agent3_test_kit_v14_9.zip` (기본 30명·변형 34명, 2026-10-25). v14.8에서 연도 없는 날짜("on 8/5")의 측정일을 고침. 이 판으로 test를 한 번만 돌림

**흐름:**

1. `for_agent3_v10.zip`의 환자 기록에서 에이전트 2가 근거를 뽑았습니다(`agent3_kit_v14_9.zip`).
2. 에이전트 3이 `agent3_kit_v14_9.zip`의 근거와 `for_agent3_v10.zip`의 기준 목록으로 기준마다 PASS, FAIL, UNKNOWN을 판정합니다.
3. `for_agent3_v10.zip`의 dev 정답으로 채점합니다.

## 6. 변형 세트 (2026-10-23, `for_agent3_v10.zip`)

기본 환자 기록에서 문서 하나만 바꿔 문제를 하나 심은 환자들입니다(공통 형식 7장). 환자 ID는 변형 여부를 드러내지 않습니다.

| | dev | test |
| --- | --- | --- |
| 파일 | `dev/input/patients_variants.jsonl`, `pairs_variants.jsonl`, 정답 `dev/gold/gold_variants.jsonl` | `test/input/`의 같은 이름 파일 (정답 없음) |
| 환자 / 쌍 | 36명 / 100쌍 | 34명 / 102쌍 |
| 심은 문제 | conflict 11, unsupported 10, violation 9, missing 6 | conflict 11, unsupported 8, violation 8, missing 4, expired 3 |

- 정답의 `injection`에 대상 기준과 바꾼 문서가 있습니다. 대상 기준 하나만 바뀌고 나머지는 기본 환자 정답을 그대로 물려받습니다.
- conflict는 "출처가 다른 기록이 엇갈림"(외부 기록 대 진료 기록, 같은 날 다른 검사실, 두 약국)입니다. 정답은 CONFLICT / `clinician_confirmation`이고, 한쪽 기록이 더 구체적이어도 FAIL이 아닙니다(공통 형식 6.3). LLM 확인에서 가장 많이 틀린 유형입니다.
- 에이전트 2 근거: `agent3_kit_v14_9.zip`의 `evidence_dev_variants_haiku_v14_9.jsonl`. test 변형 근거는 test 기본 환자와 함께 나중에 한 번만 만듭니다.
- 채점은 기본 dev와 같은 방식으로 하되, 변형 유형별로 대상 기준을 맞혔는지 따로 보면 됩니다.

## 7. dev_v8 / test_v5 (2026-10-25)

- **A1 일괄 부정 반영** (3차 회의 결정): 장기계 일괄 부정("No other cardiac, pulmonary, ... history")이 덮는 만성 질환 병력 기준을 PASS로 고침. dev 38행, test 34행(점검표 `2_blanket`). 제외 기준의 MISSING → PASS라 시험 라벨 변화 없음. 예외(검사 수치·급성 사건·약물·시술·감염·연구자 판단)는 그대로 UNKNOWN.
- **행정 항목 5행** (4차 회의 안건 3. 에이전트 3 담당이 자기 사본에서 고친 것을 우리 기준 파일에도 반영. 에이전트 1(CT.gov) 담당 원본에는 아직 미반영): 기록으로 답할 수 있는 조직·피임 항목을 `administrative: false`로. 정답은 원래 PASS라 판정 변화 없음.
- 에이전트 3 v3(p07) dev 점수: dev_v8 기준 기준 일치 82.6% / 83.2%(1·2회차), 반대 방향 2 / 0, 시험 판정 87.0% / 90.7%.
- 변형 세트는 대상 기준 외의 기준이 기본 정답을 물려받으므로 함께 다시 만듦(대상 기준·변형 내용은 그대로).

## 8. dev_v9 / test_v6 (2026-10-25, `for_agent3_v10.zip`)

4차 회의 안건 2·3에서 합의한 기준을 반영.

- **A3 나열 항목 규칙**: 기준에 나열된 항목 중 기록이 다루지 않은 것이 있으면 UNKNOWN/MISSING. 환자에게 해당할 수 없는 항목(남성의 수유, 폐경 후 임신, 자궁·난소 절제 후 임신)이나 상위 사실로 배제되는 항목은 다룬 것으로 봄. 대표 예: "임신 또는 수유"에 hCG 음성만 있으면 수유가 비어 있으므로 UNKNOWN(patient_question).
  - dev 10행: 에이전트 3 v3 목록 4행 + 같은 규칙으로 우리가 찾은 6행 (`stage2/runs/gold_fixes_dev_1025.csv`).
  - test는 같은 규칙으로 우리가 점검해 10행 (모두 임신·수유 기준).
  - 모두 제외 기준이라 시험 라벨 변화 없음.
- **행정 항목 기준**: 동의서 서명, 의향, 앞으로의 피임 동의는 `administrative: true`. 조직·검체 보유, 현재 피임 방법, 임신·수유처럼 기록으로 답할 수 있는 것은 `false`. 여러 요소가 섞인 기준은 기록 사실이 하나라도 필요하면 `false`.
  - test 후보 71행 중 14행을 `false`로 (`stage2/fix_ctgov_units.py`의 `TEST_ADMIN_FALSE`, 각 행 `fix_note`). 나머지 57행은 그대로 행정 항목.
  - 이 중 test 정답 4행은 기록에 조직이 있어 UNKNOWN → PASS로 고침(수술·생검 표본). 시험 라벨 변화 없음.
  - NCT06172478은 dev·test 공유 시험이라 dev 기준 파일에도 같은 변경이 들어감.
  - 에이전트 1(CT.gov) 원본에는 아직 반영 전. 목록을 에이전트 1 담당에게 알림.
- 시험 라벨: dev 5/15/34 (변화 없음). 변형 세트도 다시 만듦.
- **검사 최근성 30일 규칙 (공통 형식 6.3)**: dev 정답에는 30일 넘은 검사값으로 PASS/FAIL을 확정한 행이 없음. v3 코드 주석의 예(eGFR 35일, 혈당 176일)는 각각 "12주 동안 eGFR 변화" 기준(예전 값이 필요), 당뇨 진단으로 판정한 기준이라 예외가 아님. 측정일(값이 처음 기록된 날) 기준으로 검사 30일·영상 90일을 코드에 그대로 적용해도 dev 정답과 맞음. test 정답도 같은 규칙으로 점검해 맞춤(2026-10-25).

## 9. dev_v10 / test_v8, `for_agent3_v10.zip` (2026-10-26)

합성 데이터·변형·근거 일괄 점검 결과 반영. 시험 판정·순위 정답 변화 없음.

- **변형 환자 문서 번호**: 문서를 추가한 변형(모순 유형)에서 번호가 날짜 순서와 맞지 않아 추가한 문서가 드러났음(D05 → D10 → D06). 날짜 순서대로 다시 매김. 에이전트 2 근거도 v14.9에서 같은 번호로 바뀜. **v14.8 근거는 새 변형 환자 파일과 맞지 않으니 v14.9(`agent3_kit_v14_9.zip`, `agent3_test_kit_v14_9.zip`)를 쓰세요.**
- **기록 문구 2곳**(문서 날짜보다 뒤 날짜): dev SYN-0011 Brain MRI 날짜, test SYN-6332 LVEF 날짜. 글자 수 같게 고쳐 위치 변화 없음.
- **이유 표기 5행**: 관련 기록이 있지만 증명하지 못하는 행을 MISSING → UNSUPPORTED (dev 2: NCT07803965-I03, NCT07720284-I07). 둘 다 UNKNOWN이라 판정 변화 없음.
