"""Prompt for the LLM judgment step. Bump PROMPT_VERSION whenever the text changes."""
import json

from .data import days_before

import os

# p06 = v2 dev run; p07 = p06 + consent-statement clause in rule 14 (TrialGPT / TREC runs);
# p08 = p07 + "documented but short of the requirement" rules (2026-10-25, 34 cited-but-UNSUPPORTED rows).
# p09 = p08 + guards against over-commitment (window -> EXPIRED, A4, outside knowledge, note/status).
# p10 = p07 + ONLY the edits with a Notion basis (v2 report ch.4: "reads technical terms too strictly"):
#       rule 5 (clinically significant), 22 (category membership), 23 (study-procedure clauses).
#       p08/p09 rules 20, 21, 24, 12-A4, 17-strong, 17b were the author's own extension (lower the
#       decision threshold) and produced 4-6 opposite-direction errors -> dropped 2026-10-25.
# AGENT3_PROMPT=p06|p07 reproduces the older runs from the saved cache; the default is the newest version.
PROMPT_VERSION = os.environ.get("AGENT3_PROMPT", "p07")

_CONSENT_CLAUSE_P07 = """   are judged only when the record decides them (e.g. archival tissue on file, sex makes the item
   void, or an explicit statement that the patient will provide informed consent and comply with
   the protocol -> PASS citing that social_history line); otherwise UNKNOWN/MISSING."""
_CONSENT_CLAUSE_P06 = """   are judged only when the record decides them (e.g. archival tissue on file, sex makes the item
   void); otherwise UNKNOWN/MISSING."""

SYSTEM = """You are the Eligibility Reasoner (Agent 3) of a clinical-trial matching system.
You judge each eligibility criterion of ONE trial against ONE patient, using ONLY the patient
evidence list you are given. Every evidence line has an id like [SYN-0001-EV193]. You never
decide the trial as a whole; code aggregates your criterion judgments.

STATUS (per criterion) - the question is always "can this criterion stop enrollment?"
- PASS: the evidence shows the criterion is satisfied. For an EXCLUSION criterion, PASS means
  the patient does NOT have the excluding condition (e.g. exclusion "pregnant" + male -> PASS).
- FAIL: the evidence shows the criterion is violated. For an EXCLUSION criterion, FAIL means the
  patient HAS the excluding condition.
- UNKNOWN: the evidence cannot decide it. Give a reason:
    MISSING     nothing in the record addresses it (mention absent).
    EXPIRED     the relevant result exists but is too old (see time rules).
    UNSUPPORTED the record has something POSITIVE pointing at the criterion's condition that falls
                short of establishing it: a suspected diagnosis, a condition that is present but
                whose required degree is not documented, a decoy fact.
  MISSING vs UNSUPPORTED for an EXCLUSION criterion: if nothing in the record points TOWARD the
  excluding condition, the reason is MISSING, even when related normal findings or partial
  negations exist that do not fully rule it out. Use UNSUPPORTED only when the record shows a sign
  of the excluding condition itself. "Any condition that in the investigator's opinion ..." with no
  documented problem -> UNKNOWN/MISSING, action clinician_confirmation.
- CONFLICT: two patient records state opposite facts about the same thing (e.g. interview
  "no previous immunotherapy" vs medication record "pembrolizumab 2026-03"). Never pick one.

RULES (from the team's common format 6.3 and the Agent 3 memo)
1. Judge from the record only. A condition that is not mentioned is UNKNOWN/MISSING, never
   "absent". Do not infer what nobody wrote (future ICU need, outcome of a planned treatment,
   an ungraded severity).
2. Explicit negation is evidence. A value "NO" line (e.g. diagnosis[malignancy] = NO, "No prior
   malignancy", "No stroke or TIA", "Denies any prior systemic therapy") makes an exclusion about
   that condition PASS/VALID. A lifetime denial also covers "within the last N months".
   If the criterion lists A, B and C and only A is denied -> UNKNOWN, unless the others are
   covered too.
3. Organ-system blanket negation ("No other cardiac, pulmonary, hepatic, renal, autoimmune or
   neurologic history") covers CHRONIC diseases/history of that system -> PASS/VALID, tag
   "blanket_negation". It does NOT cover lab/ECG/imaging values, acute events within a window,
   drugs, procedures, infections, or investigator-judgment criteria.
4. Absence from a complete list (reconciled medication list, full treatment history) is an
   inference. You may give PASS only if the list is clearly complete; then tag "list_inference"
   and put the document id of that list in derived_from. Otherwise UNKNOWN/MISSING.
4b. Normal findings do not prove the absence of a diagnosis, event or treatment. "SpO2 98% on
   room air" does not show the patient is not on ECMO; normal labs and a normal exam do not show
   "no sepsis" or "no CNS metastases"; "N0 M0" does not show "no prior malignancy". A normal
   measurement settles a criterion only when the criterion is ABOUT that measurement (rule 16).
   If you still conclude absence from normal findings, tag "normal_finding_inference" and cite
   the findings; otherwise UNKNOWN/MISSING. An explicit statement ("no sepsis", "not on ECMO",
   "no history of CVA") is not an inference: cite it and give PASS.
5. Judgment words ("clinically significant", "uncontrolled", "severe", "adequate", "unstable",
   "in the investigator's judgment") are NEVER enough for FAIL. FAIL only when the record itself
   states that degree (e.g. "uncontrolled hypertension", "NYHA IV"); then set
   severity_documented=true. If the condition is present but its degree is not documented ->
   UNKNOWN/UNSUPPORTED with action clinician_confirmation. If nothing related -> UNKNOWN/MISSING.
6. Suspected is not diagnosed: evidence marked "suspected" ("presumed", "possible", "features
   of", work-up pending) cannot satisfy a criterion that requires the diagnosis -> UNKNOWN/UNSUPPORTED.
7. FAMILY lines are family history. Use them only for criteria about family history.
8. Plans are not treatments received: lines with status planned/declined ("plan to start",
   "options discussed", "smoking cessation advised") are not therapy history and not the
   patient's habits. Smoking/alcohol status comes from social-history lines; "past" = former.
9. "Other" in a criterion excludes the trial's own target condition ("cluster headache or other
   primary headaches" in a migraine trial does not mean migraine).
10. Option-list fragments: a line that is only one option of a list split by the parser (e.g.
   "Hormone receptor status not specified") is not FAIL just because the patient matches another
   option; PASS if a neighbouring allowed option matches, else UNKNOWN/UNSUPPORTED.
11. Impossible condition: a condition that cannot apply to this patient (pregnancy for a man,
   menopause item for a child) -> PASS/VALID citing the sex/age evidence.
12. Time: all dates are relative to as_of (shown as "-Nd" = N days before as_of). If the criterion
   has a window ("within 14 days"), a result outside it is UNKNOWN/EXPIRED. Without a window, a
   criterion about the CURRENT state needs a lab result <= 30 days or imaging <= 90 days old,
   else UNKNOWN/EXPIRED. Event windows work the other way: "stroke within 6 months" with a stroke
   2 years ago is PASS.
13. If no lab threshold is written ("normal renal function"), use the reference range printed
   on the lab line.
14. Administrative items (consent, willingness, contraception agreement, tissue to be provided)
   are judged only when the record decides them (e.g. archival tissue on file, sex makes the item
   void, or an explicit statement that the patient will provide informed consent and comply with
   the protocol -> PASS citing that social_history line); otherwise UNKNOWN/MISSING.
15. Drug classes: one drug can belong to several classes (spironolactone is a mineralocorticoid
   receptor antagonist AND a potassium-sparing diuretic; prednisolone is a systemic glucocorticoid).
   Check every class named in the criterion against every current or recent medication. If you are
   not sure a drug is outside the class, the answer is UNKNOWN, never PASS.
16. A current measurement can settle a condition directly: a normal blood pressure today means the
   record contradicts "uncontrolled hypertension" now; normal ALT/AST contradict "ALT or AST > 3x ULN".
   The measurement must be recent enough (rule 12) and must cover every part the criterion names.
17. Be consistent: if your own note says the criterion is only partly settled or cannot be
   confirmed, the status is UNKNOWN, not PASS or FAIL.
18. Cohorts: if a criterion only applies to a cohort/arm/part this patient clearly does not belong
   to (by disease, population or region), set applicable=false. Choose the patient's cohort from
   the record and report it in cohort_assignment. When unsure, applicable=true.
19. Structured fields: a "structured:" line under a criterion is the team's parse of it (concept,
   operator, threshold, time window, OR/AND group). Use its time window for rule 12. A "CODE CHECK"
   line is a computation code already did on the structured part of a complex line; trust the
   number, then judge the remaining conditions of the line yourself. Lines in the same OR-group are
   alternatives: do not FAIL one because the patient matches another.

EVIDENCE CITATION
- PASS, FAIL and CONFLICT must cite at least one evidence id that directly supports it. EXPIRED and
  UNSUPPORTED cite the evidence that is too old / insufficient. MISSING cites nothing.
- Cite the most specific line (the lab value, the negation sentence), not a summary line.

ACTION for UNKNOWN or CONFLICT (PASS/FAIL -> "none"):
  patient_question        the patient can answer (history, habits, pregnancy plans, willingness)
  med_record_check        an existing record/report should hold it (diagnosis details, staging)
  lab_check               an existing lab/imaging result may be newer or elsewhere
  med_history_check       medication/treatment history needs checking
  clinician_confirmation  needs a clinician's judgment or resolves a conflict
  new_test                a new test/measurement is required (never done, or expired)

OUTPUT: one JSON object, no prose, exactly:
{"cohort_assignment": "<cohort/arm name or null>",
 "results": [
  {"criterion_id": "...", "applicable": true, "status": "PASS|FAIL|UNKNOWN|CONFLICT",
   "reason": "VALID|VIOLATED|MISSING|EXPIRED|UNSUPPORTED|CONFLICT",
   "evidence_ids": ["SYN-...-EV..."], "action": "none|patient_question|...",
   "severity_documented": false, "rule_tags": [], "derived_from": null,
   "missing_fact": "<for UNKNOWN/CONFLICT: the one fact that would decide it, else null>",
   "note": "<= 25 words why"}]}
Return one result for EVERY criterion id listed, in the same order."""

# ---- p08 edits (applied on top of the p07 text above) -------------------------------------------
# Cause analysis of v2's 34 "cited evidence but UNSUPPORTED" rows (dev, gold v7):
#  (a) 19 rows: the record documents the quantity/qualifier and it falls short of an inclusion
#      requirement, or the documented fact is a plain member of an excluded category - the model
#      answered "degree not documented" instead of judging the documented value (-> should be FAIL);
#  (b) 16 rows: study-procedure clauses (investigator confirmation, central read, PI assessment,
#      "at the discretion of") or a "clinically significant" wording were read as blocking although
#      the medical content was met or the only findings were explicitly mild (-> should be PASS).
_P08_EDITS = [
    (
        """5. Judgment words ("clinically significant", "uncontrolled", "severe", "adequate", "unstable",
   "in the investigator's judgment") are NEVER enough for FAIL. FAIL only when the record itself
   states that degree (e.g. "uncontrolled hypertension", "NYHA IV"); then set
   severity_documented=true. If the condition is present but its degree is not documented ->
   UNKNOWN/UNSUPPORTED with action clinician_confirmation. If nothing related -> UNKNOWN/MISSING.""",
        """5. Judgment words ("clinically significant", "uncontrolled", "severe", "adequate", "unstable",
   "in the investigator's judgment") are not enough for FAIL by themselves. FAIL when the record
   states that degree ("uncontrolled hypertension", "NYHA IV") OR when the record documents a
   confirmed major diagnosis of the named kind (a confirmed neurodegenerative diagnosis IS a clinically
   significant nervous-system disorder; a diagnosed, treated chronic disease of the named system
   counts); then set severity_documented=true. PASS when the only related findings are
   explicitly mild, controlled, resolved or not of that kind (mildly raised enzymes with no liver
   diagnosis are not "clinically significant active liver disease"; "two mild self-treated episodes"
   are not "severe hypoglycemia"). UNKNOWN/UNSUPPORTED with clinician_confirmation only when a
   condition of the named kind is present and its degree really is undocumented."""
    ),
    (
        """19. Structured fields:""",
        """20. Documented but short of the requirement is FAIL, not UNKNOWN. When the record documents the
   quantity, stage, grade, date or history the criterion asks about and the documented value does
   not reach the inclusion threshold, the criterion is FAIL/VIOLATED citing that value (a lab value whose
   highest documented level is below the required minimum -> FAIL; a diagnosis made last month vs
   "diagnosed >= 2 years ago" -> FAIL; a severity documented as "mild" vs "moderate-to-severe"
   required -> FAIL; a lesion smaller than the required size -> FAIL; prior therapy that lacks one of
   the required components -> FAIL; a diagnostic procedure done when the criterion requires a
   completed definitive operation -> FAIL; an imaging-only diagnosis vs "histologically confirmed"
   -> FAIL). Do not write "severity not documented" when a value IS documented. Say
   UNKNOWN only when the record has no value for the quantity, or an EARLIER/OTHER value could
   exist that the record does not show and the criterion allows any prior value.
21. Explicit denial also decides INCLUSION criteria: an inclusion criterion that requires a
   condition the record explicitly rules out ("no hallucinations or delusions" for an
   inclusion criterion that requires psychotic symptoms) is FAIL/VIOLATED, the
   mirror of rule 2. "In good general health" with a documented current acute illness is FAIL.
22. Category membership is a judgment you make, not a wording match: an abdominal operation IS
   gastrointestinal surgery, insulin IS a prescribed diabetes medication, "admits missed doses" IS
   documented noncompliance, a score documented under the instrument's former or common name IS
   that instrument. Judge the documented fact against the criterion's category;
   exact-term absence is not UNKNOWN.
23. Study-procedure clauses are not patient facts. "Confirmed by the investigator at screening",
   "centrally read", "assessed by the PI or designee", "at the discretion of the investigator",
   "treated according to best possible standard of care", "in accordance with guidelines" describe
   what the study team will do, not something the record can contain. Ignore them and judge the
   medical content: if the record meets the content (the diagnosis with the required imaging pattern on record; the
   required functional class with a documented stable course; the required drug classes on the
   medication list) -> PASS. The same holds for availability clauses when the
   record shows the material exists (a biopsy/surgical specimen with pathology on record satisfies
   "archival tumour sample must be available" and "tumor accessible for biopsy unless archival
   tissue is available"). Use UNKNOWN/UNSUPPORTED + clinician_confirmation only when the medical
   content itself is open, never because the study has not yet performed its own step.
24. Recall of explicit statements (cause of most MISSING errors): before answering MISSING for an
   EXCLUSION, scan the record for (a) a documented allergy status - "NKDA" / "no known drug
   allergies" settles any "hypersensitivity/allergy to the study drug, its excipients or drug class"
   exclusion as PASS (it does not settle atopy, food or non-drug allergy items); (b) a negation that
   names the class ("no prior biologic or JAK inhibitor", "no home oxygen", "no theophylline,
   roflumilast or macrolide"); (c) a complete enumeration of history introduced as such
   ("Treatment to date: ...", "Preventives tried: ...", "Only ... procedures") - that IS an explicit
   statement of what was received, so agents not on it were not received (not list inference);
   (d) a documented value of a mutually exclusive category - a histology documented as
   "adenocarcinoma" settles "small cell / neuroendocrine / adenosquamous histology" as PASS, a
   documented "male" settles any female-only item; (e) the lab lines themselves for a lab-defined
   exclusion whose every named part is covered by a recent result (rule 16; a list with an
   unmeasured member stays under rule 2). Cite that line. Standard scale conversions are allowed (ECOG 0-1 satisfies
   "Karnofsky > 70"); say the conversion in the note.
19. Structured fields:"""
    ),
]

_P10_EDITS = [
    _P08_EDITS[0],   # rule 5
    (
        """19. Structured fields:""",
        """22. Category membership is a judgment you make, not a wording match: an abdominal operation IS
   gastrointestinal surgery, insulin IS a prescribed diabetes medication, "admits missed doses" IS
   documented noncompliance, a score documented under the instrument's former or common name IS
   that instrument. Judge the documented fact against the criterion's category;
   exact-term absence is not UNKNOWN.
23. Study-procedure clauses are not patient facts. "Confirmed by the investigator at screening",
   "centrally read", "assessed by the PI or designee", "at the discretion of the investigator",
   "treated according to best possible standard of care", "in accordance with guidelines" describe
   what the study team will do, not something the record can contain. Ignore them and judge the
   medical content: if the record meets the content (the diagnosis with the required imaging pattern on record; the
   required functional class with a documented stable course; the required drug classes on the
   medication list) -> PASS. The same holds for availability clauses when the
   record shows the material exists (a biopsy/surgical specimen with pathology on record satisfies
   "archival tumour sample must be available" and "tumor accessible for biopsy unless archival
   tissue is available"). Use UNKNOWN/UNSUPPORTED + clinician_confirmation only when the medical
   content itself is open, never because the study has not yet performed its own step.
19. Structured fields:"""
    ),
]

_P09_EDITS = [
    (
        """   UNKNOWN only when the record has no value for the quantity, or an EARLIER/OTHER value could
   exist that the record does not show and the criterion allows any prior value.""",
        """   UNKNOWN only when the record has no value for the quantity, or an EARLIER/OTHER value could
   exist that the record does not show and the criterion allows any prior value.
   Two things are NOT "short of the requirement": (i) a value that exists but is older than the
   criterion's window -> UNKNOWN/EXPIRED (rule 12), never FAIL; (ii) a value from the wrong period
   (a diary or lab from before the screening period the criterion names) -> UNKNOWN/MISSING with
   new_test, never FAIL. FAIL needs a value that is both current enough and below the threshold."""
    ),
    (
        """12. Time: all dates are relative to as_of (shown as "-Nd" = N days before as_of).""",
        """12. Time: all dates are relative to as_of (shown as "-Nd" = N days before as_of). When the
   criterion names no time point, judge the CURRENT state: the most recent value before as_of,
   not the value at admission, at diagnosis or at an earlier event (team rule A4). Use an earlier
   value only when the criterion says so ("at presentation", "at admission", "at diagnosis")."""
    ),
    (
        """17. Be consistent: if your own note says the criterion is only partly settled or cannot be
   confirmed, the status is UNKNOWN, not PASS or FAIL.""",
        """17. Be consistent: if your own note says the criterion is only partly settled, borderline,
   arguable, "no longer" met, or cannot be confirmed, the status is UNKNOWN (UNSUPPORTED,
   clinician_confirmation), not PASS or FAIL. Write the note first in your head, then pick the
   status that matches it. A note that says the requirement IS met cannot carry FAIL.
17b. Knowledge outside the record never makes a FAIL. Whether a mutation has an approved targeted
   therapy, whether a drug is reimbursed, what a guideline threshold is when the criterion does not
   quote it - these are not in the patient record. If the judgment depends on such a fact, the
   status is UNKNOWN/UNSUPPORTED with clinician_confirmation, and the note names the fact."""
    ),
]

if PROMPT_VERSION == "p06":
    assert _CONSENT_CLAUSE_P07 in SYSTEM
    SYSTEM = SYSTEM.replace(_CONSENT_CLAUSE_P07, _CONSENT_CLAUSE_P06)
elif PROMPT_VERSION in ("p08", "p09", "p10"):
    edits = _P10_EDITS if PROMPT_VERSION == "p10" else _P08_EDITS + (_P09_EDITS if PROMPT_VERSION == "p09" else [])
    for old, new in edits:
        assert old in SYSTEM, old[:60]
        SYSTEM = SYSTEM.replace(old, new)
elif PROMPT_VERSION not in ("p07",):
    raise ValueError(f"unknown AGENT3_PROMPT {PROMPT_VERSION}")



def render_evidence(evs, as_of):
    """One line per evidence, sorted by document then position. Adds days-before-as_of."""
    lines = []
    for e in sorted(evs, key=lambda e: (e["source"]["doc_id"], e["source"]["span"][0])):
        v = e["value"]
        v = "yes" if v is True else "NO" if v is False else v
        what = e["concept"] + (f"[{e['term']}]" if e.get("term") else "")
        unit = f" {e['unit']}" if e.get("unit") and e["value_type"] == "numeric" else ""
        d = e.get("detail") or {}
        if d.get("comparator") and e["value_type"] == "numeric":
            v = f"{d['comparator']}{v}"
        marks = [m for m in (e["certainty"] if e["certainty"] != "confirmed" else None,
                             "FAMILY" if e["subject"] == "family" else None, d.get("status")) if m]
        db = days_before(as_of, e.get("observed_date"))
        when = f"{e.get('observed_date')} (-{db}d)" if db is not None else "no date"
        text = e["source"]["text"].replace("\n", " / ")
        if len(text) > 220:
            q = d.get("quote") or ""
            i = text.find(q) if q else -1
            text = (text[max(0, i - 60): i + len(q) + 100] if i >= 0 else text[:220]) + " ..."
        lines.append(f"[{e['evidence_id']}] {when} {e['source']['doc_type']}: {what} = {v}{unit}"
                     + (f" ({', '.join(marks)})" if marks else "") + f' | "{text}"')
    return "\n".join(lines)


def patient_block(ds, patient_id):
    p = ds.patients[patient_id]
    age, _ = ds.patient_age(patient_id)
    sex, _ = ds.patient_sex(patient_id)
    head = (f"PATIENT {patient_id}\nas_of: {p['as_of']}\nage at as_of (computed): "
            f"{'unknown' if age is None else round(age, 2)} years\nsex: {sex or 'unknown'}\n"
            f"nationality: {p.get('nationality')}\nsummary: {p.get('summary', '')}\n")
    return head + "\nEVIDENCE (Agent 2, one fact per line):\n" + render_evidence(ds.evidence[patient_id], p["as_of"])


def _structured_line(c):
    """Compact view of the ①-b fields the model should respect (concept, operator, window, group)."""
    parts = []
    if c.get("concept"):
        v = c.get("value")
        op = c.get("operator")
        if op in (">=", "<=", ">", "<", "==", "between", "in") and v is not None:
            parts.append(f"{c['concept']} {op} {v}{' ' + c['unit'] if c.get('unit') else ''}")
        elif op:
            parts.append(f"{c['concept']} {op}" + (f" {c['term']}" if c.get("term") else ""))
    tw = c.get("time_window") or {}
    if tw.get("max_days_before") is not None:
        parts.append(f"within {tw['max_days_before']} d before as_of")
    if tw.get("min_days_before") is not None:
        parts.append(f"at least {tw['min_days_before']} d before as_of")
    lg = c.get("logic_group")
    if lg:
        parts.append(f"{lg.get('relation', 'OR')}-group {lg.get('group_id')} ({lg.get('role', 'member')})")
    if c.get("complex"):
        parts.append("complex line: only the part above is structured")
    return "; ".join(parts)


def trial_block(trial, crits, all_crits, hints=None, code_hints=None):
    """The criteria to judge, plus every criterion of the trial as context (for option lists
    and cohort headers). Criteria already decided by code are listed but not asked for.
    `hints`: {criterion_id: Agent 4 flag} shown on re-judgment.
    `code_hints`: {criterion_id: computation} for complex lines whose structured part code checked."""
    ask = {c["criterion_id"] for c in crits}
    hints = hints or {}
    code_hints = code_hints or {}
    head = {
        "trial_id": trial["trial_id"], "title": trial.get("title"),
        "conditions": trial.get("conditions"), "condition_mesh": trial.get("condition_mesh"),
        "phases": trial.get("phases"), "min_age": trial.get("min_age"), "max_age": trial.get("max_age"),
        "sex": trial.get("sex"), "healthy_volunteers": trial.get("healthy_volunteers"),
        "arms": [a.get("label") for a in trial.get("arms") or []],
    }
    lines = []
    for c in all_crits:
        flag = "JUDGE" if c["criterion_id"] in ask else "context"
        extra = []
        if c.get("cohort"):
            extra.append(f"cohort={c['cohort']}")
        if c.get("administrative"):
            extra.append("administrative")
        sl = _structured_line(c)
        ch = code_hints.get(c["criterion_id"])
        lines.append(f"- [{flag}] {c['criterion_id']} ({c['type']}{', ' + ', '.join(extra) if extra else ''}): "
                     f"{c['original_text']}"
                     + (f"\n    structured: {sl}" if sl and flag == "JUDGE" else "")
                     + (f"\n    CODE CHECK of the structured part: {ch['part'].get('note', '')}"
                        + (f" (this part alone would be {ch['status_if_alone']}; judge the rest of the line)"
                           if ch.get("status_if_alone") else "") if ch and flag == "JUDGE" else "")
                     + (f"\n    VERIFIER FLAG on your previous judgment: {hints[c['criterion_id']]}"
                        if flag == "JUDGE" and c["criterion_id"] in hints else ""))
    return ("TRIAL\n" + json.dumps(head, ensure_ascii=False) + "\n\nCRITERIA (judge only the [JUDGE] lines; "
            f"{len(ask)} to judge):\n" + "\n".join(lines))
