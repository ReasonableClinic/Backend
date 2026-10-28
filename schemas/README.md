# schemas

| 파일 | 내용 |
| --- | --- |
| `common_format_v0.5.md` | 공통 형식 (⓪ 시험, ① 기준, ② 환자 기록, ③ 근거, ④ 판정·정답, 6장 판정 규칙, 7장 변형). 2026-10-27판 (6.3 측정일 보완) |
| `validate_patients.py` | ② 환자 기록 형식 검사: `python3 schemas/validate_patients.py data/dev/input/patients.jsonl` |
| `check_format.py` | (준비 중, 데이터 담당) ③ 근거, ④ 에이전트 3·4 출력, 카드 형식 검사. 각 에이전트 출력이 형식에 맞는지 모듈화 때 바로 확인하는 용도 |

형식을 바꿀 때는 데이터 담당과 먼저 정하고 이 문서의 변경 기록에 적습니다.
