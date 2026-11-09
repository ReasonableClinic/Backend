# v1 검토 메모 (dev, Sonnet 5.5 + p04)

작성 2026-10-08. `runs/dev_sonnet55_p04/score.json`에서 뽑았습니다. 각 행을 누구에게 넘길지 표시했습니다.

## 반대 방향 오류 3건 (합성 담당에게 정답 확인 요청)

| 환자 | 기준 | 원문 | 정답 | Agent 3 | Agent 3 설명 | 의견 |
| --- | --- | --- | --- | --- | --- | --- |
| SYN-0007 | NCT07267169-I07 | Heart rate >= 90/min | PASS | FAIL | Current HR is 78. The admission HR of 108 has resolved. | 같은 시험의 I05·I09는 정답이 현재 값으로 FAIL, I07·I08은 입원 시 값으로 PASS. 기준 시점을 하나로 정해야 함 |
| SYN-0007 | NCT07267169-I08 | Respiratory rate >= 20/min or hyperventilation with PaCO₂ <= 32 mmHg | PASS | FAIL | Current RR is 16. The admission RR of 20 has resolved. No PaCO2 is recorded. | 위와 같음 |
| SYN-0003 | NCT06997874-I04 | Pars plana vitrectomy is planned to repair their RRD | PASS | FAIL | PPV already performed 2026-09-26, so no PPV is planned to repair the RRD. | 유리체절제술이 이미 시행됨. '계획됨'을 이미 받은 경우까지 포함하는지 정답 확인 필요 |

## 시험 판정이 다른 쌍 (Agent 3 개선 과제)

| 환자 | 시험 | 정답 | Agent 3 | 막은 기준 (Agent 3 판정 / 정답) |
| --- | --- | --- | --- | --- |
| SYN-0018 | NCT07230288 | eligible | potential | NCT07230288-I01 UNKNOWN/UNSUPPORTED / PASS/VALID |
| SYN-0011 | NCT04928846 | ineligible | potential | NCT04928846-I01 UNKNOWN/MISSING / UNKNOWN/MISSING; NCT04928846-I02 UNKNOWN/MISSING / UNKNOWN/MISSING; NCT04928846-I07 UNKNOWN/EXPIRED / UNKNOWN/EXPIRED; NCT04928846-I10 UNKNOWN/UNSUPPORTED / FAIL/VIOLATED |
| SYN-0012 | NCT07365358 | potential | eligible |  |
| SYN-0017 | NCT06982521 | eligible | potential | NCT06982521-I05 UNKNOWN/UNSUPPORTED / PASS/VALID |
| SYN-0011 | NCT07144280 | ineligible | potential | NCT07144280-I06 UNKNOWN/UNSUPPORTED / FAIL/VIOLATED; NCT07144280-E02 UNKNOWN/EXPIRED / UNKNOWN/EXPIRED |
| SYN-0018 | NCT07652658 | eligible | potential | NCT07652658-I03 UNKNOWN/UNSUPPORTED / PASS/VALID; NCT07652658-I05 UNKNOWN/UNSUPPORTED / PASS/VALID |
| SYN-0010 | NCT02714634 | eligible | potential | NCT02714634-I01 UNKNOWN/UNSUPPORTED / PASS/VALID; NCT02714634-E01 UNKNOWN/UNSUPPORTED / PASS/VALID; NCT02714634-E06 UNKNOWN/UNSUPPORTED / PASS/VALID |
| SYN-0004 | NCT06600412 | ineligible | potential | NCT06600412-I02 UNKNOWN/UNSUPPORTED / PASS/VALID; NCT06600412-I04 UNKNOWN/UNSUPPORTED / FAIL/VIOLATED; NCT06600412-I08 UNKNOWN/MISSING / UNKNOWN/MISSING; NCT06600412-E04 UNKNOWN/UNSUPPORTED / PASS/VALID |
| SYN-0002 | NCT06582017 | ineligible | potential | NCT06582017-I01 UNKNOWN/UNSUPPORTED / FAIL/VIOLATED; NCT06582017-I05 UNKNOWN/UNSUPPORTED / UNKNOWN/UNSUPPORTED; NCT06582017-I06 UNKNOWN/MISSING / UNKNOWN/MISSING; NCT06582017-E06 UNKNOWN/UNSUPPORTED / UNKNOWN/UNSUPPORTED |

정답이 eligible인데 potential이 된 쌍은 대부분 정답 PASS 또는 MISSING인 기준을 Agent 3이 UNSUPPORTED로 둔 경우입니다. 정답이 ineligible인데 potential이 된 쌍은 정답 FAIL 기준을 Agent 3이 UNKNOWN으로 남긴 경우입니다(보수적 방향, 반대 방향 오류는 아님).

SYN-0012 × NCT07365358은 반대로 정답 potential을 eligible로 냈습니다. 정답이 UNKNOWN인 기준을 Agent 3이 확정한 경우라 덜 보수적인 쪽의 오류이니, 다음 개선 때 먼저 확인하세요.

## 숫자로 본 남은 과제

- 확정 정답을 UNKNOWN으로 남김: 123 / 545 (주로 Agent 3 개선, 일부는 Agent 2 근거 누락 확인 필요)
- 정답 UNKNOWN을 확정 판정: 26건 (목록·일괄 부정 추론이 섞임. 팀 결정 후 다시 집계)
- UNKNOWN 행동 일치: 56.0% (Agent 5가 생기면 행동 기준 합의)
