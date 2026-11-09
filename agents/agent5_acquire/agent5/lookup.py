"""Agent 3 output -> record-lookup cards, the MISSING half of Agent 5 (준상).

Scope (4차 회의 'Agent 4 역할' 표 1번 + the boundary in a5u-0.2.0, agreed with 운주):
  missing   UNKNOWN/MISSING whose action is a record lookup (med_record_check / med_history_check / lab_check) or
            patient_question.
  handoff   UNKNOWN/EXPIRED·UNSUPPORTED where Agent 3 asked for a record lookup. Same rule as `handoff` in cards.py,
            recomputed here so this half does not depend on 운주's output file.
  unowned   UNKNOWN/MISSING with new_test / clinician_confirmation that does NOT block the trial (mostly exclusion
            MISSING). The blocking ones are 운주's; these had no owner (웹 화면 데모 v1 요청 5, 11/05) and are taken
            here from a5j-0.3.0 as clinician cards, so the patient is not asked more questions.

Card type is the Agent 3 action, so it can be scored against gold expected_action. Routes:
  ask_patient     patient question
  ask_site        administrative criterion (prisoner, insurance, consent ...): the research site checks it, not the
                  patient (웹 화면 제안 요청 5-4, 11/06)
  ask_clinician   clinician confirmation or a new test on a non-blocking criterion
  agent2_reread   the patient has documents no evidence cites yet -> give them to Agent 2 first
  upload_request  nothing left to read -> ask for the record (the "기록 업로드 요청" card of the 4차 회의 demo)

Non-blocking items stay in (an exclusion MISSING on an eligible trial is a safety check: a "yes" turns it
ineligible), but rank below the blocking ones. card_id = <patient>:<type>:L-<first criterion id of the card>, so the
same card keeps its id between runs (요청 5-2) and never collides with 운주's numbered ids.
"""
import re
from collections import defaultdict

from .cards import LOOKUPS, MISSING_TAKEN, OWNED, _evidence, blockers

LOOKUP_TYPES = LOOKUPS + ("patient_question",)
ROUTE = {"patient": "patient_question", "med_record": "med_record_check", "lab": "lab_check"}
TITLE = {"med_record_check": "기록 찾기", "med_history_check": "과거력 확인", "lab_check": "검사 결과 찾기",
         "patient_question": "환자 질문", "clinician_confirmation": "의사 확인", "new_test": "검사 안내"}


def criterion_type(cid, crit):
    """①-b type, or from the id (NCT…-E03 is an exclusion) when criteria.jsonl is not at hand."""
    if crit.get("type"):
        return crit["type"]
    return "exclusion" if re.search(r"-E\d+$", cid) else "inclusion"


def lookup_scope(res):
    """'missing', 'handoff', or None. 'clinician_or_test' marks MISSING rows with new_test / clinician_confirmation
    (운주's when they block, this part's 'unowned' scope when they do not)."""
    if res["status"] != "UNKNOWN":
        return None
    if res.get("reason") == "MISSING":
        return "clinician_or_test" if res.get("action") in MISSING_TAKEN else "missing"
    if res.get("reason") in OWNED and res.get("action") in LOOKUPS:
        return "handoff"
    return None


def lookup_type(res, crit):
    a = res.get("action")
    if a in LOOKUP_TYPES or a in MISSING_TAKEN:
        return a
    for who in crit.get("answerable_by") or []:
        if who in ROUTE:
            return ROUTE[who]
    return "med_record_check"


def unread_docs(patient, evidence):
    """Documents of the patient that no evidence row comes from (Agent 2 has not extracted anything from them)."""
    cited = {e["source"]["doc_id"] for e in evidence if e.get("patient_id", patient["patient_id"]) == patient["patient_id"]}
    return [d["doc_id"] for d in patient.get("documents", []) if d["doc_id"] not in cited]


def _merge_key(ctype, item):
    if ctype == "answered_review":                            # one card per answer document
        return (ctype, item["answer_doc"], False)
    if ctype in ("lab_check", "new_test") and item["concept"]:
        return (ctype, item["concept"], item["administrative"])
    if ctype == "clinician_confirmation":                     # one card per trial, like a5u
        return (ctype, item["trial_id"], item["administrative"])
    q = (item["missing_fact"] or item["criterion_text"] or item["criterion_id"]).strip().lower()
    return (ctype, re.sub(r"\W+", " ", q), item["administrative"])


def _title(card):
    i = card["items"][0]
    if card["type"] == "answered_review":
        return f"[답 받음·의료진 확인 중] {i['criterion_text'] or i['criterion_id']}"
    if card["route"] == "ask_site":
        label = "행정 확인"
    else:
        label = TITLE[card["type"]]
    if card["type"] == "clinician_confirmation":
        return f"[{label}] {i['trial_id']} 기준 {len(card['items'])}개 판단 요청"
    what = i["missing_fact"] or i["criterion_text"] or i["criterion_id"]
    return f"[{label}] {what}"


def build_lookup_cards(agent3_rows, criteria, evidence, patients, include_ineligible=False, answered=None):
    """Returns (cards, stats). `patients` is patient_id -> record (for unread documents); criteria may be empty.
    `answered` is (patient_id, trial_id, criterion_id) -> answer doc_id: criteria the patient already answered get no
    new question; while they are still UNKNOWN they go to one clinician card "답을 받았고 의료진이 확인 중"."""
    answered = answered or {}
    crit = {c["criterion_id"]: c for c in criteria}
    ev = {e["evidence_id"]: e for e in evidence}
    unread = {pid: unread_docs(p, evidence) for pid, p in patients.items()}
    stats = defaultdict(int)
    groups = defaultdict(list)
    block = {}
    for row in agent3_rows:
        pid, tid = row["patient_id"], row["trial_id"]
        block[(pid, tid)] = blockers(row)
        # what blocks, the same way as cards.py (a5u): an ineligible trial has no label_why blockers left, so compute
        # them from scratch, or a row both halves see would be "blocking" for a5u and "unowned" here
        blocking_set = block[(pid, tid)] or {
            x["criterion_id"] for x in row["criteria"] if x["status"] in ("UNKNOWN", "CONFLICT")
            and (criterion_type(x["criterion_id"], crit.get(x["criterion_id"], {})) != "exclusion" or x.get("reason") != "MISSING")
            and not (crit.get(x["criterion_id"], {}).get("administrative") and x.get("reason") == "MISSING")}
        for r in row["criteria"]:
            scope = lookup_scope(r)
            if scope is None:
                continue
            if r.get("judged_by") == "pc:llm_missing":       # the LLM call failed: not a real MISSING, asking would mislead
                stats["not_judged"] += 1
                continue
            c = crit.get(r["criterion_id"], {})
            is_blocking = r["criterion_id"] in block[(pid, tid)]
            if scope == "clinician_or_test":
                if r["criterion_id"] in blocking_set:         # 운주's (a5u boundary)
                    stats["taken_by_a5u"] += 1
                    continue
                scope = "unowned"
            stats[f"{scope}_rows"] += 1
            if row["trial_label"] == "ineligible" and not include_ineligible:
                stats["skipped_ineligible_rows"] += 1
                continue
            ans_doc = answered.get((pid, tid, r["criterion_id"]))
            ctype = "answered_review" if ans_doc else lookup_type(r, c)
            evs = _evidence(r.get("evidence_ids") or [], ev)
            item = {"trial_id": tid, "trial_label": row["trial_label"], "criterion_id": r["criterion_id"],
                    "criterion_type": criterion_type(r["criterion_id"], c), "criterion_text": c.get("original_text"),
                    "concept": c.get("concept"), "administrative": bool(c.get("administrative")),
                    "status": r["status"], "reason": r["reason"], "scope": scope,
                    "blocking": is_blocking, "agent3_action": r.get("action"), "missing_fact": r.get("missing_fact"),
                    "agent3_note": r.get("note"), "answerable_by": c.get("answerable_by"), "evidence": evs}
            if ans_doc:
                item["answer_doc"] = ans_doc
                stats["answered_rows"] += 1
            stats[f"type:{ctype}"] += 1
            groups[(pid, _merge_key(ctype, item))].append(item)

    cards = []
    for (pid, key), items in groups.items():
        ctype = key[0]
        items.sort(key=lambda i: (i["trial_id"], i["criterion_id"]))
        cids = {i["criterion_id"] for i in items}
        trials = sorted({i["trial_id"] for i in items})
        blocking = [t for t in trials if block.get((pid, t), set()) & cids]
        unlocks = [t for t in blocking if not (block[(pid, t)] - cids)]
        safety = sorted({i["trial_id"] for i in items if not i["blocking"] and i["criterion_type"] == "exclusion"
                         and i["trial_label"] != "ineligible"})
        card = {"patient_id": pid, "type": ctype, "reasons": sorted({i["reason"] for i in items}), "items": items,
                "priority": {"blocking_trials": blocking, "last_blocker_of": unlocks, "safety_check_of": safety,
                             "score": 10 * len(unlocks) + len(blocking)}}
        if ctype == "answered_review":                    # the patient already answered: no new question
            card.update(audience="clinician", route="ask_clinician",
                        answer_docs=sorted({i["answer_doc"] for i in items}))
        elif all(i["administrative"] for i in items):
            card.update(audience="clinician", route="ask_site")
        elif ctype in MISSING_TAKEN:
            card.update(audience="clinician", route="ask_clinician")
        elif ctype == "patient_question":
            card.update(audience="patient", route="ask_patient")
        elif unread.get(pid):
            card.update(audience="system", route="agent2_reread", unread_docs=unread[pid])
        else:
            card.update(audience="patient", route="upload_request")
        card["title"] = _title(card)
        card["card_id"] = f"{pid}:{ctype}:L-{items[0]['criterion_id']}"
        cards.append(card)
    cards.sort(key=lambda c: (c["patient_id"], -c["priority"]["score"], c["route"] == "ask_site", c["type"], c["title"]))
    seen = defaultdict(int)                              # same first criterion in two cards of one type: keep ids unique
    for c in cards:
        seen[c["card_id"]] += 1
        if seen[c["card_id"]] > 1:
            c["card_id"] += f"-{seen[c['card_id']]}"
    stats["cards"] = len(cards)
    stats["patients"] = len({c["patient_id"] for c in cards})
    for c in cards:
        stats[f"route:{c['route']}"] += 1
    return cards, dict(stats)
