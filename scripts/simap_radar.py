#!/usr/bin/env python3
"""simap-Radar: neue Publikationen auf simap.ch per Stichwort suchen.

Liest radar/config.json, fragt die öffentliche simap-API ab (Projektsuche und
Publikationsdetails, kein Login nötig) und schreibt radar/latest.json.
Die Web-App liest diese Datei von derselben Adresse (kein CORS-Problem).

Nur Standardbibliothek. Testmodus ohne Netz: SIMAP_FIXTURES=<ordner>.
"""
import datetime as dt
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "radar", "config.json")
OUT = os.path.join(ROOT, "radar", "latest.json")
BASE = "https://www.simap.ch/api"
UA = "prompt-hub-radar/1.0 (+https://github.com/)"
MAX_TEXT = 6000
SKIP_KEY = re.compile(r"^(id|.*Id|.*Ids|actions|links?|_links|phone|fax|email|vendorStatus|latestVendorDigitalSubmission|invitedVendors|publishers)$")
LANG_KEYS = {"de", "fr", "it", "en", "rm"}

FIXTURES = os.environ.get("SIMAP_FIXTURES")

import socket  # noqa: E402
_orig_gai = socket.getaddrinfo


def _gai_v4(host, *a, **k):
    res = _orig_gai(host, *a, **k)
    v4 = [r for r in res if r[0] == socket.AF_INET]
    return v4 or res


socket.getaddrinfo = _gai_v4
_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


DIAG = []


def note(msg):
    """Diagnose: als GitHub-Annotation sichtbar und in latest.json."""
    DIAG.append(msg)
    print("::warning::" + msg.replace("\n", " "))


def get(path, params=None):
    """GET auf die simap-API. params: Liste von (key, value), Wiederholungen erlaubt."""
    if FIXTURES:
        return _fixture(path, params)
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA, "Accept-Language": "de-CH,de;q=0.9"})
    last = ""
    for attempt in range(3):
        try:
            with _opener.open(req, timeout=30) as r:
                status, final, ctype = r.status, r.geturl(), r.headers.get("Content-Type", "")
                body = r.read().decode("utf-8", "replace")
            time.sleep(0.3)
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                # cookie-check: erste Antwort ist evtl. eine HTML-Seite, danach ist das Cookie gesetzt
                last = "keine JSON-Antwort (HTTP %s, %s, Ziel %s): %s" % (status, ctype, final, re.sub(r"\s+", " ", body[:200]))
                time.sleep(1.5)
        except urllib.error.HTTPError as e:
            snippet = re.sub(r"\s+", " ", e.read().decode("utf-8", "replace")[:200]) if hasattr(e, "read") else ""
            last = "HTTP %s bei %s: %s" % (e.code, path, snippet)
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            break
        except Exception as e:  # noqa: BLE001
            last = "%s bei %s: %s" % (type(e).__name__, path, e)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(last or ("Keine Antwort von " + url))


def _fixture(path, params):
    if "project-search" in path:
        word = dict(params).get("search", "")
        last = dict(params).get("lastItem")
        d = json.load(open(os.path.join(FIXTURES, "project_search.json"), encoding="utf-8"))
        if last or word not in ("SAP", "ERP"):
            return {"projects": [], "pagination": {}}
        return d
    if "publication-details" in path:
        return json.load(open(os.path.join(FIXTURES, "publication_details_tender.json"), encoding="utf-8"))
    return {}


def lang_pick(o):
    if isinstance(o, dict) and o and set(o) <= LANG_KEYS:
        for k in ("de", "en", "fr", "it", "rm"):
            if o.get(k):
                return o[k]
        return ""
    return None


def strip_html(s):
    s = str(s)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</(p|li|div|h\d)>", "\n", s, flags=re.I)
    s = re.sub(r"<li[^>]*>", "- ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def to_text(v, ind=""):
    lp = lang_pick(v)
    if lp is not None:
        return strip_html(lp) if lp else ""
    if v is None or v == "" or v is False:
        return ""
    if v is True:
        return "ja"
    if not isinstance(v, (dict, list)):
        return strip_html(v)
    out = []
    if isinstance(v, list):
        for x in v:
            t = to_text(x, ind + "  ")
            if t:
                out.append(ind + "- " + t.lstrip())
        return ("\n" + "\n".join(out)) if out else ""
    for k, x in v.items():
        if SKIP_KEY.match(k):
            continue
        t = to_text(x, ind + "  ")
        if t:
            out.append(ind + k + ":" + (t if t.startswith("\n") else " " + t.replace("\n", "\n" + ind + "  ")))
    return ("\n" + "\n".join(out)) if out else ""


def flat_words(v):
    if isinstance(v, dict):  # gruppiert: {"Gruppe": ["Stichwort", ...]}
        v = [w for group in v.values() for w in group]
    out = []
    for w in v or []:
        w = w.strip()
        if w and w.lower() not in [x.lower() for x in out]:
            out.append(w)
    return out


def word_rx(w):
    """Wortanfang-Treffer. Kurze Akronyme (SAP, ERP, CRM, AMS) nur exakt und gross geschrieben,
    damit «sapeurs-pompiers», «Sapin» oder «Amsteg» nicht treffen."""
    if re.fullmatch(r"[A-Z0-9/]{2,5}", w):
        return re.compile(r"(?<![\w-])" + re.escape(w) + r"(?![\w])")
    return re.compile(r"(?<![\w])" + re.escape(w), re.I)


def collect(d, keys):
    """Alle Texte (alle Sprachen) unter den genannten Schlüsseln, rekursiv."""
    out = []
    def walk(v, k=None):
        if isinstance(v, dict):
            if k in keys and set(v) <= LANG_KEYS:
                out.extend(str(x) for x in v.values() if x)
                return
            for kk, vv in v.items():
                walk(vv, kk)
        elif isinstance(v, list):
            for x in v:
                walk(x, k)
        elif k in keys and isinstance(v, str):
            out.append(v)
    walk(d)
    return strip_html(" \n ".join(out))


def cpv_codes(d):
    codes = []
    def walk(v, k=None):
        if isinstance(v, dict):
            if k in ("cpvCode", "additionalCpvCodes") and v.get("code"):
                codes.append(str(v["code"]))
            for kk, vv in v.items():
                walk(vv, kk)
        elif isinstance(v, list):
            for x in v:
                walk(x, k)
    walk(d)
    return sorted(set(codes))


def score_item(title, desc, cpvs, ptype, cfg, core_rx, ctx_rx, excl_rx):
    """Relevanz: Kernbegriffe zählen immer, Kontextbegriffe nur bei IT-/Beratungs-CPV."""
    it_cpv = any(c.startswith(tuple(cfg.get("itCpvPrefixes", ["48", "72", "794"]))) for c in cpvs)
    bad_cpv = cpvs and all(c.startswith(tuple(cfg.get("excludeCpvPrefixes", []))) for c in cpvs)
    if bad_cpv and not it_cpv:
        return 0, [], "CPV ausserhalb IT (" + ", ".join(cpvs) + ")"
    for w, rx in excl_rx:
        if rx.search(title):
            return 0, [], "Ausschlusswort im Titel: " + w
    score, why = 0, []
    for w, rx in core_rx:
        if rx.search(title):
            score += 5; why.append(w + " (Titel)")
        elif rx.search(desc):
            score += 3 if it_cpv else 1; why.append(w)
    ctx = []
    for w, rx in ctx_rx:
        if rx.search(title) or rx.search(desc):
            ctx.append(w)
    if ctx and it_cpv:
        score += min(2 * len(ctx), 4); why += ctx
    if it_cpv:
        score += 2
    if ptype in ("tender", "participant_selection"):
        score += 1
    return score, why, ""


def main():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    core = flat_words(cfg.get("core") or cfg.get("keywords"))
    ctx = [w for w in flat_words(cfg.get("context")) if w.lower() not in [c.lower() for c in core]]
    excl = flat_words(cfg.get("excludeWords"))
    words = core + ctx
    core_rx = [(w, word_rx(w)) for w in core]
    ctx_rx = [(w, word_rx(w)) for w in ctx]
    excl_rx = [(w, re.compile(r"(?<![\w])" + re.escape(w), re.I)) for w in excl]
    types = cfg.get("pubTypes", ["tender", "participant_selection", "advance_notice"])
    days = int(cfg.get("daysBack", 21))
    min_score = int(cfg.get("minScore", 4))
    max_items = int(cfg.get("maxItems", 40))
    today = dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()

    if not FIXTURES:
        try:
            get("/cantons/v1", [("lang", "de")])  # setzt das Session-Cookie
        except Exception as e:  # noqa: BLE001
            note("Cookie-Seed: %s" % e)
        note("Cookies nach Seed: %s" % (", ".join(c.name for c in _jar) or "keine"))

    # 1) Kandidaten aus der simap-Volltextsuche.
    #    Nur Einwort-Begriffe werden gesucht (simap verknüpft Wörter vermutlich mit ODER,
    #    «progiciel de gestion» träfe sonst jedes «de»). Mehrwort-Begriffe zählen nur beim Bewerten.
    t0 = time.time()
    budget = int(cfg.get("timeBudgetSec", 600))
    search_words = [w for w in words if " " not in w.strip()]
    found, errors = {}, 0
    for w in search_words:
        max_pages = 3 if w in core else 2
        cursor, pages = None, 0
        while pages < max_pages:
            params = [("lang", "de"), ("search", w), ("newestPublicationFrom", since)] + [("newestPubTypes", t) for t in types]
            if cursor:
                params.append(("lastItem", cursor))
            try:
                r = get("/publications/v2/project/project-search", params)
            except Exception as e:  # noqa: BLE001
                note("Suche «%s»: %s" % (w, e))
                errors += 1
                if errors >= 3 and not found:
                    raise RuntimeError("simap-Suche wiederholt fehlgeschlagen: %s" % e)
                break
            projects = r.get("projects") or []
            for p in projects:
                pid = p.get("id")
                if not pid or (p.get("pubType") and p.get("pubType") not in types):
                    continue
                if pid in found:
                    found[pid]["foundBy"].append(w)
                    continue
                pubs = [p.get("publicationId")] if p.get("publicationId") else []
                for lot in p.get("lots") or []:
                    if lot.get("publicationId") and lot["publicationId"] not in pubs:
                        pubs.append(lot["publicationId"])
                found[pid] = {
                    "id": pid,
                    "pubs": pubs[:3],
                    "nr": p.get("projectNumber"),
                    "title": lang_pick(p.get("title")) or "",
                    "office": lang_pick(p.get("procOfficeName")) or "",
                    "date": p.get("publicationDate"),
                    "type": p.get("pubType"),
                    "process": p.get("processType"),
                    "titleAll": " ".join(str(x) for x in (p.get("title") or {}).values() if x),
                    "foundBy": [w],
                }
            cursor = (r.get("pagination") or {}).get("lastItem")
            pages += 1
            if not cursor or not projects:
                break
        print("Suche «%s»: %d Kandidaten gesamt (%.0fs)" % (w, len(found), time.time() - t0), flush=True)

    # Vorfilter ohne Details: Ausschlusswörter im Titel; Priorität für Kernbegriffe im Titel
    def prio(it):
        t = it["titleAll"]
        core_in_title = sum(1 for _, rx in core_rx if rx.search(t))
        return (core_in_title, len(set(it["foundBy"])), it.get("date") or "")
    cands = []
    for it in found.values():
        if any(rx.search(it["titleAll"]) for _, rx in excl_rx):
            continue
        cands.append(it)
    cands.sort(key=prio, reverse=True)
    max_details = int(cfg.get("maxDetails", 150))
    skipped = max(0, len(cands) - max_details)
    cands = cands[:max_details]
    print("Details für %d Kandidaten laden (%d wegen Limit übersprungen)" % (len(cands), skipped), flush=True)

    def load(it):
        if time.time() - t0 > budget:
            return it, None
        ds = []
        for pub in it["pubs"]:
            try:
                ds.append(get("/publications/v1/project/%s/publication-details/%s" % (it["id"], pub)))
            except Exception as e:  # noqa: BLE001
                note("Details %s: %s" % (it.get("nr") or it["id"], e))
        return it, ds

    with ThreadPoolExecutor(max_workers=2) as ex:
        loaded = list(ex.map(load, cands))

    # 2) bewerten und filtern
    rejected = []
    items, dropped = [], {"cpv": 0, "score": 0, "frist": 0, "ausschluss": 0, "zeit": 0, "limit": skipped}
    for it, details in loaded:
        it.pop("pubs", None)
        it.pop("foundBy", None)
        if details is None:
            dropped["zeit"] += 1
            continue
        deadline = None
        for d in details:
            dl = (d.get("dates") or {}).get("offerDeadline")
            if dl and (not deadline or dl < deadline):
                deadline = dl
        title_all = it.pop("titleAll") + " " + " ".join(collect(d, {"title", "lotTitle"}) for d in details)
        desc_all = " ".join(collect(d, {"orderDescription", "description", "note", "lotDescription"}) for d in details)
        cpvs = sorted({c for d in details for c in cpv_codes(d)})
        sc, why, reason = score_item(title_all, desc_all, cpvs, it["type"], cfg, core_rx, ctx_rx, excl_rx)
        if deadline and deadline[:10] < today.isoformat() and not os.environ.get("RADAR_KEEP_EXPIRED"):
            dropped["frist"] += 1
            continue
        if reason:
            dropped["cpv" if reason.startswith("CPV") else "ausschluss"] += 1
            rejected.append({"title": it["title"][:90], "score": 0, "why": reason[:80]})
            continue
        if sc < min_score:
            dropped["score"] += 1
            rejected.append({"title": it["title"][:90], "score": sc, "why": ", ".join(why)[:80] + (" | CPV " + ",".join(cpvs[:3]) if cpvs else "")})
            continue
        text = "\n".join(t for t in (to_text(d, "  ") for d in details) if t)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n  [… gekürzt]"
        it.update({"deadline": deadline, "cpv": cpvs, "score": sc, "hits": why,
                   "url": "https://www.simap.ch/de/project-detail/" + it["id"], "text": text})
        items.append(it)

    items.sort(key=lambda x: (x["score"], x.get("date") or ""), reverse=True)
    items = items[:max_items]
    out = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "since": since,
        "keywords": words,
        "pubTypes": types,
        "candidates": len(found),
        "searchWords": search_words,
        "durationSec": round(time.time() - t0),
        "dropped": dropped,
        "count": len(items),
        "diagnostics": DIAG[-20:],
        "rejected": sorted(rejected, key=lambda r: -r["score"])[:80],
        "items": items,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("simap-Radar: %d relevante von %d Kandidaten seit %s (aussortiert: %s)"
          % (len(items), len(found), since, ", ".join("%s %d" % kv for kv in dropped.items())))


def write_error(e):
    try:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
        words = flat_words(cfg.get("core") or cfg.get("keywords")) + flat_words(cfg.get("context"))
    except Exception:  # noqa: BLE001
        words = []
    out = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "since": None,
           "keywords": words, "count": 0, "error": str(e), "diagnostics": DIAG[-20:], "items": []}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("::error::simap-Radar fehlgeschlagen: %s" % str(e).replace("\n", " "))
        write_error(e)
        sys.exit(1)
