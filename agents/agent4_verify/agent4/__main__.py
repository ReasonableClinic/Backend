"""CLI.

  python3 -m agent4 --patients ref/dev/input/patients.jsonl --trials ref/dev/reference/trials.jsonl \
                    --criteria stage_1b/out/dev_v3/criteria.jsonl --evidence agent2/evidence_dev.jsonl \
                    --verdicts agent3/out_dev.jsonl --out runs/dev [--patient SYN-0001] [--default-windows]

  python3 -m agent4 --fixture tests/fixture --out runs/fixture        # 합성 예시로 동작 확인

출력 (--out 폴더)
  graph/<pid>.json      Agent 3 그래프 형식 (a3format.to_agent3_graph). Agent 3 graph/ 가 있으면 그 위에 r2 판정·라벨을 더한다
  agent3_out.jsonl      입력 판정 + 격하 반영 + 시험 판정 다시 계산 (a3format.to_agent3_out_row)
  graph_<pid>.json      Agent 4 내부 그래프 (EvidenceGraph)
  verify_report.json    전체 요약 (사전 점검 preflight 포함)

사전 점검: Agent 3 판정이 인용한 evidence_id 중 근거 파일에 없는 비율이 MISMATCH_LIMIT 를 넘으면
근거 파일 버전이 판정과 안 맞는 것으로 보고 멈춘다 (--allow-mismatch 로 계속). --fixture 는 일부러 없는 ID 를 넣어 두었으므로 경고만.
"""
import argparse, json, sys
from collections import Counter
from pathlib import Path
from .build import build_graph, load_jsonl, evidence_id_mismatch
from .verify import Verifier
from .a3format import to_agent3_graph, to_agent3_out_row

MISMATCH_LIMIT = 0.01


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients"); ap.add_argument("--trials"); ap.add_argument("--criteria")
    ap.add_argument("--evidence"); ap.add_argument("--verdicts")
    ap.add_argument("--a3-graphs", help="Agent 3 의 graph/ 폴더 — 근거 파일이 없을 때 거기서 인용된 근거만 꺼내 쓴다 (검사 3·4 불완전)")
    ap.add_argument("--a3-graph-base", help="출력 graph/ 의 바탕이 될 Agent 3 graph/ 폴더 (기본: --a3-graphs, 없으면 --verdicts 옆 graph/)")
    ap.add_argument("--fixture", help="patients/trials/criteria/evidence/verdicts .jsonl 이 든 폴더")
    ap.add_argument("--patient", help="이 환자만")
    ap.add_argument("--default-windows", action="store_true", help="기준에 기간이 없어도 검사 30일·영상 90일 (6.3)")
    ap.add_argument("--allow-mismatch", action="store_true", help=f"인용 근거 ID 불일치가 {MISMATCH_LIMIT:.0%} 를 넘어도 계속")
    ap.add_argument("--out", default="runs/latest")
    a = ap.parse_args(argv)
    if a.fixture:
        f = Path(a.fixture)
        a.patients, a.trials, a.criteria, a.evidence, a.verdicts = (str(f / n) for n in ("patients.jsonl", "trials.jsonl", "criteria.jsonl", "evidence.jsonl", "verdicts.jsonl"))
    patients = load_jsonl(a.patients); trials = load_jsonl(a.trials); criteria = load_jsonl(a.criteria)
    evidence = load_jsonl(a.evidence) if a.evidence else []
    if a.a3_graphs:
        from .build import evidence_from_agent3_graphs
        evidence += evidence_from_agent3_graphs(a.a3_graphs)
    verdicts = load_jsonl(a.verdicts)

    pre = evidence_id_mismatch(verdicts, evidence, a.patient)
    if pre["missing"]:
        print(f"경고: 판정이 인용한 근거 ID {pre['cited']}개 중 {pre['missing']}개({pre['ratio']:.2%})가 근거 파일에 없음 "
              f"— 근거 파일 버전이 판정과 맞는지 확인. 예: {pre['examples'][:5]}", file=sys.stderr)
        if pre["ratio"] > MISMATCH_LIMIT and not (a.allow_mismatch or a.fixture):
            print(f"중단: 불일치 {pre['ratio']:.2%} > {MISMATCH_LIMIT:.0%}. 판정을 만든 근거 파일을 --evidence 로 주거나, "
                  f"그래도 돌리려면 --allow-mismatch", file=sys.stderr)
            return 2

    base_dir = a.a3_graph_base or a.a3_graphs or (Path(a.verdicts).parent / "graph")
    base_dir = Path(base_dir) if base_dir and Path(base_dir).is_dir() else None
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True); (out / "graph").mkdir(exist_ok=True)
    total = Counter(); reports = {}; graphs = {}
    for p in patients:
        pid = p["patient_id"]
        if a.patient and pid != a.patient:
            continue
        if not any(v.get("patient_id") == pid for v in verdicts):
            continue
        g = build_graph(p, trials, criteria, evidence, verdicts)
        rep = Verifier(g, default_windows=a.default_windows).run()
        g.save(out / f"graph_{pid}.json")
        base = json.load(open(base_dir / f"{pid}.json", encoding="utf-8")) if base_dir and (base_dir / f"{pid}.json").exists() else None
        json.dump(to_agent3_graph(g, base), open(out / "graph" / f"{pid}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        graphs[pid] = g
        reports[pid] = {"stats": g.stats(), **rep}
        total["patients"] += 1; total["checked"] += rep["checked"]; total["conflict_edges"] += rep["conflict_edges"]
        for k, n in rep["downgraded"].items():
            total[f"downgraded_{k}"] += n
        labels = ", ".join(f"{t}: {r['label']}" for t, r in rep["trial_verdicts"].items())
        print(f"{pid}: 판정 {rep['checked']} 검사, 격하 {sum(rep['downgraded'].values())} {rep['downgraded']}, 충돌 엣지 {rep['conflict_edges']}, "
              f"공유 근거 {g.stats()['evidence_shared_by_2plus_verdicts']} → 시험 판정 {{{labels}}}")
    with open(out / "agent3_out.jsonl", "w", encoding="utf-8") as f:
        for row in verdicts:
            if row.get("patient_id") in graphs:
                f.write(json.dumps(to_agent3_out_row(graphs[row["patient_id"]], row), ensure_ascii=False) + "\n")
    total["evidence_id_mismatch"] = pre["missing"]
    json.dump({"total": dict(total), "preflight": {**pre, "limit": MISMATCH_LIMIT, "a3_graph_base": str(base_dir) if base_dir else None},
               "patients": reports}, open(out / "verify_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"→ {out}  합계 {dict(total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
