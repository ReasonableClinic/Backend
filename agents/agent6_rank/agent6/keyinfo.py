"""Patient "key information" facts, shared by the template writer (brief_patient) and the LLM fact pack (brief_llm).

From the team idea doc (산학 협력 프로젝트 초기 아이디어 제안) 9장, kept inside the graph-only rule:
  1. 왜 나에게 맞는가        -> `confirmed`: inclusion PASS decisions backed by a confirmed diagnosis in the record
  2. 이 시험은 무엇을 하는가  -> `studies` (conditions, what is measured), phase/comparator/placebo/random/blinded rules,
                                `enroll`; all from the ⓪ record, cited as trial:<id>
  3. 내 상황과 어떻게 연결   -> `studies` says what the trial *studies*, never what it will do for the patient
                                ("연구 대상으로 합니다", 표현의 선); effect is unknown (rule:no_benefit_promise)
  질문 대상 라우팅            -> open inclusion criteria grouped by who can answer (patient / records / tests / doctor)
Each fact: {fid, refs, ko (template sentence), detail (raw data for the LLM), required}.
"""
import re

from . import arms as AR
from . import glossary as GL
from .rules import FIXED, PHASE_RULE

MALIGNANT = re.compile(r"cancer|carcinoma|malignan|metasta|sarcoma|melanoma|lymphoma|leuka?emia|myeloma|glioma|astrocytoma|"
                       r"blastoma|mesothelioma|richter|hodgkin|macroglobulin|"
                       r"(?-i:\b(?:CLL|CML|AML|NHL|HCC|NSCLC|SCLC|GBM|DLBCL|RCC|TNBC)\b)", re.I)
# Korean forms mirror MALIGNANT: blastoma -> 모세포종 (교모세포종), mesothelioma -> 중피종, malignan -> 악성 …종양
# (a6-0.3.6: glossary gt-1.0.0 rows translate these English names, which MALIGNANT used to catch).
# a6-0.4.0: macroglobulin / 거대글로불린혈증 (Waldenstrom, the one cancer name the 1,043-row check missed).
KO_CANCER = re.compile(r"암(?=[\s,·()/을를이가은는과와도의에]|$)|육종|흑색종|림프종|백혈병|골수종|교종|성상세포종|"
                       r"모세포종|중피종|악성[^.,·()]{0,12}종양|거대글로불린혈증")


def names_cancer(text):
    """Does the text name a cancer (Korean name or untranslated English)?"""
    return bool(KO_CANCER.search(text or "") or MALIGNANT.search(text or ""))


EVIDENCE = {}        # patient_id -> [Agent 2 evidence rows], filled by load_evidence() when --evidence is given
EVIDENCE_INFO = None  # {"files", "sha256", "id_series", "graph_ev_nodes_checked"} once the version check has passed
EV_COMPARE = ("concept", "term", "value")   # fields that must match between a graph evidence node and the file row


def _row_id(e):
    for k in ("evidence_id", "id", "ev_id"):
        if e.get(k):
            v = str(e[k])
            return v if v.startswith("ev:") else "ev:" + v
    return None


def run_meta(path):
    """Agent 2 v14.14~ sidecar `<name>.run_meta.json` next to `<name>.jsonl`: {"id_series": "haiku"|"rules",
    "id_prefix": "EV"|"R", "file_version", ...}. None when the file has no sidecar (kits issued before v14.14)."""
    import json, os
    base = path[:-6] if path.endswith(".jsonl") else path
    for m in (base + ".run_meta.json", path + ".run_meta.json"):
        if os.path.exists(m):
            return json.load(open(m, encoding="utf-8"))
    return None


def _check_series(paths):
    """a6-0.4.1: the haiku and rules-only series number evidence separately, so files of two series must never be
    mixed. Uses run_meta.json when present (stops on two series, or on ids that do not carry the declared prefix);
    files without one are still covered by the id-collision and graph checks in load_evidence."""
    import json, os, re
    seen = {}
    for p in paths:
        m = run_meta(p)
        if not m:
            continue
        seen.setdefault(m.get("id_series"), []).append(os.path.basename(p))
        pre = m.get("id_prefix")
        if pre:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        e = json.loads(line)
                        rid = (_row_id(e) or "")[3:]
                        if rid and not re.search(rf"-{re.escape(pre)}\d{{3,}}$", rid):
                            raise RuntimeError(f"{os.path.basename(p)}: id {rid} does not match its run_meta "
                                               f"id_prefix {pre!r}")
    if len(seen) > 1:
        raise RuntimeError(f"evidence files from two id series {seen}: haiku and rules-only files number evidence "
                           f"separately (Agent 2 v14.14). Pass only the series the Agent 3 run read.")
    return next(iter(seen)) if seen else None


def load_evidence(paths, graph_dirs=None):
    """Optional: Agent 2's full evidence files. The graph only holds evidence Agent 3 cited for the ranked trials, so a
    cancer diagnosis that no criterion needed can be missing from it (TREC-2021-15: "pancreatic adenocarcinoma head").

    The files must be the ones the Agent 3 run read (same Agent 2 version AND same extraction; since a6-0.3.7): every
    evidence node in every graph under graph_dirs must appear in the files under the same id with the same
    concept/term/value. Otherwise this raises before any briefing is written (e.g. v14.12 files with v14.9 graphs).
    a6-0.4.0: Agent 2's LLM and rule extractions number their evidence separately, so the same id can name different
    evidence in two files (dev v14.9: 9,438 of the 9,621 shared ids). Two loaded files sharing a (patient, evidence id) also stop the run;
    pass only the files Agent 3 used (dev: the haiku files)."""
    import glob, hashlib, json, os
    global EVIDENCE_INFO
    EVIDENCE.clear()
    EVIDENCE_INFO = None
    if not paths:
        return None
    series = _check_series(paths)
    owner = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    e = json.loads(line)
                    k = (e.get("patient_id"), _row_id(e))
                    if k[1] and k in owner and owner[k] != p:
                        raise RuntimeError(f"evidence id {k[1]} ({k[0]}) is in two files ({os.path.basename(owner[k])}, "
                                           f"{os.path.basename(p)}): different Agent 2 extractions reuse ids. Pass only "
                                           f"the evidence files the Agent 3 run read.")
                    owner[k] = p
                    EVIDENCE.setdefault(e.get("patient_id"), []).append(e)
    if graph_dirs is None:
        raise ValueError("load_evidence: pass the graph folders so the evidence version can be checked")
    rows = {pid: {_row_id(e): e for e in es if _row_id(e)} for pid, es in EVIDENCE.items()}
    checked, problems = 0, []
    for d in graph_dirs:
        for gp in sorted(glob.glob(os.path.join(d, "*.json"))):
            data = json.load(open(gp, encoding="utf-8"))
            if "nodes" not in data or "patient_id" not in data:
                continue
            got = rows.get(data["patient_id"], {})
            for n in data["nodes"]:
                if n.get("kind") != "evidence":
                    continue
                checked += 1
                e = got.get(n["id"])
                if e is None:
                    problems.append(f"{n['id']} not in evidence files")
                    continue
                diff = [k for k in EV_COMPARE if k in n and k in e and n[k] != e[k]]
                if diff:
                    problems.append(f"{n['id']} differs in {','.join(diff)}")
    if checked == 0:
        raise RuntimeError("evidence version check: the graphs hold no evidence nodes, so the files cannot be matched "
                           "to the graph version. Run without --evidence or with the graphs Agent 3 built.")
    if problems:
        raise RuntimeError(f"evidence files are not the version the graphs were built on: {len(problems)}/{checked} "
                           f"graph evidence nodes do not match (e.g. {problems[:3]}). Use the Agent 2 files of the "
                           f"same version and extraction the Agent 3 run read (test: v14.9).")
    h = hashlib.sha256()
    for p in sorted(paths, key=os.path.basename):
        h.update(open(p, "rb").read())
    EVIDENCE_INFO = {"files": sorted(os.path.basename(p) for p in paths), "sha256": h.hexdigest(), "id_series": series,
                     "graph_ev_nodes_checked": checked}
    return EVIDENCE_INFO


def _malignant_dx(e):
    return (e.get("concept") == "diagnosis" and e.get("value") is True and e.get("certainty") == "confirmed"
            and e.get("subject") in (None, "patient") and bool(MALIGNANT.search(e.get("term") or "")))


def has_confirmed_malignancy(g):
    """The patient's own record holds a confirmed, present-or-past malignant diagnosis (not negated, not suspected,
    not a relative's). Looks at the graph's evidence nodes and, when loaded, Agent 2's full evidence for the patient."""
    if any(n.get("kind") == "evidence" and _malignant_dx(n) for n in g.nodes.values()):
        return True
    return any(_malignant_dx(e) for e in EVIDENCE.get(g.patient_id, []))


def outside_malignancy_refs(g):
    """`ev:` ids of the Agent 2 rows that establish the malignancy when the graph itself does not. A sentence that names
    a cancer on the strength of evidence outside the graph must cite these (check_content: ev_uncited)."""
    if any(n.get("kind") == "evidence" and _malignant_dx(n) for n in g.nodes.values()):
        return []
    return sorted({_row_id(e) for e in EVIDENCE.get(g.patient_id, []) if _malignant_dx(e) and _row_id(e)})


def outside_evidence_ids(patient_id):
    """`ev:` ids loaded from Agent 2 files for this patient: valid refs for check_grounding besides graph nodes."""
    return {_row_id(e) for e in EVIDENCE.get(patient_id, []) if _row_id(e)}


ROUTE = {"patient_question": ("ask_you", "직접 답해 주실 수 있는 질문"),
         "med_record_check": ("records", "진료 기록에서 찾아볼 것"), "med_history_check": ("records", "진료 기록에서 찾아볼 것"),
         "lab_check": ("tests", "검사 결과가 필요한 것"), "new_test": ("tests", "검사 결과가 필요한 것"),
         "clinician_confirmation": ("doctor", "담당 의사가 판단할 것")}
ROUTE_ORDER = ["ask_you", "records", "tests", "doctor", "other"]
ADULT_AGE = 19   # 민법상 성년


def patient_age(g):
    for n in g.nodes.values():
        if n.get("kind") == "calculation" and n.get("name") == "age_at_as_of" and n.get("value") is not None:
            return n["value"]
    return None


def is_minor(g):
    a = patient_age(g)
    return a is not None and a < ADULT_AGE


def _is_excl(g, d):
    return g.nodes.get(f"crit:{d['criterion_id']}", {}).get("type") == "exclusion"


def design_rules(trial, tid):
    """Fixed design sentences for one trial, in reading order: phase, comparator, random, placebo, blinded."""
    rids = []
    ph = "+".join(trial.get("phases") or [])
    if ph in PHASE_RULE:
        rids.append(PHASE_RULE[ph])
    types = {a.get("type") for a in trial.get("arms") or []}
    if "ACTIVE_COMPARATOR" in types:
        rids.append("rule:active_comparator")
    if "NO_INTERVENTION" in types:
        rids.append("rule:no_intervention_arm")
    if trial.get("allocation") == "RANDOMIZED":
        rids.append("rule:randomized")
    if "PLACEBO_COMPARATOR" in types:
        rids.append("rule:placebo")
    if (trial.get("briefing_extra") or {}).get("masking") not in (None, "NONE"):
        rids.append("rule:blinded")
    return [{"text": FIXED[r], "refs": sorted({f"trial:{tid}", r}), "kind": "rule"} for r in rids]


def _tokens(x):
    import re
    return {w for w in re.findall(r"[a-z0-9]+", (x or "").lower()) if len(w) >= 4}


def confirmed_diagnoses(g, tid, trial=None, limit=2):
    """[(decision, [evidence nodes])] inclusion PASS backed by confirmed diagnosis evidence whose term shares a word
    with the trial's conditions (so "remission" or a side diagnosis is not shown as "why this trial")."""
    cond = set().union(*[_tokens(c) for c in ((trial or {}).get("conditions") or []) + ((trial or {}).get("condition_mesh") or [])]) \
        if trial else None
    out = []
    for d in g.decisions(tid):
        if d["status"] != "PASS" or _is_excl(g, d):
            continue
        evs = [ev for ev, _ in g.support(d["id"]) if ev.get("concept") == "diagnosis" and ev.get("certainty") == "confirmed"
               and ev.get("value") is True and (cond is None or _tokens(ev.get("term")) & cond)]
        if evs:
            out.append((d, evs))
    return out[:limit]


def josa(word, with_final, without_final):
    """Pick the Korean particle by the last Hangul syllable (parenthesised gloss ignored); English stays 을(를)."""
    import re
    w = re.sub(r"\([^()]*\)\s*$", "", word).strip()
    c = w[-1:] if w else ""
    if "가" <= c <= "힣":
        return with_final if (ord(c) - 0xAC00) % 28 else without_final
    return f"{with_final}({without_final})"


_PAREN = r"\((?:[^()]|\([^()]*\))*\)"      # one parenthesis group, one nested level allowed: (Chronic ... (COPD))
_DUAL = {"을(를)": ("을", "를"), "를(을)": ("을", "를"), "이(가)": ("이", "가"), "가(이)": ("이", "가"),
         "은(는)": ("은", "는"), "는(은)": ("은", "는"), "과(와)": ("과", "와"), "와(과)": ("과", "와"),
         "으로(로)": ("으로", "로"), "로(으로)": ("으로", "로"), "(으)로": ("으로", "로")}
_FIX_JOSA = re.compile(r"([가-힣])((?:\s*" + _PAREN + r")+)\s*(" + "|".join(re.escape(k) for k in sorted(_DUAL, key=len, reverse=True)) + ")")


def fix_josa(text):
    """a6-0.4.10: replace a two-way particle written after a Korean name ("폐섬유증(Idiopathic … (IPF))을(를)") with the
    right one, chosen by the last Hangul syllable before the parentheses. A name that ends in English keeps 을(를)
    (its Korean reading is unknown). Used on LLM sentences; template sentences already choose with josa()."""
    def rep(m):
        c, par, d = m.group(1), m.group(2), m.group(3)
        wf, nf = _DUAL[d]
        code = (ord(c) - 0xAC00) % 28
        if wf == "으로":
            pick = "로" if code in (0, 8) else "으로"     # no final consonant or ㄹ -> 로
        else:
            pick = wf if code else nf
        return c + par + pick
    return _FIX_JOSA.sub(rep, text)


_ABBR_TAIL = re.compile(r"^(.*?)\s*\(([A-Za-z0-9-]{2,8})\)$")
_PURE_ABBR = re.compile(r"^[A-Z][A-Z0-9-]{1,7}$")
_QUAL_TAIL = re.compile(r"(?i)^(bclc [0a-d]|stage [0iv1-4]+[a-c]?|grade [1-4][ab]?|p?t[0-4][a-c]?n[0-3][a-c]?(m[01])?)$")


def _syn_key(t):
    m = _ABBR_TAIL.match(t.strip())
    base, ab = (m.group(1), m.group(2)) if m else (t.strip(), None)
    return re.sub(r"[^a-z0-9]+", " ", base.lower().replace("'", "")).strip(), ab


def merge_synonyms(terms):
    """(a6-0.4.12) One trial lists the same disease under several English names ("IPF", "Idiopathic Pulmonary
    Fibrosis", "Idiopathic Pulmonary Fibrosis (IPF)"). Untranslated, each became its own Korean name, so the patient
    read "특발성 폐섬유증" three times. Groups: same words (case, punctuation, apostrophe ignored), an abbreviation that
    another name gives in parentheses or that is its initials, and a name that only adds a stage/grade to another
    (the staged one is kept). Shown once, as "Name (ABBR)" when one exists. Order: first appearance."""
    info = [(t, *_syn_key(t)) for t in terms]
    abbr_of = {}
    for t, k, ab in info:
        if ab:
            abbr_of.setdefault(ab.upper(), k)
        ini = "".join(w[0] for w in k.split() if w).upper()
        if len(ini) >= 2:
            abbr_of.setdefault(ini, k)
    keys = []
    for t, k, ab in info:
        if _PURE_ABBR.match(t.strip()) and t.strip().upper() in abbr_of:
            k = abbr_of[t.strip().upper()]
        keys.append(k)
    staged = {}
    for k in set(keys):
        for k2 in set(keys):
            if k2 != k and k2.startswith(k + " ") and _QUAL_TAIL.match(k2[len(k) + 1:]):
                staged[k] = k2
    keys = [staged.get(k, k) for k in keys]
    groups, order = {}, []
    for (t, _, ab), k in zip(info, keys):
        if k not in groups:
            groups[k] = []
            order.append(k)
        groups[k].append((t, ab))
    out = []
    for k in order:
        g = groups[k]
        withab = [t for t, ab in g if ab and _syn_key(t)[0] == k]
        plain = [t for t, ab in g if _syn_key(t)[0] == k]
        out.append(withab[0] if withab else plain[0] if plain else g[0][0])
    return out


def _drop_unstaged(out):
    """(a6-0.4.12) "다발성 간세포암(BCLC B기), 다발성 간세포암": a name equal to another one without its parentheses is
    the same diagnosis without the qualifier; keep the qualified one."""
    names = [n for n, _ in out]
    bare = {re.sub(r"\([^()]*\)", "", n).strip() for n in names if "(" in n}
    return [(n, r) for n, r in out if not ("(" not in n and n in bare)]


def ko_terms(terms, studied_only=False, limit=3, title=None):
    """[(display name, gloss ref or None)] — Korean from the reviewed glossary, else the English original as is.
    studied_only drops drug/procedure/other rows ("Tirzepatide", "Healthy") from "연구 대상" sentences.
    a6-0.4.12: names that are not in the glossary are merged by merge_synonyms, and a glossary name repeated only
    without its parenthesised qualifier is dropped (_drop_unstaged)."""
    rows = [(t, GL.lookup(t)) for t in terms]
    rows = [(t, r) for t, r in rows if not (r and studied_only and r.get("kind") not in GL.STUDIED_KINDS)]
    merged = merge_synonyms([t for t, r in rows if not r])
    keep = set(merged)
    out, seen = [], set()
    for t, row in rows:
        if row:
            name, ref = GL.display(row, title), GL.gloss_id(row["en"])
        else:
            if t not in keep:
                continue
            name, ref = t, None
        if name not in seen:
            seen.add(name)
            out.append((name, ref))
    out = _drop_unstaged(out)
    return out[:limit]


def studied_names(trial):
    """[(name, gloss ref)] for "이 시험은 ~을 연구 대상으로 합니다" (glossary + title exceptions on title/official title)."""
    bx = trial.get("briefing_extra") or {}
    titles = " | ".join(x for x in (trial.get("title"), bx.get("official_title")) if x)
    conds = trial.get("conditions") or []
    names = ko_terms(conds, studied_only=True, title=titles)
    if not any(ref for _, ref in names):
        # none of the free-text conditions is in the glossary: try the trial's MeSH terms (normalised, so spelling
        # variants and abbreviations of a known disease still match). Only then, never mixed, so the trial's own
        # condition list is not reordered when it is translatable.
        mesh = ko_terms(trial.get("condition_mesh") or [], studied_only=True, title=titles)
        if any(ref for _, ref in mesh):
            return [(n, r) for n, r in mesh if r]
    return names


def cancer_hidden(g, trial):
    """True when the patient briefing must not name the trial's disease: it is a cancer (by the names we would show)
    and the patient's record has no confirmed malignancy. Benign tumours, negated or family-history cancers included."""
    return (not has_confirmed_malignancy(g)) and any(names_cancer(nm) for nm, _ in studied_names(trial))


def patient_facts(g, item, trial, n):
    tid = item["trial_id"]
    T = f"T{n}"
    lab = g.label(tid)
    title = trial.get("title") or tid
    flags = item.get("review_flags", [])
    pending = [f["criterion_id"] for f in flags if f["flag"] == "llm_missing"]
    open_ = [d for d in g.decisions(tid) if d["status"] in ("UNKNOWN", "CONFLICT")]
    incl = [d for d in open_ if not _is_excl(g, d)]
    excl = [d for d in open_ if _is_excl(g, d)]
    bx = trial.get("briefing_extra") or {}
    facts = []

    def F(fid, refs, ko, detail, required=False):
        facts.append({"id": f"{T}.{fid}", "refs": sorted(set(refs)), "ko": ko, "detail": detail, "required": required})

    # The official (English) title stays out of the patient text: idea doc 9장 — the title's impression distorts
    # expectations, and it is the main source of untranslated English. The clinician briefing keeps it.
    ko = (f"{n}번 시험 — 기록 검토가 아직 끝나지 않아, 조건이 맞는지 아직 말씀드릴 수 없습니다." if pending else
          f"{n}번 시험 — 지금 기록으로는 조건이 맞을 가능성이 높습니다." if item["label"] == "eligible" else
          f"{n}번 시험 — 아직 확인이 필요한 조건이 있습니다.")
    F("label", [f"trial:{tid}", lab["id"]] + [g.decision(f"crit:{c}")["id"] for c in pending], ko,
      {"label": "pending (판정 미완료)" if pending else item["label"],
       "style": "공식 제목은 쓰지 않는다. 시험은 번호와 연구 대상(T*.studies)으로 가리킨다"}, True)
    conds = studied_names(trial)
    hidden = cancer_hidden(g, trial)
    if hidden:
        F("studies", [f"trial:{tid}", "rule:clinician_explains_first"], FIXED["rule:clinician_explains_first"],
          {"style": "질환 이름, 암, 종양, 항암 같은 말을 쓰지 않는다. 담당 의료진이 먼저 설명한다는 것만 쓴다"}, True)
    elif conds:
        cites = outside_malignancy_refs(g) if any(names_cancer(n_) for n_, _ in conds) else []
        F("studies", [f"trial:{tid}"] + [r for _, r in conds if r] + cites,
          f"이 시험은 {', '.join(n_ for n_, _ in conds)}{josa(conds[-1][0], '을', '를')} 연구 대상으로 합니다.",
          {"conditions": (trial.get("conditions") or [])[:4], "conditions_ko": [n_ for n_, _ in conds],
           "untranslated": [n_ for n_, r in conds if not r],
           "interventions": [i.get("name") for i in bx.get("interventions") or []][:4],
           "primary_outcomes": [o.get("measure") if isinstance(o, dict) else o for o in bx.get("primary_outcomes") or []][:2],
           "style": "연구 대상으로 한다고만 쓰고, 환자에게 효과가 있을 것처럼 쓰지 않는다"})
    arm = None if hidden else AR.arms_sentence(trial)
    if arm:   # a6-0.4.13: what the trial compares (trials.arms), drug names from the glossary
        F("arms", [f"trial:{tid}"] + arm[1], arm[0],
          {"arms": [{"type": a.get("type"), "interventions": a.get("interventions")} for a in trial.get("arms") or []][:6],
           "arms_ko": arm[0], "untranslated": arm[2],
           "style": "'시험군: …, 비교군: …' 형식 그대로 쓴다. arms_ko의 한국어 약 이름·기간은 글자 그대로 쓰고, untranslated의 "
                    "원어(시험약 코드 등)는 번역하지 않고 그대로 둔다. 어느 쪽이 더 낫다거나 효과가 있다고 쓰지 않는다"}, True)
    if bx.get("enrollment"):
        F("enroll", [f"trial:{tid}"], f"약 {bx['enrollment']}명이 참여할 예정인 연구입니다.", {"enrollment": bx["enrollment"]})
    conf = confirmed_diagnoses(g, tid, trial)
    if conf:
        terms = list(dict.fromkeys(ev.get("term") for _, evs in conf for ev in evs[:1]))
        kt = ko_terms(terms, limit=len(terms))
        F("confirmed", [d["id"] for d, _ in conf] + [ev["id"] for _, evs in conf for ev in evs[:1]] + [r for _, r in kt if r],
          f"기록에 있는 진단 {', '.join(n_ for n_, _ in kt)}{josa(kt[-1][0], '이', '가')} 이 시험의 대상 조건과 맞습니다.",
          {"criteria": [g.nodes[f"crit:{d['criterion_id']}"].get("text") for d, _ in conf], "diagnosis_terms": terms,
           "diagnosis_ko": [n_ for n_, _ in kt], "untranslated": [n_ for n_, r in kt if not r],
           "style": "진단이 대상 조건과 맞는다는 것만 쓰고, 참여할 수 있다는 뜻으로 쓰지 않는다"})
    groups = {}
    for d in incl:
        key, label = ROUTE.get(d.get("action"), ("other", "추가로 확인할 것"))
        groups.setdefault(key, (label, []))[1].append(d)
    for key in ROUTE_ORDER:
        if key in groups:
            label, ds = groups[key]
            F(f"route_{key}", [d["id"] for d in ds] + [f"crit:{d['criterion_id']}" for d in ds],
              f"{label}: {len(ds)}가지.",
              {"who": label, "items": [{"status": d["status"]} if hidden else
                                       {"criterion": g.nodes[f"crit:{d['criterion_id']}"].get("text"),
                                        "status": d["status"], "missing_info": d.get("missing_fact")} for d in ds]}
              | ({"style": "항목 내용은 쓰지 않고 개수와 누가 확인하는지만 쓴다"} if hidden else {}))
    if excl:
        conf_x = [d for d in excl if d["status"] == "CONFLICT"]
        F("excl", [d["id"] for d in excl], f"참여 전에 의료진이 확인할 항목이 {len(excl)}개 남아 있습니다.",
          {"open_exclusion_count": len(excl), "of_which_conflict": len(conf_x)}, True)
    if item["kr_sites"] > 0:   # a6-0.4.13: 0 sites -> site_lines (no "국내 0곳에서 모집 중")
        F("kr", [f"trial:{tid}"], f"국내 {item['kr_sites']}곳에서 모집 중입니다.", {"kr_sites": item["kr_sites"]})
    if item["stale"]:
        F("stale", [f"trial:{tid}"], "모집 상태가 최근에 확인되지 않아, 지금도 모집 중인지 확인이 필요합니다.",
          {"months_since_verified": item["months_since_verified"]}, True)
    return facts


def site_lines(item, trial):
    """(a6-0.4.13) No Korean site recruits: fixed rule:no_kr_site, then the recruiting countries. Deterministic in both
    the template and the LLM briefing (the LLM does not rewrite them)."""
    if item.get("kr_sites", 0) > 0:
        return []
    tid = item["trial_id"]
    out = [{"text": FIXED["rule:no_kr_site"], "refs": sorted({f"trial:{tid}", "rule:no_kr_site"}), "kind": "rule"}]
    c = AR.countries_sentence(trial)
    if c:
        out.append({"text": c, "refs": [f"trial:{tid}"], "kind": "fact"})
    return out


def opening_rules(g):
    rids = ["rule:research_not_treatment"] + (["rule:guardian"] if is_minor(g) else [])
    return [{"text": FIXED[r], "refs": [r], "kind": "rule"} for r in rids]


CLOSING = ["rule:no_benefit_promise", "rule:ask_alternatives", "rule:ask_burden", "rule:ask_clinician", "rule:voluntary",
           "rule:withdraw"]


def closing_rules():
    return [{"text": FIXED[r], "refs": [r], "kind": "rule"} for r in CLOSING]
