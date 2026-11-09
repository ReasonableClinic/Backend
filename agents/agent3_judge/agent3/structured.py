"""Code judgment of ①-b structured criteria (Agent 1 output) against Agent 2 evidence.

What code decides here, without reading meaning into the record:
  - numeric criteria (operator >=, <=, >, <, ==, between) on a specific concept key with a numeric
    evidence value: unit conversion with `alt_units`, x ULN with the lab's `ref_high`, the criterion's
    `time_window` (-> UNKNOWN/EXPIRED) and the default freshness rule of common format 6.3
  - categorical criteria (operator `in`) on a specific key: NYHA class, Child-Pugh class, ECOG, sex
  - `complex` lines (several independent conditions, one structured): decided only when the
    structured part alone settles the line (AND + violated, OR + met); otherwise the computation is
    returned as a hint for the LLM

Basket concepts (diagnosis, medication, ...) and `exists` / `not_exists` criteria stay with the LLM:
whether "prednisolone" is an "immunosuppressant" is a semantic judgment.
"""
import json
import math
import os
import re

from .data import days_before

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

NUMERIC_OPS = {">=", "<=", ">", "<", "==", "between"}
BASKETS = {"diagnosis", "medication", "procedure", "symptom_finding", "lab_other", "treatment_plan", "biomarker",
           "tumor_marker", "metastasis", "allergy", "social_history"}
EMIT_AS = {"tumor_marker": "biomarker"}         # Agent 2 writes these keys under another one (concepts_agent2.json)

ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
CHILD_PUGH_CLASS = [(5, 6, "A"), (7, 9, "B"), (10, 15, "C")]

# default freshness when the criterion has no window (common format 6.3: labs 30 days, imaging 90 days).
# a3-0.3.0 applied only the imaging rule because the dev gold seemed to accept older labs (eGFR at 35 d);
# that was candidate_evidence dating a new lab report by an older identical value (5차 회의, 2026-10-28).
# With the measurement date fixed (a3-0.3.1) the lab rule applies too.
DEFAULT_WINDOW = {"imaging_report": 90, "lab_result": 30}
IMAGING_CONCEPTS = {"lvef"}                     # imaging-derived values restated in notes
# a new report with the same value is a new measurement; any other document restates an earlier one
REPORT_DOCS = {"lab_result", "imaging_report", "pathology_report"}
# a report line that dates its value or compares with earlier results restates them
# ("Transaminases decreasing compared with 2026-09-21 (ALT 112, AST 87)", "eGFR trend 37 (04/2026) -> 38")
RESTATED_RX = re.compile(r"\b20\d\d-\d\d-\d\d\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b|\b\d{1,2}/20\d\d\b|compared|"
                         r"\bprevious|\bprior\b|\btrend|\bfrom\b|->|→", re.I)


def load_concepts(path=None):
    """Team concepts.json keyed by `key`."""
    path = path or os.path.join(HERE, "data", "dev", "reference", "concepts.json")
    with open(path, encoding="utf-8") as f:
        return {c["key"]: c for c in json.load(f)}


# ------------------------------------------------------------------ units
def _norm_unit(u):
    u = (u or "").strip().lower().replace(" ", "")
    u = u.replace("μ", "u").replace("µ", "u").replace("×", "x").replace("^", "")
    u = u.replace("%predicted", "%").replace("percent", "%")
    return u


def is_uln(u):
    return "uln" in _norm_unit(u)


def convert_threshold(value, crit_unit, concept):
    """Criterion threshold -> the concept's base unit (the unit Agent 2 writes evidence in).
    Returns (value, how) or (None, why) when the unit cannot be reconciled."""
    base = concept.get("unit")
    cu = _norm_unit(crit_unit)
    if not cu or cu == _norm_unit(base):
        return value, "same"
    alt = concept.get("alt_units") or {}
    for k, f in alt.items():
        if _norm_unit(k) == cu:
            return ([v * f for v in value] if isinstance(value, list) else value * f), f"x{f} ({crit_unit} -> {base})"
    if not base:
        return value, "no base unit; compared as written"
    return None, f"unit {crit_unit!r} not convertible to {base!r}"


def convert_evidence(e, concept):
    """Evidence value in the concept's base unit, or None when its unit is a different quantity."""
    base = concept.get("unit")
    eu = _norm_unit(e.get("unit"))
    if not base or not eu or eu == _norm_unit(base):
        return e["value"]
    for k, f in (concept.get("alt_units") or {}).items():
        if _norm_unit(k) == eu:
            return e["value"] * f
    return None


# ------------------------------------------------------------------ comparison
def _holds(op, v, ref):
    if op == "between":
        lo, hi = ref
        return lo <= v <= hi
    return {">=": v >= ref, "<=": v <= ref, ">": v > ref, "<": v < ref, "==": math.isclose(v, ref)}[op]


def holds(op, v, ref, comparator=None):
    """True / False, or None when the evidence is a bound ("<0.01") that does not settle the comparison."""
    if not comparator:
        return _holds(op, v, ref)
    big = 1e9
    lo, hi = (v, big) if comparator in (">", ">=") else (-big, v)
    a, b = _holds(op, lo, ref), _holds(op, hi, ref)
    return a if a == b else None


def _as_class(value, key):
    """Categorical value of the evidence as the criterion writes it (roman class, Child-Pugh letter)."""
    out = set()
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        n = int(value)
        out.add(str(n))
        for r, k in ROMAN.items():
            if k == n:
                out.add(r)
        if key == "child_pugh":
            for lo, hi, cls in CHILD_PUGH_CLASS:
                if lo <= n <= hi:
                    out.add(cls)
    elif isinstance(value, str):
        s = value.strip()
        out.add(s.lower())
        m = re.search(r"\b(class\s*)?([A-C]|I{1,3}|IV|V)\b", s)
        if m:
            out.add(m.group(2))
    return out


# qualifiers on how a value must be measured; code cannot see them in a number
QUALIFIER_RX = re.compile(r"\bfasting\b|\bseated\b|\bresting\b|\bsupine\b|\bstanding\b|mean of|average of|"
                          r"\b(?:two|three|2|3) (?:consecutive|separate|repeated)\b|on (?:two|three|2|3) occasions", re.I)


# ------------------------------------------------------------------ evidence
def candidate_evidence(crit, ds, patient_id, concepts):
    """Distinct measurements of the criterion's concept, newest first.

    Measurement date (common format 6.3, 5차 회의 2026-10-28): a clinic note often restates an older
    result with the note's own date ("LVEF 28%" in September for an echo done in February), so a
    line with the same value as an earlier one is a restatement and keeps the earlier date - unless
    it comes from a new report (lab / imaging / pathology), which is a new measurement of the same
    value (a report line that names another date or compares with earlier results is still a
    restatement). The evidence cited is the line that dates the measurement, which is what Agent 4
    should re-read."""
    key = EMIT_AS.get(crit["concept"], crit["concept"])
    concept = concepts.get(key, {"key": key})
    as_of = ds.as_of(patient_id)
    by_value = {}
    mine = [e for e in ds.evidence[patient_id]
            if e["concept"] == key and e.get("subject") == "patient" and not isinstance(e["value"], bool)
            and e.get("certainty") != "suspected"]
    for e in sorted(mine, key=lambda e: e.get("observed_date") or as_of):
        v = e["value"]
        vk = round(v, 6) if isinstance(v, (int, float)) else str(v).strip().lower()
        d = e.get("observed_date") or as_of
        cur = by_value.get(vk)
        new_report = e["source"]["doc_type"] in REPORT_DOCS and not RESTATED_RX.search(e["source"]["text"])
        if cur is None or (d > cur[0] and new_report):
            by_value[vk] = (d, e)
    out = sorted(by_value.values(), key=lambda t: t[0], reverse=True)
    return key, concept, [e for _, e in out]


def _action(concept, reason):
    t = concept.get("type")
    if t == "lab":
        return "lab_check"
    if t in ("measurement", "vital"):
        return "new_test"
    if t == "demographic":
        return "med_record_check"
    return "clinician_confirmation" if reason == "UNSUPPORTED" else "new_test"


def _result(crit, status, reason, evs, action, tags, note, calc):
    return {"criterion_id": crit["criterion_id"], "applicable": True, "status": status, "reason": reason,
            "evidence_ids": [e["evidence_id"] for e in evs], "action": action, "judged_by": "rule",
            "rule_tags": tags, "derived_from": None, "missing_fact": None, "note": note, "calc": calc}


def _finish(crit, met, evs, calc, tag):
    """Turn 'condition met?' into the criterion status; `complex` lines only when the part settles them."""
    excl = crit["type"] == "exclusion"
    status = ("FAIL" if met else "PASS") if excl else ("PASS" if met else "FAIL")
    if crit.get("complex"):
        # dev check (2026-10-23): settling a complex line from its structured part alone was wrong 3/13
        # times (nested AND inside an OR option; a value from the wrong period). Code only hints here.
        return None, {"part": calc, "met": met, "status_if_alone": status}
    reason = "VALID" if status == "PASS" else "VIOLATED"
    return _result(crit, status, reason, evs, "none", tag, calc.get("note", ""), calc), None


# ------------------------------------------------------------------ main entry
def judge_structured(crit, ds, patient_id, concepts, policy=None):
    """(result, hint). result: a judgment dict when code can decide; hint: the computation for the
    LLM when it cannot (complex line, bound value, unconvertible unit). Both None = nothing to say."""
    policy = policy or {}
    if crit.get("parse_status") != "structured" or not crit.get("concept") or crit.get("administrative"):
        return None, None
    op = crit.get("operator")
    if op not in NUMERIC_OPS and op != "in":
        return None, None
    if crit.get("change") or crit.get("value") is None:
        return None, None
    key = EMIT_AS.get(crit["concept"], crit["concept"])
    if key in BASKETS:
        return None, None
    tw = crit.get("time_window") or {}
    if tw.get("min_days_before") is not None and tw.get("max_days_before") is None:
        return None, None                       # washout-style window on a value: the LLM reads the sentence
    key, concept, evs = candidate_evidence(crit, ds, patient_id, concepts)
    as_of = ds.as_of(patient_id)
    tags = ["structured_" + ("numeric" if op in NUMERIC_OPS else "categorical")]
    calc = {"concept": key, "operator": op, "threshold": crit["value"], "unit": crit.get("unit")}

    if op == "in":
        evs = [e for e in evs if isinstance(e["value"], (int, float, str))]
        if not evs:
            # no value of this concept: the LLM may still decide from a neighbouring fact ("no cirrhosis"
            # for a Child-Pugh criterion; dev gold does this 11/24 times) -> hint only
            return None, {"part": dict(calc, note=f"no {key} value in the record"), "met": None, "status_if_alone": None}
        e = evs[0]
        allowed = {str(v).strip().lower() for v in crit["value"]} | {str(v).strip() for v in crit["value"]}
        have = _as_class(e["value"], key)
        met = bool(have & allowed) or bool({h.lower() for h in have} & allowed)
        calc.update(value=e["value"], observed_date=e.get("observed_date"), note=f"{key} = {e['value']} vs in {crit['value']}")
        return _finish(crit, met, [e], calc, tags)

    # ---- numeric
    evs = [e for e in evs if isinstance(e["value"], (int, float, str))]
    if not evs:
        return None, {"part": dict(calc, note=f"no {key} value in the record"), "met": None, "status_if_alone": None}
    qual = QUALIFIER_RX.search(crit["original_text"])
    e = evs[0]                                  # newest measurement, a number or a word ("not detected")
    db = days_before(as_of, e.get("observed_date"))
    calc.update(value=e["value"], value_unit=e.get("unit"), observed_date=e.get("observed_date"), days_before=db)

    # freshness: the criterion's own window, else the 6.3 default for labs / imaging. A pathology report
    # (tissue PD-L1, histology) describes the specimen, not the current state: no default window.
    win = tw.get("max_days_before")
    win_src = "criterion"
    if win is None and policy.get("default_window", True) and e["source"]["doc_type"] != "pathology_report":
        win = (DEFAULT_WINDOW.get(e["source"]["doc_type"]) or (90 if key in IMAGING_CONCEPTS else None)
               or (DEFAULT_WINDOW["lab_result"] if concept.get("type") == "lab" else None))
        win_src = "default_6.3"
    if win is not None and db is not None and db > win:
        calc.update(window_days=win, window_source=win_src, note=f"{key} = {e['value']} is {db} days old; window {win} days")
        if crit.get("complex") or qual:
            return None, {"part": calc, "met": None, "status_if_alone": "UNKNOWN/EXPIRED"}
        return _result(crit, "UNKNOWN", "EXPIRED", [e], _action(concept, "EXPIRED"), tags + ["expired_" + win_src],
                       calc["note"], calc), None
    if isinstance(e["value"], str):
        # newest result written as a word ("HBV DNA not detected", "negative"): never fall back to an
        # older number (Agent 2 guide, v14.12). The LLM decides from the word or leaves it UNKNOWN.
        calc["note"] = (f"newest {key} is the word {e['value']!r} ({e.get('observed_date') or 'no date'}, "
                        f"[{e['evidence_id']}]); older numeric values are not used")
        return None, {"part": calc, "met": None, "status_if_alone": None}

    # units
    if is_uln(crit.get("unit")):
        hi = (e.get("detail") or {}).get("ref_high")
        if not hi:
            calc["note"] = f"{key} = {e['value']} {e.get('unit') or ''}: criterion in x ULN but the lab line has no reference range"
            # the range may still be printed in the line text ("ALT 74 U/L (ref 7-55)"): the LLM reads it (rule 13)
            return None, {"part": calc, "met": None, "status_if_alone": "UNKNOWN/UNSUPPORTED"}
        v, ref = e["value"] / hi, crit["value"]
        calc.update(ref_high=hi, ratio=round(v, 3))
        how = f"{e['value']}/{hi} = {v:.2f} x ULN"
    else:
        ref, how = convert_threshold(crit["value"], crit.get("unit"), concept)
        if ref is None:
            calc["note"] = how
            return None, {"part": calc, "met": None, "status_if_alone": None}
        v = convert_evidence(e, concept)
        if v is None:
            calc["note"] = f"evidence unit {e.get('unit')!r} is not the concept unit {concept.get('unit')!r}"
            return None, {"part": calc, "met": None, "status_if_alone": None}
        if how != "same":
            calc["threshold_in_base_unit"] = ref
    comparator = (e.get("detail") or {}).get("comparator")
    met = holds(op, v, ref, comparator)
    calc["note"] = (f"{key} = {comparator or ''}{round(v, 4)} {concept.get('unit') or e.get('unit') or ''} "
                    f"({e.get('observed_date') or 'no date'}, -{db}d) vs {op} {ref}"
                    + (f" [{how}]" if how not in ("same",) else "")) + (" -> met" if met else " -> not met" if met is False else " -> undecided")
    if met is None:                                 # "<0.01" against a threshold it straddles
        return None, {"part": calc, "met": None, "status_if_alone": None}
    if qual and not QUALIFIER_RX.search(e["source"]["text"]):
        # "fasting LDL", "mean seated BP": the number alone does not show the measurement condition
        excl = crit["type"] == "exclusion"
        calc["note"] += f"; criterion requires '{qual.group(0)}', not visible on the evidence line"
        return None, {"part": calc, "met": met, "status_if_alone": ("FAIL" if met else "PASS") if excl else ("PASS" if met else "FAIL")}
    return _finish(crit, met, [e], calc, tags)


# ------------------------------------------------------------------ logic groups
def apply_logic_groups(results, crits):
    """①-b `logic_group` (several lines bound together; the CT.gov owner's dev v2 semantics):
      OR members: when any member is PASS the others are PASS too (6.3 option-list rule; gold NCT06110130-I04).
      parent ("... AND one of the following:"): own judgment AND the members' combined result.
    `results`: {criterion_id: result}, modified in place."""
    groups = {}
    for c in crits:
        lg = c.get("logic_group")
        if lg and lg.get("group_id"):
            groups.setdefault(lg["group_id"], {"relation": lg.get("relation", "OR"), "parent": None, "members": []})
            if lg.get("role") == "parent":
                groups[lg["group_id"]]["parent"] = c["criterion_id"]
            else:
                groups[lg["group_id"]]["members"].append(c["criterion_id"])
    for gid, g in groups.items():
        mem = [results[m] for m in g["members"] if m in results and results[m].get("applicable", True)]
        if not mem:
            continue
        st = [r["status"] for r in mem]
        if g["relation"] == "OR":
            passing = [r for r in mem if r["status"] == "PASS"]
            if passing:
                combined = "PASS"
                for r in mem:
                    if r["status"] != "PASS":
                        r["note"] = f"[OR group {gid}: {passing[0]['criterion_id']} is met] " + (r.get("note") or "")
                        r.update(status="PASS", reason="VALID", action="none",
                                 evidence_ids=list(passing[0]["evidence_ids"]))
                        r.setdefault("rule_tags", []).append("or_group_satisfied")
            elif all(s == "FAIL" for s in st):
                combined = "FAIL"
            else:
                combined = "UNKNOWN"
        else:                                       # AND
            combined = "FAIL" if "FAIL" in st else ("PASS" if all(s == "PASS" for s in st) else "UNKNOWN")
        p = results.get(g["parent"]) if g["parent"] else None
        if p is None:
            continue
        own = p["status"]
        if own == "FAIL" or combined == "FAIL":
            new = "FAIL"
        elif own == "PASS" and combined == "PASS":
            new = "PASS"
        elif own in ("UNKNOWN", "CONFLICT") and combined == "PASS" and "no_llm" in p.get("rule_tags", []):
            new = own                               # code-only run: parent's own condition was never judged
        else:
            new = "UNKNOWN"
        if new != own:
            p["note"] = f"[parent of group {gid}: own={own}, members={combined}] " + (p.get("note") or "")
            p.setdefault("rule_tags", []).append("logic_group_parent")
            if new == "PASS":
                p.update(status="PASS", reason="VALID", action="none")
            elif new == "FAIL":
                src = next((r for r in mem if r["status"] == "FAIL"), None)
                p.update(status="FAIL", reason="VIOLATED", action="none")
                if src and not p.get("evidence_ids"):
                    p["evidence_ids"] = list(src["evidence_ids"])
            else:
                p.update(status="UNKNOWN", reason="UNSUPPORTED" if p.get("evidence_ids") else "MISSING")
                if p["action"] == "none":
                    p["action"] = "med_record_check"
    return results
