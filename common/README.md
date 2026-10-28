# common

두 에이전트 이상이 쓰는 코드만 둡니다. 에이전트 하나만 쓰는 코드는 그 에이전트 폴더에 둡니다.

| 파일 | 내용 | 상태 |
| --- | --- | --- |
| `env_setup.py` | `.env` 읽기: `load_env()`, 키 확인 `require("ANTHROPIC_API_KEY")`, 로그용 `masked()` | 사용 가능 (에이전트 2 v14.12에서 옮김) |
| `tracing.py` | Langfuse 추적: `Tracer.create(agent=...)`, `tr.llm(...)`, `tr.step(...)`, `tr.result(...)`, `tr.finish()`. 키 없으면 아무것도 안 함 | 사용 가능 (에이전트 2판을 일반화) |
| `llm.py` | LLM 호출 (provider별 클라이언트, 제한 시간, 재시도, 비용 집계) | 모듈화 때 에이전트 2 `code/gold_lib.py`, 에이전트 3 `agent3/llm.py`에서 모음 |
| `concepts.py` | 개념 사전 읽기, 단위 변환 (`alt_units`) | 모듈화 때 모음 (에이전트 2 `extract.load_concepts`, 에이전트 3 `structured.load_concepts`) |
| `dates.py` | 날짜 파싱, 측정일 규칙 (공통 형식 6.3), as_of 기준 경과일 | 모듈화 때 모음 |

사용 예 (에이전트 `run.py` 맨 앞):

```python
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))   # repo root
from common.env_setup import load_env, require
from common.tracing import Tracer

load_env()
require("ANTHROPIC_API_KEY")
tr = Tracer.create(agent="agent3", version="a3-0.3.0", model="claude-sonnet-5-5")
```

추적 이름 규칙: trace `"<agent>:<patient_id>"`(에이전트 1은 trial_id), session = 실행 ID(`RUN_ID`, pipeline이 모든 에이전트에 같은 값을 넘김).
