"""Pack each built state into the one JSON the web page loads: data/<pid>.<state>.json + data/index.json.

Same format as the web demo v1 build_bundle.py (웹 화면 담당), so the page reads it unchanged. Nothing here writes
content: it copies the pipeline outputs and picks only the records the briefing refs need (graph, Agent 6 ranking and
briefings, Agent 5 cards a5u + a5j, the patient's documents, the trial records, glossary rows and fixed sentences).
"""
import csv
import datetime
import glob
import hashlib
import json
import os
import sys

TRIAL_KEEP = ["trial_id", "title", "overall_status", "status_verified", "phases", "conditions", "allocation", "arms",
              "countries", "sites", "brief_summary", "min_age", "max_age", "sex"]


def _jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def _json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _glossary(a6):
    sys.path.insert(0, a6)
    from agent6.glossary import gloss_id  # noqa: E402
    rows = {}
    with open(os.path.join(a6, "agent6", "glossary.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r.get("en") and r.get("ko"):
                rows[gloss_id(r["en"])] = {"en": r["en"], "ko": r["ko"], "abbr": r.get("abbr") or ""}
    return rows


def build(state_dir, gloss, fixed, trials):
    st = _json(os.path.join(state_dir, "stage.json"))
    pid = st["patient_id"]
    graph = _json(os.path.join(state_dir, "graph", pid + ".json"))
    # a patient with no trial to recommend gets no ranking line from Agent 6 (dev SYN-0014): empty ranking, not a crash
    rows = _jl(os.path.join(state_dir, "a6", "ranking.jsonl"))
    ranking = rows[0] if rows else {"patient_id": pid, "ranking": []}
    brief = {a: _json(os.path.join(state_dir, "a6", "briefing", f"{pid}.{a}.json")) for a in ("patient", "clinician")}
    cards, parts = [], {}
    for part in ("a5u", "a5j"):
        for c in _jl(os.path.join(state_dir, part, "cards.jsonl")):
            c["_part"] = part
            cards.append(c)
        rm = os.path.join(state_dir, part, "run_meta.json")
        parts[part] = _json(rm).get("lookup_version" if part == "a5j" else "agent5_version") if os.path.exists(rm) else None
    patient = _jl(os.path.join(state_dir, "patients.jsonl"))[0]
    refs = {r for b in brief.values() for s in b["sentences"] for r in s["refs"]}
    trial_ids = {n["id"].split(":", 1)[1] for n in graph["nodes"] if n["kind"] == "trial"}
    missing = sorted(r for r in refs if (r.startswith("gloss:") and r not in gloss) or (r.startswith("rule:") and r not in fixed))
    if missing:
        raise SystemExit(f"{pid}: refs not found: {missing}")
    evs = sorted(glob.glob(os.path.join(state_dir, "evidence_*.jsonl")))
    return {
        "meta": {
            "patient_id": pid, "as_of": graph.get("as_of"), "state": st["state"],
            "agent3": st["agent3"], "agent2": st["agent2"],
            "agent6": brief["patient"].get("agent6"), "briefing": "template (틀 문장)",
            "agent5": f"a5u {parts['a5u']} + a5j {parts['a5j']}",
            "evidence_sha256": {os.path.basename(p): _sha(p) for p in evs},
            "answers": st.get("answers", []), "new_docs": st.get("new_docs", []),
        },
        "patient": {"patient_id": pid, "as_of": patient.get("as_of"), "documents": patient["documents"]},
        "graph": graph,
        "ranking": ranking,
        "briefing": brief,
        "cards": cards,
        "trials": {t: {k: trials[t].get(k) for k in TRIAL_KEEP} for t in sorted(trial_ids) if t in trials},
        "glossary": {r: gloss[r] for r in sorted(refs) if r.startswith("gloss:")},
        "rules": {r: fixed[r] for r in sorted(refs) if r.startswith("rule:")},
    }


def write_all(built, out, a6, trials_path):
    """built: [(patient_id, state, state_dir)]. Writes the bundles and index.json, returns the index."""
    gloss = _glossary(a6)
    from agent6.rules import FIXED  # noqa: E402  (a6 is on sys.path after _glossary)
    trials = {t["trial_id"]: t for t in _jl(trials_path)}
    os.makedirs(out, exist_ok=True)
    index = {"built_at": datetime.datetime.now().isoformat(timespec="seconds"), "patients": []}
    by_pid = {}
    for pid, state, d in built:
        b = build(d, gloss, FIXED, trials)
        name = f"{pid}.{state}.json"
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump(b, f, ensure_ascii=False, separators=(",", ":"))
        by_pid.setdefault(pid, []).append({"state": state, "file": name, "agent3": b["meta"]["agent3"],
                                           "answers": b["meta"]["answers"]})
        print(f"   {name}: sentences P{len(b['briefing']['patient']['sentences'])}/"
              f"C{len(b['briefing']['clinician']['sentences'])}, cards {len(b['cards'])}, trials {len(b['trials'])}, "
              f"docs {len(b['patient']['documents'])}")
    index["patients"] = [{"patient_id": p, "states": s} for p, s in by_pid.items()]
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    return index
