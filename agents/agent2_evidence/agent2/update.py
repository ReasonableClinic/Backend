#!/usr/bin/env python3
"""Update path: re-extract only the documents that are new or changed since the last extraction, and merge.

When Agent 4 (verification) or Agent 5 (information gathering) brings new information, the record gains documents
(a new lab result, the patient's answer to a question) or, rarely, a corrected one. Re-extracting the whole record
would take 8-12 s and about $0.08 per patient; re-extracting the new documents is usually one or two requests.

What happens per patient:
  1. compare the record with the manifest of the last run (`docs.jsonl`: doc_id -> hash of text, date and type)
     new doc       -> extract it
     changed doc   -> drop its old evidence, extract it again
     removed doc   -> drop its old evidence
     same doc      -> keep its evidence and evidence_id unchanged
  2. new evidence gets the next free numbers (SYN-0001-EV257, ...): an evidence_id never changes meaning
  3. code-derived evidence follows the record: age from the date of birth is recomputed when as_of changes; sex
     from pronouns is dropped once a document states the sex
  4. `changes.jsonl` lists what was added, removed and changed, so Agent 3 re-judges only the criteria that used
     those evidence or whose concept they carry. In a changed document, a fact that comes out again the same (same
     sentence, concept, term, value, subject, certainty) keeps its id: "moved" when only its position moved (nothing
     to re-judge), "changed" when its date or detail changed

The plan (candidate trials and their criteria in the prompt) is computed from the whole record, so the prompt is the
same as in the first extraction: the static part and the criteria part are read from the prompt cache when the update
comes within its lifetime (5 minutes by default, `--ttl 1h` for longer).

Without a manifest (outputs made before v13.5), pass the record as it was with --old-patients; with neither, a
document counts as known when old evidence points into it and every such span still holds the same text.

    python3 agent2/update.py --patients new_patients.jsonl --old runs/dev_haiku --trials ... --criteria-ref ... \
        --provider anthropic --out runs/dev_haiku_upd
    (--provider rules: rule layer only, no LLM)
"""
import argparse, collections, json, os, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import llm_layer as LL  # noqa: E402
import plan as PL  # noqa: E402
from extract import Extractor, load_concepts, concept_list, age_on, self_check  # noqa: E402

EV_NUM = lambda eid: int(eid.rsplit("-EV", 1)[1])  # noqa: E731


def load_jsonl(path):
    return [json.loads(x) for x in open(path, encoding="utf-8") if x.strip()]


def known_docs(pid, old_dir, old_patients, old_evs, p):
    """doc_id -> hash of the version the old evidence came from (None: version unknown, judged by spans)."""
    man = os.path.join(old_dir, "docs.jsonl")
    if os.path.exists(man):
        for r in load_jsonl(man):
            if r["patient_id"] == pid:
                return r["docs"], r.get("as_of"), "manifest"
        return {}, None, "manifest"
    if old_patients and pid in old_patients:
        op = old_patients[pid]
        return {d["doc_id"]: LL.doc_hash(d) for d in op["documents"]}, op["as_of"], "old_patients"
    texts = {d["doc_id"]: d for d in p["documents"]}
    out = {}
    for e in old_evs:
        d, (s, t) = texts.get(e["source"]["doc_id"]), e["source"]["span"]
        ok = d is not None and d["text"][s:t] == e["source"]["text"]
        out[e["source"]["doc_id"]] = out.get(e["source"]["doc_id"], True) and ok
    print(f"  {pid}: WARNING no docs.jsonl in {old_dir} and no --old-patients: documents are compared by the old "
          f"evidence spans only, so text added to a known document without moving those spans is missed", flush=True)
    return {k: (LL.doc_hash(texts[k]) if ok else "changed") for k, ok in out.items()}, None, "spans"


def diff_docs(p, known):
    now = {d["doc_id"]: LL.doc_hash(d) for d in p["documents"]}
    new = [k for k in now if k not in known]
    changed = [k for k in now if k in known and known[k] != now[k]]
    removed = [k for k in known if k not in now]
    return new, changed, removed


def merge(p, old_evs, new_evs, drop_docs, old_as_of):
    """Old evidence of untouched documents keeps its id; new evidence gets the next numbers."""
    pid, as_of = p["patient_id"], p["as_of"]
    keep = [e for e in old_evs if e["source"]["doc_id"] not in drop_docs]
    # evidence of a changed document that comes out again the same (same sentence, concept, term, value, subject,
    # certainty) keeps its old id: one sentence added to a note must not make Agent 3 re-judge the whole note
    # (review of v13.5: 6 unchanged facts of SYN-0006-D02 were removed and re-added under new numbers)
    same_key = lambda e: (e["source"]["doc_id"], e["source"]["text"], e["concept"], e.get("term"),  # noqa: E731
                          json.dumps(e["value"]), e["subject"], e["certainty"])
    reusable = collections.defaultdict(list)
    for e in old_evs:
        if e["source"]["doc_id"] in drop_docs:
            reusable[same_key(e)].append(e)
    removed, changed, moved, reused_ids = [], [], [], set()
    new_rest = []
    for e in new_evs:
        olds = reusable.get(same_key(e))
        if olds:
            o = olds.pop(0)
            e2 = dict(e, evidence_id=o["evidence_id"])
            keep.append(e2)
            reused_ids.add(o["evidence_id"])
            if e2.get("observed_date") != o.get("observed_date") or e2.get("detail") != o.get("detail"):
                changed.append(o["evidence_id"])          # same fact, re-dated or re-qualified: re-judge
            elif e2["source"]["span"] != o["source"]["span"]:
                moved.append(o["evidence_id"])            # same fact, only its position moved: nothing to re-judge
        else:
            new_rest.append(e)
    new_evs = new_rest
    removed = [e["evidence_id"] for e in old_evs if e["source"]["doc_id"] in drop_docs and e["evidence_id"] not in reused_ids]
    # code-derived evidence follows the record
    if old_as_of and old_as_of != as_of:
        for e in keep:
            if (e.get("detail") or {}).get("derived_from") == "birth_date" and e["concept"] == "age":
                b = next((x for x in keep if x["concept"] == "birth_date" and x["source"]["doc_id"] == e["source"]["doc_id"]), None)
                if b:
                    e.update(value=age_on(date.fromisoformat(b["value"]), date.fromisoformat(as_of)), observed_date=as_of)
                    changed.append(e["evidence_id"])
    stated_sex = any(e["concept"] == "sex" and (e.get("detail") or {}).get("derived_from") != "pronouns"
                     for e in keep + new_evs)
    if stated_sex:
        for e in list(keep):
            if e["concept"] == "sex" and (e.get("detail") or {}).get("derived_from") == "pronouns":
                keep.remove(e)
                removed.append(e["evidence_id"])
    have = {(e["source"]["doc_id"], tuple(e["source"]["span"]), e["concept"], json.dumps(e["value"]), e.get("term"))
            for e in keep}
    nxt = max([EV_NUM(e["evidence_id"]) for e in old_evs] + [0]) + 1
    added = []
    for e in new_evs:
        if (e.get("detail") or {}).get("derived_from") == "pronouns" and (stated_sex or any(x["concept"] == "sex" for x in keep)):
            continue
        k = (e["source"]["doc_id"], tuple(e["source"]["span"]), e["concept"], json.dumps(e["value"]), e.get("term"))
        if k in have:
            continue
        e = dict(e, evidence_id=f"{pid}-EV{nxt:03d}")
        nxt += 1
        keep.append(e)
        added.append(e)
    return keep, added, removed, changed, moved


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patients", required=True, help="the records now (all documents)")
    ap.add_argument("--old", required=True, help="folder of the last run: evidence.jsonl (+ docs.jsonl)")
    ap.add_argument("--old-patients", help="the records as they were at the last run (when it has no docs.jsonl)")
    ap.add_argument("--concepts", default=os.path.join(HERE, "concepts.json"))
    ap.add_argument("--trials")
    ap.add_argument("--criteria-ref")
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--k-criteria", type=int, default=10)
    ap.add_argument("--max-criteria", type=int, default=250)
    ap.add_argument("--relevance", choices=["all", "criteria"], default="criteria")
    ap.add_argument("--provider", choices=["rules", "openrouter", "anthropic", "mock", "replay"], default="anthropic")
    ap.add_argument("--model")
    ap.add_argument("--chunk", type=int, default=15)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--min-retry", type=int, default=5)
    ap.add_argument("--send-all", action="store_true")
    ap.add_argument("--ttl", choices=["5m", "1h"])
    ap.add_argument("--prewarm", choices=["auto", "on", "off"], default="auto")
    ap.add_argument("--cache-dir")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    a.online, a.dry_run = True, False
    os.makedirs(a.out, exist_ok=True)
    concepts = load_concepts(a.concepts)                 # team list + Agent 2 overlay
    clist = concept_list(concepts)
    concept_text = "\n".join(f"{c['key']} | {c['type']} | {c.get('unit') or '-'} | {c['name']}" for c in clist)
    ex = Extractor(load_concepts(a.concepts))
    planner = PL.Planner(load_jsonl(a.trials), load_jsonl(a.criteria_ref)) if a.trials and a.criteria_ref else None
    if a.relevance == "criteria" and not planner and a.provider != "rules":
        ap.error("--relevance criteria needs --trials and --criteria-ref")
    patients = load_jsonl(a.patients)
    old_by = collections.defaultdict(list)
    for e in load_jsonl(os.path.join(a.old, "evidence.jsonl")):
        old_by[e["patient_id"]].append(e)
    old_patients = {p["patient_id"]: p for p in load_jsonl(a.old_patients)} if a.old_patients else None
    backend = None
    if a.provider != "rules":
        a.model = a.model or LL.DEFAULT_MODEL[a.provider]
        backend = LL.Backend(a.provider, a.model, a.cache_dir or os.path.join(a.out, "cache"), workers=a.workers, ttl=a.ttl)
        run_id = os.environ.get("AGENT2_RUN_ID") or f"update-{os.path.basename(os.path.normpath(a.out))}-{time.strftime('%Y%m%d-%H%M%S')}"
        backend.tracer = LL.Tracer.create(run_id, a.provider, a.model, label=os.environ.get("AGENT2_TRACE_LABEL"),
                                          version=os.environ.get("AGENT2_VERSION", "v14.12"))

    out_evs, changes, logs = [], [], []
    with open(os.path.join(a.out, "answers.jsonl"), "a", encoding="utf-8") as alog:
        for p in patients:
            pid, t0 = p["patient_id"], time.time()
            old_evs = old_by.get(pid, [])
            known, old_as_of, how = known_docs(pid, a.old, old_patients, old_evs, p)
            if not old_evs and how != "manifest":
                known = {}                                   # a new patient: everything is new
            new, changed, removed = diff_docs(p, known)
            todo = set(new) | set(changed)
            new_evs, checks = [], {}
            if todo:
                if a.provider == "rules":
                    pl = planner.plan(p, a.k) if planner else None
                    sub = dict(p, documents=[d for d in p["documents"] if d["doc_id"] in todo])
                    new_evs, checks = ex.patient(sub, pl)
                else:
                    st = LL.run([p], ex, concepts, concept_text, planner, backend, a, alog, only_docs={pid: todo})[0]
                    new_evs, lg = LL.finalize(st)
                    checks = lg["checks"]
                    backend.tracer.patient_result(dict(lg, docs_extracted=sorted(todo)))
            merged, added, dropped, recomputed, moved = merge(p, old_evs, new_evs, set(changed) | set(removed), old_as_of)
            merged, _ = self_check(merged, p, p["as_of"])
            secs = round(time.time() - t0, 2)
            out_evs += merged
            changes.append({"patient_id": pid, "docs": {"new": new, "changed": changed, "removed": removed},
                            "added": [e["evidence_id"] for e in added], "removed": dropped, "changed": recomputed, "moved": moved,
                            "added_concepts": sorted({e["concept"] for e in added}),
                            "removed_concepts": sorted({e["concept"] for e in old_evs if e["evidence_id"] in set(dropped)}),
                            "known_from": how, "seconds": secs})
            logs.append({"patient_id": pid, "docs_extracted": sorted(todo), "n_evidence": len(merged), "checks": checks,
                         "seconds": secs})
            if todo or removed:
                print(f"  {pid}: docs new {new} changed {changed} removed {removed} -> +{len(added)} -{len(dropped)} "
                      f"evidence, {secs} s", flush=True)

    def dump(name, rows):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    dump("evidence.jsonl", out_evs)
    dump("changes.jsonl", changes)
    dump("log.jsonl", logs)
    LL.write_manifest(patients, os.path.join(a.out, "docs.jsonl"))
    touched = [c for c in changes if c["docs"]["new"] or c["docs"]["changed"] or c["docs"]["removed"]]
    secs = sorted(c["seconds"] for c in touched) or [0]
    usage = dict(backend.report() if backend else {}, provider=a.provider, model=a.model, patients=len(patients),
                 patients_updated=len(touched), evidence=len(out_evs),
                 patient_seconds={"p50": secs[len(secs) // 2], "max": secs[-1]})
    json.dump(usage, open(os.path.join(a.out, "usage.json"), "w"), indent=1)
    print(f"{len(touched)} of {len(patients)} patients updated; {len(out_evs)} evidence -> {a.out}/evidence.jsonl, "
          f"changes -> {a.out}/changes.jsonl")
    print("usage:", json.dumps(usage))
    if backend:
        backend.tracer.finish()


if __name__ == "__main__":
    main()
