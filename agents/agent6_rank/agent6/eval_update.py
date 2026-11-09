"""Update response at criterion level: for each (base, variant) pair in update_pairs.csv (one document changed), do the
briefing sentences about the changed criteria change, and do the other sentences stay put?

  python3 -m agent6.eval_update runs/brief_dev --graphs G1 G2 --data K/dev

Only 1 dev pair changes a trial label, so this works per criterion, not per ranking.
- C_status (per pair): decision nodes (and crit:) whose status, reason or action differ between the two graphs, plus
  label:<trial> when the trial label or its open-criteria count differs. "The verdict changed."
- C_content: also nodes whose note, missing_fact, applicable, judged_by, calc values, or supporting evidence
  (concept, term, value, observed_date) differ. A sentence citing no
  C_content node cites exactly the same content in both graphs, so a deterministic writer must keep it word for word.
- target = variant_targets.csv target_criterion (what the injection meant to change; gold side).
- Sentences are aligned within the same audience by their refs after dropping patient-specific ids (ev:, src:);
  dec:/crit:/label:/trial:/calc:/rule:/gloss: ids are shared across the pair. Greedy match on Jaccard >= 0.5; at equal
  overlap the sentence with the same text is preferred (a6-0.4.14).
  Sentences left with no shared refs (evidence quote lines) are not scored.
Metrics:
  verdict_changed   sentences citing C_status: share whose text changed / appeared / disappeared (descriptive: a
                    changed reason can rightly leave "항목 5개" as is)
  unaffected_stable sentences citing nothing in C_content: share matched with identical text (target 100% for the
                    template writer; an LLM writer shows churn here)
  content_only      sentences citing C_content but not C_status (note / missing_fact / calc changed): share changed
  target 2x2        graph verdict of the target changed? x a sentence citing the target or its trial label changed?
                    (graph same + briefing same = Agent 6 consistent, upstream missed the update)
  A trial whose label changed, that entered/left the briefing (or the near-miss list), or whose rank position moved counts as verdict-changed for all its sentences.
  rejudged          criteria with a changed verdict per pair (1 document changed; >1 = Agent 3 re-judging churn)
"""
import argparse, csv, glob, json, os
from collections import Counter

from .graph import Graph

SHARED = ("dec:", "crit:", "label:", "trial:", "calc:", "rule:", "gloss:")   # gloss: added in a6-0.4.14


def norm_refs(s):
    return frozenset(r for r in s.get("refs", []) if r.startswith(SHARED))


def dec_sig(d):
    return (d["status"], d.get("reason"), d.get("action")) if d else None


CONTENT_KEYS = ("status", "reason", "action", "note", "missing_fact", "applicable", "judged_by")


def changed_set(gb, gv):
    """(C_status, C_content, n_rejudged_criteria)"""
    C, CC, nrej = set(), set(), 0
    tids = {n["id"][6:] for n in gb.trials()} | {n["id"][6:] for n in gv.trials()}
    for tid in tids:
        db = {d["criterion_id"]: d for d in gb.decisions(tid)}
        dv = {d["criterion_id"]: d for d in gv.decisions(tid)}
        for cid in set(db) | set(dv):
            ids = {f"crit:{cid}"} | {d["id"] for d in (db.get(cid), dv.get(cid)) if d}
            if dec_sig(db.get(cid)) != dec_sig(dv.get(cid)):
                C |= ids
                nrej += 1
            evb = sorted(json.dumps([e.get("concept"), e.get("term"), e.get("value"), e.get("observed_date")])
                         for e, _ in (gb.support(db[cid]["id"]) if cid in db else []))
            evv = sorted(json.dumps([e.get("concept"), e.get("term"), e.get("value"), e.get("observed_date")])
                         for e, _ in (gv.support(dv[cid]["id"]) if cid in dv else []))
            cb = [{k: (db.get(cid) or {}).get(k) for k in CONTENT_KEYS}, evb] + [
                {k: v for k, v in c.items() if k != "id"} for c in (gb.calculations(db[cid]["id"]) if cid in db else [])]
            cv = [{k: (dv.get(cid) or {}).get(k) for k in CONTENT_KEYS}, evv] + [
                {k: v for k, v in c.items() if k != "id"} for c in (gv.calculations(dv[cid]["id"]) if cid in dv else [])]
            if cb != cv:
                CC |= ids | {f"calc:{tid}:{cid}"}
        lb, lv = gb.label(tid), gv.label(tid)
        ob = sum(d["status"] in ("UNKNOWN", "CONFLICT") for d in db.values())
        ov = sum(d["status"] in ("UNKNOWN", "CONFLICT") for d in dv.values())
        if (lb or {}).get("label") != (lv or {}).get("label") or ob != ov:
            C.add(f"label:{tid}")
        if (lb or {}).get("why") != (lv or {}).get("why"):
            CC.add(f"label:{tid}")
    return C, C | CC, nrej


def trial_of(ref):
    """trial id a shared ref belongs to (None for rule:)."""
    k, _, rest = ref.partition(":")
    if k in ("trial", "label"):
        return rest
    if k in ("dec", "calc"):
        return rest.split(":", 1)[0]
    if k == "crit":
        return rest.rsplit("-", 1)[0]
    return None


def touches(refs, C):
    """C holds node ids and, for trials whose label/ranking changed, 'T:<trial>' (the whole trial section)."""
    return bool(refs & C) or any(f"T:{trial_of(r)}" in C for r in refs if trial_of(r))


def align(sb, sv, tb=None, tv=None):
    """greedy: [(i, j or None)] for base sentences, plus unmatched variant indexes.
    a6-0.4.14: among equal ref overlap, a sentence with the same text wins (tb/tv = texts). Several sentences of one trial
    cite only trial:<id> (size, countries, arms); when the LLM reorders them, ref overlap alone paired them crosswise and
    counted identical sentences as changed."""
    used, pairs = set(), []
    same = (lambda i, j: tb[i] == tv[j]) if tb is not None and tv is not None else (lambda i, j: False)
    cand = sorted(((len(a & b) / len(a | b), same(i, j), -i, -j, i, j) for i, a in enumerate(sb) for j, b in enumerate(sv)
                   if a and b and a & b), reverse=True)
    cand = [(c[0], c[4], c[5]) for c in cand]
    mb = {}
    for sc, i, j in cand:
        if sc < 0.5 or i in mb or j in used:
            continue
        mb[i] = j
        used.add(j)
    for i in range(len(sb)):
        pairs.append((i, mb.get(i)))
    return pairs, [j for j in range(len(sv)) if j not in used]


def compare(db, dv, C, CC, target_ids):
    sb = [s for s in db["sentences"] if s.get("kind") != "meta"]
    sv = [s for s in dv["sentences"] if s.get("kind") != "meta"]
    rb, rv = [norm_refs(s) for s in sb], [norm_refs(s) for s in sv]
    pairs, extra = align(rb, rv, [s["text"] for s in sb], [s["text"] for s in sv])
    r = Counter()
    tgt_changed = False
    for i, j in pairs:
        if not rb[i]:
            continue
        refs = rb[i] | (rv[j] if j is not None else frozenset())
        diff = j is None or sb[i]["text"] != sv[j]["text"]
        if touches(refs, C):
            r["verdict"] += 1
            r["verdict_changed"] += diff
        elif touches(refs, CC):
            r["content_only"] += 1
            r["content_only_changed"] += diff
        else:
            r["unaffected"] += 1
            r["unaffected_stable"] += not diff
        if diff and touches(refs, target_ids):
            tgt_changed = True
    for j in extra:
        if not rv[j]:
            continue
        if touches(rv[j], C):
            r["verdict"] += 1
            r["verdict_changed"] += 1
        elif touches(rv[j], CC):
            r["content_only"] += 1
            r["content_only_changed"] += 1
        else:
            r["unaffected"] += 1     # a new sentence about something that did not change
        if touches(rv[j], target_ids):
            tgt_changed = True
    return r, tgt_changed


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--data", required=True, help="K/dev (reads eval/update_pairs.csv, eval/variant_targets.csv)")
    ap.add_argument("--show", type=int, default=0, help="print this many per-pair rows")
    a = ap.parse_args(argv)
    gpath = lambda pid: next((os.path.join(d, f"{pid}.json") for d in a.graphs if os.path.exists(os.path.join(d, f"{pid}.json"))), None)
    targets = {}
    for row in csv.DictReader(open(os.path.join(a.data, "eval", "variant_targets.csv"), encoding="utf-8-sig")):
        targets[row["variant_patient_id"]] = row["target_criterion"]
    pairs = list(csv.DictReader(open(os.path.join(a.data, "eval", "update_pairs.csv"), encoding="utf-8-sig")))
    agg = {aud: Counter() for aud in ("patient", "clinician")}
    shown, rejudged = 0, []
    for p in pairs:
        v, b = p["variant_patient_id"], p["base_patient_id"]
        if not (gpath(v) and gpath(b)):
            continue
        gb, gv = Graph.load(gpath(b)), Graph.load(gpath(v))
        C, CC, nrej = changed_set(gb, gv)
        rejudged.append(nrej)
        tc = targets.get(v)
        tid = tc.rsplit("-", 1)[0] if tc else None
        target_ids = {f"crit:{tc}"} | {d["id"] for d in (gb.decision(f"crit:{tc}"), gv.decision(f"crit:{tc}")) if d} if tc else set()
        graph_tgt = bool(target_ids & C)
        target_ids = target_ids | ({f"label:{tid}"} if tid else set())
        for aud in agg:
            fb, fv = (os.path.join(a.folder, f"{x}.{aud}.json") for x in (b, v))
            if not (os.path.exists(fb) and os.path.exists(fv)):
                continue
            db, dv = (json.load(open(f, encoding="utf-8")) for f in (fb, fv))
            rkb, rkv = db.get("ranking", []), dv.get("ranking", [])
            moved = {f"T:{t}" for t in set(rkb) ^ set(rkv)} | {f"T:{t}" for t in set(rkb) & set(rkv) if rkb.index(t) != rkv.index(t)}
            moved |= {f"T:{t}" for t in set(db.get("also_mentioned", [])) ^ set(dv.get("also_mentioned", []))}
            moved |= {f"T:{x[6:]}" for x in C if x.startswith("label:")
                      and (gb.label(x[6:]) or {}).get("label") != (gv.label(x[6:]) or {}).get("label")}
            r, tgt = compare(db, dv, C | moved, CC | moved, target_ids | ({f"T:{tid}"} & moved if tid else set()))
            # target in the briefing at all? (patient briefing only shows top trials and open criteria)
            shown_t = tid in (db.get("ranking", []) + dv.get("ranking", []))
            r["pairs"] += 1
            r[f"target graph_{'changed' if graph_tgt else 'same'} / brief_{'changed' if tgt else 'same'}"
              + ("" if shown_t else " (trial not in briefing)")] += 1
            agg[aud].update(r)
            if shown < a.show:
                print(f"  {b}->{v} {aud} |C|={len(C)} target={tc} graph_changed={graph_tgt} brief_changed={tgt} {dict(r)}")
                shown += 1
    pct = lambda a, b: f"{a}/{b} ({a / max(b, 1):.1%})"
    rj = sorted(rejudged)
    if rj:
        print(f"rejudged criteria per pair (1 document changed): median {rj[len(rj) // 2]}, min {rj[0]}, max {rj[-1]}")
    for aud, r in agg.items():
        tg = ", ".join(f"{k}: {v}" for k, v in sorted(r.items()) if k.startswith("target"))
        print(f"[{aud}] pairs {r['pairs']} | unaffected_stable {pct(r['unaffected_stable'], r['unaffected'])} | "
              f"verdict_changed {pct(r['verdict_changed'], r['verdict'])} | content_only_changed "
              f"{pct(r['content_only_changed'], r['content_only'])}\n  {tg}")


if __name__ == "__main__":
    main()
