"""graph_<pid>.json → SVG / 단독 HTML (실제 그래프 파일을 그대로 그린다).

  python3 -m agent4.viz runs/dev/graph_SYN-0001.json            # → graph_SYN-0001.html
  python3 -m agent4.viz graph.json --out view.html [--svg-only]

열: Agent 3 판정 | Agent 4 격하 판정 | 근거 | 문서.  시험별로 기준(행)을 묶는다.
색: 청록 = 검증 통과 / 코랄 = 격하·충돌·없는 근거 / 회색 = 중립.
"""
import json, sys, argparse
from pathlib import Path

W, ROW, BH = 680, 48, 38
X_V1, X_V2, X_EV, X_DOC = 10, 190, 380, 560
W_V, W_EV, W_DOC = 140, 130, 110


def _short(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def _val(v):
    if v is True: return "true"
    if v is False: return "false"
    if isinstance(v, list): return "~".join(str(x) for x in v)
    return str(v)


def render_svg(g: dict) -> str:
    nodes = {n["id"]: n for n in g["nodes"]}
    edges = g["edges"]
    out_of = lambda nid, rel: [e for e in edges if e["src"] == nid and e["rel"] == rel]

    # --- 행: 시험 → 기준 순서 -------------------------------------------------
    trials = sorted(n["id"] for n in nodes.values() if n["type"] == "trial")
    row_y, groups, y = {}, [], 64
    for t in trials:
        crits = [e["dst"] for e in out_of(t, "has_criterion")]
        groups.append((t, y - 16))
        for c in crits:
            row_y[c] = y
            y += ROW
        y += 24
    height_rows = y

    # 기준별 판정 (#1 = Agent 3 원본, #2 = Agent 4 격하)
    v1, v2 = {}, {}
    for n in nodes.values():
        if n["type"] != "verdict":
            continue
        (v2 if n.get("by") == "agent4" else v1)[f"crit:{n['criterion_id']}"] = n
    row_idx = {c: i for i, c in enumerate(sorted(row_y, key=row_y.get))}

    # --- 근거 배치: 지지하는 판정의 평균 행 순서 ------------------------------
    sup = {}
    for c, v in v1.items():
        for e in out_of(v["id"], "supported_by"):
            sup.setdefault(e["dst"], []).append(row_idx[c])
    conf = [(e["src"], e["dst"]) for e in edges if e["rel"] == "conflicts_with"]
    key = {}
    for ev in (n["id"] for n in nodes.values() if n["type"] == "evidence"):
        key[ev] = sum(sup[ev]) / len(sup[ev]) if ev in sup else 99
    for a, b in conf:
        if a in sup and b not in sup:
            key[b] = key[a] + 0.1
    ghosts = {}
    for c, v in v1.items():
        for mid in v.get("missing_evidence_ids") or []:
            gid = f"ghost:{mid}"
            ghosts[gid] = (c, mid)
            key[gid] = row_idx[c] + 0.05
    order = sorted(key, key=lambda k: (key[k], k))
    ev_y = {nid: 64 + i * 52 for i, nid in enumerate(order)}
    height = max(height_rows, 64 + len(order) * 52) + 30

    # 문서 배치
    doc_ev = {}
    for e in edges:
        if e["rel"] == "from":
            doc_ev.setdefault(e["dst"], []).append(e["src"])
    docs = sorted(doc_ev, key=lambda d: sum(ev_y[x] for x in doc_ev[d]) / len(doc_ev[d]))
    doc_y, last = {}, -99
    for d in docs:
        want = sum(ev_y[x] for x in doc_ev[d]) / len(doc_ev[d])
        last = max(want, last + 52)
        doc_y[d] = last
    height = max(height, last + BH + 30)

    # --- 그리기 ----------------------------------------------------------------
    s = [f'<svg width="100%" viewBox="0 0 {W} {int(height)}" role="img"><title>Evidence Graph</title>'
         f'<desc>환자 {g.get("patient_id")} 의 판정 근거 그래프</desc>'
         '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
         '<path d="M2 1L8 5L2 9" fill="none" stroke="context-stroke" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></marker></defs>']
    for x, w, name in ((X_V1, W_V, "Agent 3 판정"), (X_V2, W_V, "Agent 4 격하"), (X_EV, W_EV, "근거"), (X_DOC, W_DOC, "문서")):
        s.append(f'<text class="ts" x="{x + w / 2}" y="20" text-anchor="middle">{name}</text>')
    for t, gy in groups:
        s.append(f'<text class="th" x="{X_V1}" y="{gy}">시험 {t.split(":")[1]}</text>')

    def curve(x1, y1, x2, y2, color, wd=1, dash=None, op=0.55, marker=True):
        mx = (x1 + x2) / 2
        d = f'M{x1} {y1} C{mx} {y1},{mx} {y2},{x2} {y2}'
        da = f' stroke-dasharray="{dash}"' if dash else ""
        mk = ' marker-end="url(#arrow)"' if marker else ""
        s.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{wd}" opacity="{op}"{da}{mk}/>')

    shared = {ev for ev, rows in sup.items() if len(rows) >= 2}
    # 간선 (박스 아래에 깔리도록 먼저)
    for c, v in v1.items():
        cy = row_y[c] + BH / 2
        right = X_V2 + W_V if c in v2 else X_V1 + W_V
        for e in out_of(v["id"], "supported_by"):
            hot = e["dst"] in shared
            curve(X_V1 + W_V if c not in v2 else X_V2 + W_V, cy, X_EV, ev_y[e["dst"]] + BH / 2,
                  "#1D9E75" if hot else "#888780", 2 if hot else 1, op=0.8 if hot else 0.5)
        for mid in v.get("missing_evidence_ids") or []:
            gid = f"ghost:{mid}"
            curve(X_V2 + W_V, cy, X_EV, ev_y[gid] + BH / 2, "#D85A30", 1.2, "4 3", 0.8)
    for d, evs in doc_ev.items():
        for ev in evs:
            curve(X_EV + W_EV, ev_y[ev] + BH / 2, X_DOC, doc_y[d] + BH / 2, "#888780", 1, op=0.4)
    for a, b in conf:
        ya, yb = sorted((ev_y[a], ev_y[b]))
        xx = X_EV + W_EV / 2
        s.append(f'<line x1="{xx}" y1="{ya + BH}" x2="{xx}" y2="{yb}" stroke="#D85A30" stroke-width="2.5"/>')
        s.append(f'<text class="ts" x="{xx + 8}" y="{(ya + BH + yb) / 2 + 4}" fill="#D85A30">충돌</text>')

    # 판정 박스
    for c, v in v1.items():
        y0, cn = row_y[c], nodes[c]
        label = f'{cn["criterion_id"].split("-")[-1]} · {_short(cn.get("concept") or "—", 14)}'
        if c in v2:
            s.append(f'<g class="c-gray"><rect x="{X_V1}" y="{y0}" width="{W_V}" height="{BH}" rx="6" stroke-width="0.5"/>'
                     f'<text class="th" x="{X_V1 + W_V / 2}" y="{y0 + 13}" text-anchor="middle" dominant-baseline="central">{label}</text>'
                     f'<text class="ts" x="{X_V1 + W_V / 2}" y="{y0 + 28}" text-anchor="middle" dominant-baseline="central">{v["status"]}</text></g>')
            n2 = v2[c]
            chk = next((e.get("check") for e in edges if e["src"] == n2["id"] and e["rel"] == "downgraded_from"), "")
            ko = {"grounding": "근거 없음", "relevance": "엉뚱한 근거", "expiry": "기간 만료", "conflict": "근거 충돌"}.get(chk, chk)
            s.append(f'<line x1="{X_V1 + W_V}" y1="{y0 + BH / 2}" x2="{X_V2 - 2}" y2="{y0 + BH / 2}" class="arr" marker-end="url(#arrow)"/>')
            s.append(f'<g class="c-coral"><rect x="{X_V2}" y="{y0}" width="{W_V}" height="{BH}" rx="6" stroke-width="0.5"/>'
                     f'<text class="th" x="{X_V2 + W_V / 2}" y="{y0 + 13}" text-anchor="middle" dominant-baseline="central">{n2["status"]}</text>'
                     f'<text class="ts" x="{X_V2 + W_V / 2}" y="{y0 + 28}" text-anchor="middle" dominant-baseline="central">{ko}</text></g>')
        else:
            s.append(f'<g class="c-teal"><rect x="{X_V1}" y="{y0}" width="{W_V}" height="{BH}" rx="6" stroke-width="0.5"/>'
                     f'<text class="th" x="{X_V1 + W_V / 2}" y="{y0 + 13}" text-anchor="middle" dominant-baseline="central">{label}</text>'
                     f'<text class="ts" x="{X_V1 + W_V / 2}" y="{y0 + 28}" text-anchor="middle" dominant-baseline="central">{v["status"]} · 검증 통과</text></g>')

    # 근거 박스
    for nid in order:
        y0 = ev_y[nid]
        if nid.startswith("ghost:"):
            s.append(f'<g class="c-coral"><rect x="{X_EV}" y="{y0}" width="{W_EV}" height="{BH}" rx="6" stroke-width="0.5" stroke-dasharray="4 3"/>'
                     f'<text class="th" x="{X_EV + W_EV / 2}" y="{y0 + 13}" text-anchor="middle" dominant-baseline="central">{_short(ghosts[nid][1], 14)}</text>'
                     f'<text class="ts" x="{X_EV + W_EV / 2}" y="{y0 + 28}" text-anchor="middle" dominant-baseline="central">존재하지 않음</text></g>')
            continue
        n = nodes[nid]
        eid = nid.split("-")[-1]
        cls = "c-teal" if nid in shared else "c-gray"
        tag = "공유 · " if nid in shared else ""
        s.append(f'<g class="{cls}"><rect x="{X_EV}" y="{y0}" width="{W_EV}" height="{BH}" rx="6" stroke-width="0.5"/>'
                 f'<text class="th" x="{X_EV + W_EV / 2}" y="{y0 + 13}" text-anchor="middle" dominant-baseline="central">{eid} · {_short(n.get("concept"), 10)}</text>'
                 f'<text class="ts" x="{X_EV + W_EV / 2}" y="{y0 + 28}" text-anchor="middle" dominant-baseline="central">{tag}{_short(_val(n.get("value")), 8)} · {str(n.get("observed_date") or "")[5:]}</text></g>')
    # 문서 박스
    for d in docs:
        n, y0 = nodes[d], doc_y[d]
        s.append(f'<g class="box"><rect x="{X_DOC}" y="{y0}" width="{W_DOC}" height="{BH}" rx="6" stroke-width="0.5"/>'
                 f'<text class="th" x="{X_DOC + W_DOC / 2}" y="{y0 + 13}" text-anchor="middle" dominant-baseline="central">{d.split("-")[-1]}</text>'
                 f'<text class="ts" x="{X_DOC + W_DOC / 2}" y="{y0 + 28}" text-anchor="middle" dominant-baseline="central">{_short(n.get("doc_type") or "문서", 12)}</text></g>')
    s.append("</svg>")
    return "".join(s)


_HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Evidence Graph — {pid}</title><style>
:root{{--bg:#fff;--fg:#2c2c2a;--fg2:#5f5e5a;--line:#888780}}
@media(prefers-color-scheme:dark){{:root{{--bg:#1f1e1b;--fg:#f1efe8;--fg2:#b4b2a9}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}}
.t{{fill:var(--fg);font-size:14px}}.ts{{fill:var(--fg2);font-size:12px}}.th{{fill:var(--fg);font-size:14px;font-weight:500}}
.box rect{{fill:none;stroke:var(--line)}}.arr{{stroke:var(--line);stroke-width:1.5}}
.c-gray rect{{fill:#f1efe8;stroke:#5f5e5a}}.c-teal rect{{fill:#e1f5ee;stroke:#0f6e56}}.c-coral rect{{fill:#faece7;stroke:#993c1d}}
.c-gray .th,.c-gray .ts{{fill:#2c2c2a}}.c-teal .th{{fill:#085041}}.c-teal .ts{{fill:#0f6e56}}.c-coral .th{{fill:#712b13}}.c-coral .ts{{fill:#993c1d}}
@media(prefers-color-scheme:dark){{.c-gray rect{{fill:#444441;stroke:#b4b2a9}}.c-teal rect{{fill:#085041;stroke:#5dcaa5}}.c-coral rect{{fill:#712b13;stroke:#f0997b}}
.c-gray .th,.c-gray .ts{{fill:#f1efe8}}.c-teal .th,.c-teal .ts{{fill:#e1f5ee}}.c-coral .th,.c-coral .ts{{fill:#faece7}}}}
.legend{{color:var(--fg2);font-size:13px;margin:8px 0}}
</style></head><body><h1 style="font-size:18px;font-weight:500;margin:0 0 4px">Evidence Graph — {pid}</h1>
<div class="legend">청록 = 검증 통과·공유 근거 / 코랄 = 격하·충돌·없는 근거 / 회색 = 중립 · 기준일 {as_of}</div>{svg}</body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("graph"); ap.add_argument("--out"); ap.add_argument("--svg-only", action="store_true")
    a = ap.parse_args()
    g = json.load(open(a.graph, encoding="utf-8"))
    svg = render_svg(g)
    out = Path(a.out) if a.out else Path(a.graph).with_suffix(".svg" if a.svg_only else ".html")
    out.write_text(svg if a.svg_only else _HTML.format(pid=g.get("patient_id"), as_of=g.get("as_of"), svg=svg), encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
