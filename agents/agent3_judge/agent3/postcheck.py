"""Output normalisation for every LLM judgment (Agent 3 v3).

Agent 3 v3 does NOT verify its own judgments. The v2 post-checks that downgraded PASS/FAIL to
UNKNOWN (no cited evidence, family-history-only, plan-only, suspected-only, judgment wording,
hedged note, measurement outside the window, possible-conflict flag) were moved out of Agent 3 on
2026-10-25 (team decision: verification is Agent 4's job, see Notion "Agent 4 역할" checks 1-4).
The v2 code is kept for reference in handoff_agent4/postcheck_v2_reference.py and is not executed.

What stays here is Agent 3's own output contract:
- vocabulary (status / reason / action sets, PASS -> VALID/none, UNKNOWN -> a reason + an action)
- cited ids that do not exist in the evidence file are moved to `cited_ids_invalid` (the Evidence
  Graph needs resolvable ids); the status is NOT changed - Agent 4 check 1 decides what that means
- the team policy switches (--blanket, --list-inference), which are judgment rules, not verification
"""
import re

from .rules import default_action

STATUS = {"PASS", "FAIL", "UNKNOWN", "CONFLICT"}
REASONS = {"PASS": {"VALID"}, "FAIL": {"VIOLATED"}, "CONFLICT": {"CONFLICT"},
           "UNKNOWN": {"MISSING", "EXPIRED", "UNSUPPORTED"}}
ACTIONS = {"patient_question", "med_record_check", "lab_check", "med_history_check",
           "clinician_confirmation", "new_test", "none"}
HISTORY_RX = re.compile(r"\bhistory\b|\bprior\b|\bprevious|\bknown\b|within \d+|within (?:the )?(?:past|last)|"
                        r"\bsurgery\b|\breceived\b", re.I)


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
    elif act == "patient_question" and crit.get("concept") in ("diagnosis", "procedure") \
            and HISTORY_RX.search(crit["original_text"]):
        # past diagnoses / procedures are looked up in the record before asking the patient (Agent 5 request
        # 2026-10-29; dev a3-0.3.0 outputs vs gold: base +13 / -8, variants +16 / -12 action matches)
        r["action"] = "med_history_check"
        r.setdefault("rule_tags", []).append("pc:action_history")
    if r["reason"] == "MISSING":
        r["evidence_ids"] = []
    return r


DEFAULT_POLICY = {"list_inference": "strict", "blanket_negation": "on"}


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
    elif "blanket_negation" in tags and _blanket_out_of_scope(crit):
        # team rule A1 (3차 회의, 합성 담당 동의): the organ-system blanket covers chronic disease HISTORY of that
        # system only - not lab values, acute events inside a window, drugs, procedures, infections or
        # investigator-judgment items. Such a PASS stays UNKNOWN/MISSING (same as --blanket off for that row).
        r["note"] = "[blanket negation out of A1 scope] " + (r.get("note") or "")
        _downgrade(r, "MISSING", "blanket_out_of_scope", "patient_question")
    return r


BLANKET_OUT_OF_SCOPE_RX = re.compile(
    # A1 exception list as written in the 3차 회의 decision (합성 담당 동의): the organ-system blanket does not
    # apply to lab values, acute events within a window, drugs, procedures, infections or investigator-judgment
    # items. Only those categories are encoded here; anything else is left to the gold owner (A1 scope queries).
    r"\bacute\b|\bcrisis\b|"                                   # acute events
    r"surgery|surgical|procedure|neurosurg|transplant|intervention|fracture|"   # procedures
    r"infection|sepsis|pneumonia|"                              # infections
    r"investigator|\bopinion\b|judg",                            # investigator judgment
    re.I)


def _blanket_out_of_scope(crit):
    if crit.get("parse_status") in ("numeric", "categorical") or crit.get("concept") == "medication":
        return True                                              # lab values, drugs
    return bool(BLANKET_OUT_OF_SCOPE_RX.search(crit["original_text"]))


def check(r, crit, ds, patient_id, trial, policy=None):
    """Normalise one LLM result in place and return it (no verification, see module docstring)."""
    policy = policy or DEFAULT_POLICY
    r.setdefault("rule_tags", [])
    cited = [e for e in (r.get("evidence_ids") or []) if isinstance(e, str)]
    # the model sometimes drops the patient prefix ("EV047" for "SYN-1791-EV047"); restore it only when that
    # id exists for this patient (a3-0.3.1, dev variants SYN-1791: 42 cited ids)
    full = [f"{patient_id}-{e}" if e not in ds.evidence_by_id and f"{patient_id}-{e}" in ds.evidence_by_id else e
            for e in cited]
    if full != cited:
        r["rule_tags"].append("pc:id_prefix_restored")
    cited = full
    valid = [e for e in cited if e in ds.evidence_by_id and ds.evidence_by_id[e]["patient_id"] == patient_id]
    if len(valid) != len(cited):
        r["cited_ids_invalid"] = [e for e in cited if e not in valid]
        r["rule_tags"].append("pc:dropped_unknown_ids")
    r["evidence_ids"] = valid
    normalise(r, crit)
    apply_policy(r, crit, policy)
    return r
