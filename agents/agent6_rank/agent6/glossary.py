"""Korean names for trial conditions and diagnosis terms (agent6/glossary.csv), cited as `gloss:<key>` refs.

A translation is not a graph fact, so it is not invented at generation time: it comes from a fixed, human-reviewed
table, like the `rule:` sentences. Lookup is case-insensitive on the English term (HTML entities unescaped).
Missing term -> None: the briefing keeps the English original (never a made-up translation).

Columns: en, ko, abbr, kind (disease/state/biomarker/drug/procedure/other), source (condition/diagnosis), dev_used,
status (draft -> reviewed), note, title_exception ("<regex> => <alt name>", matched on the trial title + official
title); several rules are separated by " ; " and the first match wins. MeSH Neoplasms and Solid Tumor rows default to
종양 and become 암 only when the titles show malignancy (cancer, carcinoma, metastatic, HCC ...). Veto rules come first:
Colorectal Neoplasms with polyp/adenoma, Liver Neoplasm with metastases (secondary, not liver cancer) stay 종양. Only disease/state/biomarker go into "이 시험은 ~을(를) 연구 대상으로 합니다".
Every briefing records how many glossary rows it used and whether any was still `draft` (generator.glossary).
"""
import csv, hashlib, html, json, os, re

DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glossary.csv")
FREEZE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "GLOSSARY_FREEZE.json")
STUDIED_KINDS = {"disease", "state", "biomarker"}
_CACHE = {}


def resolve(path=None):
    """Glossary in use. AGENT6_GLOSSARY=none runs the "no glossary" condition (English originals / LLM translation
    with the original in parentheses); AGENT6_GLOSSARY=<file> points to another file; unset = agent6/glossary.csv."""
    if path is not None:
        return path
    env = os.environ.get("AGENT6_GLOSSARY", "").strip()
    return "none" if env.lower() == "none" else (env or DEFAULT)


PATH = None   # kept for callers: None means resolve() at call time


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def check_freeze(path):
    """If GLOSSARY_FREEZE.json names this file, its sha256 must still match (frozen before test scoring)."""
    if not os.path.exists(FREEZE):
        return None
    fz = json.load(open(FREEZE, encoding="utf-8"))
    if os.path.basename(path) == fz.get("file") and sha256(path) != fz.get("sha256"):
        raise RuntimeError(f"glossary {path} changed after it was frozen ({fz.get('frozen_at')}, sha256 "
                           f"{fz.get('sha256', '')[:12]}...). Restore it or re-freeze explicitly.")
    return fz


def key(term):
    return re.sub(r"\s+", " ", html.unescape(term or "")).strip().lower()


def gloss_id(term):
    return "gloss:" + re.sub(r"[^a-z0-9]+", "_", key(term)).strip("_")


def table(path=None):
    path = resolve(path)
    if path == "none":
        return {}
    if path not in _CACHE:
        check_freeze(path)
        rows = {}
        if os.path.exists(path):
            for r in csv.DictReader(open(path, encoding="utf-8-sig")):
                if r.get("en") and r.get("ko"):
                    rows[key(r["en"])] = r
        _CACHE[path] = rows
    return _CACHE[path]


def ids(path=None):
    """{gloss_id: row} — valid `gloss:` refs for check_grounding / check_content."""
    return {gloss_id(r["en"]): r for r in table(path).values()}


def lookup(term, path=None):
    return table(path).get(key(term))


def name_for(row, title=None):
    """Korean name, honouring the row's title_exception ("polyp|adenoma => 대장 종양"): when the trial title matches
    the pattern, the reviewed alternative name is used (MeSH "Neoplasms" rows written as 암 by default)."""
    for ex in (row.get("title_exception") or "").split(" ; "):   # ordered: the first matching rule wins
        if title and "=>" in ex:
            pat, alt = (x.strip() for x in ex.split("=>", 1))
            if re.search(pat, title, re.I):
                return alt
    return row["ko"]


def display(row, title=None):
    """Korean name with the abbreviation glossed in parentheses when there is one: 만성 폐쇄성 폐질환(COPD)."""
    ab = (row.get("abbr") or "").strip()
    ko = name_for(row, title)
    return f"{ko}({ab})" if ab and ab not in ko else ko


def usage(sentences, path=None):
    """{"mode", "sha256", "rows_used", "draft"}: which glossary a briefing used and how many rows it cites."""
    p = resolve(path)
    gid = ids(path)
    used = {r for s in sentences for r in s.get("refs", []) if r in gid}
    return {"mode": "none" if p == "none" else "glossary", "sha256": None if p == "none" else sha256(p),
            "rows_used": len(used), "draft": sum(1 for r in used if gid[r].get("status") != "reviewed")}
