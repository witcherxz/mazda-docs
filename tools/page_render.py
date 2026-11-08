"""Render a free-form solution page (data/pages/<id>.md) into a structured, readable HTML page.

The site build calls render() for every article that has a page. As a script it renders
review copies of drafts, with the draft banner and the reviewer panel:

usage: page_render.py CRUNCH_DIR ARTICLE_ID [ARTICLE_ID ...]

The page keeps everything the model wrote, but gives it a fixed shape:
answer card -> quick diagnosis (rows jump to their section) -> contents ->
one card per cause with labelled steps -> parts and prices folded -> warnings
-> uncited sources grouped by type -> reviewer panel (draft only).
"""
import html as H
import json
import os
import re
import sys

import solutions
from common import ROOT, norm_ar

SITE = "https://mazda-community.org"
OPEN = ""


def slug(name, ident):
    import pages  # late: pages imports this module while it builds
    return pages.slug(name, ident)

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap")

CSS = """
:root{--ground:#131619;--surface:#1A1E22;--surface-2:#22272C;--surface-3:#2B3138;
--ink:#E9E7E2;--ink-2:#B4BAC2;--ink-3:#848D98;--rule:#2C3238;--rule-strong:#3E464F;
--accent:#E0797E;--accent-bg:#332123;--steel:#8DBBD2;--steel-bg:#1C2A33;
--tg:#8DBBD2;--yt:#E0797E;--gd:#87C298;--web:#AEA898;--nh:#E0A34E;--int:#A79AD1;
--ok:#87C298;--ok-bg:#1B2A20;--warn:#D3A055;--warn-bg:#2E2516;
--f-sym:#8DBBD2;--f-check:#A79AD1;--f-fix:#87C298;--f-cause:#E0A34E;--f-when:#6FB3A8;--f-prevent:#AEA898;
color-scheme:dark}
:root[data-theme="light"]{--ground:#FAF9F6;--surface:#FFFFFF;--surface-2:#F2F0EB;--surface-3:#E9E6DF;
--ink:#16191D;--ink-2:#4A525E;--ink-3:#7A828E;--rule:#DFDBD3;--rule-strong:#C6C0B5;
--accent:#8C1D24;--accent-bg:#F6E8E7;--steel:#2C6079;--steel-bg:#E4EEF3;
--tg:#2C6079;--yt:#8C1D24;--gd:#3D6F4C;--web:#6A6558;--nh:#A9690A;--int:#574A8C;
--ok:#3D6F4C;--ok-bg:#E8F1EA;--warn:#9A6510;--warn-bg:#FBF1DE;
--f-sym:#2C6079;--f-check:#574A8C;--f-fix:#3D6F4C;--f-cause:#A9690A;--f-when:#2F6E64;--f-prevent:#6A6558;
color-scheme:light}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:12px}
body{margin:0;background:var(--ground);color:var(--ink);font-family:"IBM Plex Sans Arabic",system-ui,sans-serif;
font-size:16px;line-height:1.75;-webkit-font-smoothing:antialiased}
main{max-width:780px;margin:0 auto;padding:18px 16px 60px;direction:rtl;text-align:right}
h1,h2,h3{font-family:"IBM Plex Sans Arabic",system-ui,sans-serif;font-weight:600;margin:0;text-wrap:balance}
a{color:var(--steel);text-decoration:none}a:hover{text-decoration:underline;text-underline-offset:3px}
p{margin:0 0 10px}ul{margin:0 0 10px;padding-inline-start:20px}li{margin:0 0 6px}li::marker{color:var(--ink-3)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}

.draft{background:var(--warn-bg);color:var(--warn);border:1px dashed var(--warn);border-radius:6px;
padding:8px 12px;font-size:13.5px;margin:0 0 14px}
.top{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--ink-3);margin:0 0 12px}
.top .sp{flex:1}.top button{font:inherit;color:var(--ink-3);background:none;border:1px solid var(--rule);
border-radius:4px;padding:3px 10px;cursor:pointer}.top button:hover{color:var(--accent);border-color:var(--accent)}
h1{font-size:26px;font-weight:700;line-height:1.45;margin:0 0 8px}
.meta{font-size:13px;color:var(--ink-3);margin:0 0 18px;display:flex;flex-wrap:wrap;gap:4px 14px}

.card{background:var(--surface);border:1px solid var(--rule);border-radius:10px;padding:16px 18px;margin:0 0 16px}
.lbl{display:inline-block;font-size:12.5px;font-weight:600;letter-spacing:.02em;margin:0 0 6px}
.answer{border-color:var(--ok);background:linear-gradient(var(--ok-bg),var(--surface) 70%)}
.answer .lbl{color:var(--ok)}.answer p{font-size:16.5px}.answer p:last-child{margin:0}

.diag .lbl{color:var(--steel)}
.drow{display:grid;grid-template-columns:1fr auto 1fr;gap:6px 12px;align-items:start;padding:10px 0;
border-top:1px solid var(--rule)}
.drow:first-of-type{border-top:0}
.drow .when{color:var(--ink)}.drow .arr{color:var(--ink-3);padding-top:1px}
.drow .go{font-weight:500}.drow .go a{display:inline-block}
.dhead{display:grid;grid-template-columns:1fr auto 1fr;gap:12px;font-size:12.5px;color:var(--ink-3);padding:0 0 4px}
.dhead span:nth-child(2){visibility:hidden}

.toc .lbl{color:var(--ink-3)}
.toc ol{margin:0;padding:0;list-style:none;counter-reset:t}
.toc li{counter-increment:t;margin:0;padding:6px 0;border-top:1px solid var(--rule)}
.toc li:first-child{border-top:0}
.toc li>a::before{content:counter(t);display:inline-grid;place-items:center;width:22px;height:22px;
border-radius:50%;background:var(--surface-3);color:var(--ink-2);font-size:12px;margin-inline-end:8px}
.toc .subs{display:flex;flex-wrap:wrap;gap:6px;margin:6px 30px 0 0}
.toc .subs a{font-size:13px;background:var(--surface-2);border:1px solid var(--rule);border-radius:999px;padding:1px 10px;color:var(--ink-2)}

section.cause{margin:26px 0 0}
.chead{display:flex;align-items:center;gap:10px;margin:0 0 10px}
.num{flex:none;display:grid;place-items:center;width:30px;height:30px;border-radius:50%;
background:var(--accent-bg);color:var(--accent);font-weight:600;font-size:14px}
h2{font-size:21px;line-height:1.45}
h3{font-size:17px;margin:4px 0 10px;color:var(--ink)}
.sub{border-top:1px dashed var(--rule-strong);padding-top:14px;margin-top:14px}
.sub:first-child{border-top:0;padding-top:0;margin-top:0}

.facet{border-inline-start:3px solid var(--fc,var(--rule-strong));padding:2px 12px 2px 0;margin:0 0 12px}
.facet .fl{font-size:13px;font-weight:600;color:var(--fc,var(--ink-2));margin:0 0 2px}
.facet .fl small{font-weight:400;color:var(--ink-3)}
.facet p:last-child,.facet ul:last-child{margin-bottom:0}
.f-sym{--fc:var(--f-sym)}.f-check{--fc:var(--f-check)}.f-fix{--fc:var(--f-fix)}
.f-cause{--fc:var(--f-cause)}.f-when{--fc:var(--f-when)}.f-prevent{--fc:var(--f-prevent)}

details.parts{background:var(--surface-2);border:1px solid var(--rule);border-radius:8px;margin:4px 0 12px}
details.parts>summary{cursor:pointer;list-style:none;padding:10px 14px;font-weight:600;font-size:14.5px;
display:flex;align-items:center;gap:8px}
details.parts>summary::-webkit-details-marker{display:none}
details.parts>summary::before{content:"";width:7px;height:7px;border-inline-start:2px solid var(--ink-3);
border-bottom:2px solid var(--ink-3);transform:rotate(-45deg);transition:transform .15s;margin-inline-end:4px}
details.parts[open]>summary::before{transform:rotate(-135deg)}
details.parts>summary .n,details.parts>summary .hint{font-weight:400;font-size:12.5px;color:var(--ink-3)}
details.parts>summary .hint{margin-inline-start:auto}details.parts[open]>summary .hint{display:none}
.pbody{padding:2px 14px 12px}
.pgroup{margin:0 0 10px}.pgroup .pl{font-size:13px;font-weight:600;color:var(--ink-2);margin:6px 0 4px}
.pbody ul{list-style:none;padding:0;margin:0}
.pbody li{background:var(--surface);border:1px solid var(--rule);border-radius:6px;padding:8px 10px;margin:0 0 6px;font-size:15px}

code.pn{font-family:"IBM Plex Mono",monospace;font-size:13.5px;background:var(--surface-3);border-radius:4px;
padding:1px 6px;direction:ltr;unicode-bidi:isolate;white-space:nowrap;color:var(--ink)}
.price{font-weight:600;color:var(--ok);white-space:nowrap}
.date{font-family:"IBM Plex Mono",monospace;font-size:12.5px;color:var(--ink-3);direction:ltr;unicode-bidi:isolate;white-space:nowrap}
.nodate{font-size:12.5px;color:var(--ink-3)}
bdi.code{font-family:"IBM Plex Mono",monospace;font-size:14px}

.warn{display:flex;gap:10px;background:var(--warn-bg);border:1px solid color-mix(in srgb,var(--warn) 45%,transparent);
border-radius:8px;padding:10px 12px;margin:0 0 12px}
.warn::before{content:"!";flex:none;display:grid;place-items:center;width:22px;height:22px;border-radius:50%;
background:var(--warn);color:var(--ground);font-weight:700;font-size:14px;margin-top:2px}
.warn div{flex:1}.warn p:last-child{margin:0}

a.src{border-bottom:1px dotted currentColor}a.src:hover{text-decoration:none;border-bottom-style:solid}
a.src::after{content:attr(data-k);font-size:10px;font-weight:600;border-radius:3px;padding:0 4px;
margin-inline-start:4px;vertical-align:2px;background:var(--surface-3);color:var(--kc,var(--ink-2))}
a.k-yt{--kc:var(--yt)}a.k-tg{--kc:var(--tg)}a.k-gd{--kc:var(--gd)}a.k-nh{--kc:var(--nh)}a.k-int{--kc:var(--int)}a.k-web{--kc:var(--web)}

.tw{overflow-x:auto;margin:0 0 12px}
table{border-collapse:collapse;width:100%;font-size:14.5px}
th,td{border-bottom:1px solid var(--rule);padding:8px;text-align:right;vertical-align:top}
th{font-weight:600;font-size:13px;color:var(--ink-3);background:var(--surface-2)}
.back{display:inline-block;font-size:12.5px;color:var(--ink-3);margin-top:4px}

.more h2{font-size:18px;margin:0 0 10px}
.more .grp{margin:0 0 10px}.more .gl{font-size:13px;color:var(--ink-3);margin:0 0 4px}
.more ul{margin:0;padding-inline-start:18px;font-size:14.5px}

.review{margin-top:30px;border:1px dashed var(--warn);background:transparent}
.review h2{font-size:17px;color:var(--warn);margin:0 0 10px}
.serp{background:var(--surface);border:1px solid var(--rule);border-radius:8px;padding:10px 12px;margin:0 0 12px}
.serp .u{font-size:12.5px;color:var(--ink-3);direction:ltr;text-align:left}
.serp .t{font-size:18px;color:var(--steel);line-height:1.4;margin:2px 0}
.serp .d{font-size:14px;color:var(--ink-2)}
.review ul{font-size:14.5px}
.stats{font-size:13px;color:var(--ink-3)}
footer{font-size:13px;color:var(--ink-3);border-top:1px solid var(--rule);margin-top:30px;padding-top:12px}

@media (max-width:560px){
 h1{font-size:23px}h2{font-size:19px}main{padding:14px 16px 50px}.card{padding:14px}
 .drow,.dhead{grid-template-columns:1fr}.dhead{display:none}
 .drow .arr{display:none}.drow .go::before{content:"افحص: ";color:var(--ink-3);font-weight:400}
 table.stack thead{display:none}table.stack tr{display:block;border:1px solid var(--rule);border-radius:6px;margin:0 0 8px;padding:4px 8px}
 table.stack td{display:block;border:0;padding:4px 0}
 table.stack td::before{content:attr(data-l);display:block;font-size:12px;color:var(--ink-3)}
}
@media print{details.parts>.pbody{display:block}.top button{display:none}}
"""

SCRIPT = """
(function(){var r=document.documentElement,b=document.getElementById('theme');
function set(m){if(m==='light')r.setAttribute('data-theme','light');else r.removeAttribute('data-theme');
b.textContent=m==='light'?'الوضع الداكن':'الوضع الفاتح';try{localStorage.setItem('theme',m)}catch(e){}}
var m='dark';try{m=localStorage.getItem('theme')||m}catch(e){}set(m);
b.onclick=function(){set(r.getAttribute('data-theme')==='light'?'dark':'light')};
document.addEventListener('click',function(e){var a=e.target.closest('a[href^="#"]');if(!a)return;
var t=document.getElementById(decodeURIComponent(a.hash.slice(1)));if(!t)return;
var d=t.closest('details');if(d)d.open=true;});})();
"""

# ---------------------------------------------------------------- inline text

PN = re.compile(r"(?<![\w.-])(?:"
                r"(?=[A-Za-z0-9-]*\d)(?=[A-Za-z0-9-]*[A-Za-z])(?=(?:[A-Za-z0-9]-?){8,})[A-Za-z0-9]{2,}(?:-[A-Za-z0-9]+)+"
                r"|(?=\w*\d)(?=\w*[A-Za-z])[A-Za-z0-9]{8,}"
                r"|\d{2}\.\d{8}\.\d)(?![\w-]|\.\w)")
PRICE = re.compile(r"(\d[\d.,]*(?:\s?-\s?\d[\d.,]*)?)\s?(ريال|رس)(?![\w])")
DATE = re.compile(r"(?<![\d/])(\d{1,2}/\d{4})(?![\d/])")
LINK = re.compile(r"\[([^\]]+)\]\(L(\d+)\)")
KINDS = {"yt": "فيديو", "tg": "تيليجرام", "gd": "ملف", "nh": "نشرة", "int": "قسم", "web": "موقع"}


def kind(run, arts):
    if run.get("nav") and run["nav"].get("a") in arts:
        return "int"
    u = run["u"].lower()
    if "youtu" in u:
        return "yt"
    if "t.me/" in u:
        return "tg"
    if "docs.google" in u:
        return "gd"
    if "nhtsa" in u:
        return "nh"
    return "web"


def href(run, arts):
    nav = run.get("nav")
    if nav and nav.get("a") in arts:
        a = arts[nav["a"]]
        return f"{SITE}/a/{slug(a['title'], a['id'])}/"
    return None if run["u"].startswith("#") else run["u"]


def mark(s):
    """Escape plain text and highlight part numbers, prices and dates."""
    s = H.escape(s, quote=False)
    s = re.sub(r"\*\*([^*\s][^*]*?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r'<bdi class="code" dir="ltr">\1</bdi>', s)
    s = PN.sub(lambda m: f'<code class="pn">{m.group(0)}</code>', s)
    s = PRICE.sub(r'<span class="price">\1 \2</span>', s)
    s = DATE.sub(r'<span class="date">\1</span>', s)
    s = s.replace("(بدون تاريخ)", '<span class="nodate">(بدون تاريخ)</span>')
    return s


class Ctx:
    def __init__(self, links, arts):
        self.links, self.arts, self.cited = links, arts, set()
        self.heads = []          # (id, heading) of every section, filled in by render()

    def cell(self, text, first):
        """A table cell; a first-column cell that names a section links to it."""
        if first and not LINK.search(text):
            t = toks(text)
            for hid, h in self.heads:
                if t and t == toks(h):
                    return f'<a href="#{hid}">{self.inline(text)}</a>'
        return self.inline(text)

    def inline(self, s):
        out, pos = [], 0
        for m in LINK.finditer(s):
            out.append(mark(s[pos:m.start()]))
            n, text = int(m.group(2)), m.group(1)
            run = self.links[n - 1] if 1 <= n <= len(self.links) else None
            url = href(run, self.arts) if run else None
            if url:
                self.cited.add(n)
                k = kind(run, self.arts)
                out.append(f'<a class="src k-{k}" data-k="{KINDS[k]}" href="{H.escape(url)}" rel="noopener">'
                           f'{H.escape(text)}</a>')
            else:
                out.append(H.escape(text))
            pos = m.end()
        out.append(mark(s[pos:]))
        return "".join(out)

# ---------------------------------------------------------------- block parse


def blocks(md):
    out, L, i = [], md.split("\n"), 0
    while i < len(L):
        line = L[i].rstrip()
        if not line.strip():
            i += 1
        elif line.startswith("### "):
            out.append(("h3", line[4:].strip())); i += 1
        elif line.startswith("## "):
            out.append(("h2", line[3:].strip())); i += 1
        elif line.startswith(">"):
            q = []
            while i < len(L) and L[i].startswith(">"):
                q.append(L[i].lstrip(">").strip()); i += 1
            out.append(("quote", " ".join(q)))
        elif line.startswith("- "):
            items = []
            while i < len(L) and L[i].startswith("- "):
                items.append(L[i][2:].strip()); i += 1
            out.append(("ul", items))
        elif line.startswith("|"):
            rows = []
            while i < len(L) and L[i].startswith("|"):
                rows.append([c.strip() for c in L[i].strip().strip("|").split("|")]); i += 1
            out.append(("table", [rows[0]] + [r for r in rows[1:] if not re.fullmatch(r"[-: ]*", "".join(r))]))
        else:
            out.append(("p", line.strip())); i += 1
    return out


LABEL = re.compile(r"^\*\*(.+?)\*\*\s*:?\s*(.*)$")
FACETS = [("sym", ("تعرف", "العلامات", "علامات", "الأعراض", "ما تلاحظ")),
          ("check", ("تفحص", "الفحص", "افحص")),
          ("fix", ("الحل", "حل ", "العلاج")),
          ("cause", ("الأسباب", "السبب", "سبب آخر")),
          ("when", ("متى",)),
          ("prevent", ("لتجنب", "الوقاية"))]


def facet_kind(label):
    if label.strip(" :") in ("غيّر", "غير", "تغيير", "يتغير"):  # a schedule step's change list
        return "fix"
    for k, words in FACETS:
        if any(w in label for w in words):
            return k
    return ""


def partsy(texts):
    """True when the text is mostly part numbers and prices."""
    hits = sum(1 for t in texts if PN.search(t) or PRICE.search(t))
    return hits and hits >= max(1, len(texts) * 0.5)


def group_facets(bl):
    """Turn '**label:** text' paragraphs (plus the list they introduce) into facets."""
    out, i = [], 0
    while i < len(bl):
        kind_, val = bl[i]
        m = LABEL.match(val) if kind_ == "p" else None
        if not m:
            out.append(bl[i]); i += 1; continue
        label, rest = m.group(1).rstrip(":"), m.group(2)
        body = [("p", rest)] if rest and not rest.endswith(":") else []
        note = rest.rstrip(":") if rest.endswith(":") else ""
        i += 1
        if i < len(bl) and bl[i][0] == "ul" and (not rest or rest.endswith(":") or len(rest) < 60):
            if body and len(rest) < 60:
                note, body = rest, []
            body.append(bl[i]); i += 1
        texts = [t for k, v in body for t in (v if k == "ul" else [v])]
        # a labelled step (how to tell, the fix, what to change) stays open even when it
        # names part numbers; only part lists themselves are folded
        is_parts = label.startswith("القطع") or (not facet_kind(label) and partsy(texts))
        out.append(("parts" if is_parts else "facet", label, note, body))
    # merge consecutive parts facets into one folded group
    merged = []
    for b in out:
        if b[0] == "parts" and merged and merged[-1][0] == "partsgroup":
            merged[-1][1].append(b)
        elif b[0] == "parts":
            merged.append(("partsgroup", [b]))
        else:
            merged.append(b)
    return merged

# ---------------------------------------------------------------- render


def render_body(body, cx):
    out = []
    for k, v in body:
        if k == "p":
            out.append(f"<p>{cx.inline(v)}</p>")
        elif k == "ul":
            if all(LABEL.match(x) for x in v):  # a list of '**label:** text' items
                for x in v:
                    m = LABEL.match(x)
                    fk = facet_kind(m.group(1))
                    out.append(f'<div class="facet f-{fk}"><div class="fl">{cx.inline(m.group(1).rstrip(":"))}</div>'
                               f'<p>{cx.inline(m.group(2))}</p></div>')
            else:
                out.append("<ul>" + "".join(f"<li>{cx.inline(x)}</li>" for x in v) + "</ul>")
        elif k == "quote":
            out.append(f'<div class="warn" role="note"><div><p>{cx.inline(v)}</p></div></div>')
        elif k == "table":
            head = v[0]
            th = "".join(f"<th>{cx.inline(c)}</th>" for c in head)
            rows = "".join("<tr>" + "".join(f'<td data-l="{H.escape(head[j] if j < len(head) else "")}">'
                                            f"{cx.cell(c, j == 0)}</td>" for j, c in enumerate(r)) + "</tr>"
                           for r in v[1:])
            out.append(f'<div class="tw"><table class="stack"><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table></div>')
        else:
            raise ValueError(k)
    return "".join(out)


def render_items(items, cx):
    out = []
    for b in items:
        if b[0] == "facet":
            _, label, note, inner = b
            fk = facet_kind(label)
            n = f" <small>{cx.inline(note)}</small>" if note else ""
            out.append(f'<div class="facet f-{fk}"><div class="fl">{cx.inline(label)}{n}</div>{render_body(inner, cx)}</div>')
        elif b[0] == "partsgroup":
            groups, count = [], 0
            for _, label, note, inner in b[1]:
                count += sum(len(v) if k == "ul" else 1 for k, v in inner)
                pieces = []
                for k, v in inner:
                    items_ = v if k == "ul" else [v]
                    pieces.append("<ul>" + "".join(f"<li>{cx.inline(x)}</li>" for x in items_) + "</ul>")
                lab = "" if label.startswith("القطع") and len(b[1]) == 1 else cx.inline(label)
                n = f" <small>{cx.inline(note)}</small>" if note else ""
                groups.append(f'<div class="pgroup">{f"<div class=pl>{lab}{n}</div>" if lab or n else ""}{"".join(pieces)}</div>')
            out.append(f'<details class="parts"{OPEN}><summary>القطع والأسعار <span class="n">{count} بند</span><span class="hint">اضغط للعرض</span>'
                       f'</summary><div class="pbody">{"".join(groups)}</div></details>')
        else:
            out.append(render_body([b], cx))
    return "".join(out)


def toks(s):
    s = norm_ar(re.sub(r"\(.*?\)|\[|\]\(L\d+\)", " ", s))
    return {re.sub(r"^(وال|بال|ال|و)", "", w) for w in re.findall(r"[\wء-ي]+", s) if len(w) > 2} - {"ثم", "اول", "باقي", "مازدا"}


def find_target(text, heads):
    best, score = None, 0.0
    t = toks(text)
    if not t:
        return None
    for hid, h in heads:
        s = len(t & toks(h)) / len(t)
        if s > score:
            best, score = hid, s
    if score >= 0.5:
        return best
    # fall back to a distinctive word that only one heading shares
    hits = {hid for hid, h in heads for w in t & toks(h) if len(w) >= 5}
    return hits.pop() if len(hits) == 1 else None


def diag_cell(cell, heads, cx):
    if LINK.search(cell):
        return cx.inline(cell)
    parts = re.split(r"(،\s*ثم\s+|،\s*)", cell)
    out = []
    for p in parts:
        if re.fullmatch(r"،\s*ثم\s+|،\s*", p or ""):
            out.append(H.escape(p)); continue
        hid = find_target(p, heads)
        out.append(f'<a href="#{hid}">{cx.inline(p)}</a>' if hid else cx.inline(p))
    return "".join(out)


def link_names(path):
    """Readable names for links whose own label is only a number or symbol."""
    out = {}
    try:
        lines = open(path, encoding="utf8").read().splitlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"L(\d+) \[(.*?)\] (.*)", line)
        if not m:
            continue
        n, label, info = int(m.group(1)), m.group(2), m.group(3)
        if solutions.real_name(label):
            continue
        x = (re.match(r"YouTube video: (.*?)(?: \(channel: .*\))?$", info)
             or re.match(r"(?:community document|section of this guide): (.*)", info))
        if x:
            out[n] = x.group(1)
        elif info.startswith("Telegram post: "):
            t = info[len("Telegram post: "):]
            out[n] = t if len(t) <= 90 else t[:90].rsplit(" ", 1)[0] + "…"
        elif info.startswith("Mazda service bulletin"):
            out[n] = "نشرة صيانة من مازدا"
    return out


def render(md_path, aid, links, arts, review=True, open_parts=False, names=None, url=None, modified=None):
    """links: the article's linked runs as they were when the page was drafted (L1 first).
    names: readable names for links labelled only with a number; read from links.txt
    beside the draft when not given. url: the page's own address, which adds the
    canonical, Open Graph and structured-data tags that a published page needs."""
    page_url = url                      # `url` is reused below for each source link
    raw = open(md_path, encoding="utf8").read()
    _, fm, rest = raw.split("---\n", 2)
    body_md, _, unc = rest.rpartition("---\nunclear:")
    if not body_md:
        body_md, unc = rest, ""
    title = re.search(r"title: (.*)", fm).group(1).strip()
    summary = re.search(r"summary: (.*)", fm).group(1).strip()
    unclear = [x[2:].strip() for x in unc.strip().split("\n") if x.startswith("- ")]
    om = re.search(r"^omit:(.*)$", unc, re.M)
    omit = {int(x) for x in re.findall(r"\d+", om.group(1))} if om else set()
    global OPEN
    OPEN = " open" if open_parts else ""
    cx = Ctx(links, arts)
    bl = blocks(body_md)

    # split into intro and sections, giving every heading an id
    intro, secs, cur, heads = [], [], None, []
    for b in bl:
        if b[0] == "h2":
            cur = {"id": f"s{len(secs) + 1}", "title": b[1], "intro": [], "subs": []}
            secs.append(cur); heads.append((cur["id"], b[1]))
        elif b[0] == "h3" and cur:
            sub = {"id": f"{cur['id']}-{len(cur['subs']) + 1}", "title": b[1], "blocks": []}
            cur["subs"].append(sub); heads.append((sub["id"], b[1]))
        elif cur is None:
            intro.append(b)
        elif cur["subs"]:
            cur["subs"][-1]["blocks"].append(b)
        else:
            cur["intro"].append(b)

    cx.heads = heads
    # intro: answer paragraphs, then the first table as quick diagnosis, then the rest
    ti = next((i for i, b in enumerate(intro) if b[0] == "table"), None)
    answer = intro[:ti] if ti is not None else intro[:2]
    diag = intro[ti][1] if ti is not None else None
    after = intro[ti + 1:] if ti is not None else intro[2:]

    html = [f'<div class="top"><span><a href="{SITE}/">دليل مازدا المنظم</a> ← شرح</span><span class="sp"></span>'
            f'<button id="theme" type="button">الوضع الفاتح</button></div>']
    if review:
        html.insert(0, '<div class="draft">مسودة للمراجعة، لم يراجعها أحد بعد. كتبها الذكاء الاصطناعي من ملفات المجتمع.</div>')
    html.append(f"<h1>{H.escape(title)}</h1>")
    html.append(f'<div class="meta"><span>من ملفات ومقالات مجتمع ملاك مازدا</span><span>{len(secs)} أقسام</span></div>')
    html.append('<div class="card answer"><div class="lbl">الجواب المختصر</div>'
                + render_body([b for b in answer if b[0] != "table"], cx) + "</div>")
    if diag and sum(bool(find_target(r[1], heads)) or bool(LINK.search(r[1])) for r in diag[1:] if len(r) > 1) * 2 < len(diag) - 1:
        # a lookup table (model -> part number), not a symptom -> section map: show it as a plain table
        after = [("table", diag)] + after
        diag = None
    if diag:
        head = diag[0]
        rows = "".join(f'<div class="drow"><div class="when">{cx.inline(r[0])}</div><div class="arr">←</div>'
                       f'<div class="go">{diag_cell(r[1] if len(r) > 1 else "", heads, cx)}</div></div>'
                       for r in diag[1:])
        html.append(f'<div class="card diag"><div class="lbl">شخّص بسرعة</div>'
                    f'<div class="dhead"><span>{cx.inline(head[0])}</span><span>←</span>'
                    f'<span>{cx.inline(head[1] if len(head) > 1 else "")}</span></div>{rows}</div>')
    if after:
        html.append(render_items(group_facets(after), cx))
    if len(secs) > 1:
        items = "".join(
            f'<li><a href="#{s["id"]}">{H.escape(s["title"])}</a>'
            + ('<div class="subs">' + "".join(f'<a href="#{u["id"]}">{H.escape(u["title"])}</a>' for u in s["subs"]) + "</div>"
               if s["subs"] else "") + "</li>" for s in secs)
        html.append(f'<nav class="card toc" id="toc" aria-label="المحتويات"><div class="lbl">في هذه الصفحة</div><ol>{items}</ol></nav>')
    for n, s in enumerate(secs, 1):
        inner = render_items(group_facets(s["intro"]), cx)
        for u in s["subs"]:
            inner += (f'<div class="sub" id="{u["id"]}"><h3>{H.escape(u["title"])}</h3>'
                      f'{render_items(group_facets(u["blocks"]), cx)}</div>')
        html.append(f'<section class="cause" id="{s["id"]}"><div class="chead"><span class="num">{n}</span>'
                    f'<h2>{H.escape(s["title"])}</h2></div><div class="card">{inner}'
                    f'<a class="back" href="#toc">↑ المحتويات</a></div></section>')

    # uncited sources, grouped by kind, named from links.txt (video titles, post text)
    if names is None:
        names = link_names(os.path.join(os.path.dirname(md_path), "links.txt"))
    groups, names_, dropped = {}, {int(k): v for k, v in names.items()}, []
    for i, r in enumerate(links, 1):
        url = href(r, arts)
        if i in cx.cited or not url:
            continue
        if i in omit:
            dropped.append(f'<li><a href="{H.escape(url)}" rel="noopener">{H.escape(names_.get(i) or solutions.link_label(r))}</a></li>')
            continue
        groups.setdefault(kind(r, arts), []).append(
            f'<li><a href="{H.escape(url)}" rel="noopener">{H.escape(names_.get(i) or solutions.link_label(r))}</a></li>')
    names = {"int": "أقسام أخرى في الدليل", "gd": "ملفات المجتمع", "yt": "فيديوهات", "tg": "منشورات تيليجرام",
             "nh": "نشرات مازدا", "web": "مواقع أخرى"}
    if groups:
        g = "".join(f'<div class="grp"><div class="gl">{names[k]}</div><ul>{"".join(v)}</ul></div>'
                    for k, v in sorted(groups.items(), key=lambda kv: list(names).index(kv[0])))
        html.append(f'<div class="card more" style="margin-top:26px"><h2>مصادر إضافية</h2>{g}</div>')

    words = len(re.findall(r"\S+", body_md))
    if review:
        unc_html = "".join(f"<li>{cx.inline(x)}</li>" for x in unclear) or "<li>لا شيء</li>"
        html.append(f'<div class="card review"><h2>للمراجع فقط، لا تنشر</h2>'
                    f'<div class="lbl" style="color:var(--ink-3)">كيف يظهر في جوجل</div>'
                    f'<div class="serp"><div class="u">mazda-community.org › a › …</div><div class="t">{H.escape(title)}</div>'
                    f'<div class="d">{H.escape(summary)}</div></div>'
                    f'<div class="stats">العنوان {len(title)}/60 حرف · الوصف {len(summary)}/160 حرف · {words} كلمة · '
                    f'{len(cx.cited)} من {len(links)} مصدر مستشهد به</div>'
                    f'<div class="lbl" style="color:var(--ink-3);margin-top:12px">نقاط يتحقق منها شخص</div><ul>{unc_html}</ul>'
                    + (f'<div class="lbl" style="color:var(--ink-3);margin-top:12px">مصادر استبعدها النموذج لأنها خارج الموضوع</div>'
                       f'<ul>{"".join(dropped)}</ul>' if dropped else "") + '</div>')
    html.append('<footer>المحتوى من ملفات ومقالات مجتمع ملاك مازدا، والأسعار حسب تاريخها في المصادر. '
                f'<a href="{SITE}/#tab=arts&art={aid}">افتح المقال في الدليل التفاعلي ←</a></footer>')

    seo = ""
    if page_url:
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": title,
              "description": summary, "inLanguage": "ar", "mainEntityOfPage": page_url,
              "isPartOf": {"@type": "WebSite", "name": "دليل مازدا المنظم", "url": SITE + "/"}}
        if modified:
            ld["dateModified"] = modified
        seo = (f'<link rel="canonical" href="{H.escape(page_url)}">'
               f'<meta property="og:type" content="article"><meta property="og:locale" content="ar_SA">'
               f'<meta property="og:title" content="{H.escape(title)}">'
               f'<meta property="og:description" content="{H.escape(summary)}">'
               f'<meta property="og:url" content="{H.escape(page_url)}"><meta name="theme-color" content="#131619">'
               f'<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>')
    return (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{H.escape(title)}</title><meta name="description" content="{H.escape(summary)}">{seo}'
            f'<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'<link rel="stylesheet" href="{FONTS}"><style>{CSS}</style></head>'
            f'<body><main>{"".join(html)}</main><script>{SCRIPT}</script></body></html>'), words, len(cx.cited)


def main():
    crunch, ids = sys.argv[1], sys.argv[2:]
    data = json.load(open(os.path.join(ROOT, "build", "solutions", "data.json"), encoding="utf8"))
    arts = {a["id"]: a for a in data["articles"]}
    for aid in ids:
        links = solutions.article_links(arts[aid])
        page, words, cited = render(f"{crunch}/{aid}/page.md", aid, links, arts)
        open(f"{crunch}/{aid}/page.html", "w", encoding="utf8").write(page)
        print(aid, "words", words, "cited", cited, "of", len(links), "bytes", len(page))


if __name__ == "__main__":
    main()
