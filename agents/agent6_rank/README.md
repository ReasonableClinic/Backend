# Agent 6 — 추천 순위, 브리핑

Evidence Graph를 읽어 환자별 시험 순위를 매기고(공통 형식 6.4), 의료진용 상세와 환자용 쉬운 설명을 만듭니다. 그래프에 없는 내용은 덧붙이지 않고, 효과를 약속하는 표현은 쓰지 않습니다.

## 현재 버전
개발 전

## 입력 / 출력 (`run(inputs, out_dir, config)`의 키)

| 입력 키 | 파일 |
| --- | --- |
| `judgments` | 최종 판정 jsonl |
| `graph` | graph/ |
| `trials` | trials.jsonl |

| 출력 키 | 파일 |
| --- | --- |
| `ranking` | ranking.jsonl |
| `briefing` | briefing/{patient_id}.json |

## dev 실행 (한 줄)

```bash
# 예: python3 -m agents.agent6_rank.run --input patients=data/dev/input/patients.jsonl --out runs/agent6_dev
```

## 모듈화 전후 확인 기준
<!-- 원본 코드로 낸 dev 출력 하나와, API 없이 같은 결과를 내는 방법 (mock, 캐시 재생 등) -->

## 원본 코드
<!-- 지금 확정판을 이 폴더에 그대로 넣고, 원래 실행 방법을 여기에 적습니다. run.py는 원래 코드를 부르기만 하면 됩니다. -->

## 담당
<!-- 이름 -->
