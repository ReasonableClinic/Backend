# p08 dev 실행 — Message Batches로 (API 키 있는 쪽에서)

`export/requests_dev_*.jsonl`은 Anthropic Message Batches 요청 형식(`custom_id`, `params`) 한 줄에 한 호출입니다. 키는 환경 변수로만 (`export ANTHROPIC_API_KEY=...`).

```bash
# 1) 배치 제출 (파일마다 하나씩; 각 61건)
python3 - <<'EOF'
import json, os, sys, urllib.request
for name in ["sonnet_p08_r1", "sonnet_p08_r2", "haiku45_p08_r1"]:
    reqs = [json.loads(l) for l in open(f"export/requests_dev_{name}.jsonl", encoding="utf-8")]
    body = {"requests": [{"custom_id": r["custom_id"], "params": r["params"]} for r in reqs]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages/batches", data=json.dumps(body).encode(),
          headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01", "content-type": "application/json"})
    out = json.load(urllib.request.urlopen(req))
    print(name, out["id"]); open(f"export/batch_id_{name}.txt", "w").write(out["id"])
EOF

# 2) 끝나면 결과(.jsonl) 내려받기 — 콘솔에서 받거나 results_url 사용
#    export/results_dev_sonnet_p08_r1.jsonl 등으로 저장

# 3) 캐시에 넣기 (요청 파일을 캐시 폴더에 export_requests.jsonl로 두어야 메타가 붙음)
for n in sonnet_p08_r1 sonnet_p08_r2 haiku45_p08_r1; do
  cp export/requests_dev_$n.jsonl runs/llm_cache/export_requests.jsonl
  python3 -m agent3.ingest --results export/results_dev_$n.jsonl
done
rm runs/llm_cache/export_requests.jsonl

# 4) 재생 실행 + 채점 (API 호출 없음)
python3 -m agent3.run --split dev --llm replay --model claude-sonnet-5-5 --out runs/dev_sonnet55_p08_r1
python3 -m agent3.run --split dev --llm replay --model claude-sonnet-5-5 --salt r2 --out runs/dev_sonnet55_p08_r2
python3 -m agent3.run --split dev --llm replay --model claude-haiku-4-5-20251001 --out runs/dev_haiku45_p08_r1
for d in dev_sonnet55_p08_r1 dev_sonnet55_p08_r2 dev_haiku45_p08_r1; do
  python3 eval/score_dev.py runs/$d/agent3_out.jsonl --md runs/$d/score.md --json runs/$d/score.json
  python3 eval/score_dev.py runs/$d/agent3_out.jsonl --gold data/dev/gold/gold_A1_assumed.jsonl --md runs/$d/score_A1assumed.md
done
```

대안: 키를 이 작업 환경에 환경 변수로 주면 `--llm anthropic`으로 직접 돌립니다(프롬프트 캐시가 걸려 live가 배치보다 비싸지 않을 수 있음; v2 dev 1회 ≈ $6).

주의
- `--salt r2`는 같은 프롬프트의 두 번째 실행을 캐시에서 구분하는 소금입니다. 재생 때도 같은 소금을 줘야 합니다.
- 결과 파일에 `succeeded`가 아닌 행이 있으면 ingest가 건너뛰고 개수를 알려 줍니다. 그 호출만 `--llm anthropic`으로 채우면 됩니다(캐시 미스만 호출).
- test 환자 기록은 열지 않습니다. test 실행은 버전 고정 뒤, Agent 2 test 근거를 받은 다음 1회.
