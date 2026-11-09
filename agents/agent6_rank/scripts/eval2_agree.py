"""Layer-2 agreement and results (a6-0.4.5). Reads the filled forms of two or more raters and key.json.

  python3 scripts/eval2_agree.py --key runs/eval2/key.json \
      --clinician rater1/clinician_form.csv rater2/clinician_form.csv \
      --patient rater1/patient_form.csv rater2/patient_form.csv

Agreement (before unblinding, all versions pooled):
  clinician 4-level rating (3 지지됨 / 2 일부 / 1 근거 없음 / 0 모순): linearly weighted Cohen's kappa for exactly two
  raters, Krippendorff's alpha (ordinal) for two or more.
  patient items (1/0, NA dropped): Cohen's kappa for two raters, Krippendorff's alpha (nominal).
Results (after unblinding with key.json): per version (template / llm) the share of sentences rated 지지됨, errors by
severity, and the share of patient items scored 1. Units rated by only one rater count in the results, not in agreement.
"""
import argparse, csv, itertools, json
from collections import Counter, defaultdict


def read_form(path, value):
    rows = [r for r in csv.DictReader(l for l in open(path, encoding="utf-8-sig") if not l.startswith("#"))]
    out = {}
    for r in rows:
        v = (r.get(value) or "").strip()
        if v and v.upper() != "NA":
            unit = (r["code"], r["version"], r.get("sid") or r.get("item"))
            out[unit] = (int(v), (r.get("severity") or "").strip())
    return out


def cohen(a, b, cats, weighted):
    n = len(a)
    if n == 0:
        return None
    k = len(cats)
    idx = {c: i for i, c in enumerate(cats)}
    w = [[(abs(i - j) / (k - 1) if weighted and k > 1 else float(i != j)) for j in range(k)] for i in range(k)]
    obs = sum(w[idx[x]][idx[y]] for x, y in zip(a, b)) / n
    pa, pb = Counter(a), Counter(b)
    exp = sum(w[idx[x]][idx[y]] * pa[x] * pb[y] for x in cats for y in cats) / (n * n)
    return None if exp == 0 else 1 - obs / exp


def kalpha(units, level):
    """units: list of value lists (one per unit, >=2 values). level: 'nominal' or 'ordinal'."""
    units = [u for u in units if len(u) >= 2]
    vals = sorted({v for u in units for v in u})
    if len(vals) < 2:
        return None
    o = defaultdict(float)
    for u in units:
        m = len(u)
        for x, y in itertools.permutations(range(m), 2):
            o[(u[x], u[y])] += 1 / (m - 1)
    nc = {c: sum(o[(c, k)] for k in vals) for c in vals}
    n = sum(nc.values())

    def d(c, k):
        if level == "nominal":
            return float(c != k)
        lo, hi = sorted((c, k))
        s = sum(nc[g] for g in vals if lo <= g <= hi) - (nc[c] + nc[k]) / 2
        return s * s
    do = sum(o[(c, k)] * d(c, k) for c in vals for k in vals)
    de = sum(nc[c] * nc[k] * d(c, k) for c in vals for k in vals) / (n - 1)
    return None if de == 0 else 1 - do / de


def agreement(forms, cats, weighted, level):
    common = set.intersection(*[set(f) for f in forms]) if forms else set()
    res = {"units_all_raters": len(common)}
    if len(forms) == 2:
        a = [forms[0][u][0] for u in sorted(common)]
        b = [forms[1][u][0] for u in sorted(common)]
        res["cohen_kappa" + ("_linear" if weighted else "")] = cohen(a, b, cats, weighted)
    allu = set().union(*[set(f) for f in forms])
    res["krippendorff_alpha_" + level] = kalpha([[f[u][0] for f in forms if u in f] for u in sorted(allu)], level)
    return res


def results(forms, key, kind):
    by = defaultdict(list)
    sev = defaultdict(Counter)
    for f in forms:
        for (code, ab, _), (v, s) in f.items():
            ver = key[code][ab]
            by[ver].append(v)
            if kind == "clinician" and v <= 1:
                sev[ver][s or "미기재"] += 1
    out = {}
    for ver, vs in sorted(by.items()):
        if kind == "clinician":
            out[ver] = {"ratings": len(vs), "지지됨": round(sum(v == 3 for v in vs) / len(vs), 3),
                        "일부": round(sum(v == 2 for v in vs) / len(vs), 3),
                        "근거 없음·모순": round(sum(v <= 1 for v in vs) / len(vs), 3), "severity": dict(sev[ver])}
        else:
            out[ver] = {"ratings": len(vs), "그렇다 비율": round(sum(vs) / len(vs), 3)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", required=True)
    ap.add_argument("--clinician", nargs="*", default=[])
    ap.add_argument("--patient", nargs="*", default=[])
    a = ap.parse_args(argv)
    key = json.load(open(a.key, encoding="utf-8"))
    report = {}
    if a.clinician:
        f = [read_form(p, "rating") for p in a.clinician]
        report["clinician"] = {"raters": len(f), "agreement": agreement(f, [0, 1, 2, 3], True, "ordinal"),
                               "by_version": results(f, key, "clinician")}
    if a.patient:
        f = [read_form(p, "score") for p in a.patient]
        report["patient"] = {"raters": len(f), "agreement": agreement(f, [0, 1], False, "nominal"),
                             "by_version": results(f, key, "patient")}
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
