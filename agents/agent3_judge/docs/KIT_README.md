# 에이전트 3 키트 v14.9 (에이전트 2 → 에이전트 3)

| 경로 | 내용 |
| --- | --- |
| `agent3_kit/` | 근거 파일(dev Haiku·규칙, TREC Haiku·규칙, TrialGPT Haiku·규칙, dev 변형 36명 Haiku·규칙), 이전 키트 대비 ID 변경 목록, 123건 분류표 |
| `agent2/evidence_index.py` | **근거 조회 코드**: `EvidenceIndex`, ①-b 기준별 선별 `for_criterion`, 한 줄 표시 `render` |
| `agent2/concepts.json`, `agent2/concepts_agent2.json` | ①-b 개념 사전 138개와 에이전트 2 조정 (`evidence_index.py`가 자동으로 읽음) |
| `code/eval_concepts.py` | 수치 기준 코드 판정 미리보기, 개념 단위 확인 (단독 실행 가능) |
| `code/missing_check.py` | UNKNOWN/MISSING 기준의 정답 위치에 Agent 2 근거가 있는지, 선별에 들어갔는지 (`--agent3 runs/X/agent3_out.jsonl`) |
| `AGENT2_OUTPUT_FOR_AGENT3.md` | 사용법과 필드 설명 (1장 파일, 3장 사용법, 7장 ①-b 선별) |

압축을 푼 폴더에서 바로 실행됩니다:

```
python3 agent2/evidence_index.py --evidence agent3_kit/evidence_dev_haiku_v14_9.jsonl --patients data/dev/input/patients.jsonl --patient SYN-0001
```
