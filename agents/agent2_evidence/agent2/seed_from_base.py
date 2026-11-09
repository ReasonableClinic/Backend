#!/usr/bin/env python3
"""Seed an extraction of new patients whose records copy documents of already extracted patients (variant sets).

For each new patient: find the extracted patient with the most documents of identical text, copy that patient's
evidence for those documents under the new patient and document ids (spans stay valid: the text is identical), and
write the record as it was "known" (only the copied documents). `update.py --old <seed> --old-patients <known>` then
extracts only the documents that are new or different, with the same plan and settings, and merges.

Why: evidence of unchanged documents stays exactly the evidence the base patient has, so a variant differs from its
base only where its record differs (a model re-run would add run-to-run noise, about 10% of facts, to every
document). Evidence ids are numbered for the new patient (`<new id>-EVnnn`).

    python3 agent2/seed_from_base.py --patients variants/patients.jsonl --base-patients data/dev/input/patients.jsonl \
        --base-evidence agent3_kit/evidence_dev_haiku_v14_9.jsonl --out runs/variants_seed_haiku

Writes <out>/evidence.jsonl, <out>/known_patients.jsonl and <out>/seed_map.jsonl (which base patient and documents
were reused: internal, never put in the kit, it would tell Agent 3 which document was changed).
"""
import argparse, collections, json, os


def L(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--patients", required=True)
    ap.add_argument("--base-patients", required=True)
    ap.add_argument("--base-evidence", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    base = L(a.base_patients)
    by_text = collections.defaultdict(list)                 # document text -> [(base pid, base doc)]
    for p in base:
        for d in p["documents"]:
            by_text[d["text"]].append((p["patient_id"], d))
    bev = collections.defaultdict(list)
    for e in L(a.base_evidence):
        bev[(e["patient_id"], e["source"]["doc_id"])].append(e)
    out_ev, known, smap = [], [], []
    for p in L(a.patients):
        votes = collections.Counter(bp for d in p["documents"] for bp, _ in by_text.get(d["text"], []))
        if not votes:
            known.append(dict(p, documents=[]))
            smap.append({"patient_id": p["patient_id"], "base": None, "reused": [], "new_or_changed": [d["doc_id"] for d in p["documents"]]})
            continue
        bp = votes.most_common(1)[0][0]
        reused, fresh, docs = [], [], []
        n = 0
        for d in p["documents"]:
            hit = next((bd for b, bd in by_text.get(d["text"], []) if b == bp and bd.get("date") == d.get("date")
                        and bd.get("type") == d.get("type")), None)
            if not hit:
                fresh.append(d["doc_id"])
                continue
            reused.append([d["doc_id"], hit["doc_id"]])
            docs.append(d)
            for e in sorted(bev[(bp, hit["doc_id"])], key=lambda x: int(x["evidence_id"].rsplit("-EV", 1)[1])):
                n += 1
                src = dict(e["source"], doc_id=d["doc_id"])
                out_ev.append(dict(e, patient_id=p["patient_id"], evidence_id=f"{p['patient_id']}-EV{n:03d}", source=src))
        known.append(dict(p, documents=docs))
        smap.append({"patient_id": p["patient_id"], "base": bp, "reused": reused, "new_or_changed": fresh})
    for name, rows in (("evidence.jsonl", out_ev), ("known_patients.jsonl", known), ("seed_map.jsonl", smap)):
        with open(os.path.join(a.out, name), "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(known)} patients, {sum(1 for s in smap if s['base'])} matched to a base patient, "
          f"{sum(len(s['reused']) for s in smap)} documents reused, {sum(len(s['new_or_changed']) for s in smap)} to extract, "
          f"{len(out_ev)} evidence copied -> {a.out}")


if __name__ == "__main__":
    main()
