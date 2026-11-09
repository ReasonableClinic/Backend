#!/usr/bin/env python3
"""Carry record corrections from the data owner into finished evidence without re-running the model.

Two kinds of correction (synthetic owner, 2026-10-26):
  1. documents renumbered (`--doc-map` csv: set, patient_id, old_doc_id, new_doc_id): `source.doc_id` is rewritten
     for the patients in the evidence file; text and spans do not move
  2. same-length text edits (`--text-edits` csv: set, patient_id, doc_id, old_text, new_text; doc ids after step 1):
     evidence whose `source.text` holds the edited words gets the new words; a date that the edit changed moves in
     `observed_date` and `detail` too ("2026-03-26" -> "2026-03-20", "(03/26)" -> "(03/20)")

Every evidence is then checked against `--patients` (the corrected records): `source.text == document[span]`.
Evidence ids never change. Writes the new file and `<out>.changes_from_<prev>.jsonl`, one line per changed field.

    python3 agent2/apply_record_edits.py --evidence agent3_kit/evidence_test_haiku_v14_8.jsonl \
        --patients for_agent2_1026/input/test/patients.jsonl --doc-map ... --text-edits ... \
        --out agent3_kit/evidence_test_haiku_v14_9.jsonl --changes agent3_kit/evidence_test_haiku_v14_9.changes_from_v14_8.jsonl
"""
import argparse, csv, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract as X  # noqa: E402

ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
MD = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])")


def L(p):
    return [json.loads(x) for x in open(p, encoding="utf-8") if x.strip()]


def date_moves(old, new):
    """[(kind, old, new)] for dates the edit changed: ("iso", "2026-03-26", "2026-03-20") or ("md", (3, 26), (3, 20))."""
    out = []
    for a, b in zip(ISO.finditer(old), ISO.finditer(new)):
        if a.group(0) != b.group(0):
            out.append(("iso", a.group(0), b.group(0)))
    for a, b in zip(MD.finditer(old), MD.finditer(new)):
        if a.group(0) != b.group(0):
            out.append(("md", (int(a.group(1)), int(a.group(2))), (int(b.group(1)), int(b.group(2)))))
    return out


def move_date(value, moves):
    if not isinstance(value, str):
        return value
    for kind, a, b in moves:
        if kind == "iso" and value == a:
            return b
        if kind == "md" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) and (int(value[5:7]), int(value[8:10])) == a:
            return f"{value[:4]}-{b[0]:02d}-{b[1]:02d}"
    return value


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--evidence", required=True)
    ap.add_argument("--patients", required=True, help="the corrected records")
    ap.add_argument("--doc-map")
    ap.add_argument("--text-edits")
    ap.add_argument("--out", required=True)
    ap.add_argument("--changes", required=True)
    a = ap.parse_args()
    pats = {p["patient_id"]: p for p in L(a.patients)}
    docs = {d["doc_id"]: d["text"] for p in pats.values() for d in p["documents"]}
    dmap = {}
    if a.doc_map:
        for r in csv.DictReader(open(a.doc_map, encoding="utf-8-sig")):
            if r["patient_id"] in pats:
                dmap[r["old_doc_id"]] = r["new_doc_id"]
    edits = {}
    if a.text_edits:
        for r in csv.DictReader(open(a.text_edits, encoding="utf-8-sig")):
            if r["patient_id"] in pats:
                assert len(r["old_text"]) == len(r["new_text"]), r
                edits.setdefault(r["doc_id"], []).append((r["old_text"], r["new_text"]))
    ddates = {d["doc_id"]: d.get("date") for p in pats.values() for d in p["documents"]}
    out, changes, bad = [], [], []
    for e in L(a.evidence):
        before = json.loads(json.dumps(e))
        src = e["source"]
        if src["doc_id"] in dmap and dmap[src["doc_id"]] != src["doc_id"]:
            src["doc_id"] = dmap[src["doc_id"]]
        moves = []
        for old_t, new_t in edits.get(src["doc_id"], []):
            # the evidence span may hold the whole edited phrase or only a piece of it: compare by position
            s0, s1 = src["span"]
            slice_new = docs[src["doc_id"]][s0:s1]
            if slice_new != src["text"] and len(slice_new) == len(src["text"]):
                moves += date_moves(src["text"], slice_new)
                for k in ("quote", "date_from"):
                    if isinstance((e.get("detail") or {}).get(k), str):
                        e["detail"][k] = e["detail"][k].replace(old_t, new_t)
                        for kind, x, y in date_moves(old_t, new_t):
                            if kind == "iso":
                                e["detail"][k] = e["detail"][k].replace(x, y)
                            else:
                                e["detail"][k] = e["detail"][k].replace(f"{x[0]:02d}/{x[1]:02d}", f"{y[0]:02d}/{y[1]:02d}")
                if isinstance(e.get("term"), str):
                    e["term"] = e["term"].replace(old_t, new_t)
                src["text"] = slice_new
        if moves:
            e["observed_date"] = move_date(e.get("observed_date"), moves)
            if isinstance(e.get("value"), str):
                e["value"] = move_date(e["value"], moves)
            for k in ("start",):
                if (e.get("detail") or {}).get(k):
                    e["detail"][k] = move_date(e["detail"][k], moves)
        X.fix_md_dates([e], ddates)                       # the v14.8 month/day rule, on the corrected text
        d = docs.get(src["doc_id"])
        if d is None or d[src["span"][0]:src["span"][1]] != src["text"]:
            bad.append(e["evidence_id"])
        for f, ov, nv in (("source.doc_id", before["source"]["doc_id"], src["doc_id"]),
                          ("source.text", before["source"]["text"], src["text"]),
                          ("observed_date", before.get("observed_date"), e.get("observed_date")),
                          ("value", before.get("value"), e.get("value")),
                          ("term", before.get("term"), e.get("term")),
                          ("detail", before.get("detail"), e.get("detail"))):
            if ov != nv:
                changes.append({"evidence_id": e["evidence_id"], "patient_id": e["patient_id"], "field": f,
                                "old": ov, "new": nv})
        out.append(e)
    with open(a.out, "w", encoding="utf-8") as f:
        for e in out:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
    with open(a.changes, "w", encoding="utf-8") as f:
        for c in changes:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    n_ev = len({c["evidence_id"] for c in changes})
    print(f"{len(out)} evidence, {n_ev} changed ({len(changes)} field changes), span mismatches {len(bad)} {bad[:5]}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
