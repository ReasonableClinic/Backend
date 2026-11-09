"""Layer-2 expert evaluation kit (a6-0.4.5, dev only): sample patients, blind template vs LLM, write rating forms.

  python3 scripts/eval2_kit.py --template dev_out/briefing --ranking dev_out/ranking.jsonl --graphs <graph dirs> \
      [--llm runs/brief_llm_dev] [--n 12] [--seed 2026] --out runs/eval2

Sample: base dev patients only (variants differ from their base patient by one document), chosen greedily so the
sample covers: minor (guardian sentence), confirmed-diagnosis sentence, review flags, near-miss, 0/1/2/3 ranked trials,
LLM template fallback (when --llm). Deterministic for a seed.
Workload: every sampled patient gets the patient checklist; only --clinician-n of them (default 6) get the clinician
sentence-by-sentence rating (dev template: about 70 sentences per clinician briefing, twice that with --llm).
Blinding: per patient the two versions are shown as A and B in random order (seed); the mapping goes to key.json,
which raters must not see. Without --llm only the template version (A) is written (clinician sentence rating still works).
Writes:
  packets/<code>/patient_A.md, patient_B.md         numbered sentences, as the patient sees them
  packets/<code>/clinician_A.md, clinician_B.md     numbered sentences, each with the graph evidence it cites
  forms/patient_form.csv, forms/clinician_form.csv  one row per item / sentence to fill (copy per rater)
  key.json, sample.csv                              coordinator only
"""
import argparse, csv, glob, json, os, random

PATIENT_ITEMS = [  # own wording, grouped by the domains in EVAL_PLAN.md (PEMAT/CDC CCI/KGCP: originals not yet verified)
    ("U1", "이해", "이 안내가 무엇에 대한 것인지(연구 참여 검토용) 처음에 분명히 알 수 있다"),
    ("U2", "이해", "전문 용어가 없거나, 있으면 쉬운 말로 풀려 있다"),
    ("U3", "이해", "문장이 짧고 한 문장에 내용이 하나씩 있다"),
    ("U4", "이해", "시험마다 무엇을 연구하는지 알 수 있다"),
    ("U5", "이해", "숫자(개수·인원·기관 수)가 헷갈리지 않게 쓰여 있다"),
    ("A1", "행동", "다음에 무엇을 해야 하는지(누구에게 무엇을 물을지) 알 수 있다"),
    ("A2", "행동", "직접 답할 것과 의료진이 확인할 것이 구분되어 있다"),
    ("M1", "치료적 오해", "조건이 맞는다는 말을 '효과가 있다'로 오해하지 않게 쓰여 있다"),
    ("M2", "치료적 오해", "참여가 아직 확정이 아니라는 점이 분명하다"),
    ("M3", "치료적 오해", "위약·무작위가 있는 시험이면 그 사실이 이해되게 쓰여 있다"),
    ("K1", "고지", "참여는 자유이고 언제든 그만둘 수 있다는 점이 있다"),
    ("K2", "고지", "다른 치료 방법과 참여 부담을 물어볼 수 있다는 점이 있다"),
    ("S1", "안전", "환자를 불안하게 하거나 진단을 단정하는 표현이 없다(예: 확정되지 않은 '암')"),
]
PATIENT_SCALE = "1=그렇다, 0=그렇지 않다, NA=해당 없음"
CLIN_SCALE = "rating: 3=지지됨, 2=일부, 1=근거 없음, 0=모순 / severity(1·0일 때): 치명, 중대, 경미"


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def features(pid, rank, tdir, llm_log):
    p = json.load(open(os.path.join(tdir, f"{pid}.patient.json"), encoding="utf-8"))
    txt = [s["text"] for s in p["sentences"]]
    return {"patient_id": pid, "trials": len(rank["items"]), "minor": any("보호자" in t for t in txt),
            "dx": any(t.startswith("기록에 있는 진단") for t in txt),
            "flags": sum(len(i.get("review_flags", [])) for i in rank["items"]) > 0,
            "near_miss": bool(rank.get("near_miss")), "llm_fallback": bool(llm_log.get(pid))}


def pick(feats, n, seed):
    rnd = random.Random(seed)
    pool = sorted(feats, key=lambda f: f["patient_id"])
    rnd.shuffle(pool)
    want = ["minor", "dx", "flags", "near_miss", "llm_fallback", "t0", "t1", "t2", "t3"]
    has = lambda f, w: (f["trials"] == int(w[1]) if w.startswith("t") and w[1:].isdigit() else f[w])
    chosen = []
    for w in want:                      # one patient per property first
        if len(chosen) < n and not any(has(f, w) for f in chosen):
            c = next((f for f in pool if f not in chosen and has(f, w)), None)
            if c:
                chosen.append(c)
    for f in sorted(pool, key=lambda f: -f["trials"]):   # then fill, preferring briefings with more content
        if len(chosen) >= n:
            break
        if f not in chosen:
            chosen.append(f)
    return chosen


def resolve(ref, nodes, src_of):
    n = nodes.get(ref)
    if not n:
        return ref.split(":", 1)[0] + " (그래프 밖: 용어 사전·고정 문구·에이전트 2 근거)"
    k = n["kind"]
    if k == "decision":
        return f"판정 {n.get('criterion_id')}: {n.get('status')}/{n.get('reason') or ''} — {(n.get('note') or '')[:200]}"
    if k == "criterion":
        return f"기준 {ref[5:]} [{n.get('type')}]: {n.get('text', '')[:200]}"
    if k == "evidence":
        s = nodes.get(src_of.get(ref, ""), {})
        return f"근거 {n.get('term')} = {n.get('value')} ({n.get('observed_date')}) 원문: \"{s.get('text', '')[:160]}\""
    if k == "source":
        return f"원문 {n.get('doc_id')}: \"{n.get('text', '')[:160]}\""
    if k == "calculation":
        return f"계산: {n.get('note', '')[:160]}"
    if k == "trial_decision":
        return f"시험 판정: {n.get('label')} ({'; '.join(n.get('why') or [])[:160]})"
    if k == "trial":
        return f"시험: {n.get('title', '')[:160]}"
    return k


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", required=True)
    ap.add_argument("--llm")
    ap.add_argument("--ranking", required=True)
    ap.add_argument("--graphs", nargs="+", required=True)
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--clinician-n", type=int, default=6, help="patients whose clinician briefing is rated sentence by sentence (the first ones picked, so properties stay covered)")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    ranks = {r["patient_id"]: r for r in read_jsonl(a.ranking)}
    llm_log = {}
    if a.llm and os.path.exists(os.path.join(a.llm, "llm_log.jsonl")):
        for l in read_jsonl(os.path.join(a.llm, "llm_log.jsonl")):
            if l.get("fallback"):
                llm_log[l["patient_id"]] = True
    base = [pid for pid in ranks if os.path.exists(os.path.join(a.template, f"{pid}.patient.json"))
            and pid.startswith("SYN-00")]           # dev base patients (variants: SYN-1xxx and up)
    if a.llm:
        base = [pid for pid in base if os.path.exists(os.path.join(a.llm, f"{pid}.patient.json"))]
    feats = [features(pid, ranks[pid], a.template, llm_log) for pid in base]
    chosen = pick(feats, a.n, a.seed)
    clin_set = {f["patient_id"] for f in chosen[:a.clinician_n]}
    rnd = random.Random(a.seed + 1)
    os.makedirs(os.path.join(a.out, "forms"), exist_ok=True)
    key, prow, crow = {}, [], []
    for k, f in enumerate(sorted(chosen, key=lambda f: f["patient_id"]), 1):
        pid, code = f["patient_id"], f"P{k:02d}"
        versions = [("template", a.template)] + ([("llm", a.llm)] if a.llm else [])
        if len(versions) == 2:
            rnd.shuffle(versions)
        key[code] = {"patient_id": pid, **{chr(65 + i): v for i, (v, _) in enumerate(versions)}}
        d = os.path.join(a.out, "packets", code)
        os.makedirs(d, exist_ok=True)
        gp = next(os.path.join(g, f"{pid}.json") for g in a.graphs if os.path.exists(os.path.join(g, f"{pid}.json")))
        g = json.load(open(gp, encoding="utf-8"))
        nodes = {n["id"]: n for n in g["nodes"]}
        src_of = {x: y for x, rel, y in g["edges"] if rel == "derived_from"}
        for i, (_, folder) in enumerate(versions):
            ab = chr(65 + i)
            for aud in ("patient", "clinician"):
                doc = json.load(open(os.path.join(folder, f"{pid}.{aud}.json"), encoding="utf-8"))
                lines = [f"# {code} {aud} {ab}\n"]
                for j, s in enumerate(doc["sentences"], 1):
                    lines.append(f"[s{j}] {s['text']}")
                    if aud == "clinician":
                        for r in s.get("refs", []):
                            lines.append(f"      - {resolve(r, nodes, src_of)}")
                        if s.get("kind") != "meta" and pid in clin_set:
                            crow.append({"code": code, "version": ab, "sid": f"s{j}", "text": s["text"],
                                         "rating": "", "severity": "", "comment": ""})
                open(os.path.join(d, f"{aud}_{ab}.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
            for it, dom, q in PATIENT_ITEMS:
                prow.append({"code": code, "version": ab, "item": it, "domain": dom, "question": q,
                             "score": "", "comment": ""})
    for name, rows, note in (("patient_form.csv", prow, PATIENT_SCALE), ("clinician_form.csv", crow, CLIN_SCALE)):
        with open(os.path.join(a.out, "forms", name), "w", newline="", encoding="utf-8-sig") as fh:
            fh.write(f"# {note}\n")
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    json.dump(key, open(os.path.join(a.out, "key.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    with open(os.path.join(a.out, "sample.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=["code"] + list(chosen[0]) + ["clinician_rated"])
        w.writeheader()
        for code, v in key.items():
            w.writerow({"code": code, **next(f for f in chosen if f["patient_id"] == v["patient_id"]),
                        "clinician_rated": v["patient_id"] in clin_set})
    print(f"{len(key)} patients x {2 if a.llm else 1} versions -> {a.out} | patient items {len(prow)}, "
          f"clinician sentences {len(crow)} | key.json is for the coordinator only")


if __name__ == "__main__":
    main()
