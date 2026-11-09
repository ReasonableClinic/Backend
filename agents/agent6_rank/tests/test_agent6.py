import json, os, sys, unittest

os.environ.pop("AGENT6_GLOSSARY", None)   # tests always use the shipped glossary

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent6.rank import kr_info, months_since, rank_patient  # noqa: E402
from agent6.check_grounding import check  # noqa: E402
from agent6.graph import Graph  # noqa: E402

AS_OF = "2026-10-01"


def row(tid, label, statuses):
    return {"patient_id": "P", "trial_id": tid, "as_of": AS_OF, "trial_label": label,
            "criteria": [{"criterion_id": f"{tid}-I{i:02d}", "status": s} for i, s in enumerate(statuses, 1)]}


def trial(tid, verified="2026-08", kr=False, status="RECRUITING"):
    return {"trial_id": tid, "status_verified": verified, "overall_status": status,
            "countries": ["South Korea"] if kr else ["France"],
            "sites": [{"country": "South Korea" if kr else "France", "status": "RECRUITING"}]}


class Rank(unittest.TestCase):
    def test_months(self):
        self.assertEqual(months_since("2025-10", AS_OF), 12)
        self.assertEqual(months_since("2024-09", AS_OF), 25)

    def test_kr(self):
        self.assertEqual(kr_info(trial("A", kr=True)), (True, 1))

    def test_order(self):
        rows = [row("POT_KR", "potential", ["UNKNOWN"]), row("ELI", "eligible", ["PASS"]),
                row("ELI_STALE", "eligible", ["PASS"]), row("ELI_KR_2U", "eligible", ["UNKNOWN", "UNKNOWN"]),
                row("ELI_1U", "eligible", ["UNKNOWN"]), row("ELI_1U_KR", "eligible", ["UNKNOWN"]),
                row("OLD", "eligible", ["PASS"]), row("NO", "ineligible", ["FAIL"])]
        T = {"POT_KR": trial("POT_KR", kr=True), "ELI": trial("ELI"), "ELI_STALE": trial("ELI_STALE", "2025-06"),
             "ELI_KR_2U": trial("ELI_KR_2U", kr=True), "ELI_1U": trial("ELI_1U"), "ELI_1U_KR": trial("ELI_1U_KR", kr=True),
             "OLD": trial("OLD", "2024-01"), "NO": trial("NO")}
        r = rank_patient(rows, T, AS_OF)
        # eligible before potential; KR never jumps a tier; stale to the back of its tier; >24 months dropped
        self.assertEqual(r["ranking"], ["ELI", "ELI_1U_KR", "ELI_1U", "ELI_KR_2U", "ELI_STALE", "POT_KR"])
        self.assertEqual(r["stale_trials"], ["ELI_STALE"])
        self.assertEqual(r["dropped_stale_trials"], ["OLD"])


class Grounding(unittest.TestCase):
    G = Graph({"patient_id": "P", "as_of": AS_OF, "version": 1,
               "nodes": [{"id": "trial:A", "kind": "trial"}, {"id": "label:A", "kind": "trial_decision", "label": "eligible"}],
               "edges": [["trial:A", "labelled", "label:A"]]})

    def doc(self, sents, audience="patient"):
        return {"audience": audience, "ranking": ["A"], "sentences": sents}

    def test_unlinked_and_bad(self):
        r = check(self.doc([{"text": "x", "refs": []}, {"text": "y", "refs": ["ev:nope"]}], "clinician"), self.G)
        self.assertEqual(r["unlinked"], [0])
        self.assertEqual(r["bad_refs"], [(1, "ev:nope")])

    def test_patient_rules(self):
        r = check(self.doc([{"text": "이 시험을 꼭 참여하세요 NCT99999999", "refs": ["label:A"]}]), self.G)
        self.assertTrue(r["banned"])
        self.assertIn("rule:research_not_treatment", r["missing_rules"])
        self.assertEqual(r["trials_not_ranked"], ["NCT99999999"])


class Review(unittest.TestCase):
    def test_flags(self):
        from agent6.review import criterion_flags
        self.assertEqual(criterion_flags({"criterion_id": "N-I03", "status": "UNKNOWN", "note": "Hallucinations denied."}),
                         ["note_negates"])
        self.assertEqual(criterion_flags({"criterion_id": "N-I03", "status": "UNKNOWN", "note": "Not documented."}), [])
        self.assertEqual(criterion_flags({"criterion_id": "N-E03", "status": "UNKNOWN", "note": "denied"}), [])
        self.assertIn("llm_missing", criterion_flags({"criterion_id": "N-E01", "status": "UNKNOWN",
                                                      "judged_by": "pc:llm_missing"}))


GC = Graph({"patient_id": "P", "as_of": AS_OF, "version": 1, "nodes": [
    {"id": "trial:A", "kind": "trial", "title": "T"},
    {"id": "label:A", "kind": "trial_decision", "label": "potential"},
    {"id": "crit:A-I01", "kind": "criterion", "type": "inclusion", "text": "eGFR >= 30"},
    {"id": "dec:A:A-I01:r1", "kind": "decision", "trial_id": "A", "criterion_id": "A-I01", "status": "UNKNOWN",
     "reason": "EXPIRED", "action": "lab_check", "round": 1},
    {"id": "crit:A-E01", "kind": "criterion", "type": "exclusion", "text": "pregnancy"},
    {"id": "dec:A:A-E01:r1", "kind": "decision", "trial_id": "A", "criterion_id": "A-E01", "status": "PASS",
     "reason": "VALID", "action": "none", "round": 1},
    {"id": "calc:A:A-I01", "kind": "calculation", "concept": "egfr", "value": 37, "observed_date": "2026-04-02",
     "days_before": 182}],
    "edges": [["trial:A", "has_criterion", "crit:A-I01"], ["crit:A-I01", "decided_as", "dec:A:A-I01:r1"],
              ["trial:A", "has_criterion", "crit:A-E01"], ["crit:A-E01", "decided_as", "dec:A:A-E01:r1"],
              ["trial:A", "labelled", "label:A"], ["calc:A:A-I01", "computes", "dec:A:A-I01:r1"]]})


class Content(unittest.TestCase):
    def chk(self, text, refs):
        from agent6.check_content import check_sentence
        return [p[0] for p in check_sentence({"text": text, "refs": refs, "kind": "fact"}, GC, {}, AS_OF)]

    def test_numbers_dates(self):
        refs = ["dec:A:A-I01:r1", "calc:A:A-I01"]
        self.assertEqual(self.chk("eGFR 37은 2026년 4월 2일 값으로 182일 전입니다.", refs), [])
        self.assertEqual(self.chk("eGFR 38은 2026-04-02 값입니다.", refs), ["number"])
        self.assertEqual(self.chk("eGFR 37은 4월 3일 값입니다.", refs), ["date"])

    def test_typed_quote_rank(self):
        from agent6.check_content import check_sentence
        T = {"A": {"title": "T", "sites": [{"country": "South Korea", "status": "RECRUITING"}],
                   "countries": ["South Korea"], "status_verified": "2026-07", "briefing_extra": {"enrollment": 120}}}
        ck = lambda text, refs, rk=None: [p[0] for p in check_sentence({"text": text, "refs": refs, "kind": "fact"},
                                                                         GC, T, AS_OF, rk)]
        self.assertEqual(ck("국내 1곳, 약 120명, 3개월", ["trial:A"]), [])
        self.assertEqual(ck("국내 2곳에서 모집 중입니다.", ["trial:A"]), ["number"])
        self.assertEqual(ck("약 121명이 참여할 예정입니다.", ["trial:A"]), ["number"])
        self.assertEqual(ck("1번 시험 — 확인이 필요합니다.", ["trial:A"], ["A"]), [])
        self.assertEqual(ck("2번 시험 — 확인이 필요합니다.", ["trial:A"], ["A"]), ["number"])

    def test_verdict(self):
        self.assertEqual(self.chk("임신 기준을 충족합니다.", ["dec:A:A-E01:r1"]), ["verdict"])
        self.assertEqual(self.chk("신장 기능 조건은 확인되었습니다.", ["dec:A:A-I01:r1"]), ["verdict"])
        self.assertEqual(self.chk("조건이 맞을 가능성이 높습니다.", ["label:A"]), ["verdict"])


class ExternalFixes(unittest.TestCase):
    """Bugs the TREC 2021 run found (dev had no such cases)."""

    def test_trec_ids_are_not_dates(self):
        from agent6.check_content import check_sentence
        g = Graph({"patient_id": "TREC-2021-8", "as_of": "2021-04-27", "version": 1, "edges": [], "nodes": [
            {"id": "ev:TREC-2021-8-EV001", "kind": "evidence", "observed_date": "2021-04-27"},
            {"id": "src:TREC-2021-8-D01:0-71", "kind": "source", "text": "57-year-old gentleman with CLL."}]})
        s = {"text": '근거: "57-year-old gentleman with CLL." (TREC-2021-8-D01, 2021-04-27)',
             "refs": ["ev:TREC-2021-8-EV001", "src:TREC-2021-8-D01:0-71"], "kind": "fact"}
        self.assertEqual(check_sentence(s, g, {}, "2021-04-27"), [])   # "2021-8" inside the doc id is not a date

    def test_dropped_stale_is_a_rule(self):
        from agent6.check_content import check_sentence
        s = {"text": "NCT00000001: 모집 상태가 24개월 넘게 확인되지 않아 추천에서 제외했습니다 (공통 형식 6.4).",
             "refs": ["trial:A", "rule:dropped_stale"], "kind": "fact"}
        self.assertEqual(check_sentence(s, GC, {"A": {}}, AS_OF), [])

    def test_malignancy_terms_and_full_evidence(self):
        from agent6 import keyinfo as KI
        self.assertTrue(KI.MALIGNANT.search("Richter's transformation") and KI.MALIGNANT.search("CLL"))
        self.assertFalse(KI.MALIGNANT.search("all patients"))
        g = Graph({"patient_id": "PX", "as_of": AS_OF, "version": 1, "nodes": [], "edges": []})
        self.assertFalse(KI.has_confirmed_malignancy(g))
        KI.EVIDENCE["PX"] = [{"concept": "diagnosis", "term": "pancreatic adenocarcinoma head", "value": True,
                              "certainty": "confirmed", "subject": "patient"}]
        try:
            self.assertTrue(KI.has_confirmed_malignancy(g))
        finally:
            KI.EVIDENCE.pop("PX")


class Quote(unittest.TestCase):
    def test_verbatim(self):
        from agent6.check_content import check_sentence
        g = Graph({"patient_id": "P", "as_of": AS_OF, "version": 1, "edges": [], "nodes": [
            {"id": "src:P-D01:0-10", "kind": "source", "text": "ECOG 1 on 2026-09-10."}]})
        ok = {"text": '근거: "ECOG 1 on 2026-09-10." (P-D01, 2026-09-10)', "refs": ["src:P-D01:0-10"], "kind": "fact"}
        bad = dict(ok, text='근거: "ECOG 2 on 2026-09-10." (P-D01, 2026-09-10)')
        self.assertEqual(check_sentence(ok, g, {}, AS_OF), [])
        self.assertIn("quote", [p[0] for p in check_sentence(bad, g, {}, AS_OF)])


class LLMPath(unittest.TestCase):
    """A bad LLM draft must be retried, then fall back to template sentences; output still passes both checks."""

    def run_with(self, replies):
        from agent6 import brief_llm
        from agent6.check_content import check as cc
        calls = []

        class Fake:
            model, dry = "fake", False

            def __call__(self, system, user, pack):
                calls.append(user)
                return replies[min(len(calls), len(replies)) - 1]
        item = {"trial_id": "A", "label": "potential", "open_criteria": ["A-I01"], "stale": False, "kr_recruiting": False,
                "kr_sites": 0, "review_flags": [], "rank": 1, "months_since_verified": 3, "status_verified": "2026-07"}
        r = {"patient_id": "P", "ranking": ["A"], "items": [item], "dropped_stale_trials": []}
        doc, log = brief_llm.build("P", r, GC, {"A": {"title": "T"}}, "patient", Fake(), 5)
        g = check(doc, GC)
        self.assertFalse(g["unlinked"] or g["bad_refs"] or g["banned"] or g["missing_rules"])
        self.assertEqual(cc(doc, GC, {"A": {"title": "T"}}), [])
        return doc, log, calls

    def test_good(self):
        good = json.dumps({"sentences": [{"trial": "T1", "text": "1번 시험 — 아직 확인이 필요한 조건이 있습니다.",
                                          "facts": ["T1.label"]},
                                         {"trial": "T1", "text": "콩팥 기능 검사 결과를 다시 확인해야 합니다.", "facts": ["T1.route_tests"]}]})
        doc, log, calls = self.run_with([good])
        self.assertEqual((len(calls), log["fallback"]), (1, []))

    def test_out_of_glossary_term_needs_original(self):
        from agent6.brief_llm import assemble
        pack = {"T1": [{"id": "T1.label", "refs": ["trial:A", "label:A"], "ko": "1번 시험 — …", "detail": {}, "required": True},
                       {"id": "T1.studies", "refs": ["trial:A"], "ko": "이 시험은 Myasthenia Gravis을(를) 연구 대상으로 합니다.",
                        "detail": {"untranslated": ["Myasthenia Gravis"]}, "required": False}]}
        ok = [{"trial": "T1", "text": "1번 시험 — 아직 확인이 필요한 조건이 있습니다.", "facts": ["T1.label"]},
              {"trial": "T1", "text": "이 시험은 중증 근무력증(Myasthenia Gravis)을 연구 대상으로 합니다.", "facts": ["T1.studies"]}]
        bad = [ok[0], {"trial": "T1", "text": "이 시험은 중증 근무력증을 연구 대상으로 합니다.", "facts": ["T1.studies"]}]
        self.assertEqual(assemble(ok, pack, "patient")[1], [])
        self.assertTrue(any("원어 병기 없음" in p for p in assemble(bad, pack, "patient")[1]))

    def test_bad_then_fallback(self):
        bad = json.dumps({"sentences": [{"trial": "T1", "text": "1. 이 시험에 참여 가능합니다. eGFR 40", "facts": ["T1.label"]},
                                        {"trial": "T1", "text": "x", "facts": ["T9.zz"]}]})
        doc, log, calls = self.run_with([bad, bad])
        self.assertEqual((len(calls), log["fallback"]), (2, ["T1"]))
        self.assertIn("문제", calls[1])


class Update(unittest.TestCase):
    def test_trial_of_and_touch(self):
        from agent6.eval_update import touches, trial_of
        self.assertEqual([trial_of(r) for r in ("trial:A", "label:A", "crit:A-I01", "dec:A:A-I01:r1", "calc:A:A-I01",
                                                 "rule:placebo")], ["A", "A", "A", "A", "A", None])
        self.assertTrue(touches(frozenset({"rule:placebo", "trial:A"}), {"T:A"}))
        self.assertFalse(touches(frozenset({"rule:placebo"}), {"T:A"}))

    def test_align(self):
        from agent6.eval_update import align
        a, b = frozenset({"dec:x", "crit:x"}), frozenset({"dec:y"})
        pairs, extra = align([a, b], [b, frozenset({"dec:z"})])
        self.assertEqual(pairs, [(0, None), (1, 0)])
        self.assertEqual(extra, [1])


class Dual(unittest.TestCase):
    def test_split(self):
        from agent6.eval_dual import score_doc
        doc = {"patient_id": "P", "audience": "clinician", "as_of": AS_OF, "ranking": ["A"], "sentences": [
            {"text": "미확인 1개", "refs": ["dec:A:A-I01:r1"], "kind": "fact"},
            {"text": "충족", "refs": ["dec:A:A-E01:r1"], "kind": "fact"}]}
        gold = {("P", "A"): {"label": "potential", "crit": {"A-I01": "PASS", "A-E01": "PASS"}}}
        r = score_doc(doc, GC, {}, gold, {"P": ["A"]})
        self.assertEqual((r["upstream_error"], r["a6_error"], r["ok"]), (1, 1, 0))


class KeyInfo(unittest.TestCase):
    def test_design_rules_and_age(self):
        from agent6.keyinfo import design_rules
        from agent6.review import age_outside, near_miss
        t = {"phases": ["PHASE2", "PHASE3"], "allocation": "RANDOMIZED", "briefing_extra": {"masking": "DOUBLE"},
             "arms": [{"type": "EXPERIMENTAL"}, {"type": "PLACEBO_COMPARATOR"}]}
        self.assertEqual([r["refs"][0] for r in design_rules(t, "A")],
                         ["rule:phase_PHASE2_PHASE3", "rule:randomized", "rule:placebo", "rule:blinded"])
        self.assertTrue(age_outside(7.4, {"min_age": 18}))
        self.assertFalse(age_outside(68.7, {"min_age": 18, "max_age": None}))
        self.assertTrue(age_outside(76.2, {"min_age": 18, "max_age": 75}))
        rows = [{"trial_id": "B", "trial_label": "ineligible", "criteria": [
            {"criterion_id": "B-E01", "status": "FAIL", "note": "Note conflicts with the history line."}]}]
        self.assertEqual(near_miss(rows), [{"trial_id": "B", "criterion_id": "B-E01", "flags": ["fail_note_conflict"]}])

    def test_glossary_and_josa(self):
        from agent6 import glossary as GL
        from agent6.keyinfo import josa, ko_terms
        self.assertEqual(GL.display(GL.lookup("chronic obstructive pulmonary disease")), "만성 폐쇄성 폐질환(COPD)")
        self.assertEqual(GL.lookup("Alzheimer&#39; Disease")["ko"], "알츠하이머병")
        self.assertEqual([n for n, _ in ko_terms(["Tirzepatide", "Obesity", "Made Up Disease"], studied_only=True)],
                         ["비만", "Made Up Disease"])
        cr = GL.lookup("Colorectal Neoplasms")
        self.assertEqual((GL.name_for(cr, "A Trial in Advanced Colorectal Cancer"),
                          GL.name_for(cr, "Colonoscopy Detection of Adenomas in Colorectal Cancer Screening"),
                          GL.name_for(cr, "Bowel Preparation Study")), ("대장암", "대장 종양", "대장 종양"))
        lv = GL.lookup("Liver Neoplasm")
        self.assertEqual((GL.name_for(lv, "Radioembolization for Liver Metastases"),
                          GL.name_for(lv, "T-Cell Therapy in Adults With Advanced HCC")), ("간 종양", "간암"))
        st = GL.lookup("Advanced Solid Tumors")
        self.assertEqual((GL.name_for(st, "Open-Label Study of BBO-10203 in Subjects With Advanced Solid Tumors"),
                          GL.name_for(st, "Study in Advanced or Metastatic Solid Tumors")), ("진행성 고형 종양", "진행성 고형암"))
        self.assertEqual((josa("신증후군", "을", "를"), josa("심부전", "을", "를"), josa("치매", "을", "를"),
                          josa("만성 폐쇄성 폐질환(COPD)", "을", "를"), josa("Foo", "이", "가")),
                         ("을", "을", "를", "을", "이(가)"))

    def test_mesh_fallback(self):
        from agent6.keyinfo import studied_names
        t = {"title": "A Study", "conditions": ["Some Unlisted Wording"], "condition_mesh": ["Pulmonary Disease, Chronic Obstructive"]}
        self.assertEqual([n for n, _ in studied_names(t)], ["만성 폐쇄성 폐질환(COPD)"])
        t2 = {"title": "A Study", "conditions": ["Heart Failure", "Unlisted"], "condition_mesh": ["Diabetes Mellitus"]}
        self.assertEqual([n for n, _ in studied_names(t2)], ["심부전", "Unlisted"])   # conditions hit: MeSH not mixed in

    def test_rules_not_banned(self):
        from agent6.rules import BANNED, FIXED
        self.assertEqual([(k, w) for k, v in FIXED.items() for w in BANNED if w in v], [])


class ExternalTumourWording(unittest.TestCase):
    """TrialGPT TREC/SIGIR patients (tests/external): no cancer name for patients without a confirmed malignancy."""

    def test_external(self):
        from agent6 import eval_external as E
        cases = json.load(open(E.DEFAULT, encoding="utf-8"))["cases"]
        res, _ = E.run(cases, protect=True)
        self.assertEqual(res[("benign", "cancer_named")] + res[("hard_negative", "cancer_named")], 0)
        self.assertEqual(res[("malignant", "cancer_trial_named")], res[("malignant", "cancer_trial")])
        off, _ = E.run(cases, protect=False)
        self.assertGreater(off[("benign", "cancer_named")] + off[("hard_negative", "cancer_named")], 0)


class GlossaryProtocol(unittest.TestCase):
    """10/31 protocol: frozen extractor without trial ids, two scoring conditions, freeze by sha256."""

    def test_terms_tool_has_no_trial_ids(self):
        import csv, tempfile
        from agent6 import glossary as GL, glossary_terms as GT
        d = tempfile.mkdtemp()
        tp, out = os.path.join(d, "trials.jsonl"), os.path.join(d, "terms.csv")
        with open(tp, "w") as f:
            f.write(json.dumps({"trial_id": "NCT99999999", "conditions": ["Example Rare Syndrome", "Heart Failure"],
                                "condition_mesh": ["Example Rare Syndrome"]}) + "\n")
        GT.main(["--trials", tp, "--glossary", GL.DEFAULT, "--out", out])
        rows = list(csv.DictReader(open(out, encoding="utf-8-sig")))
        self.assertEqual([(r["en"], r["source"]) for r in rows], [("Example Rare Syndrome", "condition+mesh")])
        self.assertNotIn("NCT", open(out, encoding="utf-8-sig").read())
        self.assertEqual(GT.TOOL_VERSION, "gt-1.0.0")

    def test_none_mode_and_freeze(self):
        import tempfile, shutil
        from agent6 import glossary as GL
        os.environ["AGENT6_GLOSSARY"] = "none"
        try:
            self.assertIsNone(GL.lookup("Heart Failure"))
            self.assertEqual(GL.usage([])["mode"], "none")
        finally:
            os.environ.pop("AGENT6_GLOSSARY")
        self.assertEqual(GL.lookup("Heart Failure")["ko"], "심부전")
        d = tempfile.mkdtemp()
        g = os.path.join(d, "glossary.csv"); shutil.copy(GL.DEFAULT, g)
        old = GL.FREEZE
        GL.FREEZE = os.path.join(d, "GLOSSARY_FREEZE.json")
        try:
            json.dump({"file": "glossary.csv", "sha256": GL.sha256(g)}, open(GL.FREEZE, "w"))
            self.assertTrue(GL.check_freeze(g))
            with open(g, "a", encoding="utf-8") as f:
                f.write("Edited Term,편집,,disease,condition,,reviewed,,\n")
            with self.assertRaises(RuntimeError):
                GL.check_freeze(g)
        finally:
            GL.FREEZE = old



class EvidenceVersion(unittest.TestCase):
    """a6-0.3.7: Agent 2 files read directly must be the graph's version; outside-graph evidence is cited as ev:."""

    def setUp(self):
        import tempfile
        self.d = tempfile.mkdtemp()
        self.gdir = os.path.join(self.d, "graph"); os.makedirs(self.gdir)
        self.g = {"patient_id": "PV", "as_of": AS_OF, "version": 1, "edges": [["trial:A", "labelled", "label:A"]], "nodes": [
            {"id": "trial:A", "kind": "trial"}, {"id": "label:A", "kind": "trial_decision", "label": "potential"},
            {"id": "ev:PV-EV001", "kind": "evidence", "concept": "ecog", "term": "ECOG", "value": 1}]}
        json.dump(self.g, open(os.path.join(self.gdir, "PV.json"), "w"))

    def tearDown(self):
        from agent6 import keyinfo as KI
        KI.load_evidence([])

    def ev(self, rows):
        p = os.path.join(self.d, "ev.jsonl")
        with open(p, "w") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
        return p

    MAL = {"evidence_id": "PV-EV009", "patient_id": "PV", "concept": "diagnosis", "term": "pancreatic adenocarcinoma",
           "value": True, "certainty": "confirmed", "subject": "patient"}

    def test_same_version_passes_and_mismatch_stops(self):
        from agent6 import keyinfo as KI
        same = {"evidence_id": "PV-EV001", "patient_id": "PV", "concept": "ecog", "term": "ECOG", "value": 1}
        info = KI.load_evidence([self.ev([same, self.MAL])], [self.gdir])
        self.assertEqual(info["graph_ev_nodes_checked"], 1)
        with self.assertRaises(RuntimeError):                 # renumbered ids (another Agent 2 version)
            KI.load_evidence([self.ev([dict(same, evidence_id="PV-EV101")])], [self.gdir])
        with self.assertRaises(RuntimeError):                 # same id, different term
            KI.load_evidence([self.ev([dict(same, term="ECOG performance status")])], [self.gdir])
        with self.assertRaises(ValueError):                   # no graph folders -> cannot check
            KI.load_evidence([self.ev([same])])
        other = os.path.join(self.d, "rules.jsonl")           # another extraction reusing the id -> stop
        with open(other, "w") as f:
            f.write(json.dumps(dict(same, term="Atopic dermatitis", concept="diagnosis")) + "\n")
        with self.assertRaises(RuntimeError):
            KI.load_evidence([self.ev([same]), other], [self.gdir])

    def test_outside_evidence_is_cited(self):
        from agent6 import keyinfo as KI
        from agent6.check_content import check as cc
        same = {"evidence_id": "PV-EV001", "patient_id": "PV", "concept": "ecog", "term": "ECOG", "value": 1}
        KI.load_evidence([self.ev([same, self.MAL])], [self.gdir])
        g = Graph(self.g)
        self.assertEqual(KI.outside_malignancy_refs(g), ["ev:PV-EV009"])
        trial = {"trial_id": "A", "title": "Pancreatic cancer study", "conditions": ["Pancreatic Cancer"]}
        facts = KI.patient_facts(g, {"trial_id": "A", "label": "potential", "review_flags": [], "kr_recruiting": False, "kr_sites": 0, "stale": False}, trial, 1)
        st = next(f for f in facts if f["id"] == "T1.studies")
        self.assertIn("ev:PV-EV009", st["refs"])
        self.assertEqual(check({"audience": "patient", "ranking": ["A"], "sentences": [
            {"text": st["ko"], "refs": st["refs"], "kind": "fact"}]}, g)["bad_refs"], [])   # ev: of the file is valid
        doc = {"audience": "patient", "ranking": ["A"], "as_of": AS_OF,
               "sentences": [{"text": st["ko"], "refs": ["trial:A"], "kind": "fact"}]}
        self.assertIn("ev_uncited", [p[1] for p in cc(doc, g, {"A": trial})])
        doc["sentences"][0]["refs"] = st["refs"]
        self.assertNotIn("ev_uncited", [p[1] for p in cc(doc, g, {"A": trial})])


class WaldenstromIsCancer(unittest.TestCase):
    def test_both_languages(self):
        from agent6 import keyinfo as KI, glossary as GL
        self.assertTrue(KI.names_cancer("Waldenstrom Macroglobulinemia"))
        self.assertTrue(KI.names_cancer(GL.lookup("Waldenstrom Macroglobulinemia")["ko"]))
        self.assertFalse(KI.names_cancer("고글로불린혈증"))


class IdSeries(unittest.TestCase):
    """a6-0.4.1: Agent 2 v14.14 rules-only ids -R001; run_meta id_series must not be mixed."""

    def test_r_ids_are_not_numbers(self):
        from agent6.check_content import ID_RE
        for t in ("SYN-0001-R001", "SYN-0001-R1234", "TREC-2021-7-R001", "R001", "EV1000", "SYN-0001-EV1000"):
            self.assertEqual(ID_RE.sub("", t).strip(), "", t)
        self.assertEqual(ID_RE.sub("", "약 120명").strip(), "약 120명")

    def test_run_meta_series(self):
        import tempfile
        from agent6 import keyinfo as KI
        d = tempfile.mkdtemp()
        def put(name, rows, meta):
            p = os.path.join(d, name + ".jsonl")
            with open(p, "w") as f:
                f.write("".join(json.dumps(r) + "\n" for r in rows))
            if meta:
                json.dump(meta, open(os.path.join(d, name + ".run_meta.json"), "w"))
            return p
        h = put("h", [{"evidence_id": "P-EV001", "patient_id": "P"}], {"id_series": "haiku", "id_prefix": "EV"})
        r = put("r", [{"evidence_id": "P-R001", "patient_id": "P"}], {"id_series": "rules", "id_prefix": "R"})
        bad = put("b", [{"evidence_id": "P-EV001", "patient_id": "P"}], {"id_series": "rules", "id_prefix": "R"})
        self.assertEqual(KI._check_series([h]), "haiku")
        self.assertEqual(KI._check_series([r]), "rules")
        self.assertIsNone(KI._check_series([put("n", [{"evidence_id": "P-EV001", "patient_id": "P"}], None)]))
        with self.assertRaises(RuntimeError):
            KI._check_series([h, r])
        with self.assertRaises(RuntimeError):
            KI._check_series([bad])


class LLMGuards042(unittest.TestCase):
    """a6-0.4.2: problems the first real LLM run showed that the old checks let through."""

    def test_one_fact_one_sentence(self):
        from agent6.brief_llm import assemble
        pack = {"T1": [{"id": "T1.label", "refs": ["trial:A", "label:A"], "ko": "", "detail": {}, "required": True},
                       {"id": "T1.route_ask_you", "refs": ["dec:A:A-I06:r1", "dec:A:A-I07:r1"], "ko": "", "detail": {},
                        "required": False}]}
        split = [{"trial": "T1", "text": "1번 시험 — 아직 확인이 필요한 조건이 있습니다.", "facts": ["T1.label"]},
                 {"trial": "T1", "text": "직접 답해 주실 질문이 2가지 남아 있습니다.", "facts": ["T1.route_ask_you"]},
                 {"trial": "T1", "text": "동의서 작성이 아직 확인되지 않았습니다.", "facts": ["T1.route_ask_you"]}]
        self.assertTrue(any("여러 문장" in p for p in assemble(split, pack, "patient")[1]))
        self.assertEqual(assemble(split[:2], pack, "patient")[1], [])

    def test_patient_english_outside_parens(self):
        from agent6.check_content import english_outside_parens
        g = Graph({"patient_id": "P", "as_of": AS_OF, "version": 1, "edges": [], "nodes": []})
        trials = {"A": {"conditions": ["Myasthenia Gravis"]}}
        bad = {"text": "7일 이내에 측정한 CRP로 계산해야 합니다.", "refs": ["trial:A"], "kind": "fact"}
        self.assertEqual(english_outside_parens(bad, g, trials), ["CRP"])
        ok1 = {"text": "이 시험은 Myasthenia Gravis을(를) 연구 대상으로 합니다.", "refs": ["trial:A"], "kind": "fact"}
        ok2 = {"text": "이 시험은 중증 근무력증(Myasthenia Gravis)을 연구 대상으로 합니다.", "refs": ["trial:A"], "kind": "fact"}
        self.assertEqual(english_outside_parens(ok1, g, trials), [])
        self.assertEqual(english_outside_parens(ok2, g, trials), [])

    def test_flag_claim_needs_a_flag(self):
        from agent6.check_content import check as cc, flags_by_trial
        g = Graph({"patient_id": "P", "as_of": AS_OF, "version": 1, "edges": [], "nodes": [{"id": "trial:A", "kind": "trial"}]})
        doc = {"patient_id": "P", "audience": "clinician", "ranking": ["A"], "as_of": AS_OF,
               "sentences": [{"text": "모집 상태가 오래되었으며, 재확인 표시가 있습니다.", "refs": ["trial:A"], "kind": "fact"}]}
        none = flags_by_trial([{"patient_id": "P", "items": [{"trial_id": "A", "review_flags": []}], "near_miss": []}])
        some = flags_by_trial([{"patient_id": "P", "items": [{"trial_id": "A", "review_flags": [{"flag": "note_negates"}]}],
                                "near_miss": []}])
        other = flags_by_trial([{"patient_id": "Q", "items": [{"trial_id": "A", "review_flags": [{"flag": "note_negates"}]}],
                                 "near_miss": []}])
        self.assertIn("flag_claim", [p[1] for p in cc(doc, g, {}, none)])
        self.assertNotIn("flag_claim", [p[1] for p in cc(doc, g, {}, some)])
        self.assertIn("flag_claim", [p[1] for p in cc(doc, g, {}, other)])     # another patient's flag does not count


class LLMGuards043(unittest.TestCase):
    def test_internal_T_label(self):
        from agent6.brief_llm import assemble
        pack = {"T1": [{"id": "T1.label", "refs": ["trial:A", "label:A"], "ko": "", "detail": {}, "required": True}]}
        bad = [{"trial": "T1", "text": "T1은 potential 판정입니다.", "facts": ["T1.label"]}]
        ok = [{"trial": "T1", "text": "NCT00000001은 potential 판정입니다.", "facts": ["T1.label"]}]
        self.assertTrue(any("내부 번호" in p for p in assemble(bad, pack, "clinician")[1]))
        self.assertEqual(assemble(ok, pack, "clinician")[1], [])


class Eval2Agreement(unittest.TestCase):
    """a6-0.4.5: layer-2 agreement statistics against published values."""

    def test_krippendorff_example(self):
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
        from eval2_agree import kalpha, cohen
        N = None   # Krippendorff (2011) "Computing Krippendorff's alpha-reliability", 4 coders x 12 units
        rows = [[1, 2, 3, 3, 2, 1, 4, 1, 2, N, N, N], [1, 2, 3, 3, 2, 2, 4, 1, 2, 5, N, 3],
                [N, 3, 3, 3, 2, 3, 4, 2, 2, 5, 1, N], [1, 2, 3, 3, 2, 4, 4, 1, 2, 5, 1, N]]
        units = [[x for x in col if x is not None] for col in zip(*rows)]
        self.assertAlmostEqual(kalpha(units, "nominal"), 0.743, places=3)
        self.assertAlmostEqual(kalpha(units, "ordinal"), 0.815, places=3)
        self.assertAlmostEqual(cohen([0, 1, 2, 3], [0, 1, 2, 3], [0, 1, 2, 3], True), 1.0)


class KoreanParticleIds(unittest.TestCase):
    """a6-0.4.7: ids followed by a Korean particle are ids, not numbers to check; plain numbers are still checked."""

    def test_ids(self):
        from agent6.check_content import ID_RE
        for t, want in (("이 중 E23에서 같은 날", "이 중 에서 같은 날"), ("I03은 미확인", "은 미확인"), ("R001과", "과"),
                        ("SYN-0001-EV028이", "이"), ("약 23명", "약 23명"), ("E23", ""), ("BE23X", "BE23X")):
            self.assertEqual(ID_RE.sub("", t), want, t)

    def test_network_retry(self):
        import urllib.error
        from agent6 import brief_llm
        calls = []

        class R:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"content":[{"type":"text","text":"ok"}],"usage":{}}'

        def fake(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError("timed out")
            return R()
        import tempfile, unittest.mock as um
        with um.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}):
            llm = brief_llm.LLM("m", tempfile.mkdtemp())
        llm.key, llm.base = "k", "http://x"
        with um.patch("urllib.request.urlopen", fake), um.patch("time.sleep", lambda s: None), \
                um.patch("json.load", lambda r: json.loads(r.read())):
            self.assertEqual(llm("s", "u", []), "ok")
        self.assertEqual(len(calls), 2)


class CardLinks(unittest.TestCase):
    """a6-0.4.8: briefing dec: refs join Agent 5 cards on (patient, trial, criterion)."""

    def test_link(self):
        import tempfile, io, contextlib
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
        import link_cards
        d = tempfile.mkdtemp()
        b = os.path.join(d, "b"); os.makedirs(b)
        json.dump({"patient_id": "P", "audience": "patient", "sentences": [
            {"text": "직접 답해 주실 수 있는 질문: 1가지.", "refs": ["crit:A-I01", "dec:A:A-I01:r1"], "kind": "fact"},
            {"text": "담당 의사가 판단할 것: 1가지.", "refs": ["dec:A:A-I02:r1"], "kind": "fact"}]},
            open(os.path.join(b, "P.patient.json"), "w"))
        cp = os.path.join(d, "cards.jsonl")
        open(cp, "w").write(json.dumps({"patient_id": "P", "type": "patient_question", "card_id": "P:patient_question:L01",
                                        "items": [{"trial_id": "A", "criterion_id": "A-I01"}]}) + "\n")
        out = os.path.join(d, "links.jsonl")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            link_cards.main(["--briefings", b, "--cards", cp, "--out", out])
        rows = [json.loads(l) for l in open(out)]
        self.assertEqual([(r["i"], r["cards"]) for r in rows], [(0, ["P:patient_question:L01"])])
        self.assertIn("with a card 1 (50.0%)", buf.getvalue())
        self.assertIn("matching card type 1/1", buf.getvalue())


class FixJosa(unittest.TestCase):
    """a6-0.4.10: two-way particles after a Korean name are resolved; after an English name they stay."""

    def test_fix(self):
        from agent6.keyinfo import fix_josa
        cases = [("특발성 폐섬유증(Idiopathic Pulmonary Fibrosis (IPF))을(를) 연구", "특발성 폐섬유증(Idiopathic Pulmonary Fibrosis (IPF))을 연구"),
                 ("신증후군(Nephrotic Syndrome)을(를)", "신증후군(Nephrotic Syndrome)을"),
                 ("심부전(Heart Failure)을(를)", "심부전(Heart Failure)을"),
                 ("당뇨병(Diabetes)이(가) 맞습니다", "당뇨병(Diabetes)이 맞습니다"),
                 ("편두통(Migraine)과(와) 두통", "편두통(Migraine)과 두통"),
                 ("만성 폐쇄성 폐질환(COPD)을(를)", "만성 폐쇄성 폐질환(COPD)을"),
                 ("치매(Dementia)을(를)", "치매(Dementia)를"),
                 ("관절염(Arthritis)(으)로", "관절염(Arthritis)으로"),
                 ("Nephrotic Syndrome을(를) 연구", "Nephrotic Syndrome을(를) 연구"),
                 ("췌장암(Pancreas Cancer)을 연구", "췌장암(Pancreas Cancer)을 연구")]
        for a, b in cases:
            self.assertEqual(fix_josa(a), b, a)


class PatientTranslationChecks(unittest.TestCase):
    """a6-0.4.11 (pb10): stage/grade kept in Korean, HR+/ER+/PR+ spelled out; the parenthesised original does not count."""

    def test_qualifier(self):
        from agent6.brief_llm import qualifier_missing as q
        t = "multifocal hepatocellular carcinoma BCLC B"
        self.assertEqual(q(t, f"기록에 있는 진단 다발성 간세포암({t})이 맞습니다."), ["BCLC B"])
        self.assertEqual(q(t, f"기록에 있는 진단 다발성 간세포암 BCLC B기({t})가 맞습니다."), [])
        self.assertEqual(q("Stage IV Lung Cancer", "4기 폐암(Stage IV Lung Cancer)"), [])
        self.assertEqual(q("Stage IIIA Lung Cancer", "3A기 폐암(Stage IIIA Lung Cancer)"), [])
        self.assertEqual(q("grade 2 peripheral neuropathy", "말초신경병증(grade 2 peripheral neuropathy)"), ["grade 2"])
        self.assertEqual(q("grade 2 peripheral neuropathy", "2등급 말초신경병증(grade 2 peripheral neuropathy)"), [])
        self.assertEqual(q("sigmoid primary pT3N2a", "구불결장 원발, 병리 병기 pT3N2a(sigmoid primary pT3N2a)"), [])
        self.assertEqual(q("Heart Failure", "심부전(Heart Failure)"), [])

    def test_abbreviation(self):
        from agent6.brief_llm import abbreviation_left as a
        t = "HR+/HER2- breast cancer"
        self.assertEqual(a(t, f"HR+/HER2- 유방암({t})"), ["HR+"])
        self.assertEqual(a(t, f"호르몬 수용체 양성·HER2 음성 유방암({t})"), [])

class SynonymMerge(unittest.TestCase):
    """a6-0.4.12: one trial's synonyms / a diagnosis repeated without its stage are shown once."""

    def test_merge(self):
        from agent6.keyinfo import merge_synonyms as m
        self.assertEqual(m(["IPF", "Idiopathic Pulmonary Fibrosis", "Idiopathic Pulmonary Fibrosis (IPF)"]),
                         ["Idiopathic Pulmonary Fibrosis (IPF)"])
        self.assertEqual(m(["multifocal hepatocellular carcinoma BCLC B", "multifocal hepatocellular carcinoma"]),
                         ["multifocal hepatocellular carcinoma BCLC B"])
        self.assertEqual(m(["Graves' Disease", "Graves disease"]), ["Graves' Disease"])
        self.assertEqual(m(["COPD", "COPD exacerbation"]), ["COPD", "COPD exacerbation"])
        self.assertEqual(m(["Ovarian Cancer", "Pancreas Cancer"]), ["Ovarian Cancer", "Pancreas Cancer"])
        self.assertEqual(m(["Rheumatoid Arthritis", "Insufficient Response to Methotrexate or Leflunomide"]),
                         ["Rheumatoid Arthritis", "Insufficient Response to Methotrexate or Leflunomide"])

    def test_drop_unstaged(self):
        from agent6.keyinfo import _drop_unstaged as d
        self.assertEqual(d([("다발성 간세포암(BCLC B기)", "g1"), ("다발성 간세포암", "g2")]), [("다발성 간세포암(BCLC B기)", "g1")])
        self.assertEqual(d([("만성 폐쇄성 폐질환", "g1"), ("만성 폐쇄성 폐질환 악화", "g2")]),
                         [("만성 폐쇄성 폐질환", "g1"), ("만성 폐쇄성 폐질환 악화", "g2")])


class ArmsAndSites(unittest.TestCase):
    """a6-0.4.13: what the trial compares (arms, glossary drug names) and the no-Korean-site sentence."""

    def test_arms(self):
        from agent6.arms import arms_sentence, render_intervention as r
        t = {"arms": [{"type": "EXPERIMENTAL", "interventions": ["Drug: Abatacept (W12-W48)", "Drug: TNF Inhibitor (W0-W12)"]},
                      {"type": "ACTIVE_COMPARATOR", "interventions": ["Drug: TNF Inhibitor (W12-W48)", "Drug: TNF Inhibitor (W0-W12)"]}]}
        self.assertEqual(arms_sentence(t)[0], "시험군: TNF 억제제(0~12주) → 아바타셉트(12~48주), 비교군: TNF 억제제(0~48주).")
        t = {"arms": [{"type": "EXPERIMENTAL", "interventions": ["Drug: Methotrexate + targeted therapy administration"]},
                      {"type": "ACTIVE_COMPARATOR",
                       "interventions": ["Drug: methotrexate or leflunomide + sulfasalazine + hydroxychloroquine administration"]}]}
        self.assertEqual(arms_sentence(t)[0], "시험군: 메토트렉세이트 + 표적치료, 비교군: 메토트렉세이트 또는 레플루노미드 + 설파살라진 + 하이드록시클로로퀸.")
        self.assertEqual(r("Drug: AZD8965 high dose")[0], "시험약 AZD8965(고용량)")
        self.assertEqual(r("Other: Placebo for AZD8965")[0], "위약")
        self.assertEqual(r("Drug: empagliflozin 10mg")[0], "엠파글리플로진(10mg)")
        self.assertEqual(r("Procedure: Intravitreal 100% C3F8 Injection")[0], "유리체강 내 100% C3F8 가스 주입")
        self.assertIsNone(arms_sentence({"arms": []}))

    def test_sites(self):
        from agent6.keyinfo import site_lines
        t = {"overall_status": "RECRUITING", "countries": ["France", "Monaco"],
             "sites": [{"country": "France", "status": "RECRUITING"}, {"country": "Monaco", "status": "RECRUITING"}]}
        out = site_lines({"trial_id": "NCT0", "kr_sites": 0}, t)
        self.assertEqual([s["text"] for s in out], ["현재 국내에는 이 시험의 참여자를 모집하는 기관이 없습니다.", "모집 국가: 프랑스, 모나코."])
        self.assertIn("rule:no_kr_site", out[0]["refs"])
        self.assertEqual(site_lines({"trial_id": "NCT0", "kr_sites": 2}, t), [])
        from agent6.arms import countries_sentence
        many = {"sites": [{"country": c, "status": "RECRUITING"} for c in
                          ["United States", "Germany", "Japan", "France", "Italy", "Spain", "Atlantis"]]}
        self.assertEqual(countries_sentence(many), "모집 국가: 미국, 독일, 일본, 프랑스, 이탈리아 외 2개국.")


if __name__ == "__main__":
    unittest.main()
