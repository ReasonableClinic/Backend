# Agent 3 → Agent 4 인계 (2026-10-25)

## 바뀐 것

Agent 3 v3부터 **자기 판정을 검증하지 않습니다.** v2에 있던 후검사 격하(아래 표)는 모두 빠졌고, 같은 검사는 Agent 4가 합니다(노션 "Agent 4 역할" 검사 1~4). v2 코드는 `postcheck_v2_reference.py`에 참고용으로만 두었고 실행되지 않습니다.

| v2 후검사 | Agent 4 대응 | v2 dev에서 작동한 횟수 |
| --- | --- | --- |
| PASS/FAIL인데 유효 근거 0 → UNKNOWN/MISSING | 검사 1 (grounding) | 0 |
| 인용 ID가 근거 파일에 없음 → 제거 | 검사 1 | 0 |
| 가족력만·계획만·의심만으로 확정 → UNSUPPORTED | 검사 2 (근거 적합성) 확장 | plan_only 2 |
| 판단 용어 FAIL인데 정도 미기록 → UNSUPPORTED | 검사 2 | 1 |
| 노트가 모호("arguable")한데 확정 → UNSUPPORTED | (추가 검토) | 1 |
| 창 밖 수치만 인용 → EXPIRED | 검사 3 (만료) | 0 |
| 같은 개념 상반 값 → `flag:possible_conflict` | 검사 4 (충돌) | — |

## Agent 3 v3 출력에서 볼 필드 (`agent3_out.jsonl` → `criteria[]`)

- `status`, `reason`, `action`, `evidence_ids` — 공통 형식 어휘 그대로.
- `evidence_ids`에는 **근거 파일에 존재하는 ID만** 들어갑니다(그래프가 ID를 풀어야 하므로). LLM이 지어낸 ID나 다른 환자 ID는 `cited_ids_invalid`에 그대로 남고 `rule_tags`에 `pc:dropped_unknown_ids`가 붙습니다. 상태는 바꾸지 않았으므로 **PASS/FAIL인데 `evidence_ids`가 빈 행이 올 수 있습니다** — 검사 1이 잡아야 할 행입니다.
- `rule_tags`: `blanket_negation`, `list_inference`, `normal_finding_inference`(LLM이 붙인 추론 표시), `pc:strict_*`·`pc:blanket_out_of_scope`(팀 정책으로 Agent 3이 UNKNOWN으로 내린 행; 노트에 `[... would give PASS]`로 원 판정이 남음), `code:*`(①-b 코드 판정).
- `severity_documented`, `derived_from`, `missing_fact`, `note` — v2와 같음.
- `graph/{patient_id}.json`: decision 노드에 위 상태가 그대로 들어감. Agent 4는 `verification` 노드를 붙이고, 격하 시 `verified:false`, `original_status`, `downgrade_reason`을 기록(노션 Agent 4 역할 3장 형식).

## 추가로 꼭 넣어 달라는 검사 (v3 dev 실행에서 확인)

- **노트-상태 일치**: 노트에 "arguable", "borderline", "partly settled", "no longer met", "not met"처럼 쓰고 상태를 PASS/FAIL로 낸 행 → UNKNOWN/UNSUPPORTED + clinician_confirmation. 10/25 dev 실행의 반대 방향 오류 절반이 이 유형이고, 근거 인용은 정확해서 검사 1~3으로는 안 잡힙니다. v2 `postcheck_v2_reference.py`의 `HEDGE_RX`(+ borderline, not met)를 그대로 옮기면 됩니다.
- **모델 외부 지식에 기댄 FAIL**: "KRAS G12V는 승인 표적치료가 있다"처럼 기록에 없는 의학 지식으로 FAIL을 낸 경우. 코드로 잡기 어려우니, 바이오마커·약물 승인 여부가 걸린 기준의 FAIL은 clinician_confirmation으로 보내는 규칙을 검토해 주세요.

## 입력 예시

- 기본 54쌍: `handoff_agent4/dev_agent3_out_v3_p07/` (v3 고정판, a3-0.3.0 + p07, 2026-10-25 1회차). 변형 세트 페이지의 `agent3_out_v2_p06`를 이것으로 교체해 주세요.
- 변형 100쌍: Agent 4 담당이 요청하는 시점에 Agent 3이 1회 실행해서 전달(B안, 10/25 결정).
