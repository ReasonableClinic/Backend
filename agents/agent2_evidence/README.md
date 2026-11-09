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
| `evidence` (선택) | 넘겨줄 고정 근거 파일 (기본 모드) |

| 출력 키 | 파일 |
| --- | --- |
| `evidence` | evidence.jsonl (③) |

## dev 실행 (한 줄)

```bash
python3 -m agents.agent2_evidence.run --input patients=data/dev/input/patients.jsonl --input trials=data/dev/reference/trials.jsonl --input criteria=data/dev/reference/criteria.jsonl --input evidence=data/dev/evidence/evidence_dev_haiku_v14_12.jsonl --out runs/a2
```

- 기본: 고정 근거 v14.12를 검사(근거 ID, 환자 범위)해서 그대로 넘깁니다. 파이프라인 `ORDER`에는 없습니다(근거 파일이 입력).
- 재추출: `--config '{"provider": "anthropic"}'`이면 `agent2/llm_layer.py`를 부릅니다. Agent 2는 LLM 답 캐시가 없어 키가 필요합니다.

## 모듈화 전후 확인 기준
기본 모드 출력 `evidence.jsonl`은 입력 근거 파일과 바이트 단위로 같습니다.

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
