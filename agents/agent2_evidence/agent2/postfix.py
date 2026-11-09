#!/usr/bin/env python3
"""Apply Agent 2's evidence-level corrections (extract.lab_values, extract.post_fix) to a finished evidence file
without re-running the model. Evidence ids stay; an evidence the corrections drop is listed as "removed", one
they rewrite as "changed" (changes.jsonl, same format as carry_ids.py / update.py).

    python3 agent2/postfix.py --in agent3_kit/evidence_dev_haiku_v14.jsonl --out agent3_kit/evidence_dev_haiku_v14_3.jsonl \
        --patients data/dev/input/patients.jsonl --add-rule measurable_disease

With --patients and --add-rule, rule facts of those concepts that the file has nowhere at the same place are added
with the next unused ids ("added"), as a model run of this version would (llm_layer.rule_missing).
"""
import argparse, collections, copy, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract as X  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concepts", default=os.path.join(X.HERE, "concepts.json"))
    ap.add_argument("--patients")
    ap.add_argument("--add-rule", default="", help="comma-separated concepts")
    a = ap.parse_args()
    ex = X.Extractor(X.load_concepts(a.concepts))
    add_keys = {k for k in a.add_rule.split(",") if k}
    pats, docs, ddates = {}, {}, {}
    if a.patients:
        for line in open(a.patients, encoding="utf-8"):
            if line.strip():
                p = json.loads(line)
                docs[p["patient_id"]] = {d["doc_id"]: d["text"] for d in p["documents"]}
                ddates.update({d["doc_id"]: d.get("date") for d in p["documents"]})
    if a.patients and add_keys:
        for line in open(a.patients, encoding="utf-8"):
            if line.strip():
                p = json.loads(line)
                pats[p["patient_id"]] = p           # sets the lab matchers lab_values uses
    by = collections.defaultdict(list)
    for line in open(a.inp, encoding="utf-8"):
        if line.strip():
            e = json.loads(line)
            by[e["patient_id"]].append(e)
    out, changes, tot = [], [], collections.Counter()
    for pid, evs in by.items():
        before = {e["evidence_id"]: copy.deepcopy(e) for e in evs}
        tot["fix_lab_value"] += X.lab_values(evs, X.LAB_CONCEPTS)
        if ddates:
            tot["fix_md_date"] += X.fix_md_dates(evs, ddates)
        evs, c = X.post_fix(evs, docs.get(pid))
        tot.update(c)
        seen, keep = set(), []
        for e in evs:
            k = (e["source"]["doc_id"], tuple(e["source"]["span"]), e["concept"], json.dumps(e["value"]), e.get("term"))
            if k in seen:
                tot["drop_duplicate"] += 1
                continue
            seen.add(k)
            keep.append(e)
        added = []
        if pid in pats:
            rule_evs, _ = ex.patient(pats[pid])
            nxt = max(int(i.rsplit("-EV", 1)[1]) for i in before) + 1
            for r in rule_evs:
                if r["concept"] not in add_keys:
                    continue
                d, (s0, e0) = r["source"]["doc_id"], r["source"]["span"]
                if any(k["concept"] == r["concept"] and k["source"]["doc_id"] == d and k["source"]["span"][0] < e0
                       and s0 < k["source"]["span"][1] for k in keep):
                    continue
                r = dict(r, evidence_id=f"{pid}-EV{nxt:03d}")
                nxt += 1
                keep.append(r)
                added.append(r["evidence_id"])
                tot[f"add_rule_{r['concept']}"] += 1
        ids = {e["evidence_id"] for e in keep}
        changed = [e["evidence_id"] for e in keep if e["evidence_id"] in before and e != before[e["evidence_id"]]]
        removed = [i for i in before if i not in ids]
        changes.append({"patient_id": pid, "added": added, "removed": removed, "changed": changed, "kept": len(keep)})
        out += keep
    with open(a.out, "w", encoding="utf-8") as f:
        for e in out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    cp = os.path.splitext(a.out)[0] + ".changes.jsonl"
    with open(cp, "w", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"{len(out)} evidence, changed {sum(len(c['changed']) for c in changes)}, removed "
          f"{sum(len(c['removed']) for c in changes)}; {dict(tot)} -> {a.out}, {cp}")


if __name__ == "__main__":
    main()
