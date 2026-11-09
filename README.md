# 임상시험 매칭 에이전트 — backend

환자 기록과 임상시험 기준을 비교해, 판정마다 근거를 붙인 **Evidence Graph**를 만드는 에이전트 묶음입니다.
웹 화면은 별도 레포 [Healthcare-web](https://github.com/ReasonableClinic/Healthcare-web)(web_demo_v3.12)에 있고, test 정답·채점은 data-eval 레포 Release `test_pack.zip`에 있습니다.

## 흐름

```
① 기준(CT.gov) ─┐
                 ├─> agent3 판정 ─> agent4 검증 ─> agent5 정보 획득 ─┐
② 환자 기록 ────┘        ^                                          │ 답 → 새 기록 문서
   agent2 근거 추출 ─────┘<───────────── agent2 부분 재추출 <────────┘
                                                    agent6 추천·브리핑 ─> api ─> frontend
```

- 모든 에이전트는 Evidence Graph(공통 형식 파일)를 통해서만 결과를 주고받습니다. 다른 에이전트의 내부 함수를 직접 부르지 않습니다.
- 실행 순서, 버전 기록, 5번 고리(질문 → 재추출 → 재판정)는 `pipeline/`이 맡습니다.
- 형식은 `schemas/common_format_v0.5.md`가 기준입니다.

## 폴더

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `common/` | 두 에이전트 이상이 쓰는 코드: `.env` 읽기(`env_setup.py`), Langfuse 추적(`tracing.py`). LLM 호출·개념 사전·날짜 처리는 모듈화 때 여기로 모음 | 정리 담당 |
| `schemas/` | 공통 형식 문서, 형식 검사기 | 데이터 담당 |
| `agents/agent1_criteria/` | ① CT.gov 수집, 기준 구조화(①-b) | 팀원 1 |
| `agents/agent2_evidence/` | ③ 환자 기록 → 근거 추출 | 에이전트 2 담당 |
| `agents/agent3_judge/` | ④ 기준별 판정, 시험 판정 집계, Evidence Graph 작성 | 팀원 2 |
| `agents/agent4_verify/` | 판정 검증 (확정 → 보류로만 내림) | 에이전트 4 담당 |
| `agents/agent5_acquire/` | UNKNOWN 보완: `expired_unsupported/`(검사 안내·의사 확인, CONFLICT 포함), `missing/`(기록 찾기·환자 질문) | 에이전트 5 담당 2명 |
| `agents/agent6_rank/` | 추천 순위, 의료진용·환자용 브리핑 | 에이전트 6 담당 |
| `pipeline/` | 오케스트레이터: 실행 순서, 실행 기록(manifest), 부분 재실행, 5번 고리 | 정리 담당 |
| `api/` | frontend에 그래프를 보내는 API (나중) | 미정 |
| `data/dev/` | dev 입력·참조를 놓는 자리 (파일은 리포에 올리지 않음, zip으로 받음) | 데이터 담당 |
| `tests/` | 뼈대 규칙 검사, 에이전트별 테스트 | 공통 |

## 올리는 규칙

1. **자기 폴더에 지금 확정판을 그대로** 넣습니다. 안쪽 코드는 지금 구조에 맞추지 않아도 됩니다.
2. 폴더마다 세 가지만 맞춥니다.
   - `README.md`: 하는 일, 입력·출력 파일, dev 실행 명령 한 줄, 현재 버전 (틀이 들어 있음)
   - `run.py`의 `run(inputs, out_dir, config)`: pipeline이 부르는 진입점 하나. 안에서 원래 코드를 부르면 됨
   - 키는 직접 읽지 않고 `common/env_setup.py`의 `load_env()`
3. 새 폴더는 자유롭게 만들되 위 세 가지를 따릅니다. **두 에이전트 이상이 쓰는 코드는 `common/`**에 넣습니다.
4. **올리면 안 되는 것**: `.env`·API 키, test 정답, 환자 ID 대응표(`id_map*`, `*private*`), LLM 응답 캐시, 실행 결과(`runs/`). `.gitignore`가 막아 주지만 `git status`로 한 번 확인합니다.
5. 같이 올릴 것: dev 실행 명령과 그 출력 하나(예: `agents/agent3_judge/expected/` 아래 작은 파일 또는 해시). 모듈화 전후 결과가 같은지 확인하는 기준이 됩니다.

## 작업 방식

- main에 직접 push하지 않고 브랜치 → Pull Request → 한 명 확인 후 병합 (무료 Organization이라 강제는 안 됨, 팀 약속)
- 정리(모듈화) 중에는 원본을 각자 따로 고치지 않습니다. 고칠 것은 정리 담당에게 알리거나 정리 후 정리본에서 고칩니다.
- 모듈화 기준: **모듈화 전후 dev 출력이 같을 것**. 에이전트 2는 `--provider mock`, 에이전트 3은 `--llm replay`(캐시)로 API 없이 비교합니다.

## 시작하기

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install python-dotenv "langfuse>=5,<6"     # 둘 다 선택. 없어도 동작
cp .env.example .env                                       # 쓰는 키만 채움
python3 -m unittest discover -s tests                      # 뼈대 규칙 검사
```

- 전체 실행: `python3 -m pipeline.run_pipeline --data data/dev --evidence data/dev/evidence/evidence_dev_haiku_v14_12.jsonl --out runs/pipeline_dev` (Agent 3 → 4 → 5 → 6, 키 없이 replay. `replay_pack.zip`을 레포 위에 푼 뒤). 보고 수치 확인: `bash reproduce.sh`. 자세한 것은 [REPRODUCE.md](REPRODUCE.md).

## 현재 버전 (2026-11-09, 제출 고정)

| 구성 | 확정 버전 | 비고 |
| --- | --- | --- |
| 1 | agent1 (캐시 200개 = dev 197 + 3) | `agents/agent1_criteria/`, 캐시는 Release `replay_pack.zip` |
| 2 | v14.12 (dev·데모), test 근거 v14.9 고정 | 근거 파일은 Release zip |
| 3 | a3-0.3.1 + p07 + claude-sonnet-5-5 (dev), test 출력은 a3-0.3.0 | LLM 답 캐시는 Release zip (`--llm replay`) |
| 4 | v2 (LLM 없음) | |
| 5 | a5u-0.2.0 + a5j-0.3.1 | |
| 6 | a6-0.4.14 (데모·dev), a6-0.4.0 + 사전 06fc5ffa… (test) | a6-0.4.0은 `replay_pack.zip`의 `extra/` |
| 통합 | 통합 최종 11/09 (`pipeline/`, `api/`, backend-0.1.1 다음 판) | 경로만 레포 안으로, 화면 폴더는 `../Healthcare-web` (`pipeline/config.py`) |
| 웹 | web_demo_v3.12 (별도 레포 Healthcare-web) | 데이터는 통합 최종 출력과 같음. `api.server`가 옆 폴더 `../Healthcare-web`을 `/`로 띄우고, `build_demo`가 그 번역 2개를 `data/`로 복사 |

평가자 실행·재현 방법: [REPRODUCE.md](REPRODUCE.md) (`bash reproduce.sh`, API 키 없음).
