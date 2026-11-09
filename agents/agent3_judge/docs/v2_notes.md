# Agent 3 v2 작업 메모 (2026-10-23)

## 설계 결정 (dev 정답과 대조해서 정함)

| 결정 | 근거 |
| --- | --- |
| 측정일 = 그 값이 기록에 처음 나온 날 | 9월 진료 기록이 2월 심초음파 LVEF 28%를 다시 적으면 Agent 2 근거 날짜는 9월. 정답은 2월 기준 EXPIRED. ALT도 옛 값(112)을 재인용한 줄이 최신 값(74)보다 뒤에 있어 "최신 근거"를 고르면 틀림 |
| `complex` 줄은 코드가 확정하지 않음 | 구조화된 부분만으로 확정한 13건 중 3건 오답(OR 선택지 안의 AND 중첩, 다른 기간의 값), 그중 1건이 반대 방향 오류 |
| 값이 없으면 코드가 MISSING을 내지 않음 | 24건 중 11건은 정답이 이웃 사실로 판정 ("no cirrhosis" → Child-Pugh 기준 PASS) |
| 기간 없는 수치 기준의 기본 신선도: 영상만 90일 | 정답은 35일 된 eGFR, 176일 된 혈당을 PASS로 인정. LVEF(심초음파)만 EXPIRED |
| x ULN인데 `ref_high`가 없으면 LLM에 넘김 | 참고 범위가 줄 텍스트에 있는 경우("ALT 74 U/L (ref 7-55)")를 LLM이 읽음 (규칙 13) |
| "fasting", "seated" 같은 측정 조건은 LLM에 넘김 | "Fasting LDL <= 130": 값은 맞지만 정답은 공복 여부 미확인으로 MISSING |

## 정답 담당에게 확인 요청

- SYN-0010 × NCT05428488-I05 "DAS28-CRP > 3.2 … CRP dated less than 7 days from baseline": DAS28 5.1이 as_of 기준 21일 전. ①-b `time_window` 7일로 코드는 UNKNOWN/EXPIRED, 정답은 PASS. 기준의 7일이 baseline(미래 방문) 기준이라 as_of 기준 신선도와 다른 뜻인지 확인 필요.
- 행정 항목(`administrative: true`)인데 정답이 PASS인 기준 21행: 코드는 메모 2.1대로 UNKNOWN/MISSING. 정답이 기록으로 판정한 행정 항목(예: 보관 조직 있음)이면 `administrative`를 false로 바꾸는 게 맞는지 확인.

## LLM 단계 결과 (2026-10-23 밤, Sonnet 5.5)

- dev: README 표. p06 엄격 정책이 v2 기준 버전 (기준 일치 83.0%, 반대 방향 0, 시험 판정 87.0%, eligible 재현율 3/5).
- 남은 반대 방향 오류 후보: p05에서 SYN-0011 NCT06692738-I03 (KRAS G12V를 "승인된 표적치료가 있는 driver mutation"으로 봄 — G12C만 승인됨). p06에서는 나오지 않았지만 모델 지식 문제라 재발 가능. Agent 4가 잡을 영역.
- TrialGPT 반대 방향 0.39%, TREC "제외인데 eligible" 4% → 두 합격선 통과.
- 비용: dev 2회 + TrialGPT + TREC 합쳐 토큰 약 480만 (대부분 캐시 읽기), 대략 $20 안팎.

## 다음

1. ~~dev 실행, v1 vs v2 비교표~~ 완료. ~~TrialGPT·TREC~~ 완료 (동의 진술은 split 예외가 아니라 일반 규칙으로: 기록에 "will provide informed consent and comply" 문장이 있으면 그 줄을 인용해 PASS, `rules.py` 4번·프롬프트 규칙 14)
2. A3 규칙("나열 항목 중 일부만 확인되면 UNKNOWN") 적용 기준 목록 추출 → 정답 담당에게 전달
3. 확정 정답을 UNKNOWN으로 남긴 129건 분류 (`score.json`의 `missed_list`): 일괄 부정 81건은 A1 확정 후 정답 반영으로 해소, 목록 추론 52건은 관대 점수, 나머지를 프롬프트로
4. 기준별 근거 선별(`agent2/evidence_index.py for_criterion`)을 프롬프트에 넣어 토큰·정확도 비교
5. 모델 비교 (Haiku 4.5), 2회 실행 재현성 (D3)
