"""Demo update scene (a6-0.4.13, dev only): one patient's briefing before and after a record change, as the screen
shows it — template sentences by default, the LLM briefing as a comparison toggle.

  python3 scripts/demo_toggle.py --before SYN-0010 --after SYN-4657 \
      --template runs/brief_dev --llm runs/brief_llm_dev --data for_agent456_v6/dev --out demo/SYN-0010

The "after" briefing can come from another run folder (--template-after / --llm-after), e.g. the same patient id
re-run after the patient answered the question cards; by default both sides are read from the same folder.

Writes <out>.json (for the screen) and <out>.md (to read). Per view (template / llm) and audience (patient /
clinician): the sentences before and after, each with refs and a change mark. Sentences are matched before -> after
by their shared refs (dec:/crit:/label:/trial:/rule:/gloss:, the same alignment as eval_update):
  before: same | changed | removed      after: same | changed | new
The LLM view also lists the trial sections that fell back to template sentences (llm_log.jsonl), so the screen can say
"이 부분은 틀 문장" there. Without --llm (or when the files are missing) the llm view is null and the toggle is hidden.
"""
import argparse, csv, json, os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from agent6 import VERSION  # noqa: E402
from agent6.eval_update import align  # noqa: E402


def load(d, pid, aud):
    p = os.path.join(d, f"{pid}.{aud}.json") if d else None
    return json.load(open(p, encoding="utf-8")) if p and os.path.exists(p) else None


def fallbacks(d, pid, aud):
    p = os.path.join(d or "", "llm_log.jsonl")
    if not d or not os.path.exists(p):
        return None
    for line in open(p, encoding="utf-8"):
        r = json.loads(line)
        if r.get("patient_id") == pid and r.get("audience") == aud:
            return r.get("fallback", [])
    return None


def marked(db, dv):
    """a6-0.4.14: when before/after are two patient ids (dev variant), the after patient id is read as the before one
    in refs and text, so evidence lines (ev:/src:, "SYN-4657-D07") match; same text wins at equal ref overlap."""
    pb, pv = db.get("patient_id"), dv.get("patient_id")
    nt = (lambda t: t.replace(pv, pb)) if pb and pv and pb != pv else (lambda t: t)
    sb = [s for s in db["sentences"] if s.get("kind") != "meta"]
    sv = [s for s in dv["sentences"] if s.get("kind") != "meta"]
    rb = [frozenset(s.get("refs", [])) for s in sb]
    rv = [frozenset(nt(r) for r in s.get("refs", [])) for s in sv]
    tb, tv = [s["text"] for s in sb], [nt(s["text"]) for s in sv]
    pairs, extra = align(rb, rv, tb, tv)
    before, after = [], [None] * len(sv)
    for i, j in pairs:
        if j is None:
            mark = "same" if tb[i] in tv else "removed"
        else:
            mark = "same" if tb[i] == tv[j] else "changed"
            after[j] = dict(sv[j], change=mark)
        before.append(dict(sb[i], change=mark))
    texts_b = set(tb)
    for j in extra:
        after[j] = dict(sv[j], change="same" if tv[j] in texts_b else "new")
    return before, after


def view(d, d_after, a, aud):
    db, dv = load(d, a.before, aud), load(d_after, a.after, aud)
    if not db or not dv:
        return None
    before, after = marked(db, dv)
    out = {"before": before, "after": after,
           "ranking": {"before": db.get("ranking"), "after": dv.get("ranking")},
           "glossary": db.get("glossary"), "agent6": dv.get("agent6")}
    fb = fallbacks(d, a.before, aud), fallbacks(d_after, a.after, aud)
    if fb != (None, None):
        out["template_fallback"] = {"before": fb[0], "after": fb[1]}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--before", required=True)
    ap.add_argument("--after", required=True)
    ap.add_argument("--template", required=True)
    ap.add_argument("--llm")
    ap.add_argument("--template-after", help="folder of the after briefing (default: --template)")
    ap.add_argument("--llm-after", help="folder of the after LLM briefing (default: --llm)")
    ap.add_argument("--data", help="K/dev: reads eval/update_pairs.csv and eval/variant_targets.csv for the changed document")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    change = {}
    if a.data:
        for name in ("update_pairs.csv", "variant_targets.csv"):
            p = os.path.join(a.data, "eval", name)
            if os.path.exists(p):
                for r in csv.DictReader(open(p, encoding="utf-8-sig")):
                    if r.get("variant_patient_id") == a.after and r.get("base_patient_id") == a.before:
                        change.update({k: r[k] for k in ("changed_doc_id", "base_doc_id", "trial_id", "target_criterion",
                                                          "expected_status") if r.get(k)})
    doc = {"scene": "update", "before": a.before, "after": a.after, "change": change, "default_view": "template",
           "agent6": VERSION, "views": {}}
    for name, d, d2 in (("template", a.template, a.template_after or a.template), ("llm", a.llm, a.llm_after or a.llm)):
        doc["views"][name] = {aud: view(d, d2, a, aud) for aud in ("patient", "clinician")}
        if not any(doc["views"][name].values()):
            doc["views"][name] = None
    if not doc["views"]["template"]:
        sys.exit(f"no template briefings for {a.before} / {a.after} in {a.template}")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    json.dump(doc, open(a.out + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    sym = {"same": " ", "changed": "~", "removed": "-", "new": "+"}
    with open(a.out + ".md", "w", encoding="utf-8") as f:
        f.write(f"# {a.before} → {a.after} (기록 변경 {change.get('changed_doc_id', '?')})\n\n")
        f.write("표시: `~` 바뀜, `-` 없어짐, `+` 새로 생김. 기본 화면은 틀 문장, LLM은 비교 토글.\n")
        for name in ("template", "llm"):
            for aud in ("patient", "clinician"):
                v = (doc["views"].get(name) or {}).get(aud)
                if not v:
                    continue
                f.write(f"\n## {name} · {aud}\n")
                if v.get("template_fallback"):
                    f.write(f"\n틀 문장 대체: 전 {v['template_fallback']['before']} / 후 {v['template_fallback']['after']}\n")
                for side in ("before", "after"):
                    f.write(f"\n### {'전' if side == 'before' else '후'}\n\n")
                    for s in v[side]:
                        if side == "after" or s["change"] != "same" or aud == "patient":
                            f.write(f"- `{sym[s['change']]}` {s['text']}\n")
    print(f"{a.out}.json / .md | views: " + ", ".join(k for k, v in doc["views"].items() if v))


if __name__ == "__main__":
    main()
