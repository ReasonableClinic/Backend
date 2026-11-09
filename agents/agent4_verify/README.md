# Agent 4 — Verifier + Evidence Graph

Agent 3의 판정을 **근거 그래프 위에서 검사**하고, 근거가 뒷받침하지 못하는 확정 판정을 내린다(격하만, 승격 없음). LLM을 쓰지 않는다.
결과물은 환자 1명의 후보 시험 전체를 담은 `graph_<patient_id>.json` — 화면(시각화), Agent 5(질문), Agent 6(브리핑)이 이 파일만 읽는다.

```
입력: ⓪ trials.jsonl  ① criteria.jsonl(①-b)  ② patients.jsonl  ③ evidence.jsonl(Agent 2)  ④ 모양의 Agent 3 출력
build  → 그래프 구성 (같은 evidence_id 는 노드 하나 → 여러 판정이 공유)
verify → 충돌 엣지 생성 → 판정마다 검사 1~4 → 격하 → 시험 판정 재계산 (공통 형식 6.1)
출력: graph_<pid>.json, verify_report.json
```

## 실행

```bash
cd ~/ctgov_collect/agent4
python3 tests/test_agent4.py                                   # 동작 확인 (검사 4종 각 1건, 잘못된 격하 0)
python3 -m agent4 --fixture tests/fixture --out runs/fixture   # 합성 예시
python3 -m agent4 --patients ../ref/dev/input/patients.jsonl --trials ../ref/dev/reference/trials.jsonl \
                  --criteria ../stage_1b/out/dev_v3/criteria.jsonl \
                  --evidence <Agent2 evidence_dev.jsonl> --verdicts <Agent3 dev 출력.jsonl> --out runs/dev
```

Agent 3 출력은 gold.jsonl 과 같은 모양이면 그대로 읽는다: `{patient_id, trial_id, criteria:[{criterion_id, status, reason, supporting_evidence:[evidence_id…], expected_action}]}` (`expected_status`·`evidence_ids` 도 허용).

## 그래프 스키마

| 노드 | 출처 | 주요 속성 |
|---|---|---|
| `trial:NCT…` | ⓪ | title, min_age, max_age, sex |
| `crit:NCT…-I01` | ①-b | crit_type, original_text, concept, term, operator, value, unit, time_window, answerable_by, administrative, logic_group |
| `ev:<evidence_id>` | ③ | concept, term, value, unit, value_type, observed_date, certainty, subject, detail, text |
| `doc:<doc_id>` | ② | doc_type, date, author_role |
| `verdict:<criterion_id>#n` | ④ / Agent 4 | status, reason, expected_action, by(agent3/agent4), verified, original_status, downgrade_check, note |

| 엣지 | 뜻 | 누가 만드나 |
|---|---|---|
| `trial → has_criterion → crit` | 시험의 기준 | build |
| `crit → in_group → crit` (relation AND/OR) | ①-b logic_group | build |
| `verdict → judges → crit` | 이 판정은 이 기준에 대한 것 | build / Agent 4 |
| `verdict → supported_by → ev` | 이 근거를 보고 판단했다 | build / Agent 4 |
| `ev → from → doc` | 이 근거는 이 문서에서 나왔다 | build |
| `ev ↔ conflicts_with ↔ ev` | 같은 개념인데 값이 다르다 | **Agent 4** |
| `verdict(new) → downgraded_from → verdict(old)` | 검증자가 내렸다. 원본은 남긴다 | **Agent 4** |

"믿을 수 있는 판정" = `verdict → supported_by → ev → from → doc` 사슬이 끊기지 않고, 날짜가 기간 안이고, 충돌 엣지가 없는 것. 검사 4개는 전부 이 사슬 검사다.

## 검사와 격하

| # | 검사 | 실패 시 | 행동 |
|---|---|---|---|
| 1 grounding | supported_by 가 0개, 또는 존재하지 않는 evidence_id | UNKNOWN / UNSUPPORTED | 규칙표 |
| 2 relevance | 근거 concept(+term) ≠ 기준 concept(+term) (공통 개념 사전 문자열 비교) | UNKNOWN / UNSUPPORTED | 규칙표 |
| 3 expiry | 가장 최근 근거 측정일 < as_of − `time_window.max_days_before` (`--default-windows`: 기간 없는 검사 30일·영상 90일) | UNKNOWN / EXPIRED | new_test |
| 4 conflict | 같은 concept+term 근거끼리 값이 다름(수치 5% 초과, 불리언 반대; stopped/past 는 false 로 봄), 측정일 차이 ≤ 30일 | CONFLICT | clinician_confirmation |

- PASS/FAIL 만 검사한다. UNKNOWN/CONFLICT 는 이미 보수적이므로 행동만 규칙표로 통일한다. 행정 항목은 시험 판정에서 빠지므로 검사하지 않는다.
- 날짜가 없는 근거는 만료 판단을 하지 않는다(TREC 규칙). 단위가 다른 수치는 환산 전엔 충돌로 보지 않는다.
- 격하는 **새 verdict 노드**를 만들고 `downgraded_from` 으로 연결한다. `original_status` 로 "LLM 은 뭐라 했나" 가 남아 "LLM 단독 N건 → 검증 후 0건" 을 셀 수 있다.

### 다음 행동 규칙표 (`decide_action`)

| reason | answerable_by | expected_action |
|---|---|---|
| EXPIRED | — | new_test |
| CONFLICT | — | clinician_confirmation |
| MISSING | med_record ∈ | med_record_check |
| MISSING | patient ∈ | patient_question |
| MISSING | lab ∈ | lab_check |
| UNSUPPORTED | clinician ∈ | clinician_confirmation |
| UNSUPPORTED | patient ∈ | patient_question |
| 그 밖 | | clinician_confirmation |

## 갱신 (Agent 5 → 2 → 3 → 4 루프)

```python
g = EvidenceGraph.load("graph_SYN-0001.json")
g.affected_by_evidence(["SYN-0001-EV188"])    # {"verdicts": [...], "criteria": [...], "trials": [...]}  ← 이 범위만 재판정
g.affected_by_concept("pregnancy")            # 새 개념 근거가 들어왔을 때 다시 볼 기준 (UNKNOWN/MISSING 이던 것)
g.chain("verdict:NCT…-I01#1")                 # 판정 → 근거 → 문서 사슬 (화면·브리핑용)
```

Agent 2 의 `changes.jsonl`(`added`/`removed`/`changed`/`added_concepts`)을 그대로 넣으면 된다. 전체 재실행이 아니라 영향 범위만 돌린다는 것을 `history` 로그로 보일 수 있다.

## 평가 (변형 세트가 오면)

- expired 변형에서 EXPIRED 검출률, conflict 변형에서 CONFLICT 검출률, missing 변형에서 UNKNOWN 유지율
- **base 환자에서 잘못된 격하 비율** (낮아야 함) — `tests/test_agent4.py` 의 "정상 판정 3건 무격하" 가 같은 검사
- `original_status` 로 "Agent 3 단독 근거 없는 확정 N건 → Agent 4 후 0건"

## 폴더

| 경로 | 내용 |
|---|---|
| `agent4/graph.py` | EvidenceGraph — 노드·엣지, 조회, 전파(`affected_by_*`), 저장/복원 |
| `agent4/build.py` | 입력 5종 → 그래프 |
| `agent4/verify.py` | Verifier(검사 4종·격하), `decide_action`, `trial_verdict`(6.1) |
| `agent4/a3format.py` | Agent 3 형식 출력: `graph/<pid>.json`, `agent3_out.jsonl` 줄 |
| `agent4/__main__.py` | CLI |
| `tests/fixture/` | 합성 환자 1명·시험 2개 — 검사 4종이 각각 한 건씩 걸리고 HbA1c 근거가 두 시험에 공유됨 |
| `tests/test_agent4.py` | 자체 검사 |

## 한계·다음

- 검사 2 는 문자열 비교라 별칭(aliases)·단위 환산은 안 본다 → concepts.json 을 넣어 `check_concepts.unit_ok` 로 확장 예정.
- `--default-windows` 의 "현재 상태를 묻는 기준" 판별은 아직 없음(수치 검사·영상에만 적용). 안건 4(DAS28 7일 창)는 ①-b `time_window` 값을 따른다.
- Agent 3 v2 실제 출력 파일을 받으면 변환기(필드명 차이)와 dev 50명 실행 결과를 붙인다.

## 업데이트 (2026-11-01) — dev 실행
실행 (Agent 3 a3-0.3.1 dev 출력 + Agent 2 v14.12 근거):
    python3 -m agent4 --patients <patients.jsonl> --trials <trials.jsonl> --criteria <criteria.jsonl> \
        --evidence evidence_dev_haiku_v14_12.jsonl --verdicts agent3_out.jsonl --out runs/dev_a031
(근거 파일이 없으면 `--a3-graphs <Agent3 graph/ 폴더>` 로 인용된 근거만 사용 — 만료·충돌 검사 불완전)

검사 5종: 근거 존재 / 관련성(개념 계열 허용) / 노트 불일치(확정인데 불확실 표현) / 만료(같은 개념의 최신 근거 기준) / 충돌(수치는 같은 날짜만, 종료일 없는 과거 병력은 현재로 간주).
Agent 3 의 UNKNOWN·CONFLICT 판정과 action 은 그대로 두고, PASS·FAIL 만 격하한다. 격하 이유는 `downgrade_reason`.

dev 결과(19명·54쌍·판정 1,044): Agent 3 PASS 446 / FAIL 72 / UNKNOWN 526 / CONFLICT 0
→ Agent 4 이후 PASS 418 / FAIL 60 / UNKNOWN 542 / CONFLICT 24. 시험 라벨 변경 3쌍(모두 potential 로 하향).
미검증: gold 대비 점수, 충돌 24건 개별 검토, 변형 100쌍, Agent 3 그래프 형식과의 정렬.

## 업데이트 (2026-11-07) — Agent 3 형식 출력, llm_missing, 사전 점검
`--out` 폴더에 기존 `graph_<pid>.json`·`verify_report.json` 에 더해:

| 파일 | 내용 |
|---|---|
| `graph/<pid>.json` | Agent 3 그래프 형식 (`agent4/a3format.py`). 노드 `kind`, 판정 `dec:<trial>:<crit>:r<n>`, 엣지 `[a, rel, b]`, 시험 판정 `label:<trial>` |
| `agent3_out.jsonl` | 입력 판정 줄 + 격하 반영 + 시험 판정 다시 계산 |

- Agent 3 `graph/` 가 `--verdicts` 옆에 있으면(또는 `--a3-graph-base`) 그 노드·엣지를 그대로 두고 위에 더한다. 없으면 r1 부터 만든다.
- 격하된 판정은 새 라운드 `dec:…:r<n+1>` (`by: agent4`, `downgraded_from: <이전 라운드 id>`, `downgrade_check`, `downgrade_reason`, `original_status`) + 엣지 `[new, downgraded_from, old]`. 근거 충돌은 `[ev, conflicts_with, ev]`.
- `label:<trial>` 은 Agent 4 가 다시 계산한 값(`by: agent4`, `why` 는 Agent 3 `label_why` 모양)으로 바꾸고 Agent 3 값은 `agent3_label`/`agent3_why` 로 남긴다. `agent3_out.jsonl` 도 `trial_label`·`label_why`·`counts` 를 바꾸고 `agent3_trial_label`, 기준별 `original_status/reason/action` 을 남긴다.
- `judged_by`(또는 `rule_tags`)가 `pc:llm_missing` 인 줄은 판정되지 않은 것으로 보고 제외 기준·OR 그룹·행정 항목이어도 시험을 `potential` 로 둔다 (`label_why: NOT_JUDGED <cid>`, Agent 3 a031 #5 와 같은 규칙).
- **사전 점검**: 시작할 때 판정이 인용한 evidence_id 중 근거 파일에 없는 수·비율을 출력하고 `verify_report.json` 의 `preflight`·`total.evidence_id_mismatch` 에 남긴다. 1% 를 넘으면 종료 코드 2 로 멈춘다(근거 파일 버전이 판정과 다름). 그래도 돌리려면 `--allow-mismatch`. `--fixture` 는 검사 1 용으로 없는 ID 를 일부러 넣어 두어 경고만 한다.
- dev_a031 판정의 짝은 Agent 2 **v14_12** 근거다. v14_18 은 인용 근거 785개 중 13개(1.66%)가 없어 사전 점검에서 멈춘다.
- CLI 가 Python 3.11 에서도 돈다 (전에는 3.12 전용 f-string 문법 때문에 3.11 에서 SyntaxError).
