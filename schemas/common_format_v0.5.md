# 환자-임상시험 매칭 데이터 공통 형식 v0.5

각 담당자는 각자 작업하되, 아래 다섯 가지 형식으로만 데이터를 주고받는다. 형식을 지키면 합성 세트와 TREC 세트를 같은 채점 코드 하나로 평가할 수 있다.

> **v0.5 변경 (합성 세트 정답 달기와 팀 회의 결정 반영)**
> - ⓪ `briefing_extra`를 정식 필드로. 한국 모집 여부 `kr_recruiting`, `kr_sites` 추가
> - ① `administrative` 필드 추가 (동의서·순응 같은 행정 항목). ①-b `time_window`에 `min_days_before` 추가
> - ① 기준 ID는 정답이 달린 `ctgov_v1/criteria.jsonl` 것을 그대로 유지 (①-b는 같은 파일에 필드만 채움)
> - ② `as_of`는 환자마다 두되 값은 데이터셋별로 고정 (합성 2026-10-01, TREC 2021-04-27). `nationality` 필드 추가 (합성 세트 전원 `"South Korea"`)
> - ③ `subject` 필드 추가 (`patient` / `family`). 가족력도 근거로 추출. 선택 필드 `term`, `detail`(`status` 등) 추가 (5.1)
> - ④ 시험 판정 규칙 확정 (6.1). `label_source: "human_verified"`의 뜻 정의 (6.2). 기준마다 `review` 필드(`human` / `agreed`) 추가. 코호트에 해당하지 않는 기준은 `criteria`에서 뺌
> - ④ 기준 판정 규칙 추가 (6.3: 오래된 검사, 판단 표현, 논의만 된 치료)
> - 검수 시트 `review.csv` 형식 추가 (`review_flag` 열 포함, 9장)
> - TREC: 가려진 날짜·이상치 날짜는 `observed_date: null`
> - 채점: 라벨 대상이 아닌 후보 풀 시험은 채점 제외 (unjudged)
>
> **v0.5 추가 (2026-10-06)**
> - ③ 과거 습관·받은 적 없는 치료의 표현, `social_history` (5.1). 갱신 출력 `changes.jsonl` (5.2)
> - ④ 놓친 사실 점검 반영 (1장 6단계, 6.2 현황). 판정 규칙 "other = 대상 질환 제외" 추가, 일괄 부정·목록 추론 규칙 제안 (6.3)
> - 7장 국적·거주 기준 변형, 10장 미결 항목 추가
>
> **v0.5 추가 (2026-10-09)**
> - ① CT.gov 담당의 ①-b dev 도착 (3,856줄, 기준 ID·원문 변경 0, 개념 사전 `concepts.json` 137개). 추가 필드 `term`·`complex`·`change`·`concept_proposed` (3장). `logic_group`은 여러 기준을 같은 `group_id`로 묶어야 함, `administrative`는 true/false 필수 (3장)
> - ① 단위 규칙: 상대 단위(xULN)는 환자 검사지의 참고 범위로 계산, 변화량 기준은 `%`·`fold` 허용, 기본 단위가 없는 검사(`lab_other`, `biomarker`)는 원문 단위 유지 (3장, 8장)
> - ④ dev 정답 5행 수정 (Agent 3 v1 검토, 시험 판정 불변), 정답 근거에 `concept`·`term`·`value`·`unit`·`status` 채움 (dev 706/745) (1장, 6장)
> - ④ 판정 규칙: 시점이 없는 기준은 현재 값, "계획됨" 기준인데 이미 시행 → 의료진 확인, OR 선택지 조각 (6.3)
> - 10장: 개념 코드 검증 완료, Agent 3 v1 회의 안건 반영

## 1. 역할과 데이터 흐름

| 담당 | 만드는 것 | 쓰는 형식 |
| --- | --- | --- |
| CT.gov API 파싱 | 고정한 시험의 정보와 기준을 API 응답에서 추출·구조화 | ⓪ Trial, ① Criterion (①-b 포함) |
| TREC 파싱 | TREC 환자·시험·qrels를 공통 형식으로 변환. TREC 시험은 CT.gov 담당의 파서를 같이 써서 ⓪·①로 변환 | ⓪ Trial, ① Criterion, ② Patient Record, ④ Gold |
| 합성 데이터 생성·파싱 | 합성 환자 기록, 정답, 문제를 심은 변형 | ② Patient Record, ④ Gold |
| 환자 근거 추출 (Agent 2) | 환자 기록에서 근거 객체 추출 | ③ Evidence |

정답은 두 갈래로 따로 만들고, 형식과 채점 코드만 공유한다.

- **합성 세트**: 합성 환자 × CT.gov 담당이 고정한 시험 → 정답 달기 (LLM 두 번 + 심판 LLM + 사람 검수)
- **TREC 세트**: TREC 환자 × TREC 시험 × 공식 qrels → 공통 형식으로 변환

### 합성 세트 생성 단계

| 단계 | 읽는 것 | 만드는 것 | 상태 |
| --- | --- | --- | --- |
| 1. 환자 생성 | 없음 (시험 기준 문구를 생성에 쓰지 않음) | ② | 완료 (dev 20, test 30) |
| 2. 정답 달기 | ⓪ + ①-a (①-b는 있으면 사용) + ② | ④, `ranking_gold.jsonl` | 완료 (dev 54쌍, test 90쌍). 놓친 사실 점검 반영, dev는 Agent 3 v1 검토 수정과 정답 근거 개념 채움까지 (dev_v5, test_v4) |
| 3. 표적 변형 | ② + ④ (PASS인 기준 선택) + ①-b | 새 ② + 새 ④ (`injection` 기록) | dev ①-b 도착(10-09), test ①-b 대기. 시험 후 시작 |
| 평가 | ② → 에이전트 → ③ | ③을 ④와 비교해 채점 | |

정답 달기 절차 (2단계):

1. LLM이 같은 쌍을 두 번 판정 (1차 temperature 0, 2차 0.7)
2. 두 판정이 다르거나 근거 인용이 기록에서 찾아지지 않는 기준에 "확인" 표시
3. 심판 LLM이 확인 표시 기준과 시험 판정이 갈린 쌍의 모든 기준을 다시 판정하고 한국어로 해설
4. 사람이 검수 화면에서 확인 표시 기준, FAIL 기준, 판정이 갈린 쌍을 검수 → `review.csv`
5. `apply_review.py --accept-agreed`로 ④ 생성
6. 놓친 사실 점검: UNKNOWN/MISSING으로 남은 기준을 기록 전체와 다시 대조해, 기록이 직접 부정하거나 직접 보여 주는 기준을 PASS/FAIL로 고침 (`audit_patch.py`, 점검표 `audit_dev_missing.csv`·`audit_test_missing.csv`). 2026-10-06: dev 30행, test 43행 수정, 시험 판정 변화 없음
7. 에이전트 검토 반영: Agent 3 v1 결과에서 지적된 정답 오류 수정 (`gold_fixes_dev_1008.csv`). 2026-10-08: dev 5행(시점 통일 2, 이미 시행한 "계획됨" 1, OR 선택지 조각 2), 시험 판정 변화 없음
8. 정답 근거 개념 채우기: ①-b와 `concepts.json`이 오면 `fill_gold_evidence.py`로 `gold_evidence`의 개념·값을 채움. 2026-10-09: dev 745개 중 706개 (사실이 아닌 문장 38개, 숫자 없는 문장 1개는 비움)

## 2. ⓪ Trial 형식 (CT.gov 담당)

시험 하나당 객체 하나. 파일: `trials.jsonl`. ClinicalTrials.gov API v2 응답(`https://clinicaltrials.gov/api/v2/studies/{nctId}`)에서 필요한 필드만 옮긴다.

```json
{
  "trial_id": "NCT0xxxxxxx",
  "title": "...",
  "overall_status": "RECRUITING",
  "status_verified": "2026-08",
  "study_type": "INTERVENTIONAL",
  "primary_purpose": "TREATMENT",
  "phases": ["PHASE2"],
  "conditions": ["Non-small Cell Lung Cancer"],
  "condition_mesh": ["Carcinoma, Non-Small-Cell Lung"],
  "min_age": 18,
  "max_age": 75.5,
  "sex": "ALL",
  "healthy_volunteers": false,
  "allocation": "RANDOMIZED",
  "arms": [{"label": "...", "type": "EXPERIMENTAL", "interventions": ["..."]}],
  "countries": ["South Korea"],
  "sites": [{"facility": "Seoul National University Hospital", "city": "Seoul", "country": "South Korea", "status": "RECRUITING"}],
  "kr_recruiting": true,
  "kr_sites": 1,
  "brief_summary": "...",
  "eligibility_text": "Inclusion Criteria:\n\n* ...",
  "criteria_complete": true,
  "briefing_extra": {"official_title": "...", "masking": "QUADRUPLE", "intervention_model": "PARALLEL", "enrollment": 288, "interventions": [], "arm_descriptions": []},
  "fetched_at": "2026-10-04"
}
```

| 필드 | API 위치 | 쓰는 곳 |
| --- | --- | --- |
| `trial_id`, `title` | `protocolSection.identificationModule.nctId`, `briefTitle` | 전체 |
| `overall_status` | `statusModule.overallStatus` | 추천 순위 |
| `status_verified` | `statusModule.statusVerifiedDate` ("YYYY-MM" 그대로) | 추천 순위. 12개월 넘게 확인되지 않은 시험은 모집 상태를 믿기 어려움 |
| `study_type` | `designModule.studyType` | 수집 단계 필터. `INTERVENTIONAL`만 사용 |
| `primary_purpose` | `designModule.designInfo.primaryPurpose` | 수집 단계 필터. `TREATMENT` 우선, `DIAGNOSTIC`·`SCREENING`은 제외 |
| `phases`, `allocation` | `designModule.phases`, `designModule.designInfo.allocation` | 개인화 브리핑 |
| `conditions` | `conditionsModule.conditions` | 시험 후보 검색 |
| `condition_mesh` | `derivedSection.conditionBrowseModule`의 MeSH 용어 | 질환 개념 정규화 |
| `min_age`, `max_age`, `sex`, `healthy_volunteers` | `eligibilityModule.minimumAge`, `maximumAge`, `sex`, `healthyVolunteers` | 나이·성별 기준. 연 단위 숫자로 변환: "18 Years" → 18, "6 Months" → 0.5, "8 Weeks" → 0.153, "30 Days" → 0.082 (소수 셋째 자리). 없으면 `null` |
| `arms` | `armsInterventionsModule` | 개인화 브리핑 (비교군, 위약 여부) |
| `sites` | `contactsLocationsModule.locations[]`의 `facility`, `city`, `country`, `status` | 추천 순위, 개인화 브리핑(가까운 기관). 연락처(`contacts`)는 넣지 않음 |
| `countries` | `sites` 중 `status`가 `RECRUITING` 또는 `NOT_YET_RECRUITING`인 기관의 국가 (중복 제거). 기관 `status`가 비어 있으면 `overall_status`를 따름 | 추천 순위. 시험 전체가 모집 중이어도 한국 기관이 모집을 끝냈으면 한국은 빠짐 |
| `kr_recruiting` **(v0.5)** | `countries`에 `"South Korea"`가 있으면 `true` | 추천 순위 가중치 (6.4) |
| `kr_sites` **(v0.5)** | `sites` 중 국가가 `"South Korea"`이고 모집 중인 기관 수 | 추천 순위, 브리핑 |
| `brief_summary` | `descriptionModule.briefSummary` | 개인화 브리핑 |
| `eligibility_text` | `eligibilityModule.eligibilityCriteria` (원문 그대로, 정리 전) | ① 파싱 원본. 파서를 고쳐도 API를 다시 부르지 않음 |
| `criteria_complete` | 파서가 판단 | 원문이 "Key Inclusion Criteria"처럼 일부만 싣거나 "Other protocol-defined criteria may apply"로 끝나면 `false`. `false`인 시험은 `eligible`이라도 브리핑에 "공개되지 않은 기준이 더 있음"을 표시 |
| `briefing_extra` **(v0.5)** | `officialTitle`, `detailedDescription`, `designInfo.maskingInfo.masking`, `designInfo.interventionModel`, `enrollmentInfo.count`, `interventions[]`, `armGroups[].description` | 개인화 브리핑 전용. 판정에는 쓰지 않음 |
| `fetched_at` | 받은 날짜 | 재현성, 출처 표기. 모집 상태와 기준은 바뀔 수 있음 |

국가 이름은 API 표기 그대로 `"South Korea"`를 쓴다 (`"Korea, Republic of"` 아님).

`resultsSection`은 쓰지 않는다. 모집 중인 시험에는 대부분 없고, 브리핑의 중립성 원칙과도 맞지 않는다.

`descriptionModule.detailedDescription`에 기준이 다시 적혀 있는 시험이 있지만, ①은 `eligibilityCriteria`에서만 만든다. 두 곳이 다르면 `eligibilityCriteria`를 따른다.

### 시험 후보 파일

파일: `trial_candidates.jsonl`. 기본 환자 하나당 한 줄.

```json
{"base_id": "S001", "split": "dev", "trial_ids": ["NCT06880770", "NCT07267169"], "pool_trial_ids": ["NCT06253117", "NCT07609771"]}
```

- `trial_ids`: 정답(④)을 다는 라벨 대상 시험. 질환과 무관한 시험은 넣지 않으며, 0~3개도 정상
- `pool_trial_ids`: 추천 검색용 후보 풀. 정답을 달지 않음 → **채점에서 unjudged로 처리** (8장)
- 한 시험이 dev와 test에 동시에 들어가지 않게 한다

## 3. ① Criterion 형식 (CT.gov 담당)

기준 하나당 객체 하나. 파일: `criteria.jsonl`. API는 기준을 마크다운 문자열 하나(`eligibility_text`)로 주므로, 이 형식은 파싱 결과물이다. 두 단계로 나눠 채운다.

- **①-a 분할 (필수)**: `trial_id`, `criterion_id`, `type`, `original_text`, `cohort`, `administrative`. 규칙 기반 처리.
- **①-b 구조화 (선택)**: `concept`부터 `answerable_by`까지. LLM 파싱으로 채우고, 못 채우면 `null`로 둔다.

> **v0.5: 기준 ID 고정.** 합성 세트 정답(④)은 `ctgov_v1/criteria.jsonl`(분할 규칙 수정본, 10,913개)의 `criterion_id`에 묶여 있다. ①-b는 이 파일에 필드만 채우고, **기준을 다시 나누거나 번호를 바꾸지 않는다.** 분할을 꼭 고쳐야 하면 바뀌는 ID 목록을 먼저 공유한다 (해당 쌍의 ④를 다시 달아야 함).

```json
{
  "trial_id": "NCT0xxxxxxx",
  "criterion_id": "NCT0xxxxxxx-I04",
  "type": "inclusion",
  "original_text": "ANC >= 1.5 x 10^9/L within 14 days before enrollment",
  "cohort": null,
  "administrative": false,
  "parse_status": "structured",
  "concept": "anc",
  "operator": ">=",
  "value": 1.5,
  "unit": "10^9/L",
  "time_window": {"anchor": "as_of", "max_days_before": 14, "min_days_before": null},
  "logic_group": null,
  "answerable_by": ["lab"]
}
```

| 필드 | 단계 | 값 | 설명 |
| --- | --- | --- | --- |
| `criterion_id` | ①-a | `{NCT}-I03`, `{NCT}-E01`, `{NCT}-U01`, 쪼갠 경우 `{NCT}-I03.1` | I = 선정, E = 제외, U = 제목이 없어 판별 불가 (선정으로 취급). 원문 번호는 무시하고 등장 순서대로 01부터 다시 매김. 한 글머리표에 기준이 여러 개면 `.1`, `.2` |
| `type` | ①-a | `inclusion` `exclusion` `unknown` | |
| `original_text` | ①-a | 글머리표 원문 (아래 정리 규칙 적용) | 쪼갠 경우에도 해당 부분 원문 |
| `cohort` | ①-a | 문자열 또는 `null` | 특정 코호트·지역·성별에만 적용되는 기준이면 그 소제목. 모든 참가자에게 적용되면 `null`. 정답 달기 때 환자의 코호트를 정하고, 해당하지 않는 코호트 기준은 ④ `criteria`에서 뺀다 |
| `administrative` **(v0.5)** | ①-a | `true` `false` | 동의서 서명, 참여·방문 의지, 피임 동의, 연구용 검체 제공 등 환자 기록으로 판정할 수 없는 행정 항목. `classify_admin.py`(LLM)로 표시하고 검수자가 고칠 수 있음. 시험 판정 규칙(6.1)에서 쓰임 |
| `parse_status` | ①-a | `split_only` `structured` `free_text` | ①-b를 채웠는지 |
| `concept` | ①-b | 공유 개념 키 | `concepts.json`에 있는 키만 사용 |
| `operator` | ①-b | `>=` `<=` `>` `<` `==` `between` `in` `exists` `not_exists` | `between`의 `value`는 `[하한, 상한]` |
| `time_window` | ①-b | `{anchor, max_days_before, min_days_before}` 또는 `null` | `max_days_before`: "등록 전 14일 이내" 같은 유효 기간. `min_days_before` **(v0.5)**: "마지막 항암 후 4주 이상 경과" 같은 최소 간격(씻김 기간). 해당 없으면 `null` |
| `logic_group` | ①-b | `{group_id, relation: "AND" or "OR"}` 또는 `null` | 묶인 기준. **여러 기준에 같은 `group_id`를 붙여야 묶임**: "A, or" 다음 줄 "B"처럼 여러 줄로 나뉜 선택지는 같은 그룹에 `OR`. 그룹 안 하나라도 PASS면 나머지는 FAIL이 아님 (6.3 선택지 목록 조각) |
| `answerable_by` | ①-b | `patient` `lab` `med_record` `clinician` 중 복수 | 정보 획득 방법 선택에 사용 |
| `term` **(v0.5)** | ①-b | 문자열 목록 | 바구니 개념(`diagnosis`, `medication`, `procedure`, `symptom_finding`, `biomarker` 등)에서 기준 원문의 표기 ("AP", "PERT"). 기록 쪽 표기(③ `term`)와의 동의어 판단은 Agent 3 몫 |
| `complex` **(v0.5)** | ①-b | `true` `false` | 한 줄에 독립 조건이 여럿. 가장 객관적인 조건 하나만 구조화됨 → 나머지는 원문으로 판정 |
| `change` **(v0.5)** | ①-b | `true` `false` | 변화량 기준 ("eGFR 50% 감소"). `value`는 변화량 |
| `concept_proposed` **(v0.5)** | ①-b | 문자열 또는 `null` | 사전에 없는 개념을 제안한 경우 (`concept`는 `null`). 빈도는 `concepts_unlisted.json` |

- **제외 기준도 "제외를 일으키는 조건"을 그대로 쓴다.** 제외 "Pregnant" → `pregnancy`/`exists`. PASS/FAIL로 뒤집는 것은 판정 단계 몫.
- **`administrative`는 true/false 필수**다 (null 금지). 시험 판정(6.1)이 이 값을 쓴다.
- **단위**: `unit`은 개념의 기본 단위나 `alt_units`로 변환 가능해야 한다. 예외: 상대 단위 `xULN`(환자 검사 줄의 참고 범위 상한으로 계산, 범위가 없으면 UNKNOWN/UNSUPPORTED + `lab_check`), `change: true`의 `%`·`fold`, 기본 단위가 없는 `lab_other`·`biomarker`(원문 단위 유지).

규칙만으로 나누기 어려운 경우:

- 제목이 없거나 "Key Inclusion Criteria", "Inclusion/Exclusion Step 1 Inclusion Criteria (Groups 1 and 2 only)", "Participants are excluded from the study if ..." 같은 변형 표현을 씀
- 글머리표가 중첩되거나 번호 목록을 씀 (하위 항목은 상위 항목의 조건으로 보고 하나로 묶음)
- 한 글머리표에 기준이 여러 개 → `.1`, `.2`로 분할
- "For participants in Korea:", "Phase Ib only:" 같은 소제목 아래 기준 → `cohort`에 소제목

`original_text` 정리 규칙 (`eligibility_text`는 원문 그대로 두고, ①에만 적용):

- 마크다운 이스케이프 해제: `\>` → `>`, `\<` → `<`, `\*` → `*`, `\_` → `_`
- 비교 기호 통일: `≥` → `>=`, `≤` → `<=`
- 위 첨자를 일반 표기로: `10⁹/L` → `10^9/L`, `m²` → `m^2`, `mm³` → `mm^3`
- 앞뒤 공백, 글머리표 기호(`*`, `-`, `•`), 원문 번호 제거

## 4. ② Patient Record 형식 (TREC·합성 담당)

환자 한 명 = 날짜와 출처가 붙은 문서 목록. 파일: `patients.jsonl`

```json
{
  "patient_id": "SYN-0007",
  "as_of": "2026-10-01",
  "nationality": "South Korea",
  "summary": "A 29-year-old woman presents with intermittent palpitations ...",
  "documents": [
    {"doc_id": "SYN-0007-D01", "type": "registration", "date": "2026-09-01", "author_role": "clerk", "text": "Female, DOB 1997-03-14."},
    {"doc_id": "SYN-0007-D02", "type": "lab_result", "date": "2026-09-03", "author_role": "lab", "text": "TSH <0.01 mIU/L; free T4 3.9 ng/dL."}
  ]
}
```

| 필드 | 설명 |
| --- | --- |
| `patient_id` | 변형을 드러내지 않는 일련번호. 합성 `SYN-0001`, TREC `TREC-{연도}-{토픽번호}` |
| `as_of` | 판정 기준일(등록 예정일). **v0.5: 필드는 환자마다 두고, 값은 데이터셋별로 고정한다.** 합성 세트 `2026-10-01`, TREC 세트 `2021-04-27`. 모든 시간 계산은 `as_of` 기준이며, 실행하는 날(오늘)을 쓰지 않는다 |
| `nationality` **(v0.5)** | 국적. ⓪ `countries`와 같은 표기(`"South Korea"`). 모르면 `null`. 등록 문서(`registration`) 본문에도 같은 내용을 적어 에이전트가 기록에서 읽을 수 있게 한다. 한국 기관 가중치(6.4)와 "국내 거주자" 같은 기준 판정에 사용 |
| `summary` | 대회 예시와 같은 1~2문장 요약. 대회 형식으로 내보낼 때 `title` |
| `documents[].type` | `registration` `clinic_note` `lab_result` `medication_record` `imaging_report` `pathology_report` `patient_interview` `discharge_summary` |
| `documents[].date` | 문서 작성일. 문서 안의 "5일 전" 같은 상대 날짜는 이 날짜 기준 |
| `documents[].author_role` | `physician` `nurse` `lab` `pharmacy` `patient` `clerk` |

입력 파일에는 정답·변형 정보를 넣지 않는다. 어떤 변형인지는 ④에만 기록한다. `patient_id` → 기본 환자 ID 대응표(`id_map*.json`)도 에이전트에 넘기지 않는다.

> **합성 세트**: 국적과 거주국 모두 한국으로 가정하고 전원 `"nationality": "South Korea"`. 등록 문서 끝에 `Nationality: South Korea.`를 붙였다 (끝에 붙여 기존 근거 위치는 그대로). 국적 기준은 3단계에서 별도 변형으로 시험한다.

## 5. ③ Evidence 형식 (Agent 2 출력)

근거 하나당 객체 하나.

```json
{
  "evidence_id": "SYN-0007-EV03",
  "patient_id": "SYN-0007",
  "concept": "free_t4",
  "value": 3.9,
  "unit": "ng/dL",
  "value_type": "numeric",
  "observed_date": "2026-09-03",
  "certainty": "confirmed",
  "subject": "patient",
  "source": {
    "doc_id": "SYN-0007-D02",
    "doc_type": "lab_result",
    "author_role": "lab",
    "span": [17, 34],
    "text": "free T4 3.9 ng/dL"
  },
  "extracted_by": "rule"
}
```

| 필드 | 값 | 설명 |
| --- | --- | --- |
| `value_type` | `numeric` `boolean` `categorical` `date` | 이력 유무는 `boolean` |
| `observed_date` | ISO 날짜 또는 `null` | 검사·투약이 실제로 일어난 날. 날짜를 알 수 없으면 `null` (TREC 규칙은 8장) |
| `certainty` | `confirmed` `reported` `suspected` | 환자 진술은 `reported` |
| `subject` **(v0.5)** | `patient` `family` | 누구에 대한 사실인지. 가족력("어머니 유방암")도 근거로 추출하되 `family`로 표시. "가족력 있음" 기준은 `family` 근거로, 환자 본인 질환 기준은 `patient` 근거로만 판정 |
| `source.span` | `[시작, 끝]` | 문서 `text` 안의 문자 위치 (끝은 포함하지 않음) |
| `extracted_by` | `rule` `llm` | 오류 분석용 |

기록에 명시적으로 "없다"고 적힌 경우만 `false` 근거를 만든다. 언급이 없으면 근거를 만들지 않는다.

### 5.1 선택 필드 (v0.5, 에이전트 2 구현에서 추가)

에이전트 3이 판정 규칙(6.3)을 지키는 데 필요한 정보라 선택 필드로 둔다. 없으면 생략한다.

```json
{"concept": "diagnosis", "value": true, "certainty": "suspected",
 "term": "minimal change disease",
 "detail": {"status": "current", "start": null, "quote": "presumed minimal change disease"}}
```

| 필드 | 값 | 설명 |
| --- | --- | --- |
| `term` | 문자열 | 일반 개념(`diagnosis`, `medication`, `procedure`, `symptom_finding`, `lab_other`, `treatment_plan`, `social_history`)에서 구체적으로 무엇인지. 예: `diagnosis` + `"minimal change disease"`. ①-b 공식 개념 키로 바뀌면 줄어든다 |
| `detail.status` | `observed` `current` `past` `stopped` `planned` `declined` | 측정·소견 / 진행 중인 질환·복용 중인 약 / 과거·완료 / 중단 / 계획·논의·권고 / 환자 거부. **`planned`·`declined`는 시행 이력이 아니다** (6.3 "논의·계획은 받은 치료가 아니다") |
| `detail.start` | ISO 날짜 또는 `null` | 지속 중인 약·질환의 시작일 ("since 2019" → `2019-01-01`). `observed_date`와 다름 |
| `detail.quote` | 문자열 | `source.text`(문장·줄 단위) 안에서 이 사실에 해당하는 정확한 부분 |
| `detail.comparator` | `<` `>` `<=` `>=` | `"<0.01"` 같은 값의 부등호 |
| `detail.derived_from` | 문자열 | 코드로 계산한 값의 출처 (예: 생년월일 → 나이, `as_of` 기준) |

권고·지시 문장의 처리: 계획 부분에 쓰인 "no smoking", "avoid alcohol", "no contact sports" 같은 권고는 환자의 상태가 아니므로 해당 행동 개념(`smoking` 등)으로 만들지 않고 `treatment_plan`(`status: planned`)으로 만든다. 처방 지시("Start prednisolone 60 mg daily")는 `medication` + `current`.

과거 습관은 `value: true` + `detail.status: past`로 만든다("Ex-smoker", "quit 2020", "abstinent from smoking since 2020"). `false`는 "한 적 없음"이다. "Alcohol use disorder: abstinent since 09-25"는 진단(`current`)과 음주(`past`) 두 근거로 나눈다. 받은 적 없는 치료는 `medication`/`procedure` `false`로 만든다("Denies any prior systemic therapy" → `medication` `false`, `term: "prior systemic therapy"`).

`social_history`: 직업, 보호자, 동거인, 방문 가능 여부("Works as a nurse", "Guardian: mother.", "Willing to travel to Seoul for study visits."). 보호자·간병인·직업 노출·거주 기준에만 쓴다.

### 5.2 갱신 출력 (v0.5 추가, 에이전트 2 → 에이전트 3)

에이전트 4·5의 새 정보로 기록이 바뀌면(새 문서, 드물게 수정·삭제) 에이전트 2는 바뀐 문서만 다시 추출한다.

- 바뀌지 않은 근거는 `evidence_id`를 유지한다. 수정된 문서에서도 같은 사실(문장, 개념, `term`, 값, `subject`, `certainty`)이 다시 나오면 옛 ID를 유지한다.
- 새 근거는 다음 번호를 받는다. 한 번 쓴 ID가 다른 근거를 가리키는 일은 없다.
- 생년월일로 계산한 나이는 `as_of`가 바뀌면 같은 ID로 값만 바뀐다.

환자마다 `changes.jsonl`에 한 줄:

```json
{"patient_id": "SYN-0002", "docs": {"new": ["SYN-0002-D99"], "changed": [], "removed": []},
 "added": ["SYN-0002-EV188"], "removed": [], "changed": [], "moved": [],
 "added_concepts": ["alcohol"], "removed_concepts": []}
```

에이전트 3은 `removed`·`changed` ID를 근거로 쓴 기준과 `added_concepts`에 해당하는 기준만 다시 판정한다. `moved`(문서 안 위치만 바뀜)는 다시 판정하지 않는다.

## 6. ④ Gold 형식 (TREC·합성 담당)

환자-시험 쌍 하나당 객체 하나. 파일: `gold.jsonl`

```json
{
  "patient_id": "SYN-0009",
  "trial_id": "NCT01234567",
  "base_id": "S002",
  "variant": "expired",
  "as_of": "2026-10-01",
  "label_source": "human_verified",
  "trial_label": "potential",
  "criteria": [
    {
      "criterion_id": "NCT01234567-I02",
      "expected_status": "UNKNOWN",
      "reason": "EXPIRED",
      "supporting_evidence": ["G03"],
      "decoy_evidence": [],
      "expected_action": "lab_check",
      "review": "human"
    }
  ],
  "gold_evidence": [
    {"gold_ev_id": "G03", "concept": "free_t4", "value": 3.9, "unit": "ng/dL", "observed_date": "2026-06-20", "doc_id": "SYN-0009-D02", "span": [17, 34], "text": "free T4 3.9 ng/dL"}
  ],
  "injection": {"type": "EXPIRED", "target_criterion": "NCT01234567-I02", "note": "lab date moved 82 days before as_of; window 30 days"}
}
```

| 필드 | 값 | 설명 |
| --- | --- | --- |
| `label_source` | `generated` `llm` `human_verified` `trec_qrels` | 채점에는 `generated`, `human_verified`, `trec_qrels`만 사용 (6.2) |
| `trial_label` | `eligible` `potential` `ineligible` | 시험 단위 판정 (6.1) |
| `criteria` | 기준 목록 | 환자의 코호트에 해당하는 기준만. 다른 코호트 기준은 빠짐 |
| `expected_status` | `PASS` `FAIL` `UNKNOWN` `CONFLICT` | 기준 단위 판정 |
| `reason` | `VALID` `VIOLATED` `MISSING` `EXPIRED` `UNSUPPORTED` `CONFLICT` | PASS→VALID, FAIL→VIOLATED, CONFLICT→CONFLICT, UNKNOWN→MISSING/EXPIRED/UNSUPPORTED |
| `supporting_evidence` | `gold_ev_id` 목록 | 판정에 쓰여야 하는 근거. PASS, FAIL, CONFLICT, UNKNOWN(EXPIRED·UNSUPPORTED)에는 필수. UNKNOWN(MISSING)은 비움 |
| `decoy_evidence` | `gold_ev_id` 목록 | 근거로 쓰면 안 되는 미끼 |
| `expected_action` | `patient_question` `med_record_check` `lab_check` `med_history_check` `clinician_confirmation` `new_test` `none` | PASS·FAIL은 `none`, UNKNOWN·CONFLICT는 `none`이 아닌 값 |
| `review` **(v0.5)** | `human` `agreed` `llm` | 기준 단위 출처. `human`: 사람이 검수. `agreed`: LLM 두 번의 판정이 일치하고 확인 표시가 없어 그대로 인정. `llm`: 아직 검수 전. `label_source`는 그대로 두고 분석용으로만 씀 (예: `human` 기준만으로 채점) |
| `base_id`, `variant` | 기본 환자 ID, `base` `violation` `missing` `expired` `conflict` `unsupported` | TREC는 `base_id: null`, `variant: "base"` |
| `injection` | 객체 또는 `null` | 변형에서 무엇을 바꿨는지 |

`gold_evidence`의 `concept`·`value`·`unit`은 ①-b와 `concepts.json`이 준비되면 채운다 (`fill_gold_evidence.py`). 수치는 개념의 기본 단위로 변환해 저장하고, 질환·약물·시술은 `true`/`false`(명시적 부정은 `false`)로 저장한다. 바구니 개념에는 `term`(기록 표기), 모든 근거에 `status`(③ `detail.status`와 같은 값)를 붙인다. 가족에 대한 사실이면 `"subject": "family"`를 붙인다 (③과 같은 뜻). 채우기 전에는 `null`. 점수 "23/30"은 23, 등급 "III"은 3, 범위 "5-7"은 6, 정성 결과("not detected", "trace")는 단어 그대로 저장한다.

```json
{"gold_ev_id": "G04", "concept": "diagnosis", "term": "acute pancreatitis", "value": true, "unit": null, "status": "past",
 "observed_date": "2026-08-10", "doc_id": "SYN-0007-D02", "span": [0, 42], "text": "..."}
```

TREC 세트처럼 기준 단위 정답이 없는 쌍은 `criteria: []`로 두고 `trial_label`만 채점한다.

### 6.1 시험 판정 규칙 (v0.5 확정)

기준 판정에서 시험 판정을 계산하는 규칙. 정답 생성(`gold_lib.trial_label`)과 에이전트 출력 채점에 같은 규칙을 쓴다. TREC 평가자의 판정 방식에 맞췄다.

| 순서 | 조건 | 시험 판정 |
| --- | --- | --- |
| 1 | FAIL이 하나라도 있음, 또는 나이·성별이 ⓪ `min_age`·`max_age`·`sex` 범위 밖 | `ineligible` |
| 2 | 선정 기준(I, U) 중 UNKNOWN 또는 CONFLICT가 있음. 단 **행정 항목(`administrative: true`)의 UNKNOWN/MISSING은 제외** | `potential` |
| 3 | 제외 기준(E) 중 CONFLICT, 또는 UNKNOWN/EXPIRED, UNKNOWN/UNSUPPORTED가 있음 | `potential` |
| 4 | 그 밖 | `eligible` |

- 제외 기준의 UNKNOWN/MISSING(기록에 전혀 언급이 없음)은 시험 판정을 막지 않는다. "그런 병이 있다는 기록이 없다"를 "없다"로 보는 TREC 평가 방식과 같다. 기준 단위에서는 UNKNOWN으로 남아 정보 획득 대상이 된다.
- 행정 항목 선정 기준(동의서 등)이 기록에 없어도 판정을 막지 않는다. 기록으로는 원래 알 수 없는 항목이기 때문이다.
- 검수자는 `review.csv`의 `admin` 열로 행정 항목 표시를 고칠 수 있고, 시험 판정은 고친 값으로 다시 계산된다.

### 6.2 `label_source`의 뜻

| 값 | 뜻 |
| --- | --- |
| `generated` | 변형(7장)으로 만든 정답. 바꾼 기준은 규칙으로 정해지고, 나머지는 원래 쌍의 정답을 물려받음 |
| `llm` | LLM 판정만 있고 사람 검수를 끝내지 않음. **채점에 쓰지 않음** |
| `human_verified` | 확인이 필요한 기준을 사람이 모두 검수했고, 나머지 기준은 LLM 두 번의 판정이 일치해 그대로 인정한 정답. 확인이 필요한 기준은 (1) 두 판정이 다르거나 근거 인용에 문제가 있는 기준, (2) 어느 한 번이라도 FAIL인 기준, (3) 두 번의 시험 판정이 달랐던 쌍의 모든 기준. 검수자가 "모르겠음(의료진 확인)"으로 표시한 기준이 남아 있으면 `human_verified`가 되지 않음 |
| `trec_qrels` | TREC 공식 평가자 판정 |

기준 단위로는 `review` 필드로 구분한다. 합성 세트 현황 (2026-10-27): dev 54쌍(dev_v10), test 90쌍(test_v9) 모두 `human_verified`. 시험 판정 dev eligible 5 / potential 15 / ineligible 34, test 9 / 30 / 51 (둘 다 처음 검수 때와 같음. test_v7의 검사 최근성 7행은 새 검사 보고서를 옛 값으로 묶은 착오라 test_v9에서 되돌림).

### 6.3 기준 판정 규칙 (정답 달기 프롬프트와 검수에 공통)

- **기록에 근거해서만 판정한다.** 제외 조건이 언급되지 않았으면 "없다"로 가정하지 않고 UNKNOWN/MISSING.
- **명시적 부정은 근거다.** "No prior malignancy", "NKDA"처럼 기록이 직접 부정하면 PASS/VALID와 그 문장을 근거로.
- **논의·계획은 받은 치료가 아니다.** "Options discussed", "plan to start", "consider"는 시행 이력이 아니다.
- **오래된 결과**: 기준에 기간이 없어도 "현재 상태"를 묻는 기준이면 `as_of` 기준 검사는 30일, 영상은 90일이 넘으면 UNKNOWN/EXPIRED. 기준에 기간이 있으면 그 기간을 따른다. 날짜는 측정일로 센다: 값 옆에 날짜가 적혀 있으면("eGFR 59 on 8/5", "HbA1c 5.9% (6/2026)") 그 날짜, 없으면 그 값이 실린 검사 문서(`lab_result`, `imaging_report` 등 검사 보고서)의 날짜. 진료 기록에 이전 결과를 옮겨 적은 값은 측정일을 바꾸지 않는다(처음 기록된 날짜). 같은 값이라도 새 검사 보고서에 다시 나오면 새로 잰 값이다 (2026-10-25 명시, 2026-10-27 보완: 값이 같다는 이유로 새 검사를 옛 검사로 묶지 않는다).
- **판단 표현**: "clinically significant", "adequate", "investigator's opinion"처럼 의사 판단이 필요한 표현은, 기록에 해당 질환·상태가 직접 적혀 있지 않으면 UNKNOWN/UNSUPPORTED + `clinician_confirmation`. 관련 기록이 전혀 없으면 UNKNOWN/MISSING.
- **정상 범위가 적히지 않은 검사 기준**: 기준에 수치가 없으면 검사지의 참고 범위로 판정한다.
- **의심은 진단이 아니다.** "suspected", "possible", "features of", 검사 중인 진단은 확진이 아니므로, 그 진단을 요구하는 기준은 UNKNOWN/UNSUPPORTED.
- **적히지 않은 것은 추론하지 않는다.** 미래의 ICU 필요, 계획된 치료의 결과, 아무도 매기지 않은 중증도 등으로 판정하지 않는다 (UNKNOWN).
- **선택지 목록 조각**: 파서가 선택지 목록을 쪼개 "Hormone receptor status not specified"처럼 선택지 하나만 남은 줄은, 환자가 다른 선택지에 해당한다는 이유로 FAIL하지 않는다. 이웃 줄에서 허용된 선택지에 맞으면 PASS, 아니면 UNKNOWN/UNSUPPORTED.
- **불가능한 조건**: 남성 환자의 임신 기준처럼 해당 환자에게 성립할 수 없는 제외 조건은 PASS/VALID (근거: 성별·나이 문서).
- **근거 인용**: 한 문서에서 글자 그대로 연속된 짧은 문장. "..."로 줄이지 않는다.
- **판정 시점** (2026-10-08, A4): 기준 문구에 시점("at presentation", "at diagnosis")이 없으면 `as_of` 기준 현재 값으로 판정한다. 같은 쌍의 기준끼리 시점을 섞지 않는다.
- **"계획됨" 기준인데 이미 시행함** (2026-10-08, A5): "PPV is planned"처럼 앞으로 할 치료를 요구하는데 기록상 이미 시행했으면 UNKNOWN/UNSUPPORTED + `clinician_confirmation`.
- **행정 항목의 행동** (2026-10-08, B1): 동의·참여 의지는 `patient_question`, "investigator's judgment"는 `clinician_confirmation`.
- **(제안, 회의 확정 대기) 여러 항목을 나열한 기준** (A3): "ALT 또는 AST > 3×ULN, 또는 CK > 5×ULN"처럼 나열한 항목 중 하나라도 확인되지 않으면 UNKNOWN.
- **"other"는 시험 대상 질환을 뺀 것** (2026-10-06 추가): 만성 편두통 시험의 "cluster headache or other primary headaches"는 편두통 자체를 뜻하지 않는다. 대상 질환이 있다는 이유로 FAIL하지 않는다.
- **(제안, 팀 확인 필요) 장기계 일괄 부정**: "No other cardiac, pulmonary, hepatic, renal, autoimmune or neurologic history"는 그 계통 만성 질환의 병력·진단 기준에 대한 명시적 부정(PASS/VALID). 검사 수치, 기간 안의 급성 사건, 약물, 시술, 감염, 연구자 판단 기준에는 적용하지 않는다.
- **(제안, 팀 확인 필요) 목록에서 추론한 "없음"**: 정리된 투약 목록이나 치료 이력에 없다는 이유만으로 한 판정은 정답에서 UNKNOWN/MISSING으로 두고, 채점 때 PASS도 허용하는 관대 점수를 함께 보고한다 (점검표의 `3_inferred` 행). 확정되면 지금 정답에 남아 있는 목록 추론 PASS(Agent 2 분석상 dev 약 24행: 투약 목록 10, 정상 검사치로 "질환 없음" 14)도 같은 방식으로 정리한다.
- **출처가 다른 기록끼리 엇갈리면 CONFLICT** (2026-10-23 추가): 외부 기록·다른 병원·약국·의뢰서가 다른 문서의 진술이나 "없음"과 반대되는 진단·치료·알레르기·결과를 적었으면, 한쪽이 더 구체적이어도 어느 쪽이 맞는지 정하지 않고 CONFLICT / `clinician_confirmation`. 바뀔 수 있는 측정값(검사·활력징후·영상)만 최근 값이 이전 값을 대신한다.

### 6.4 추천 순위 정답

환자 단위. 파일: `ranking_gold.jsonl`

```json
{"patient_id": "SYN-0007", "as_of": "2026-10-01", "ranking": ["NCT01234567", "NCT07654321"], "stale_trials": ["NCT07654321"], "dropped_stale_trials": [], "label_source": "human_verified"}
```

`ranking`에는 `eligible`, `potential` 시험만 넣는다. 정렬 순서 (앞 조건이 우선):

1. `eligible`이 `potential`보다 앞
2. **모집 상태 확인 시기 (v0.5)**: 같은 판정 안에서 `status_verified`가 `as_of` 기준 12개월을 넘은 시험은 맨 뒤로
3. 같은 판정 안에서 UNKNOWN·CONFLICT 기준이 적은 시험
4. **한국 기관 가중치 (v0.5)**: 같은 판정 단계 안에서 `kr_recruiting: true`인 시험을 앞으로. 판정 단계를 넘어서 올리지는 않음 (`potential`인 국내 시험이 `eligible`인 해외 시험보다 앞서지 않음)
5. `overall_status`가 `RECRUITING`인 시험이 `NOT_YET_RECRUITING`보다 앞
6. `status_verified`가 최근인 시험

모집 상태 확인 시기 규칙 (v0.5):

| `as_of` 기준 경과 | 처리 | `ranking_gold.jsonl` 필드 |
| --- | --- | --- |
| 12개월 이하 | 그대로 | |
| 12개월 초과 ~ 24개월 이하 | 같은 판정 단계 안에서 맨 뒤로. 브리핑에 "모집 상태가 오래 확인되지 않음" 표시 | `stale_trials` |
| 24개월 초과 | 추천에서 제외 (`ranking`에 넣지 않음). 시험 판정(④ `trial_label`)은 그대로 둠 | `dropped_stale_trials` |

근거: 합성 세트 수집 551개 중 12개월 초과 29개(5%), 라벨 대상 144개 중 4개.

`label_source`는 그 환자의 모든 쌍이 `human_verified`일 때만 `human_verified`.

## 7. 변형(문제 주입) 규칙

기본 환자 1명에서 변형 5개를 만들고, 변형마다 문제를 딱 하나만 심는다.

| 변형 | 만드는 방법 | 대상 기준 기대 판정 | 기대 행동 |
| --- | --- | --- | --- |
| `base` | 문제 없음 | 2단계 정답 그대로 | |
| `violation` | 근거 값 하나를 기준 위반 값으로 변경 | FAIL / VIOLATED | `none` |
| `missing` | 근거가 담긴 문장 또는 문서를 삭제 | UNKNOWN / MISSING | `answerable_by`에 따름 |
| `expired` | 검사 날짜를 `time_window` 밖으로 이동 (값은 그대로) | UNKNOWN / EXPIRED | `lab_check` 또는 `new_test` |
| `conflict` | 다른 출처의 반대 기록을 추가 | CONFLICT / CONFLICT | `clinician_confirmation` |
| `unsupported` | 진짜 근거를 지우고, 관련은 있지만 입증하지 못하는 미끼를 추가 | UNKNOWN / UNSUPPORTED | `answerable_by`에 따름 |

- 대상 기준은 2단계에서 PASS로 확인되고(`human_verified`) `parse_status`가 `structured`이며 `administrative: false`인 기준 중에서 고른다. `expired`처럼 `time_window`가 필요한 변형은 ①-b가 있어야 만들 수 있다.
- `expired`는 `time_window`가 있는 기준, `conflict`·`unsupported`는 `exists`/`not_exists` 기준이 적합하다.
- 바꾼 문서 외의 문서는 글자 하나 바꾸지 않는다.
- 변형은 기본 환자와 같은 쪽(dev/test)에 둔다.
- 국적·거주 기준("Thai National", "국내 거주자")은 `violation` 변형으로 `nationality`와 등록 문서의 국적 문장을 바꿔 시험한다.

## 8. 공통 규칙

- **파일**: UTF-8, 여러 건은 JSONL(한 줄에 한 객체). 날짜는 `YYYY-MM-DD`. 필드 이름은 영어 snake_case.
- **기준일**: 시간 계산은 모두 `as_of` 기준. "14일 이내" = `as_of - observed_date <= 14`일. 실행하는 날짜를 쓰지 않는다.
- **날짜 없는 문장**: 대회 예시처럼 날짜가 없는 "presents with ..." 문장은 `as_of` 당일 관찰로 본다.
- **제외 기준의 PASS/FAIL**: 상태는 "이 기준 때문에 등록할 수 있는가"를 뜻한다. 제외 기준 "임신 중"에서 임신이 아니면 PASS, 임신이면 FAIL.
- **개념 키**: `concepts.json` 하나를 팀이 같이 관리한다. 새 개념은 여기에 먼저 추가하고, `check_concepts.py`로 검사한다. 형식:

```json
[{"key": "free_t4", "name": "Free thyroxine", "type": "lab", "unit": "ng/dL",
  "code": {"system": "LOINC", "code": "3024-7"}, "aliases": ["FT4", "free T4"], "alt_units": {"pmol/L": 0.0777}}]
```

`type`: `lab` `vital` `measurement` `drug` `condition` `procedure` `demographic` `behavior` `other`. `code.system`: `LOINC`(검사) `RxNorm`(약물) `SNOMED CT` 또는 `ICD-10`(진단). `aliases`(기록에 쓰이는 다른 이름)와 `alt_units`(다른 단위 → 기본 단위로 곱할 값)는 선택.
- **단위**: 개념마다 기본 단위를 하나 정하고, 다른 단위는 판정 전에 변환한다. 상대 단위(xULN)와 변화량 단위는 3장 규칙을 따른다.
- **개념 사전**: 현재 `concepts.json`(137개, CT.gov 담당 ①-b와 함께 전달). Agent 2의 조정(추가 표기, `alt_units`)은 덮어쓰지 않고 `concepts_agent2.json`에 따로 둔다.
- **ID**: 문서 `{patient_id}-D01`, 근거 `{patient_id}-EV01`, 기준 `{NCT}-I01`/`{NCT}-E01`/`{NCT}-U01`(분할 시 `{NCT}-I01.1`), 정답 근거 `G01`.
- **시험 데이터 갱신**: 같은 시험을 다시 받으면 `fetched_at`을 갱신하고, `eligibility_text`가 바뀌었으면 ①과 해당 시험의 ④를 다시 만든다.
- **채점 범위**: ④가 있는 쌍만 채점한다. 에이전트가 후보 풀(`pool_trial_ids`) 시험을 추천해도 정답·오답으로 세지 않는다 (unjudged). 순위 지표는 judged 시험만으로 계산하고, unjudged 비율을 함께 보고한다.
- **대회 형식 내보내기**: `summary`를 `{"topics": [{"num": patient_id, "title": summary}]}`로 내보낸다.
- **TREC 변환**:
  - 환자 설명은 `clinic_note` 문서 하나(날짜 = `as_of` = `2021-04-27`).
  - qrels 2 → `eligible`, 1 → `ineligible`, 0 → 채점 제외. `label_source: "trec_qrels"`. 기준 단위 정답은 TrialGPT 주석이 있는 쌍에만 단다.
  - **v0.5 날짜 처리**: TREC 본문의 날짜는 가려져 있거나(`[**2101-3-4**]` 형태) 비현실적인 값(먼 미래·과거)인 경우가 있다. 이런 날짜에서 나온 근거는 `observed_date: null`로 두고, 기간 기준은 날짜 없는 문장 규칙(`as_of` 당일)을 적용한다. 실제 날짜로 고쳐 쓰지 않는다.
- **출처 기록**: 생성 방법(모델, Synthea 버전, 시드)과 데이터 출처·라이선스를 `generation_meta.json`에 남긴다.

## 9. 검수 시트 `review.csv` (v0.5)

`label_gold.py`가 만들고, 검수 화면(정답 검수실)에서 내보내며, `apply_review.py`가 읽는다. 기준 하나당 한 줄, UTF-8 BOM.

| 열 | 채우는 쪽 | 설명 |
| --- | --- | --- |
| `patient_id` `base_id` `trial_id` `trial_title` `criterion_id` `type` `cohort` `original_text` | 스크립트 | 식별 정보 |
| `admin` | 스크립트, 검수자 | 행정 항목이면 `Y`. 검수자가 바꾸면 시험 판정에 반영 |
| `trial_label_llm` `trial_label_llm2` `cohort_assignment` | 스크립트 | 1·2차 시험 판정, LLM이 정한 코호트 |
| `check` | 스크립트 | `CHECK runs differ`, `CHECK quote/auto-fill` 등. 비어 있으면 1·2차 일치 |
| `llm_*`, `llm2_*` | 스크립트 | 1·2차의 상태·이유·행동·근거·설명 |
| `review_status` | 검수자 | `OK`(1차 그대로) `PASS` `FAIL` `UNKNOWN` `CONFLICT` `N/A`(해당 코호트 아님). 비우면 미검수 |
| `review_reason` | 검수자 | UNKNOWN일 때만 `MISSING` `EXPIRED` `UNSUPPORTED` |
| `review_action` | 검수자 | UNKNOWN·CONFLICT일 때 행동. 비우면 1차 행동 (1차가 `none`이면 반드시 채움) |
| `review_evidence` | 검수자 | `doc_id: 인용` 형식. 여러 개는 세로 막대로 구분. 비우면 LLM 근거 유지 |
| `review_note` | 검수자 | 메모. `gold_review_log.jsonl`에 남음 |
| `review_flag` | 검수자 | `clinician` = 검수자가 판단하지 못해 의료진 확인이 필요함 ("모르겠음" 버튼). 이 표시가 남은 쌍은 `human_verified`가 되지 않음. 확인 후 지운다 |

심판 LLM 의견(`adjudication.jsonl`)은 검수 화면에만 보여 주며 `review.csv`에는 들어가지 않는다. 검수자가 "심판 채택"을 누르면 그 값이 `review_*` 열에 들어간다.

## 10. 팀 결정 사항

- [x] ①-b는 CT.gov 담당이 채운다. 기준 ID는 `ctgov_v1/criteria.jsonl` 것을 유지 (3장)
- [x] 한국 기관 가중치: ⓪ 컬럼(`kr_recruiting`, `kr_sites`) + 같은 판정 단계 안에서 순위 조정 (6.4)
- [x] `as_of`: 필드는 환자마다, 값은 데이터셋별 고정 (합성 2026-10-01, TREC 2021-04-27)
- [x] 국적: ② `nationality` 필드 + 등록 문서 본문. 합성 세트는 전원 `"South Korea"` (국적·거주국 모두 한국 가정)
- [x] 가족력: ③ `subject: "family"`로 근거에 포함
- [x] TREC 가려진 날짜: `observed_date: null`
- [x] 후보 풀 시험: 채점 제외 (unjudged)
- [x] 오래 확인되지 않은 시험: 12개월 초과는 같은 판정 안에서 맨 뒤 + 브리핑 경고, 24개월 초과는 추천 제외 (6.4)
- [x] 사람 검수와 두 번 일치 인정 구분: `label_source`는 그대로, 기준마다 `review: "human" | "agreed"` (6장)
- [x] `concepts.json` 코드 검증: 합성 담당이 검사 (2026-10-09). LOINC 51개 모두 공식 이름과 일치, 남은 단위 오류 2건(`NCT07655700-I03` 발작 횟수 ↔ 편두통 일수, `NCT07594145-I07` UACR 단위 오타)은 CT.gov 담당에 수정 요청
  - 역할: CT.gov 담당이 ①-b를 채우며 개념 추가, 합성 담당이 코드 검증 (교차 확인)
  - 검증 방법: `check_concepts.py`로 키·코드 형식·검증 숫자(LOINC mod 10, SNOMED CT Verhoeff)·단위 검사, `--online`으로 LOINC·RxNorm·ICD-10 공식 이름 대조
- [x] TREC 정답(qrels → ④) 변환: TREC 담당 완료 (11,589쌍, `trec_qrels`)
- [ ] 장기계 일괄 부정 규칙과 목록 추론 관대 점수 (6.3 제안)
  - 근거: 놓친 사실 점검에서 dev 38행·test 34행이 일괄 부정으로 판정 가능. 반영해도 시험 판정은 바뀌지 않음
  - 확정되면 dev·test 정답에 `--tiers 1_explicit 2_blanket`로 반영
  - 함께 정할 것 (Agent 3 v1 회의): 목록 추론으로 PASS가 된 기존 정답 행(dev 약 24행)을 UNKNOWN + 관대 목록으로 정리할지, NKDA를 "특정 약 알레르기 없음"으로 인정할지(4행, 지금은 PASS)
- [ ] Agent 3 v1 회의 안건 (2026-10-08~09)
  - 확정 반영: A4 판정 시점, A5 "계획됨"인데 이미 시행, A6 OR 선택지 조각(정답 수정), B1 행정 항목 행동 (6.3)
  - 결정 대기: A1·A2 (위 항목), A3 여러 항목 나열 기준 (6.3 제안), D2 "정답 eligible 재현율" 지표 추가
  - 행정 항목 하나: `NCT07018323-I04` "Other, more specific inclusion criteria are defined in the protocol"을 행정 항목으로 보면 SYN-0020 × NCT07018323이 potential → eligible (정답 eligible 5 → 6). 합성 담당 의견은 행정 항목
- [ ] ①-b 수정 요청 (CT.gov 담당, test 전달 때 dev 수정본도 함께)
  - `administrative` null 2,711줄을 true/false로
  - 여러 줄 선택지를 같은 `logic_group`으로 연결 (지금은 그룹 1,508개가 모두 기준 하나씩)
  - 단위 오류 2건 (위 개념 코드 검증 항목)
  - 검토 메모: `docs/ctgov_request/REVIEW_1b_dev_v1.md`
- [ ] LLM 라벨러를 TREC 세트(TrialGPT 주석)로 검증할 때 합격 기준
  - 참고 수치 (TrialGPT, Jin et al., Nature Communications 2024): 의사 3명이 환자 53명·환자-시험 105쌍에서 기준 1,015개를 주석. TrialGPT(GPT-4) 기준 단위 정확도 87.3% (선정 89.9%, 제외 85.9%), 전문가 정확도 88.7~90.0%. 시험 단위는 부적합 시험 걸러내기 AUROC 0.798, 순위 NDCG@10 0.728
  - 제안: 기준 단위는 TrialGPT 주석과 일치율 87% 이상 (선정·제외 따로 보고). 시험 단위는 qrels(적합/부적합)와 Cohen's κ 0.6 이상 (논문에 κ가 없어 팀 자체 기준)
  - 1차 결과 (2026-10-06, TREC 2021 표본 100쌍: eligible 50 / excluded 50, gpt-oss-120b 두 번 판정):
    - "확인 필요"를 뺀 κ 0.42 (2차 판정 0.46), 정확도 74~76%. 우리 판정의 39%가 "확인 필요" (TREC 정답에는 없는 값)
    - TREC 제외인데 우리가 적합: 50쌍 중 2쌍 (4%). 부적합한 시험을 적합으로 추천하는 오류는 드묾
    - TREC 적합인데 우리가 부적합인 14쌍을 읽어 보니: 기록상 우리 판정이 맞아 보이는 경우 약 9 (예: 보르테조밉 투여 이력, FEV1 60%, 원격 전이), 라벨러 오류 2 (의심 진단을 탈락 처리, 기록에 없는 ICU 필요 추론), 기준 분할 문제 1, 애매 2
    - 해석: TREC 평가자는 시험 단위로 너그럽게, 우리 라벨러는 기준마다 엄격하게 판정해 κ가 낮게 나옴. 실제 라벨러 오류는 일부
    - 조치: 판정 규칙 3개 추가 (6.3: 의심 진단, 추론 금지, 선택지 목록 조각) 후 같은 100쌍 재실행 (2026-10-06)
    - 재실행 결과: κ 0.43 (2차 0.44), 정확도 75~76%, TREC 제외인데 우리가 적합 3쌍·2쌍 (6%·4%). 의심 진단·ICU 추론 두 오류는 "확인 필요"로 바로잡힘. 선택지 목록 조각은 그대로 → 프롬프트가 아니라 기준 분할(에이전트 1)에서 고칠 문제. 그 밖의 변화는 1·2차 판정 사이 차이(약 10%) 수준
    - 결론: κ 차이는 라벨러 오류보다 판정 방식 차이(TREC는 시험 단위로 너그럽게, "확인 필요" 없음)에서 옴. 시험 단위 κ를 합격 기준으로 쓰지 않는 수정 제안 유지
  - 기준 단위 결과 (2026-10-06, TrialGPT 전문가 주석 1,014개, 환자 53명·105쌍, gpt-oss-120b 두 번 판정):
    - 같은 데이터로 계산한 GPT-4 정확도 0.873 (논문 값과 일치 → 라벨 대응이 맞음을 확인)
    - 우리 라벨러, 우리 규칙 그대로(언급 없는 제외 조건 = 정보 부족): 정확도 0.45 (선정 0.79, 제외 0.26)
    - 언급 없는 제외 조건을 "not excluded"로 읽으면: 0.757 / 2차 0.745 (선정 0.79, 제외 0.74)
    - **반대 방향 오류** (전문가 적합 ↔ 우리 탈락 또는 그 반대): 1,014개 중 5개 (0.5%). 둘 다 확정 판정한 174개 중에서는 97% 일치. 5개 중 3개는 "significant disease" 같은 판단 표현을 탈락 처리한 것(6.3 규칙 위반), 1개는 동의서를 탈락 처리한 것, 1개는 반대로 전문가가 미충족으로 본 선정 기준("인플루엔자를 시사하는 임상 양상")을 우리가 충족으로 본 것
    - 차이의 대부분은 보수성: 전문가가 확정한 것을 우리가 "정보 부족"으로 둔 경우 (선정 기준 included → 정보 부족 41개 중 34개가 MISSING). 일부는 기록에 있는데 놓친 진짜 누락 (예: "known to have hypertension"을 못 찾음), 나머지는 전문가가 추론으로 채운 것 (예: 성인이면 "체중 5 kg 이상" 충족)
    - 제외 기준의 판정 방식 차이: TrialGPT 전문가는 언급 없는 제외 조건을 대부분 "not excluded"로 봄 (우리 규칙은 UNKNOWN/MISSING. 시험 판정 6.1에서는 막지 않으므로 시험 단위 결과는 같음)
    - 참고: 다른 팀(ClarifyTrial) 발표의 자유문장 판정 79.1% (일부 표본, 판정 방식 다름)
  - 수정 제안 (합격 기준):
    - 필수: 반대 방향 오류 1% 이하 (현재 0.5%, 통과). 시험 단위로는 "TREC 제외인데 우리가 적합" 5% 이하 (현재 4~6%)
    - 참고 지표: TrialGPT 대응 정확도(언급 없는 제외 = not excluded)와 TREC κ는 판정 방식 차이가 커서 합격선으로 쓰지 않고 함께 보고
    - 개선 과제: 선정 기준에서 기록에 있는 사실을 놓치는 누락, 판단 표현 탈락 금지 규칙 준수 (최종 에이전트 3에서 확인)
  - 참고: 합성 세트에서 라벨러 1·2차 자체 일치율 85%. 미달 시 사람 검수 범위 확대 (1·2차 일치 기준도 일부 표본 검수)
