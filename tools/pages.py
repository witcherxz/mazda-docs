"""Static pages, one per topic, so search engines have something to index.

The app is one URL with everything behind hash fragments, which search engines
ignore — so nothing but the home page can rank. These pages give every topic,
article and document a crawlable address with its own title and text, each
linking into the app for the interactive view.
"""
import html
import json
import os
import re

from common import ROOT, norm_ar

SITE = "https://mazda-community.org"
PAGES_DIR = os.path.join(ROOT, "data", "pages")   # solution pages written from the articles
KIND_AR = {"telegram": "تيليقرام", "youtube": "يوتيوب", "google-doc": "مستند",
           "web": "موقع", "nhtsa": "استدعاءات", "archive": "أرشيف",
           "shortlink": "رابط مختصر", "image": "صورة", "maps": "خريطة",
           "instagram": "انستقرام", "twitter": "تويتر", "gdrive": "درايف",
           "internal-anchor": "داخل الدليل", "source-doc": "موضع في المستند"}

CSS = """
:root{color-scheme:dark;--bg:#131619;--fg:#E9E7E2;--dim:#B4BAC2;--line:#2C3238;
  --acc:#E0797E;--card:#1A1E22}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font-family:"IBM Plex Sans Arabic",
  system-ui,sans-serif;line-height:1.7;font-size:16px}
main{max-width:760px;margin:0 auto;padding:28px 20px 64px}
a{color:#8DBBD2}
h1{font-size:26px;margin:0 0 6px;line-height:1.35}
h2{font-size:18px;margin:28px 0 10px}
.crumb{font-size:13px;color:var(--dim);margin-bottom:18px}
.lede{color:var(--dim);margin:0 0 20px}
.open{display:inline-block;margin:6px 0 22px;padding:9px 16px;border:1px solid var(--acc);
  border-radius:5px;color:var(--acc);text-decoration:none;font-weight:600}
ul{margin:0;padding-inline-start:1.1em;display:flex;flex-direction:column;gap:9px}
li{color:var(--dim)} li a{text-decoration:none} li a:hover{text-decoration:underline}
.kind{font-size:12px;color:var(--dim);margin-inline-start:6px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 18px;padding:0;list-style:none}
.tags li{font-size:12px;padding:2px 9px;border:1px solid var(--line);border-radius:99px}
.rel{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.rel a{font-size:14px;padding:4px 10px;border:1px solid var(--line);border-radius:4px;
  text-decoration:none;color:var(--fg)}
footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);font-size:13px;
  color:var(--dim)}
"""

MODEL_AR = {"mazda2": "مازدا 2", "mazda3": "مازدا 3", "mazda6": "مازدا 6", "cx3": "CX-3",
            "cx5": "CX-5", "cx9": "CX-9", "cx30": "CX-30", "cx50": "CX-50",
            "cx60": "CX-60", "cx70": "CX-70", "cx90": "CX-90", "mx5": "MX-5", "mpv": "MPV"}


def slug(name, ident):
    s = norm_ar(name)
    s = re.sub(r"[^\wء-ي]+", "-", s, flags=re.UNICODE).strip("-")
    return f"{s[:60]}-{ident}" if s else ident


def page(title, description, body, path, extra_head="", index=True):
    url = f"{SITE}/{path}"
    robots = "" if index else '<meta name="robots" content="noindex,follow">\n'
    return f"""<!doctype html><html lang="ar" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{robots}<title>{html.escape(title)}</title>
<meta name="description" content="{html.escape(description[:300])}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article"><meta property="og:locale" content="ar_SA">
<meta property="og:title" content="{html.escape(title)}">
<meta property="og:description" content="{html.escape(description[:300])}">
<meta property="og:url" content="{url}">
<meta name="theme-color" content="#131619">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;600&display=swap">
<style>{CSS}</style>{extra_head}
</head><body><main>{body}
<footer>المحتوى من إعداد ومتابعة مجتمع مازدا —
<a href="https://t.me/mzda6">قروب مازدا 6 على تيليقرام</a> ·
هذه الصفحة عرض منظّم آلياً، والمرجع هو
<a href="{{SOURCE}}">المستند الأصلي</a>.</footer>
</main></body></html>"""


def source_list(sources):
    out = []
    for s in sources:
        kind = KIND_AR.get(s.get("kind") or "", "")
        label = html.escape(s.get("label") or "مصدر")
        url = html.escape(s.get("url") or "")
        out.append(f'<li><a href="{url}" rel="noopener">{label}</a>'
                   f'<span class="kind">{kind}</span></li>')
    return "<ul>" + "".join(out) + "</ul>"


def facet_tags(f):
    bits = [MODEL_AR.get(m, m) for m in (f.get("models") or [])]
    bits += (f.get("engines") or [])
    if f.get("turbo") == "turbo":
        bits.append("تيربو")
    bits += [f"{a}–{b}" if a != b else str(a) for a, b in (f.get("years") or [])[:2]]
    if not bits:
        return ""
    return '<ul class="tags">' + "".join(f"<li>{html.escape(str(b))}</li>" for b in bits) + "</ul>"


def load_drafts(folder=PAGES_DIR):
    """{article id: meta} for every article with a solution page; meta["md"] is its file.

    meta.json keeps each page's links as they were when it was drafted, because the
    page cites them by position (L1, L2...) and the article's links shift as it is edited.
    """
    try:
        with open(os.path.join(folder, "meta.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except OSError:
        return {}
    out = {}
    for aid, m in meta.items():
        md = os.path.join(folder, aid + ".md")
        if os.path.exists(md):
            out[aid] = dict(m, md=md)
    return out


def stale_drafts(articles, drafts):
    """Articles edited since their page was drafted. The page still shows; redraft it."""
    import solutions
    return sorted(a["id"] for a in articles if a["id"] in drafts
                  and solutions.input_hash(solutions.article_text(a)[0])
                  != drafts[a["id"]].get("source_hash"))


def build(data, dist, drafts=None):
    """Write a page per topic, article, document and letter, plus the sitemap."""
    source_doc = data["source"]
    urls, written = [], 0
    drafts = load_drafts() if drafts is None else drafts

    def emit(path, markup, index=True, lastmod=None):
        # index=False: the page stays reachable for links people already have, but
        # search engines are told to skip it and the sitemap leaves it out
        nonlocal written
        full = os.path.join(dist, path, "index.html")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        open(full, "w", encoding="utf-8").write(markup)
        if index:
            urls.append((f"{SITE}/{path}/", lastmod))
        written += 1

    def write(path, title, description, body, extra_head="", index=True):
        emit(path, page(title, description, body, path + "/", extra_head, index).replace(
            "{SOURCE}", html.escape(source_doc)), index)

    hub = [t for t in data["topics"] if t.get("doc") == "hub"]
    by_letter = {}
    for t in hub:
        by_letter.setdefault(t.get("letter") or "#", []).append(t)

    # ---- one page per hub topic ----------------------------------------
    # A topic page is only a list of links, not an article, so it is kept out of
    # search results; the article pages are the ones meant to rank.
    for t in hub:
        path = "t/" + slug(t["name"], t["id"])
        t["_path"] = path
    for t in hub:
        siblings = [x for x in by_letter[t.get("letter") or "#"] if x is not t][:12]
        rel = "".join(f'<a href="{SITE}/{x["_path"]}/">{html.escape(x["name"])}</a>'
                      for x in siblings)
        kinds = ", ".join(sorted({KIND_AR.get(s.get("kind") or "", "") for s in t["sources"]} - {""}))
        desc = (f'{t["name"]} — {t["n"]} مصدر من دليل صيانة مازدا: {kinds}. '
                f'{(t.get("note") or "")[:80]}')
        body = (f'<div class="crumb"><a href="{SITE}/">دليل مازدا المنظم</a> ← '
                f'{html.escape(t.get("letter") or "")}</div>'
                f'<h1>{html.escape(t["name"])}</h1>'
                f'<p class="lede">{t["n"]} مصدر جمعها مجتمع مازدا لهذا الموضوع.</p>'
                f'{facet_tags(t.get("f") or {})}'
                f'<a class="open" href="{SITE}/#topic={t["id"]}">افتح في الدليل التفاعلي ←</a>'
                f'<h2>المصادر</h2>{source_list(t["sources"])}'
                + (f'<h2>مواضيع قريبة</h2><div class="rel">{rel}</div>' if rel else ""))
        ld = {"@context": "https://schema.org", "@type": "Article",
              "headline": t["name"], "inLanguage": "ar",
              "isPartOf": {"@type": "WebSite", "name": "دليل مازدا المنظم", "url": SITE + "/"}}
        head = f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>'
        write(t["_path"], f'{t["name"]} — دليل مازدا', desc, body, head, index=False)

    # ---- one page per article ------------------------------------------
    # An article with a solution page gets that page; the rest keep the plain text.
    arts = {a["id"]: a for a in data["articles"]}
    stale = stale_drafts(data["articles"], drafts)
    if stale:
        print(f"→ pages {len(stale)} solution pages drafted from an older article: {', '.join(stale)}")
    for a in data["articles"]:
        path = "a/" + slug(a["title"], a["id"])
        d = drafts.get(a["id"])
        if d:
            import page_render
            markup = page_render.render(d["md"], a["id"], d["links"], arts, review=False,
                                        names=d.get("names", {}), url=f"{SITE}/{path}/",
                                        modified=d.get("drafted"))[0]
            emit(path, markup, lastmod=d.get("drafted"))
            continue
        blocks = []
        for b in a["blocks"][:60]:
            text = html.escape(b.get("t") or " ".join(r["t"] for r in b.get("runs", [])))
            if text.strip():
                blocks.append(f"<p>{text}</p>")
        body = (f'<div class="crumb"><a href="{SITE}/">دليل مازدا المنظم</a> ← شرح</div>'
                f'<h1>{html.escape(a["title"])}</h1>'
                f'<a class="open" href="{SITE}/#tab=arts&art={a["id"]}">افتح في الدليل التفاعلي ←</a>'
                + "".join(blocks))
        write(path, f'{a["title"]} — دليل مازدا', (a.get("norm") or a["title"])[:280], body)

    # ---- one page per satellite document --------------------------------
    # These show only a title and counts, not the document's text, so they are kept
    # out of search until they carry real content.
    for doc in data.get("docs", []):
        secs = "".join(f'<li>{html.escape(s["title"])}</li>' for s in doc.get("sections", [])[:40])
        body = (f'<div class="crumb"><a href="{SITE}/">دليل مازدا المنظم</a> ← مستند</div>'
                f'<h1>{html.escape(doc["title"])}</h1>'
                f'<p class="lede">{doc["topics"]} موضوع · {doc["links"]} رابط</p>'
                f'<a class="open" href="{SITE}/#tab=topics&doc={doc["id"]}">'
                f'مواضيع هذا المستند في الدليل ←</a>'
                + (f'<h2>أقسامه</h2><ul>{secs}</ul>' if secs else "")   # most docs have none
                + f'<p><a href="{html.escape(doc["url"])}" rel="noopener">فتح المستند في قوقل ←</a></p>')
        write("d/" + slug(doc["title"], doc["id"][:8]), f'{doc["title"]} — دليل مازدا',
              f'{doc["title"]}: {doc["topics"]} موضوع من مستندات مجتمع مازدا', body, index=False)

    # ---- a page per index letter: a list of topic pages, so also not indexed ---
    for letter, topics in by_letter.items():
        links = "".join(f'<li><a href="{SITE}/{t["_path"]}/">{html.escape(t["name"])}</a>'
                        f'<span class="kind">{t["n"]} مصدر</span></li>' for t in topics)
        body = (f'<div class="crumb"><a href="{SITE}/">دليل مازدا المنظم</a> ← فهرس</div>'
                f'<h1>مواضيع حرف {html.escape(letter)}</h1>'
                f'<p class="lede">{len(topics)} موضوع.</p><ul>{links}</ul>')
        write("l/" + slug(letter, "idx"), f'حرف {letter} — فهرس دليل مازدا',
              f'مواضيع دليل صيانة مازدا التي تبدأ بحرف {letter}', body, index=False)

    # ---- sitemap --------------------------------------------------------
    day = (data.get("built_at") or "")[:10]
    entries = [f"  <url><loc>{SITE}/</loc><changefreq>daily</changefreq>"
               f"<priority>1.0</priority></url>"]
    entries += [f"  <url><loc>{u}</loc><lastmod>{lastmod or day}</lastmod>"
                f"<changefreq>weekly</changefreq></url>" for u, lastmod in urls]
    open(os.path.join(dist, "sitemap.xml"), "w", encoding="utf-8").write(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries) + "\n</urlset>\n")
    return written, len(urls)
