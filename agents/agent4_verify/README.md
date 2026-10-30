# Agent 4 — 검증

에이전트 3 판정을 검사해 통과하지 못한 확정 판정(PASS/FAIL)을 UNKNOWN 또는 CONFLICT로 내립니다. 올리는 일은 하지 않습니다. 검사: 근거가 있는지, 기준과 같은 개념인지, 측정일이 기간 안인지, 기록끼리 어긋나지 않는지.

## 현재 버전
개발 시작

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `judgments` | agent3_out.jsonl |
| `evidence` | evidence.jsonl |
| `patients` | patients.jsonl |
| `criteria` | criteria.jsonl |

| 출력 키 | 파일 |
| --- | --- |
| `judgments` | agent4_out.jsonl (같은 형식, 바뀐 줄에 이유) |
| `graph` | graph/ 갱신 |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agent4_verify.run --input patients=data/dev/input/patients.jsonl --out runs/agent4_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
