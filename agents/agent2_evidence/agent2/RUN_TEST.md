# test 근거 추출 절차 (dev 예행연습과 같은 순서)

2026-10-21 작성. dev로 한 번 그대로 돌려 본 뒤 test에 쓰는 절차입니다. 명령은 zsh에 그대로 붙여 넣을 수 있게 `#`, `!`를 쓰지 않았습니다. 모든 명령은 인계 폴더(`agent2/`, `code/`, `data/`가 있는 곳)에서 실행합니다.

## 지키는 것

- test 정답(④)은 보지 않고, test 결과를 보고 코드·프롬프트·사전을 고치지 않습니다 (블라인드). `release.py`는 test 정답 경로를 주면 멈춥니다.
- `id_map`, `review.csv`(기본 환자 ID가 들어 있음), 정답 파일은 에이전트 입력 폴더에 두지 않습니다.
- test는 **한 번만** 돌립니다. 그 전에 dev 예행연습을 같은 코드로 끝내 둡니다.
- 키는 Mac의 환경변수로만 둡니다.

## 0-1. test 실행 (2026-10-25 에이전트 3 `a3-0.3.0` 고정 → 실행)

입력: `data_test_v147.zip` (test 기본 30명, 변형 34명, ①-a, ①-b = 에이전트 3 고정본 `for_agent3_v7`의 test 기준: CT.gov test v1 + 합성 담당 단위 정리 5행). 코드: `agent2_v14_7.zip`. Mac `gemini-work`에서:

```
cd /Users/david/gemini-work
unzip -o ~/Downloads/agent2_v14_7.zip
unzip -o ~/Downloads/data_test_v147.zip
source .venv_a2/bin/activate
export ANTHROPIC_API_KEY=여기에_실제_키
python agent2/preflight_inputs.py --patients data_test/test/input/patients.jsonl --trials data_test/test/reference_1b/trials.jsonl --criteria data_test/test/reference_1b/criteria.jsonl --criteria-a data_test/test/reference/criteria.jsonl
python agent2/llm_layer.py --patients data_test/test/input/patients.jsonl --trials data_test/test/reference_1b/trials.jsonl --criteria-ref data_test/test/reference_1b/criteria.jsonl --provider anthropic-batch --out runs/test_haiku_v147
python agent2/seed_from_base.py --patients data_test/test/input/patients_variants.jsonl --base-patients data_test/test/input/patients.jsonl --base-evidence runs/test_haiku_v147/evidence.jsonl --out runs/test_variants_seed_haiku
python agent2/update.py --patients data_test/test/input/patients_variants.jsonl --old runs/test_variants_seed_haiku --old-patients runs/test_variants_seed_haiku/known_patients.jsonl --trials data_test/test/reference_1b/trials.jsonl --criteria-ref data_test/test/reference_1b/criteria.jsonl --provider anthropic --out runs/test_variants_haiku_v147
zip -r test_haiku_v147.zip runs/test_haiku_v147 runs/test_variants_haiku_v147 -x "*/cache/*"
```

규칙판(기본 7,135개, 변형 8,268개)은 이쪽에서 만들어 형식 확인 0건. test는 이 한 번만 돌린다.

## 0. 준비 (Mac, 코드가 바뀔 때마다)

Mac에서 겪은 것 (10-21 예행연습):

- 작업 폴더는 `/Users/david/gemini-work`. 그 안의 `data/`에는 dev 파일이 없고 dev 입력은 `data14/dev/`(`data14_dev.zip`)에 있으므로 dev 명령의 `data/dev/`는 `data14/dev/`로 바꿔 씀. test 입력도 같은 방식으로 `data_test/`처럼 따로 풀면 경로만 바꾸면 됨
- 기존 `.venv`에는 `anthropic`이 설치되지 않아 새 가상환경 `.venv_a2`를 만듦: `python3 -m venv .venv_a2`, `source .venv_a2/bin/activate`, `python -m pip install -U pip anthropic openai`
- 401 `invalid x-api-key`는 키 문제 (요금 없음). `echo ${ANTHROPIC_API_KEY:0:10}`로 앞 글자 확인

최신 코드 zip(지금은 `agent2_v14_7.zip`)을 인계 폴더에 풀어 덮어씁니다 (`agent2/`, `code/`, `data/dev/reference_1b/`가 바뀜).

```
cd 인계폴더경로
unzip -o ~/Downloads/agent2_v14_7.zip
source .venv_a2/bin/activate
export ANTHROPIC_API_KEY=sk-ant-...
```

## 1. 입력 확인 (돈 쓰기 전, 1초)

dev:

```
python3 agent2/preflight_inputs.py --patients data/dev/input/patients.jsonl --trials data/dev/reference_1b/trials.jsonl --criteria data/dev/reference_1b/criteria.jsonl --criteria-a data/dev/reference/criteria.jsonl
```

test (CT.gov 담당의 test ①-b를 `data/test/reference_1b/`에 넣은 뒤):

```
python3 agent2/preflight_inputs.py --patients data/test/input/patients.jsonl --trials data/test/reference_1b/trials.jsonl --criteria data/test/reference_1b/criteria.jsonl --criteria-a data/test/reference/criteria.jsonl
```

마지막 줄이 `OK`면 다음 단계로. `STOP:`이 나오면 그 줄을 보내 주세요. 비용·시간 추정도 같이 나옵니다 (dev 약 $1.9 / 19분, test 약 $4 / 40분).

## 2. 추출 (Haiku 4.5 배치)

dev 예행연습:

```
python3 agent2/llm_layer.py --patients data/dev/input/patients.jsonl --trials data/dev/reference_1b/trials.jsonl --criteria-ref data/dev/reference_1b/criteria.jsonl --provider anthropic-batch --out runs/dev_haiku_v144
```

test:

```
python3 agent2/llm_layer.py --patients data/test/input/patients.jsonl --trials data/test/reference_1b/trials.jsonl --criteria-ref data/test/reference_1b/criteria.jsonl --provider anthropic-batch --out runs/test_haiku_v147
```

끝에 `usage:` 줄이 나오면 정상입니다. 중간에 끊기면 같은 명령을 다시 실행합니다 (이미 받은 답은 캐시에서 다시 씀).

## 3. 결과 보내기

```
zip -r dev_haiku_v144.zip runs/dev_haiku_v144 -x "runs/dev_haiku_v144/cache/*"
```

(test는 `dev`를 `test`로 바꿔서.) zip과 `usage:` 줄을 보내 주시면 이쪽에서 4단계를 합니다.

## 4. 확인과 키트 (이쪽에서)

dev: 형식 확인 + 이전 키트 ID 유지 + 정답 채점.

```
python3 agent2/release.py --evidence runs/dev_haiku_v144/evidence.jsonl --patients data/dev/input/patients.jsonl --old agent3_kit/evidence_dev_haiku_v14_7.jsonl --gold data/dev/gold/gold.jsonl --criteria data/dev/reference_1b/criteria.jsonl --out runs/rel_v144/evidence_dev_haiku_v14_4.jsonl
```

test: 형식 확인만 (정답 없음, 이전 키트 없음).

```
python3 agent2/release.py --evidence runs/test_haiku_v147/evidence.jsonl --patients data/test/input/patients.jsonl --out agent3_kit/evidence_test_haiku_v14_7.jsonl
```

`release.py`가 확인하는 것: 모든 환자에 근거가 있음, `source.text`가 문서 원문과 같음, 기준일 이후 날짜 없음, 중복·형식이 틀린 ID 없음, 필수 필드. 하나라도 걸리면 종료 코드 1이고 보고서(`*.report.md`)에 첫 사례가 적힙니다.

test 키트에는 규칙만 쓴 근거도 같이 넣습니다 (모델 실패 시 대체용, 비용 0):

```
python3 agent2/extract.py --patients data/test/input/patients.jsonl --trials data/test/reference_1b/trials.jsonl --criteria-ref data/test/reference_1b/criteria.jsonl --out runs/test_rules_v147
python3 agent2/release.py --evidence runs/test_rules_v147/evidence.jsonl --patients data/test/input/patients.jsonl --out agent3_kit/evidence_test_rules_v14_7.jsonl
```

## 5. dev 예행연습 결과 (2026-10-21, `runs/dev_haiku_v144`)

- 213 요청, 311초(배치), 추정 $1.89. 형식 확인 0건
- 재현율 1.000, IoU 0.802, 개념 일치 0.909, 값 일치 0.856, 수치 코드 판정 88/88, 기준별 선별 정답 포함 0.820 (v14.3 키트와 같거나 약간 높음)
- 재현성 (같은 코드, 모델만 다시 실행: v14 답 재생 vs 새 실행): 근거 사실(위치·개념·값) 90% 동일(Jaccard 0.898, 모델 근거만 0.867), term 표현·status까지 72%. 참·거짓이 뒤집힌 근거 2개 ("DKA resolved", "Fever resolved"), 둘 다 "resolved"라 과거 사실의 표현 차이
- 키트는 v14.3 유지 (점수가 같아서 교체하면 에이전트 3의 재판정만 늘어남)

## 6. dev 예행연습에서 볼 것

- 형식 확인 0건
- 재현율 1.000 근처, 개념 일치 0.90, 값 일치 0.85, 수치 코드 판정 89/89 근처 (`synthetic_dev_v5` 정답, 키트 v14.3과 비교)
- 같은 코드로 두 번 돌린 결과 차이 (v14 실행 대비 `changes.jsonl`): 모델 재실행에 따른 흔들림의 크기. 발표 자료의 재현성 수치로 씀

## 7. 변형 환자 (dev 10-23 완료, test는 test 기본 환자와 함께)

변형 환자는 기본 환자 기록에서 문서 하나만 바뀐 것이라, 같은 문서의 근거는 기본 환자 근거를 옮기고 바뀐 문서만 추출한다 (재실행 흔들림이 변형 효과에 섞이지 않게).

```
python3 agent2/seed_from_base.py --patients <변형 patients.jsonl> --base-patients <기본 patients.jsonl> --base-evidence <기본 근거 키트 파일> --out runs/variants_seed_haiku
python agent2/update.py --patients <변형 patients.jsonl> --old runs/variants_seed_haiku --old-patients runs/variants_seed_haiku/known_patients.jsonl --trials ... --criteria-ref ... --provider anthropic --out runs/variants_haiku
```

test에서는 test 기본 환자 Haiku 추출을 먼저 끝내고, 그 결과를 `--base-evidence`로 쓴다. `seed_map.jsonl`·`changes.jsonl`은 바뀐 문서를 드러내므로 키트에 넣지 않는다.
