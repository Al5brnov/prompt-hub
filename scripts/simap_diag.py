#!/usr/bin/env python3
"""Einmalige Diagnose: warum fehlen bestimmte Ausschreibungen im Radar? Schreibt radar/diag-result.json."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import simap_radar as R

ROOT = R.ROOT
cfg = json.load(open(os.path.join(ROOT, "radar", "diag.json"), encoding="utf-8"))
out = {"projects": [], "searches": []}
try:
    R.get("/cantons/v1", [("lang", "de")])
except Exception as e:  # noqa: BLE001
    out["seed"] = str(e)

def summarize(p):
    return {"id": p.get("id"), "nr": p.get("projectNumber"), "title": R.lang_pick(p.get("title")),
            "office": R.lang_pick(p.get("procOfficeName")), "pubType": p.get("pubType"), "date": p.get("publicationDate"),
            "publicationId": p.get("publicationId"), "lots": len(p.get("lots") or [])}

def search(params, label):
    try:
        r = R.get("/publications/v2/project/project-search", [("lang", "de")] + params)
        ps = r.get("projects") or []
        out["searches"].append({"label": label, "params": params, "count": len(ps), "pagination": r.get("pagination"),
                                "items": [summarize(p) for p in ps[:40]]})
        return ps
    except Exception as e:  # noqa: BLE001
        out["searches"].append({"label": label, "params": params, "error": str(e)})
        return []

for s in cfg.get("searches", []):
    search([tuple(x) for x in s["params"]], s["label"])

for pid in cfg.get("projectIds", []):
    rec = {"id": pid}
    try:
        h = R.get("/publications/v2/project/%s/project-header" % pid)
        rec["header"] = {k: h.get(k) for k in ("projectNumber", "projectType", "projectSubType", "processType", "lotsType")}
        pub = (h.get("latestPublication") or {})
        rec["latestPublication"] = {k: pub.get(k) for k in ("id", "pubType", "publicationNumber", "dates")}
        rec["title"] = R.lang_pick(pub.get("title"))
        if pub.get("id"):
            d = R.get("/publications/v1/project/%s/publication-details/%s" % (pid, pub["id"]))
            rec["cpv"] = R.cpv_codes(d)
            rec["detailDates"] = {k: (d.get("dates") or {}).get(k) for k in ("publicationDate", "initialPublicationDate", "offerDeadline")}
            rec["basePublicationDate"] = (d.get("base") or {}).get("publicationDate")
            rec["orderDescription"] = R.one_line(R.lang_pick((d.get("procurement") or {}).get("orderDescription")), 400)
    except Exception as e:  # noqa: BLE001
        rec["error"] = str(e)
    out["projects"].append(rec)

json.dump(out, open(os.path.join(ROOT, "radar", "diag-result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("Diagnose fertig:", len(out["searches"]), "Suchen,", len(out["projects"]), "Projekte")
