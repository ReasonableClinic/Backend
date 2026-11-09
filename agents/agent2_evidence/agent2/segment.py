"""Split a document into fact units with exact character spans.

Levels: line -> sentence (". " / "; " / ": " followed by a new clause) -> item (comma pieces of a list of
measurements such as "Hb 12.1, plt 210, ANC 3.2"). Every unit is (start, end) into the original text, trimmed of
spaces, bullets and trailing separators, so source.text == text[start:end] always holds.
"""
import os, re

_NUM = re.compile(r"\d")
# sentence break: terminator, spaces, then something that starts a new clause
_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z0-9(\-\"'])|(?<=[A-Za-z\)]:)\s+(?=[A-Z0-9\-])|;\s*")
_ABBR = re.compile(r"(?:\b(?:Dr|Mr|Mrs|Ms|vs|approx|e\.g|i\.e|St|No)\.|\b[A-Z]\.|\.\.\.|\u2026)$")
# a colon splits only after a section heading: ALL-CAPS words or the usual note labels
_HEADLIKE = re.compile(r"[A-Z][A-Z0-9 /&\-]{2,40}(?:\s*\([^)]{0,40}\))?|HPI|CC|Imp|Impression|Assessment|Plan|A/P|"
                       r"Assessment and plan|Assessment/Plan|Course|Hospital course|Interval history|Subjective|"
                       r"Objective|History|Medications|Allergies|PMH|PSH|FHx|SHx|ROS")   # case-sensitive on purpose
_NOTE_LABEL = re.compile(r"HPI|CC|Imp|Impression|Assessment|Plan|A/P|Assessment and plan|Assessment/Plan|Course|"
                         r"Hospital course|Interval history|Subjective|Objective|History|Medications|Allergies|PMH|PSH|"
                         r"FHx|SHx|ROS|Dx|Diagnosis|Stage|Staging")   # these split even before a number ("HPI: 61-year-old")
_ABS_NEXT = re.compile(r"\s*abs(?:olute)?\b", re.I)
_BULLET = re.compile(r"^(?:[-*•]\s+|\d{1,2}[.)]\s+)")
_TRIM_END = " \t,;:"
_OLD_COLON = bool(os.environ.get("AGENT2_SEG_V13_2"))   # replay answers made before v13.3 (colon split before a value)
_HEADING = re.compile(r"[A-Z][A-Z /&()\-,]{3,80}")   # bare section headings are not facts


def _trim(text, s, e):
    while s < e and text[s] in " \t":
        s += 1
    m = _BULLET.match(text[s:e])
    if m:
        s += m.end()
    while e > s and text[e - 1] in _TRIM_END:
        e -= 1
    return s, e


def _sentences(text, s, e):
    out, cur = [], s
    for m in _SENT.finditer(text, s, e):
        if _ABBR.search(text[max(cur, m.start() - 6):m.start()]):
            continue
        if _ABS_NEXT.match(text, m.end()):          # "; absolute 8.6 x10^3/uL" belongs to the count before it
            continue
        if text[m.start() - 1] == ":" and (not _HEADLIKE.fullmatch(text[cur:m.start() - 1].strip())
                                           or (not _OLD_COLON and re.match(r"[<>]?\s*\d", text[m.end():m.end() + 3])
                                               and not _NOTE_LABEL.fullmatch(text[cur:m.start() - 1].strip()))):
            continue                                  # "Relapses: 0", "ALT: 43 U/L" (a value, not a section)
        out.append((cur, m.start()))
        cur = m.end()
    out.append((cur, e))
    return out


def _comma_items(text, s, e):
    """Split on commas (outside parentheses) only when most pieces carry a number: a list of measurements."""
    pieces, depth, cur = [], 0, s
    for i in range(s, e):
        ch = text[i]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0 and not (i + 1 < e and text[i + 1].isdigit() and i > s and text[i - 1].isdigit()):
            pieces.append((cur, i))
            cur = i + 1
    pieces.append((cur, e))
    merged = []
    for a, b in pieces:                             # ", abs 5.1 x10^9/L" stays with the item before it
        if merged and _ABS_NEXT.match(text, a):
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    pieces = merged
    if len(pieces) < 2:
        return None
    with_num = sum(bool(_NUM.search(text[a:b])) for a, b in pieces)
    return pieces if with_num >= max(2, 0.6 * len(pieces)) else None


def units(text):
    """List of dicts {span, level, parent} for one document."""
    out = []
    pos = 0
    for line in text.split("\n"):
        ls, le = pos, pos + len(line)
        pos = le + 1
        for ss, se in _sentences(text, ls, le):
            ss, se = _trim(text, ss, se)
            if se - ss < 2 or _HEADING.fullmatch(text[ss:se]):
                continue
            items = _comma_items(text, ss, se)
            if items:
                for a, b in items:
                    a, b = _trim(text, a, b)
                    if b - a >= 2:
                        out.append({"span": (a, b), "level": "item", "parent": (ss, se)})
            else:
                out.append({"span": (ss, se), "level": "sentence", "parent": (ss, se)})
    return out
