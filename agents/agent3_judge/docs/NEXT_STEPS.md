# Agent 3 완성까지 남은 단계

작성 2026-10-07, 갱신 2026-10-08. 1단계(실제 모델로 dev 실행)와 2단계 첫 개선(p02→p04)까지 끝났고, Sonnet 5.5 + p04를 v1으로 정했습니다(README의 결과 표, `docs/v1_review.md`).

## 단계 한눈에

| 단계 | 할 일 | 마침 조건 | 필요한 것 |
| --- | --- | --- | --- |
| 1 | ~~실제 모델로 dev 54쌍 실행~~ 완료 (v1) | `score.md` 팀 공유 | — |
| 2 | 오류 분석 → 프롬프트·후검사 개선 (2~4회) | dev 반대 방향 오류 0~1건, 시험 판정 혼동 정리 | — |
| 3 | 근거 버전·모델 비교 | 비교표 1장 | — |
| 4 | TrialGPT·TREC 외부 검증 | 반대 방향 오류 ≤ 1%, TREC 제외→eligible ≤ 5% | TREC 담당 파일, Agent 2의 TREC 근거, 평가 스크립트 |
| 5 | Agent 4·5·6 연결과 데모 | 질문 → 재판정 → 순위 변화가 한 번에 도는 데모 | 각 담당과 스키마 합의 |
| 6 | ①-b 도착 후 수치 기준 코드 판정 | 수치 기준의 코드 판정 비율 상승 | CT.gov 담당의 ①-b |
| 7 | 팀 미결 규칙 반영 | 기본값 확정 | 팀 회의 |
| 8 | 버전 고정과 test 1회 실행 | 출력 전달 | test 시험·기준·쌍 목록, Agent 2의 test 근거 |

---

## 1. 실제 모델로 dev 전체 실행

1. 노션에 적힌 API 키는 폐기하고 새 키를 발급해 환경 변수로만 둡니다.
   ```bash
   export ANTHROPIC_API_KEY=...
   python3 -m agent3.run --split dev --llm anthropic --model claude-sonnet-5-5 --out runs/dev_sonnet_p02
   python3 eval/score_dev.py runs/dev_sonnet_p02/agent3_out.jsonl
   ```
2. 규모: LLM 호출 63회(기준 30개 넘는 시험은 나눠 부름), 호출당 환자 근거 블록 약 8,800토큰, 캐시 없이 입력 약 56만 토큰, 출력 약 8만 토큰(추정). 같은 환자의 두 번째 시험부터 환자 블록은 프롬프트 캐시로 읽습니다. 실제 사용량은 `run_meta.json`의 `usage`에 남습니다.
3. 비용을 줄이려면 `--llm export`로 요청 파일을 만들어 Message Batches로 보내고, 결과를 `python3 -m agent3.ingest --results 결과.jsonl`로 넣은 뒤 `--llm replay`로 돌립니다.
4. 볼 숫자(순서대로): 반대 방향 오류 → 근거 없는 확정 판정(0이어야 함) → 시험 판정 혼동 → 엄격 일치 → 확정 정답을 UNKNOWN으로 남긴 수.

## 2. 오류 분석과 개선

`score.json`에 세 목록이 있습니다: `opposite_list`(PASS↔FAIL), `missed_list`(정답이 확정인데 UNKNOWN), `unknown_decided_list`(정답이 UNKNOWN인데 확정).

1. 각 행을 넷으로 나눕니다.
   - (a) 근거 누락: 기록에는 있는데 근거 목록에 없음 → Agent 2 담당에게 전달
   - (b) 기준 분할 문제: 선택지 조각, 코호트 소제목 누락 → Agent 1(CT.gov) 담당에게 전달
   - (c) 판정 규칙 위반 → 프롬프트나 후검사 수정 (Agent 3)
   - (d) 정답이 의심스러움 → 합성 데이터 담당에게 전달
2. 프롬프트를 고치면 `agent3/prompt.py`의 `PROMPT_VERSION`을 올리고 dev를 다시 돌립니다. 후검사만 고쳤으면 `--llm replay`로 API 호출 없이 비교됩니다.
3. 과적합 주의: dev는 환자 20명뿐입니다. 규칙은 일반 문장으로 쓰고, 특정 환자 사례의 문구를 프롬프트에 넣지 않습니다. 예시(few-shot)를 넣는다면 TrialGPT 쪽 사례에서 고릅니다.
4. 드라이런에서 이미 본 경향
   - 약물 계열 누락(spironolactone = 칼륨보존 이뇨제)이 반대 방향 오류를 만듦 → p02에 규칙 15로 반영함
   - 정답은 현재 측정값이 조건을 직접 반박하면 PASS로 둠(BP 136/84 ↔ uncontrolled hypertension) → p02 규칙 16
   - 여러 항목을 나열한 기준에서 일부만 확인될 때, 메모 규칙은 UNKNOWN인데 정답은 PASS인 경우가 있음(ALT·AST 정상, CK 없음) → 프롬프트로 맞추지 말고 2·7단계에서 팀이 정할 것
   - UNKNOWN의 행동(action) 일치율이 45~57%로 낮음 → Agent 5 담당과 행동 고르는 기준을 먼저 합의하고 예시를 추가

## 3. 근거 버전·모델 비교 (발표용)

```bash
python3 -m agent3.run --split dev --llm anthropic --evidence-kind rules --out runs/dev_sonnet_rules
python3 -m agent3.run --split dev --llm anthropic --model claude-haiku-4-5-20251001 --out runs/dev_haiku
python3 -m agent3.run --split dev --llm openai --model gpt-oss-120b --out runs/dev_gptoss   # 정답 생성기와 같은 모델
```

- 비교할 것: Haiku 근거 vs 규칙 근거, 판정 모델 2~3개, 후검사가 바꾼 판정 수(`rule_tags`의 `pc:*` 개수), 비용·지연
- "코드 판정 + LLM + 후검사" 구성이 LLM 단독보다 나은지는 후검사가 막은 오류 수로 보여 줄 수 있습니다

## 4. TrialGPT·TREC 외부 검증

1. TREC 담당에게 공통 형식 파일(`patients.jsonl`, `trials.jsonl`, `criteria.jsonl`, `gold.jsonl`의 `trec_qrels`)과, 합성 담당에게 `trialgpt_eval.py`·`compare_trec.py`를 받습니다.
2. TREC 환자의 근거가 필요합니다. Agent 2 담당에게 일괄 추출을 요청하세요. 근거 없이 원문만으로 판정하는 모드는 아직 없습니다(필요하면 `patient_block`에 문서 원문을 넣는 모드를 추가, 하루 분량).
3. TREC은 `as_of`가 2021-04-27이고 가려진 날짜는 `observed_date: null`입니다. 프롬프트는 날짜 없는 근거를 "no date"로 보여 주므로 그대로 동작합니다.
4. `agent3_out.jsonl`을 `trialgpt_eval.py compare`가 읽는 `gold_draft.jsonl` 형식으로 바꾸는 작은 변환 스크립트가 필요합니다(필드 확인 후).
5. 합격선: 반대 방향 오류 ≤ 1%, TREC 제외인데 eligible ≤ 5%. 참고 지표로 "기록에 없는 제외 기준 = 해당 없음" 정확도를 정답 생성기 0.757과 비교합니다.

## 5. Agent 4·5·6 연결

| 연결 | 주고받는 것 | Agent 3 쪽 준비 상태 |
| --- | --- | --- |
| Agent 3 → 4 | `agent3_out.jsonl`, `graph/{patient_id}.json` (판정마다 근거 ID, 원문 위치, 계산 노드) | 완료 |
| Agent 4 → 3 | `flags.jsonl` {patient_id, trial_id, criterion_id, issue, detail} | `--rejudge` 완료. 1회 제한은 오케스트레이터에서 |
| Agent 5 → 2 → 3 | 새 문서 → Agent 2 갱신 → `changes.jsonl` | `--changes` 완료 |
| Agent 3 → 6 | `trial_label`, `counts`, `label_why` | 완료. 순위 규칙 6.4는 Agent 6 |

- 오케스트레이터에서 파이썬으로 부를 때: `Agent3(ds, judge).judge_pair(patient_id, trial_id, only, hints, prev)`
- 데모 시나리오: 첫 판정 potential → Agent 5가 질문 2개 → 답변을 새 문서로 → Agent 2 갱신 → Agent 3이 연결된 기준만 재판정(그래프 회차 2) → Agent 6 순위 변화
- 그래프 형식(노드·간선 이름)을 Agent 4와 웹 화면 담당에게 먼저 보여 주고 확정합니다

## 6. ①-b가 오면

- `criteria.jsonl`의 `concept`·`operator`·`value`·`unit`·`time_window`가 채워지면 `agent3/rules.py`에 수치 기준 코드 판정을 추가합니다: 같은 개념의 최신 근거 값 → `concepts.json`의 `alt_units`로 단위 변환 → 비교 → `time_window` 밖이면 UNKNOWN/EXPIRED
- 근거 선별은 `agent2/evidence_index.py`의 structured 모드(`for_criterion`)로 바꿔 프롬프트를 줄일 수 있습니다
- 변형 세트(violation·missing·expired·conflict·unsupported)가 생기면 `eval/score_dev.py`에 변형별 적중률을 추가합니다

## 7. 팀이 정할 것

- 장기계 일괄 부정, 목록 추론: 확정되면 기본값을 `--blanket on`, `--list-inference allow`로 바꿉니다(지금은 dev 정답과 같은 off/strict)
- 행정 항목의 행동: 메모는 `clinician_confirmation`, dev 정답은 `patient_question`이 다수(53 대 10). 코드는 정답을 따라 동의·의지 항목에 `patient_question`, "investigator's judgment"에 `clinician_confirmation`을 씁니다
- Agent 3 출력 어휘와 그래프 형식 확정(2차 회의 B4)

## 8. 고정과 test

1. 모델·프롬프트·코드 버전을 고정합니다(`run_meta.json` 보관, 저장소 태그).
2. 받은 파일에는 test의 시험·기준(`test/reference/`)과 쌍 목록이 없습니다. 합성 담당에게 받아 `data/test/reference/`와 `data/test/input/pairs.jsonl`(patient_id, trial_id)로 둡니다. test 환자 기록은 개발 중 열지 않습니다.
3. Agent 2에 test 근거 생성을 요청하고 `agent3_kit/evidence_test_haiku_v13_7.jsonl`로 둡니다.
4. 한 번만 실행해 `agent3_out.jsonl`을 합성 담당에게 넘깁니다(채점은 그쪽).
   ```bash
   python3 -m agent3.run --split test --llm anthropic --model <고정 모델> --out runs/test_final
   ```
