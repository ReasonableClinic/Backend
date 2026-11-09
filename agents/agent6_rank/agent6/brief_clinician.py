"""Baseline clinician briefing: no LLM, every line is built from graph nodes and carries their ids.

  python3 -m agent6.brief_clinician --ranking runs/rank_dev/ranking.jsonl --graphs K/dev/agent3_out_a031/graph \
      --trials K/dev/reference/trials.jsonl --out runs/brief_dev

Writes <out>/<patient_id>.clinician.json (sentences with refs, see BRIEFING_FORMAT.md) and a readable .md.
This is the floor to beat: an LLM version may reword and group, but must keep refs on every sentence.
"""
import argparse, json, os

from . import keyinfo as KI
from . import VERSION
from .graph import Graph
from .rank import read_jsonl
from .keyinfo import cancer_hidden
from .rules import FIXED
from .review import FLAG_KO

STATUS_KO = {"PASS": "충족", "FAIL": "불충족", "UNKNOWN": "미확인", "CONFLICT": "기록 충돌"}
EXCL_KO = {"PASS": "제외 사유 없음", "FAIL": "제외 사유 있음"}   # exclusion PASS = the patient is NOT excluded
REASON_KO = {"MISSING": "기록 없음", "EXPIRED": "기간 지남", "UNSUPPORTED": "근거 불충분", "VALID": "", "VIOLATED": ""}


def S(text, refs, kind="fact"):
    return {"text": text, "refs": sorted(set(refs)), "kind": kind}


def calc_text(c):
    """Two shapes: age {name, value, lo, hi}; measurement {concept, value, value_unit, operator, threshold, unit,
    observed_date, days_before, window_days?, note}."""
    if "name" in c:
        return f"{c['name']} = {c['value']} (범위 {c.get('lo')}~{c.get('hi')})"
    t = f"{c.get('concept')} {c.get('value')} {c.get('value_unit') or ''} {c.get('operator')} {c.get('threshold')} {c.get('unit') or ''}"
    if c.get("observed_date"):
        t += f", 측정 {c['observed_date']}"
        if c.get("days_before") is not None:
            t += f" ({c['days_before']}일 전" + (f", 허용 {c['window_days']}일" if c.get("window_days") else "") + ")"
    return " ".join(t.split())


def site_countries(trial):
    ok = ("RECRUITING", "NOT_YET_RECRUITING")
    c = list(dict.fromkeys(s.get("country") for s in trial.get("sites") or []
                           if s.get("country") and (s.get("status") or trial.get("overall_status")) in ok))
    return c or [x for x in dict.fromkeys(trial.get("countries") or []) if x]


def no_kr_line(trial):
    """(a6-0.4.13) clinician: no recruiting Korean site, with the countries as in the record."""
    c = site_countries(trial)
    return "국내 모집 기관 없음" + (f" (모집 국가: {', '.join(c[:8])}{' 외' if len(c) > 8 else ''})" if c else "")


def arms_line(trial):
    """(a6-0.4.13) clinician: arms as in the record (type: interventions)."""
    arms = [a for a in trial.get("arms") or [] if a.get("interventions")]
    if not arms:
        return None
    parts = [f"{a.get('type')}: {' + '.join(a['interventions'])}" for a in arms[:6]]
    return "Arms — " + "; ".join(parts) + (f"; 외 {len(arms) - 6}개" if len(arms) > 6 else "")


def trial_section(g, item, trial):
    tid = item["trial_id"]
    lab = g.label(tid)
    out = [S(f"{item['rank']}. {tid} {trial.get('title', '')}".strip(), [f"trial:{tid}"], "heading"),
           S(f"시험 판정: {item['label']}" + (f" (남은 항목 {len(item['open_criteria'])}개)" if item["open_criteria"] else ""),
             [lab["id"]] if lab else [f"trial:{tid}"])]
    if any(f["flag"] == "age_mismatch" for f in item.get("review_flags", [])):
        ages = [n for n in g.nodes.values() if n.get("name") == "age_at_as_of"][:1]
        out.append(S(f"{FLAG_KO['age_mismatch']} (시험 {trial.get('min_age')}~{trial.get('max_age')}세)",
                     [f"trial:{tid}"] + [a["id"] for a in ages]))
    for fl in ("llm_missing", "note_negates"):
        ids = [f["criterion_id"] for f in item.get("review_flags", []) if f["flag"] == fl]
        if ids:
            decs = [g.decision(f"crit:{c}") for c in ids]
            out.append(S(f"{FLAG_KO[fl]}: " + ", ".join(ids), [d["id"] for d in decs if d]))
    if cancer_hidden(g, trial):
        out.append(S("환자 기록에 확정된 악성 진단 없음: 환자용 안내에서 이 시험의 질환명을 쓰지 않았음. 환자에게 설명 전 확인 필요",
                     [f"trial:{tid}"]))
    if item["stale"]:
        out.append(S(f"모집 상태가 {item['months_since_verified']}개월 동안 확인되지 않음 (status_verified {item['status_verified']})",
                     [f"trial:{tid}"]))
    if item["kr_sites"] > 0:
        out.append(S(f"국내 모집 기관 {item['kr_sites']}곳", [f"trial:{tid}"]))
    else:   # a6-0.4.13
        out.append(S(no_kr_line(trial), [f"trial:{tid}"]))
    if arms_line(trial):
        out.append(S(arms_line(trial), [f"trial:{tid}"]))
    for d in g.decisions(tid):
        crit = g.nodes[f"crit:{d['criterion_id']}"]
        why = REASON_KO.get(d.get("reason"), d.get("reason") or "")
        st = EXCL_KO.get(d["status"], STATUS_KO[d["status"]]) if crit.get("type") == "exclusion" else STATUS_KO[d["status"]]
        head = f"{d['criterion_id']} [{crit.get('type')}] {st}" + (f" ({why})" if why else "")
        if d.get("action") not in (None, "none"):
            head += f" → 다음: {d['action']}"
        refs = [crit["id"], d["id"]]
        lines = [S(head, refs)]
        for ev, src in g.support(d["id"]):
            if src:
                lines.append(S(f"   근거: \"{src['text']}\" ({src['doc_id']}, {ev.get('observed_date')})", [ev["id"], src["id"]]))
        for c in g.calculations(d["id"]):
            lines.append(S("   계산: " + calc_text(c), [c["id"]]))
        if d.get("missing_fact"):
            lines.append(S(f"   필요한 정보: {d['missing_fact']}", [d["id"]]))
        out += lines
    return out


def near_miss_section(g, near, trials):
    """Ineligible trials with a single FAIL: not ranked (6.4), shown so a clinician can check that one criterion."""
    near = [x for x in near if f"crit:{x['criterion_id']}" in g.nodes]
    if not near:
        return []
    out = [S("참고: FAIL 하나로 제외된 시험 (순위에는 넣지 않음, 그 기준만 확인하면 판정이 바뀔 수 있음)",
             [f"trial:{x['trial_id']}" for x in near], "heading")]
    for x in near:
        tid, cid = x["trial_id"], x["criterion_id"]
        crit, d, lab = g.nodes[f"crit:{cid}"], g.decision(f"crit:{cid}"), g.label(tid)
        st = EXCL_KO["FAIL"] if crit.get("type") == "exclusion" else STATUS_KO["FAIL"]
        out.append(S(f"{tid} {trials.get(tid, {}).get('title', '')}: {cid} [{crit.get('type')}] {st}".strip(),
                     [f"trial:{tid}", crit["id"], d["id"]] + ([lab["id"]] if lab else [])))
        if d.get("note"):
            out.append(S(f"   노트: {d['note']}", [d["id"]]))
        for fl in x.get("flags", []):
            if fl in FLAG_KO:
                out.append(S(f"   {FLAG_KO[fl]}", [d["id"]]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ranking", required=True)
    ap.add_argument("--graphs", required=True, nargs="+", help="graph folder(s)")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--patient", action="append")
    ap.add_argument("--evidence", nargs="*", default=[], help="Agent 2 evidence jsonl (cancer-diagnosis check)")
    a = ap.parse_args(argv)
    KI.load_evidence(a.evidence, a.graphs)
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    os.makedirs(a.out, exist_ok=True)
    n = 0
    for r in read_jsonl(a.ranking):
        pid = r["patient_id"]
        if a.patient and pid not in a.patient:
            continue
        path = next((os.path.join(d, f"{pid}.json") for d in a.graphs if os.path.exists(os.path.join(d, f"{pid}.json"))), None)
        if not path:
            continue
        g = Graph.load(path)
        sents = [S(f"환자 {pid}, 기준일 {g.as_of}", [], "meta")]
        if not r["items"]:
            sents.append(S("추천할 시험 없음 (eligible·potential 없음)", [], "meta"))
        for item in r["items"]:
            sents += trial_section(g, item, trials.get(item["trial_id"], {}))
        for tid in r["dropped_stale_trials"]:
            sents.append(S(f"{tid}: " + FIXED["rule:dropped_stale"], [f"trial:{tid}", "rule:dropped_stale"]))
        sents += near_miss_section(g, r.get("near_miss", []), trials)
        doc = {"patient_id": pid, "as_of": g.as_of, "audience": "clinician", "graph_file": os.path.basename(path),
               "ranking": r["ranking"], "also_mentioned": sorted(r["dropped_stale_trials"]) +
               [x["trial_id"] for x in r.get("near_miss", [])], "sentences": sents,
               "evidence": KI.EVIDENCE_INFO, "agent6": VERSION}
        with open(os.path.join(a.out, f"{pid}.clinician.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        with open(os.path.join(a.out, f"{pid}.clinician.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(("## " if s["kind"] == "heading" else "") + s["text"] for s in sents) + "\n")
        n += 1
    print(f"{n} clinician briefings -> {a.out}")


if __name__ == "__main__":
    main()
