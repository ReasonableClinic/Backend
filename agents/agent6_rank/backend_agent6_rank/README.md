# Agent 6 — 추천 순위, 브리핑

Evidence Graph를 읽어 환자별 시험 순위를 매기고(공통 형식 6.4), 의료진용 상세와 환자용 쉬운 설명을 만듭니다. 그래프에 없는 내용은 덧붙이지 않고(문장마다 그래프 노드 ID), 효과를 약속하는 표현은 쓰지 않습니다.

## 현재 버전
a6-0.4.3 — dev 개발판 (test 채점 버전은 a6-0.4.0 고정), 용어 사전 sha256 `06fc5ffa26d3e447baa02050401cfbec94c07a17da1656ce6917637826d032fe` (6.4 정렬 + 재확인 표시·near-miss, 핵심 정보 브리핑(틀 문장 또는 LLM 브리핑), 근거·내용 검사). 합성 담당 키트 `for_agent6_v1`에서 시작

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `judgments` | 최종 판정 jsonl (에이전트 3 `agent3_out.jsonl`, 4가 붙으면 4의 출력). 여러 번 주면 합침 |
| `graph` | 환자별 그래프 폴더 `graph/` (여러 번 줄 수 있음) |
| `trials` | `trials.jsonl` |
| `evidence` (선택, 권장) | 에이전트 2 근거 jsonl. 환자 기록의 암 진단 판단에 씀 (없으면 그래프만 봄). **그래프를 만든 에이전트 3 실행이 읽은 파일**(같은 버전, 같은 추출. LLM 추출과 규칙 추출은 ID가 겹치므로 섞지 않음. 파일 옆 `run_meta.json`의 `id_series`가 다르면 멈춤)이어야 하며, 다르면 브리핑 전에 멈춥니다. 이 근거로 쓴 문장은 `ev:` ID를 인용합니다 |

| 출력 키 | 파일 |
| --- | --- |
| `ranking` | `ranking.jsonl` (`ranking_gold.jsonl` 형식 + `items` 설명) |
| `briefing` | `briefing/<patient_id>.clinician.json·.md`, `briefing/<patient_id>.patient.json·.md` |

## dev 실행 (한 줄)

```bash
python3 agents/agent6_rank/run.py --input judgments=data/dev/agent3_out_v3_p07/agent3_out.jsonl --input graph=data/dev/agent3_out_v3_p07/graph --input trials=data/dev/reference/trials.jsonl --out runs/agent6_dev
```

## 모듈화 전후 확인 기준
LLM 없이(기본) 같은 입력이면 같은 출력. dev 기본+변형: 순위 순서 일치 40/55, 첫 시험 일치 43/55, `check_grounding`·`check_content` 110개 브리핑 실패 0. LLM 켤 때: `--config '{"llm": true}'`

## 원본 코드
`agent6/` (rank, graph, keyinfo, glossary, brief_clinician, brief_patient, brief_llm, rules, review, check_grounding, check_content). `review.py`는 에이전트 4 출력이 생기면 그 결과를 표시하는 방식으로 바꿀 예정입니다. 설명은 키트 README.

## 담당
<!-- 이름 -->
