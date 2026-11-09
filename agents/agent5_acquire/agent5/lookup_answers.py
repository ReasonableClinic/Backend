"""Answers to record-lookup cards -> new documents (common format ②), for Agent 2 `update.py`.

answers_lookup.jsonl, one line per answer:
  lookup card        {"card_id", "date": "2026-09-15", "text": "...", "doc_type": "clinic_note"}   doc_type optional
                     {"card_id", "not_found": true, "comment": "..."}   record does not exist -> no document
  patient_question   {"card_id", "answer": "No, I have never had ..."}  same document as agent5/answers.py
  new_test           {"card_id", "date", "result": "..."}                same as agent5/answers.py (lab_result)
  clinician_confirmation {"card_id", "criterion_id", "decision": "met" | "not_met" | "cannot_determine", "comment"}

Same date rule as answers.py: nothing after as_of. A document dated before the patient's latest one gets the next
number anyway, so it is reported as a warning (number order and date order then disagree, see 5차 회의 feedback).
"""
from .answers import DECISION
from .data import days_before, next_doc_id

DEFAULT_DOC = {"lab_check": ("lab_result", "lab"), "med_record_check": ("clinic_note", "physician"),
               "med_history_check": ("clinic_note", "physician")}
ROLE = {"lab_result": "lab", "imaging_report": "physician", "clinic_note": "physician",
        "discharge_summary": "physician", "medication_record": "pharmacy", "pathology_report": "physician",
        "patient_interview": "patient"}


def apply_lookup_answers(patients, cards, answers):
    """Appends documents to `patients` (changed in place). Returns (new_docs, not_found, problems)."""
    by_id = {c["card_id"]: c for c in cards}
    new, not_found, problems = [], [], []
    for a in answers:
        card = by_id.get(a.get("card_id"))
        if card is None:
            problems.append(f"unknown card {a.get('card_id')}")
            continue
        p = patients[card["patient_id"]]
        as_of = p["as_of"]
        day = a.get("date") or as_of
        if (days_before(as_of, day) or 0) < 0:
            problems.append(f"{card['card_id']}: date {day} is after as_of {as_of}")
            continue
        if card["type"] == "patient_question":
            q = card["items"][0]["missing_fact"] or card["items"][0]["criterion_text"] or card["items"][0]["criterion_id"]
            dtype, role, text = "patient_interview", "patient", f"Question: {q} Patient answer: {a['answer'].strip()}"
        elif card["type"] == "clinician_confirmation":
            item = next((i for i in card["items"] if i["criterion_id"] == a.get("criterion_id")), None)
            if item is None or a.get("decision") not in DECISION:
                problems.append(f"{card['card_id']}: needs criterion_id of the card and decision {sorted(DECISION)}")
                continue
            dtype, role = "clinic_note", "physician"
            text = (f"Investigator review for trial {item['trial_id']}, criterion \"{item['criterion_text']}\": "
                    f"the patient {DECISION[a['decision']]}." + (" " + a["comment"].strip() if a.get("comment") else ""))
        elif card["type"] == "new_test":
            dtype, role, text = "lab_result", "lab", a["result"].strip()
        elif a.get("not_found"):
            not_found.append({"card_id": card["card_id"], "patient_id": p["patient_id"], "comment": a.get("comment")})
            continue
        else:
            dtype, role = DEFAULT_DOC[card["type"]]
            if a.get("doc_type"):
                if a["doc_type"] not in ROLE:
                    problems.append(f"{card['card_id']}: doc_type must be one of {sorted(ROLE)}")
                    continue
                dtype, role = a["doc_type"], ROLE[a["doc_type"]]
            text = a["text"].strip()
        latest = max((d.get("date") or "" for d in p["documents"]), default="")
        if day < latest:
            problems.append(f"warn {card['card_id']}: {day} is before the latest document ({latest})")
        d = {"doc_id": next_doc_id(p), "type": dtype, "date": day, "author_role": role, "text": text}
        p["documents"].append(d)
        new.append({"patient_id": p["patient_id"], "card_id": card["card_id"], "doc_id": d["doc_id"]})
    return new, not_found, problems
