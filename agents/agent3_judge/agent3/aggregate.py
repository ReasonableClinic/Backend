"""Trial label from criterion judgments: common format 6.1 (same rule as gold_lib.trial_label)."""


def trial_label(results, crit_by_id, prefilter_reasons=()):
    """results: applicable criterion results. Returns (label, why)."""
    if prefilter_reasons:
        return "ineligible", list(prefilter_reasons)
    fails = [r["criterion_id"] for r in results if r["status"] == "FAIL"]
    if fails:
        return "ineligible", [f"FAIL {c}" for c in fails]
    why = []
    for r in results:
        c = crit_by_id[r["criterion_id"]]
        incl = c["type"] != "exclusion"            # I and U count as inclusion
        if "pc:llm_missing" in (r.get("rule_tags") or []):
            # no answer from the model (API failure, cache miss, criterion left out of the reply): never judged,
            # so it blocks eligible even as an exclusion (Agent 5 report 2026-10-29)
            why.append(f"NOT_JUDGED {c['criterion_id']}")
        elif incl and r["status"] in ("UNKNOWN", "CONFLICT"):
            if c.get("administrative") and r["status"] == "UNKNOWN" and r["reason"] == "MISSING":
                continue
            why.append(f"{r['status']}/{r['reason']} {c['criterion_id']}")
        elif not incl and (r["status"] == "CONFLICT" or (r["status"] == "UNKNOWN" and r["reason"] in ("EXPIRED", "UNSUPPORTED"))):
            why.append(f"{r['status']}/{r['reason']} {c['criterion_id']}")
    return ("potential", why) if why else ("eligible", [])


def counts(results):
    out = {"PASS": 0, "FAIL": 0, "UNKNOWN": 0, "CONFLICT": 0}
    for r in results:
        out[r["status"]] += 1
    return out
