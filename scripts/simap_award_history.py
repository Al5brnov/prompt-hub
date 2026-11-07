#!/usr/bin/env python3
"""Zuschlags-Historie: Zuschläge eines Zeitraums von simap holen (einmalig oder bei Bedarf).

Nutzt dieselben Regeln wie der Radar (radar/config.json): IT-/Beratungs-CPV und Kernbegriffe als Quelle,
Umfang-Prüfung (Software, Beratung, Betrieb, Support), Ausschlusswörter, Relevanz-Score.
Schreibt eine Teildatei (JSON-Zeilen wie radar/awards.json). Zusammenführen mit --merge.

  python scripts/simap_award_history.py --from 2022-11-07 --to 2023-11-06 --out part.json
  python scripts/simap_award_history.py --merge part1.json part2.json ...
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simap_radar as R  # noqa: E402

AWARD_PUBTYPES = ["award", "direct_award"]


def windows(start, end, days):
    a = start
    while a <= end:
        b = min(end, a + dt.timedelta(days=days - 1))
        yield a, b
        a = b + dt.timedelta(days=1)


def search(q, a, b, max_pages, found, label):
    cursor, pages = None, 0
    while pages < max_pages:
        params = [("lang", "de")] + q + [("newestPublicationFrom", a.isoformat()), ("newestPublicationUntil", b.isoformat())]
        params += [("newestPubTypes", t) for t in AWARD_PUBTYPES]
        if cursor:
            params.append(("lastItem", cursor))
        try:
            r = R.get("/publications/v2/project/project-search", params)
        except Exception as e:  # noqa: BLE001
            R.note("Suche %s %s–%s: %s" % (label, a, b, e))
            return
        projects = r.get("projects") or []
        for p in projects:
            pid = p.get("id")
            if not pid or p.get("pubType") not in AWARD_PUBTYPES:
                continue
            if pid in found:
                found[pid]["viaCpv"] = found[pid]["viaCpv"] or label.startswith("cpv:")
                continue
            pubs = [p.get("publicationId")] if p.get("publicationId") else []
            for lot in p.get("lots") or []:
                if lot.get("publicationId") and lot["publicationId"] not in pubs:
                    pubs.append(lot["publicationId"])
            found[pid] = {"id": pid, "pubs": pubs[:3], "nr": p.get("projectNumber"), "title": R.lang_pick(p.get("title")) or "",
                          "office": R.lang_pick(p.get("procOfficeName")) or "", "date": p.get("publicationDate"), "type": p.get("pubType"),
                          "process": p.get("processType"), "titleAll": " ".join(str(x) for x in (p.get("title") or {}).values() if x),
                          "viaCpv": label.startswith("cpv:")}
        cursor = (r.get("pagination") or {}).get("lastItem")
        pages += 1
        if not cursor or not projects:
            break
    if pages >= max_pages and cursor:
        R.note("Seitenlimit erreicht: %s %s–%s (Fenster verkleinern)" % (label, a, b))


def run(start, end, out, window_days, budget):
    cfg = json.load(open(R.CONFIG, encoding="utf-8"))
    core = R.flat_words(cfg.get("core") or cfg.get("keywords"))
    ctx = [w for w in R.flat_words(cfg.get("context")) if w.lower() not in [c.lower() for c in core]]
    core_rx = [(w, R.word_rx(w)) for w in core]
    ctx_rx = [(w, R.word_rx(w)) for w in ctx]
    excl_rx = [(w, R.re.compile(r"(?<![\w])" + R.re.escape(w), R.re.I)) for w in R.flat_words(cfg.get("excludeWords"))]
    min_score = int(cfg.get("minScore", 3))
    t0 = time.time()
    if not R.FIXTURES:
        try:
            R.get("/cantons/v1", [("lang", "de")])
        except Exception as e:  # noqa: BLE001
            R.note("Cookie-Seed: %s" % e)

    found = {}
    queries = [("cpv:" + c, [("cpvCodes", c)]) for c in cfg.get("cpvSearch", [])]
    queries += [(w, [("search", w)]) for w in core if " " not in w.strip() and len(w.strip()) >= 3]
    for a, b in windows(start, end, window_days):
        for label, q in queries:
            search(q, a, b, int(cfg.get("historyPages", 30)), found, label)
        print("%s–%s: %d Kandidaten gesamt (%.0fs)" % (a, b, len(found), time.time() - t0), flush=True)

    cands = []
    for it in found.values():
        if any(rx.search(it["titleAll"]) for _, rx in excl_rx):
            continue
        if not it["viaCpv"] and not any(rx.search(it["titleAll"]) for _, rx in core_rx):
            continue
        cands.append(it)
    print("Details für %d Zuschläge laden" % len(cands), flush=True)

    rows, stats = [], {"geladen": 0, "ausserhalb": 0, "ohne Anbieter": 0, "zeit": 0}
    for n, it in enumerate(cands, 1):
        if time.time() - t0 > budget:
            stats["zeit"] = len(cands) - n + 1
            R.note("Zeitbudget erreicht, %d Zuschläge nicht geladen" % stats["zeit"])
            break
        ds = []
        for pub in it["pubs"]:
            try:
                ds.append(R.get("/publications/v1/project/%s/publication-details/%s" % (it["id"], pub)))
            except Exception as e:  # noqa: BLE001
                R.note("Details %s: %s" % (it.get("nr") or it["id"], e))
        if not ds:
            continue
        stats["geladen"] += 1
        it["url"] = "https://www.simap.ch/de/project-detail/" + it["id"]
        cpvs = sorted({c for d in ds for c in R.cpv_codes(d)})
        title_all = it["titleAll"] + " " + " ".join(R.collect(d, {"title", "lotTitle"}) for d in ds)
        desc_all = " ".join(R.collect(d, {"orderDescription", "description", "note", "lotDescription"}) for d in ds)
        mcpv, otype = R.main_cpv(ds)
        reason = R.scope_check(mcpv, otype, cfg, title_all, desc_all, core_rx)
        if reason:
            stats["ausserhalb"] += 1
            continue
        sc, _, reason = R.score_item(title_all, desc_all, cpvs, it["type"], cfg, core_rx, ctx_rx, excl_rx)
        if reason:
            stats["ausserhalb"] += 1
            continue
        rs = R.award_rows(it, ds, cpvs)
        if not rs:
            stats["ohne Anbieter"] += 1
        for r in rs:
            r["Radar-relevant"] = "ja" if sc >= min_score else "nein"
            rows.append(r)
        if n % 100 == 0:
            print("%d/%d Zuschläge, %d Zeilen (%.0fs)" % (n, len(cands), len(rows), time.time() - t0), flush=True)
    json.dump({"from": start.isoformat(), "to": end.isoformat(), "stats": stats, "notes": R.DIAG[-30:], "rows": rows},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("Fertig %s–%s: %d Zuschlagszeilen, %s" % (start, end, len(rows), stats))


def merge(parts):
    rows = []
    for p in parts:
        d = json.load(open(p, encoding="utf-8"))
        print("%s: %s–%s, %d Zeilen, %s" % (os.path.basename(p), d.get("from"), d.get("to"), len(d.get("rows", [])), d.get("stats")))
        rows += d.get("rows", [])
    n = R.write_awards(rows, dt.date.today())
    print("radar/awards.csv: %d Zeilen gesamt" % n)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--out", default="awards_part.json")
    ap.add_argument("--window", type=int, default=14)
    ap.add_argument("--budget", type=int, default=19800)
    ap.add_argument("--merge", nargs="*")
    a = ap.parse_args()
    if a.merge:
        merge(a.merge)
    else:
        run(dt.date.fromisoformat(a.start), dt.date.fromisoformat(a.end), a.out, a.window, a.budget)
