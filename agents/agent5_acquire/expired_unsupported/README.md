# Agent 5 — EXPIRED·UNSUPPORTED·CONFLICT (검사 안내, 의사 확인)

UNKNOWN/EXPIRED → 검사 안내(`new_test`), UNKNOWN/UNSUPPORTED → 의사 확인·환자 질문, CONFLICT와 시험을 막는 MISSING 중 검사·의사 확인 줄. 기록 찾기 줄은 `missing/`으로 넘김.

## 현재 버전
a5u-0.2.0

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `judgments` | agent3_out.jsonl |
| `patients` | patients.jsonl |
| `evidence` | evidence.jsonl |
| `answers` | answers.jsonl (선택) |

| 출력 키 | 파일 |
| --- | --- |
| `cards` | cards.jsonl |
| `handoff` | handoff_record_lookup.jsonl (→ missing/) |
| `patients` | patients.jsonl (답 문서 포함) |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agents.agent5_acquire.expired_unsupported.run --input patients=data/dev/input/patients.jsonl --out runs/agent5_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
