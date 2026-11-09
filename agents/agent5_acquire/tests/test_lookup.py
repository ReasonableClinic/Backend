import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent5.cards import build_cards  # noqa: E402
from agent5.lookup import build_lookup_cards, unread_docs  # noqa: E402
from agent5.lookup_answers import apply_lookup_answers  # noqa: E402
from tests.test_agent5 import CRIT, EV, ROWS, res  # noqa: E402

CRIT2 = CRIT + [{"criterion_id": "T1-I07", "type": "inclusion", "original_text": "HbA1c 7-10%", "concept": "hba1c",
                 "answerable_by": ["lab"]},
                {"criterion_id": "T2-I02", "type": "inclusion", "original_text": "HbA1c < 9%", "concept": "hba1c",
                 "answerable_by": ["lab"]}]
ROWS2 = copy.deepcopy(ROWS)
ROWS2[0]["criteria"].append(res("T1-I07", "UNKNOWN", "MISSING", "lab_check", missing_fact="HbA1c"))
ROWS2[0]["label_why"].append("UNKNOWN/MISSING T1-I07")
ROWS2[1]["criteria"].append(res("T2-I02", "UNKNOWN", "MISSING", "lab_check", missing_fact="HbA1c value"))
ROWS2[1]["label_why"].append("UNKNOWN/MISSING T2-I02")


def patients(*doc_ids):
    return {"P": {"patient_id": "P", "as_of": "2026-10-01",
                  "documents": [{"doc_id": d, "date": "2026-09-01"} for d in doc_ids]}}


class TestLookupCards(unittest.TestCase):
    def setUp(self):
        self.cards, self.stats = build_lookup_cards(ROWS2, CRIT2, EV, patients("P-D01"))
        self.by_type = {}
        for c in self.cards:
            self.by_type.setdefault(c["type"], []).append(c)

    def test_scope(self):
        cids = {i["criterion_id"] for c in self.cards for i in c["items"]}
        self.assertEqual(cids, {"T1-I04", "T2-E01", "T1-I07", "T2-I02", "T2-E02"})
        self.assertEqual(self.stats["taken_by_a5u"], 1)             # T1-I05 blocking MISSING clinician -> 운주
        self.assertEqual(self.stats["unowned_rows"], 1)             # T2-E02 non-blocking exclusion MISSING -> here
        [clin] = self.by_type["clinician_confirmation"]
        self.assertEqual((clin["audience"], clin["route"], clin["items"][0]["scope"]),
                         ("clinician", "ask_clinician", "unowned"))
        self.assertNotIn("skipped_ineligible_rows", self.stats)     # T3's row is UNSUPPORTED patient_question (운주)

    def test_handoff_matches_a5u(self):
        _, handoff, _ = build_cards(ROWS2, CRIT2, EV, {"P": "2026-10-01"})
        mine = {i["criterion_id"] for c in self.cards for i in c["items"] if i["scope"] == "handoff"}
        self.assertEqual(mine, {h["criterion_id"] for h in handoff})

    def test_no_overlap_with_a5u(self):
        a5u, _, _ = build_cards(ROWS2, CRIT2, EV, {"P": "2026-10-01"}, include_ineligible=True)
        theirs = {(i["trial_id"], i["criterion_id"]) for c in a5u for i in c["items"]}
        mine = {(i["trial_id"], i["criterion_id"]) for c in self.cards for i in c["items"]}
        self.assertFalse(theirs & mine)

    def test_lab_merged_and_ranked(self):
        [lab] = self.by_type["lab_check"]
        self.assertEqual({i["trial_id"] for i in lab["items"]}, {"T1", "T2"})
        self.assertEqual(lab["priority"]["blocking_trials"], ["T1", "T2"])
        self.assertEqual(self.cards[0]["card_id"], lab["card_id"])
        self.assertEqual(lab["card_id"], "P:lab_check:L-T1-I07")   # first criterion of the card, stable between runs

    def test_card_id_stable_and_admin_to_site(self):
        rows = copy.deepcopy(ROWS2)
        rows[1]["criteria"] = [c for c in rows[1]["criteria"] if c["criterion_id"] != "T2-I02"]   # another run
        rows[1]["label_why"] = [w for w in rows[1]["label_why"] if not w.endswith("T2-I02")]
        crit = [dict(c, administrative=True) if c["criterion_id"] == "T2-E01" else c for c in CRIT2]
        cards, _ = build_lookup_cards(rows, crit, EV, patients("P-D01"))
        ids = {c["card_id"] for c in cards}
        self.assertIn("P:med_record_check:L-T1-I04", {c["card_id"] for c in self.cards} & ids)
        [site] = [c for c in cards if c["route"] == "ask_site"]
        self.assertEqual((site["audience"], site["title"][:7]), ("clinician", "[행정 확인]"))

    def test_safety_and_routes(self):
        [q] = self.by_type["patient_question"]
        self.assertEqual(q["priority"]["safety_check_of"], ["T2"])  # exclusion MISSING on a potential trial
        self.assertEqual(q["priority"]["score"], 0)
        self.assertEqual(q["route"], "ask_patient")
        self.assertEqual(self.by_type["med_record_check"][0]["route"], "upload_request")
        cards, _ = build_lookup_cards(ROWS2, CRIT2, EV, patients("P-D01", "P-D02"))
        rec = next(c for c in cards if c["type"] == "med_record_check")
        self.assertEqual((rec["route"], rec["unread_docs"]), ("agent2_reread", ["P-D02"]))

    def test_answered_no_new_question(self):
        # the patient answered T1-I04 in P-D09; Agent 3 still says UNKNOWN -> clinician reviews, no patient card
        cards, stats = build_lookup_cards(ROWS2, CRIT2, EV, patients("P-D01"), answered={("P", "T1", "T1-I04"): "P-D09"})
        [rev] = [c for c in cards if c["type"] == "answered_review"]
        self.assertEqual((rev["audience"], rev["route"], rev["answer_docs"]), ("clinician", "ask_clinician", ["P-D09"]))
        self.assertEqual([i["criterion_id"] for i in rev["items"]], ["T1-I04"])
        self.assertTrue(rev["title"].startswith("[답 받음·의료진 확인 중]"))
        self.assertNotIn("T1-I04", {i["criterion_id"] for c in cards if c is not rev for i in c["items"]})
        self.assertEqual(stats["answered_rows"], 1)
        self.assertEqual(len(cards), len(self.cards))

    def test_without_criteria(self):
        cards, _ = build_lookup_cards(ROWS2, [], EV, patients("P-D01"))
        q = next(c for c in cards if c["type"] == "patient_question")
        self.assertEqual(q["items"][0]["criterion_type"], "exclusion")
        self.assertEqual(unread_docs(patients("P-D01")["P"], EV), [])


class TestFromGraph(unittest.TestCase):
    def test_latest_verdict_and_trial_label(self):
        import json
        import tempfile
        from agent5.from_graph import load_graphs
        g = {"patient_id": "P", "as_of": "2026-10-01", "history": [], "nodes": [
            {"id": "crit:T1-I01", "type": "criterion", "criterion_id": "T1-I01", "trial_id": "T1", "crit_type": "inclusion",
             "original_text": "HbA1c 7-10%", "concept": "hba1c", "answerable_by": ["lab"]},
            {"id": "crit:T1-E01", "type": "criterion", "criterion_id": "T1-E01", "trial_id": "T1", "crit_type": "exclusion",
             "original_text": "Pregnant", "answerable_by": ["patient"]},
            {"id": "verdict:T1-I01#1", "type": "verdict", "criterion_id": "T1-I01", "trial_id": "T1", "status": "PASS",
             "reason": "VALID", "expected_action": "none", "by": "agent3"},
            {"id": "verdict:T1-I01#2", "type": "verdict", "criterion_id": "T1-I01", "trial_id": "T1", "status": "UNKNOWN",
             "reason": "UNSUPPORTED", "expected_action": "clinician_confirmation", "by": "agent4", "original_status": "PASS"},
            {"id": "verdict:T1-E01#1", "type": "verdict", "criterion_id": "T1-E01", "trial_id": "T1", "status": "UNKNOWN",
             "reason": "MISSING", "expected_action": "patient_question", "by": "agent3"},
            {"id": "ev:P-EV1", "type": "evidence", "concept": "hba1c", "value": 8, "text": "HbA1c 8%"},
            {"id": "doc:P-D01", "type": "document", "doc_type": "lab_result"}],
            "edges": [{"src": "verdict:T1-I01#2", "rel": "supported_by", "dst": "ev:P-EV1"},
                      {"src": "ev:P-EV1", "rel": "from", "dst": "doc:P-D01"}]}
        rep = {"patients": {"P": {"trial_verdicts": {"T1": {"label": "potential", "why": None, "pending": ["T1-I01"]}}}}}
        with tempfile.TemporaryDirectory() as d:
            for name, obj in (("graph_P.json", g), ("verify_report.json", rep)):
                with open(f"{d}/{name}", "w", encoding="utf-8") as f:
                    json.dump(obj, f)
            rows, crit, ev, as_of = load_graphs(d)
        [row] = rows
        st = {c["criterion_id"]: c for c in row["criteria"]}
        self.assertEqual((st["T1-I01"]["status"], st["T1-I01"]["verified_by"]), ("UNKNOWN", "agent4"))
        self.assertEqual(st["T1-I01"]["evidence_ids"], ["P-EV1"])
        self.assertEqual(row["label_why"], ["UNKNOWN/UNSUPPORTED T1-I01"])
        self.assertEqual(ev[0]["source"]["doc_id"], "P-D01")
        cards, _ = build_lookup_cards(rows, crit, ev, {"P": {"patient_id": "P", "documents": [{"doc_id": "P-D01"}]}})
        self.assertEqual([c["type"] for c in cards], ["patient_question"])      # E01 MISSING; I01 went to a5u (clinician)


class TestLookupAnswers(unittest.TestCase):
    def test_documents(self):
        cards, _ = build_lookup_cards(ROWS2, CRIT2, EV, patients("P-D01"))
        ids = {c["type"]: c["card_id"] for c in cards}
        pats = patients("P-D01", "P-D09")
        new, not_found, problems = apply_lookup_answers(pats, cards, [
            {"card_id": ids["lab_check"], "date": "2026-09-20", "text": "HbA1c 8.1%"},
            {"card_id": ids["med_record_check"], "date": "2026-08-01", "text": "HF since 2019.", "doc_type": "discharge_summary"},
            {"card_id": ids["patient_question"], "answer": "No."},
            {"card_id": ids["lab_check"], "date": "2026-10-05", "text": "too late"},
            {"card_id": ids["med_record_check"], "not_found": True},
            {"card_id": ids["lab_check"], "text": "x", "doc_type": "fax"}])
        docs = pats["P"]["documents"][2:]
        self.assertEqual([d["doc_id"] for d in docs], ["P-D10", "P-D11", "P-D12"])
        self.assertEqual([d["type"] for d in docs], ["lab_result", "discharge_summary", "patient_interview"])
        self.assertEqual(len(new), 3)
        self.assertEqual(len(not_found), 1)
        self.assertEqual(len([p for p in problems if p.startswith("warn")]), 1)   # 08-01 before latest 09-20
        self.assertEqual(len([p for p in problems if not p.startswith("warn")]), 2)


if __name__ == "__main__":
    unittest.main()
