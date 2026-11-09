#!/usr/bin/env python3
"""Keep evidence ids stable across Agent 2 versions.

A new Agent 2 version re-extracts every record and numbers its evidence from EV001 again, so one dropped fact
shifts every later id and Agent 3's saved judgments (and its replay cache) point at the wrong evidence. This
script gives every evidence of the new run the id it had in the old run when it is the same fact (same document,
span, concept, term, value; or same place, concept and value with a corrected term -> listed as "changed"), and
the next unused numbers otherwise. An id of the old run that has no match is
never reused. A `changes.jsonl` (same format as update.py) lists what was added and removed per patient.

    python3 agent2/carry_ids.py --old agent3_kit/evidence_dev_haiku_v13_7.jsonl --new runs/X/evidence.jsonl \
        --out agent3_kit/evidence_dev_haiku_v13_8.jsonl
"""
import argparse, collections, json, os

NUM = lambda eid: int(eid.rsplit("-EV", 1)[1])  # noqa: E731


def key(e, with_span=True):
    return (e["source"]["doc_id"], tuple(e["source"]["span"]) if with_span else e["source"]["text"], e["concept"],
            e.get("term"), json.dumps(e["value"]), e["subject"], e["certainty"])


GENERIC = {"lab_other", "symptom_finding", "diagnosis", "treatment_plan", "medication", "procedure", "tumor_marker",
           "biomarker", "social_history"}


def _norm(v):
    if isinstance(v, str):
        x = v.strip().lower()
        if x in ("negative", "nonreactive", "non-reactive", "not detected", "absent", "no"):
            return False
        if x in ("positive", "reactive", "detected", "present", "yes"):
            return True
        try:
            return float(x.replace(",", ""))
        except ValueError:
            return x
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _words(t):
    import re
    return {w[:4] for w in re.findall(r"[a-z][a-z0-9]{2,}", (t or "").lower())}


def same_fact(o, n):
    if o["subject"] != n["subject"]:
        return False
    if o["concept"] != n["concept"] and not (o["concept"] in GENERIC or n["concept"] in GENERIC):
        return False
    if _norm(o["value"]) == _norm(n["value"]) and (o["concept"] == n["concept"] or _words(o.get("term")) & _words(
            (n.get("term") or "") + " " + n["concept"].replace("_", " "))):
        return True
    return (o["concept"] == n["concept"] and bool(_words(o.get("term")) & _words(n.get("term")))
            and not (isinstance(_norm(o["value"]), bool) and isinstance(_norm(n["value"]), bool)
                     and _norm(o["value"]) != _norm(n["value"])))


def carry(old, new):
    old_by = collections.defaultdict(list)
    for e in old:
        old_by[e["patient_id"]].append(e)
    new_by = collections.defaultdict(list)
    for e in new:
        new_by[e["patient_id"]].append(e)
    out, changes = [], []
    for pid in list(dict.fromkeys([e["patient_id"] for e in new] + [e["patient_id"] for e in old])):
        olds, news = old_by.get(pid, []), new_by.get(pid, [])
        pool = collections.defaultdict(list)
        for e in olds:
            pool[key(e)].append(e["evidence_id"])
        loose = collections.defaultdict(list)          # same fact, position moved (segmentation change)
        for e in olds:
            loose[key(e, False)].append(e["evidence_id"])
        relabel = collections.defaultdict(list)        # same place and value, term or attributes corrected
        for e in olds:
            relabel[(e["source"]["doc_id"], tuple(e["source"]["span"]), e["concept"], json.dumps(e["value"]))].append(
                e["evidence_id"])
        old_by_id = {e["evidence_id"]: e for e in olds}
        changed = []
        used, nxt, added, kept = set(), max([NUM(e["evidence_id"]) for e in olds] + [0]) + 1, [], []
        pending = []
        for e in news:
            ids = [i for i in pool.get(key(e), []) if i not in used]
            if ids:
                used.add(ids[0])
                kept.append(dict(e, evidence_id=ids[0]))
            else:
                pending.append(e)
        for e in pending:
            ids = [i for i in loose.get(key(e, False), []) if i not in used]
            ids2 = [i for i in relabel.get((e["source"]["doc_id"], tuple(e["source"]["span"]), e["concept"],
                                            json.dumps(e["value"])), []) if i not in used]
            if ids:
                used.add(ids[0])
                kept.append(dict(e, evidence_id=ids[0]))
            elif ids2:                                 # e.g. a medication fragment that now names its drug
                used.add(ids2[0])
                kept.append(dict(e, evidence_id=ids2[0]))
                changed.append(ids2[0])
            else:
                e = dict(e, evidence_id=f"{pid}-EV{nxt:03d}")
                nxt += 1
                kept.append(e)
                added.append(e["evidence_id"])
        # last pass: the same sentence restated by a new run ("ANA negative" vs false, "RBC 4.9" vs the whole
        # line, lab_other -> a specific key): same document and span, same or refined concept, and an equivalent
        # value or a shared word in the term -> keep the id, listed as "changed"
        left_old = collections.defaultdict(list)
        for e in olds:
            if e["evidence_id"] not in used:
                left_old[(e["source"]["doc_id"], tuple(e["source"]["span"]))].append(e)
        still = []
        for e in [x for x in kept if x["evidence_id"] in set(added)]:
            cands = left_old.get((e["source"]["doc_id"], tuple(e["source"]["span"])), [])
            m = next((o for o in cands if o["evidence_id"] not in used and same_fact(o, e)), None)
            if m:
                used.add(m["evidence_id"])
                added.remove(e["evidence_id"])
                e["evidence_id"] = m["evidence_id"]
                changed.append(m["evidence_id"])
        kept.sort(key=lambda e: NUM(e["evidence_id"]))
        out += kept
        removed = [e["evidence_id"] for e in olds if e["evidence_id"] not in used]
        changes.append({"patient_id": pid, "added": added, "removed": removed, "changed": changed, "kept": len(used)})
    return out, changes


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--changes", help="default: <out without .jsonl>.changes.jsonl")
    a = ap.parse_args()
    L = lambda f: [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]  # noqa: E731
    out, changes = carry(L(a.old), L(a.new))
    with open(a.out, "w", encoding="utf-8") as f:
        for e in out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    cpath = a.changes or os.path.splitext(a.out)[0] + ".changes.jsonl"
    with open(cpath, "w", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"{len(out)} evidence, kept ids {sum(c['kept'] for c in changes)}, added {sum(len(c['added']) for c in changes)}, "
          f"removed {sum(len(c['removed']) for c in changes)} -> {a.out}, {cpath}")


if __name__ == "__main__":
    main()
