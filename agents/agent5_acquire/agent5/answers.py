"""Answers to cards -> new documents in the patient record (common format ②), for Agent 2 `update.py`.

answers.jsonl, one line per answer:
  new_test               {"card_id", "date": "2026-09-28", "result": "Brain MRI: no CNS lesions."}
  clinician_confirmation {"card_id", "criterion_id", "decision": "met" | "not_met" | "cannot_determine", "comment"}
  patient_question       {"card_id", "answer": "No, I have never had ..."}

Documents are dated on or before as_of (the enrollment date all judgments use). A test result dated after as_of
would count as a future record, so it is refused rather than silently moved.
"""
from .data import days_before, next_doc_id

DECISION = {"met": "meets this criterion", "not_met": "does not meet this criterion",
            "cannot_determine": "cannot be determined at this time"}


def _doc(patient, dtype, role, day, text):
    d = {"doc_id": next_doc_id(patient), "type": dtype, "date": day, "author_role": role, "text": text}
    patient["documents"].append(d)
    return d


def apply_answers(patients, cards, answers):
    """Appends documents to `patients` (dict patient_id -> record, changed in place).
    Returns (new_docs, problems)."""
    by_id = {c["card_id"]: c for c in cards}
    new, problems = [], []
    for a in answers:
        card = by_id.get(a.get("card_id"))
        if card is None:
            problems.append(f"unknown card {a.get('card_id')}")
            continue
        p = patients[card["patient_id"]]
        as_of = p["as_of"]
        if card["type"] == "new_test":
            day = a.get("date") or as_of
            if (days_before(as_of, day) or 0) < 0:
                problems.append(f"{card['card_id']}: result date {day} is after as_of {as_of}")
                continue
            kind = card["items"][0]["test"]["kind"]
            d = _doc(p, "imaging_report" if kind == "imaging" else "lab_result",
                     "physician" if kind == "imaging" else "lab", day, a["result"].strip())
        elif card["type"] == "clinician_confirmation":
            item = next((i for i in card["items"] if i["criterion_id"] == a.get("criterion_id")), None)
            if item is None or a.get("decision") not in DECISION:
                problems.append(f"{card['card_id']}: needs criterion_id of the card and decision {sorted(DECISION)}")
                continue
            text = (f"Investigator review for trial {item['trial_id']}, criterion \"{item['criterion_text']}\": "
                    f"the patient {DECISION[a['decision']]}.")
            if a.get("comment"):
                text += " " + a["comment"].strip()
            d = _doc(p, "clinic_note", "physician", a.get("date") or as_of, text)
        else:
            q = card["items"][0]["missing_fact"] or card["items"][0]["criterion_text"]
            d = _doc(p, "patient_interview", "patient", a.get("date") or as_of,
                     f"Question: {q} Patient answer: {a['answer'].strip()}")
        new.append({"patient_id": p["patient_id"], "card_id": card["card_id"], "doc_id": d["doc_id"]})
    return new, problems
