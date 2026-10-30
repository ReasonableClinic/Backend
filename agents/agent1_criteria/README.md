# Agent 1 — 기준 구조화 (CT.gov)

ClinicalTrials.gov에서 시험(⓪)과 선정·제외 기준 원문(①-a)을 받아, 기준을 개념·연산자·값·단위·기간으로 구조화(①-b)합니다.

## 현재 버전
①-b dev v2 final / test v1

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `trial_ids` | 시험 ID 목록 또는 CT.gov 응답 JSON |

| 출력 키 | 파일 |
| --- | --- |
| `trials` | trials.jsonl (⓪) |
| `criteria` | criteria.jsonl (①-a + ①-b) |
| `concepts` | concepts.json (개념 사전) |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agent1_criteria.run --input patients=data/dev/input/patients.jsonl --out runs/agent1_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
