#!/usr/bin/env python3
"""①-b 후처리 (합성 담당 검토 REVIEW_1b_dev_v1 반영). API 호출 없음.

  python3 fix_1b.py --in out/dev_v1 --out out/dev_v2 [--concepts concepts.json]

1. administrative 가 비어 있는 줄을 true/false 로 채운다.
   - LLM 이 행정 항목으로 본 줄(admin_candidates.csv) → true, 나머지 → false. 이미 값이 있으면 그대로.
2. logic_group 을 "여러 줄에 걸친 선택지 묶음" 으로 다시 만든다.
   - 기존 한 줄짜리 그룹(1,508개, 전부 단독)은 `inline_relation` 필드로 옮기고 logic_group 은 비운다.
   - (a) "… OR" / "…, or" 로 끝나는 줄은 다음 줄과 같은 묶음 (연쇄).
   - (b) "one/any/all of the following …:" 으로 끝나는 부모 줄은 뒤따르는 줄들과 같은 묶음.
       자식은 새 문장 주어("The subject", "Participant", "Age", "Must", "Willing" …)로 시작하는 줄이나
       다른 부모 줄을 만나면 끝. relation 은 "all of the following" 이면 AND, 그 외 OR.
   - 묶음 목록은 logic_groups_review.csv 로 내보내 사람이 확인한다.
3. 단위 오류 2건: NCT07655700-I03 (발작 횟수 ≠ 편두통 일수 → 새 개념 migraine_attack_frequency),
   NCT07594145-I07 (UACR "mg/dl" 는 원문 오타 → mg/g, note 기록).
4. CHANGES.md 에 변경 요약.
"""
import argparse, csv, json, re, shutil
from collections import Counter, defaultdict
from pathlib import Path

END_OR = re.compile(r"(?:\b(?:or|and/or)|\bOR)\s*[:;,.]?\s*$")
PARENT = re.compile(r"(?:one|any|all|either|at least \w+|\d+)\s+(?:or more\s+)?of\s+the\s+following[^:]{0,40}:\s*$|following\s+(?:criteria|conditions)\s*:\s*$|as follows\s*:\s*$|either\s*[;:]\s*$", re.I)
ALL_OF = re.compile(r"\ball of the following", re.I)
NEW_SUBJECT = re.compile(r"^(?:the\s+)?(?:subject|participant|patient|individual|women|men|female|male)s?\b|^(?:age|aged|must|willing|able|signed|informed|life expectancy|ecog|karnofsky|body mass|bmi|weight|adequate)\b", re.I)
LETTER_RANGE = re.compile(r"\(\s*a\s*[-–]\s*([a-z])\s*\)", re.I)   # "(a-e)" → 자식 5개

UNIT_FIXES = {
    "NCT07655700-I03": {"concept": "migraine_attack_frequency", "unit": "attacks/month",
                        "note": "발작 횟수는 편두통 일수(monthly_migraine_days)와 다른 개념 → 새 개념 migraine_attack_frequency"},
    "NCT07594145-I07": {"unit": "mg/g",
                        "note": "원문 'UACR > 30 mg/dl' 은 단위 오타로 판단 (UACR 30 mg/g 가 표준 역치). 값은 그대로"},
}
NEW_CONCEPTS = [
    {"key": "migraine_attack_frequency", "name": "Migraine attack frequency", "type": "measurement",
     "unit": "attacks/month", "aliases": ["migraine attacks per month", "attacks/month"]},
]


def load_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def suffix_num(cid):
    m = re.search(r"-([IEU])(\d+)(?:\.(\d+))?$", cid)
    return (m.group(1), int(m.group(2)), int(m.group(3) or 0)) if m else None


def build_groups(rows):
    """같은 시험·같은 type 안에서 등장 순서대로 보며 여러 줄 묶음을 찾는다. 반환: {criterion_id: (group_id, relation, role)}"""
    out = {}
    by = defaultdict(list)
    for c in rows:
        by[(c["trial_id"], c["type"])].append(c)
    for key, lst in by.items():
        lst.sort(key=lambda c: suffix_num(c["criterion_id"]) or (c["criterion_id"], 0, 0))
        i = 0
        while i < len(lst):
            t = lst[i]["original_text"].strip()
            members, relation = [], None
            if PARENT.search(t):
                relation = "AND" if ALL_OF.search(t) else "OR"
                members = [lst[i]]
                m = LETTER_RANGE.search(t)
                limit = (ord(m.group(1).lower()) - ord("a") + 1) if m else 8
                j = i + 1
                while j < len(lst) and len(members) - 1 < limit:
                    tj = lst[j]["original_text"].strip()
                    if PARENT.search(tj) or (NEW_SUBJECT.match(tj) and not END_OR.search(lst[j - 1]["original_text"].strip())):
                        break
                    members.append(lst[j])
                    j += 1
                if len(members) >= 2:
                    i = j - 1
            elif END_OR.search(t):
                relation = "OR"
                members = [lst[i]]
                j = i + 1
                while j < len(lst):
                    members.append(lst[j])
                    if not END_OR.search(lst[j]["original_text"].strip()):
                        break
                    j += 1
                if len(members) >= 2:
                    i = j
            if len(members) >= 2 and relation:
                gid = f"{members[0]['criterion_id']}-G"
                for k, m in enumerate(members):
                    out[m["criterion_id"]] = (gid, relation, "parent" if (k == 0 and PARENT.search(t)) else "member")
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--concepts", default=None, help="기본: <in>/concepts.json")
    a = ap.parse_args()
    IN, OUT = Path(a.inp), Path(a.out)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = load_jsonl(IN / "criteria.jsonl")
    cpath = Path(a.concepts) if a.concepts else IN / "concepts.json"
    concepts = json.load(open(cpath, encoding="utf-8"))
    keys = {c["key"] for c in concepts}
    for nc in NEW_CONCEPTS:
        if nc["key"] not in keys:
            concepts.append(nc); keys.add(nc["key"])

    admin_ids = set()
    ap_ = IN / "admin_candidates.csv"
    if ap_.exists():
        admin_ids = {r["criterion_id"] for r in csv.DictReader(open(ap_, encoding="utf-8-sig"))}

    stats = Counter()
    # 1) administrative
    for c in rows:
        if c.get("administrative") is None:
            c["administrative"] = c["criterion_id"] in admin_ids
            stats["admin_filled_true" if c["administrative"] else "admin_filled_false"] += 1
            if c["administrative"] and c.get("concept"):
                c["concept"], c["term"], c["operator"], c["value"], c["unit"] = None, None, None, None, None
                c["parse_status"] = "free_text"

    # 2) logic_group
    for c in rows:
        lg = c.get("logic_group")
        c["inline_relation"] = lg["relation"] if isinstance(lg, dict) else None
        c["logic_group"] = None
    groups = build_groups(rows)
    for c in rows:
        if c["criterion_id"] in groups:
            gid, rel, role = groups[c["criterion_id"]]
            c["logic_group"] = {"group_id": gid, "relation": rel, "role": role}
            stats["logic_group_members"] += 1
    stats["logic_groups"] = len({g[0] for g in groups.values()})

    # 3) unit fixes
    for c in rows:
        f = UNIT_FIXES.get(c["criterion_id"])
        if f:
            for k, v in f.items():
                if k != "note":
                    c[k] = v
            c["fix_note"] = f["note"]
            stats["unit_fixed"] += 1

    # write
    with open(OUT / "criteria.jsonl", "w", encoding="utf-8") as fo:
        for c in rows:
            fo.write(json.dumps(c, ensure_ascii=False) + "\n")
    json.dump(concepts, open(OUT / "concepts.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for name in ("structure_review.csv", "time_window_review.csv", "concepts_unlisted.json", "structure_overrides.json", "admin_candidates.csv"):
        if (IN / name).exists():
            shutil.copy(IN / name, OUT / name)
    with open(OUT / "logic_groups_review.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["group_id", "relation", "role", "criterion_id", "original_text"])
        byid = {c["criterion_id"]: c for c in rows}
        for cid, (gid, rel, role) in sorted(groups.items(), key=lambda x: (x[1][0], x[0])):
            w.writerow([gid, rel, role, cid, byid[cid]["original_text"]])
    adm = Counter(str(c["administrative"]) for c in rows)
    (OUT / "CHANGES.md").write_text(f"""# ①-b dev v2 변경 (fix_1b.py)

합성 담당 검토(REVIEW_1b_dev_v1) 반영. API 호출 없음. criterion_id·original_text 변경 없음.

1. administrative: 비어 있던 {stats['admin_filled_true']+stats['admin_filled_false']}줄을 채움 (true {stats['admin_filled_true']}, false {stats['admin_filled_false']}). 최종 분포: {dict(adm)}.
   true 로 바뀐 줄은 concept 를 비우고 parse_status=free_text.
2. logic_group: 한 줄짜리 그룹은 `inline_relation` 으로 이동, logic_group 은 여러 줄 선택지 묶음만. 묶음 {stats['logic_groups']}개 / {stats['logic_group_members']}줄.
   relation: OR (기본) / AND ("all of the following"). role: parent(“… of the following:” 줄) / member. 목록: logic_groups_review.csv
3. 단위 수정 {stats['unit_fixed']}건: NCT07655700-I03 → migraine_attack_frequency (새 개념), NCT07594145-I07 unit mg/dl → mg/g (fix_note 참조).
4. concepts.json: {len(concepts)}개 (migraine_attack_frequency 추가).
""", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False), "| administrative:", dict(adm))


if __name__ == "__main__":
    main()
