# test 채점 실행 안내 (에이전트 6 a6-0.4.0 → 합성 담당)

에이전트 6 쪽은 test 파일을 갖지 않습니다. 이 고정 패키지를 합성 담당이 test에 **1회** 돌리고, **점수와 검사 요약(`SUMMARY.txt`)만** 돌려주시면 됩니다. API 키는 필요 없습니다(틀 문장 브리핑).

## 고정 값

| 항목 | 값 |
| --- | --- |
| 코드 + 사전 (한 쌍) | **a6-0.4.0** + `06fc5ffa26d3e447baa02050401cfbec94c07a17da1656ce6917637826d032fe` (`VERSION.md`) |
| 패키지 | `agent6_a6-0.4.0.zip` (zip sha256은 함께 보내는 `agent6_a6-0.4.0.zip.sha256`) |
| 패키지 안 파일 | `MANIFEST.sha256` (실행할 때 `sha256sum -c`로 확인) |
| 용어 사전 | `agent6/glossary.csv` 1,043행, sha256 `06fc5ffa26d3e447baa02050401cfbec94c07a17da1656ce6917637826d032fe` |
| 에이전트 2 근거 | **v14.9 고정** (에이전트 3 test 실행이 쓴 버전) |

## 실행

```bash
unzip agent6_a6-0.4.0.zip && cd agent6_a6-0.4.0
A3="<에이전트 3 test 출력 agent3_out.jsonl ...>" \
G="<에이전트 3 test graph 폴더 ...>" \
TR="<test reference trials.jsonl>" \
EV="<에이전트 3 test 실행이 읽은 에이전트 2 근거 v14.9 .jsonl (LLM 추출. 규칙 추출 파일은 넣지 않음)>" \
SCORE_CMD='<순위 채점 명령. $RANKING(순위 파일)·$PRED(에이전트 3 출력)를 쓸 수 있음>' \
GOLD="<test gold 폴더 (있으면)>" \
bash run_test.sh
```

- `SCORE_CMD` 예 (dev와 같은 채점기): `python3 <test 데이터>/eval/eval_variants.py --data <test 데이터> --pred $PRED --ranking $RANKING`
- 실행이 하는 일:
  1. 패키지 파일 해시, 사전 고정, 사전 sha256, 근거 파일 이름 v14.9를 확인하고 단위 테스트를 돌립니다. 하나라도 다르면 멈춥니다.
  2. 순위를 만들고 채점합니다.
  3. 브리핑을 **사전 있음**과 **사전 없음**(`AGENT6_GLOSSARY=none`) 두 조건으로 만들고 각각 검사합니다(`check_grounding`·`check_content`·변조 시험·읽기 지표, gold가 있으면 두 정답 대조).
- 근거 파일을 읽을 때 그래프 근거 노드와 ID·진단명이 모두 맞는지 대조합니다. 버전이 다르면 브리핑을 쓰기 전에 멈춥니다.
- 에이전트 2의 LLM 추출과 규칙 추출은 근거 번호를 따로 매겨서, 같은 ID가 두 파일에서 다른 근거를 가리킵니다(dev v14.9: 함께 있는 9,621개 중 9,438개). 그래서 **에이전트 3 test 실행이 읽은 파일만** 넣어 주세요. 두 파일에 같은 ID가 있으면 멈춥니다.

## 돌려주실 것

- `runs/test_a6/SUMMARY.txt` 한 파일

`SUMMARY.txt`에는 합계 줄만 들어갑니다. 파일별 실패 줄(문장 일부가 들어감), 브리핑, 순위 파일, `full.log`는 합성 담당 쪽에 두세요. 실패가 있으면 개수만 알려 주시면 됩니다. 원인을 봐야 하면 따로 정합니다.
