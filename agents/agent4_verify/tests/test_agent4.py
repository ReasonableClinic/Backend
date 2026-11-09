"""동작 확인 (pytest 없이 실행 가능):  python3 tests/test_agent4.py
1. 검사 4종이 각각 정확히 한 건씩 격하하고, 정상 판정 3건은 손대지 않는다 (잘못된 격하 0).
2. 근거 하나(HbA1c)가 시험 2개의 판정에 공유된다.
3. 새 근거가 들어오면 영향 범위만 돌려준다 (전체 재실행 아님).
4. 저장 → 다시 읽기 → 같은 그래프.
"""
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent4.build import build_graph, load_jsonl
from agent4.verify import Verifier, trial_verdict, decide_action

F = Path(__file__).parent / "fixture"
P = load_jsonl(F / "patients.jsonl")[0]
T, C, E, V = (load_jsonl(F / n) for n in ("trials.jsonl", "criteria.jsonl", "evidence.jsonl", "verdicts.jsonl"))

g = build_graph(P, T, C, E, V)
rep = Verifier(g).run()

# 1. 검사별 1건씩, 정상 판정 무격하
assert rep["downgraded"] == {"grounding": 1, "relevance": 1, "expiry": 1, "conflict": 1}, rep["downgraded"]
ok = {v["criterion_id"] for v in g.current_verdicts() if v["by"] == "agent3" and v["verified"] is True and v["status"] in ("PASS", "FAIL")}
assert ok == {"NCTFX00001-I01", "NCTFX00001-E01", "NCTFX00002-I01"}, ok
by_cid = {d["criterion_id"]: d for d in rep["details"]}
assert by_cid["NCTFX00001-E02"]["check"] == "grounding" and by_cid["NCTFX00001-E02"]["to"] == "UNKNOWN/UNSUPPORTED"
assert by_cid["NCTFX00002-E01"]["check"] == "relevance" and by_cid["NCTFX00002-E01"]["action"] == "patient_question"
assert by_cid["NCTFX00002-I02"]["check"] == "expiry" and by_cid["NCTFX00002-I02"]["action"] == "new_test"
assert by_cid["NCTFX00001-I02"]["check"] == "conflict" and by_cid["NCTFX00001-I02"]["to"] == "CONFLICT/CONFLICT"
# 격하는 원본을 지우지 않는다
assert g.node("verdict:NCTFX00001-I02#1")["status"] == "PASS" and g.node("verdict:NCTFX00001-I02#1")["verified"] is False
assert g.verdict_for("NCTFX00001-I02")["status"] == "CONFLICT"
# 행동 규칙표
assert decide_action("MISSING", ["lab"]) == "lab_check" and decide_action("MISSING", ["patient", "lab"]) == "patient_question"
assert decide_action("EXPIRED", ["lab"]) == "new_test" and decide_action("CONFLICT", []) == "clinician_confirmation"

# 2. 근거 공유 (HbA1c EV01 → 두 시험의 판정)
assert len(g.inn("ev:FX-0001-EV01", "supported_by")) == 2
assert g.stats()["evidence_shared_by_2plus_verdicts"] >= 1

# 3. 갱신 전파: HbA1c 재검사 결과가 들어오면 영향은 두 시험의 HbA1c 판정 2개뿐
aff = g.affected_by_evidence(["FX-0001-EV01"])
assert {v.split("#")[0] for v in aff["verdicts"]} == {"verdict:NCTFX00001-I01", "verdict:NCTFX00002-I01"}, aff
assert set(aff["trials"]) == {"trial:NCTFX00001", "trial:NCTFX00002"}
# 새 개념(임신 검사) 근거가 추가되면 다시 판정할 기준
assert g.affected_by_concept("pregnancy") == ["crit:NCTFX00002-E01"]

# 시험 판정 (6.1)
tv = {t: trial_verdict(g, t)["label"] for t in ("NCTFX00001", "NCTFX00002")}
assert tv == {"NCTFX00001": "potential", "NCTFX00002": "potential"}, tv

# 4. 저장/복원
from agent4.graph import EvidenceGraph
with tempfile.TemporaryDirectory() as d:
    g.save(Path(d) / "g.json"); g2 = EvidenceGraph.load(Path(d) / "g.json")
    assert g2.stats() == g.stats() and len(g2.edges) == len(g.edges)

import copy
from agent4.a3format import to_agent3_graph, to_agent3_out_row
from agent4.build import evidence_id_mismatch
from agent4.__main__ import main

# 5. Agent 3 그래프 형식: 노드 kind, dec:<trial>:<crit>:r<n>, 엣지 [a, rel, b], label:<trial>, 격하는 r2 (by agent4, downgraded_from r1)
a3 = to_agent3_graph(g)
nodes = {n["id"]: n for n in a3["nodes"]}
assert {n["kind"] for n in a3["nodes"]} >= {"trial", "criterion", "decision", "evidence", "source", "trial_decision"}
assert all(isinstance(e, list) and len(e) == 3 and e[0] in nodes and e[2] in nodes for e in a3["edges"])
r1, r2 = nodes["dec:NCTFX00001:NCTFX00001-I02:r1"], nodes["dec:NCTFX00001:NCTFX00001-I02:r2"]
assert r1["status"] == "PASS" and r1["by"] == "agent3" and r1["round"] == 1
assert r2["status"] == "CONFLICT" and r2["by"] == "agent4" and r2["round"] == 2 and r2["downgraded_from"] == r1["id"]
assert ["dec:NCTFX00001:NCTFX00001-I02:r2", "downgraded_from", r1["id"]] in a3["edges"]
assert ["crit:NCTFX00001-I02", "decided_as", r2["id"]] in a3["edges"] and ["ev:FX-0001-EV03", "conflicts_on", r2["id"]] in a3["edges"]
assert sum(1 for n in a3["nodes"] if n["kind"] == "decision" and n["by"] == "agent4") == 4
assert "dec:NCTFX00001:NCTFX00001-I01:r2" not in nodes                       # 통과한 판정은 r1 만
assert any(e[1] == "derived_from" and e[2].startswith("src:") for e in a3["edges"])
assert any(e[1] == "conflicts_with" for e in a3["edges"])
for t in ("NCTFX00001", "NCTFX00002"):
    lab = nodes[f"label:{t}"]
    assert lab["kind"] == "trial_decision" and lab["label"] == trial_verdict(g, t)["label"] and lab["by"] == "agent4"
    assert [f"trial:{t}", "labelled", f"label:{t}"] in a3["edges"]
# Agent 3 그래프(base) 위에 얹기: Agent 3 노드는 그대로, 새 라운드는 base 의 마지막 라운드 + 1
g0 = build_graph(P, T, C, E, V)
base = to_agent3_graph(g0)
base["nodes"] = [dict(n, by="agent3", agent3_only=True) if n["kind"] == "trial_decision" else n for n in base["nodes"]]
for n in base["nodes"]:
    if n["id"] == "dec:NCTFX00001:NCTFX00001-I01:r1":
        n["note"] = "agent3 원본 노트"
a3b = to_agent3_graph(g, base)
nb = {n["id"]: n for n in a3b["nodes"]}
assert a3b["version"] == base["version"] + 1 and nb["dec:NCTFX00001:NCTFX00001-I01:r1"]["note"] == "agent3 원본 노트"
assert nb["dec:NCTFX00001:NCTFX00001-I02:r2"]["downgraded_from"] == "dec:NCTFX00001:NCTFX00001-I02:r1"
assert nb["label:NCTFX00001"]["by"] == "agent4" and nb["label:NCTFX00001"]["agent3_label"] == {n["id"]: n for n in base["nodes"]}["label:NCTFX00001"]["label"]
assert all(list(e) in a3b["edges"] for e in base["edges"])

# 6. agent3_out.jsonl 한 줄: 격하 반영, 원래 값 보존, 시험 판정 다시 계산
row = {"patient_id": "FX-0001", "trial_id": "NCTFX00001", "trial_label": "eligible", "label_why": [], "counts": {},
       "criteria": [dict(cv, action=cv.pop("expected_action")) for cv in copy.deepcopy(V[0]["criteria"])]}
o = to_agent3_out_row(g, row)
oc = {cv["criterion_id"]: cv for cv in o["criteria"]}
assert oc["NCTFX00001-I02"]["status"] == "CONFLICT" and oc["NCTFX00001-I02"]["original_status"] == "PASS" and oc["NCTFX00001-I02"]["by"] == "agent4"
assert oc["NCTFX00001-I02"]["action"] == "clinician_confirmation" and oc["NCTFX00001-I01"]["status"] == "PASS" and "by" not in oc["NCTFX00001-I01"]
assert o["agent3_trial_label"] == "eligible" and o["trial_label"] == trial_verdict(g, "NCTFX00001")["label"] == "potential"
assert o["label_why"] == trial_verdict(g, "NCTFX00001")["label_why"] and o["counts"]["CONFLICT"] == 1 and row["criteria"][1]["status"] == "PASS"

# 7. pc:llm_missing 는 시험을 eligible 로 두지 않는다 (제외 기준이어도, judged_by 든 rule_tags 든)
def _tv(e02):
    vv = [{"patient_id": "FX-0001", "trial_id": "NCTFX00001", "criteria": [
        {"criterion_id": "NCTFX00001-I01", "status": "PASS", "reason": "VALID", "supporting_evidence": ["FX-0001-EV01"]},
        {"criterion_id": "NCTFX00001-E01", "status": "PASS", "reason": "VALID", "supporting_evidence": ["FX-0001-EV04"]},
        dict({"criterion_id": "NCTFX00001-E02", "status": "UNKNOWN", "reason": "MISSING", "supporting_evidence": []}, **e02)]}]
    gg = build_graph(P, T, C, E, vv); Verifier(gg).run()
    return trial_verdict(gg, "NCTFX00001"), gg, vv
tv_ok, _, _ = _tv({"judged_by": "llm"})
assert tv_ok["label"] == "eligible", tv_ok                                   # 제외 기준 UNKNOWN/MISSING 은 원래 막지 않는다
for mark in ({"judged_by": "pc:llm_missing", "rule_tags": ["pc:llm_missing"]}, {"judged_by": "pc:llm_missing"}, {"rule_tags": ["pc:llm_missing"]}):
    tv_lm, gg, vv = _tv(mark)
    assert tv_lm["label"] == "potential" and tv_lm["label_why"] == ["NOT_JUDGED NCTFX00001-E02"], (mark, tv_lm)
assert to_agent3_out_row(gg, vv[0])["trial_label"] == "potential"
assert {n["id"]: n for n in to_agent3_graph(gg)["nodes"]}["label:NCTFX00001"]["why"] == ["NOT_JUDGED NCTFX00001-E02"]

# 8. 사전 점검: 인용 근거 ID 불일치 > 1% 면 중단 (--allow-mismatch 로 계속), --fixture 는 경고만
pre = evidence_id_mismatch(V, E)
assert pre["cited"] == 6 and pre["missing"] == 1 and pre["examples"] == ["FX-0001-EV99"]
assert evidence_id_mismatch(V, E + [{"evidence_id": "FX-0001-EV99"}])["missing"] == 0
args = ["--patients", str(F / "patients.jsonl"), "--trials", str(F / "trials.jsonl"), "--criteria", str(F / "criteria.jsonl"),
        "--evidence", str(F / "evidence.jsonl"), "--verdicts", str(F / "verdicts.jsonl")]
import contextlib, io
with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
    assert main(args + ["--out", f"{d}/stop"]) == 2 and not Path(f"{d}/stop").exists()
    assert main(args + ["--out", f"{d}/go", "--allow-mismatch"]) == 0
    assert main(["--fixture", str(F), "--out", f"{d}/fx"]) == 0
    r = json.load(open(f"{d}/go/verify_report.json"))
    assert r["preflight"]["missing"] == 1 and r["total"]["evidence_id_mismatch"] == 1
    out_rows = load_jsonl(f"{d}/go/agent3_out.jsonl")
    assert [x["trial_id"] for x in out_rows] == [x["trial_id"] for x in V] and Path(f"{d}/go/graph/FX-0001.json").exists()
    assert Path(f"{d}/go/graph_FX-0001.json").exists()                         # 기존 출력도 그대로

print("OK —", json.dumps({"downgraded": rep["downgraded"], "conflict_edges": rep["conflict_edges"], "stats": g.stats()}, ensure_ascii=False))
