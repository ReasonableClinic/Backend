# 에이전트 5 카드 예시 (dev 기본, 2026-10-30 기준)

- `a5u_expired_unsupported_dev_cards.jsonl`: 운주 a5u-0.2.0. 검사 안내(`new_test`), 의사 확인(`clinician_confirmation`), CONFLICT 확인
- `a5j_missing_dev_cards.jsonl`: 준상 a5j-0.1.0. 기록 찾기, 과거력 확인, 검사 결과 찾기, 환자 질문. `priority.safety_check_of`는 시험을 막지 않는 제외 기준 확인

둘 다 에이전트 3 a3-0.3.0 dev 출력으로 만든 것입니다. 카드 `items[].trial_id`·`criterion_id`가 그래프의 `dec:<trial>:<criterion>:r1`과 이어집니다. 형식은 아직 바뀔 수 있으니, 브리핑에서 카드를 참조하려면 에이전트 5 두 명과 먼저 맞춰 주세요.
