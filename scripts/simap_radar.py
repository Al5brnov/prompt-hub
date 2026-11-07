#!/usr/bin/env python3
"""simap-Radar: neue Publikationen auf simap.ch per Stichwort suchen.

Liest radar/config.json, fragt die öffentliche simap-API ab (Projektsuche und
Publikationsdetails, kein Login nötig) und schreibt radar/latest.json.
Die Web-App liest diese Datei von derselben Adresse (kein CORS-Problem).

Nur Standardbibliothek. Testmodus ohne Netz: SIMAP_FIXTURES=<ordner>.
"""
import csv
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
HISTORY = os.path.join(ROOT, "radar", "history.csv")
# Zwischenspeicher der Publikationsdetails (nicht im Repo, wird per actions/cache zwischen Läufen behalten)
CACHE = os.environ.get("RADAR_CACHE", os.path.join(ROOT, ".cache", "details.json"))
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
            time.sleep(0.4)
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
            time.sleep(5 * (attempt + 1))
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
        own = os.path.join(FIXTURES, "publication_details_%s.json" % path.rstrip("/").split("/")[-1])
        if os.path.exists(own):
            return json.load(open(own, encoding="utf-8"))
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


PUBTYPE_DE = {"award": "Zuschlag", "direct_award": "Freihändige Vergabe", "tender": "Ausschreibung", "participant_selection": "Präqualifikation", "advance_notice": "Vorankündigung",
              "competition": "Wettbewerb", "study_contract": "Studienauftrag", "request_for_information": "Informationsanfrage"}
ORDER_DE = {"service": "Dienstleistung", "supply": "Lieferung", "construction": "Bau"}
PROCESS_DE = {"open": "offen", "selective": "selektiv", "invitation": "Einladung", "direct": "freihändig", "no_process": "ohne Verfahren"}


def one_line(s, n=None):
    s = re.sub(r"\s+", " ", strip_html(s or "")).strip()
    return (s[: n - 1] + "…") if n and len(s) > n else s


def fields(details):
    """Kerninhalte für Excel: Gegenstand, Kriterien, Lose, Verfahren."""
    desc, qual, award, lots, proc = [], [], [], [], ""
    for d in details:
        pr = d.get("procurement") or {}
        t = lang_pick(pr.get("orderDescription"))
        if t and t not in desc:
            desc.append(t)
        proc = proc or pr.get("processType") or (d.get("project-info") or {}).get("processType") or ""
        cr = d.get("criteria") or {}
        for q in cr.get("qualificationCriteria") or []:
            x = one_line(lang_pick(q.get("title")) or lang_pick(q.get("description")) or "", 120)
            if x and x not in qual:
                qual.append(x)
        if not qual and cr.get("qualificationCriteriaInDocuments") in (True, "yes"):
            qual.append("gemäss Ausschreibungsunterlagen")
        for a in cr.get("awardCriteria") or []:
            x = one_line(lang_pick(a.get("title")) or "", 80)
            if x:
                w = a.get("weighting")
                x += " (Gewichtung %s)" % w if w not in (None, "") else ""
                if x not in award:
                    award.append(x)
        if not award and "document" in str(cr.get("awardCriteriaSelection") or ""):
            note_ = one_line(lang_pick(cr.get("awardCriteriaNote")) or "", 200)
            award.append("gemäss Ausschreibungsunterlagen" + (" (" + note_ + ")" if note_ and "unterlagen" not in note_.lower() else ""))
        for lot in d.get("lots") or []:
            x = "Los %s: %s" % (lot.get("lotNumber", "?"), one_line(lang_pick(lot.get("title")) or "", 100))
            if x not in lots:
                lots.append(x)
        if d.get("lot"):
            lot = d["lot"]
            x = "Los %s: %s" % (lot.get("lotNumber", "?"), one_line(lang_pick(lot.get("title")) or "", 100))
            if x not in lots:
                lots.append(x)
    return {
        "gegenstand": one_line(" / ".join(desc), 1200),
        "eignung": "; ".join(qual)[:1500],
        "zuschlag": "; ".join(award)[:800],
        "lose": "; ".join(lots)[:800],
        "verfahren": PROCESS_DE.get(proc, proc),
    }


HIST_COLS = ["Projekt-Nr", "Titel", "Auftraggeber", "Typ", "Verfahren", "publiziert", "Eingabefrist", "Relevanz",
             "Treffergrund", "Gegenstand", "Eignungskriterien", "Zuschlagskriterien", "Lose", "CPV", "Link",
             "zuerst gefunden", "zuletzt gesehen", "Status simap", "simap-ID",
             # neu ab 07.11.2026, nur hinten anfügen: die Excel-Pipeline ordnet A–S nach Position zu
             "Haupt-CPV", "Auftragsart", "Umfang"]


def write_history(items, today, scope=None, backfill=None):
    """Fortlaufende Liste: nichts wird gelöscht, neue Treffer kommen ans Ende.
    scope: Umfang-Prüfung je simap-ID aus diesem Lauf. backfill(ids) -> dict für alte Zeilen ohne Umfang."""
    rows = []
    if os.path.exists(HISTORY):
        with open(HISTORY, encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f, delimiter=";"))
    by_id = {r.get("simap-ID"): r for r in rows}
    iso = today.isoformat()
    for it in items:
        f_ = it.get("fields") or {}
        new = {
            "Projekt-Nr": it.get("nr") or "", "Titel": one_line(it.get("title")), "Auftraggeber": one_line(it.get("office")),
            "Typ": PUBTYPE_DE.get(it.get("type"), it.get("type") or ""), "Verfahren": f_.get("verfahren", ""),
            "publiziert": (it.get("date") or "")[:10], "Eingabefrist": (it.get("deadline") or "")[:10],
            "Relevanz": str(it.get("score", "")), "Treffergrund": ", ".join(it.get("hits") or []),
            "Gegenstand": f_.get("gegenstand", ""), "Eignungskriterien": f_.get("eignung", ""),
            "Zuschlagskriterien": f_.get("zuschlag", ""), "Lose": f_.get("lose", ""), "CPV": ", ".join(it.get("cpv") or []),
            "Link": it.get("url", ""), "zuletzt gesehen": iso, "simap-ID": it["id"],
        }
        if it["id"] in by_id:
            by_id[it["id"]].update(new)
        else:
            new["zuerst gefunden"] = iso
            rows.append(new)
            by_id[it["id"]] = new
    scope = dict(scope or {})
    missing = [r.get("simap-ID") for r in rows if not r.get("Umfang") and r.get("simap-ID") not in scope]
    if backfill and missing:
        scope.update(backfill(missing))
    for r in rows:
        if r.get("simap-ID") in scope:
            r.update(scope[r["simap-ID"]])
    for r in rows:
        fr = (r.get("Eingabefrist") or "")[:10]
        r["Status simap"] = "Frist abgelaufen" if fr and fr < iso else "offen"
    with open(HISTORY, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HIST_COLS, delimiter=";", extrasaction="ignore", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: one_line(r.get(k, "")) for k in HIST_COLS})
    return len(rows)


AWARDS_JSON = os.path.join(ROOT, "radar", "awards.json")
AWARDS_CSV = os.path.join(ROOT, "radar", "awards.csv")
AWARD_TYPES = ("award", "direct_award")
PRICEBASIS_DE = {"price_of_selected_offers": "Preis der berücksichtigten Angebote", "price_range": "Preisspanne", "lowest_and_highest_offer": "tiefstes und höchstes Angebot"}
VAT_DE = {"full": "inkl. MWST", "no_vat": "exkl. MWST", "reduced": "reduzierte MWST"}
AWARD_COLS = ["Zuschlagsdatum", "Projekt-Nr", "Titel", "Auftraggeber", "Typ", "Verfahren", "Los", "Anbieter", "Anbieter-Ort",
              "Preis CHF", "MWST", "Preisbasis", "Angebote", "Anzahl Zuschläge", "CPV", "Radar-relevant", "Link", "erfasst", "simap-ID",
              "Stundensatz CHF", "Stundensatz Fundstelle"]


def _num(v):
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


RATE_RX = re.compile(r"(stundens[aä]tz\w*|stundenans[aä]tz\w*|std\.?-?s[aä]tz\w*|pro stunde|/\s*std\.?\b|/\s*h\b|chf\s*/\s*h|taux horaires?|tarifs? horaires?|par heure|tariff[ae] orari[ae]|all.ora|hourly rates?|per hour)", re.I)
NUM_RX = re.compile(r"(?<![\d'’.])(\d{2,3}(?:[.,]\d{1,2})?)(?![\d'’])")


def all_strings(v):
    """Alle Textwerte einer Publikation (alle Sprachen), ohne IDs/Kontaktdaten."""
    out = []
    def walk(x, k=None):
        if k and SKIP_KEY.match(k):
            return
        if isinstance(x, dict):
            for kk, vv in x.items():
                walk(vv, kk)
        elif isinstance(x, list):
            for y in x:
                walk(y, k)
        elif isinstance(x, str):
            out.append(strip_html(x))
    walk(v)
    return out


def hourly_rates(details):
    """Stundensätze, wo im Publikationstext genannt: (Liste CHF-Werte 60–400, Fundstellen)."""
    vals, spots = [], []
    for d in details:
        for t in all_strings(d):
            for m in RATE_RX.finditer(t):
                win = t[max(0, m.start() - 90): m.end() + 90]
                nums = [float(n.replace(",", ".")) for n in NUM_RX.findall(win)]
                nums = [n for n in nums if 60 <= n <= 400]
                if nums:
                    vals += nums
                    spots.append(one_line(win, 200))
    return sorted(set(vals)), list(dict.fromkeys(spots))[:3]


def award_rows(it, details, cpvs):
    """Eine Zeile pro Zuschlagsempfänger (und Los). Quelle: decision.vendors der Publikationsdetails."""
    rows = []
    rates, spots = hourly_rates(details)
    rate_txt = ("%.0f" % rates[0] if len(rates) == 1 else "%.0f–%.0f" % (rates[0], rates[-1])) if rates else ""
    for d in details:
        decs = []
        if isinstance(d.get("decision"), dict):
            decs.append((d["decision"], d.get("lot")))
        for lot in d.get("lots") or []:
            if isinstance(lot, dict) and isinstance(lot.get("decision"), dict):
                decs.append((lot["decision"], lot))
        proc = (d.get("procurement") or {}).get("processType") or it.get("process") or ""
        for dec, lot in decs:
            vendors = [v for v in dec.get("vendors") or [] if isinstance(v, dict)]
            lot_txt = ""
            if isinstance(lot, dict) and lot:
                lot_txt = ("Los %s: %s" % (lot.get("lotNumber", "?"), one_line(lang_pick(lot.get("title")) or "", 80))).strip()
            for v in vendors:
                pr = v.get("price") or {}
                price = _num(pr.get("price"))
                if price is None and (pr.get("priceFrom") or pr.get("priceTo")):
                    price = _num(pr.get("priceTo") or pr.get("priceFrom"))
                addr = v.get("vendorAddress") or {}
                cur = (pr.get("currency") or "chf").lower()
                rows.append({
                    "Zuschlagsdatum": (dec.get("awardDecisionDate") or it.get("date") or "")[:10],
                    "Projekt-Nr": it.get("nr") or "", "Titel": one_line(it.get("title")), "Auftraggeber": one_line(it.get("office")),
                    "Typ": PUBTYPE_DE.get(it.get("type"), it.get("type") or ""), "Verfahren": PROCESS_DE.get(proc, proc), "Los": lot_txt,
                    "Anbieter": one_line(lang_pick(v.get("vendorName")) or v.get("vendorName") or ""),
                    "Anbieter-Ort": one_line(addr.get("city") or ""),
                    "Preis CHF": price if cur == "chf" else None, "MWST": VAT_DE.get(pr.get("vatType"), pr.get("vatType") or ""),
                    "Preisbasis": PRICEBASIS_DE.get(dec.get("totalPriceSelection"), one_line(dec.get("totalPriceSelection") or "")), "Angebote": dec.get("numberOfSubmissions"),
                    "Anzahl Zuschläge": len(vendors), "CPV": ", ".join(cpvs), "Link": it.get("url") or "https://www.simap.ch/de/project-detail/" + it["id"],
                    "simap-ID": it["id"], "Stundensatz CHF": rate_txt, "Stundensatz Fundstelle": " | ".join(spots),
                })
    return rows


def write_awards(new_rows, today):
    """Marktinfo: alle je gefundenen Zuschläge, fortlaufend (JSON für die App, CSV für Excel)."""
    try:
        old = json.load(open(AWARDS_JSON, encoding="utf-8")).get("rows", [])
    except Exception:  # noqa: BLE001
        old = []
    def key(r):
        return "%s|%s|%s" % (r.get("simap-ID"), r.get("Los"), r.get("Anbieter", "").lower())
    by = {key(r): r for r in old}
    iso = today.isoformat()
    for r in new_rows:
        k = key(r)
        r["erfasst"] = by.get(k, {}).get("erfasst") or iso
        by[k] = r
    rows = sorted(by.values(), key=lambda r: (r.get("Zuschlagsdatum") or "", r.get("Projekt-Nr") or ""), reverse=True)
    with open(AWARDS_JSON, "w", encoding="utf-8") as f:
        json.dump({"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "count": len(rows), "rows": rows},
                  f, ensure_ascii=False, separators=(",", ":"))
    with open(AWARDS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=AWARD_COLS, delimiter=";", extrasaction="ignore", lineterminator="\r\n")
        w.writeheader()
        for r in rows:
            out = {k: one_line(str(r.get(k)) if r.get(k) is not None else "") for k in AWARD_COLS}
            if r.get("Preis CHF") is not None:
                out["Preis CHF"] = ("%.2f" % r["Preis CHF"])  # Punkt als Dezimaltrenner, Power Query: Gebietsschema en-US
            w.writerow(out)
    return len(rows)


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


def main_cpv(details):
    """Haupt-CPV (procurement.cpvCode) und Auftragsart (service/supply/construction) der Publikation."""
    code, otype = "", ""
    for d in details:
        pr = d.get("procurement") or {}
        c = (pr.get("cpvCode") or {}).get("code")
        code = code or (str(c) if c else "")
        otype = otype or pr.get("orderType") or (d.get("project-info") or {}).get("orderType") or ""
    return code, otype


def scope_check(main, otype, cfg, title="", desc="", core_rx=()):
    """Nur Dienstleistungen rund um Software, Beratung, Betrieb und Support.
    Hart: Auftragsart (Bau), Haupt-CPV ausserhalb mainCpvAllow oder in mainCpvExclude (Hardware).
    Weich: softCpvExclude und softExcludeWords (Betrieb, Infrastruktur, Service Desk) schliessen nur aus,
    wenn kein Kernbegriff (SAP, ERP …) in Titel oder Beschreibung vorkommt.
    Liefert einen Ausschlussgrund oder ""."""
    if otype and otype in cfg.get("excludeOrderTypes", []):
        return "Auftragsart %s" % otype
    if main:
        if any(main.startswith(p) for p in cfg.get("mainCpvExclude", [])):
            return "Haupt-CPV %s (Hardware)" % main
        allow = cfg.get("mainCpvAllow")
        if allow and not any(main.startswith(p) for p in allow):
            return "Haupt-CPV %s ausserhalb Software/Beratung" % main
    soft = ""
    if main and any(main.startswith(p) for p in cfg.get("softCpvExclude", [])):
        soft = "Haupt-CPV %s (Betrieb/Infrastruktur)" % main
    if not soft:
        for w in flat_words(cfg.get("softExcludeWords")):
            if re.search(r"(?<![\w])" + re.escape(w), title, re.I):
                soft = "«%s» im Titel" % w
                break
    if soft and not any(rx.search(title) or rx.search(desc) for _, rx in core_rx):
        return soft + " ohne SAP-/ERP-Bezug"
    return ""


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
    title_only = set(cfg.get("titleOnly", []))
    for w, rx in core_rx:
        if rx.search(title):
            score += 5; why.append(w + " (Titel)")
        elif w in title_only:
            continue
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
    search_words = [w for w in words if " " not in w.strip() and len(w.strip()) >= 3]
    market = cfg.get("marketTypes", [])
    all_types = types + [t for t in market if t not in types]
    ok_types = set(all_types) | ({"award"} if any(t.startswith("award") for t in all_types) else set())
    # Kandidatenquellen: alle Publikationen mit IT-/Beratungs-CPV, plus Stichwortsuche (findet auch Fälle mit anderem CPV)
    queries = [("cpv:" + c, [("cpvCodes", c)], int(cfg.get("cpvPages", 10))) for c in cfg.get("cpvSearch", [])]
    queries += [(w, [("search", w)], 3 if w in core else 2) for w in search_words]
    found, errors = {}, 0

    def run_query(w, q, max_pages):
        """Eine Suche mit Folgeseiten. True = vollständig, False = abgebrochen (Netzwerk)."""
        nonlocal errors
        cursor, pages = None, 0
        while pages < max_pages:
            params = [("lang", "de")] + q + [("newestPublicationFrom", since)] + [("newestPubTypes", t) for t in all_types]
            if cursor:
                params.append(("lastItem", cursor))
            try:
                r = get("/publications/v2/project/project-search", params)
            except Exception as e:  # noqa: BLE001
                note("Suche «%s»: %s" % (w, e))
                errors += 1
                if errors >= 3 and not found:
                    raise RuntimeError("simap-Suche wiederholt fehlgeschlagen: %s" % e)
                return False
            projects = r.get("projects") or []
            for p in projects:
                pid = p.get("id")
                if not pid or (p.get("pubType") and p.get("pubType") not in ok_types):
                    continue
                if pid in found:
                    found[pid]["foundBy"].append(w)
                    found[pid]["viaCpv"] = found[pid]["viaCpv"] or w.startswith("cpv:")
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
                    "viaCpv": w.startswith("cpv:"),
                }
            cursor = (r.get("pagination") or {}).get("lastItem")
            pages += 1
            if not cursor or not projects:
                break
        return True

    failed = []
    for w, q, max_pages in queries:
        if not run_query(w, q, max_pages):
            failed.append((w, q, max_pages))
        print("Suche «%s»: %d Kandidaten gesamt (%.0fs)" % (w, len(found), time.time() - t0), flush=True)
    if failed:
        time.sleep(20)  # zweiter Versuch nach kurzer Pause
        still = [f[0] for f in failed if not run_query(*f)]
        note("Wiederholt: %d Suchen, weiterhin fehlgeschlagen: %s" % (len(failed), ", ".join(still) or "keine"))

    # Vorfilter ohne Details: Ausschlusswörter im Titel; Priorität für Kernbegriffe im Titel
    def prio(it):
        t = it["titleAll"]
        core_in_title = sum(1 for _, rx in core_rx if rx.search(t))
        bid = 1 if it.get("type") in ("tender", "participant_selection", "advance_notice") else 0
        return (1 if core_in_title else 0, bid, core_in_title, len(set(it["foundBy"])), it.get("date") or "")
    bid_types = ("tender", "participant_selection", "advance_notice")
    cands, pre_skipped = [], 0
    for it in found.values():
        if any(rx.search(it["titleAll"]) for _, rx in excl_rx):
            continue
        core_title = any(rx.search(it["titleAll"]) for _, rx in core_rx)
        if it["viaCpv"]:
            # IT-/Beratungs-CPV bekannt: Ausschreibungen immer prüfen, Zuschläge nur mit Kernbegriff im Titel,
            # ausser marketAllItAwards: dann alle IT-Zuschläge für die Marktinfo (niedrigste Priorität)
            if it.get("type") not in bid_types and not core_title and not cfg.get("marketAllItAwards"):
                pre_skipped += 1
                continue
        elif not core_title:
            # nur über Stichwort gefunden, CPV nicht IT: nur mit Kernbegriff im Titel weiterverfolgen
            pre_skipped += 1
            continue
        cands.append(it)
    cands.sort(key=prio, reverse=True)
    max_details = int(cfg.get("maxDetails", 150))
    skipped = max(0, len(cands) - max_details)
    cands = cands[:max_details]
    print("Details für %d Kandidaten laden (%d vorab aussortiert, %d wegen Limit übersprungen)" % (len(cands), pre_skipped, skipped), flush=True)

    # Details sind pro Publikations-ID unveränderlich (Korrekturen erhalten eine neue ID): bereits geladene wiederverwenden
    try:
        cache = json.load(open(CACHE, encoding="utf-8")) if not FIXTURES else {}
    except Exception:  # noqa: BLE001
        cache = {}
    used, stats = {}, {"cache": 0, "neu": 0}

    def load(it):
        ds = []
        for pub in it["pubs"]:
            key = "%s|%s" % (it["id"], pub)
            if key in cache:
                ds.append(cache[key]); used[key] = cache[key]; stats["cache"] += 1
                continue
            if time.time() - t0 > budget:
                return it, None
            try:
                d = get("/publications/v1/project/%s/publication-details/%s" % (it["id"], pub))
                ds.append(d); used[key] = d; stats["neu"] += 1
            except Exception as e:  # noqa: BLE001
                note("Details %s: %s" % (it.get("nr") or it["id"], e))
        return it, ds

    with ThreadPoolExecutor(max_workers=1) as ex:
        loaded = list(ex.map(load, cands))
    print("Details: %d aus Zwischenspeicher, %d neu geladen" % (stats["cache"], stats["neu"]), flush=True)
    if not FIXTURES:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(used, f, ensure_ascii=False)

    # 2) bewerten und filtern
    rejected, market, scope = [], [], {}
    items, dropped = [], {"vorab": pre_skipped, "cpv": 0, "score": 0, "frist": 0, "ausschluss": 0, "zeit": 0, "limit": skipped}
    for it, details in loaded:
        it.pop("pubs", None)
        it.pop("foundBy", None)
        it.pop("viaCpv", None)
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
        mcpv, otype = main_cpv(details)
        reason = scope_check(mcpv, otype, cfg, title_all, desc_all, core_rx)
        scope[it["id"]] = {"Haupt-CPV": mcpv, "Auftragsart": ORDER_DE.get(otype, otype), "Umfang": ("ausserhalb: " + reason) if reason else "passt"}
        if reason:
            sc, why = 0, []
        else:
            sc, why, reason = score_item(title_all, desc_all, cpvs, it["type"], cfg, core_rx, ctx_rx, excl_rx)
        if it["type"] in AWARD_TYPES and not reason:
            for r in award_rows(it, details, cpvs):
                r["Radar-relevant"] = "ja" if sc >= min_score else "nein"
                market.append(r)
        if deadline and deadline[:10] < today.isoformat() and not os.environ.get("RADAR_KEEP_EXPIRED"):
            dropped["frist"] += 1
            continue
        if reason:
            dropped["cpv" if ("CPV" in reason or reason.startswith("Auftragsart")) else "ausschluss"] += 1
            rejected.append({"title": it["title"][:90], "score": 0, "why": reason[:80]})
            continue
        if sc < min_score:
            dropped["score"] += 1
            rejected.append({"title": it["title"][:90], "score": sc, "why": ", ".join(why)[:80] + (" | CPV " + ",".join(cpvs[:3]) if cpvs else "")})
            continue
        text = "\n".join(t for t in (to_text(d, "  ") for d in details) if t)
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + "\n  [… gekürzt]"
        it.update({"deadline": deadline, "cpv": cpvs, "score": sc, "hits": why, "fields": fields(details),
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
        "detailsCached": stats["cache"],
        "detailsLoaded": stats["neu"],
        "dropped": dropped,
        "count": len(items),
        "diagnostics": DIAG[-20:],
        "rejected": sorted(rejected, key=lambda r: -r["score"])[:80],
        "items": items,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    def backfill(ids):
        """Alte Trefferzeilen ohne Umfang nachträglich prüfen (Projektkopf + Details, mit Zwischenspeicher)."""
        out, hist_title = {}, {}
        if os.path.exists(HISTORY):
            with open(HISTORY, encoding="utf-8-sig", newline="") as f:
                for r in csv.DictReader(f, delimiter=";"):
                    hist_title[r.get("simap-ID")] = (r.get("Titel") or "", r.get("Gegenstand") or "")
        for pid in ids[: int(cfg.get("backfillMax", 150))]:
            if time.time() - t0 > budget + 300:
                note("Umfang-Nachprüfung abgebrochen (Zeit), Rest im nächsten Lauf")
                break
            try:
                h = get("/publications/v2/project/%s/project-header" % pid)
                pubs = [x["id"] for x in [h.get("latestPublication") or {}] + [l.get("latestPublication") or {} for l in h.get("lots") or []] if x.get("id")]
                ds = []
                for pub in pubs[:3]:
                    key = "%s|%s" % (pid, pub)
                    d = cache.get(key) or get("/publications/v1/project/%s/publication-details/%s" % (pid, pub))
                    used[key] = d; ds.append(d)
                mcpv, otype = main_cpv(ds)
                otype = otype or h.get("orderType") or ""
                t, g = hist_title.get(pid, ("", ""))
                t += " " + " ".join(collect(d, {"title", "lotTitle"}) for d in ds)
                g += " " + " ".join(collect(d, {"orderDescription", "description", "note", "lotDescription"}) for d in ds)
                reason = scope_check(mcpv, otype, cfg, t, g, core_rx)
                out[pid] = {"Haupt-CPV": mcpv, "Auftragsart": ORDER_DE.get(otype, otype), "Umfang": ("ausserhalb: " + reason) if reason else "passt"}
            except Exception as e:  # noqa: BLE001
                note("Umfang-Nachprüfung %s: %s" % (pid, e))
        print("Umfang-Nachprüfung: %d alte Zeilen geprüft" % len(out), flush=True)
        return out

    n_hist = write_history(items, today, scope, None if FIXTURES else backfill)
    if not FIXTURES and used:
        with open(CACHE, "w", encoding="utf-8") as f:
            json.dump(used, f, ensure_ascii=False)
    print("Trefferliste: %d Einträge in radar/history.csv" % n_hist)
    n_aw = write_awards(market, today)
    print("Marktinfo: %d Zuschlagszeilen in diesem Lauf, %d gesamt in radar/awards.csv" % (len(market), n_aw))
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
