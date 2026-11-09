"""Prompt for the LLM layer, split for prompt caching:

  STATIC  (same for every call of a run)  : instructions + concept list + worked examples  -> cache breakpoint 1
  PATIENT (same for all calls of a patient): candidate-trial criteria (relevance=criteria)  -> cache breakpoint 2
  UNITS   (changes every call)             : the numbered units to read

Claude Haiku 4.5 caches only prompts of 4,096 tokens or more, so the static part carries enough worked examples
to pass that size (they also anchor the output format). With OpenRouter / gpt-oss the three parts are simply
joined into one user message.
"""

INSTRUCTIONS = """You turn a patient's medical record into evidence facts for clinical-trial eligibility checking.
Another agent will judge trial criteria ONLY from the facts you return, so do not drop real facts about the
patient. You only extract facts; never judge eligibility and never say whether a criterion is met.

The record is split into numbered units (u1, u2, ...). A unit is a sentence, a line or one item of a list of
measurements; for list items the whole sentence is shown once above them as "(sentence in ...)". For each unit
that states a fact about the patient (or about a relative), return one or more facts. Leave out units that state
no fact: bare headings, scheduling and follow-up logistics, document boilerplate, signatures.{relevance_rule}

RULES
1. No record, no fact. Make value false only when the text explicitly denies something ("No prior
   malignancy", "NKDA", "never smoker", "HIV negative", "no diplopia"). A unit listing several denials gives
   one false fact per denied item. Silence is never a false fact.
2. concept: a key from the concept list. Use a specific key whenever one fits. Use the generic keys
   (diagnosis, medication, procedure, symptom_finding, lab_other, treatment_plan) only when no specific key
   fits, and then name the thing itself in "term" ("Graves disease", "methimazole", "appendectomy",
   "MMSE 23/30"). Keep "term" short and as written.
3. value:
   - lab / vital / measurement keys: the number exactly as written (no unit conversion) and "unit" as
     written (null if none). "<0.01" -> value 0.01 with "comparator": "<". Blood pressure "134/82" as a string.
   - conditions, drugs, procedures, behaviors: true / false.
   - sex "male" / "female"; age a number in years; birth_date "YYYY-MM-DD"; nationality as written.
   - cancer_stage, tumor_marker, lab_other and qualitative results: the result as written ("stage IVA",
     "ER 95%", "positive", "trace", "4+").
4. certainty: "confirmed" for tests, pathology, imaging and diagnoses stated by the clinician; "reported" for
   what the patient or a relative says ("reports", "mother notes", "by history", "per patient", interview
   answers); "suspected" for "suspected", "possible", "probable", "presumed", "presumptive", "likely",
   "features of", "concern for", "rule out", "cannot exclude", "under work-up". A cue applies only to what it
   qualifies: "idiopathic nephrotic syndrome, presumed minimal change disease" = nephrotic syndrome confirmed
   AND minimal change disease suspected; "acute pancreatitis, likely alcohol-related" = pancreatitis confirmed.
   Likewise a denial covers only what follows it: "Mild eye involvement without active orbitopathy" = eye
   involvement true AND active orbitopathy false.
5. subject: "family" when the fact is about a relative ("Father T2DM", "mother had breast cancer at 45"),
   else "patient". A relative's opinion or experience that is not their medical history is not a family fact.
6. status:
   - "observed": a measurement, test result or exam finding
   - "current": an ongoing condition or a drug the patient is taking now
   - "past": a previous or resolved condition, a completed treatment, a past procedure
   - "stopped": a drug or treatment that was stopped (give the stop date in "date" if written)
   - "planned": a plan, recommendation, referral, an option discussed, "consider", "will start",
     "candidate for", "not yet started"
   - "declined": the patient refused
   Planned, discussed or declined treatments are NOT treatments received: give them concept
   "treatment_plan" with the drug or procedure in "term" and status "planned" or "declined".
   An order written in the note ("Start prednisolone 60 mg/m2/day.", "Started methotrexate") IS a treatment
   given from the document date: medication, status "current", start = the document date.
   Advice about a habit in a plan ("no smoking", "avoid alcohol", "smoking cessation advised", "alcohol program")
   says nothing about the patient's habit: treatment_plan with the advice in "term", status "planned", never
   smoking / alcohol / substance_use. "No smoking." in the social history is the patient's habit (smoking false).
   Occupation, living situation, guardian or caregiver, hobbies: social_history with the words in "term".
7. date: YYYY-MM-DD only when the unit itself dates the fact. "dx 2017" -> "2017-01-01"; "2026-09" ->
   "2026-09-01"; "09-16" -> that day in the document's year (the year before if that would be after the
   document date); "3 days ago" / "last night" -> counted back from the document date. Otherwise null, and
   the document date is used. Never a date after the judgment date. Masked dates like [**2101-3-4**] -> null.
   For an ongoing drug or condition "since 2019" give "date": null and "start": "2019-01-01".
8. quote: optional. When a unit holds several facts, give for each fact the exact substring of the unit that
   states it ("HbA1c 8.9%"). Copy characters exactly, including spaces and symbols; no "..."; omit the
   quote if unsure. The quote must be inside that unit's text.
9. hint: the rule layer's guess for the unit, with marks for non-defaults ("/suspected", "/family",
   "/planned") and the term in brackets. It is often wrong or incomplete; correct it freely. Check every
   "no", "not", "without", "never", "denies" in the unit: a hint that says true for a denied item is wrong.
10. Output only facts present in the text. Do not compute or infer values (no eGFR from creatinine, no age
    from a date of birth; code does that).

OUTPUT (keep it short: answer time grows with every token you write)
Only JSON, no prose:
{{"units": [{{"u": 3, "ok": true}}, {{"u": 12, "facts": [{{"concept": "...", "value": ...}}]}}], "drop": [5, 9]}}
- Every unit id of the request appears exactly once: in "units" or in "drop".
- {{"u": N, "ok": true}} whenever the hint's concept(s) and value(s) are right and the fact is the patient's,
  certainty confirmed, status observed or current. "ok" is the preferred, fastest answer: do not restate a
  correct hint as facts just to add a term, a quote or the document date.
- {{"u": N, "facts": [...]}} only when the hint is wrong or incomplete, or a field differs from its default
  (suspected / reported, family, past / stopped / planned / declined, a date of its own). In a fact OMIT every
  field that has its default: certainty "confirmed", subject "patient", status "observed", and unit / term /
  date / start / quote / comparator null.
- "drop": units that state no fact (headings, scheduling, boilerplate).
- Use plain ASCII spaces. Never write "..." inside a value, term or quote.

Judgment date (as_of): {as_of}

CONCEPT LIST (key | type | default unit | name)
{concepts}
"""

EXAMPLES = r"""
WORKED EXAMPLES (invented records; the format and the decisions are what matter)

Example A
Units:
u1 | X-D01, registration, 2026-08-02 | - | Female. | hint: sex=female
u2 | X-D01, registration, 2026-08-02 | - | DOB 1979-11-30. | hint: birth_date=1979-11-30
u3 | X-D01, registration, 2026-08-02 | - | Nationality: South Korea. | hint: nationality=South Korea
u4 | X-D01, registration, 2026-08-02 | - | Teacher. | hint: symptom_finding=true
u5 | X-D01, registration, 2026-08-02 | - | Signed: registration desk. | hint: -
Answer:
{"units": [{"u": 1, "ok": true}, {"u": 2, "ok": true}, {"u": 3, "ok": true}, {"u": 4, "ok": true}], "drop": [5]}
Note: u4 the hint is right (a finding about the patient); no need to restate it. u5 is boilerplate.

Example B
Units:
u10 | X-D03, lab_result, 2026-08-20 | labs | Hemoglobin 10.9 g/dL (12.0-16.0) L | hint: hemoglobin=10.9
   (sentence in X-D03: Platelets 98 x10^9/L, ANC 1.1 x10^9/L, creatinine 88 umol/L)
u11 | X-D03, lab_result, 2026-08-20 | labs | Platelets 98 x10^9/L | hint: platelet_count=98
u12 | X-D03, lab_result, 2026-08-20 | labs | ANC 1.1 x10^9/L | hint: anc=1.1
u13 | X-D03, lab_result, 2026-08-20 | labs | creatinine 88 umol/L | hint: creatinine=0.99
u14 | X-D03, lab_result, 2026-08-20 | labs | HBsAg non-reactive; anti-HCV reactive, HCV RNA not detected | hint: hepatitis_b=false
u15 | X-D03, lab_result, 2026-08-20 | labs | TSH <0.01 mIU/L (0.4-4.0) L | hint: tsh=0.01
u16 | X-D03, lab_result, 2026-08-20 | labs | Urine dipstick protein 2+, blood negative | hint: lab_other=true
u17 | X-D03, lab_result, 2026-08-20 | labs | Urine protein/creatinine ratio 0.4 mg/mg | hint: creatinine=0.4
Answer:
{"units": [{"u": 10, "ok": true}, {"u": 11, "ok": true}, {"u": 12, "ok": true},
 {"u": 13, "facts": [{"concept": "creatinine", "value": 88, "unit": "umol/L"}]},
 {"u": 14, "facts": [{"concept": "hepatitis_b", "value": false, "term": "HBsAg non-reactive", "quote": "HBsAg non-reactive"},
   {"concept": "hepatitis_c", "value": true, "term": "anti-HCV reactive", "quote": "anti-HCV reactive"},
   {"concept": "hepatitis_c", "value": false, "term": "HCV RNA not detected", "quote": "HCV RNA not detected"}]},
 {"u": 15, "facts": [{"concept": "tsh", "value": 0.01, "unit": "mIU/L", "comparator": "<"}]},
 {"u": 16, "facts": [{"concept": "lab_other", "value": "2+", "term": "urine dipstick protein", "quote": "Urine dipstick protein 2+"},
   {"concept": "lab_other", "value": "negative", "term": "urine dipstick blood", "quote": "blood negative"}]},
 {"u": 17, "facts": [{"concept": "urine_protein_creatinine_ratio", "value": 0.4, "unit": "mg/mg"}]}], "drop": []}
Notes: u13 the hint had converted the unit; give the value as written. u17 the hint was wrong: a ratio is not the
serum creatinine. u14 one unit, three facts, each with its own quote.

Example C
Units:
u20 | X-D05, clinic_note, 2026-09-10 | narrative | 52-year-old woman with seropositive RA since 2015, on methotrexate 20 mg weekly since 2016 | hint: age=52; sex=female; diagnosis=true
u21 | X-D05, clinic_note, 2026-09-10 | narrative | Hydroxychloroquine stopped in 2024 because of rash. | hint: medication=true
u22 | X-D05, clinic_note, 2026-09-10 | narrative | Possible early interstitial lung disease on CT, under work-up. | hint: diagnosis=true
u23 | X-D05, clinic_note, 2026-09-10 | pmh | No other cardiac, pulmonary, renal or neurologic history. No prior malignancy. | hint: diagnosis=false
u24 | X-D05, clinic_note, 2026-09-10 | family | Mother breast cancer at 61; brother psoriasis. | hint: diagnosis=true
u25 | X-D05, clinic_note, 2026-09-10 | social | Never smoker. Alcohol none. | hint: smoking=false; alcohol=false
u26 | X-D05, clinic_note, 2026-09-10 | allergy | NKDA. | hint: allergy=false
u27 | X-D05, clinic_note, 2026-09-10 | plan | Options discussed: add a TNF inhibitor vs switch to JAK inhibitor; patient prefers to wait. | hint: treatment_plan=true
u28 | X-D05, clinic_note, 2026-09-10 | plan | Follow-up in 6 weeks with labs. | hint: symptom_finding=true
u29 | X-D05, clinic_note, 2026-09-10 | narrative | She declined tocilizumab last year. | hint: treatment_plan=true
u30 | X-D05, clinic_note, 2026-09-10 | narrative | Reports morning stiffness for about 2 hours since 3 weeks ago. | hint: symptom_finding=true
u31 | X-D05, clinic_note, 2026-09-10 | exam | DAS28-CRP 5.4; TJC 8, SJC 6. | hint: symptom_finding=true
u32 | X-D05, clinic_note, 2026-09-10 | narrative | ECOG 1. LMP 2 weeks ago; urine hCG negative today. | hint: ecog=1; pregnancy=false
Answer:
{"units": [
 {"u": 20, "facts": [{"concept": "age", "value": 52, "unit": "years", "quote": "52-year-old"},
   {"concept": "sex", "value": "female", "quote": "woman"},
   {"concept": "diagnosis", "value": true, "term": "seropositive rheumatoid arthritis", "status": "current", "start": "2015-01-01", "quote": "seropositive RA since 2015"},
   {"concept": "medication", "value": true, "term": "methotrexate 20 mg weekly", "status": "current", "start": "2016-01-01", "quote": "on methotrexate 20 mg weekly since 2016"}]},
 {"u": 21, "facts": [{"concept": "medication", "value": true, "term": "hydroxychloroquine", "status": "stopped", "date": "2024-01-01"}]},
 {"u": 22, "facts": [{"concept": "diagnosis", "value": true, "term": "interstitial lung disease", "certainty": "suspected", "status": "current"}]},
 {"u": 23, "facts": [{"concept": "diagnosis", "value": false, "term": "other cardiac history", "status": "past"},
   {"concept": "diagnosis", "value": false, "term": "other pulmonary history", "status": "past"},
   {"concept": "diagnosis", "value": false, "term": "other renal history", "status": "past"},
   {"concept": "diagnosis", "value": false, "term": "other neurologic history", "status": "past"},
   {"concept": "diagnosis", "value": false, "term": "prior malignancy", "status": "past", "quote": "No prior malignancy."}]},
 {"u": 24, "facts": [{"concept": "diagnosis", "value": true, "term": "breast cancer at 61", "certainty": "reported", "subject": "family", "status": "past", "quote": "Mother breast cancer at 61"},
   {"concept": "diagnosis", "value": true, "term": "psoriasis", "certainty": "reported", "subject": "family", "status": "current", "quote": "brother psoriasis"}]},
 {"u": 25, "facts": [{"concept": "smoking", "value": false, "certainty": "reported", "status": "past", "quote": "Never smoker."},
   {"concept": "alcohol", "value": false, "certainty": "reported", "status": "current", "quote": "Alcohol none."}]},
 {"u": 26, "facts": [{"concept": "allergy", "value": false, "term": "no known drug allergies", "status": "current"}]},
 {"u": 27, "facts": [{"concept": "treatment_plan", "value": true, "term": "TNF inhibitor", "status": "planned"},
   {"concept": "treatment_plan", "value": true, "term": "JAK inhibitor", "status": "planned"}]},
 {"u": 29, "facts": [{"concept": "treatment_plan", "value": true, "term": "tocilizumab", "status": "declined", "date": "2025-01-01"}]},
 {"u": 30, "facts": [{"concept": "symptom_finding", "value": true, "term": "morning stiffness about 2 hours", "certainty": "reported", "status": "current", "start": "2026-08-20"}]},
 {"u": 31, "facts": [{"concept": "symptom_finding", "value": "5.4", "term": "DAS28-CRP", "quote": "DAS28-CRP 5.4"},
   {"concept": "symptom_finding", "value": "8", "term": "tender joint count", "quote": "TJC 8"},
   {"concept": "symptom_finding", "value": "6", "term": "swollen joint count", "quote": "SJC 6"}]},
 {"u": 32, "facts": [{"concept": "ecog", "value": 1, "quote": "ECOG 1."},
   {"concept": "hcg", "value": "negative", "term": "urine hCG", "quote": "urine hCG negative today"},
   {"concept": "pregnancy", "value": false, "quote": "urine hCG negative today"}]}], "drop": [28]}
Notes: u28 is dropped (scheduling). u27 and u29 are not treatments received. u22 is suspected, not a diagnosis.
u23: one false fact per denied item; "No other ... history" denies only what it names. u24 is family history,
not the patient's. u30: "3 weeks ago" from 2026-09-10 gives the start 2026-08-20. u25 and u26 could not be "ok":
the hints miss certainty, status or term.

Example D
Units:
u40 | X-D07, clinic_note, 2026-09-28 | meds | Insulin glargine 20 units SC nightly, start 2026-09 | hint: medication=true
u41 | X-D07, clinic_note, 2026-09-28 | meds | Metformin 1000 mg PO BID, started 2019, STOPPED 2026-09-12 (AKI) | hint: medication=true
u42 | X-D07, clinic_note, 2026-09-28 | meds | Planned switch to oral semaglutide once eGFR recovers; not yet started | hint: treatment_plan=true
u43 | X-D07, clinic_note, 2026-09-28 | psh | Laparoscopic cholecystectomy 2012. No other surgery. | hint: procedure=true
u44 | X-D07, clinic_note, 2026-09-28 | narrative | Echocardiogram 2026-09: LVEF 45%, mild MR. | hint: lvef=45
u45 | X-D07, clinic_note, 2026-09-28 | narrative | Mother reports he snores; sleep study pending. | hint: symptom_finding=true
u46 | X-D07, clinic_note, 2026-09-28 | vitals | BP 148/92, HR 88, T 36.9 C, SpO2 97% RA. | hint: blood_pressure=148/92; heart_rate=88; body_temperature=36.9
u47 | X-D07, clinic_note, 2026-09-28 | narrative | Ex-smoker, 30 pack-years, quit 2015. | hint: smoking=true
Answer:
{"units": [
 {"u": 40, "facts": [{"concept": "medication", "value": true, "term": "insulin glargine 20 units nightly", "status": "current", "start": "2026-09-01"}]},
 {"u": 41, "facts": [{"concept": "medication", "value": true, "term": "metformin 1000 mg BID", "status": "stopped", "date": "2026-09-12", "start": "2019-01-01"}]},
 {"u": 42, "facts": [{"concept": "treatment_plan", "value": true, "term": "oral semaglutide", "status": "planned"}]},
 {"u": 43, "facts": [{"concept": "procedure", "value": true, "term": "laparoscopic cholecystectomy", "status": "past", "date": "2012-01-01", "quote": "Laparoscopic cholecystectomy 2012."},
   {"concept": "procedure", "value": false, "term": "other surgery", "status": "past", "quote": "No other surgery."}]},
 {"u": 44, "facts": [{"concept": "lvef", "value": 45, "unit": "%", "date": "2026-09-01", "quote": "LVEF 45%"},
   {"concept": "symptom_finding", "value": true, "term": "mild mitral regurgitation", "date": "2026-09-01", "quote": "mild MR"}]},
 {"u": 45, "facts": [{"concept": "symptom_finding", "value": true, "term": "snoring", "certainty": "reported", "status": "current", "quote": "Mother reports he snores"}]},
 {"u": 46, "facts": [{"concept": "blood_pressure", "value": "148/92", "unit": "mmHg", "quote": "BP 148/92"},
   {"concept": "heart_rate", "value": 88, "quote": "HR 88"},
   {"concept": "body_temperature", "value": 36.9, "unit": "C", "quote": "T 36.9 C"},
   {"concept": "spo2", "value": 97, "unit": "%", "quote": "SpO2 97% RA"}]},
 {"u": 47, "facts": [{"concept": "smoking", "value": true, "term": "ex-smoker, 30 pack-years", "status": "past", "date": "2015-01-01"}]}], "drop": []}
Notes: u45 is about the patient (the mother only reports it), so subject stays "patient" (omitted) and certainty
is "reported"; the pending sleep study is not a fact. u41 was received and then stopped. u46 could not be "ok": the
hint shows only three facts and the unit has four. u47: a past smoker is smoking true with status "past".

Example E
Units:
u50 | X-D09, clinic_note, 2026-09-30 | exam | Resp: no cough or dyspnea. | hint: symptom_finding=true[Resp: no cough or dyspnea.]
u51 | X-D09, clinic_note, 2026-09-30 | narrative | Echo: LVEF 60%, no evidence of pulmonary hypertension. | hint: lvef=60; diagnosis=false[hypertension]
u52 | X-D09, clinic_note, 2026-09-30 | plan | Imp: idiopathic nephrotic syndrome, presumed minimal change disease. | hint: diagnosis=true[idiopathic nephrotic syndrome]; diagnosis=true[minimal change disease]/suspected
u53 | X-D09, clinic_note, 2026-09-30 | plan | Start prednisolone 60 mg/m2/day. | hint: medication=true[prednisolone]
u54 | X-D09, clinic_note, 2026-09-30 | plan | Mild eye symptoms: lubricating drops, no smoking, reassess at each visit. | hint: treatment_plan=true[no smoking]/planned
Answer:
{"units": [
 {"u": 50, "facts": [{"concept": "symptom_finding", "value": false, "term": "cough"}, {"concept": "symptom_finding", "value": false, "term": "dyspnea"}]},
 {"u": 51, "ok": true},
 {"u": 52, "ok": true},
 {"u": 53, "facts": [{"concept": "medication", "value": true, "term": "prednisolone 60 mg/m2/day", "status": "current", "start": "2026-09-30"}]},
 {"u": 54, "facts": [{"concept": "symptom_finding", "value": true, "term": "mild eye symptoms", "status": "current"},
   {"concept": "treatment_plan", "value": true, "term": "lubricating drops", "status": "planned"},
   {"concept": "treatment_plan", "value": true, "term": "no smoking", "status": "planned"}]}], "drop": []}
Notes: u50 the hint said true for denied symptoms, so it cannot be "ok". u51 the hint already has the denial right.
u52 the hint is right, minimal change disease is only presumed. u53 is an order, so a treatment given, not a plan.
u54 "no smoking" is advice in the plan, not a statement that the patient does not smoke.
"""

REL_ALL = ""
REL_CRITERIA = ("\nAlso leave out facts that cannot bear on any of the candidate-trial criteria given below. "
                "When in doubt, keep the fact; a missing fact costs more than an extra one. Always keep, whatever "
                "the criteria say: living situation, caregiver or companion, occupation, adherence to treatment, "
                "daily function, counts of past episodes, admissions or exacerbations, treatments given during an "
                "admission, and tests that were sent or are pending.")

PATIENT_CRITERIA = """CANDIDATE-TRIAL CRITERIA (only to decide which facts are relevant; do not judge them)
{criteria}
"""

UNITS = """RECORD UNITS (id | document id, type, date | section | text | hint)
{units}

Return only the JSON answer."""


def static_part(as_of, concepts_text, relevance):
    rel = REL_CRITERIA if relevance == "criteria" else REL_ALL
    return INSTRUCTIONS.format(relevance_rule=rel, as_of=as_of, concepts=concepts_text) + EXAMPLES
