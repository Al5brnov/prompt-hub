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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(ROOT, "radar", "config.json")
OUT = os.path.join(ROOT, "radar", "latest.json")
BASE = "https://www.simap.ch/api"
UA = "prompt-hub-radar/1.0 (+https://github.com/)"
MAX_TEXT = 6000
SKIP_KEY = re.compile(r"^(id|.*Id|.*Ids|actions|links?|_links|phone|fax|email|vendorStatus|latestVendorDigitalSubmission|invitedVendors|publishers)$")
LANG_KEYS = {"de", "fr", "it", "en", "rm"}

FIXTURES = os.environ.get("SIMAP_FIXTURES")
_jar = http.cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def get(path, params=None):
    """GET auf die simap-API. params: Liste von (key, value), Wiederholungen erlaubt."""
    if FIXTURES:
        return _fixture(path, params)
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    for attempt in range(3):
        try:
            with _opener.open(req, timeout=30) as r:
                body = r.read().decode("utf-8")
            time.sleep(0.3)
            return json.loads(body)
        except json.JSONDecodeError:
            # cookie-check: erste Antwort ist eine HTML-Seite, danach ist das Cookie gesetzt
            time.sleep(1)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise RuntimeError("Keine JSON-Antwort von " + url)


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


def main():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    words = [w.strip() for w in cfg.get("keywords", []) if w.strip()]
    types = cfg.get("pubTypes", ["tender", "participant_selection", "advance_notice"])
    days = int(cfg.get("daysBack", 21))
    today = dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()

    if not FIXTURES:
        try:
            get("/cantons/v1", [("lang", "de")])  # setzt das Session-Cookie
        except Exception as e:  # noqa: BLE001
            print("Cookie-Seed fehlgeschlagen:", e, file=sys.stderr)

    found = {}
    for w in words:
        cursor, pages = None, 0
        while pages < 5:
            params = [("lang", "de"), ("search", w), ("newestPublicationFrom", since)] + [("newestPubTypes", t) for t in types]
            if cursor:
                params.append(("lastItem", cursor))
            r = get("/publications/v2/project/project-search", params)
            projects = r.get("projects") or []
            for p in projects:
                pid = p.get("id")
                if not pid:
                    continue
                if pid in found:
                    if w not in found[pid]["hits"]:
                        found[pid]["hits"].append(w)
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
                    "hits": [w],
                }
            cursor = (r.get("pagination") or {}).get("lastItem")
            pages += 1
            if not cursor or not projects:
                break

    items = []
    for it in found.values():
        texts, deadline = [], None
        for pub in it.pop("pubs"):
            try:
                d = get("/publications/v1/project/%s/publication-details/%s" % (it["id"], pub))
            except Exception as e:  # noqa: BLE001
                texts.append("  [Details nicht ladbar: %s]" % e)
                continue
            dl = (d.get("dates") or {}).get("offerDeadline")
            if dl and (not deadline or dl < deadline):
                deadline = dl
            texts.append(to_text(d, "  "))
        text = "\n".join(t for t in texts if t)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n  [… gekürzt]"
        it["deadline"] = deadline
        it["url"] = "https://www.simap.ch/de/project-detail/" + it["id"]
        it["text"] = text
        if deadline and deadline[:10] < today.isoformat() and not os.environ.get("RADAR_KEEP_EXPIRED"):
            continue  # Frist abgelaufen
        items.append(it)

    items.sort(key=lambda x: (x.get("date") or ""), reverse=True)
    out = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "since": since,
        "keywords": words,
        "pubTypes": types,
        "count": len(items),
        "items": items,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("simap-Radar: %d Treffer seit %s (%s)" % (len(items), since, ", ".join(words)))


if __name__ == "__main__":
    main()
