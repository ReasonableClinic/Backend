# 에이전트 2 출력 안내 (에이전트 3 개발용)

작성 2026-10-06, 갱신 2026-10-26 v14.9 (합성 담당 기록 수정 반영: 1장, 연도 없는 날짜 보정: 1장, 검사 대기·미기재 값: 1장, TrialGPT 근거 추가: 1장, ①-b 반영: 1·3·4·7장, 검토 11장 보정: 1장, Agent 3 v1 회의 안건 F: 6장). 에이전트 2(근거 추출)의 출력 ③을 에이전트 3(기준 판정)이 바로 쓸 수 있게 정리한 문서입니다. 형식의 기준은 `common_format_v0.5.md` 5장이고, 여기서는 확장 필드와 값의 뜻, 권장 사용법을 적습니다.

## 1. 파일 (v14.9, 2026-10-26; TREC·TrialGPT는 v14.7 그대로)

| 파일 | 내용 |
| --- | --- |
| `agent3_kit/evidence_dev_haiku_v14_9.jsonl` | dev 환자 20명의 ③, 근거 4,901개 (환자당 약 245개). Claude Haiku 4.5 배치 실행(v14, ①-b 계획) + 규칙, v14.3·v14.7 보정 적용 (아래) |
| `agent3_kit/evidence_dev_rules_v14_9.jsonl` | 같은 환자, 규칙만 쓴 ③ 3,538개 |
| `agent3_kit/evidence_dev_variants_haiku_v14_9.jsonl` | dev 변형 환자 36명(합성 담당 `for_agent2_variants_dev.zip`), 근거 8,819개. 기본 환자와 같은 문서의 근거는 기본 환자 근거를 그대로 옮기고(새 환자·문서·근거 ID), 다른 문서 하나만 Haiku 4.5로 새로 추출 (10-23, $1.13) |
| `agent3_kit/evidence_dev_variants_rules_v14_9.jsonl` | 같은 환자, 규칙만 6,376개 (같은 방식) |
| `agent3_kit/evidence_trec_haiku_v14_7.jsonl` | TREC 환자 75명, Haiku 1,600개. `eval_tools_v1`의 TREC 표본 70명 모두 포함, 원문 위치 불일치 0 |
| `agent3_kit/evidence_trec_rules_v14_7.jsonl` | TREC 환자 75명, 규칙만 1,293개 |
| `agent3_kit/evidence_trialgpt_haiku_v14_7.jsonl` | TrialGPT 검증 환자 53명(`eval_tools_v1/trialgpt`), Haiku 693개 (요약 한 편이라 환자당 약 13개). ①-b가 없는 기준이라 원문 기준으로 추출 (10-22, $0.40) |
| `agent3_kit/evidence_trialgpt_rules_v14_7.jsonl` | 같은 환자, 규칙만 515개 (대체용) |
| `agent3_kit/evidence_test_haiku_v14_9.jsonl` | **test** 기본 환자 30명, 근거 9,724개 (환자당 약 334개, 기록이 dev보다 김). 에이전트 3 `a3-0.3.0` 고정 후 1회 추출 (10-25, Haiku 4.5 배치, $5.68 + 기준 수정 반영 재요청 $1.34). 형식 오류 0 |
| `agent3_kit/evidence_test_rules_v14_9.jsonl` | 같은 환자, 규칙만 7,135개 (대체용) |
| `agent3_kit/evidence_test_variants_haiku_v14_9.jsonl` | **test** 변형 환자 34명, 근거 11,017개. 같은 문서 289개는 test 기본 환자 근거를 그대로 옮기고(새 ID), 바뀐 문서 34개만 Haiku로 추출 ($1.35 + $0.63). 형식 오류 0 |
| `agent3_kit/evidence_test_variants_rules_v14_9.jsonl` | 같은 환자, 규칙만 8,268개 (같은 방식) |
| `agent3_kit/*.changes_from_*.jsonl` | 이전 키트 파일 대비 근거 ID별 added / removed / changed. v14.7은 모든 파일에서 추가·삭제 0, 내용만 바뀐 근거가 파일마다 0~7개 |
| `agent3_kit/agent3_v1_missed_123_by_agent2.csv` | Agent 3 v1의 "확정 정답을 UNKNOWN으로" 123건 분류 (6.1) |
| `agent2/concepts.json`, `agent2/concepts_agent2.json` | ①-b 개념 사전 138개(팀 공용, 10-22 `migraine_attack_frequency`·환산 단위 추가)와 Agent 2 조정 (별칭, `tumor_marker` → `biomarker`) |
| `agent2/evidence_index.py` | ①-b 기준별 근거 선별 `for_criterion`, 한 줄 표시 `render` (7장) |
| `code/missing_check.py` | Agent 3이 UNKNOWN/MISSING으로 남긴 확정 정답 기준마다 정답 문장 위치의 Agent 2 근거 ID와 `for_criterion` 포함 여부를 표로 (v2 회의 다음 할 일 3번). 분류: `in_lookup` / `agent2_only` / `no_gold_place` / `agent2_missing` |

같은 환자 입력(`data/dev/input/patients.jsonl`, 합성 담당 `synthetic_dev_v4/input/patients.jsonl`과 같은 파일)에서 만들었고, 정답이나 `id_map`은 쓰지 않았습니다. test 출력은 블라인드 규칙에 따라 아직 만들지 않았습니다.

**v14.8 → v14.9 (10-26, 합성 담당 기록 수정 `for_agent2_1026`, 모델 재실행 없음, `agent2/apply_record_edits.py`)**: 근거 ID·개수는 그대로. 입력 환자 파일도 새 판으로 바꿔야 원문 위치가 맞습니다 (dev SYN-0011, test SYN-6332, 변형 환자 전체).

- 변형 환자 문서 번호를 날짜 순으로 다시 매김 → `source.doc_id`만 바뀜 (dev 변형 Haiku 2,265개 / 규칙 1,606개, test 변형 2,101 / 1,490). 내용·위치는 같음
- 문서 날짜보다 뒤의 날짜를 고친 문구: dev SYN-0011 "Brain MRI 2026-02-16" → "2026-02-12", test SYN-6332 "TTE ordered (LVEF 61% on 2026-03-26" → "TTE on file (… 2026-03-20", "baseline (03/26)" → "(03/20)" (각 환자의 변형도 같음). `source.text`, `observed_date`, `detail.quote`, `term`에 반영
- "LVEF 61% baseline (03/20)"은 이번에 측정일 2026-03-20으로 맞춤 (전에는 모델이 03/26을 "2026년 3월"로 읽어 03-01, 규칙판은 문서 날짜)
- 바뀐 필드만 모은 `*.changes_from_v14_8.jsonl` (한 줄 = 근거 하나의 필드 하나: 옛 값 → 새 값)

**v14.7 → v14.8 (10-26, 합성 담당 test 근거 점검 반영, 모델 재실행 없음)**: 문장 안의 연도 없는 날짜를 측정일로 읽음. 근거 ID·개수·값은 그대로이고 `observed_date`만 바뀜 (바뀐 근거에 `detail.date_from`). 바뀐 행만 모은 `*.changes_from_v14_7.jsonl`: dev 1, dev 변형 0, test 7, test 변형 10 (규칙판도 같은 수).

- 값 바로 뒤의 날짜만 그 값의 측정일: "eGFR 59 on 8/5." → 08-05, "CRP 14 mg/L on 06/10" → 06-10, "(UACR 48 mg/g on 6/10)" → 06-10. 패널 머리말 날짜도 같음: "Lipids (06/10): LDL-C 124" → 06-10
- 연도는 문서 연도, 그 날짜가 문서 날짜보다 뒤면 전년도
- 괄호 안의 예전 값 날짜는 앞의 현재 값에 쓰지 않음: "Wt 58.7 kg (58.5 kg on 09/22)"의 58.7은 문서 날짜 유지
- 앞으로 할 일의 날짜는 측정일이 아님: "keep sleep study on 9/15"
- 모델이 이미 날짜를 읽어 문서 날짜와 다른 근거는 건드리지 않음

**v14.6 → v14.7 (검토 14장 반영, 10-23, 모델 재실행 없음)**: 근거 ID와 개수는 그대로, 값만 바뀐 근거가 dev 4·변형 7·TREC 4·TrialGPT 1개.

- 검사를 보냈거나 지시만 하고 결과가 없는 문장: `value: "pending"`, `detail.status: "pending"` ("Hepatitis B, hepatitis C and HIV screening ordered; specimens sent, results pending", "Alpha-1 antitrypsin: sent to reference laboratory, result pending", "Full EEG reports are pending"). 전에는 일부가 `true`로 나와 양성으로 읽힐 수 있었음. 기존 "QuantiFERON-TB: sent, result pending" = `"pending"`과 같은 형식
- "기록 안 됨"("product not recorded", "Hypertension is not documented"): `value: null` (전에는 `false`라 "없음"으로 읽힐 수 있었음)
- hCG·간염·HIV 결과를 글자("negative", "positive")로 낸 근거는 `false`/`true`로 통일

TREC·TrialGPT 요약 끝의 "The patient will provide informed consent, and will comply with the trial protocol …" 문장은 `social_history = true`(동의·순응 가능) 근거 하나로 냅니다. 동의·순응 기준(대개 행정 항목)에 인용할 수 있습니다.

**v14 → v14.3 (검토 11장 반영, 모델 재실행 없음, `agent2/postfix.py`)**: 근거 ID는 그대로이고 내용만 고친 것은 `changed`입니다.

- 검사 줄의 숫자: "Alpha-1 antitrypsin 135 mg/dL (ref 90-200)"처럼 값이 적힌 줄이 `lab_other = true`로 나오던 것을 숫자로 (dev Haiku 282개). 사전에 있는 검사는 그 키로 (`calcium` 8.5 mg/dL, `magnesium`, `phosphate`), 나머지는 `lab_other` + 숫자·단위·`term`(검사 이름)·참고 범위. `">300"`, `"0.048 (low)"` 같은 문자열 값도 숫자 + `detail.comparator`로
- "HIV 1/2 Ag/Ab negative"의 HIV 값이 숫자 1이던 것 → `false` (3개)
- `cancer_stage`가 아닌 것 제외: "Grade 2 peripheral neuropathy", "ALBI grade 2", "GOLD 3", "moderately severe"(췌장염 중증도) (dev 11개: 같은 문장에 다른 근거가 있으면 제거 8, 없으면 `symptom_finding`으로 3)
- "Counselled on effective contraception …" → `contraception`이 아니라 `treatment_plan` (`planned`)
- 새 개념 `measurable_disease`: 크기가 적힌 종양 병변 문장("4.2 cm RUL mass", "new 1.6 cm and 0.9 cm liver lesions")에 `true` + `detail.size_mm`(가장 큰 값). RECIST 측정 가능 여부(10 mm 이상, 영상 시점)는 Agent 3 판단 (dev 19개 추가)
- dev Haiku: changed 290, removed 8 (모두 위 `cancer_stage`), added 19. Agent 3 v2가 v14 근거로 저장한 판정은 `removed` 8개를 인용한 기준만 다시 판정하면 됩니다

## 2. 근거 하나의 모양

```json
{"evidence_id": "SYN-0001-EV193", "patient_id": "SYN-0001",
 "concept": "diagnosis", "value": true, "unit": null, "value_type": "boolean",
 "observed_date": "2026-09-30", "certainty": "suspected", "subject": "patient",
 "source": {"doc_id": "SYN-0001-D07", "doc_type": "clinic_note", "author_role": "physician",
            "span": [3915, 4044],
            "text": "Idiopathic nephrotic syndrome, presumed minimal change disease, steroid-responsive, in remission on day 15 of daily prednisolone."},
 "extracted_by": "llm",
 "term": "minimal change disease",
 "detail": {"status": "current", "quote": "presumed minimal change disease"}}
```

### 형식에 있는 필드의 뜻 (에이전트 2가 지키는 것)

| 필드 | 뜻 |
| --- | --- |
| `value` | 수치 개념은 숫자(개념의 기본 단위로 변환됨). 질환·약물·시술·행동은 `true`/`false`. **`false`는 기록에 명시적으로 부정된 것**("No prior malignancy", "Resp: no cough")이다. 기록에 없는 것은 근거 자체가 없다 |
| `certainty` | `confirmed`(검사·병리·영상·의사 판단), `reported`(환자·보호자 진술), `suspected`("presumed", "possible", "likely" 등이 그 항목을 수식할 때만) |
| `subject` | `family`면 가족력. 보호자가 전한 환자 증상("mother notes foamy urine")은 `patient` + `reported` |
| `observed_date` | 사실이 일어난 날. 문장에 날짜가 없으면 문서 날짜. 가려진 날짜·미래 날짜는 `null` |
| `source.span` | 문서 `text` 안의 정확한 위치. 단위는 문장·줄·검사 항목. `source.text == document.text[span[0]:span[1]]` 항상 성립 |

### 확장 필드 (공통 형식에 추가)

| 필드 | 뜻 |
| --- | --- |
| `term` | 일반 개념(`diagnosis`, `medication`, `procedure`, `symptom_finding`, `lab_other`, `treatment_plan`, `social_history`)에서 무엇인지. 진단은 이름 전체("Graves disease", "minimal change disease")이고 "disease" 같은 낱말만 따로 나오지 않는다 |
| `detail.status` | `observed` 측정·소견 / `current` 진행 중인 질환·복용 중인 약 / `past` 과거·완료 / `stopped` 중단 / `planned` 계획·논의·권고 / `declined` 환자 거부 |
| `detail.start` | 지속 중인 약·질환의 시작일 ("since 2019" → `2019-01-01`). `observed_date`와 다름 |
| `detail.quote` | 모델이 고른 정확한 인용 (위치는 단위 전체, 인용은 그 안의 해당 부분) |
| `detail.comparator` | `"<0.01"` 같은 값의 부등호 |
| `detail.derived_from` | 코드로 계산한 값 (생년월일 → 나이, as_of 기준) |
| `extracted_by` | `llm` 또는 `rule` (규칙 결과를 쓴 경우: 확실한 검사 수치, 모델이 빠뜨린 것, 재질문 실패 등) |

### 판정할 때 주의할 점

- **계획은 받은 치료가 아니다.** `concept: "treatment_plan"`(status `planned`/`declined`)은 시행 이력으로 세지 말 것. 반대로 기록의 지시("Start prednisolone ...")는 `medication` + `current`로 나온다.
- **생활 습관 권고는 습관이 아니다 (v13.4).** 계획 속 "no smoking", "avoid alcohol", "smoking cessation advised", "outpatient alcohol program"은 `treatment_plan`(`planned`)으로 나오고 `smoking`·`alcohol`·`substance_use` 근거가 되지 않는다. 흡연·음주 여부는 사회력("Never smoker", "Current smoker", "Alcohol 1-2 drinks/week")의 근거로 판정할 것.
- **사회력 (v13.4~5).** 직업, 동거인, 보호자("Guardian: mother.", "Retired factory worker.", "Lives with husband.", "father is guardian")는 등록 문서든 진료 기록이든 `social_history`로 나온다. 보호자·간병인·직업 노출 같은 기준에만 쓰면 된다.
- **끊은 습관 (v13.5~7).** "abstinent since 09-25", "quit 2015", "Remains abstinent from smoking since 2020", "Ex-smoker"는 모두 `alcohol`/`smoking` = `true`, `detail.status: "past"`이고, 끊은 날짜가 있으면 `observed_date`가 그날이다. "현재 음주" 기준은 `current`인 근거만 있음으로 볼 것. `false`는 "평생 안 함"("Never smoker", "No alcohol")일 때만 나온다. 진단(예: 알코올 사용 장애)은 따로 `diagnosis` 근거로 나온다.
- **의심은 진단이 아니다.** `certainty: "suspected"`는 UNKNOWN 근거로. "idiopathic nephrotic syndrome, presumed minimal change disease"는 신증후군 confirmed + 미세변화병 suspected 두 근거로 나온다.
- **가족력**(`subject: "family"`)은 환자 본인 질환 기준에 쓰지 말 것.
- **나이·성별은 등록 정보 우선 (v14.12).** 규칙의 "45M" 형식이 검사 참고치 "5.10 M/uL"을 나이 10세·남성으로 읽는 버그가 v14.12에서 고쳐졌다. 고정된 test 키트(v14.9)에는 이렇게 나온 나이·성별 근거가 몇 개 남아 있고(`source.text`가 "RBC ... M/uL" 같은 검사 줄), dev 키트에는 없다. 나이·성별 근거가 서로 다르면 등록 문서나 생년월일로 계산한 나이를 우선하고, `source.text`가 검사 줄인 나이·성별 근거는 쓰지 말 것.
- **같은 사실이 여러 문서에 반복**된다(초진, 경과, 종합 H&P). 최신 `observed_date`를 우선하고, 서로 다르면 CONFLICT 후보.
- **오래된 결과**(공통 형식 6.3): 기간 없는 "현재 상태" 기준은 검사 30일, 영상 90일 넘으면 UNKNOWN/EXPIRED. `observed_date`와 `source.doc_type`(`lab_result`, `imaging_report`)으로 계산할 수 있다. `observed_date: null`(TREC 가려진 날짜)은 날짜 없는 문장 규칙대로 `as_of` 당일로 본다.
- **판정 규칙은 정답과 같게**: 정답은 공통 형식 6.3 규칙으로 달렸다. 에이전트 2는 그중 근거 쪽 규칙(명시적 부정 = `false`, 계획 ≠ 시행, 의심 ≠ 진단, 가족력 분리)을 이미 값에 반영해 두었다.
- **개념 키**는 ①-b 공식 `agent2/concepts.json`(138개)을 따른다. 에이전트 2는 `concepts_agent2.json`의 조정만 더한다: 종양 마커는 `tumor_marker`가 아니라 기준 79개가 쓰는 `biomarker`로, `administrative`는 내지 않음. 혈압은 `blood_pressure`("148/92")와 `systolic_bp`·`diastolic_bp`(숫자)를 같이 낸다. FEV1·FVC·DLCO는 % predicted 값만 낸다(리터 값만 있으면 내지 않음).

## 3. 권장 사용법

①-b가 있는 기준은 7장의 기준별 선별(`for_criterion`)을 먼저 쓰고, 선별 결과로 UNKNOWN이 나오면 **환자 근거 전체**로 한 번 더 판정하는 것을 권합니다. 환자 근거 전체는 한 줄씩 정리하면 환자당 약 9천 토큰(최대 1만)이라 그대로 들어가고, 같은 환자의 여러 시험을 판정할 때 프롬프트 캐시로 재사용할 수 있습니다. ①-b가 없는 기준(free_text 426줄)도 이 방식입니다.

```python
import sys; sys.path.insert(0, "agent2")
from evidence_index import EvidenceIndex
ix = EvidenceIndex("agent3_kit/evidence_dev_haiku_v14_9.jsonl", patients="data/dev/input/patients.jsonl")
text = ix.render(sorted(ix.by_patient["SYN-0001"], key=lambda e: (e["source"]["doc_id"], e["source"]["span"][0])))
# render()는 줄바꿈으로 이은 문자열 하나를 돌려줍니다 (근거 하나에 한 줄)
```

한 줄 모양:

```
[SYN-0001-EV193] 2026-09-30 clinic_note: diagnosis[minimal change disease] = yes (suspected, current) | "Idiopathic nephrotic syndrome, presumed minimal change disease, steroid-responsive, in remission on day 15 of daily pred"
```

판정 결과의 근거로 `evidence_id`를 돌려주면 에이전트 4(검증)가 `source.span`으로 원문을 다시 확인할 수 있습니다.

기준에 ①-b `concept`가 없으면 `for_criterion`은 단어 겹침으로 찾습니다(약함: 정답 근거 포함 0.65). ①-b가 있으면 개념 일치 + `time_window` 표시 방식이고 자세한 것은 7장입니다.

## 4. 품질 (dev, 합성 담당 정답 `synthetic_dev_v5`, 2026-10-22)

정답 근거 622개(기준이 인용한 것)로 쟀습니다. dev_v5부터 정답 근거에 개념·값이 있어 개념·값 일치도 잽니다 (`code/eval_evidence.py`).

| 지표 | Haiku v14.3 | 규칙만 v14.3 |
| --- | --- | --- |
| 정답 근거와 위치가 겹치는 비율 | **1.000** | 0.979 |
| 위치 일치 (IoU ≥ 0.5) | 0.802 | 0.780 |
| 개념 일치: 정답 근거 위치에 같은 개념 근거가 있음 | 0.904 (526/582) | 0.878 |
| 값 일치: 그 위치의 같은 개념 근거 중 값이 같은 것이 있음 | 0.859 (500/582) | 0.826 |
| 수치 기준 101개를 Agent 2 값으로 코드 판정 (`code/eval_concepts.py`) | 89개 판정, **정답과 89 모두 일치** | 89개 판정, 89 일치 |
| `source.text` 불일치, 기준일 이후 날짜, 중복 ID | 0 | 0 |

개념이 다른 곳은 대부분 "문장이 말하는 개념"(Agent 2)과 "기준이 쓰는 개념"(정답)의 차이입니다: "Male." `sex` ↔ `pregnancy`, "Urine hCG negative" `hcg` ↔ `pregnancy`, "Retina attached" `symptom_finding` ↔ `diagnosis`. `for_criterion`의 관련 키 묶음으로 이어지므로 판정에는 문제가 없습니다. 값이 다른 곳은 표기 차이가 많습니다: `"non-reactive"` ↔ `false`, "HBV DNA not detected (<10 IU/mL)"의 10 + `comparator: "<"` ↔ `"not detected"`.

부정 문장 수는 `agent2/attr_audit.py`로 다시 센 값입니다. 이전 문서의 143은 다른 방식으로 센 값이고, 같은 방식이면 v12도 136이라 이번 수정으로 줄어든 것은 없습니다.

v13.4에서 뺀 잡음 (dev, Haiku): 진료과 머리줄("Pediatric nephrology.", "Endocrine clinic, new referral.") 11, 검사 묶음 제목("ROUTINE PANEL (collected ...)") 6, "Hospital day 4." 같은 빈 문장 2, 다른 줄의 사실을 머리줄에 붙인 모델 답 4개 단위(다시 물음), "disease"·"syndrome" 같은 낱말 진단 9 → 2. 등록 문서의 직업·보호자 13개는 `social_history`로 바꿈 (정답 근거로 쓰인 줄이 있어 지우지 않음).

알려진 약점: 복합 문장에서 일부 항목 누락, 임상의 판단을 `reported`로 표시하는 경우, 결과 대기 검사 일부. 자세한 기록은 `AGENT2_BRIEF.md` 9장.

## 5. 앞으로 바뀌는 것

- 값 정확도 채점: 완료 (4장, `synthetic_dev_v5` 정답)
- test 근거: 에이전트 3 버전 고정 후 한 번만 추출 (날짜는 팀이 정함). test ①-b는 10-22 도착, 절차는 `agent2/RUN_TEST.md`로 dev에서 예행연습 완료(10-21). 키트에는 `evidence_test_haiku_v14_6.jsonl`(Haiku)과 `evidence_test_rules_v14_6.jsonl`(대체용)로 들어감
- 갱신 (v13.5, `agent2/update.py`): 에이전트 4의 피드백이나 에이전트 5의 새 정보(새 문서)가 오면 새로 생기거나 바뀐 문서만 다시 추출한다. 바뀌지 않은 문서의 근거와 `evidence_id`는 그대로이고, 새 근거는 다음 번호(`SYN-0001-EV257` ...)를 받는다. 한 번 쓴 ID가 다른 근거를 가리키는 일은 없다. 같은 폴더의 `changes.jsonl`에 환자마다 무엇이 바뀌었는지 나온다:

```json
{"patient_id": "SYN-0002", "docs": {"new": ["SYN-0002-D99"], "changed": [], "removed": []},
 "added": ["SYN-0002-EV188", "SYN-0002-EV189"], "removed": [], "changed": [], "moved": [],
 "added_concepts": ["alcohol", "diagnosis"], "removed_concepts": []}
```

  에이전트 3은 `removed`·`changed` ID를 근거로 쓴 기준과, `added_concepts`에 해당하는 기준만 다시 판정하면 된다. 바뀐 문서의 옛 근거는 `removed`에 나온다 (근거가 사라진 기준은 다시 판정). 생년월일로 계산한 나이는 as_of가 바뀌면 같은 ID로 값만 바뀌어 `changed`에 나온다. 수정된 문서에서 문장·개념·term·값·대상·확실성이 같은 사실은 옛 ID를 그대로 쓴다: 위치만 옮겨졌으면 `moved`(다시 판정할 것 없음), 날짜·detail이 바뀌었으면 `changed`. LLM으로 다시 추출하면 term 표현이 달라져 새 ID가 되는 경우가 있다. 이 형식에 의견이 있으면 알려 주세요
- 정할 것: 판정에 쓴 근거 목록(근거-기준 연결)을 에이전트 3이 기록할지 (브리프 10장)

## 6. Agent 3 v1 회의 안건에 대한 답 (2026-10-08)

### 6.1 확정 정답을 UNKNOWN으로 남긴 123건 (안건 F "근거 누락 사례 확인")

v1 실행(`dev_sonnet55_p04`, 입력 근거 v13.7)의 123건마다 정답 근거 위치에 Agent 2 근거가 있는지 확인했습니다. 표는 `agent3_kit/agent3_v1_missed_123_by_agent2.csv`(분류, 기준 원문, 정답 근거 원문, 그 위치의 Agent 2 근거, Agent 3이 인용한 근거, `missing_fact`).

| 분류 | 건수 | 뜻 |
| --- | --- | --- |
| Agent 2가 정답 근거를 못 뽑음 | **0** | 123건 모두 정답 근거 위치에 Agent 2 근거가 있다 (1건은 정답 근거 2개 중 "diagnosed 2015"만 없음, SYN-0015 NCT03404336-I05) |
| 근거가 있는데 Agent 3이 인용하지 않음 | 82 | 2026-10-09 한 줄씩 재분류 (`stage2/runs/a2_candidates_dev.csv`, 아래 표 기준; 처음 낸 21/14/10/4/33은 단어 기준 대략치라 대체): A1 일괄 부정 17, A2 목록 추론 12, A2 확장(정상 검사치로 "질환 없음") 7, 기타 추론(나이·ECOG 환산·다른 조직형) 5, NKDA 3, 정답 유지(기록에 값이 있는데 Agent 3이 놓침, 예: eGFR 125, 프레드니솔론 5 mg) 13, 정답 재검토(정답이 너무 관대) 18, 행정 항목 성격 4, 이미 수정됨 3 |
| 근거를 인용했는데 UNKNOWN | 41 | 판단 문제: "RECIST measurable", "stable dose 4주", "EULAR 2010 기준 충족", "CAAT"(기록엔 CAT) 같은 표현을 엄격하게 읽음 (안건 A·D2) |

결론: 123건은 Agent 2 추출이 아니라 판정 규칙(안건 A1·A2·A3), Agent 3의 엄격도, 그리고 정답 18행의 관대함 문제입니다. 정답 유지 13건은 근거 ID가 이미 키트에 있으므로 Agent 3 쪽에서 인용만 하면 됩니다. 근거 표시 쪽에서 판단을 도울 수 있는 것은 고쳤습니다 (6.3).

### 6.2 TREC 환자 근거 (안건 F "TREC 환자 근거 추출")

- 입력: TREC 담당 `trec_parsing.zip`의 `patients.jsonl` (환자 75명, 문서 1개씩, `as_of` 2021-04-27, md5 `60bf2f31e8e9de56cd6b392a328e71ad`). 같은 파일인지 md5로 확인해 주세요.
- 품질: 근거 정답이 없어 합성 담당의 LLM 라벨 초안(`trec_eval/runs/trec_v2`, 100쌍, 근거 297개, 사람 검수 전)으로 쟀습니다. 위치 겹침 재현율 Haiku 0.997, 규칙 0.980. 위치 불일치·기준일 이후 날짜·중복 ID 0, 가려진 날짜(`[**...**]`)에서 나온 근거 56개는 `observed_date: null`.
- 나이·성별은 75명 모두 있음 (본문 "45-year-old man", 대명사로 추정한 성별은 `detail.derived_from: "pronouns"`).
- 환자당 한 줄 표시로 평균 약 1천 토큰(최대 2.5천)이라 전부 프롬프트에 넣어도 됩니다.

### 6.3 v13.8에서 바뀐 것

- **근거 ID 유지**: 새 버전이 근거를 하나 빼거나 더해도 뒤 번호가 밀리지 않게, 같은 사실은 이전 키트의 ID를 그대로 씁니다(`agent2/carry_ids.py`). v13.7 → v13.8에서 Haiku 근거 4,828개 모두 ID 유지, 내용이 고쳐진 14개는 `changes_from_v13_7.jsonl`의 `changed`. Agent 3의 저장된 판정(`--llm replay`)을 그대로 쓸 수 있습니다.
- **비교 부호 표시**: `evidence_index.render()`가 `tsh = <0.01 mIU/L`처럼 `detail.comparator`를 값 앞에 붙입니다 (전에는 `tsh = 0.01`로 보여 "0.01"로 읽힐 수 있었음).
- **투약 조각**: 투약 줄이 쉼표로 나뉜 조각("started 2026-09-16 (dispensed 28 days)", "max 3 g/day", "since 2014")이 `medication[started]`, `medication[dispensed]`처럼 나오던 것을 앞 약 이름으로 바꿨습니다 (`medication[prednisolone 50 mg daily]`, `detail.fragment_of`에 원래 약 줄). v1이 SYN-0001 NCT05003986-E05 판정에 쓴 EV100이 이 경우이고 ID는 그대로입니다.

## 7. ①-b 이후 기준별 근거 선별 (v14.3, 2026-10-09)

`ix.for_criterion(patient_id, criterion, k=12)`에 ①-b 기준(`concept`, `term`, `time_window`가 있는 줄)을 넣으면:

- **구체 키**(`hba1c`, `egfr`, `nyha_class` …): 그 개념과 관련 키의 근거 전부 (예: `pregnancy` → `hcg`·`sex`·`age`·`menopausal_status`, `blood_pressure` ↔ `systolic_bp`/`diastolic_bp`, `pulmonary_function` ↔ `fev1`/`fvc`/`dlco`). `time_window` 밖이면 `_outside_window: "too old"` 표시만 하고 빼지 않음
- **바구니 키**(`diagnosis`, `medication` …): 그 개념의 서로 다른 사실 전부(같은 term·값은 최신 1개), 기준 `term`·원문과 단어가 겹치는 것부터. 최대 40개. "immunosuppressants" → "prednisolone" 같은 동의어 판단은 Agent 3 LLM 몫
- 둘 다 원문 단어로 찾은 근거 몇 개를 덧붙임 (정답이 이웃 사실로 판정하는 경우: 임신 기준 ← "Male.")

dev 정답(`synthetic_dev_v5`, ①-b dev 확정본) 기준 588개 중 정답 근거가 돌려준 목록 안에 있는 비율 (규칙 근거 / Haiku 근거, 키트 v14.3):

| 방식 | 기준당 개수 (중앙값 / p90) | 정답 근거 포함 |
| --- | --- | --- |
| ①-b 전 단어 겹침 top 12 | 7 / 12 | 0.654 |
| ①-b 개념 + 바구니 전부 | 12~16 / 43 | 0.787 / 0.820 |
| 환자 근거 전부 | 약 245 | 1.0 |

권장: 수치 기준(구체 키 + 비교 연산자)은 선별 결과로 코드 판정. 바구니 기준은 선별 결과로 먼저 판정하되 UNKNOWN이 나오면 환자 근거 전부로 한 번 더 (정답 근거의 약 20%는 다른 개념의 사실에서 추론됨). 수치 기준 코드 판정을 Agent 2 근거로 미리 돌려 본 결과는 `code/eval_concepts.py` (`synthetic_dev_v5` 정답·①-b dev 확정본으로 수치 기준 101개 중 89개 판정, 89개 모두 정답과 일치).

참고치: 검사 근거에 `detail.ref_low` / `detail.ref_high`가 있으면 그 검사지의 참고 범위입니다 (같은 단위로 변환됨). ①-b의 "x ULN" 기준 41줄은 `value / ref_high`로 비교하면 됩니다. `render()`도 `alt = 74 U/L (ref 10.0-40.0)`처럼 보여 줍니다.

