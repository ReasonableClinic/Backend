"""python3 -m unittest discover -s tests   (from the project root)"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from agent3.aggregate import trial_label                      # noqa: E402
from agent3.data import Dataset                               # noqa: E402
from agent3.llm import parse_json                             # noqa: E402
from agent3.postcheck import check                            # noqa: E402
from agent3.rules import age_in_range, is_pure_age, judge_by_rule, parse_age_bounds  # noqa: E402

D = os.path.join(ROOT, "data", "dev")
DS = Dataset(os.path.join(D, "input/patients.jsonl"), os.path.join(D, "reference/trials.jsonl"),
             os.path.join(D, "reference/criteria.jsonl"),
             os.path.join(ROOT, "agent3_kit/evidence_dev_haiku_v14_9.jsonl"))


def crit(text, ctype="inclusion", admin=False, cid="NCTX-I01"):
    return {"criterion_id": cid, "trial_id": "NCTX", "type": ctype, "original_text": text, "administrative": admin}


def ev_id(pid, concept, value=None):
    for e in DS.evidence[pid]:
        if e["concept"] == concept and (value is None or e["value"] == value):
            return e["evidence_id"]
    raise KeyError((pid, concept, value))


class TestAge(unittest.TestCase):
    def test_parse(self):
        for text, lo, hi in [("Age >= 18 years", 18, None), ("18-65 years of age;", 18, 65),
                             ("Aged 18 to 75 years inclusive, with no restriction on gender", 18, 75),
                             ("Between 40 to 80 years of age", 40, 80), ("Over 19 years old", 19, None),
                             ("Age below 18 years.", None, 18), ("18 years <= age <= 65 years;", 18, 65)]:
            b = parse_age_bounds(text)
            self.assertIsNotNone(b, text)
            self.assertEqual((b[0], b[2]), (lo, hi), text)
            self.assertTrue(is_pure_age(text, b[4]), text)

    def test_not_age(self):
        self.assertIsNone(parse_age_bounds("ANC >= 1.5 x 10^9/L within 14 days"))
        b = parse_age_bounds("Patients aged 18 years or older diagnosed with pulmonary mucormycosis (PM).")
        self.assertFalse(is_pure_age("Patients aged 18 years or older diagnosed with pulmonary mucormycosis (PM).", b[4]))

    def test_whole_years(self):
        self.assertTrue(age_in_range(75.6, 18, True, 75, True))
        self.assertFalse(age_in_range(17.9, 18, True, None, True))
        self.assertFalse(age_in_range(0.26, 0.5, True, None, True))

    def test_infant_exact_age(self):
        age, _ = DS.patient_age("SYN-0014")
        self.assertTrue(0.2 < age < 0.3)


class TestRules(unittest.TestCase):
    def test_age_exclusion_direction(self):
        r = judge_by_rule(crit("Age below 18 years.", "exclusion"), DS, "SYN-0005")
        self.assertEqual(r["status"], "PASS")          # 45-year-old is not excluded

    def test_pregnancy_male(self):
        r = judge_by_rule(crit("Pregnant or breastfeeding women.", "exclusion"), DS, "SYN-0012")
        self.assertEqual((r["status"], r["rule_tags"][0]), ("PASS", "impossible"))

    def test_cervical_is_not_a_sex_condition(self):
        text = "History of other malignancy except adequately treated basal cell carcinoma or cervical carcinoma in situ"
        self.assertIsNone(judge_by_rule(crit(text, "exclusion"), DS, "SYN-0002"))

    def test_female_inclusion_not_conditional_goes_to_llm(self):
        self.assertIsNone(judge_by_rule(crit("Postmenopausal women with HR+ breast cancer"), DS, "SYN-0012"))

    def test_consent(self):
        r = judge_by_rule(crit("Signed written informed consent.", admin=True), DS, "SYN-0012")
        self.assertEqual((r["status"], r["reason"]), ("UNKNOWN", "MISSING"))


class TestDemographics(unittest.TestCase):
    """a3-0.3.1: age / sex from registration first, never from a lab line (Agent 2 guide, v14.12)."""

    def ds(self, evs):
        d = Dataset.__new__(Dataset)
        d.patients = {"P": {"patient_id": "P", "as_of": "2026-10-01"}}
        d.evidence = {"P": evs}
        return d

    def ev(self, concept, value, doc, text, eid):
        return {"evidence_id": eid, "patient_id": "P", "concept": concept, "value": value, "subject": "patient",
                "observed_date": "2026-09-20", "source": {"doc_type": doc, "text": text}}

    def test_lab_line_age_sex_ignored(self):
        evs = [self.ev("age", 63, "registration", "Female, 63.", "REG"), self.ev("sex", "female", "registration", "Female, 63.", "REGS"),
               self.ev("age", 10, "lab_result", "RBC 3.41 (3.90-5.10 M/uL) L", "LAB"),
               self.ev("sex", "male", "clinic_note", "RBC 4.05 M/uL (3.80-5.20)", "NOTE")]
        d = self.ds(evs)
        self.assertEqual(d.patient_age("P"), (63.0, evs[0]))
        self.assertEqual(d.patient_sex("P"), ("female", evs[1]))

    def test_note_with_age_words_still_counts(self):
        e = self.ev("age", 67, "clinic_note", "67-year-old man, platelets 150 K/uL", "N")
        self.assertEqual(self.ds([e]).patient_age("P"), (67.0, e))


class TestPostcheck(unittest.TestCase):
    pid = "SYN-0012"

    def res(self, status, evs, **kw):
        return dict({"criterion_id": "NCTX-I01", "status": status, "reason": None, "evidence_ids": evs,
                     "action": None, "rule_tags": []}, **kw)

    # v3 (2026-10-25): Agent 3 no longer verifies its own judgments (Agent 4 does). The post-check only
    # normalises vocabulary and keeps resolvable evidence ids; a PASS with no evidence stays PASS here.
    def test_no_evidence_is_not_downgraded_by_agent3(self):
        r = check(self.res("PASS", []), crit("Type 2 diabetes"), DS, self.pid, {})
        self.assertEqual((r["status"], r["reason"], r["action"]), ("PASS", "VALID", "none"))

    def test_foreign_ids_moved_aside_status_kept(self):
        r = check(self.res("PASS", ["SYN-0001-EV001"]), crit("Type 2 diabetes"), DS, self.pid, {})
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(r["evidence_ids"], [])
        self.assertEqual(r["cited_ids_invalid"], ["SYN-0001-EV001"])
        self.assertIn("pc:dropped_unknown_ids", r["rule_tags"])

    def test_short_ids_get_patient_prefix(self):
        e = ev_id(self.pid, "sex")
        short = e[len(self.pid) + 1:]
        r = check(self.res("PASS", [short, "EV999999"]), crit("Type 2 diabetes"), DS, self.pid, {})
        self.assertEqual((r["evidence_ids"], r["cited_ids_invalid"]), ([e], [f"EV999999"]))
        self.assertIn("pc:id_prefix_restored", r["rule_tags"])

    def test_judgment_fail_not_downgraded_by_agent3(self):
        e = ev_id(self.pid, "sex")
        r = check(self.res("FAIL", [e]), crit("Clinically significant cardiac disease", "exclusion"), DS, self.pid, {})
        self.assertEqual((r["status"], r["reason"], r["action"]), ("FAIL", "VIOLATED", "none"))

    def test_strict_list_inference(self):
        e = ev_id(self.pid, "sex")
        r = check(self.res("PASS", [e], rule_tags=["list_inference"], derived_from="SYN-0012-D05"),
                  crit("Use of any lipid-lowering drug", "exclusion"), DS, self.pid, {})
        self.assertEqual(r["status"], "UNKNOWN")
        r = check(self.res("PASS", [e], rule_tags=["list_inference"], derived_from="SYN-0012-D05"),
                  crit("Use of any lipid-lowering drug", "exclusion"), DS, self.pid, {},
                  {"list_inference": "allow", "blanket_negation": "on"})
        self.assertEqual(r["status"], "PASS")

    def test_history_item_action_is_record_lookup(self):
        c = dict(crit("History of transient ischemic attack within 180 days", "exclusion"), concept="diagnosis")
        r = check(self.res("UNKNOWN", [], reason="MISSING", action="patient_question"), c, DS, self.pid, {})
        self.assertEqual(r["action"], "med_history_check")
        c = dict(crit("Willing to follow diet counseling"), concept=None)
        r = check(self.res("UNKNOWN", [], reason="MISSING", action="patient_question"), c, DS, self.pid, {})
        self.assertEqual(r["action"], "patient_question")

    def test_reason_action_consistency(self):
        e = ev_id(self.pid, "sex")
        r = check(self.res("PASS", [e], reason="MISSING", action="lab_check"), crit("x"), DS, self.pid, {})
        self.assertEqual((r["reason"], r["action"]), ("VALID", "none"))


class TestStructured(unittest.TestCase):
    """①-b numeric / categorical code judgment (agent3/structured.py)."""
    from agent3.structured import load_concepts
    CON = load_concepts()

    def scrit(self, concept, op, value, unit=None, ctype="inclusion", tw=None, text="x", **kw):
        return dict({"criterion_id": "NCTX-I01", "trial_id": "NCTX", "type": ctype, "original_text": text,
                     "administrative": False, "parse_status": "structured", "concept": concept, "operator": op,
                     "value": value, "unit": unit, "time_window": tw, "complex": False, "change": False,
                     "inline_relation": None, "logic_group": None}, **kw)

    def ds_with(self, pid, evs):
        """A tiny dataset stub: one patient, the given evidence."""
        class DS:
            pass
        d = DS()
        d.evidence = {pid: evs}
        d.as_of = lambda p: "2026-10-01"
        return d

    def ev(self, concept, value, date, unit=None, doc="lab_result", eid="E1", detail=None, certainty="confirmed"):
        return {"evidence_id": eid, "patient_id": "P", "concept": concept, "value": value, "unit": unit,
                "value_type": "numeric", "observed_date": date, "certainty": certainty, "subject": "patient",
                "source": {"doc_id": "D1", "doc_type": doc, "span": [0, 1], "text": f"{concept} {value}"},
                "detail": detail or {}}

    def judge(self, crit, evs, policy=None):
        from agent3.structured import judge_structured
        return judge_structured(crit, self.ds_with("P", evs), "P", self.CON, policy or {})

    def test_numeric_inclusion_and_exclusion_direction(self):
        r, _ = self.judge(self.scrit("anc", ">=", 1.5, "10^9/L"), [self.ev("anc", 1.8, "2026-09-28", "10^9/L")])
        self.assertEqual((r["status"], r["reason"], r["evidence_ids"]), ("PASS", "VALID", ["E1"]))
        r, _ = self.judge(self.scrit("egfr", "<", 30, "mL/min/1.73m2", ctype="exclusion"),
                          [self.ev("egfr", 25, "2026-09-28", "mL/min/1.73m2")])
        self.assertEqual(r["status"], "FAIL")           # excluding condition met -> cannot enroll

    def test_alt_units_scale_the_threshold(self):
        # criterion in mg/mmol, evidence in the base unit mg/mg (alt_units mg/mmol -> x0.00885)
        r, _ = self.judge(self.scrit("urine_protein_creatinine_ratio", "<=", 20, "mg/mmol"),
                          [self.ev("urine_protein_creatinine_ratio", 0.15, "2026-09-28", "mg/mg")])
        self.assertEqual(r["status"], "PASS")
        self.assertAlmostEqual(r["calc"]["threshold_in_base_unit"], 0.177, places=3)

    def test_uln_uses_ref_high_or_hints(self):
        r, h = self.judge(self.scrit("alt", "<", 1.25, "x ULN"), [self.ev("alt", 74, "2026-09-30", "U/L", detail={"ref_high": 55})])
        self.assertEqual(r["status"], "FAIL")           # 74/55 = 1.35 x ULN
        r, h = self.judge(self.scrit("alt", "<", 1.25, "x ULN"), [self.ev("alt", 74, "2026-09-30", "U/L")])
        self.assertIsNone(r)
        self.assertIn("no reference range", h["part"]["note"])

    def test_bound_value_undecided_goes_to_llm(self):
        r, h = self.judge(self.scrit("tsh", "<", 0.1, "mIU/L"), [self.ev("tsh", 0.5, "2026-09-28", "mIU/L", detail={"comparator": "<"})])
        self.assertIsNone(r)                            # "<0.5" does not settle "< 0.1"
        r, h = self.judge(self.scrit("tsh", "<", 1.0, "mIU/L"), [self.ev("tsh", 0.5, "2026-09-28", "mIU/L", detail={"comparator": "<"})])
        self.assertEqual(r["status"], "PASS")           # "<0.5" does settle "< 1.0"

    def test_measurement_date_is_first_appearance(self):
        # an echo in February restated by a September note: the value is 7 months old -> EXPIRED
        evs = [self.ev("lvef", 28, "2026-02-19", "%", doc="discharge_summary", eid="OLD"),
               self.ev("lvef", 28, "2026-09-24", "%", doc="clinic_note", eid="NOTE")]
        r, _ = self.judge(self.scrit("lvef", "<", 50, "%"), evs)
        self.assertEqual((r["status"], r["reason"], r["evidence_ids"]), ("UNKNOWN", "EXPIRED", ["OLD"]))
        # a newer distinct value wins over a restated old one
        evs = [self.ev("alt", 112, "2026-09-21", "U/L", eid="A"), self.ev("alt", 112, "2026-09-30", "U/L", doc="clinic_note", eid="A2"),
               self.ev("alt", 74, "2026-09-30", "U/L", eid="B")]
        r, _ = self.judge(self.scrit("alt", "<", 100, "U/L"), evs)
        self.assertEqual((r["status"], r["evidence_ids"]), ("PASS", ["B"]))

    def test_criterion_window_and_lab_default_window(self):
        r, _ = self.judge(self.scrit("anc", ">=", 1.5, "10^9/L", tw={"anchor": "as_of", "max_days_before": 7, "min_days_before": None}),
                          [self.ev("anc", 1.8, "2026-09-01", "10^9/L")])
        self.assertEqual((r["status"], r["reason"]), ("UNKNOWN", "EXPIRED"))
        # a3-0.3.1: 6.3 lab default 30 days applies when the criterion has no window
        r, _ = self.judge(self.scrit("egfr", "between", [20, 59], "mL/min/1.73m2"), [self.ev("egfr", 38, "2026-08-27", "mL/min/1.73m2")])
        self.assertEqual((r["status"], r["reason"], r["calc"]["window_source"]), ("UNKNOWN", "EXPIRED", "default_6.3"))
        # also when the lab value is only restated in a note (window by concept type, not only by document)
        r, _ = self.judge(self.scrit("egfr", "between", [20, 59], "mL/min/1.73m2"),
                          [self.ev("egfr", 38, "2026-08-27", "mL/min/1.73m2", doc="clinic_note")])
        self.assertEqual(r["reason"], "EXPIRED")

    def test_new_report_with_same_value_is_a_new_measurement(self):
        # SYN-0004 (5차 회의): eGFR 37 in April, 38 in August, 37 again in a September lab report
        evs = [self.ev("egfr", 37, "2026-04-08", "mL/min/1.73m2", eid="APR"),
               self.ev("egfr", 38, "2026-08-27", "mL/min/1.73m2", eid="AUG"),
               self.ev("egfr", 37, "2026-09-24", "mL/min/1.73m2", doc="clinic_note", eid="NOTE"),
               self.ev("egfr", 37, "2026-09-24", "mL/min/1.73m2", eid="SEP")]
        r, _ = self.judge(self.scrit("egfr", "between", [20, 59], "mL/min/1.73m2"), evs)
        self.assertEqual((r["status"], r["evidence_ids"], r["calc"]["observed_date"]), ("PASS", ["SEP"], "2026-09-24"))
        # SYN-0008: a later report line comparing with the earlier result is not a new measurement
        evs = [self.ev("alt", 112, "2026-09-21", "U/L", eid="A"), self.ev("alt", 74, "2026-09-30", "U/L", eid="B"),
               self.ev("alt", 112, "2026-09-30", "U/L", eid="CMP")]
        evs[2]["source"]["text"] = "Transaminases decreasing compared with 2026-09-21 (ALT 112, AST 87)."
        r, _ = self.judge(self.scrit("alt", "<", 100, "U/L"), evs)
        self.assertEqual((r["status"], r["evidence_ids"]), ("PASS", ["B"]))

    def test_newest_word_value_is_not_replaced_by_older_number(self):
        evs = [self.ev("hbv_dna", 25, "2026-03-02", "IU/mL", eid="NUM"),
               self.ev("hbv_dna", "not detected", "2026-09-20", "IU/mL", eid="WORD")]
        r, h = self.judge(self.scrit("hbv_dna", "<", 20, "IU/mL"), evs)
        self.assertIsNone(r)
        self.assertIn("not detected", h["part"]["note"])
        self.assertIn("WORD", h["part"]["note"])

    def test_complex_and_no_value_and_qualifier_only_hint(self):
        r, h = self.judge(self.scrit("bmi", ">=", 28, "kg/m2", complex=True, inline_relation="OR"), [self.ev("bmi", 29.6, "2026-09-24", "kg/m2")])
        self.assertIsNone(r)
        self.assertEqual((h["met"], h["status_if_alone"]), (True, "PASS"))
        r, h = self.judge(self.scrit("child_pugh", ">", 6), [])
        self.assertIsNone(r)
        self.assertIn("no child_pugh value", h["part"]["note"])
        r, h = self.judge(self.scrit("ldl_cholesterol", "<=", 130, "mg/dL", text="Fasting LDL-C <= 130 mg/dL"),
                          [self.ev("ldl_cholesterol", 124, "2026-10-01", "mg/dL")])
        self.assertIsNone(r)
        self.assertIn("fasting", h["part"]["note"].lower())

    def test_categorical_in(self):
        r, _ = self.judge(self.scrit("nyha_class", "in", ["III", "IV"], ctype="exclusion"), [self.ev("nyha_class", 3, "2026-09-24")])
        self.assertEqual(r["status"], "FAIL")
        r, _ = self.judge(self.scrit("child_pugh", "in", ["B", "C"], ctype="exclusion"), [self.ev("child_pugh", 6, "2026-09-24")])
        self.assertEqual(r["status"], "PASS")           # 6 points = class A

    def test_or_group_and_parent(self):
        from agent3.structured import apply_logic_groups
        lg = lambda role: {"group_id": "G", "relation": "OR", "role": role}
        crits = [{"criterion_id": "P", "logic_group": lg("parent")}, {"criterion_id": "A", "logic_group": lg("member")},
                 {"criterion_id": "B", "logic_group": lg("member")}]
        R = lambda c, s, r, ev: {"criterion_id": c, "status": s, "reason": r, "evidence_ids": ev, "action": "none", "rule_tags": [], "note": ""}
        res = {"P": R("P", "PASS", "VALID", ["E0"]), "A": R("A", "PASS", "VALID", ["E1"]), "B": R("B", "FAIL", "VIOLATED", ["E2"])}
        apply_logic_groups(res, crits)
        self.assertEqual((res["B"]["status"], res["B"]["evidence_ids"]), ("PASS", ["E1"]))     # gold NCT06110130-I04
        self.assertEqual(res["P"]["status"], "PASS")
        res = {"P": R("P", "PASS", "VALID", ["E0"]), "A": R("A", "FAIL", "VIOLATED", ["E1"]), "B": R("B", "UNKNOWN", "MISSING", [])}
        apply_logic_groups(res, crits)
        self.assertEqual((res["A"]["status"], res["B"]["status"], res["P"]["status"]), ("FAIL", "UNKNOWN", "UNKNOWN"))


class TestAggregate(unittest.TestCase):
    def test_rules_61(self):
        cb = {"I1": {"criterion_id": "I1", "type": "inclusion"}, "A1": {"criterion_id": "A1", "type": "inclusion", "administrative": True},
              "E1": {"criterion_id": "E1", "type": "exclusion"}}
        R = lambda c, s, r: {"criterion_id": c, "status": s, "reason": r}
        self.assertEqual(trial_label([R("I1", "PASS", "VALID"), R("E1", "UNKNOWN", "MISSING")], cb)[0], "eligible")
        self.assertEqual(trial_label([R("I1", "PASS", "VALID"), R("A1", "UNKNOWN", "MISSING")], cb)[0], "eligible")
        self.assertEqual(trial_label([R("I1", "UNKNOWN", "MISSING")], cb)[0], "potential")
        self.assertEqual(trial_label([R("E1", "UNKNOWN", "EXPIRED")], cb)[0], "potential")
        self.assertEqual(trial_label([R("I1", "PASS", "VALID"), R("E1", "FAIL", "VIOLATED")], cb)[0], "ineligible")
        self.assertEqual(trial_label([R("I1", "PASS", "VALID")], cb, ["age"])[0], "ineligible")

    def test_llm_missing_blocks_eligible(self):
        # a3-0.3.1 (Agent 5 report 2026-10-29): a criterion the model never answered is not "probably fine"
        cb = {"I1": {"criterion_id": "I1", "type": "inclusion"}, "E1": {"criterion_id": "E1", "type": "exclusion"}}
        ok = {"criterion_id": "I1", "status": "PASS", "reason": "VALID"}
        lost = {"criterion_id": "E1", "status": "UNKNOWN", "reason": "MISSING", "rule_tags": ["pc:llm_missing"]}
        label, why = trial_label([ok, lost], cb)
        self.assertEqual((label, why), ("potential", ["NOT_JUDGED E1"]))
        lost_fail = dict(ok, criterion_id="E1", status="FAIL", reason="VIOLATED")
        self.assertEqual(trial_label([lost_fail, lost], cb)[0], "ineligible")


class TestParse(unittest.TestCase):
    def test_fenced(self):
        self.assertEqual(parse_json('```json\n{"a": "x}"}\n```')["a"], "x}")


class TestCacheKey(unittest.TestCase):
    def test_prompt_content_is_part_of_the_key(self):
        """v1 bug: a new evidence file replayed answers given to the old one."""
        from agent3.llm import Judge
        with tempfile.TemporaryDirectory() as t:
            j = Judge("replay", "m", t)
            k1 = j.cache_key(["p04", "SYN-0001", "NCT1"], ["NCT1-I01"], "evidence A")
            k2 = j.cache_key(["p04", "SYN-0001", "NCT1"], ["NCT1-I01"], "evidence A")
            k3 = j.cache_key(["p04", "SYN-0001", "NCT1"], ["NCT1-I01"], "evidence B")
            self.assertEqual(k1, k2)
            self.assertNotEqual(k1, k3)


class TestEndToEnd(unittest.TestCase):
    def test_mock_then_rejudge(self):
        with tempfile.TemporaryDirectory() as t:
            run = [sys.executable, "-m", "agent3.run", "--split", "dev", "--patient", "SYN-0016", "--cache", t + "/c",
                   "--evidence", os.path.join(ROOT, "agent3_kit/evidence_dev_haiku_v14_9.jsonl")]
            subprocess.run(run + ["--llm", "mock", "--out", t + "/a"], cwd=ROOT, check=True, capture_output=True)
            prev = t + "/a/agent3_out.jsonl"
            rows = [json.loads(l) for l in open(prev)]
            self.assertEqual(len(rows), 3)
            flag = {"patient_id": "SYN-0016", "trial_id": rows[0]["trial_id"],
                    "criterion_id": rows[0]["criteria"][-1]["criterion_id"], "issue": "evidence_missing", "detail": "x"}
            with open(t + "/flags.jsonl", "w") as f:
                f.write(json.dumps(flag) + "\n")
            subprocess.run(run + ["--llm", "mock", "--out", t + "/a", "--prev", prev, "--rejudge", t + "/flags.jsonl"],
                           cwd=ROOT, check=True, capture_output=True)
            g = json.load(open(t + "/a/graph/SYN-0016.json"))
            rounds = [n["round"] for n in g["nodes"] if n.get("kind") == "decision" and n["criterion_id"] == flag["criterion_id"]]
            self.assertEqual(sorted(rounds), [1, 2])
            self.assertEqual(g["version"], 2)


if __name__ == "__main__":
    unittest.main()
