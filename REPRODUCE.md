# TrialTrace 실행·재현 안내 (평가자용, 2026-11-09)

임상시험 기준과 합성 환자 기록을 6개 에이전트로 이어 기준별 판정·근거·추천 순위·설명을 만드는 프로젝트입니다. 이 문서는 제출물을 받은 분이 **데모를 띄우고, 보고서 수치를 다시 계산하는 방법**을 적습니다.

| 단계 | 하는 일 | API 키 | 걸리는 시간 |
| --- | --- | --- | --- |
| A. 데모 | 미리 실행한 결과를 웹 화면으로 재생 | 필요 없음 | 5분 |
| B. 보고 수치 재현 | 저장된 LLM 답을 재생해 같은 출력과 점수를 다시 계산 (`reproduce.sh`) | 필요 없음 | 1분 안팎 |
| C. 전체 재실행 | LLM을 실제로 다시 불러 처음부터 실행 | 필요 | 수 시간, 비용 발생 |

B는 보고서와 **같은 숫자**가 나와야 합니다(다른 줄은 5장). C는 모델(claude-sonnet-5-5)이 temperature를 받지 않아 실행마다 일부 판정이 달라질 수 있습니다.

## 1. 환경

- macOS 또는 Linux (Windows는 WSL). `bash`, `unzip`, Python **3.11** 이상
- A·B는 Python 표준 라이브러리만 씁니다. C에서 Agent 2를 다시 추출할 때만 `pip install anthropic python-dotenv`
- 데이터는 모두 합성 데이터입니다(실제 환자 정보 없음). 기준일(as_of) 2026-10-01

## 2. 받기

| 받을 것 | 위치 | 내용 |
| --- | --- | --- |
| backend 레포 | https://github.com/ReasonableClinic/Backend | 에이전트 코드(고정 버전 그대로), 통합 파이프라인 `pipeline/`, API `api/`, `reproduce.sh` |
| 웹 화면 레포 | https://github.com/ReasonableClinic/Healthcare-web | 웹 화면 web_demo_v3.11 (`index.html`, `app.js`, 번역 `data/ko.json`·`card_ko.json`, backend-0.1.1과 같은 데모 묶음) |
| `replay_pack.zip` | backend 레포 Release | dev 데이터·정답, Agent 1 캐시, Agent 3 LLM 답 캐시, 원본 실행 출력, 데모 데이터. **test 파일 없음** |
| `test_pack.zip` (선택) | https://github.com/ReasonableClinic/data-eval Release | test 입력·정답(기본 30명 + 변형 34명), 변형 순위 정답, Agent 2 test 근거 v14.9, Agent 3 test 출력·캐시, 채점 기록 |

```bash
git clone https://github.com/ReasonableClinic/Backend.git trialtrace
git clone https://github.com/ReasonableClinic/Healthcare-web.git    # 데모 화면 (trialtrace 옆에 둠)
cd trialtrace
unzip -q <받은 곳>/replay_pack.zip -d replay
unzip -q <받은 곳>/test_pack.zip -d ../trialtrace_test        # test 단계를 볼 때만
```

- 두 zip 안의 `MANIFEST.txt`에 파일마다 sha256·크기가 있습니다.
- `replay_pack`은 레포와 같은 경로로 묶여 있습니다(`data/dev/`, `agents/agent3_judge/runs/` …). `reproduce.sh`는 레포를 `_repro/`에 복사하고 그 위에 `replay/`를 덮어 실행하므로 레포 자체는 바뀌지 않습니다.
- 키·`.env`, 환자 ID 대응표, test 정답은 레포에 없습니다(`.gitignore`가 막음).

```
trialtrace/                        (backend 레포)
  REPRODUCE.md  reproduce.sh
  agents/agent1_criteria/ … agent6_rank/   에이전트 패키지 (아래 표의 고정 버전 그대로, runs/·캐시 제외)
  pipeline/ api/                   통합 파이프라인(backend-0.1.1), API
  scripts/make_packs.sh            Release zip 2개를 만든 스크립트 (팀 내부용)
  replay/                          replay_pack.zip을 푼 곳 (git에 없음)
```

| 구성 | 고정 버전 | 레포 위치 |
| --- | --- | --- |
| Agent 1 기준 구조화 | agent1 (캐시 200개 = dev 197 + 3) | `agents/agent1_criteria/` (캐시는 replay) |
| Agent 2 근거 추출 | v14.12 (dev·데모), v14.9 (test, test_pack) | `agents/agent2_evidence/` (근거 파일은 replay `data/dev/evidence/`) |
| Agent 3 기준별 판정 | a3-0.3.1 + p07 + claude-sonnet-5-5 (dev), a3-0.3.0 (test 출력) | `agents/agent3_judge/` (캐시는 replay `runs/llm_cache/`) |
| Agent 4 검증 | v2 (LLM 없음) | `agents/agent4_verify/` |
| Agent 5 추가 정보 카드 | a5u-0.2.0 + a5j-0.3.1 | `agents/agent5_acquire/` |
| Agent 6 순위·설명 | a6-0.4.14 (dev·데모), a6-0.4.0 + 용어 사전 06fc5ffa… (test) | `agents/agent6_rank/`, a6-0.4.0은 replay `extra/agent6_a6-0.4.0/` |
| 통합 | backend-0.1.1 | `pipeline/`, `api/` |
| 웹 화면 | web_demo_v3.11 (데이터는 backend-0.1.1 출력과 같음) | 별도 레포 Healthcare-web |

## 3. A. 데모

```bash
cp -R replay/. .                   # replay_pack을 레포 위에 덮음 (git에 안 잡히는 경로들)
python3 -m pipeline.build_demo     # data/ 에 데모 묶음 생성, API 호출 없음
cp ../Healthcare-web/data/ko.json ../Healthcare-web/data/card_ko.json data/   # 화면 번역 (서버는 /data/를 data/에서 읽음)
python3 -m api.server              # ../Healthcare-web 화면을 http://localhost:8000 에서 띄움 (다른 곳이면 --web <폴더>)
```

- 환자 SYN-0010: 1차 판정 → 결핵 검사 결과(새 정보 1건) 입력 → 2차 판정. 답한 기준만 다시 판정하고, 결과를 자동 확정하지 않고 의료진 확인으로 넘깁니다.
- 환자 모드와 의료진 모드를 오른쪽 위에서 바꿉니다.
- 빌드 없이 보기: `cd ../Healthcare-web && python3 -m http.server 8000` (그 레포의 `data/`, backend-0.1.1이 만든 묶음 그대로).

## 4. B. 보고 수치 재현 (키 없음)

```bash
bash reproduce.sh                                            # dev + 데모
TRIALTRACE_TEST_DIR=../trialtrace_test bash reproduce.sh     # + test
```

- 시작할 때 API 키 환경변수를 지우고 프록시를 닫힌 주소로 돌려, LLM·네트워크 호출이 생기면 그 단계가 실패합니다. Agent 3은 `run_meta.json`의 호출 수 0(캐시 적중만)을 같이 확인합니다.
- 줄마다 `단계 / 지표 / 기대값 / 실제값 / 결과`를 냅니다. 결과는 `OK`, `KNOWN`(이 고정 버전이 내는 값이고 기대값이 옛 보고 수치인 줄, 5장), `DIFF`(설명되지 않은 차이, 종료 코드 1).
- 각 단계의 전체 출력은 `_repro/logs/`, 실행 결과는 `_repro/agents/*/runs/repro_*`에 남습니다.

| 단계 | 명령 (`_repro/` 안, `D=data/dev`) | 기대값 |
| --- | --- | --- |
| Agent 1 | `cd agents/agent1_criteria && python3 -m agent1 --nct NCT05428488 --out runs/repro_one` / `python3 -m agent1 --saved tests/fixtures/ctgov_response_gastric_HER2.json --no-llm --out runs/repro_offline` | 캐시 적중(API·네트워크 없음), offline 시험 19건·기준 525줄. 캐시와 dev 기준 파일이 같은 줄 3,831/3,856 (5.1) |
| Agent 2 | `python3 agents/agent2_evidence/code/eval_evidence.py --gold $D/gold/gold.jsonl --pred $D/evidence/evidence_dev_haiku_v14_12.jsonl --patients $D/input/patients.jsonl` / `code/eval_concepts.py --gold … --criteria $D/reference/criteria.jsonl --concepts $D/reference/concepts.json --pred …` | 위치 겹침 1.000, 개념 0.904, 값 0.859, 수치 기준 89/89 (5.2) |
| Agent 3 | `cd agents/agent3_judge && python3 -m agent3.run --split dev --llm replay --model claude-sonnet-5-5 --evidence agent3_kit/evidence_dev_haiku_v14_12.jsonl --out runs/repro_dev` (변형: `--patients data/dev/input/patients_variants.jsonl --pairs data/dev/gold/gold_variants.jsonl --evidence agent3_kit/evidence_dev_variants_haiku_v14_12.jsonl`) → `python3 eval/score_dev.py …` | 호출 0(캐시 61 / 113), 출력이 공식 실행과 바이트 단위로 같음, 엄격 일치 83.9% / 82.8%, 시험 판정 87.0% / 89.0% (기본 / 변형) |
| Agent 4 v2 | `cd agents/agent4_verify && PYTHONPATH=. python3 -m agent4 --patients … --trials … --criteria … --evidence <v14.12 기본> --verdicts $D/agent3_out_a031/agent3_out.jsonl --out runs/repro_dev` | 판정 1,044, 바꾼 판정 8, CONFLICT 0→3, 시험 판정 변경 0, evidence_id_mismatch 0 |
| Agent 5 | `cd agents/agent5_acquire && python3 -m agent5.lookup_run cards --agent3 <Agent 4 출력> --split dev --patients … --criteria … --evidence …` (+ `agent5.run cards`, `--include-ineligible` → `eval/score_lookup.py`) | 카드 167장(환자 15명), 환자 114 / 의료진·연구기관 53, 정답 MISSING 커버 80.9%, 새 구역 72.0% |
| Agent 6 | `cd agents/agent6_rank && K=<_repro>/data bash run_dev.sh` | 테스트 46개, 순위 41/55, 첫 시험 43/55, 근거·내용 검사 실패 0, a6_error 0 |
| 데모 | `python3 -m pipeline.build_demo` | SYN-0010 답 후 바뀐 판정 1건(NCT05428488-E09 → UNKNOWN/MISSING), 시험 판정 변화 없음, 카드 24→24, Agent 6 검사 실패 0, 묶음이 backend-0.1.1 원본(replay `results/backend-0.1.1_data/`)과 같음 |
| test (`TRIALTRACE_TEST_DIR`) | a3-0.3.0 test 출력 채점(`score_dev.py --gold <test gold> --criteria <test criteria>`) → Agent 4 v2 → a6-0.4.0 `run_test.sh` (순위 채점 `data/dev/eval/eval_variants.py --data <test>` + 변형 순위 정답) | Agent 3 엄격 80.2%, 시험 판정 75.6%, 반대 방향 오류 12 (0.7%) / Agent 6 순위 39/64, 첫 시험 50/64, 괄호 밖 영어 6.8%·22.9% (사전 있음·없음) / Agent 4 v2를 거친 Agent 6 (새로 기록): 순위 35/64, 첫 시험 49/64, 괄호 밖 영어 6.8%·22.4%, 검사 실패 0 |

### 2026-11-09 빈 폴더 검증

레포 파일 + Release zip 2개만으로 `TRIALTRACE_TEST_DIR=… bash reproduce.sh`를 돌린 결과(macOS, Python 3.13, 약 35초): 45줄 중 41줄 OK, 4줄 KNOWN(5.1·5.2), DIFF 0. Agent 3 dev 재생은 공식 출력과 바이트 단위로 같고 API 호출 0입니다.

## 5. 알려진 차이와 한계

### 5.1 Agent 1 "3,831/3,856줄 일치"는 출처를 찾지 못함

캐시(200개)의 기준 줄을 dev 기준 파일(`data/dev/reference/criteria.jsonl`, 3,856줄)과 줄 전체로 비교하면 **3,796줄**이 같습니다(60줄 다름). 다른 필드는 `answerable_by` 24, `term` 21, `unit` 16, `concept` 10, `complex` 8, `operator` 7, `administrative` 6, `fix_note` 6, `inline_relation` 5, `value` 4, `concept_proposed` 3, `parse_status` 2줄. 구조 필드(concept·operator·value·unit·term·inline_relation·complex·parse_status)만 보면 3,813줄입니다. 3,831이 나오는 비교 방식은 찾지 못했습니다(담당 확인 필요). Agent 1 README의 "196/197", "88/88"도 출처 미확인·옛 값입니다(현재 수치 기준 89/89는 Agent 1 기준 구조 + Agent 2 값 공동 지표, 5.2 참고).

### 5.2 Agent 2 개념 0.904·값 0.859·89/89는 옛 키트 값

이 세 값은 Agent 2 README 기록상 **근거 키트 v14.3 + `synthetic_dev_v5` 정답**(2026-10-22) 점수입니다. 고정 버전(근거 v14.12 + dev_v10 정답·기준)으로 같은 채점기를 돌리면 위치 겹침 1.000, 개념 **0.896**(523/584), 값 **0.851**(497/584), 수치 기준 **88/88**(101개 중 결정 88)입니다. 코드는 고치지 않았습니다. 보고서 값을 v14.12 기준으로 바꿀지 결정이 필요합니다.

### 5.3 그 밖의 한계

- 갱신 고리에서 결핵 기준 E09는 음성 결과 후에도 UNKNOWN/MISSING입니다(Agent 3 `pc:strict_normal_finding_inference`). 화면은 의료진 확인 카드(`[답 받음·의료진 확인 중]`)로 넘깁니다.
- `agents/agent5_acquire/scripts/run_loop.py`(C 단계 갱신 고리)의 Agent 4 경로는 `../agent4_v1`입니다. 데모 데이터는 v2로 돌려도 같습니다(SYN-0010 바꾼 판정 0).
- a6-0.4.14 변조 숫자 검출 72.6%: 새 문장 "국내 N곳", "N상 연구"의 숫자를 내용 검사가 대조하지 않습니다. 틀 문장 데모는 영향 없습니다.
- 웹 화면 v3.11은 v3.2에서 남았던 3가지(`answered_review` 카드를 원래 카드의 후속으로 짝짓기, 환자 모드 "할 일 카드 없이 남음" 태그 제거, `answered_review` 이름표)를 v3.9에서 반영했고, v3.11에서 면책 고지 문구를 확정했습니다. 화면 데이터는 backend-0.1.1 `data/`와 바이트 단위로 같습니다.
- backend-0.1.1 원본 묶음은 Windows에서 만들어져 줄바꿈이 CRLF라, 묶음 안 `evidence_sha256` 값만 다시 만든 묶음과 다릅니다(내용은 같음, `reproduce.sh`가 확인).
- Agent 6 용어 사전은 AI 언어 검토만 거쳤습니다(임상 전문가 검토 전).
- test 점수는 a3-0.3.0 + a6-0.4.0 고정 조합입니다. dev 수치와 버전이 다릅니다. a3-0.3.0 test 실행의 LLM 답 캐시(224개)는 test_pack `agent3_llm_cache_test/`에 기록용으로 있고, 코드가 바뀐 a3-0.3.1로는 재생되지 않습니다.
- 문서 몇 곳(Agent 2·3 README)에 test 환자 ID 하나(SYN-6332)가 기록 수정 사례로 적혀 있습니다. test 파일은 아닙니다.

## 6. C. 전체 재실행 (키 필요)

`reproduce.sh`를 한 번 돌린 뒤 `_repro/` 안에서 합니다(데이터·근거·캐시가 이미 제자리에 있음).

```bash
cd _repro/agents/agent3_judge
cp .env.example .env                     # ANTHROPIC_API_KEY만 입력. .env는 제출물에 넣지 않음
python3 -m agent3.run --split dev --llm anthropic --model claude-sonnet-5-5 \
  --evidence agent3_kit/evidence_dev_haiku_v14_12.jsonl --out runs/dev_rerun      # 54쌍, 받은 답은 캐시에 쌓임
cd ../agent5_acquire && python3 scripts/run_loop.py --help                         # 갱신 고리 SYN-0010 (Agent 2 → 3 → 4 → 카드)
```

- `agents/agent3_judge/scripts/run_dev.sh`는 받은 zip 4개와 파일을 대조(`check_inputs.py`)하므로 zip이 없는 이 묶음에서는 위처럼 `agent3.run`을 직접 부릅니다.
- Agent 2 Haiku 재추출 절차는 `agents/agent2_evidence/agent2/RUN_LOCAL.md`, Agent 1 새 시험 구조화는 `agents/agent1_criteria/README.md`.
