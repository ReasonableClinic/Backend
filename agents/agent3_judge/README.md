# Agent 3 — 판정

환자-시험 쌍마다 기준별로 PASS / FAIL / UNKNOWN / CONFLICT를 내고 근거 ID를 붙인 뒤, 공통 형식 6.1로 시험 판정을 집계하고 Evidence Graph를 씁니다. 수치·범주 기준은 코드(`structured.py`), 나머지는 LLM.

## 현재 버전
a3-0.3.0 + p07 + claude-sonnet-5-5

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `patients` | patients.jsonl |
| `pairs` | pairs.jsonl |
| `criteria` | criteria.jsonl |
| `evidence` | evidence.jsonl (③) |

| 출력 키 | 파일 |
| --- | --- |
| `judgments` | agent3_out.jsonl (④ 어휘) |
| `graph` | graph/{patient_id}.json |
| `meta` | run_meta.json |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agent3_judge.run --input patients=data/dev/input/patients.jsonl --out runs/agent3_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
