import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent5.answers import apply_answers  # noqa: E402
from agent5.cards import blockers, build_cards, card_type  # noqa: E402
from agent5.data import next_doc_id  # noqa: E402

CRIT = [
    {"criterion_id": "T1-I01", "type": "inclusion", "original_text": "LVEF < 50%", "concept": "lvef",
     "time_window": {"max_days_before": 90}, "answerable_by": ["lab"]},
    {"criterion_id": "T1-I02", "type": "inclusion", "original_text": "Clinically stable", "answerable_by": ["clinician"]},
    {"criterion_id": "T1-I03", "type": "inclusion", "original_text": "Willing to comply", "answerable_by": ["patient"]},
    {"criterion_id": "T1-I04", "type": "inclusion", "original_text": "HF diagnosis >= 180 days", "answerable_by": ["med_record"]},
    {"criterion_id": "T2-I01", "type": "inclusion", "original_text": "LVEF < 40%", "concept": "lvef", "answerable_by": ["lab"]},
    {"criterion_id": "T2-E01", "type": "exclusion", "original_text": "Pregnant", "answerable_by": ["patient"]},
    {"criterion_id": "T1-I05", "type": "inclusion", "original_text": "Adequate organ function", "answerable_by": ["clinician"]},
    {"criterion_id": "T1-I06", "type": "inclusion", "original_text": "No prior malignancy", "answerable_by": ["med_record"]},
    {"criterion_id": "T2-E02", "type": "exclusion", "original_text": "Significant comorbidity", "answerable_by": ["clinician"]},
]
EV = [{"evidence_id": "P-EV1", "concept": "lvef", "value": 28, "unit": "%", "observed_date": "2026-01-01",
       "source": {"doc_id": "P-D01", "doc_type": "imaging_report", "text": "LVEF 28%"}}]


def res(cid, status, reason, action, **kw):
    return dict(criterion_id=cid, status=status, reason=reason, action=action, evidence_ids=kw.pop("ev", []), **kw)


ROWS = [
    {"patient_id": "P", "trial_id": "T1", "as_of": "2026-10-01", "trial_label": "potential",
     "label_why": ["UNKNOWN/EXPIRED T1-I01", "UNKNOWN/UNSUPPORTED T1-I02", "UNKNOWN/UNSUPPORTED T1-I03",
                   "UNKNOWN/UNSUPPORTED T1-I04", "UNKNOWN/MISSING T1-I05", "CONFLICT/CONFLICT T1-I06"],
     "criteria": [res("T1-I01", "UNKNOWN", "EXPIRED", "new_test", ev=["P-EV1"],
                      calc={"concept": "lvef", "value": 28, "value_unit": "%", "observed_date": "2026-01-01",
                            "window_days": 90}),
                  res("T1-I02", "UNKNOWN", "UNSUPPORTED", "clinician_confirmation", missing_fact="stable?"),
                  res("T1-I03", "UNKNOWN", "UNSUPPORTED", "patient_question", missing_fact="willing?"),
                  res("T1-I04", "UNKNOWN", "UNSUPPORTED", "med_record_check", missing_fact="HF date"),
                  res("T1-I05", "UNKNOWN", "MISSING", "clinician_confirmation"),
                  res("T1-I06", "CONFLICT", "CONFLICT", "med_record_check")]},
    {"patient_id": "P", "trial_id": "T2", "as_of": "2026-10-01", "trial_label": "potential",
     "label_why": ["UNKNOWN/EXPIRED T2-I01"],
     "criteria": [res("T2-I01", "UNKNOWN", "EXPIRED", "new_test", ev=["P-EV1"]),
                  res("T2-E01", "UNKNOWN", "MISSING", "patient_question"),
                  res("T2-E02", "UNKNOWN", "MISSING", "clinician_confirmation")]},
    {"patient_id": "P", "trial_id": "T3", "as_of": "2026-10-01", "trial_label": "ineligible",
     "label_why": ["FAIL T3-I01"], "criteria": [res("T2-E01", "UNKNOWN", "UNSUPPORTED", "patient_question")]},
]


class TestCards(unittest.TestCase):
    def setUp(self):
        self.cards, self.handoff, self.stats = build_cards(ROWS, CRIT, EV, {"P": "2026-10-01"})
        self.by_type = {}
        for c in self.cards:
            self.by_type.setdefault(c["type"], []).append(c)

    def test_scope_and_routing(self):
        cids = {i["criterion_id"] for c in self.cards for i in c["items"]}
        self.assertNotIn("T2-E01", cids)                       # MISSING is the other half; T3 is ineligible
        self.assertEqual(self.stats["skipped_ineligible_rows"], 1)
        self.assertEqual([h["criterion_id"] for h in self.handoff], ["T1-I04"])   # lookup -> 준상
        self.assertEqual(sorted(self.by_type), ["clinician_confirmation", "new_test", "patient_question"])

    def test_boundary(self):
        scope = {i["criterion_id"]: i["scope"] for c in self.cards for i in c["items"]}
        self.assertEqual(scope["T1-I05"], "boundary")                  # blocking MISSING -> clinician
        self.assertEqual(scope["T1-I06"], "boundary")                  # CONFLICT, even with a lookup action
        self.assertNotIn("T2-E02", scope)                              # exclusion MISSING does not block
        [clin] = self.by_type["clinician_confirmation"]
        self.assertEqual({i["criterion_id"] for i in clin["items"]}, {"T1-I02", "T1-I05", "T1-I06"})

    def test_same_test_merged_with_window(self):
        [t] = self.by_type["new_test"]
        self.assertEqual({i["trial_id"] for i in t["items"]}, {"T1", "T2"})
        info = t["items"][0]["test"]
        self.assertEqual((info["kind"], info["last_days_before"], info["result_on_or_after"]),
                         ("imaging", 273, "2026-07-03"))
        self.assertEqual(t["priority"]["last_blocker_of"], ["T2"])      # T2's only blocker
        self.assertEqual(self.cards[0]["card_id"], t["card_id"])        # ranked first

    def test_answerable_by_fallback(self):
        self.assertEqual(card_type({"status": "UNKNOWN", "reason": "UNSUPPORTED", "action": None}, CRIT[2]), "patient_question")
        self.assertEqual(card_type({"status": "UNKNOWN", "reason": "EXPIRED", "action": None}, {}), "new_test")

    def test_blockers(self):
        self.assertEqual(blockers(ROWS[1]), {"T2-I01"})
        self.assertEqual(blockers(ROWS[2]), set())


class TestAnswers(unittest.TestCase):
    def test_documents(self):
        cards, _, _ = build_cards(ROWS, CRIT, EV, {"P": "2026-10-01"})
        ids = {c["type"]: c["card_id"] for c in cards}
        pats = {"P": {"patient_id": "P", "as_of": "2026-10-01",
                      "documents": [{"doc_id": "P-D01"}, {"doc_id": "P-D09"}]}}
        new, problems = apply_answers(pats, cards, [
            {"card_id": ids["new_test"], "date": "2026-09-22", "result": "Echo: LVEF 30%."},
            {"card_id": ids["new_test"], "date": "2026-10-05", "result": "too late"},
            {"card_id": ids["clinician_confirmation"], "criterion_id": "T1-I02", "decision": "met"},
            {"card_id": ids["patient_question"], "answer": "Yes."},
            {"card_id": "nope", "answer": "x"}])
        docs = pats["P"]["documents"][2:]
        self.assertEqual([d["doc_id"] for d in docs], ["P-D10", "P-D11", "P-D12"])
        self.assertEqual([d["type"] for d in docs], ["imaging_report", "clinic_note", "patient_interview"])
        self.assertEqual(len(new), 3)
        self.assertEqual(len(problems), 2)                     # after as_of, unknown card

    def test_next_doc_id(self):
        self.assertEqual(next_doc_id({"patient_id": "S", "documents": []}), "S-D01")
        self.assertEqual(next_doc_id({"patient_id": "S", "documents": [{"doc_id": "S-D007"}, {"doc_id": "x"}]}),
                         "S-D008")


if __name__ == "__main__":
    unittest.main()
