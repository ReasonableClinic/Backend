"""Review flags: how far to trust an Agent 3/4 decision. They never change the ranking (common format 6.4 stays as is);
they are shown in the clinician briefing and stop the patient briefing from sounding settled.

  llm_missing   judged_by == "pc:llm_missing": the LLM gave no answer, the UNKNOWN/MISSING is a placeholder.
                The trial is "판정 미완료" in both briefings, even when its label is eligible.
  note_negates  inclusion criterion left UNKNOWN while its note records the *absence* of what the criterion needs
                ("hallucinations denied", "statin only planned", "below the threshold"). Likely FAIL that Agent 4
                should look at ("노트-상태 일치" in the Agent 3 -> 4 handoff).
                dev a3-0.3.0 (base+variants): 31 flagged, gold FAIL 18 (precision 0.58), recall 18/47 inclusion
                UNKNOWN-vs-gold-FAIL. Catches NCT06159673 I03/I06/I08 and NCT06600412-I04 (7 of the 9 "extra trial"
                ranking misses). Low precision: clinician-only hint, never a verdict.
  fail_note_conflict  FAIL whose note itself mentions a conflict ("Note conflicts with 'no prior malignancy'").
                common format 6.3 says conflicting sources -> CONFLICT, not FAIL. dev: 2 flagged, both gold CONFLICT
                (SYN-7851 NCT07803965-E06; the 2 "gold trial left out" ranking misses are both single-FAIL trials).
  age_mismatch  patient age (age_at_as_of) outside the trial's min_age/max_age while the trial is still ranked.
                Hard guard from the idea doc (소아 가드레일): should never happen; if it does, Agent 3 missed the age rule.
Near-miss (rank.near_miss): ineligible trials with exactly one FAIL. Clinician briefing only: a single FAIL is where an
upstream error costs a whole trial (dev: 33 such trials, 2 of them gold potential = both left-out ranking misses).

PLANNED CHANGE: these flags are Agent 6's own heuristics standing in for verification that belongs to Agent 4. Once
Agent 4 output exists (its r2+ decision rounds and verification results in the graph), review.py will DISPLAY Agent 4's
findings instead of computing note_negates / fail_note_conflict itself; llm_missing, age_mismatch and near-miss stay as
display of facts already in the graph. Until then the flags remain clinician-only hints and never change the ranking.
"""
import re

NEGATES = re.compile(
    r"\b(denied|denies|negated|negative for|ruled out|not a current|only planned|planned only|shows none|lists none|"
    r"no history of|never (had|diagnosed)|not on (any|a|an)\b)|\bno (psychosis|psychotic|delusions?|hallucinations?)\b|"
    r"\b(below|under|do(es)? not (exceed|reach|meet))\b", re.I)
CONFLICT_NOTE = re.compile(r"conflict|contradict|discrepan|inconsisten", re.I)
SKIP = re.compile(r"^\s*\[inferable PASS|header line only", re.I)

FLAG_KO = {"llm_missing": "판정 미완료 (LLM 응답 없음)", "note_negates": "재확인 권장: 노트는 해당 조건이 없다고 적었는데 판정은 미확인",
           "fail_note_conflict": "재확인 권장: 노트가 기록 충돌을 언급하는데 판정은 FAIL (공통 형식상 충돌은 CONFLICT)",
           "age_mismatch": "나이 확인 필요: 환자 나이가 시험 나이 범위 밖"}


def criterion_flags(c):
    """c: a criterion row from agent3_out.jsonl or a decision node from the graph (same field names)."""
    out = []
    if c.get("judged_by") == "pc:llm_missing":
        out.append("llm_missing")
    cid = c.get("criterion_id", "")
    note = c.get("note") or ""
    if (c.get("applicable", True) and c.get("status") == "UNKNOWN" and "-I" in cid
            and not SKIP.search(note) and NEGATES.search(note)):
        out.append("note_negates")
    if c.get("applicable", True) and c.get("status") == "FAIL" and CONFLICT_NOTE.search(note):
        out.append("fail_note_conflict")
    return out


def patient_age_from_rows(rows):
    for r in rows:
        for c in r.get("criteria", []):
            calc = c.get("calc") or {}
            if calc.get("name") == "age_at_as_of" and calc.get("value") is not None:
                return calc["value"]
    return None


def age_outside(age, trial):
    if age is None:
        return False
    lo, hi = trial.get("min_age"), trial.get("max_age")
    return (lo is not None and age < lo) or (hi is not None and age >= hi + 1)


def near_miss(rows):
    """ineligible trials whose only FAIL is one criterion: [{trial_id, criterion_id, flags}]"""
    out = []
    for r in rows:
        if r.get("trial_label") != "ineligible":
            continue
        fails = [c for c in r["criteria"] if c.get("applicable", True) and c["status"] == "FAIL"]
        if len(fails) == 1:
            out.append({"trial_id": r["trial_id"], "criterion_id": fails[0]["criterion_id"], "flags": criterion_flags(fails[0])})
    return sorted(out, key=lambda x: (not x["flags"], x["trial_id"]))


def row_flags(row):
    """[{criterion_id, flag}] for one patient-trial row."""
    return [{"criterion_id": c["criterion_id"], "flag": f} for c in row["criteria"] for f in criterion_flags(c)]
