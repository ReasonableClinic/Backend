# 에이전트 2 test 근거 (2026-10-25, 키트 v14.7 규약, 10-26 v14.8 날짜 보정, v14.9 기록 수정 반영)

에이전트 3 `a3-0.3.0` 고정 후 한 번만 추출했습니다. test 정답은 보지 않았습니다. 입력은 합성 담당 `for_agent2_test.zip` 10-25 저녁 수정판(행정 14행 `administrative: false`)과 바이트 단위로 같은 파일입니다. 수정 전 기준으로 한 번 돌린 뒤, 응답 캐시를 그대로 쓰고 프롬프트가 바뀐 요청만 다시 보내 이 기준에 맞췄습니다(기본 30명 중 7명의 근거가 달라짐).

| 파일 | 환자 | 근거 | 방법 |
| --- | --- | --- | --- |
| `agent3_kit/evidence_test_haiku_v14_9.jsonl` | 기본 30명 | 9,724 | Haiku 4.5 배치 + 규칙 |
| `agent3_kit/evidence_test_rules_v14_9.jsonl` | 기본 30명 | 7,135 | 규칙만 (대체용) |
| `agent3_kit/evidence_test_variants_haiku_v14_9.jsonl` | 변형 34명 | 11,017 | 같은 문서는 기본 환자 근거를 옮기고, 바뀐 문서만 Haiku |
| `agent3_kit/evidence_test_variants_rules_v14_9.jsonl` | 변형 34명 | 8,268 | 같은 방식, 규칙만 |

네 파일 모두 원문 위치 불일치·기준일 이후 날짜·중복 ID·빠진 환자 0. 규약은 dev 키트 v14.7과 같습니다 (결과 대기 = `"pending"`, 기록 안 됨 = `null`). 조회 코드(`agent2/evidence_index.py`)와 개념 사전은 dev 키트 v14.7의 것을 그대로 씁니다.

**v14.8 (10-26)**: 연도 없는 "on M/D", "(M/D)", 패널 머리말 "Lipids (06/10):" 날짜를 값의 측정일로 고침(모델 재실행 없음, 근거 ID 그대로). 바뀐 행은 `*.changes_from_v14_7.jsonl` (test 7, test 변형 10, 규칙판 같은 수).

**v14.9 (10-26)**: 합성 담당의 기록 수정 반영(모델 재실행 없음, 근거 ID 그대로). 변형 환자 문서 번호를 날짜 순으로 다시 매긴 표대로 `source.doc_id` 변경, SYN-6332(와 그 변형)의 "TTE on file (LVEF 61% on 2026-03-20"·"baseline (03/20)" 문구와 그 날짜를 `source.text`·`observed_date`에 반영. 바뀐 행은 `*.changes_from_v14_8.jsonl`. 새 환자 파일 기준 원문 위치 불일치 0.
