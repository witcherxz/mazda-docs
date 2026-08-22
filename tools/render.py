"""Render the site.

Two shapes come out of one template:
  site/index.html   data inlined — opens from the filesystem, publishes as an artifact
  dist/            shell + data.json — what gets deployed, so the 4 MB payload is
                   fetched separately and served gzipped
"""
import copy, json, os

from common import ROOT

SERVICE_WORKER = """/* Offline support for the deployed site: the shell is cached on install, the
   dataset is served from cache while a fresh copy downloads in the background.
   Readers in a workshop with bad signal still get the guide. */
const CACHE = "mazda-v1";
const SHELL = ["./", "./index.html", "./manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  e.respondWith(caches.open(CACHE).then(async cache => {
    const hit = await cache.match(e.request);
    const live = fetch(e.request).then(res => {
      if (res && res.status === 200) cache.put(e.request, res.clone());
      return res;
    }).catch(() => hit);
    return hit || live;
  }));
});
"""

DOMAIN = "mazda-community.org"          # the CNAME file must ship inside the Pages artifact
SITE_URL = f"https://{DOMAIN}/"

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
            b.pop("t", None)                   # recomputed from the runs in the browser
            for r in b["runs"]:
                r.pop("k", None)               # derived from the URL
    for iv in d["schedule"]:
        for it in iv["replace"] + iv["inspect"]:
            it.pop("t", None)
            for r in it["runs"]:
                r.pop("k", None)
    for doc in d.get("docs", []):
        doc["sections"] = doc["sections"][:25]
        doc["f"] = {k: v for k, v in (doc.get("f") or {}).items() if v}
    return d


def build(data, out=SITE, template=TEMPLATE, dist=DIST, deploy=True):
    """deploy=False renders a preview only, leaving site/ and dist/ untouched."""
    tpl = open(template, encoding="utf-8").read()
    small = compact(data)
    payload = json.dumps(small, ensure_ascii=False, separators=(",", ":"))

    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w", encoding="utf-8").write(tpl.replace("/*__DATA__*/null", payload))

    if not deploy:
        return out, os.path.getsize(out)

    os.makedirs(dist, exist_ok=True)
    shell = tpl.replace("/*__DATA__*/null", "null")
    page = ('<!doctype html><html lang="ar" dir="rtl"><head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<meta name="description" content="دليل صيانة مازدا — عرض منظّم ومحدّث آلياً '
            'من مستند مجتمع مازدا السعودي">'
            '<meta name="theme-color" content="#131619">'
            # shared into Telegram groups more than anywhere else, so the preview matters
            '<meta property="og:type" content="website">'
            '<meta property="og:site_name" content="دليل مازدا المنظم">'
            '<meta property="og:locale" content="ar_SA">'
            '<meta property="og:title" content="دليل مازدا المنظم">'
            '<meta property="og:description" content="بحث في دليل صيانة مازدا: '
            'المواضيع ومصادرها، جدول الصيانة، والشروحات — مولّد آلياً من مستند المجتمع">'
            '<meta name="twitter:card" content="summary">'
            f'<meta property="og:url" content="{SITE_URL}">'
            f'<link rel="canonical" href="{SITE_URL}">'
            '<link rel="manifest" href="manifest.webmanifest">'
            '<link rel="icon" href="data:image/svg+xml,'
            '%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E'
            '%3Ctext y=%22.9em%22 font-size=%2290%22%3E%F0%9F%9A%97%3C/text%3E%3C/svg%3E">'
            '</head><body>' + shell + "</body></html>")
    open(os.path.join(dist, "index.html"), "w", encoding="utf-8").write(page)
    open(os.path.join(dist, "data.json"), "w", encoding="utf-8").write(payload)
    open(os.path.join(dist, "CNAME"), "w", encoding="utf-8").write(DOMAIN + "\n")
    open(os.path.join(dist, "robots.txt"), "w", encoding="utf-8").write(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}sitemap.xml\n")
    open(os.path.join(dist, "sitemap.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f'  <url><loc>{SITE_URL}</loc><changefreq>daily</changefreq></url>\n'
        '</urlset>\n')
    open(os.path.join(dist, "sw.js"), "w", encoding="utf-8").write(SERVICE_WORKER)
    open(os.path.join(dist, "manifest.webmanifest"), "w", encoding="utf-8").write(
        json.dumps({"name": "دليل مازدا المنظم", "short_name": "دليل مازدا",
                    "lang": "ar", "dir": "rtl", "start_url": ".", "display": "standalone",
                    "background_color": "#131619", "theme_color": "#131619"},
                   ensure_ascii=False, indent=1))
    return out, os.path.getsize(out)
