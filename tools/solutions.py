"""Draft problem-solution pages from the guide's articles.

prepare  writes one input per article: its text with link markers, plus excerpts from
         what its links point at. A model turns each into data/solutions/<id>.json.
check    verifies a draft against its input. Numbers and Latin words must exist in the
         source and no link may be lost. Meaning still needs a human.
review   writes one local page holding every draft, for that human.

Link IDs count the article's linked runs in order, so a draft refers to links without
ever typing a URL. The input's hash goes into the draft: when the source changes, the
hash stops matching and the draft needs redoing.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse

import satellites
from common import MOBILE, ROOT, fetch, norm_ar, real_name

WORK = os.path.join(ROOT, "build", "solutions")
INPUTS = os.path.join(WORK, "in")
OUTPUTS = os.path.join(ROOT, "data", "solutions")

EXCERPT_CHARS = 2500        # per link target
ARTICLE_EXCERPTS = 30000    # per article
TITLE_MAX, SUMMARY_MAX = 60, 160
NOVEL_WARN = 5.0            # percent of draft words not found in the source
DOC_TTL = 7 * 86400

STOP = set("او و في من على علي عن مع الى اذا بعد قبل ان لا ما اثناء فقط".split())
PREFIXES = ("وال", "بال", "فال", "كال", "لل", "ال", "و", "ب", "ف", "ل", "ك")
SUFFIXES = ("ها", "هم", "ه", "ات", "ين", "ون", "ي")
MARKER = re.compile(r"\[L\d+:|\]|\bL\d+\b")


# ------------------------------------------------------------------- inputs
def article_links(article):
    """The linked runs, in the order that defines their IDs (L1 is the first)."""
    return [r for b in article["blocks"] for r in b.get("runs", []) if r.get("u")]


def article_text(article):
    """The article with each link written inline as [L12:label], one block per line."""
    n, lines = 0, []
    for b in article["blocks"]:
        line = ""
        for r in b.get("runs", []):
            if r.get("u"):
                n += 1
                line += f"[L{n}:{r['t'].strip()}]"
            else:
                line += r.get("t", "")
        if line.strip():
            lines.append(line.strip())
    return "\n".join(lines), n


def terms(s):
    return {w for w in re.findall(r"[\wء-ي]+", norm_ar(s)) if w not in STOP and len(w) > 1}


def locate(label, url, blocks):
    """Find where a link lands in a document: its exact anchor when it has one, otherwise
    the short line that best matches its label. Documents open with an A-Z index holding
    the same names, so among equal matches prefer the one with the most text after it."""
    frag = url.split("#", 1)[1].split("=")[-1] if "#" in url else ""
    if frag:
        for i, b in enumerate(blocks):
            if frag in b.get("ids", []):
                return 1.0, i
    wanted, best = terms(label), None
    if not wanted:
        return 0, None
    for i, b in enumerate(blocks):
        if not b["t"] or len(b["t"]) > 110:
            continue
        score = len(wanted & terms(b["t"])) / len(wanted)
        if score < 0.5:
            continue
        rank = (round(score, 1), sum(len(x["t"]) for x in blocks[i + 1:i + 3]), -i)
        if best is None or rank > best:
            best = rank
    return (best[0], -best[2]) if best else (0, None)


def excerpt_from(texts):
    out, used = [], 0
    for t in texts:
        t = re.sub(r"\s+", " ", t).strip()
        if not t:
            continue
        if used + len(t) > EXCERPT_CHARS:
            break
        out.append(t)
        used += len(t)
    return " | ".join(out)


def load_doc(doc_id):
    raw = fetch(MOBILE.format(doc_id), ttl=DOC_TTL)
    p = satellites.DocParser()
    p.feed(raw.decode("utf-8", "replace"))
    p._close()
    return p.blocks


def block_text(b):
    return " ".join(r.get("t", "") for r in b.get("runs", []))


def excerpts_for(article, known_docs, articles, load=load_doc):
    """One excerpt per distinct link target, strongest matches first, within a budget."""
    targets, docs = {}, {}
    for n, r in enumerate(article_links(article), 1):
        if not real_name(r["t"]):
            continue
        nav = r.get("nav")
        if nav and nav.get("a") in articles and nav["a"] != article["id"]:
            key, score = ("article", nav["a"], nav.get("b", 0)), 1.0
            texts = [block_text(b) for b in articles[nav["a"]]["blocks"][nav.get("b", 0):]]
        else:
            m = re.search(r"/document/d/([\w-]+)", r["u"])
            if not m or m.group(1) not in known_docs:
                continue
            doc = m.group(1)
            if doc not in docs:
                try:
                    docs[doc] = load(doc)
                except Exception as e:                  # noqa: BLE001 - one doc is optional
                    print(f"  skipped document {doc[:10]}: {e}", file=sys.stderr)
                    docs[doc] = []
            score, i = locate(r["t"], r["u"], docs[doc])
            if i is None:
                continue
            key, texts = ("doc", doc, i), [b["t"] for b in docs[doc][i:]]
        entry = targets.setdefault(key, {"ids": [], "score": score, "first": n,
                                         "label": r["t"].strip(), "texts": texts})
        entry["ids"].append(n)
    chosen, used = [], 0
    for e in sorted(targets.values(), key=lambda e: (-e["score"], e["first"])):
        body = excerpt_from(e["texts"])
        if not body or used + len(body) > ARTICLE_EXCERPTS:
            continue
        used += len(body)
        chosen.append(e | {"body": body})
    return sorted(chosen, key=lambda e: e["first"])


def input_for(article, known_docs, articles, load=load_doc):
    body, count = article_text(article)
    text = (f"ARTICLE_ID: {article['id']}\nTITLE: {article['title']}\nLINK_COUNT: {count}\n"
            f"---\n{body}\n")
    found = excerpts_for(article, known_docs, articles, load)
    if found:
        text += "\n=== EXCERPTS FROM LINKED DOCUMENTS ===\n" + "\n\n".join(
            f"EXCERPT for {', '.join('L%d' % i for i in e['ids'])} ({e['label']}):\n{e['body']}"
            for e in found) + "\n"
    return text


def prepare(data):
    os.makedirs(INPUTS, exist_ok=True)
    known = {d["id"] for d in data["docs"]}
    articles = {a["id"]: a for a in data["articles"]}
    for a in data["articles"]:
        text = input_for(a, known, articles)
        open(os.path.join(INPUTS, a["id"] + ".txt"), "w", encoding="utf-8").write(text)
        print(f"  {a['id']:14s} {len(article_links(a)):4d} links {len(text):6d} chars  {a['title']}")


# ------------------------------------------------------------------- checks
def input_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def stems(word):
    out = {word}
    for p in PREFIXES:
        if word.startswith(p) and len(word) - len(p) >= 3:
            out.add(word[len(p):])
    for x in list(out):
        for s in SUFFIXES:
            if x.endswith(s) and len(x) - len(s) >= 3:
                out.add(x[:-len(s)])
    return out


def arabic_words(s):
    return re.findall(r"[ء-ي]{3,}", norm_ar(s))


def numbers(s):
    return set(re.findall(r"\d+", norm_ar(s)))


def latin(s):
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]+", s)}


def draft_links(draft):
    used = [n for c in draft.get("cases", []) for i in c.get("items", []) for n in i.get("links", [])]
    return used + [n for p in draft.get("parts", []) for n in p.get("links", [])]


def draft_text(draft):
    """Every string a reader will see, so each one gets checked against the source."""
    bits = [draft.get("title", ""), draft.get("summary", "")]
    for c in draft.get("cases", []):
        bits.append(c.get("h", ""))
        bits += [i.get("t", "") for i in c.get("items", [])]
    for p in draft.get("parts", []):
        bits += [p.get("part", ""), p.get("fits", "")] + p.get("numbers", [])
        for price in p.get("prices", []):
            bits += [str(price.get(k, "")) for k in ("value", "where", "date", "note")]
    return " ".join(bits)


def check(draft, source):
    """Return (errors, warnings). Errors block a draft; warnings point a reviewer at it."""
    header, _, rest = source.partition("---\n")
    aid = re.search(r"ARTICLE_ID: (\S+)", header).group(1)
    count = int(re.search(r"LINK_COUNT: (\d+)", header).group(1))
    src = MARKER.sub(" ", rest)
    errors, warnings = [], []

    if draft.get("article") != aid:
        errors.append(f"article is {draft.get('article')!r}, expected {aid!r}")
    if not draft.get("cases"):
        errors.append("no cases")
    if not draft.get("title") or len(draft["title"]) > TITLE_MAX:
        errors.append(f"title length {len(draft.get('title') or '')}, limit {TITLE_MAX}")
    if not draft.get("summary") or len(draft["summary"]) > SUMMARY_MAX:
        errors.append(f"summary length {len(draft.get('summary') or '')}, limit {SUMMARY_MAX}")

    used, unplaced = draft_links(draft), draft.get("unplaced", [])
    unknown = sorted({n for n in used + unplaced if not 1 <= n <= count})
    missing = sorted(set(range(1, count + 1)) - set(used) - set(unplaced))
    if unknown:
        errors.append(f"unknown link IDs: {unknown[:20]}")
    if missing:
        errors.append(f"links dropped ({len(missing)}): {missing[:20]}")

    text = draft_text(draft)
    new = sorted(numbers(text) - numbers(src), key=lambda x: (len(x), x))
    if new:
        errors.append(f"numbers not in source: {new[:20]}")
    joined = re.sub(r"\s+", "", src).lower()
    alien = sorted(w for w in latin(text) if w not in joined)
    if alien:
        errors.append(f"Latin words not in source: {alien[:20]}")

    seen = set()
    for w in arabic_words(src):
        seen |= stems(w)
    body = [w for w in arabic_words(text) if w not in STOP]
    novel = sorted({w for w in body if not stems(w) & seen})
    rate = 100 * sum(1 for w in body if not stems(w) & seen) / max(1, len(body))
    if rate > NOVEL_WARN:
        warnings.append(f"{rate:.1f}% of words not in source: {novel[:15]}")
    if unplaced:
        warnings.append(f"{len(unplaced)} links unplaced")
    if draft.get("unclear"):
        warnings.append(f"{len(draft['unclear'])} lines marked unclear")
    thin = [i["t"] for c in draft.get("cases", []) for i in c.get("items", [])
            if len(i.get("t", "").split()) < 2]
    if thin:
        warnings.append(f"{len(thin)} one-word items: {thin[:6]}")
    return errors, warnings


def read_input(aid):
    return open(os.path.join(INPUTS, aid + ".txt"), encoding="utf-8").read()


def draft_path(aid):
    return os.path.join(OUTPUTS, aid + ".json")


def run_check(ids, stamp=None):
    """Print a line per draft. With stamp, record the model and source hash on passing drafts."""
    failed = 0
    for aid in ids:
        if not os.path.exists(draft_path(aid)):
            print(f"MISSING {aid}")
            failed += 1
            continue
        try:
            raw = open(draft_path(aid), encoding="utf-8").read()
            draft = json.loads(raw)
        except ValueError as e:
            print(f"FAIL {aid}: invalid JSON: {e}")
            failed += 1
            continue
        source = read_input(aid)
        errors, warnings = check(draft, source)
        print(f"{'FAIL' if errors else 'ok  '} {aid}: {draft.get('title')}")
        for e in errors:
            print(f"     error: {e}")
        for w in warnings:
            print(f"     warn:  {w}")
        failed += bool(errors)
        if stamp and not errors:
            draft.update(source_hash=input_hash(source), model=stamp)
            open(draft_path(aid), "w", encoding="utf-8").write(
                json.dumps(draft, ensure_ascii=False, indent=1) + "\n")
    print(f"{len(ids) - failed} of {len(ids)} passed")
    return failed


# ------------------------------------------------------------------- review
REVIEW_CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#1c1f22;--dim:#5d6570;--line:#d8dce0;--acc:#0b6bcb;
  --warn:#a15c00;--ok:#0a7a4a;--card:#f6f7f8}
@media (prefers-color-scheme:dark){:root{--bg:#131619;--fg:#e9e7e2;--dim:#a2a9b2;--line:#2c3238;
  --acc:#8dbbd2;--warn:#e6b35a;--ok:#5fc592;--card:#1a1e22}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.65 "IBM Plex Sans Arabic",system-ui,sans-serif}
main{max-width:820px;margin:0 auto;padding:24px 16px 80px}
a{color:var(--acc)}
h1{font-size:24px;line-height:1.35;margin:0 0 8px}
h2{font-size:22px;line-height:1.35;margin:0 0 4px}
h3{font-size:16px;margin:20px 0 6px}
nav ol{padding-inline-start:22px}
section{border-top:1px solid var(--line);margin-top:36px;padding-top:24px}
.src{font-size:13px;color:var(--dim);margin:0 0 12px}
.answer{border:1px solid var(--ok);border-radius:8px;padding:10px 12px;margin:0 0 14px}
.answer b{display:block;font-size:13px;color:var(--ok)}
.flag{border:1px solid var(--warn);border-radius:8px;padding:8px 12px;margin:0 0 14px;font-size:14px}
.flag b{color:var(--warn)}
ul{margin:0 0 8px;padding-inline-start:20px}
li{margin-bottom:4px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:3px 0 6px}
.chip{font-size:12px;border:1px solid var(--line);border-radius:5px;padding:1px 7px;text-decoration:none;overflow-wrap:anywhere}
.tw{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:right;vertical-align:top}
th{color:var(--dim);font-weight:600}
bdi{font-family:ui-monospace,monospace;font-size:12px}
"""


def link_label(run):
    t = run["t"].strip()
    if real_name(t):
        return t
    host = urllib.parse.urlparse(run["u"]).netloc.replace("www.", "")
    return host or "مصدر"


def chips(ids, links):
    out = ""
    for n in ids:
        run = links[n - 1] if 1 <= n <= len(links) else None
        if not run or run["u"].startswith("#"):
            continue
        out += (f'<a class="chip" href="{html.escape(run["u"])}" rel="noopener">'
                f'{html.escape(link_label(run))}</a>')
    return f'<div class="chips">{out}</div>' if out else ""


def review_section(article, draft):
    e = html.escape
    links = article_links(article)
    out = [f'<section id="{e(article["id"])}"><h2>{e(draft["title"])}</h2>'
           f'<p class="src">العنوان في المصدر: {e(article["title"])} · {len(links)} رابط</p>'
           f'<div class="answer"><b>الخلاصة</b>{e(draft["summary"])}</div>']
    if draft.get("unclear"):
        out.append('<div class="flag"><b>يحتاج مراجعة (غير واضح في المصدر):</b><ul>'
                   + "".join(f"<li>{e(u)}</li>" for u in draft["unclear"]) + "</ul></div>")
    for c in draft["cases"]:
        out.append(f'<h3>{e(c["h"])}</h3><ul>')
        for i in c["items"]:
            out.append(f'<li>{e(i["t"])}{chips(i.get("links", []), links)}</li>')
        out.append("</ul>")
    if draft.get("parts"):
        out.append('<h3>القطع والأسعار</h3><div class="tw"><table><tr><th>القطعة</th><th>يناسب</th>'
                   "<th>الرقم</th><th>السعر</th><th>المصدر</th></tr>")
        for p in draft["parts"]:
            nums = " ".join(f"<bdi>{e(n)}</bdi>" for n in p.get("numbers", []))
            prices = "<br>".join(
                e(" · ".join(str(x[k]) for k in ("value", "where", "date", "note") if x.get(k)))
                for x in p.get("prices", []))
            out.append(f'<tr><td>{e(p.get("part", ""))}</td><td>{e(p.get("fits", ""))}</td>'
                       f'<td>{nums}</td><td>{prices}</td><td>{chips(p.get("links", []), links)}</td></tr>')
        out.append("</table></div>")
    extra = chips(draft.get("unplaced", []), links)
    if extra:
        out.append(f"<h3>روابط لم توضع في مكانها</h3>{extra}")
    out.append("</section>")
    return "".join(out)


def review(data, path=os.path.join(WORK, "review.html")):
    sections, index = [], []
    for a in data["articles"]:
        if not os.path.exists(draft_path(a["id"])):
            continue
        draft = json.load(open(draft_path(a["id"]), encoding="utf-8"))
        sections.append(review_section(a, draft))
        index.append(f'<li><a href="#{html.escape(a["id"])}">{html.escape(draft["title"])}</a></li>')
    page = (f'<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>مراجعة المسودات</title><style>{REVIEW_CSS}</style></head><body><main>"
            f"<h1>مراجعة المسودات: {len(sections)} صفحة</h1>"
            f"<p class=\"src\">مسودات آلية من مستندات المجتمع. لم تُنشر، وتحتاج مراجعة قبل النشر.</p>"
            f"<nav><ol>{''.join(index)}</ol></nav>{''.join(sections)}</main></body></html>")
    open(path, "w", encoding="utf-8").write(page)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("command", choices=["prepare", "check", "review"])
    ap.add_argument("ids", nargs="*", help="article IDs (default: all)")
    ap.add_argument("--data", default=os.path.join(WORK, "data.json"), help="the site's data.json")
    ap.add_argument("--stamp", metavar="MODEL", help="check: record model and source hash on passes")
    args = ap.parse_args()
    data = json.load(open(args.data, encoding="utf-8"))
    if args.command == "prepare":
        prepare(data)
    elif args.command == "check":
        sys.exit(1 if run_check(args.ids or [a["id"] for a in data["articles"]], args.stamp) else 0)
    else:
        print(review(data))


if __name__ == "__main__":
    main()
