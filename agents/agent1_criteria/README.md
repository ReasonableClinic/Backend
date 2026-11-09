# Agent 1 — Trial Parsing Agent

> **backend 파이프라인 진입점 (`run.py`, 레포 루트에서 dev 한 줄):**
> `python3 -m agents.agent1_criteria.run --input trial_ids=<NCT 목록 파일> --out runs/a1   # 캐시에 있는 시험만 (replay_pack), 없으면 멈춤`
> 전체는 `python3 -m pipeline.run_pipeline` (REPRODUCE.md). 아래는 받은 패키지의 원래 README입니다.

임상시험 기준 원문 → 공통 형식 ⓪ Trial + ①(a+b) Criterion. Agent 2가 환자 쪽 번역기라면 Agent 1은 시험 쪽 번역기다. 둘 다 `concepts.json`(같은 사전)을 쓰므로 Agent 3이 두 출력을 같은 어휘로 비교할 수 있다.

```
입력: NCT 번호            또는  (질환명, 환자 나이·성별)
plan → retrieve(API) → split(규칙) → window(규칙) → structure(LLM) → link(규칙) → verify(자기 검증·재시도) → finalize(캐시·제안)
출력: trials.jsonl, criteria.jsonl, run_log.json
```

에이전트다운 점: 도구 사용(ClinicalTrials.gov API, 개념 사전), 환자 나이·성별로 후보 필터, 자기 검증(사전 키·단위·형식) 후 실패 줄만 LLM 재시도, 그래도 안 되면 `free_text`로 솔직하게 표시, 사전에 없는 개념은 `concept_proposed`로 사람 승인 대기, 이미 처리한 시험은 캐시(548개 사전 적재 가능).

## 폴더

| 경로 | 내용 |
| --- | --- |
| `agent1/agent.py` | `TrialParsingAgent` — 단계 오케스트레이션 |
| `agent1/retrieve.py` | API 도구 (검색·단건 조회·저장 응답 읽기) |
| `agent1/ctgov_to_common.py` | ⓪ 변환·①-a 분할 (팀 참고 코드) |
| `agent1/time_window.py` | 기간 규칙 (stage_1b `fill_time_window.py`) |
| `agent1/structure_llm.py` | LLM 프롬프트·검증 (stage_1b `fill_structure.py`) |
| `agent1/postprocess.py` | 여러 줄 logic_group (stage_1b `fix_1b.py`) |
| `agent1/check_concepts.py` | 단위 변환 검사 (팀 공용) |
| `concepts.json` | 개념 사전 (dev_v2 와 동일, 138개) |
| `cache/` | 시험별 결과 캐시 |
| `tests/fixtures/` | 저장된 API 응답 (오프라인 테스트용) |

## 실행

```bash
cd ~/ctgov_collect/agent1
export ANTHROPIC_API_KEY=...

# 1) 네트워크·API 없이 규칙 단계만 (동작 확인)
python3 -m agent1 --saved tests/fixtures/ctgov_response_gastric_HER2.json --no-llm --out runs/offline

# 2) 기존 ①-b 결과를 캐시로 적재 (548개는 LLM 재호출 없음)
python3 -m agent1 --import-structured ../ref/dev/reference/trials.jsonl ../stage_1b/out/dev_v2/criteria.jsonl
python3 -m agent1 --import-structured ../ref/test/reference/trials.jsonl ../stage_1b/out/test_v1/criteria.jsonl   # test 끝난 뒤

# 3) 새 시험 하나 (LLM 사용, 10~20초)
python3 -m agent1 --nct NCT06880770 --out runs/one

# 4) 환자 조건으로 검색 → 상위 5건 구조화
python3 -m agent1 --condition "Graves disease" --age 29 --sex female --max 5 --out runs/graves
```

## 다른 에이전트와의 연결

- **Agent 6(추천)·오케스트레이터**: 환자 질환·나이·성별을 주고 `run(condition=…, age=…, sex=…)` 호출 → 후보 시험 ⓪ + 구조화 기준 ①. 캐시에 있으면 즉시.
- **Agent 3**: `criteria.jsonl` 그대로 입력. 필드 의미는 노션 "①-b 구조화 기준 전달 가이드" 참고 (`logic_group` = 여러 줄 묶음, `inline_relation` = 한 줄 안의 and/or).
- **Agent 2**: 후보 시험의 `concept` 목록 = 환자에게서 찾을 것(추출 계획).
- 사전 확장: `run_log.json`의 `concept_proposals` → 사람이 승인하면 `concepts.json`에 추가 → Agent 2와 공유.

## 자체 성능 (발표용)

- 규칙 파서가 Inclusion/Exclusion 제목을 못 찾은 시험 19건(`unknown` 224줄)을 LLM 단계가 처리.
- dev 수치 기준 코드 판정: 정답과 88/88 일치 (합성 담당 확인).
- dev 3,856줄 structured 89%, 검사기 ID 변경 0.
- 규칙 분할 실패 시험을 LLM 분할로 복구 — NCT03708627 unknown 1줄 → 4줄 전부 structured.
- verify 재시도 경로 작동 확인 — Graves 3건에서 3줄 재시도 후 남은 문제 0.

## 한계

- LLM 출력이라 실행마다 조금 다를 수 있음(캐시로 고정). 변형 대상 기준은 사람이 확인.
- `complex: true` 줄은 조건 하나만 구조화. 상대 단위(xULN)는 환자 검사지 참고치 필요.
- 네트워크가 막힌 환경에서는 `--saved`로 저장 응답을 쓴다.
