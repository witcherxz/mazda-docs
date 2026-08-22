"""Render the site.

Two shapes come out of one template:
  site/index.html   data inlined — opens from the filesystem, publishes as an artifact
  dist/            shell + data.json — what gets deployed, so the 4 MB payload is
                   fetched separately and served gzipped
"""
import copy, json, os

from common import ROOT

TEMPLATE = os.path.join(ROOT, "tools", "template.html")
SITE = os.path.join(ROOT, "site", "index.html")
DIST = os.path.join(ROOT, "dist")


def compact(data):
    """Drop anything the browser can recompute, and cap the long text fields."""
    d = copy.deepcopy(data)
    for t in d["topics"]:
        t.pop("norm", None)                    # derived from the name in JS
        for s in t["sources"]:
            s.pop("kind", None)                # derived from the URL in JS
        if t.get("snorm"):
            t["snorm"] = t["snorm"][:160]
        if not t.get("note"):
            t.pop("note", None)
        f = t.get("f") or {}
        t["f"] = {k: v for k, v in f.items() if v}
    for a in d["articles"]:
        a["norm"] = a.get("norm", "")[:3000]
        for b in a["blocks"]:
            for l in b["links"]:
                l.pop("kind", None)
    for iv in d["schedule"]:
        for it in iv["replace"] + iv["inspect"]:
            for l in it["links"]:
                l.pop("kind", None)
    for doc in d.get("docs", []):
        doc["sections"] = doc["sections"][:25]
        doc["f"] = {k: v for k, v in (doc.get("f") or {}).items() if v}
    return d


def build(data, out=SITE, template=TEMPLATE, dist=DIST):
    tpl = open(template, encoding="utf-8").read()
    small = compact(data)
    payload = json.dumps(small, ensure_ascii=False, separators=(",", ":"))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/null", payload))

    os.makedirs(dist, exist_ok=True)
    shell = tpl.replace("/*__DATA__*/null", "null")
    page = ('<!doctype html><html lang="ar" dir="rtl"><head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="description" content="دليل صيانة مازدا — عرض منظّم ومحدّث آلياً '
            'من مستند مجتمع مازدا السعودي">'
            '<meta name="theme-color" content="#8C1D24">'
            '<link rel="manifest" href="manifest.webmanifest">'
            '<link rel="icon" href="data:image/svg+xml,'
            '%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E'
            '%3Ctext y=%22.9em%22 font-size=%2290%22%3E%F0%9F%9A%97%3C/text%3E%3C/svg%3E">'
            '</head><body>' + shell + "</body></html>")
    open(os.path.join(dist, "index.html"), "w", encoding="utf-8").write(page)
    open(os.path.join(dist, "data.json"), "w", encoding="utf-8").write(payload)
    open(os.path.join(dist, "manifest.webmanifest"), "w", encoding="utf-8").write(
        json.dumps({"name": "دليل مازدا المنظم", "short_name": "دليل مازدا",
                    "lang": "ar", "dir": "rtl", "start_url": ".", "display": "standalone",
                    "background_color": "#FAF9F6", "theme_color": "#8C1D24"},
                   ensure_ascii=False, indent=1))
    return out, os.path.getsize(out)
