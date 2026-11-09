"""Content check: does a linked sentence say what its nodes say? (README 6장 1번, the part check_grounding leaves out)

  python3 -m agent6.check_content runs/brief_dev --graphs G1 G2 --trials K/dev/reference/trials.jsonl [--strict]

For every sentence, against the nodes in its refs only (not the whole graph):
  number   every number in the text appears in a referenced node (value, threshold, text, trial record ...), or is a
           count the refs imply (how many decisions, per action / status / criterion type; open criteria of a
           referenced trial; Korean sites; months since status_verified). A trial:/label: ref licenses only the
           record fields a briefing uses (trial_fields: title, conditions, phases, ages, enrollment, interventions,
           primary outcomes, status_verified), not the eligibility text or summary. Rounding of a node value is accepted
           (68.668 -> 68, 69, 68.7). IDs (NCT, SYN-, I05, r1 ...) are removed first.
           Counts are typed by their unit: N곳 = sites / Korean sites, N개월 = months since status_verified,
           N명 = enrollment, N개·N가지·N건 = a count of the cited decisions (per action/status/type) or of a cited
           trial's open criteria.
  date     every date (2026-09-10, 2026.9.10, 2026년 9월 10일, 9월 10일, 2026년 9월) matches a date in a referenced node.
  quote    text inside "..." in a sentence citing src: nodes must be a verbatim substring of one of them.
  cancer   (patient audience) a cancer name while the patient's record has no confirmed malignant diagnosis.
  english  (patient) English outside parentheses that is not an allowed original or part of a glossary name (0.4.2).
  flag_claim (clinician, with --ranking) "재확인" for a trial without review flags (0.4.2).
  ev_uncited (patient audience) a cancer name allowed only by Agent 2 evidence outside the graph, without its ev: id.
  verdict  exclusion PASS said as "충족" (it means 제외 사유 없음); an UNKNOWN/CONFLICT-only sentence that sounds settled;
           a potential trial said "가능성이 높" (eligible wording).
Deterministic, no LLM. It catches invented or altered numbers/dates and flipped verdict words; it does not catch a
paraphrase that is wrong in other ways (that needs a second-model or human check).
"""
import argparse, glob, json, os, re, sys
from collections import Counter

from . import keyinfo as KI
from .graph import Graph
from .rank import kr_info, months_since, read_jsonl
from .glossary import ids as gloss_ids
from .keyinfo import has_confirmed_malignancy, names_cancer, outside_malignancy_refs
from .rules import FIXED

# Short ids use ASCII-only boundaries (a6-0.4.7): `\b` treats Hangul as a word character, so "E23에서" / "I03은" (id +
# Korean particle) were not seen as ids and their digits went to the number check (SYN-4657 LLM fallback).
_A, _Z = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
ID_RE = re.compile(r"NCT\d{8}(-[IE]\d+)?|\b[A-Z]{2,}(?:-\d+)+(?:-[A-Z]+\d+)?(?::\d+-\d+)?|" + _A + r"[IE]\d{2}" + _Z + "|"
                   + _A + r"r\d" + _Z + "|"
                   + _A + r"(?:EV|R)\d{3,}" + _Z + "|"     # evidence ids alone: haiku -EV001, rules-only -R001, 3+ digits
                   + _A + r"[A-Z]{1,3}\d{2,3}" + _Z)    # SYN-0019-EV025, SYN-0019-R001, TREC-2021-7-D01, TG-12-D01:0-71 ...
DATE_PATTERNS = [
    (re.compile(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})"), "ymd"),
    (re.compile(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일"), "ymd"),
    (re.compile(r"(\d{4})년\s*(\d{1,2})월"), "ym"),
    (re.compile(r"(\d{4})[-./](\d{1,2})(?![\d])"), "ym"),
    (re.compile(r"(?<!\d)(\d{1,2})월\s*(\d{1,2})일"), "md"),
]
NUM_RE = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?")
NODE_DATE = re.compile(r"(\d{4})-(\d{2})(?:-(\d{2}))?")
UNIT_RE = re.compile(r"\s*(개월|곳|명|개|가지|건)")
QUOTE_RE = re.compile(r'"([^"]+)"|“([^”]+)”')
SETTLED = re.compile(r"충족했|충족합니다|충족됩니다|확인되었|확인됐|맞습니다|문제가? 없|해당하지 않습니다")


def _walk(x, nums, strs):
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, (int, float)):
        nums.add(float(x))
    elif isinstance(x, str):
        strs.append(x)
    elif isinstance(x, dict):
        for v in x.values():
            _walk(v, nums, strs)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _walk(v, nums, strs)


def _counts(c):
    return {float(v) for v in c.values()}


def trial_fields(t):
    """The part of a ⓪ trial record a briefing may quote (what brief_* and the LLM fact pack actually use).
    Citing trial:<id> no longer licenses every number in the eligibility text or summary."""
    bx = t.get("briefing_extra") or {}
    return {"title": t.get("title"), "conditions": t.get("conditions"), "phases": t.get("phases"),
            "min_age": t.get("min_age"), "max_age": t.get("max_age"), "status_verified": t.get("status_verified"),
            "arm_interventions": [i for a in t.get("arms") or [] for i in a.get("interventions", [])],
            "enrollment": bx.get("enrollment"), "interventions": [i.get("name") for i in bx.get("interventions") or []],
            "primary_outcomes": [o.get("measure") if isinstance(o, dict) else o for o in bx.get("primary_outcomes") or []]}


def allowed(sentence, g, trials, as_of):
    """(numbers, dates) a sentence may use, from its refs."""
    nums, strs = set(), []
    typed = {"곳": set(), "개월": set(), "명": set(), "count": set()}
    refs = sentence.get("refs", [])
    decs = [g.nodes[r] for r in refs if r.startswith("dec:") and r in g.nodes]
    GLOSS = gloss_ids()
    for r in refs:
        if r in FIXED:
            strs.append(FIXED[r])
            continue
        if r in GLOSS:   # glossary row: its Korean name / abbreviation may carry numbers ("제2형 당뇨병")
            strs += [GLOSS[r]["ko"], GLOSS[r].get("abbr") or "", GLOSS[r]["en"], GLOSS[r].get("title_exception") or ""]
            continue
        n = g.nodes.get(r)
        if n is None:
            continue
        _walk({k: v for k, v in n.items() if k != "why"} if n.get("kind") == "trial_decision" else n, nums, strs)
        tid = n.get("trial_id") or (r.split(":", 1)[1] if r.startswith(("trial:", "label:")) else None)
        if r.startswith(("trial:", "label:")) and tid:
            t = trials.get(tid, {})
            _walk(trial_fields(t), nums, strs)
            kr, kr_sites = kr_info(t)
            typed["곳"] |= {float(kr_sites), float(len(t.get("sites") or []))}
            m = months_since(t.get("status_verified"), as_of)
            if m is not None:
                typed["개월"].add(float(m))
            # a6-0.4.13: arm numbering ("시험군 2"), "외 N개 군", country counts ("외 N개국")
            n_arms = len(t.get("arms") or [])
            n_cty = len(set(t.get("countries") or []) | {s.get("country") for s in t.get("sites") or [] if s.get("country")})
            nums |= {float(k) for k in range(0, max(n_arms, n_cty) + 1)}
            for a in t.get("arms") or []:   # week windows "(W12-W48)": the letter-number tokens hide them from NUM_RE
                for i in a.get("interventions") or []:
                    nums |= {float(w) for w in re.findall(r"(?<![A-Za-z])W(\d+)", i)}
            if (t.get("briefing_extra") or {}).get("enrollment"):
                typed["명"].add(float(t["briefing_extra"]["enrollment"]))
            open_ = [d for d in g.decisions(tid) if d["status"] in ("UNKNOWN", "CONFLICT")]
            typ = Counter(g.nodes.get(f"crit:{d['criterion_id']}", {}).get("type") for d in open_)
            typed["count"] |= {float(len(open_))} | _counts(typ) | _counts(Counter(d.get("action") for d in open_))
    if decs:
        typed["count"].add(float(len(decs)))
        for key in ("action", "status", "reason"):
            typed["count"] |= _counts(Counter(d.get(key) for d in decs))
        typed["count"] |= _counts(Counter(g.nodes.get(f"crit:{d['criterion_id']}", {}).get("type") for d in decs))
    for s in strs:
        for m in NUM_RE.findall(ID_RE.sub(" ", s)):
            nums.add(float(m.replace(",", "")))
    dates = set()
    for s in strs:
        for y, mo, d in NODE_DATE.findall(s):
            dates.add((int(y), int(mo), int(d) if d else None))
    typed["base"] = nums          # values found in the cited nodes' own text/fields
    return typed, dates


def _num_ok(x, nums):
    for v in nums:
        if abs(v - x) < 1e-9 or abs(round(v) - x) < 1e-9 or abs(int(v) - x) < 1e-9 or abs(round(v, 1) - x) < 1e-9:
            return True
    return False


def _date_ok(kind, parts, dates):
    if kind == "ymd":
        return any((y, m, d) == parts or (y, m) == parts[:2] and d is None for y, m, d in dates)
    if kind == "ym":
        return any((y, m) == parts for y, m, _ in dates)
    return any((m, d) == parts for _, m, d in dates)


def check_sentence(s, g, trials, as_of, ranking=None):
    if s.get("kind") in ("meta",):
        return []
    text = s["text"]
    typed, dates = allowed(s, g, trials, as_of)
    nums = typed["base"]
    probs = []
    rest = ID_RE.sub(" ", text)
    for pat, kind in DATE_PATTERNS:
        for m in list(pat.finditer(rest)):
            parts = tuple(int(x) for x in m.groups())
            if not _date_ok(kind, parts, dates):
                probs.append(("date", m.group(0)))
        rest = pat.sub(" ", rest)
    lead = re.match(r"^\s*(\d+)(\.\s|번 시험)", rest)     # list numbering "1. " / "1번 시험" = the trial's rank
    if lead and ranking:
        tids = [r.split(":", 1)[1] for r in s.get("refs", []) if r.startswith("trial:")]
        pos = [ranking.index(t) + 1 for t in tids if t in ranking]
        if pos and int(lead.group(1)) not in pos:
            probs.append(("number", f"rank {lead.group(1)} (is {pos[0]})"))
    rest = re.sub(r"^\s*\d+(\.\s|번 시험)", " ", rest)
    for m in NUM_RE.finditer(rest):
        x = float(m.group().replace(",", ""))
        unit = UNIT_RE.match(rest, m.end())
        u = unit.group(1) if unit else None
        if u in ("곳", "개월", "명"):            # a count with a unit must be that count (or a value in the node text)
            ok = _num_ok(x, typed[u]) or _num_ok(x, nums)
        elif u in ("개", "가지", "건"):
            ok = _num_ok(x, typed["count"]) or _num_ok(x, nums)
        else:
            ok = _num_ok(x, nums) or _num_ok(x, typed["count"])
        if not ok:
            probs.append(("number", m.group()))
    srcs = [g.nodes[r]["text"] for r in s.get("refs", []) if r.startswith("src:") and r in g.nodes and g.nodes[r].get("text")]
    if srcs:   # a quoted source sentence must be copied verbatim from a cited source node
        for q in (a or b for a, b in QUOTE_RE.findall(text)):
            if not any(q in t for t in srcs):
                probs.append(("quote", q[:40]))
    decs = [g.nodes[r] for r in s.get("refs", []) if r.startswith("dec:") and r in g.nodes]
    for d in decs:
        crit = g.nodes.get(f"crit:{d['criterion_id']}", {})
        if crit.get("type") == "exclusion" and d["status"] == "PASS" and "충족" in text and "제외 사유" not in text \
                and len(decs) == 1:
            probs.append(("verdict", "exclusion PASS written as 충족"))
    if decs and all(d["status"] in ("UNKNOWN", "CONFLICT") for d in decs) and SETTLED.search(text):
        probs.append(("verdict", "open criteria written as settled: " + SETTLED.search(text).group(0)))
    for r in s.get("refs", []):
        if r.startswith("label:") and r in g.nodes and g.nodes[r].get("label") == "potential" and "가능성이 높" in text:
            probs.append(("verdict", "potential trial written with eligible wording"))
    return probs


LATIN = re.compile(r"[A-Za-z][A-Za-z0-9'-]*[A-Za-z0-9]|[A-Za-z]")
PARENS = re.compile(r"\([^()]*\)")
FLAG_WORDS = re.compile(r"재확인")


def _allowed_english(s, g, trials):
    """Latin tokens a patient sentence may show outside parentheses: tokens of the Korean names it cites from the
    glossary (HER2 양성 유방암), and the English originals it may keep (untranslated trial conditions / MeSH, diagnosis
    terms of cited evidence)."""
    gid = gloss_ids()
    allow = set()
    def add(t):
        allow.update(x.lower() for x in LATIN.findall(t or ""))
    for r in s.get("refs", []):
        if r in gid:
            add(gid[r].get("ko")); add(gid[r].get("abbr"))
        elif r.startswith("trial:"):
            t = trials.get(r[6:], {})
            for c in (t.get("conditions") or []) + (t.get("condition_mesh") or []):
                add(c)
            for a in t.get("arms") or []:   # a6-0.4.13: intervention originals kept in the arms sentence (ABBV-142)
                for i in a.get("interventions") or []:
                    add(i)
        elif r.startswith("ev:"):
            n = g.nodes.get(r) or next((e for e in KI.EVIDENCE.get(g.patient_id, [])
                                        if "ev:" + str(e.get("evidence_id")) == r), {})
            add(n.get("term"))
    return allow


def english_outside_parens(s, g, trials):
    """(patient) English left outside parentheses that is not an allowed original or part of a glossary name."""
    bare = PARENS.sub(" ", s.get("text", ""))
    bare = ID_RE.sub(" ", bare)
    left = [w for w in LATIN.findall(bare) if w.lower() not in _allowed_english(s, g, trials)]
    return left


def flags_by_trial(rows):
    """{patient_id: {trial_id: set(review flags)}} from ranking rows: items[].review_flags and near_miss[].flags."""
    out = {}
    for r in rows:
        p = out.setdefault(r["patient_id"], {})
        for it in r.get("items", []):
            p.setdefault(it["trial_id"], set()).update(f["flag"] for f in it.get("review_flags", []))
        for x in r.get("near_miss", []):
            p.setdefault(x["trial_id"], set()).update(x.get("flags") or [])
    return out


def _sentence_trials(s):
    tids = set()
    for r in s.get("refs", []):
        p, _, rest = r.partition(":")
        if p in ("trial", "label"):
            tids.add(rest)
        elif p in ("dec", "calc"):
            tids.add(rest.split(":")[0])
    return tids


def check(doc, g, trials, flags=None):
    out = []
    no_dx = doc.get("audience") == "patient" and not has_confirmed_malignancy(g)
    outside = set(outside_malignancy_refs(g)) if doc.get("audience") == "patient" and not no_dx else set()
    for i, s in enumerate(doc["sentences"]):
        for p in check_sentence(s, g, trials, doc.get("as_of") or g.as_of, doc.get("ranking")):
            out.append((i, *p))
        if no_dx and s.get("kind") != "meta" and names_cancer(s["text"]):
            # a cancer name in front of a patient whose record has no confirmed malignancy (keyinfo.cancer_hidden)
            out.append((i, "cancer", s["text"][:40]))
        if doc.get("audience") == "patient" and s.get("kind") == "fact":
            left = english_outside_parens(s, g, trials)
            if left:   # a6-0.4.2: test kind of English in front of patients (DAS28-CRP, CRP ...)
                out.append((i, "english", " ".join(left[:4])))
        if flags is not None and doc.get("audience") == "clinician" and s.get("kind") != "meta" and FLAG_WORDS.search(s["text"]):
            tids = _sentence_trials(s)
            pf = flags.get(doc.get("patient_id") or g.patient_id, {})
            if tids and not any(pf.get(t) for t in tids):   # "재확인" claimed for a trial with no review flag
                out.append((i, "flag_claim", s["text"][:40]))
        if outside and s.get("kind") != "meta" and names_cancer(s["text"]) and not outside & set(s.get("refs", [])):
            # the cancer name is allowed only because of Agent 2 evidence outside the graph: the sentence must cite it
            out.append((i, "ev_uncited", s["text"][:40]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--graphs", required=True, nargs="+")
    ap.add_argument("--trials", required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--show", type=int, default=3, help="problems printed per failing file")
    ap.add_argument("--evidence", nargs="*", default=[], help="Agent 2 evidence jsonl (cancer-diagnosis check)")
    ap.add_argument("--ranking", help="ranking.jsonl: enables flag_claim (재확인 without a review flag)")
    a = ap.parse_args(argv)
    flags = flags_by_trial(read_jsonl(a.ranking)) if a.ranking else None
    KI.load_evidence(a.evidence, a.graphs)
    trials = {t["trial_id"]: t for t in read_jsonl(a.trials)}
    tot = fails = 0
    agg = Counter()
    for f in sorted(glob.glob(os.path.join(a.folder, "*.json"))):
        doc = json.load(open(f, encoding="utf-8"))
        gp = next(os.path.join(d, doc["graph_file"]) for d in a.graphs if os.path.exists(os.path.join(d, doc["graph_file"])))
        probs = check(doc, Graph.load(gp), trials, flags)
        tot += 1
        agg.update(p[1] for p in probs)
        if probs:
            fails += 1
            print(f"  ! {os.path.basename(f)}: " + "; ".join(f"#{i} {k} {v!r}" for i, k, v in probs[:a.show]))
    print(f"{tot} briefings, {fails} failing | content number {agg['number']}, date {agg['date']}, quote {agg['quote']}, "
          f"verdict {agg['verdict']}, cancer {agg['cancer']}, ev_uncited {agg['ev_uncited']}, english {agg['english']}, "
          f"flag_claim {agg['flag_claim']}")
    if a.strict and fails:
        sys.exit(1)


if __name__ == "__main__":
    main()
