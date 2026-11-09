"""Link Agent 6 briefing sentences to Agent 5 cards (a6-0.4.8). Does not change the briefings.

  python3 scripts/link_cards.py --briefings dev_out/briefing --cards <agent5 cards.jsonl ...> \
      [--graphs <graph dirs>] --out runs/card_links.jsonl

Join key: a briefing ref `dec:<trial_id>:<criterion_id>:r<n>` ↔ a card item (`patient_id`, `items[].trial_id`,
`items[].criterion_id`). One sentence can link to several cards and one card to several sentences.
Writes one line per sentence that links: {patient_id, audience, i (sentence index), text, cards: [card_id], types}.
Prints coverage: share of dec refs with a card, and (patient briefing) whether each route sentence ("직접 답해 주실 수
있는 질문", "진료 기록에서 찾아볼 것", "검사 결과가 필요한 것", "담당 의사가 판단할 것") links only to cards of the
matching type. With --graphs, unlinked refs are counted by (status, reason, action) so gaps can be read as
"other card owner" (a5u: clinician_confirmation, new_test, EXPIRED, CONFLICT) or "no card needed" (PASS).
"""
import argparse, collections, glob, json, os

ROUTE = {"직접 답해 주실 수 있는 질문": ("patient_question",), "진료 기록에서 찾아볼 것": ("med_record_check", "med_history_check"),
         "검사 결과가 필요한 것": ("lab_check", "new_test"), "담당 의사가 판단할 것": ("clinician_confirmation",)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--briefings", required=True)
    ap.add_argument("--cards", nargs="+", required=True)
    ap.add_argument("--graphs", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    by, ctype = collections.defaultdict(set), {}
    for f in a.cards:
        for line in open(f, encoding="utf-8"):
            if line.strip():
                c = json.loads(line)
                ctype[c["card_id"]] = c["type"]
                for it in c["items"]:
                    by[(c["patient_id"], it["trial_id"], it["criterion_id"])].add(c["card_id"])
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    stats = {aud: collections.Counter() for aud in ("patient", "clinician")}
    gaps = collections.Counter()
    with open(a.out, "w", encoding="utf-8") as out:
        for p in sorted(glob.glob(os.path.join(a.briefings, "*.json"))):
            d = json.load(open(p, encoding="utf-8"))
            aud, pid = d.get("audience"), d.get("patient_id")
            if aud not in stats:
                continue
            nodes = {}
            if a.graphs:
                gp = next((os.path.join(g, f"{pid}.json") for g in a.graphs if os.path.exists(os.path.join(g, f"{pid}.json"))), None)
                nodes = {n["id"]: n for n in json.load(open(gp, encoding="utf-8"))["nodes"]} if gp else {}
            for i, s in enumerate(d["sentences"]):
                got = set()
                for r in s.get("refs", []):
                    if not r.startswith("dec:"):
                        continue
                    _, tid, cid, _ = r.split(":")
                    stats[aud]["dec_refs"] += 1
                    k = by.get((pid, tid, cid))
                    if k:
                        stats[aud]["linked"] += 1
                        got |= k
                    elif r in nodes:
                        n = nodes[r]
                        gaps[(aud, n.get("status"), n.get("reason"), n.get("action"))] += 1
                if not got:
                    continue
                types = sorted({ctype[c] for c in got})
                out.write(json.dumps({"patient_id": pid, "audience": aud, "i": i, "text": s["text"],
                                      "cards": sorted(got), "types": types}, ensure_ascii=False) + "\n")
                stats[aud]["sentences"] += 1
                want = next((v for k, v in ROUTE.items() if s["text"].startswith(k)), None)
                if aud == "patient" and want:
                    stats[aud]["route_match" if set(types) <= set(want) else "route_mismatch"] += 1
    for aud, c in stats.items():
        cov = c["linked"] / c["dec_refs"] if c["dec_refs"] else 0
        extra = f", route sentences matching card type {c['route_match']}/{c['route_match'] + c['route_mismatch']}" if aud == "patient" else ""
        print(f"[{aud}] dec refs {c['dec_refs']}, with a card {c['linked']} ({cov:.1%}), sentences linked {c['sentences']}{extra}")
    if gaps:
        for aud in ("patient", "clinician"):
            top = [(k[1:], v) for k, v in gaps.most_common() if k[0] == aud][:8]
            print(f"  unlinked [{aud}] by (status, reason, action): " + "; ".join(f"{'/'.join(map(str, k))} {v}" for k, v in top))
    print(f"-> {a.out}")


if __name__ == "__main__":
    main()
