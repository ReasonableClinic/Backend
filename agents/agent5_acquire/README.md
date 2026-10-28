# Agent 5 — 정보 획득

UNKNOWN·CONFLICT 기준을 받아 기록 찾기, 환자 질문, 검사 안내, 의사 확인 카드를 만들고, 받은 답을 새 기록 문서로 바꿔 에이전트 2 갱신 → 에이전트 3 부분 재판정으로 넘깁니다. 두 하위 폴더로 나눠 개발합니다.

## 현재 버전
a5u-0.2.0 (expired_unsupported), missing 개발 중

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `judgments` | agent3_out.jsonl 또는 agent4_out.jsonl |
| `patients` | patients.jsonl |
| `evidence` | evidence.jsonl |
| `answers` | answers.jsonl (카드에 대한 답, 선택) |

| 출력 키 | 파일 |
| --- | --- |
| `cards` | cards.jsonl |
| `patients` | 답을 문서로 넣은 patients.jsonl |
| `new_docs` | new_docs.jsonl |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agents.agent5_acquire.run --input patients=data/dev/input/patients.jsonl --out runs/agent5_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
