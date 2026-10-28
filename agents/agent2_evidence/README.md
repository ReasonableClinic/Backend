# Agent 2 — 근거 추출

환자 기록 문서를 단위로 나눠 규칙과 LLM으로 사실(개념, 값, 단위, 측정일, 원문 위치)을 뽑아 ③ 근거를 만듭니다. 새 문서만 다시 뽑는 갱신 경로(`update.py`)가 있습니다.

## 현재 버전
v14.12

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `patients` | patients.jsonl (②) |
| `trials` | trials.jsonl |
| `criteria` | criteria.jsonl (①-b, 후보 기준 계획용) |

| 출력 키 | 파일 |
| --- | --- |
| `evidence` | evidence.jsonl (③) |
| `log` | log.jsonl, usage.json |
| `changes` | changes.jsonl (갱신 경로) |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agents.agent2_evidence.run --input patients=data/dev/input/patients.jsonl --out runs/agent2_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
