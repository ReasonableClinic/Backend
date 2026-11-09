"""(a6-0.4.13) What the trial compares (arms) and where it recruits, for the patient briefing.

arms_sentence(trial) -> "시험군: 메토트렉세이트 + 표적 치료, 비교군: 메토트렉세이트 또는 레플루노마이드 + ..." built from
trials.arms[].type / interventions. Drug and procedure names come from the reviewed glossary (gloss: refs); a name
that is not in it stays as the original (investigational codes such as ABBV-142 have no Korean name). Week windows
"(W0-W12)" become "(0~12주)", consecutive windows of the same drug are merged, and a switch is written with "→".

recruiting_countries(trial) -> Korean country names of the sites that recruit (RECRUITING / NOT_YET_RECRUITING, the
trial's overall status when a site has none), else of trials.countries. A country missing from COUNTRY_KO is counted,
not shown in English ("외 N개국").
"""
import re

from . import glossary as GL

ROLE = {"EXPERIMENTAL": "시험군", "ACTIVE_COMPARATOR": "비교군", "PLACEBO_COMPARATOR": "위약군",
        "SHAM_COMPARATOR": "가짜 시술군", "NO_INTERVENTION": "관찰군", "OTHER": "기타군"}
ROLE_ORDER = list(ROLE)
MAX_ARMS = 4

COUNTRY_KO = {
    "Argentina": "아르헨티나", "Australia": "호주", "Austria": "오스트리아", "Bangladesh": "방글라데시", "Belgium": "벨기에",
    "Brazil": "브라질", "Bulgaria": "불가리아", "Canada": "캐나다", "Chile": "칠레", "China": "중국", "Colombia": "콜롬비아",
    "Costa Rica": "코스타리카", "Croatia": "크로아티아", "Czechia": "체코", "Czech Republic": "체코", "Denmark": "덴마크",
    "Egypt": "이집트", "Estonia": "에스토니아", "Finland": "핀란드", "France": "프랑스", "Georgia": "조지아",
    "Germany": "독일", "Greece": "그리스", "Hong Kong": "홍콩", "Hungary": "헝가리", "India": "인도",
    "Indonesia": "인도네시아", "Ireland": "아일랜드", "Israel": "이스라엘", "Italy": "이탈리아", "Japan": "일본",
    "Jordan": "요르단", "Kyrgyzstan": "키르기스스탄", "Latvia": "라트비아", "Lithuania": "리투아니아",
    "Malaysia": "말레이시아", "Mexico": "멕시코", "Monaco": "모나코", "Netherlands": "네덜란드", "New Zealand": "뉴질랜드",
    "North Macedonia": "북마케도니아", "Norway": "노르웨이", "Oman": "오만", "Pakistan": "파키스탄", "Peru": "페루",
    "Philippines": "필리핀", "Poland": "폴란드", "Portugal": "포르투갈", "Puerto Rico": "푸에르토리코",
    "Romania": "루마니아", "Russia": "러시아", "Russian Federation": "러시아", "Saudi Arabia": "사우디아라비아",
    "Serbia": "세르비아", "Singapore": "싱가포르", "Slovakia": "슬로바키아", "Slovenia": "슬로베니아",
    "South Africa": "남아프리카공화국", "South Korea": "대한민국", "Korea, Republic of": "대한민국", "Spain": "스페인",
    "Sri Lanka": "스리랑카", "Sweden": "스웨덴", "Switzerland": "스위스", "Syria": "시리아", "Taiwan": "대만",
    "Thailand": "태국", "Tunisia": "튀니지", "Turkey": "튀르키예", "Turkey (Türkiye)": "튀르키예", "Türkiye": "튀르키예",
    "Ukraine": "우크라이나", "United Arab Emirates": "아랍에미리트", "United Kingdom": "영국", "United States": "미국",
    "Vietnam": "베트남", "Lebanon": "레바논", "Kazakhstan": "카자흐스탄", "Belarus": "벨라루스", "Iran": "이란",
    "Iraq": "이라크", "Kuwait": "쿠웨이트", "Qatar": "카타르", "Morocco": "모로코", "Algeria": "알제리", "Nigeria": "나이지리아",
    "Kenya": "케냐", "Uruguay": "우루과이", "Paraguay": "파라과이", "Ecuador": "에콰도르", "Guatemala": "과테말라",
    "Panama": "파나마", "Dominican Republic": "도미니카공화국", "Bosnia and Herzegovina": "보스니아 헤르체고비나",
    "Moldova": "몰도바", "Armenia": "아르메니아", "Azerbaijan": "아제르바이잔", "Iceland": "아이슬란드",
    "Luxembourg": "룩셈부르크", "Cyprus": "키프로스", "Malta": "몰타", "Nepal": "네팔", "Myanmar": "미얀마",
    "Cambodia": "캄보디아", "Mongolia": "몽골", "Uzbekistan": "우즈베키스탄",
}
KR = "South Korea"
OK = ("RECRUITING", "NOT_YET_RECRUITING")
MAX_COUNTRIES = 5


def recruiting_countries(trial):
    """(names in Korean, number of countries) of the recruiting sites, in order of first appearance."""
    seen = []
    for s in trial.get("sites") or []:
        c = s.get("country")
        if c and (s.get("status") or trial.get("overall_status")) in OK and c not in seen:
            seen.append(c)
    if not seen:
        seen = [c for c in dict.fromkeys(trial.get("countries") or []) if c]
    return [COUNTRY_KO[c] for c in seen if c in COUNTRY_KO], len(seen)


def countries_sentence(trial):
    ko, n = recruiting_countries(trial)
    if not n:
        return None
    shown = ko[:MAX_COUNTRIES]
    if not shown:
        return f"모집 국가: {n}개국."
    rest = n - len(shown)
    return "모집 국가: " + ", ".join(shown) + (f" 외 {rest}개국." if rest else ".")


# ---------- interventions ----------

_KIND = re.compile(r"^(Drug|Biological|Procedure|Radiation|Device|Diagnostic Test|Dietary Supplement|Behavioral|"
                   r"Genetic|Combination Product|Other):\s*", re.I)
_WEEKS = re.compile(r"\s*\(W(\d+)\s*-\s*W(\d+)\)\s*$", re.I)
_DOSE_NO = re.compile(r"\s*\(Dose\s*#?\s*(\d+)\)\s*$", re.I)
_LEVEL = re.compile(r"\s+(high|medium|low)\s+dose$", re.I)
_AMOUNT = re.compile(r"\s+(\d+(?:\.\d+)?\s?(?:mg|mcg|µg|g|ml|mL|IU))$")
_ADMIN = re.compile(r"\s+administration$", re.I)
_INJ = re.compile(r"(?i)\s+injection(?:\s+every\s+(\d+)\s+weeks?)?(\s+by\s+IV\s+infusion)?$")
_CODE = re.compile(r"^[A-Z]{1,6}[- ]?\d[A-Za-z0-9-]*$|^[A-Z]{2,6}-[A-Z0-9]+$")
_PLACEBO = re.compile(r"(?i)^(matching\s+)?placebo(\s+(for|to|of)\s+.+)?$")
_SPLIT = re.compile(r"\s+(\+|or|and)\s+", re.I)
_PAREN = re.compile(r"^(.*?)\s*\(([^()]+)\)$")
LEVEL_KO = {"high": "고용량", "medium": "중간 용량", "low": "저용량"}


def _lookup(name):
    row = GL.lookup(name)
    return (GL.display(row), GL.gloss_id(row["en"])) if row else None


def _render_list(text, refs, untranslated):
    hit = _lookup(text)
    if hit:
        refs.append(hit[1])
        return hit[0]
    if _CODE.match(text):   # investigational code, no Korean name: say what it is
        untranslated.append(text)
        return f"시험약 {text}"
    parts = _SPLIT.split(text)
    if len(parts) == 1:
        untranslated.append(text)
        return text
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(" + " if p == "+" else " 또는 " if p.lower() == "or" else " 및 ")
            continue
        h = _lookup(p.strip())
        if h:
            refs.append(h[1])
            out.append(h[0])
        elif _CODE.match(p.strip()):
            untranslated.append(p.strip())
            out.append(f"시험약 {p.strip()}")
        else:
            untranslated.append(p.strip())
            out.append(p.strip())
    return "".join(out)


def render_intervention(s):
    """'Drug: TNF Inhibitor (W0-W12)' -> ('TNF 억제제', (0, 12), [gloss refs], [untranslated originals])."""
    name = _KIND.sub("", (s or "").strip())
    refs, untranslated, mods, window = [], [], [], None
    m = _WEEKS.search(name)
    if m:
        window, name = (int(m.group(1)), int(m.group(2))), name[:m.start()]
    m = _DOSE_NO.search(name)
    if m:
        mods.append(f"용량 {m.group(1)}")
        name = name[:m.start()]
    m = _LEVEL.search(name)
    if m:
        mods.append(LEVEL_KO[m.group(1).lower()])
        name = name[:m.start()]
    m = _AMOUNT.search(name)
    if m:
        mods.append(m.group(1))
        name = name[:m.start()]
    m = None if _lookup(name) else _INJ.search(name)   # a glossary name ending in "Injection" stays whole
    if m:   # "QXL138AM Injection every 2 weeks by IV Infusion" -> QXL138AM(2주마다 정맥 주사)
        mods.insert(0, (f"{m.group(1)}주마다 " if m.group(1) else "") + ("정맥 주사" if m.group(2) else "주사"))
        name = name[:m.start()]
    name = _ADMIN.sub("", name).strip()
    if _PLACEBO.match(name):
        hit = _lookup("Placebo")
        text = hit[0] if hit else "위약"
        if hit:
            refs.append(hit[1])
    else:
        m = _PAREN.match(name)
        if m and not _lookup(name):
            text = _render_list(m.group(1).strip(), refs, untranslated) + "(" + \
                _render_list(m.group(2).strip(), refs, untranslated) + ")"
        else:
            text = _render_list(name, refs, untranslated)
    if mods:
        text += "(" + ", ".join(mods) + ")"
    return text, window, refs, untranslated


def _arm_text(interventions):
    items, refs, untr = [], [], []
    for s in interventions:
        t, w, r, u = render_intervention(s)
        refs += r
        untr += u
        items.append([t, w])
    timed = [x for x in items if x[1]]
    if timed and len(timed) == len(items):
        timed.sort(key=lambda x: x[1])
        merged = []
        for t, w in timed:
            if merged and merged[-1][0] == t and merged[-1][1][1] == w[0]:
                merged[-1][1] = (merged[-1][1][0], w[1])
            else:
                merged.append([t, w])
        text = " → ".join(f"{t}({a}~{b}주)" for t, (a, b) in merged)
    else:
        text = " + ".join(dict.fromkeys(t for t, _ in items))
    return text, refs, untr


def arms_sentence(trial):
    """(sentence, gloss refs, untranslated originals) or None when the trial lists no arm interventions."""
    arms = [a for a in trial.get("arms") or [] if a.get("interventions") or a.get("type") == "NO_INTERVENTION"]
    if not arms:
        return None
    rows, refs, untr = [], [], []
    for a in sorted(arms, key=lambda a: ROLE_ORDER.index(a.get("type")) if a.get("type") in ROLE else len(ROLE)):
        role = ROLE.get(a.get("type"), "기타군")
        if a.get("type") == "NO_INTERVENTION":
            text = "시험 치료 없음"
        else:
            text, r, u = _arm_text(a.get("interventions"))
            refs += r
            untr += u
        if (role, text) not in rows:
            rows.append((role, text))
    count = {}
    for role, _ in rows:
        count[role] = count.get(role, 0) + 1
    seen, parts = {}, []
    for role, text in rows[:MAX_ARMS]:
        seen[role] = seen.get(role, 0) + 1
        parts.append(f"{role}{' ' + str(seen[role]) if count[role] > 1 else ''}: {text}")
    rest = len(rows) - MAX_ARMS
    sent = ", ".join(parts) + (f" 외 {rest}개 군." if rest > 0 else ".")
    return sent, sorted(set(refs)), list(dict.fromkeys(untr))
