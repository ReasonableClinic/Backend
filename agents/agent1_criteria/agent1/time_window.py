#!/usr/bin/env python3
"""①-b 중 time_window를 규칙으로 채운다 (v0.5: 입력 파일 전체 행 대상, 원본은 수정하지 않음).

사용법:
  python3 fill_time_window.py --criteria ~/Downloads/for_agent3_v2/dev/reference/criteria.jsonl --out out/dev

입력:  out/criteria.jsonl, out/trial_candidates.jsonl
출력:  out/criteria.jsonl               time_window 채워진 버전으로 덮어씀
       out/criteria_split_only.jsonl    덮어쓰기 전 백업 (처음 한 번만)
       out/time_window_review.csv       사람이 훑어볼 표: criterion_id, 원문, 추출 결과, 플래그

time_window 형식 (공통 형식 v0.4의 {anchor, max_days_before}에 kind·min_days_before를 추가):
  {"anchor": "as_of", "max_days_before": 28, "kind": "lookback"}
      "within 4 weeks prior to screening" — as_of 기준 28일 안에 있었는지 본다 (검사 유효기간, 최근 투약 금지 등)
  {"anchor": "as_of", "min_days_before": 180, "kind": "min_elapsed"}
      "at least 6 months since last dose" — as_of 기준 180일 이상 지났어야 한다 (휴약기간, 안정 기간)
expired 변형은 kind == "lookback"인 기준에서 고르면 된다.
"""
import argparse, csv, json, re, shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"

DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
NUMWORD = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "twelve": 12, "fourteen": 14, "twenty-four": 24, "twenty-eight": 28, "thirty": 30}
NUM = r"(\d+(?:\.\d+)?|" + "|".join(NUMWORD) + r")"
UNIT = r"(days?|weeks?|wks?|months?|mos?|years?|yrs?)"

# 되돌아보는 창: "within 4 weeks (prior to|before) X", "in the past 2 years", "<= 28 days before", "in the previous 6 months"
LOOKBACK = re.compile(
    rf"\b(?:within|in the (?:past|last|previous|preceding)|during the (?:past|last|previous)|over the (?:past|last)|"
    rf"<=?|less than|no more than|not more than|up to|during)\s*(?:the\s+)?(?:last\s+|past\s+)?{NUM}\s*{UNIT}\b"
    rf"(?!\s*(?:after|following|post|from the start|of (?:study|treatment) (?:start|initiation)))", re.I)
LOOKBACK2 = re.compile(rf"\b{NUM}\s*{UNIT}\s+(?:or less\s+)?(?:prior to|before|preceding)\b", re.I)

# 최소 경과: "at least 4 weeks (since|after|before|from)", ">= 6 months since", "more than 2 years ago", "for at least 3 months"
MIN_ELAPSED = re.compile(
    rf"\b(?:at least|>=?|≥|more than|greater than|minimum of|a minimum of|no less than|not less than|for at least|over)\s*{NUM}\s*{UNIT}\b", re.I)
MIN_ELAPSED2 = re.compile(rf"\b{NUM}\s*{UNIT}\s+(?:or more|or longer|or greater)\b", re.I)

# 기간 표현이지만 유효기간이 아닌 것들 — 이 단어가 바로 앞 60자 안에 있으면 건너뜀
NOT_WINDOW = re.compile(
    r"life expectancy|survival|duration of (?:study|treatment|follow)|throughout|for the duration|after (?:the )?(?:last|final) dose of study|"
    r"follow[- ]?up|half-lives|aged?\b|years?\s+(?:of\s+age|old)|age\s*[<>=]|washout|dosing interval|every \d+ (?:weeks?|days?)|"
    r"q\d+w|cycle|per (?:day|week)|times? (?:per|a) (?:day|week)|anticipated|expected to|planned|will (?:be|require)|plans? to|"
    r"contracept|pregnan|breast[- ]?feed|lactat", re.I)


def to_days(n, unit):
    n = NUMWORD.get(n.lower(), None) if not re.match(r"\d", n) else float(n)
    if n is None:
        return None
    u = unit.lower().rstrip("s")
    u = {"wk": "week", "mo": "month", "yr": "year"}.get(u, u)
    d = n * DAYS[u]
    return int(d) if d == int(d) else round(d, 1)


# 숫자 바로 앞에 '>=', '>', 'more than', 'for (the past)' 가 있으면 "N일 이상 지났어야/유지했어야" 조건 → min_elapsed
MIN_PREFIX = re.compile(r"(?:>=|≥|>/=|>|\(>=?\)|more than|greater than(?: or equal to)?(?: \(>=?\))?|longer than|for(?:\s+the\s+(?:past|last|previous))?)\s*$", re.I)


def extract(text):
    """(time_window dict or None, flags list)"""
    flags = []
    cands = []  # (position, kind, days, matched)
    for kind, pats in (("lookback", (LOOKBACK, LOOKBACK2)), ("min_elapsed", (MIN_ELAPSED, MIN_ELAPSED2))):
        for p in pats:
            for m in p.finditer(text):
                before = text[max(0, m.start() - 60):m.start()]
                after = text[m.end():m.end() + 30]
                if NOT_WINDOW.search(before + " " + m.group(0) + " " + after):
                    continue
                d = to_days(m.group(1), m.group(2))
                if d is None or d <= 0:
                    continue
                k = kind
                if kind == "lookback":
                    # 'within' 류가 아니라 'N units before' 꼴이고 바로 앞에 >= / for 가 있으면 최소 경과 조건
                    num_start = m.start(1)
                    if not re.match(r"(?:within|in the|during|over the|<=?|less than|no more than|not more than|up to)", m.group(0), re.I) \
                            and MIN_PREFIX.search(text[max(0, num_start - 25):num_start]):
                        k = "min_elapsed"
                cands.append((m.start(), m.end(), k, d, m.group(0)))
    if not cands:
        return None, flags
    cands.sort(key=lambda c: (c[0], 0 if c[2] == "lookback" else 1))
    # 겹치는 구간은 하나로 (같은 구절을 두 패턴이 잡은 경우 lookback 우선)
    dedup = []
    for c in cands:
        if any(c[0] < e and c[1] > s_ for s_, e, *_ in dedup):
            continue
        dedup.append(c)
    if len(dedup) > 1:
        flags.append("multi_window")  # 기준 하나에 창이 여러 개 → 첫 번째만 채움, 사람이 확인
    pos, end, kind, d, matched = dedup[0]
    tw = {"anchor": "as_of", "max_days_before": None, "min_days_before": None, "kind": kind, "matched": matched}
    tw["max_days_before" if kind == "lookback" else "min_days_before"] = d
    if re.search(r"half-li", text, re.I):
        flags.append("half_life_alt")  # "or 5 half-lives, whichever is longer"
    if kind == "lookback" and re.search(r"\b(stable|unchanged|same dose)\b", text, re.I):
        flags.append("maybe_duration")  # "stable dose within 4 weeks"는 사실 기간 조건일 수 있음
    return tw, flags


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", required=True, help="입력 criteria.jsonl (예: for_agent3_v2/dev/reference/criteria.jsonl). 원본은 수정하지 않음")
    ap.add_argument("--out", required=True, help="출력 폴더 (예: out/dev)")
    a = ap.parse_args()

    global OUT
    OUT = Path(a.out); OUT.mkdir(parents=True, exist_ok=True)
    src = Path(a.criteria)                      # 원본(합성 담당 파일)은 읽기만 한다
    crit_path = OUT / "criteria.jsonl"          # 결과는 out 폴더에 새로 쓴다
    target = None                               # 전체 행 대상

    ov_path = HERE / "time_window_overrides.json"   # 사람이 검수해서 고친 값 (criterion_id → time_window)
    overrides = json.load(open(ov_path, encoding="utf-8")) if ov_path.exists() else {}
    rows, n_target, n_filled, n_flag, n_ov = [], 0, 0, 0, 0
    with open(crit_path, "w", encoding="utf-8") as fo:
        for line in open(src, encoding="utf-8"):
            c = json.loads(line)
            if target is None or c["trial_id"] in target:
                n_target += 1
                tw, flags = extract(c["original_text"])
                if c["criterion_id"] in overrides:
                    tw = overrides[c["criterion_id"]]["time_window"]
                    flags = ["reviewed"]
                    n_ov += 1
                    if tw:
                        tw = {"anchor": "as_of", "max_days_before": None, "min_days_before": None, **tw, "matched": "manual"}
                if tw:
                    c["time_window"] = tw
                    n_filled += 1
                    n_flag += bool(flags)
                    rows.append([c["criterion_id"], c["type"], tw["kind"],
                                 tw.get("max_days_before", ""), tw.get("min_days_before", ""),
                                 tw["matched"], ";".join(flags), c["original_text"]])
                elif c["criterion_id"] in overrides:
                    rows.append([c["criterion_id"], c["type"], "none", "", "", "manual", "reviewed", c["original_text"]])
            fo.write(json.dumps(c, ensure_ascii=False) + "\n")

    with open(OUT / "time_window_review.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["criterion_id", "type", "kind", "max_days_before", "min_days_before", "matched_phrase", "flags", "original_text"])
        w.writerows(rows)
    print(f"대상 기준 {n_target}줄 중 time_window 채움 {n_filled}줄 (확인 필요 플래그 {n_flag}줄, 수동 검수 반영 {n_ov}줄)")
    print(f"→ {crit_path} 갱신, 검수표 {OUT / 'time_window_review.csv'}")


if __name__ == "__main__":
    main()
