#!/usr/bin/env python3
"""Score agent3_out.jsonl against the dev gold (common format ④).

  python3 eval/score_dev.py runs/dev_none_haiku/agent3_out.jsonl [--md report.md]

Criterion level (only criteria present in the gold; cohort-excluded ones are not in it)
  strict      status equal to expected_status
  lenient     also accepts PASS on audit rows 3_inferred (memo 2.4) and 2_blanket (6.3 proposal)
  opposite    PASS <-> FAIL: the pass/fail line of the team (<= 1 %)
  missed      gold PASS/FAIL that Agent 3 left UNKNOWN (the "놓친 사실" problem)
  attribution PASS/FAIL agreed with gold whose cited evidence overlaps a gold evidence span
  unsupported PASS/FAIL/CONFLICT without any evidence id
Trial level   eligible / potential / ineligible confusion (6.1)
"""
import argparse
import csv
import json
import os
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ST = ["PASS", "FAIL", "UNKNOWN", "CONFLICT", "N/A", "absent"]


def load(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def score(pred_path, gold_path, audit_path, evidence_path, criteria_path):
    gold = {(g["patient_id"], g["trial_id"]): g for g in load(gold_path)}
    pred = {(p["patient_id"], p["trial_id"]): p for p in load(pred_path)}
    ev = {e["evidence_id"]: e for e in load(evidence_path)}
    crit_type = {c["criterion_id"]: c["type"] for c in load(criteria_path)}
    lenient = defaultdict(set)                      # tier -> {(pid, tid, cid)}
    with open(audit_path, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["proposed"] == "PASS" and row["tier"] in ("3_inferred", "2_blanket"):
                lenient[row["tier"]].add((row["patient_id"], row["trial_id"], row["criterion_id"]))

    cm = Counter()
    n = strict = strict_reason = len3 = len23 = 0
    by_type = defaultdict(Counter)
    by_review = defaultdict(Counter)
    opposite, missed, wrong_decided = [], [], []
    act_n = act_ok = 0
    attr_n = attr_ok = 0
    unsupported = decided = 0
    tl = Counter()
    for key, g in gold.items():
        p = pred.get(key)
        if p is None:
            continue
        pc = {c["criterion_id"]: c for c in p["criteria"]}
        na = {c["criterion_id"] for c in p.get("not_applicable", [])}
        for c in p["criteria"]:
            if c["status"] in ("PASS", "FAIL", "CONFLICT"):
                decided += 1
                unsupported += not c.get("evidence_ids")
        gev = {x["gold_ev_id"]: x for x in g["gold_evidence"]}
        for k in g["criteria"]:
            n += 1
            cid, gs = k["criterion_id"], k["expected_status"]
            r = pc.get(cid)
            ps = "N/A" if cid in na else (r["status"] if r else "absent")
            cm[(gs, ps)] += 1
            ok = ps == gs
            strict += ok
            strict_reason += ok and (r or {}).get("reason") == k["reason"]
            t3 = (key[0], key[1], cid) in lenient["3_inferred"]
            t2 = (key[0], key[1], cid) in lenient["2_blanket"]
            len3 += ok or (ps == "PASS" and t3)
            len23 += ok or (ps == "PASS" and (t3 or t2))
            ctype = crit_type.get(cid, "?")
            by_type[ctype]["n"] += 1
            by_type[ctype]["ok"] += ok
            by_review[k.get("review")]["n"] += 1
            by_review[k.get("review")]["ok"] += ok
            if {gs, ps} == {"PASS", "FAIL"}:
                opposite.append((key[0], key[1], cid, gs, ps, (r or {}).get("note")))
            elif gs in ("PASS", "FAIL") and ps == "UNKNOWN":
                missed.append((key[0], key[1], cid, gs, (r or {}).get("rule_tags")))
            elif gs == "UNKNOWN" and ps in ("PASS", "FAIL") and not (ps == "PASS" and (t3 or t2)):
                wrong_decided.append((key[0], key[1], cid, k["reason"], ps, (r or {}).get("note")))
            if gs in ("UNKNOWN", "CONFLICT") and ps == gs and r:
                act_n += 1
                act_ok += r.get("action") == k["expected_action"]
            if ok and gs in ("PASS", "FAIL") and k["supporting_evidence"] and r and r.get("evidence_ids"):
                attr_n += 1
                spans = [(gev[x]["doc_id"], gev[x]["span"]) for x in k["supporting_evidence"] if x in gev]
                mine = [(ev[e]["source"]["doc_id"], ev[e]["source"]["span"]) for e in r["evidence_ids"] if e in ev]
                attr_ok += any(d1 == d2 and overlap(s1, s2) for d1, s1 in mine for d2, s2 in spans)
        tl[(g["trial_label"], p["trial_label"])] += 1

    pairs = sum(tl.values())
    res = {
        "pred": pred_path, "pairs": pairs, "criteria": n,
        "strict_status_acc": strict / n, "strict_status_reason_acc": strict_reason / n,
        "lenient_acc_3inferred": len3 / n, "lenient_acc_3inferred_2blanket": len23 / n,
        "opposite_errors": len(opposite), "opposite_rate": len(opposite) / n,
        "missed_definite": len(missed),
        "gold_definite": sum(v for (gs, _), v in cm.items() if gs in ("PASS", "FAIL")),
        "unknown_decided_wrongly": len(wrong_decided),
        "action_acc_on_unknown": act_ok / act_n if act_n else None, "action_n": act_n,
        "evidence_attribution": attr_ok / attr_n if attr_n else None, "attribution_n": attr_n,
        "unsupported_decisions": unsupported, "decided": decided,
        "by_type": {k: v["ok"] / v["n"] for k, v in by_type.items()},
        "by_review": {k: v["ok"] / v["n"] for k, v in by_review.items()},
        "trial_acc": sum(v for (a, b), v in tl.items() if a == b) / pairs if pairs else None,
        "trial_eligible_or_potential_to_ineligible": sum(v for (a, b), v in tl.items() if a in ("eligible", "potential") and b == "ineligible"),
        "trial_ineligible_to_eligible": tl[("ineligible", "eligible")],
        # D2 (3rd meeting): conservative errors are invisible in the opposite-direction count, so report how many
        # gold-eligible pairs the agent also calls eligible
        "gold_eligible_recall": (tl[("eligible", "eligible")], sum(v for (a, b), v in tl.items() if a == "eligible")),
        "status_confusion": {f"{a}->{b}": v for (a, b), v in sorted(cm.items())},
        "trial_confusion": {f"{a}->{b}": v for (a, b), v in sorted(tl.items())},
        "opposite_list": opposite, "missed_list": missed, "unknown_decided_list": wrong_decided,
    }
    return res


def markdown(r):
    pct = lambda x: "-" if x is None else f"{100 * x:.1f}%"
    L = [f"# Agent 3 dev score: `{r['pred']}`", "",
         f"쌍 {r['pairs']}개, 기준 {r['criteria']}개", "",
         "| 지표 | 값 |", "| --- | --- |",
         f"| 기준 상태 일치 (엄격) | {pct(r['strict_status_acc'])} |",
         f"| 상태+이유 일치 | {pct(r['strict_status_reason_acc'])} |",
         f"| 관대 (3_inferred PASS 허용) | {pct(r['lenient_acc_3inferred'])} |",
         f"| 관대 (3_inferred + 2_blanket) | {pct(r['lenient_acc_3inferred_2blanket'])} |",
         f"| **반대 방향 오류 (PASS↔FAIL)** | **{r['opposite_errors']} ({pct(r['opposite_rate'])})** |",
         f"| 확정 정답을 UNKNOWN으로 남김 | {r['missed_definite']} / {r['gold_definite']} |",
         f"| 정답 UNKNOWN을 확정 판정 (관대 행 제외) | {r['unknown_decided_wrongly']} |",
         f"| UNKNOWN 행동 일치 | {pct(r['action_acc_on_unknown'])} (n={r['action_n']}) |",
         f"| 근거 귀속 (정답 근거와 위치 겹침) | {pct(r['evidence_attribution'])} (n={r['attribution_n']}) |",
         f"| 근거 없는 확정 판정 | {r['unsupported_decisions']} / {r['decided']} |",
         f"| 시험 판정 일치 | {pct(r['trial_acc'])} |",
         f"| 시험: 정답 eligible/potential → ineligible | {r['trial_eligible_or_potential_to_ineligible']} |",
         f"| 시험: 정답 ineligible → eligible | {r['trial_ineligible_to_eligible']} |",
         f"| 시험: 정답 eligible 재현율 (D2) | {r['gold_eligible_recall'][0]} / {r['gold_eligible_recall'][1]} |",
         "", "유형별 엄격 일치: " + ", ".join(f"{k} {pct(v)}" for k, v in r["by_type"].items()),
         "", "검수 출처별: " + ", ".join(f"{k} {pct(v)}" for k, v in r["by_review"].items()),
         "", "## 기준 상태 혼동 (정답 → 예측)", "", "| 정답 \\ 예측 | " + " | ".join(ST) + " |",
         "| --- |" + " --- |" * len(ST)]
    for gs in ["PASS", "FAIL", "UNKNOWN", "CONFLICT"]:
        L.append(f"| {gs} | " + " | ".join(str(r["status_confusion"].get(f"{gs}->{ps}", 0)) for ps in ST) + " |")
    L += ["", "## 시험 판정 혼동 (정답 → 예측)", "", "| 정답 \\ 예측 | eligible | potential | ineligible |", "| --- | --- | --- | --- |"]
    for a in ["eligible", "potential", "ineligible"]:
        L.append(f"| {a} | " + " | ".join(str(r["trial_confusion"].get(f"{a}->{b}", 0)) for b in ["eligible", "potential", "ineligible"]) + " |")
    if r["opposite_list"]:
        L += ["", "## 반대 방향 오류", ""] + [f"- {x[0]} {x[2]}: 정답 {x[3]}, 예측 {x[4]} — {x[5]}" for x in r["opposite_list"]]
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pred")
    ap.add_argument("--gold", default=os.path.join(HERE, "data/dev/gold/gold.jsonl"))
    ap.add_argument("--audit", default=os.path.join(HERE, "data/dev/gold/audit_dev_missing.csv"))
    ap.add_argument("--evidence", default=os.path.join(HERE, "agent3_kit/evidence_dev_haiku_v14_12.jsonl"))
    ap.add_argument("--criteria", default=os.path.join(HERE, "data/dev/reference/criteria.jsonl"))
    ap.add_argument("--md")
    ap.add_argument("--json")
    a = ap.parse_args()
    r = score(a.pred, a.gold, a.audit, a.evidence, a.criteria)
    md = markdown(r)
    print(md)
    base = os.path.dirname(a.pred)
    with open(a.md or os.path.join(base, "score.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(a.json or os.path.join(base, "score.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
