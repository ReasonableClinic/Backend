"""Code checks on every LLM judgment, before it reaches the Evidence Graph.

Each check can only make a judgment MORE cautious (PASS/FAIL -> UNKNOWN), never the reverse,
so the checks cannot create a new opposite-direction error. Every change is recorded in
`rule_tags` as `pc:<check>` so the error analysis can count them.
"""
import re

from .data import days_before
from .rules import FAMILY_RX, JUDGMENT_RX, default_action, window_days

# the model hedging in its own note while giving a definite status (prompt rule 17)
HEDGE_RX = re.compile(r"\barguable\b|\bdebatable\b|\bunclear\b|\buncertain\b|\bnot certain\b|\bambiguous\b|"
                      r"\bcannot (?:be )?(?:confirm|verif|determin|establish)|\bpartly settled\b|\bmay or may not\b|"
                      r"\bnot (?:fully|clearly|explicitly) (?:settled|established|documented|confirmed)\b", re.I)

STATUS = {"PASS", "FAIL", "UNKNOWN", "CONFLICT"}
REASONS = {"PASS": {"VALID"}, "FAIL": {"VIOLATED"}, "CONFLICT": {"CONFLICT"},
           "UNKNOWN": {"MISSING", "EXPIRED", "UNSUPPORTED"}}
ACTIONS = {"patient_question", "med_record_check", "lab_check", "med_history_check",
           "clinician_confirmation", "new_test", "none"}


def _downgrade(r, reason, check, action=None, keep_evidence=True):
    r["status"], r["reason"] = "UNKNOWN", reason
    if not keep_evidence or reason == "MISSING":
        r["evidence_ids"] = []
    r["action"] = action or r.get("action")
    r.setdefault("rule_tags", []).append("pc:" + check)


def normalise(r, crit):
    """Vocabulary and consistency (PASS -> VALID/none, UNKNOWN -> a reason and an action)."""
    st = str(r.get("status") or "").upper().strip()
    if st not in STATUS:
        r.setdefault("rule_tags", []).append("pc:bad_status:" + st)
        st = "UNKNOWN"
        r["reason"] = "MISSING"
    r["status"] = st
    reason = str(r.get("reason") or "").upper().strip()
    if reason not in REASONS[st]:
        reason = next(iter(REASONS[st])) if st != "UNKNOWN" else ("MISSING" if not r.get("evidence_ids") else "UNSUPPORTED")
    r["reason"] = reason
    act = r.get("action")
    if st in ("PASS", "FAIL"):
        r["action"] = "none"
    elif act not in ACTIONS or act == "none":
        r["action"] = default_action(crit["original_text"], bool(crit.get("administrative")))
    if r["reason"] == "MISSING":
        r["evidence_ids"] = []
    return r


DEFAULT_POLICY = {"list_inference": "strict", "blanket_negation": "off"}


def apply_policy(r, crit, policy):
    """Team rules still open (common format 10): list inference and blanket negation.

    strict / off (default) = the current dev gold: such PASS becomes UNKNOWN/MISSING, and the
    inference is kept in `derived_from` / `note` so Agent 5 knows which record to check.
    allow / on = the proposal in 6.3 (scored by the lenient columns of eval/score_dev.py).
    """
    if r["status"] != "PASS":
        return r
    tags = r.get("rule_tags", [])
    if "list_inference" in tags and policy.get("list_inference", "strict") == "strict":
        r["note"] = f"[inferable PASS from {r.get('derived_from') or 'a list'}] " + (r.get("note") or "")
        _downgrade(r, "MISSING", "strict_list_inference", "med_history_check")
    elif "normal_finding_inference" in tags and policy.get("list_inference", "strict") == "strict":
        # team rule A2 (strict): absence inferred from normal findings stays UNKNOWN; lenient scoring may allow it
        r["note"] = "[inferable PASS from normal findings] " + (r.get("note") or "")
        _downgrade(r, "MISSING", "strict_normal_finding_inference", "med_record_check")
    elif "blanket_negation" in tags and policy.get("blanket_negation", "off") == "off":
        r["note"] = "[blanket negation would give PASS] " + (r.get("note") or "")
        _downgrade(r, "MISSING", "blanket_off", "patient_question")
    return r


def check(r, crit, ds, patient_id, trial, policy=None):
    """Apply all checks to one LLM result in place and return it."""
    policy = policy or DEFAULT_POLICY
    r.setdefault("rule_tags", [])
    r["evidence_ids"] = [e for e in (r.get("evidence_ids") or []) if isinstance(e, str)]
    text = crit["original_text"]
    as_of = ds.as_of(patient_id)

    # 1. cited ids must exist and belong to this patient (Agent 4 re-reads them by span)
    valid = [e for e in r["evidence_ids"] if e in ds.evidence_by_id and ds.evidence_by_id[e]["patient_id"] == patient_id]
    if len(valid) != len(r["evidence_ids"]):
        r["rule_tags"].append("pc:dropped_unknown_ids")
    r["evidence_ids"] = valid
    normalise(r, crit)
    evs = [ds.evidence_by_id[e] for e in valid]
    st = r["status"]

    # 2. a decision with no evidence is an unsupported decision (Yesung: evidence-grounded)
    if st in ("PASS", "FAIL", "CONFLICT") and not evs:
        _downgrade(r, "MISSING", "no_evidence", default_action(text, bool(crit.get("administrative"))))
        return r

    if st in ("PASS", "FAIL") and evs:
        # 3. family history used for the patient's own condition
        if all(e["subject"] == "family" for e in evs) and not FAMILY_RX.search(text):
            _downgrade(r, "UNSUPPORTED", "family_only", "patient_question")
            return r
        # 4. plans / declined treatments counted as treatment received or as a habit
        if all(e["concept"] == "treatment_plan" or (e.get("detail") or {}).get("status") in ("planned", "declined")
               for e in evs) and not ("planned" in text.lower() or "plan to" in text.lower()):
            _downgrade(r, "UNSUPPORTED", "plan_only", "med_history_check")
            return r
        # 5. suspected diagnosis used as a diagnosis (inclusion PASS / exclusion FAIL)
        positive = (crit["type"] != "exclusion" and st == "PASS") or (crit["type"] == "exclusion" and st == "FAIL")
        if positive and all(e["certainty"] == "suspected" and e["value"] is not False for e in evs):
            _downgrade(r, "UNSUPPORTED", "suspected_only", "med_record_check")
            return r
        # 6. judgment wording: FAIL only with the documented degree
        if st == "FAIL" and JUDGMENT_RX.search(text) and not r.get("severity_documented"):
            _downgrade(r, "UNSUPPORTED", "judgment_term", "clinician_confirmation")
            return r
        # 6b. a definite status with a hedged explanation ("arguable", "unclear") is not definite (rule 17)
        if HEDGE_RX.search(r.get("note") or ""):
            _downgrade(r, "UNSUPPORTED", "hedged_note", "clinician_confirmation")
            return r
        # 7. measurement older than the criterion's own window -> EXPIRED
        win = window_days(text)
        dated = [e for e in evs if e["value_type"] == "numeric" and e["concept"] not in ("age",)
                 and days_before(as_of, e.get("observed_date")) is not None]
        if win and dated and len(dated) == len(evs) and all(days_before(as_of, e["observed_date"]) > win for e in dated):
            _downgrade(r, "EXPIRED", "outside_window", "lab_check")
            return r

    # 8. list inference must name its list (memo 2.4); open team rules
    if st == "PASS" and "list_inference" in r["rule_tags"] and not r.get("derived_from"):
        r["rule_tags"].append("pc:inference_without_source")
    apply_policy(r, crit, policy)

    # 9. opposite facts among the cited evidence -> flag for the Verifier (not changed here)
    vals = {}
    for e in evs:
        if isinstance(e["value"], bool) and e["subject"] == "patient":
            vals.setdefault((e["concept"], (e.get("term") or "").lower()), set()).add(e["value"])
    if any(len(v) > 1 for v in vals.values()) and st != "CONFLICT":
        r["rule_tags"].append("flag:possible_conflict")
    return r
