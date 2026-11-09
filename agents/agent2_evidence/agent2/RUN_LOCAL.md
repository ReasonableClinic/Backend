# LLM 층 로컬 실행 안내

키는 각자 PC의 `.env` 파일에만 둡니다 (대화·노션·코드에 넣지 않음). 설정 방법은 `agent2/TRACING.md` 1절을 봅니다. 아래 명령은 zsh에서 그대로 붙여 넣어도 되도록 `#`, `!`를 쓰지 않았습니다.
모든 명령은 인계 폴더(`agent2_handoff_v1`, `agent2/`와 `data/`가 있는 곳)에서 실행합니다.

## 0. 준비 (한 번)

macOS Homebrew 파이썬은 시스템 전체 설치를 막으므로(PEP 668) 폴더 안에 가상환경을 만듭니다.

```
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -U openai anthropic python-dotenv
cp .env.example .env
```

`.env`를 열어 사용할 키만 채웁니다. 추적(Langfuse)을 쓰려면 `python3 -m pip install "langfuse>=5,<6"`도 설치합니다.

새 터미널을 열 때마다 `source .venv/bin/activate`를 먼저 실행합니다 (프롬프트 앞에 `(.venv)`가 보이면 됨).

## 1. 개발: OpenRouter gpt-oss-120b

`.env`에 `OPENROUTER_API_KEY`가 들어 있으면 따로 export할 필요가 없습니다.

먼저 환자 2명으로 확인 (1~2분):

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider openrouter --out runs/dev_oss_smoke --limit 2
```

끝에 `usage:` 줄과 환자별 `checks`가 나오면 정상입니다. `STOP:`이 나오면 그 메시지를 그대로 보내 주세요.

서비스 응답 시간 측정 (환자를 한 명씩 처리, 환자별 소요 시간을 `usage.json`의 `patient_seconds`에 기록):

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider openrouter --online --out runs/dev_oss_online --limit 5
```

속도 기본값 (v3): 요청당 30단위, 동시 요청 8개, 재시도는 더 작은 요청으로, gpt-oss 추론 `low`, 요청 제한 시간 120초. 바꾸려면 `--chunk`, `--workers`, `REASONING_EFFORT=medium`, `LLM_DEADLINE=240`을 명령 앞이나 옵션으로 줍니다.

dev 전체, 두 가지 모드:

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider openrouter --relevance all --out runs/dev_oss_all
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider openrouter --relevance criteria --out runs/dev_oss_crit
```

채점 (선택, 결과는 제가 다시 봅니다):

```
python3 code/eval_evidence.py --gold data/dev/gold/gold.jsonl --pred runs/dev_oss_all/evidence.jsonl --patients data/dev/input/patients.jsonl --by doc_type
```

돌려보낼 것 (응답 캐시는 빼고):

```
zip -r agent2_runs_oss.zip runs/dev_oss_all runs/dev_oss_crit -x "*/cache/*"
```

- 같은 명령을 다시 실행하면 `cache/`에 있는 답을 재사용해서 호출하지 않습니다. 프롬프트를 고친 뒤에는 바뀐 요청만 다시 호출됩니다.
- 중간에 멈춰도 다시 실행하면 이어서 합니다 (이미 받은 답은 캐시).

## 2. 최종: Claude Haiku 4.5 + Message Batches + 프롬프트 캐시

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider anthropic-batch --relevance all --out runs/dev_haiku_all
```

- 배치는 제출 후 대기합니다 (대부분 1시간 안, 최대 24시간). 30초마다 진행 상황을 출력합니다. 창을 닫아도 배치는 서버에서 계속 돌고, 같은 명령을 다시 실행하면 저장된 배치 ID(`cache/batches.json`)로 이어서 결과를 받습니다.
- 잘못된 답이 있으면 2라운드, 3라운드 배치가 자동으로 이어집니다.
- 배치는 오프라인 처리(dev/test 평가, 등록된 환자 기록 미리 추출)에만 씁니다. 사용자가 기다리는 경로는 `--provider anthropic --online`(일반 호출, 정가, 병렬)으로 측정합니다.
- 프롬프트 캐시: 고정 지시문+예시(약 6천 토큰, Haiku 4.5 최소 4,096 토큰 이상)와 환자별 후보 시험 기준에 캐시 지점을 둡니다. TTL은 일반 호출 5분, 배치 1시간. 고정 부분은 실행 시작 때 한 번 미리 써 두고, 요청이 4개 이상인 환자는 환자별 기준도 먼저 한 번 써 둡니다 (`--prewarm auto`, 기본값. 환자당 약 1초 추가, 빈 캐시에서 비용 약 절반). `--prewarm off`/`on`으로 끄거나 항상 켤 수 있습니다. 배치 안에서 캐시 적중은 보장되지 않고 "최선 노력"입니다. `usage.json`의 `batch_cache_read_input_tokens`로 실제 적중을 확인합니다.
- `ANTHROPIC_BASE_URL`이 환경에 설정돼 있어도 무시하고 `https://api.anthropic.com`으로 보냅니다. 프록시를 써야 하면 `AGENT2_ANTHROPIC_BASE_URL`에 주소를 넣습니다.
- `usage.json`의 `estimated_cost_usd`는 2026-10-06 공개 가격(Haiku 4.5 입력 $1, 출력 $5 / 100만 토큰, 배치 50%, 캐시 쓰기 1h 2배, 읽기 0.1배)으로 계산한 추정치입니다. 실제 청구액은 Console에서 확인합니다.

## 3. 모델을 바꾼 뒤

gpt-oss에서 맞춘 프롬프트가 Haiku에서도 같게 동작한다는 보장이 없으므로, Haiku로 dev를 다시 돌려 같은 지표(재현율, 환자당 개수, 속성 점검)를 비교하고 필요하면 dev로만 다시 맞춥니다. test는 고정된 버전으로 한 번만 돌립니다.

## 갱신 경로 (새 문서만 다시 추출)

에이전트 4·5가 새 정보를 가져와 문서가 추가·수정되면, 그 문서만 추출해 기존 근거에 합칩니다. `--old`는 지난 실행 폴더입니다.

```
python3 agent2/update.py --patients data_update_demo/patients_plus.jsonl --old runs/dev_haiku_v1341 --old-patients data/dev/input/patients.jsonl --trials data/dev/reference/trials.jsonl --criteria-ref data/dev/reference/criteria.jsonl --provider anthropic --out runs/dev_haiku_upd
```

- v13.5 이후 실행 폴더에는 `docs.jsonl`(문서 지문)이 있어 `--old-patients`가 필요 없습니다. 그 전 실행이면 그때의 기록 파일을 `--old-patients`로 줍니다.
- 결과: `evidence.jsonl`(합친 전체), `changes.jsonl`(환자별 추가·삭제·변경 근거 ID와 개념), `docs.jsonl`(다음 갱신용).
- `--provider rules`는 LLM 없이 규칙만 씁니다.

## test 절차

test 추출과 그 예행연습(dev)은 `agent2/RUN_TEST.md` 한 문서를 따릅니다 (입력 확인 → 배치 추출 → 결과 확인·키트).

## ①-b 이후 (v14, 2026-10-09)

개념 목록은 팀 공용 `agent2/concepts.json`(①-b, 138개)이 기본이고, 에이전트 2만의 조정은 `agent2/concepts_agent2.json`에 있습니다. 기준 파일은 `data/dev/reference_1b/criteria.jsonl`(①-b 채운 것)을 씁니다.

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference_1b/trials.jsonl --criteria-ref data/dev/reference_1b/criteria.jsonl --provider anthropic --out runs/dev_haiku_1b
```

개념 단위 확인 (근거 정답의 concept·value가 채워지기 전):

```
python3 code/eval_concepts.py --gold data/dev/gold/gold.jsonl --criteria data/dev/reference_1b/criteria.jsonl --concepts agent2/concepts.json --pred runs/dev_haiku_1b/evidence.jsonl
```

