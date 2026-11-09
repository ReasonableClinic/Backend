# .env 키 관리와 Langfuse 추적

에이전트 2(`llm_layer.py`, `update.py`)에 붙였습니다. 추적 키가 없거나 `langfuse` 패키지가 없으면 예전과 똑같이 동작합니다 (mock으로 결과 파일이 바이트 단위로 같은지 확인).

## 1. .env로 키 관리

```
python3 -m pip install python-dotenv
cp .env.example .env
```

- `.env`를 열어 쓰는 키만 채웁니다. 실행할 때마다 `export`할 필요가 없습니다.
- 찾는 순서: `AGENT2_ENV_FILE`에 적은 경로 → 실행하는 폴더의 `.env` → 인계 폴더 루트의 `.env`.
- 터미널에서 `export`한 값이 있으면 그 값이 우선합니다 (한 번만 다른 키로 돌릴 때).
- `python-dotenv`가 없어도 내장 파서로 읽습니다 (`KEY=value`, `#` 주석, 따옴표).
- `.gitignore`에 `.env`가 들어 있습니다. `.env.example`만 공유합니다.
- 키가 노출된 적이 있으면 먼저 폐기하고 새로 발급한 키를 넣습니다.

## 2. Langfuse 추적 켜기

```
python3 -m pip install "langfuse>=5,<6"
```

`.env`에 `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`을 채우면 자동으로 켜집니다. 실행 첫 줄에 `tracing: on (session ...)`이 나오면 정상입니다. 끄려면 `AGENT2_TRACING=0`.

먼저 mock으로 연결만 확인 (LLM 호출 없음, 비용 없음). 아래 명령의 `data/dev/input/`, `data/dev/reference/`는 이 zip에 없고 기존 인계 폴더(`agent2_handoff_v1`)에 있으므로, 그 폴더에서 실행하거나 두 폴더를 이 폴더의 `data/dev/` 아래로 복사합니다:

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider mock --out runs/trace_smoke --limit 2
```

## 3. Langfuse에서 보이는 것

| 단위 | 내용 |
|---|---|
| Session | 실행 한 번 (`<out 폴더 이름>-<시각>`, `AGENT2_RUN_ID`로 직접 지정 가능) |
| Trace | 환자 한 명. 이름 `agent2:<patient_id>`, User = patient_id, 태그 = agent2, provider, 모델, `AGENT2_TRACE_LABEL` |
| Generation | LLM 요청 하나 (`extract r<라운드> c<청크>`): 보낸 단위, 답, 토큰, 비용(OpenRouter 실청구액), 소요 시간, 오류 |
| Score `answer_parse` | 요청별 답 파싱 결과: ok / truncated / bad_json / request_failed |
| Span `patient_result` | 환자별 근거 수, 사실이 나온 단위 수, `checks` 카운터 전체. 실패·깨진 JSON이 있으면 WARNING |
| Score `n_evidence`, `units_with_facts` | 환자별 수치 (실행끼리 비교용) |

자주 쓰는 확인:
- `answer_parse = bad_json` 또는 `truncated`로 거르면 프롬프트·청크 크기 문제가 있는 요청만 보입니다.
- User(patient_id)로 거르면 한 환자의 모든 요청이 라운드 순서대로 보입니다. 검사 스크립트(`eval_evidence.py`, 속성 점검)에서 걸린 환자를 여기서 찾아 실제 입력과 답을 봅니다.
- Session 두 개를 비교하면 프롬프트를 바꾼 전후의 토큰·비용·실패율 차이가 보입니다.
- 로컬 응답 캐시(`cache/responses.jsonl`)에서 바로 나온 답은 호출이 없으므로 기록되지 않습니다. 전부 다시 보려면 `--cache-dir`를 새 폴더로 줍니다.
- 배치(`anthropic-batch`)는 결과를 받을 때 한꺼번에 기록되므로 소요 시간은 의미가 없고, 메타데이터에 `batch_id`가 붙습니다.

## 4. 무엇이 밖으로 나가는지 (`AGENT2_TRACE_CONTENT`)

| 값 | 보내는 내용 |
|---|---|
| `units` (기본) | 기록 단위 텍스트와 모델 답. 고정 지시문(약 6천 토큰, 모든 요청에 같음)과 후보 기준 부분은 해시와 길이만 |
| `full` | 프롬프트 전체 |
| `none` | 텍스트 없음. 개수, 토큰, 시간, 점수만 |

지금은 합성 환자라 `units`로 충분합니다. 실제 환자 기록을 다루게 되면 `none`으로 두거나, Langfuse를 직접 설치(self-host)해 `LANGFUSE_BASE_URL`을 그 주소로 바꿉니다.

## 5. 바뀐 파일

- 새 파일: `agent2/env_setup.py` (.env 읽기), `agent2/tracing.py` (Langfuse, 꺼져 있으면 아무것도 안 함), `agent2/TRACING.md`, `.env.example`, `.gitignore`
- `agent2/backends.py`: 시작할 때 `.env`를 읽고, 요청마다 generation 기록 (일반 호출·배치·오류)
- `agent2/llm_layer.py`: 실행마다 추적기 생성, 답 파싱 결과 점수, 환자별 `patient_result`, 끝에 전송
- `agent2/update.py`: 새 문서만 다시 추출하는 경로에도 같은 추적 (Session 이름이 `update-`로 시작)
- `code/gold_lib.py`: 키가 없을 때 안내 문구에 `.env` 추가
- `code/fill_gold_evidence.py`: 시작할 때 `.env`를 읽음 (`agent2/`가 옆에 없으면 건너뛰고 예전처럼 `export`만 사용)
- `agent2/llm_layer.py`, `agent2/update.py`: Langfuse에 기록되는 버전 기본값 `v14.10` (`AGENT2_VERSION`으로 바꿀 수 있음)
- `agent2/RUN_LOCAL.md`: `export` 대신 `.env` 안내

추적 기록은 판정이 아니라 원인 확인용입니다. 정답과 맞는지는 지금처럼 검사 스크립트로 봅니다.
