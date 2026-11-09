"""Agent 3 output -> cards for the UNKNOWN criteria the records cannot settle.

Scope (4차 회의 'Agent 4 역할' 표 1번, 운주): UNKNOWN/EXPIRED (-> new_test) and UNKNOWN/UNSUPPORTED
(-> patient_question / clinician_confirmation). Also taken from the boundary with the record-lookup half (준상),
because they end in the same two card types: CONFLICT (-> clinician_confirmation, no owner in the table) and
UNKNOWN/MISSING rows Agent 3 sent to new_test or clinician_confirmation, when they block the trial (exclusion
MISSING and administrative MISSING do not change the trial label, so asking them changes nothing).
The rest of UNKNOWN/MISSING (record lookups, patient questions) stays with 준상.

Card type: Agent 3's action when it is one of the three. When Agent 3 asks for a record lookup instead
(med_record_check / med_history_check / lab_check), the row goes to the record-lookup half of Agent 5 (준상) in
`handoff` rather than being turned into a question here: dev gold keeps a lookup for about half of those rows.
With no usable action, the first route in ①-b `answerable_by` decides.

Merging: one new_test card per test (same concept, or the same cited evidence), one clinician card per trial,
one patient card per distinct question. Ranking: only trials that answers can still change (no FAIL) are kept by
default; a card ranks higher when it is the last blocker of a trial (answer it well -> eligible).
"""
import re
from collections import defaultdict

from .data import days_before, earliest_ok

OWNED = ("EXPIRED", "UNSUPPORTED")
CARD_TYPES = ("new_test", "clinician_confirmation", "patient_question")
MISSING_TAKEN = ("new_test", "clinician_confirmation")
LOOKUPS = ("med_record_check", "med_history_check", "lab_check")
ROUTE = {"patient": "patient_question", "clinician": "clinician_confirmation",
         "med_record": "clinician_confirmation", "lab": "new_test"}
IMAGING_DOCS = {"imaging_report"}
IMAGING_RX = re.compile(r"\b(MRI|CT|PET|scan|imaging|echo\w*|LVEF|ultrasound|x-ray|radiograph)\b", re.I)
BLOCKER_RX = re.compile(r"^(UNKNOWN|CONFLICT)/\w+ (\S+)$")


def card_type(res, crit):
    if res["status"] == "CONFLICT":                  # common format: CONFLICT -> clinician_confirmation
        return "clinician_confirmation"
    a = res.get("action")
    if a in CARD_TYPES:
        return a
    for who in crit.get("answerable_by") or []:
        if who in ROUTE:
            return ROUTE[who]
    return "new_test" if res["reason"] == "EXPIRED" else "clinician_confirmation"


def in_scope(res, blocking):
    """'owned' (표 1번 운주 rows), 'boundary' (taken from the lookup half), or None."""
    if res["status"] == "UNKNOWN" and res.get("reason") in OWNED:
        return "owned"
    if res["status"] == "CONFLICT":
        return "boundary"
    if res["status"] == "UNKNOWN" and res.get("reason") == "MISSING" and res.get("action") in MISSING_TAKEN \
            and res["criterion_id"] in blocking:
        return "boundary"
    return None


def blockers(row):
    """Criterion ids that keep a potential trial from being eligible (Agent 3 label_why)."""
    return {m.group(2) for w in row.get("label_why", []) for m in [BLOCKER_RX.match(w)] if m}


def _evidence(ids, ev):
    out = []
    for i in ids:
        e = ev.get(i)
        if e:
            s = e["source"]
            out.append({"evidence_id": i, "concept": e.get("concept"), "value": e.get("value"), "unit": e.get("unit"),
                        "date": e.get("observed_date"), "doc_id": s["doc_id"], "doc_type": s["doc_type"],
                        "text": s["text"]})
    return out


def _test_info(res, crit, evs, as_of):
    """What to test and by when, from Agent 3's calc (code judgments) or the criterion window and cited evidence."""
    calc = res.get("calc") or {}
    window = calc.get("window_days") or (crit.get("time_window") or {}).get("max_days_before")
    dated = [e for e in evs if e["date"]]
    last = max(dated, key=lambda e: e["date"]) if dated else None
    term = crit.get("term")
    term = ", ".join(term) if isinstance(term, list) else term          # ①-b term may list several words
    name = calc.get("concept") or term or crit.get("concept") or (last or {}).get("concept")
    text = " ".join([crit["original_text"], res.get("missing_fact") or ""] + [e["text"] for e in evs])
    kind = "imaging" if (last and last["doc_type"] in IMAGING_DOCS) or IMAGING_RX.search(text) else "lab"
    info = {"name": name, "kind": kind, "window_days": window,
            "last_date": calc.get("observed_date") or (last or {}).get("date"),
            "last_value": calc.get("value", (last or {}).get("value")),
            "unit": calc.get("value_unit") or (last or {}).get("unit")}
    info["last_days_before"] = days_before(as_of, info["last_date"])
    info["result_on_or_after"] = earliest_ok(as_of, window) if window else None
    return info


def _merge_key(ctype, item):
    if ctype == "new_test":
        t = item["test"]
        if t["name"]:
            return ("new_test", t["name"])
        return ("new_test", tuple(sorted(e["evidence_id"] for e in item["evidence"])) or item["criterion_id"])
    if ctype == "clinician_confirmation":
        return ("clinician_confirmation", item["trial_id"])
    q = (item["missing_fact"] or item["criterion_text"]).strip().lower()
    return ("patient_question", re.sub(r"\W+", " ", q))


def _title(card):
    it = card["items"]
    if card["type"] == "new_test":
        t = it[0]["test"]
        what = t["name"] or ("영상 검사" if t["kind"] == "imaging" else "검사")
        when = f"{t['result_on_or_after']} 이후 결과 필요" if t["result_on_or_after"] else "최신 결과 필요"
        last = f"마지막 {t['last_date']}({t['last_days_before']}일 전)" if t["last_date"] else "최근 결과 없음"
        return f"[검사 안내] {what}: {last}, {when}"
    if card["type"] == "clinician_confirmation":
        return f"[의사 확인] {it[0]['trial_id']} 기준 {len(it)}개 판단 요청"
    return f"[환자 질문] {it[0]['missing_fact'] or it[0]['criterion_text']}"


def build_cards(agent3_rows, criteria, evidence, as_of_by_patient, include_ineligible=False):
    """Returns (cards, handoff, stats). cards are sorted per patient by priority; handoff rows go to the
    record-lookup half of Agent 5."""
    crit = {c["criterion_id"]: c for c in criteria}
    ev = {e["evidence_id"]: e for e in evidence}
    stats = defaultdict(int)
    handoff = []
    groups = defaultdict(list)                       # (patient, merge key) -> items
    block = {}                                       # (patient, trial) -> blocker ids
    for row in agent3_rows:
        pid, tid = row["patient_id"], row["trial_id"]
        # an ineligible trial has no label_why blockers left to compute "blocking" from, so take them from scratch
        blocking = blockers(row) or {r["criterion_id"] for r in row["criteria"] if r["status"] in ("UNKNOWN", "CONFLICT")
                                     and (crit[r["criterion_id"]]["type"] != "exclusion" or r.get("reason") != "MISSING")
                                     and not (crit[r["criterion_id"]].get("administrative") and r.get("reason") == "MISSING")}
        scoped = [(r, s) for r in row["criteria"] for s in [in_scope(r, blocking)] if s]
        for r, s in scoped:
            stats[f"{s}_rows"] += 1
        if not scoped:
            continue
        if row["trial_label"] == "ineligible" and not include_ineligible:
            stats["skipped_ineligible_rows"] += len(scoped)
            continue
        block[(pid, tid)] = blockers(row)
        as_of = row.get("as_of") or as_of_by_patient.get(pid)
        for r, scope in scoped:
            c = crit[r["criterion_id"]]
            if r.get("action") in LOOKUPS and r["status"] != "CONFLICT":
                stats["handoff_lookup"] += 1
                handoff.append({"patient_id": pid, "trial_id": tid, "criterion_id": r["criterion_id"],
                                "reason": r["reason"], "action": r["action"], "missing_fact": r.get("missing_fact"),
                                "blocking": r["criterion_id"] in block[(pid, tid)]})
                continue
            ctype = card_type(r, c)
            evs = _evidence(r.get("evidence_ids") or [], ev)
            item = {"trial_id": tid, "trial_label": row["trial_label"], "criterion_id": r["criterion_id"],
                    "criterion_type": c["type"], "criterion_text": c["original_text"],
                    "status": r["status"], "reason": r["reason"], "scope": scope,
                    "agent3_action": r.get("action"), "missing_fact": r.get("missing_fact"),
                    "agent3_note": r.get("note"), "answerable_by": c.get("answerable_by"), "evidence": evs}
            if ctype == "new_test":
                item["test"] = _test_info(r, c, evs, as_of)
            stats[f"type:{ctype}"] += 1
            groups[(pid, _merge_key(ctype, item))].append(item)

    cards = []
    for (pid, key), items in groups.items():
        ctype = key[0]
        cids = {i["criterion_id"] for i in items}
        trials = sorted({i["trial_id"] for i in items})
        blocking = [t for t in trials if block.get((pid, t), set()) & cids]
        unlocks = [t for t in blocking if not (block[(pid, t)] - cids)]
        card = {"card_id": f"{pid}:{ctype}:{len([c for c in cards if c['patient_id'] == pid]) + 1:02d}",
                "patient_id": pid, "type": ctype,
                "audience": "patient" if ctype in ("patient_question", "new_test") else "clinician",
                "reasons": sorted({i["reason"] for i in items}), "items": items,
                "priority": {"blocking_trials": blocking, "last_blocker_of": unlocks,
                             "score": 10 * len(unlocks) + len(blocking)}}
        card["title"] = _title(card)
        cards.append(card)
    cards.sort(key=lambda c: (c["patient_id"], -c["priority"]["score"], c["type"], c["card_id"]))
    # stable ids after sorting: patient:type:rank
    rank = defaultdict(int)
    for c in cards:
        rank[c["patient_id"]] += 1
        c["card_id"] = f"{c['patient_id']}:{c['type']}:{rank[c['patient_id']]:02d}"
    stats["cards"] = len(cards)
    stats["patients"] = len({c["patient_id"] for c in cards})
    return cards, handoff, dict(stats)
