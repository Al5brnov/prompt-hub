#!/usr/bin/env python3
"""Liest neue Blogbeiträge der SAP Community über deren öffentliche API (LiQL) und schreibt
radar/sap-community.json. Konfiguration: radar/sap-feeds.json.
Gespeichert werden nur Titel, Link, Datum und Quelle (kein Volltext)."""
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "radar" / "sap-feeds.json"
OUT = ROOT / "radar" / "sap-community.json"
API = "https://community.sap.com/api/2.0/search?q="
UA = "prompt-hub-radar/1.0 (+https://github.com/Al5brnov/prompt-hub)"


def liql(query):
    req = urllib.request.Request(API + urllib.parse.quote(query), headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("status") != "success":
        raise RuntimeError(str(data.get("message") or data)[:200])
    return data.get("data", {}).get("items", [])


def q(s):
    return s.replace("'", "\\'")


def product_id(feed):
    if feed.get("product"):
        return feed["product"]
    rows = liql(f"SELECT id, title FROM products WHERE title = '{q(feed['productTitle'])}' LIMIT 5")
    if not rows:
        raise RuntimeError(f"Managed Tag «{feed['productTitle']}» nicht gefunden")
    print(f"{feed['name']}: Managed-Tag-ID {rows[0]['id']} (in sap-feeds.json als product eintragen)")
    return rows[0]["id"]


def fetch(feed, since):
    fields = "SELECT id, subject, view_href, post_time FROM messages WHERE conversation.style = 'blog' AND depth = 0"
    if feed.get("board"):
        where = f" AND board.id = '{q(feed['board'])}'"
    else:
        where = f" AND products.id = '{q(product_id(feed))}' AND products.includes = true"
    rows = liql(fields + where + " ORDER BY post_time DESC LIMIT 50")
    return [m for m in rows if (m.get("post_time") or "") and datetime.fromisoformat(m["post_time"].replace("Z", "+00:00")) >= since]


def matches(title, words):
    if not words:
        return True
    for w in words:
        if len(w) <= 3:  # Kürzel wie SD, MM nur als ganzes Wort
            if re.search(r"(?<![A-Za-z])" + re.escape(w) + r"(?![A-Za-z])", title):
                return True
        elif w.lower() in title.lower():
            return True
    return False


def main():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    since = datetime.now(timezone.utc) - timedelta(days=cfg.get("tageZurueck", 3))
    seen, out, status = set(), [], []
    for f in cfg["feeds"]:
        try:
            n = 0
            for m in fetch(f, since):
                title, link = (m.get("subject") or "").strip(), m.get("view_href") or ""
                if not title or not link or link in seen or not matches(title, f.get("filter", [])):
                    continue
                seen.add(link)
                out.append({"titel": title, "url": link, "datum": m.get("post_time", ""), "quelle": f["name"]})
                n += 1
            status.append({"feed": f["name"], "ok": True, "neu": n})
        except Exception as e:  # ein Feed darf die anderen nicht blockieren
            print(f"::warning::Feed {f['name']}: {e}", file=sys.stderr)
            status.append({"feed": f["name"], "ok": False, "fehler": str(e)[:200]})
    out.sort(key=lambda x: x["datum"], reverse=True)
    out = out[: cfg.get("maxEintraege", 60)]
    OUT.write_text(json.dumps({"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": out, "feeds": status}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(out)} Beiträge; " + ", ".join(f"{s['feed']}: {s.get('neu', 'Fehler')}" for s in status))
    if not any(s["ok"] for s in status):
        sys.exit(1)


if __name__ == "__main__":
    main()
