"""Agent 6 baseline ranking: common format 6.4 sort rules applied to Agent 3 (or Agent 4) output. No LLM.

  python3 -m agent6.rank --agent3 K/dev/agent3_out_a031/agent3_out.jsonl --trials K/dev/reference/trials.jsonl \
      --out runs/rank_dev/ranking.jsonl
  (K = the for_agent456_v6 folder)

One line per patient: {"patient_id", "as_of", "ranking": [trial_id...], "stale_trials", "dropped_stale_trials", "items"}.
`ranking`, `stale_trials`, `dropped_stale_trials` follow ranking_gold.jsonl; `items` explains each trial's place
(tier, open criteria, KR, months since status_verified) so the briefing can say *why* without re-deriving it.
"""
import argparse, json, os
from datetime import date

from .review import age_outside, near_miss, patient_age_from_rows, row_flags

KR = "South Korea"


def read_jsonl(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def months_since(ym, as_of):
    """status_verified 'YYYY-MM' -> whole months before as_of (None when unknown)."""
    if not ym:
        return None
    y, m = int(ym[:4]), int(ym[5:7])
    a = date.fromisoformat(as_of)
    return (a.year - y) * 12 + (a.month - m)


def kr_info(trial):
    """kr_recruiting / kr_sites as common format §2 defines them (derived; trials.jsonl does not carry them)."""
    if "kr_recruiting" in trial:
        return bool(trial["kr_recruiting"]), int(trial.get("kr_sites") or 0)
    ok = ("RECRUITING", "NOT_YET_RECRUITING")
    n = sum(1 for s in trial.get("sites") or []
            if s.get("country") == KR and (s.get("status") or trial.get("overall_status")) in ok)
    return KR in (trial.get("countries") or []), n


def open_criteria(row):
    return [c["criterion_id"] for c in row["criteria"] if c.get("applicable", True) and c["status"] in ("UNKNOWN", "CONFLICT")]


def rank_patient(rows, trials, as_of):
    items, dropped = [], []
    patient_age = patient_age_from_rows(rows)
    for r in rows:
        if r["trial_label"] not in ("eligible", "potential"):
            continue
        t = trials.get(r["trial_id"], {})
        age = months_since(t.get("status_verified"), as_of)
        if age is not None and age > 24:
            dropped.append(r["trial_id"])
            continue
        kr, kr_sites = kr_info(t)
        oc = open_criteria(r)
        items.append({"trial_id": r["trial_id"], "label": r["trial_label"], "open_criteria": oc,
                      "stale": age is not None and age > 12, "status_verified": t.get("status_verified"),
                      "months_since_verified": age, "kr_recruiting": kr, "kr_sites": kr_sites,
                      "overall_status": t.get("overall_status"), "label_why": r.get("label_why", []),
                      "review_flags": row_flags(r) + ([{"criterion_id": None, "flag": "age_mismatch"}]
                                                      if age_outside(patient_age, t) else [])})   # briefings only, not sorted on

    def key(i):
        return (i["label"] != "eligible",                 # 1. eligible first
                i["stale"],                               # 2. >12 months unverified to the back of its tier
                len(i["open_criteria"]),                  # 3. fewer UNKNOWN/CONFLICT
                not i["kr_recruiting"],                   # 4. KR inside the tier only
                i["overall_status"] != "RECRUITING",      # 5. RECRUITING before NOT_YET_RECRUITING
                -(12 * int(i["status_verified"][:4]) + int(i["status_verified"][5:7])) if i["status_verified"] else 0,
                i["trial_id"])                            # stable tie-break
    items.sort(key=key)
    for n, i in enumerate(items, 1):
        i["rank"] = n
    return {"ranking": [i["trial_id"] for i in items], "stale_trials": [i["trial_id"] for i in items if i["stale"]],
            "dropped_stale_trials": sorted(dropped), "items": items, "near_miss": near_miss(rows)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent3", required=True, nargs="+", help="agent3_out.jsonl (several files are concatenated)")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    by_p = {}
    for f in a.agent3:
        for r in read_jsonl(f):
            by_p.setdefault(r["patient_id"], []).append(r)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        for pid in sorted(by_p):
            rows = by_p[pid]
            res = rank_patient(rows, trials, rows[0]["as_of"])
            f.write(json.dumps({"patient_id": pid, "as_of": rows[0]["as_of"], **res}, ensure_ascii=False) + "\n")
    print(f"{len(by_p)} patients -> {a.out}")


if __name__ == "__main__":
    main()
