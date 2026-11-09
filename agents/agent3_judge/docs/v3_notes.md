# Agent 3 v3 작업 메모 (2026-10-25, 오전 중간 메모 — 최종은 `v3_report.md`)

> 이 문서는 p08 작업 중의 중간 기록입니다. 최종 결정(p07 유지, p08~p10 미채택)과 수치는 `docs/v3_report.md`를 보세요.

코드 `a3-0.3.0-dev`, 프롬프트 `p08`, 데이터 `for_agent3_v7`(정답 dev_v7) + Agent 2 키트 v14.7.
4차 회의(10/23) "1단계: Agent 3 고정 → test 1회" 순서대로 진행. 결정 사항은 아래 0장.

## 0. 10/25 결정 (Agent 3 담당)

| # | 안건 | 결정 |
| --- | --- | --- |
| 1 | A1 일괄 부정 기본값 | `--blanket on` 기본 (노션 제안). 단 A1 범위 규칙을 코드로 둠 (2.3장) |
| 2 | 변형 세트 Agent 3 실행 | **B안**: 고정 후 Agent 4 담당 요청 시점에 실행. 노션에 두 선택지 중 명시된 지시는 없음 |
| 3 | 예산 | 노션 제안대로 (p08 dev 1회 ≈ $6, 재현성·Haiku ≈ $15) |
| 4 | Agent 3 안의 검증(후검사 격하) | **제거**. 검증은 Agent 4 책임 (명확한 역할 분리). v2 코드는 `handoff_agent4/postcheck_v2_reference.py`에 참고용 보관, 실행 안 됨 |

## 1. 재현과 데이터 교체 (0단계)

- v2 결과 재현: v5 데이터 + v14.3 근거 + p06, `--llm replay` → 83.0% / 반대 방향 0 / 129 / 29 / 81.6% / 87.0% / 3/5. 노션 보고와 동일.
- p06 프롬프트 원문 복원: p07 = p06 + 규칙 14의 동의 진술 절. 61/61 캐시 키 재현 → `AGENT3_PROMPT=p06|p07|p08`으로 선택 가능.
- 정답 v6 → v7 차이 4행: 행정 3행 PASS→UNKNOWN/MISSING(NCT07113262-I05, NCT07762105-I07, NCT07379333-E28), DAS28(NCT05428488-I05) PASS→EXPIRED(안건 4 종결). 기준 파일(①-b dev)은 v5 = v7 동일.
- v2 출력을 v7 정답으로 채점: 83.3%, 확정 정답 UNKNOWN 125/531 (변형 세트 페이지 수치와 일치).
- 근거 v14.3 → v14.7: dev 4,901줄 중 4줄만 값 변경(SYN-0010 ×2, SYN-0019, SYN-0020; `pending`/`null` 규약). 캐시로 재채점 가능한 범위: 61호출 중 50 → 행정 플래그 수정 후 48 (39쌍, 15명).

## 2. v2 → v3에서 바뀐 것

### 2.1 후검사 격하 제거 (`agent3/postcheck.py`)

- 남긴 것: 어휘 정리(status/reason/action), 존재하지 않는 근거 ID는 `cited_ids_invalid`로 옮기고 `evidence_ids`에서 제외(그래프가 ID를 풀어야 함) — **상태는 바꾸지 않음**, 팀 정책 스위치(`--blanket`, `--list-inference`).
- 뺀 것: 근거 없는 확정 → UNKNOWN, 가족력만·계획만·의심만, 판단 용어 FAIL, 모호 노트, 창 밖 수치 → EXPIRED, 충돌 플래그. 모두 Agent 4 검사 1~4 영역.
- 영향 측정: v2 dev 전체에서 이 격하들은 **4건**만 작동(plan_only 2, hedged_note 1, judgment_term 1). 캐시 재채점 39쌍에서는 0건 → 수치 변화 없음. "근거 없는 확정 판정 0"은 LLM 자체가 근거를 인용하기 때문에 격하 없이도 0/371.
- 결과 표의 "근거 없는 확정 판정" 행은 v3부터 **Agent 4 통과 전 값**으로 의미가 바뀜. 보고서에 명시.

### 2.2 행정 항목 (안건 3, ①-b dev v2.1)

`data/dev/reference/criteria.jsonl` 5행 `administrative: false` + `fix_note` (`CHANGES_dev_v2_1b_2026-10-25.md`): NCT07566156-I02, NCT07720284-I08, NCT06692738-I04, NCT03424005-I09, NCT02714634-I09. 나머지 3행은 정답 v7이 UNKNOWN으로 정리해서 유지.
test 쪽 같은 유형 71행(조직 26, 피임 45) 목록: `data/test/reference/admin_review_candidates_test.csv` — 정답 담당과 기준 합의 후 재검토, 지금은 미수정.

### 2.3 A1 일괄 부정: 기본 on + 범위 규칙

`--blanket on`을 켜자 39쌍에서 일괄 부정 PASS 60건 중 12건이 정답(A1 반영 가정)과 어긋남. 모두 A1 제안의 예외("검사 수치·기간 내 급성 사건·약물·시술·감염·연구자 판단")에 해당: 급성 관상동맥증후군, 급성 심근염(90일), 두개저 골절·신경외과 수술, 두통 유형·편두통 합병증, 뇌혈관 기형·동맥류, 삼출액·복수, 이식 대기, 신장 위기.
→ `postcheck.apply_policy`에 `pc:blanket_out_of_scope` 추가(정규식: acute, crisis, fracture, neurosurg, transplant, effusion, ascites, malformation, aneurysm, complication, headache). dev 39쌍에서 11건 차단(정답 UNKNOWN 10, 정답 PASS 1 = 오차단), 남은 불일치 1건(SYN-0009 NCT06252649-E04 간질성 폐질환 — 정답 담당 질의, `runs/gold_query_A1_scope.csv`).
정규식은 dev 11건으로 맞춘 것이라 과적합 위험이 있음. 시간창(`time_window`)·"current"·"clinically significant"는 정답이 일괄 부정 PASS를 인정하므로 범위 규칙에 넣지 않음.

### 2.4 프롬프트 p08

v2의 "인용하고도 UNSUPPORTED" 35건(정답 v7) 분류 → `runs/analysis_unsupported_cited_v2.csv`:
- (a) 19건: 기록에 값·등급·날짜가 있고 선정 기준 문턱에 못 미침, 또는 제외 범주의 명백한 구성원인데 "정도 미기록"으로 UNKNOWN (정답 FAIL).
- (b) 16건: 연구 절차 문구("investigator confirmation", "central read", "at the discretion of")나 "clinically significant"를 막는 조건으로 읽음. 의학적 내용은 충족, 또는 소견이 명시적으로 경미 (정답 PASS).

MISSING 38건(정책 격하 제외, 미인용) → `runs/missing_check_v2.csv`: Agent 2 누락 **0건**(모두 정답 위치에 근거 있음). 원인: NKDA 미적용 5, 클래스 부정문 놓침 8, 완결 열거문("Treatment to date: …") 3, 배타 범주(adenocarcinoma ↔ small cell) 2, 척도 환산(ECOG↔Karnofsky) 1, 정상 수치 vs 수치 정의 제외 ~6(대부분 `complex` 줄 = A3 쟁점), 행정·조직 3(2.2장에서 해결), 임상 추론 ~6.

p08 변경(일반 문장으로, dev 특정 문구 제거): 규칙 5 수정(확진된 주요 진단 = clinically significant; 경미·조절됨만 있으면 PASS), 규칙 20(기록된 값이 요건에 못 미치면 FAIL), 21(명시적 부정은 선정 기준도 FAIL), 22(범주 소속 판단: 충수절제 = 위장관 수술), 23(연구 절차 문구 무시, 조직 존재 = 가용), 24(MISSING 전 회상 점검: NKDA·클래스 부정·완결 열거·배타 범주·수치, A3 목록은 규칙 2 유지).
**A2 경계 주의**: 24(c) 완결 열거문을 명시 진술로 보는 것은 정답의 판정을 따른 것. 정답 담당 확인 항목.

### 2.5 기타

- `--salt` 옵션: 같은 프롬프트의 재현성 재실행(D3)용 캐시 키 소금.
- `eval/score_dev.py` 기본 근거 경로 v14.7. `run.py` EVIDENCE_FILES v14.7 + `dev_variants`.
- 단위 테스트 27개 통과(격하 테스트 3개는 v3 계약으로 교체).

## 3. 캐시 재채점 결과 (39쌍 / 15명, p06 답 그대로, 코드만 v3)

| 지표 | v2 (같은 39쌍) | v3-dev, 현재 정답 v7 | v3-dev, A1 반영 가정 정답 | v2, A1 반영 가정 |
| --- | --- | --- | --- | --- |
| 기준 일치 (엄격) | 83.4% | 83.4% | **86.1%** | 80.1% |
| 관대 (3_inferred + 2_blanket) | 84.8% | 87.9% | 87.5% | 81.4% |
| 반대 방향 오류 | 0 | 0 | 0 | 0 |
| 확정 정답을 UNKNOWN으로 | 86/378 | 62/378 | 65/405 | 112/405 |
| 정답 UNKNOWN을 확정 | 21 | 22 | 22 | 21 |
| 근거 없는 확정 판정 | 0/322 | 0/371 | — | — |
| 시험 판정 일치 / D2 | 89.7% / 2/3 | 89.7% / 2/3 | — | — |

- "현재 정답" 열이 v2와 같은 83.4%인 것은 일괄 부정 PASS(정답 미반영 38행)가 득실 상쇄하기 때문. A1 패치 후 +2.7pt 예상.
- 나머지 15쌍(SYN-0010·0011·0017·0019·0020)과 p08 전체 실행은 API 호출 필요 → 4장.

## 4. API 실행 대기 (`export/`)

Message Batches 요청 파일 3개, 각 61호출(dev 54쌍), 입력 약 85만 토큰/파일(캐시 전):

| 파일 | 모델 | 소금 | 용도 |
| --- | --- | --- | --- |
| `requests_dev_sonnet_p08_r1.jsonl` | claude-sonnet-5-5 | — | p08 dev 1회 (노션 할 일 2) |
| `requests_dev_sonnet_p08_r2.jsonl` | claude-sonnet-5-5 | r2 | 재현성 2회차 (D3) |
| `requests_dev_haiku45_p08_r1.jsonl` | claude-haiku-4-5-20251001 | — | 모델 비교 (E1) |

실행·반영 절차는 `docs/RUNBOOK_batches.md`. 반영 후: `--llm replay`로 dev 채점(정답 v7과 A1 가정 두 번), r1/r2 차이로 재현성, Haiku 비교표 → 버전 고정 판단.

## 5. 정답·다른 담당에게 넘길 것

| 받을 곳 | 내용 | 파일 |
| --- | --- | --- |
| 정답 | A1 38행 패치(dev·test) 일정 — v3는 `--blanket on` 기본 | — |
| 정답 | A1 범위 질의 1행(간질성 폐질환이 일괄 부정에 덮이는지) | `runs/gold_query_A1_scope.csv` |
| 정답 | A3 priority 10행 검토(아직 PASS) | `a3_list_criteria_dev.csv` (기존) |
| 정답 | A2 경계: "Treatment to date: …" 완결 열거를 명시 진술로 본 정답 판정 유지 여부 | 2.4장 |
| CT.gov(본인) | test ①-b 행정 71행 재검토 — 정답 담당과 기준 합의 후 | `data/test/reference/admin_review_candidates_test.csv` |
| Agent 4 | 검증 책임 이전 안내, 출력 필드 | `handoff_agent4/README.md` |
| Agent 2 | MISSING 38건 모두 근거 존재 → 요청 없음. `for_criterion` 선별은 38건 중 7건을 가리므로 채택 보류 | `runs/missing_check_v2.csv` |

## 6. 남은 순서

1. Batches 3개 실행 → ingest → dev 채점(현재 정답 / A1 가정) → 재현성·Haiku 표
2. p08 결과에서 반대 방향 오류·과확정 점검(특히 규칙 20·21·22가 만든 FAIL)
3. 버전 고정(`run_meta.json`, 태그 `a3-0.3.0`) → 노션 "Agent 3 v3 보고" → Agent 2에 test 근거 요청 → test 1회
4. (B안) Agent 4 담당 요청 시 변형 100쌍 1회 실행
