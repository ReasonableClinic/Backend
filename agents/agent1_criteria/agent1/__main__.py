"""CLI.

  python3 -m agent1 --nct NCT06880770                      # 한 시험
  python3 -m agent1 --condition "Graves disease" --age 29 --sex female --max 5
  python3 -m agent1 --saved tests/fixtures/ctgov_response_gastric_HER2.json --no-llm   # 네트워크·API 없이 규칙 단계만
  python3 -m agent1 --import-structured ref/dev/reference/trials.jsonl out/dev_v2/criteria.jsonl   # 기존 ①-b 를 캐시로

출력: --out 폴더에 trials.jsonl, criteria.jsonl, run_log.json
"""
import argparse, json
from pathlib import Path
from .agent import TrialParsingAgent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nct")
    ap.add_argument("--condition")
    ap.add_argument("--term", default="")
    ap.add_argument("--age", type=float)
    ap.add_argument("--sex")
    ap.add_argument("--max", type=int, default=10)
    ap.add_argument("--saved", help="저장된 API 응답 JSON")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--out", default="runs/latest")
    ap.add_argument("--import-structured", nargs=2, metavar=("TRIALS_JSONL", "CRITERIA_JSONL"))
    a = ap.parse_args()

    agent = TrialParsingAgent(model=a.model, use_llm=not a.no_llm)
    if a.import_structured:
        n = agent.import_structured(*a.import_structured)
        print(f"캐시 적재 {n}건 → {agent.cache_dir}")
        return
    res = agent.run(nct_id=a.nct, condition=a.condition, term=a.term, age=a.age, sex=a.sex, saved=a.saved, max_trials=a.max)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    with open(out / "trials.jsonl", "w", encoding="utf-8") as f:
        for t in res.trials:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with open(out / "criteria.jsonl", "w", encoding="utf-8") as f:
        for c in res.criteria:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump(res.to_dict()["log"] + [{"concept_proposals": dict(res.proposals)}], open(out / "run_log.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for s in res.log:
        print(f"[{s.status:7}] {s.name:28} {s.detail}  ({s.seconds:.1f}s)")
    print(f"→ {out}")


if __name__ == "__main__":
    main()
