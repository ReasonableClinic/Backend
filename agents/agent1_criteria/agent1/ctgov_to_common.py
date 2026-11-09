#!/usr/bin/env python3
"""ClinicalTrials.gov API v2 response -> common format v0.4 (⓪ Trial + ①-a Criterion).

Reference converter for the CT.gov owner. Takes a saved search response
({"studies": [...]}) or a single study ({"protocolSection": ...}).

Usage:
  python3 ctgov_to_common.py response.json [more.json ...] \
      --trials trials.jsonl --criteria criteria.jsonl [--only NCT1,NCT2] [--drop-flagged]

Prints one screening line per study:
  KEEP / DROP  nctId  flags
Flags (rules from ctgov_request.md):
  not_interventional, purpose:<X>   hard drop with --drop-flagged
  stale_status                      statusVerifiedDate older than 12 months (kept, ranked lower)
  incomplete_criteria               "Key ... criteria" or "other protocol-defined criteria"
  kr_site                           at least one Korean site recruiting / not yet recruiting (info)
"""
import argparse, json, re, sys
from datetime import date

ACTIVE = {"RECRUITING", "NOT_YET_RECRUITING"}
HARD_DROP_PURPOSES = {"DIAGNOSTIC", "SCREENING"}
KOREA = {"South Korea", "Korea, Republic of"}  # API v2 uses "South Korea"

# ---------------------------------------------------------------- ⓪ Trial

UNIT_YEARS = {"year": 1.0, "month": 1 / 12, "week": 7 / 365.25, "day": 1 / 365.25, "hour": 1 / 8766, "minute": 1 / 525960}


def age_years(s):
    """'18 Years' -> 18, '6 Months' -> 0.5, None -> None."""
    if not s:
        return None
    m = re.match(r"\s*([\d.]+)\s*([A-Za-z]+)", s)
    if not m:
        return None
    n, unit = float(m.group(1)), m.group(2).lower().rstrip("s")
    v = round(n * UNIT_YEARS.get(unit, 1.0), 3)
    return int(v) if v == int(v) else v


INCOMPLETE = re.compile(r"\bkey\s+(inclusion|exclusion|eligibility)\b|other\s+protocol[- ]defined|"
                        r"additional\s+(inclusion|exclusion|eligibility\s+)?criteria\s+(may\s+)?apply", re.I)


def to_trial(study, fetched_at):
    p = study["protocolSection"]
    ident, status, design = p["identificationModule"], p.get("statusModule", {}), p.get("designModule", {})
    elig, cond = p.get("eligibilityModule", {}), p.get("conditionsModule", {})
    arms_mod = p.get("armsInterventionsModule", {})
    overall = status.get("overallStatus")
    sites = []
    for loc in p.get("contactsLocationsModule", {}).get("locations", []):  # contacts deliberately dropped
        sites.append({"facility": loc.get("facility"), "city": loc.get("city"),
                      "country": loc.get("country"), "status": loc.get("status")})
    countries = []
    for s in sites:
        active = s["status"] in ACTIVE if s["status"] else overall in ACTIVE
        if active and s["country"] and s["country"] not in countries:
            countries.append(s["country"])
    text = elig.get("eligibilityCriteria", "")
    mesh = [m.get("term") for m in study.get("derivedSection", {}).get("conditionBrowseModule", {}).get("meshes", [])]
    return {
        "trial_id": ident["nctId"],
        "title": ident.get("briefTitle"),
        "overall_status": overall,
        "status_verified": status.get("statusVerifiedDate"),
        "study_type": design.get("studyType"),
        "primary_purpose": design.get("designInfo", {}).get("primaryPurpose"),
        "phases": design.get("phases", []),
        "conditions": cond.get("conditions", []),
        "condition_mesh": mesh,
        "min_age": age_years(elig.get("minimumAge")),
        "max_age": age_years(elig.get("maximumAge")),
        "sex": elig.get("sex", "ALL"),
        "healthy_volunteers": elig.get("healthyVolunteers", False),
        "allocation": design.get("designInfo", {}).get("allocation"),
        "arms": [{"label": a.get("label"), "type": a.get("type"), "interventions": a.get("interventionNames", [])}
                 for a in arms_mod.get("armGroups", [])],
        "countries": countries,
        "sites": sites,
        "brief_summary": p.get("descriptionModule", {}).get("briefSummary"),
        "eligibility_text": text,
        "criteria_complete": not INCOMPLETE.search(text),
        "fetched_at": fetched_at,
    }


def screen(t, today):
    flags = []
    if t["study_type"] != "INTERVENTIONAL":
        flags.append("not_interventional")
    if t["primary_purpose"] and t["primary_purpose"] != "TREATMENT":
        flags.append(f"purpose:{t['primary_purpose']}")
    v = t["status_verified"]
    if v:
        y, m = int(v[:4]), int(v[5:7]) if len(v) >= 7 else 1
        if (today.year - y) * 12 + today.month - m > 12:
            flags.append("stale_status")
    if not t["criteria_complete"]:
        flags.append("incomplete_criteria")
    if any(s["country"] in KOREA and (s["status"] in ACTIVE if s["status"] else t["overall_status"] in ACTIVE)
           for s in t["sites"]):
        flags.append("kr_site")
    hard = "not_interventional" in flags or any(f.split(":")[-1] in HARD_DROP_PURPOSES for f in flags)
    return flags, hard

# ---------------------------------------------------------------- ①-a Criterion

SUP = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")


def clean(s):
    s = re.sub(r"\\([<>*_\[\]()#+\-.!~|=^])", r"\1", s)          # markdown escapes
    s = s.replace("≥", ">=").replace("≤", "<=").replace("＞", ">").replace("＜", "<")
    s = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m: "^" + m.group(0).translate(SUP), s)
    s = s.replace("**", "").replace("__", "")
    return re.sub(r"\s+", " ", s).strip()


BULLET = re.compile(r"^(\s*)([*\-•+]|\d{1,2}[.)]|[a-zA-Z][.)]|[ivxIVX]{1,4}[.)]|\(\w{1,4}\))(?:\s+|(?<=[.)])(?=[A-Za-z≥≤<>]))(.*)$")
HEADER = re.compile(r"^\W*(key\s+|main\s+|general\s+)?(inclusion|exclusion)(\s+criteria)?\b[^:]{0,40}:?\W*$", re.I)
COHORT_HINT = re.compile(r"^(for|in|part|cohort|arm|phase|stage|module|dose|only|participants|patients)\b|\bonly\b|\bcohort\b|\bpart [a-z0-9]\b", re.I)
def is_cohort(t):
    """'For participants in Korea:' / 'Part 2 Dose Expansion:' yes; '... one of the following:' no (that is a parent)."""
    return (len(t) < 100 and COHORT_HINT.search(re.sub(r"^[-*•\s]+", "", t)) is not None
            and not re.search(r"\b(following|include|includes|as below|ineligible|eligible|excluded)\b", t, re.I))


INLINE_NUM = re.compile(r"(?:(?<=^)|(?<=\s))(\d{1,2})\.(?=\s?[A-Za-z≥≤<>(])")


def split_inline_numbers(line):
    """'1.Sign ... 2. >=18 years 3.Histologically ...' -> separate lines, only if numbers run consecutively."""
    ms = list(INLINE_NUM.finditer(line))
    chain = []
    for m in ms:
        n = int(m.group(1))
        if not chain or n == int(chain[-1].group(1)) + 1:
            chain.append(m)
    if len(chain) < 2:
        return [line]
    indent = re.match(r"\s*", line).group(0)
    parts, prev = [], 0
    for m in chain:
        if line[prev:m.start()].strip():
            parts.append(indent + line[prev:m.start()].strip())
        prev = m.start()
    parts.append(indent + line[prev:].strip())
    return parts


def marker_kind(m):
    return "num" if m[0].isdigit() else "alpha" if m[0].isalpha() or m.startswith("(") else "sym"


CRITERION_WORDS = re.compile(r">=|<=|[<>]|\b(must|have|has|had|history|prior|previous|within|no|not|known|able|adequate|"
                             r"age|aged|years|ecog|signed|willing|measurable|life expectancy)\b", re.I)


def merge_option_lists(items):
    """A cohort heading followed by >=3 short numbered entries like 'Ovarian cancer' is a list of
    alternatives (eligible tumour types), not separate AND criteria: merge it into one item."""
    out, i = [], 0
    while i < len(items):
        j = i
        while (j < len(items) and items[j]["cohort"] and items[j]["cohort"] == items[i]["cohort"]
               and items[j]["type"] == items[i]["type"] and items[j]["kind"] == "num"
               and len(clean(items[j]["text"])) < 120 and not CRITERION_WORDS.search(clean(items[j]["text"]))):
            j += 1
        if j - i >= 3:
            m = dict(items[i])
            m["text"] = "One of: " + " | ".join(clean(x["text"]) for x in items[i:j])
            out.append(m)
            i = j
        else:
            out.append(items[i])
            i += 1
    return out


def split_criteria(trial_id, text):
    """Rule-based ①-a split.
    - Sub-bullets (deeper indent, or a different marker kind under a parent ending with ':') merge into the parent.
    - A numbered bullet that continues the top-level numbering is top level whatever its indent.
    - 'For participants in Korea:'-style lines set `cohort`; 'Exclusion Criteria due to ...:' group headings do not.
    - Inline '1.xxx 2.yyy' runs are split first."""
    items, ctype, cohort = [], "unknown", None
    cur = None                      # {"type","cohort","text","indent","kind","num"}
    last_num = None

    def flush():
        nonlocal cur
        t = clean(cur["text"]) if cur else ""
        if cur and re.search(r"[A-Za-z0-9]", t) and not (t.endswith(":") and len(t) < 40):  # bare 'Reproduction:' label
            items.append(cur)
        cur = None

    def start(body, indent, kind, num):
        nonlocal cur, last_num
        flush()
        cur = {"type": ctype, "cohort": cohort, "text": body, "indent": indent, "kind": kind}
        if kind == "num":
            last_num = num

    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.strip():
            raw = re.sub(r"^(\s*)\\([-*+])", r"\1\2", raw)    # '\- item' is an escaped bullet
            lines.extend(split_inline_numbers(raw.rstrip()))

    for line in lines:
        plain = clean(line)
        h = HEADER.match(plain.replace("*", "").strip())
        if h and len(plain) < 70:
            flush()
            ctype, cohort, last_num = h.group(2).lower(), None, None
            continue
        b = BULLET.match(line)
        if b:
            indent, marker, body = len(b.group(1).expandtabs(4)), b.group(2), b.group(3)
            kind = marker_kind(marker)
            num = int(re.match(r"\d+", marker).group(0)) if kind == "num" else None
            body_c = clean(body)
            if cur is None:
                child = False
            elif kind == "num" and last_num is not None and num == last_num + 1 and cur["kind"] == "num":
                child = False                                   # numbering continues: top level
            elif indent > cur["indent"]:
                child = True
            elif cur.get("open") and (kind != cur["kind"] or num == 1):
                child = True                                    # list under 'xxx as follows:'
            elif cur.get("child") == (kind, indent):
                child = True                                    # next sibling of an earlier child
            else:
                child = False
            if child:
                sep = " " if cur["text"].rstrip().endswith(":") else "; "
                cur["text"] = cur["text"].rstrip() + sep + body
                cur.setdefault("child", (kind, indent))
                continue
            if body_c.endswith(":") and is_cohort(body_c):
                flush()
                cohort, last_num = re.sub(r"^[-*•\s]+", "", body_c).rstrip(":").strip(), None
                continue
            start(body, indent, kind, num)
            if body_c.endswith(":"):
                cur["open"] = True
            continue
        if plain.endswith(":") and len(plain) < 120:          # free-standing sub-heading
            flush()
            if re.search(r"\bcriteri", plain, re.I):          # group heading inside a section
                t = re.search(r"\b(inclusion|exclusion)\b", plain, re.I)
                ctype = t.group(1).lower() if t else ctype
                cohort = None
            elif re.search(r"\b(ineligible|not eligible|excluded)\b", plain, re.I):
                ctype, cohort = "exclusion", None
            elif is_cohort(plain):
                cohort = re.sub(r"^[-*•\s]+", "", plain).rstrip(":").strip()
            else:                                              # parent text for the bullets below
                start(line.strip(), -1, "text", None)
                cur["open"] = True
            last_num = None if cur is None else last_num
            continue
        if cur is not None:                                    # wrapped continuation line
            cur["text"] += " " + line.strip()
        else:
            start(line.strip(), len(line) - len(line.lstrip()), "text", None)
    flush()

    items = merge_option_lists(items)
    out, counters = [], {"inclusion": 0, "exclusion": 0, "unknown": 0}
    for it in items:
        counters[it["type"]] += 1
        letter = {"inclusion": "I", "exclusion": "E", "unknown": "U"}[it["type"]]
        out.append({"trial_id": trial_id, "criterion_id": f"{trial_id}-{letter}{counters[it['type']]:02d}",
                    "type": it["type"], "original_text": clean(it["text"]), "cohort": it["cohort"],
                    "parse_status": "split_only", "concept": None, "operator": None, "value": None, "unit": None,
                    "time_window": None, "logic_group": None, "answerable_by": None})
    return out

# ---------------------------------------------------------------- main


def load_studies(path):
    d = json.load(open(path, encoding="utf-8"))
    return d["studies"] if "studies" in d else [d]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("responses", nargs="+")
    ap.add_argument("--trials", default="trials.jsonl")
    ap.add_argument("--criteria", default="criteria.jsonl")
    ap.add_argument("--only", help="comma-separated NCT ids to keep")
    ap.add_argument("--drop-flagged", action="store_true", help="skip not_interventional / DIAGNOSTIC / SCREENING")
    ap.add_argument("--fetched-at", default=date.today().isoformat())
    a = ap.parse_args()
    only = set(a.only.split(",")) if a.only else None
    today = date.fromisoformat(a.fetched_at)

    trials, crits, seen = [], [], set()
    for path in a.responses:
        for st in load_studies(path):
            t = to_trial(st, a.fetched_at)
            if t["trial_id"] in seen or (only and t["trial_id"] not in only):
                continue
            seen.add(t["trial_id"])
            flags, hard = screen(t, today)
            c = split_criteria(t["trial_id"], t["eligibility_text"])
            drop = hard and a.drop_flagged
            ni, ne = sum(x["type"] == "inclusion" for x in c), sum(x["type"] == "exclusion" for x in c)
            print(f"{'DROP' if drop else 'KEEP'}  {t['trial_id']}  I{ni:>2} E{ne:>2}  {','.join(flags) or '-'}  {t['title'][:60]}")
            if drop:
                continue
            trials.append(t)
            crits.extend(c)
    with open(a.trials, "w", encoding="utf-8") as f:
        for t in trials:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    with open(a.criteria, "w", encoding="utf-8") as f:
        for c in crits:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"{len(trials)} trials -> {a.trials}, {len(crits)} criteria -> {a.criteria}")
    n_unknown = sum(c["type"] == "unknown" for c in crits)
    if n_unknown:
        print(f"note: {n_unknown} criteria with type 'unknown' (no Inclusion/Exclusion header found) - check by hand")


if __name__ == "__main__":
    main()
