#!/usr/bin/env python3
"""Build the browsable site from the Mazda hub doc.

Reads the local .docx snapshot (or fetches live), extracts topics, sources,
vehicle facets, the maintenance matrix and the prose sections, then writes
  build/data.json   the dataset
  site/index.html   a single self-contained RTL app (data inlined)
"""
import io, json, os, re, sys, zipfile, hashlib
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sync import (W, R, load, rtext, tokens, classify, is_topic_name, slug, SPLIT, HUB)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# ---------------------------------------------------------------- normalizing
AR_DIAC = re.compile(r"[ً-ْـ]")
def norm_ar(s):
    s = AR_DIAC.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s).replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    return re.sub(r"\s+", " ", s).strip().lower()

# ------------------------------------------------------------------- facets
MODELS = [
    ("mazda3", r"مازدا\s*٣|مازدا\s*3|\bم\s*3\b|\bم٣\b|mazda\s*3|\bm3\b"),
    ("mazda6", r"مازدا\s*٦|مازدا\s*6|\bم\s*6\b|\bم٦\b|mazda\s*6|\bm6\b"),
    ("mazda2", r"مازدا\s*2|\bم\s*2\b|mazda\s*2"),
    ("cx3",  r"\bcx\s*-?\s*3\b"), ("cx5", r"\bcx\s*-?\s*5\b"),
    ("cx9",  r"\bcx\s*-?\s*9\b"), ("cx30", r"\bcx\s*-?\s*30\b"),
    ("cx50", r"\bcx\s*-?\s*50\b"), ("cx60", r"\bcx\s*-?\s*60\b"),
    ("cx70", r"\bcx\s*-?\s*70\b"), ("cx90", r"\bcx\s*-?\s*90\b"),
    ("mx5",  r"\bmx\s*-?\s*5\b"), ("mpv", r"\bmpv\b"),
]
ENGINES = [("1.6", r"\b1[.,]6\b"), ("2.0", r"\b2[.,]0\b"), ("2.5", r"\b2[.,]5\b"),
           ("3.5", r"\b3[.,]5\b"), ("3.7", r"\b3[.,]7\b")]
TRIMS = [("full", r"\bفل\b|فل\s*اوبشن"), ("standard", r"ستاندر"), ("signature", r"سقنتشر|سيقنتشر")]
YEARS = re.compile(r"\b(19[7-9]\d|20[0-4]\d)\s*[-–—]\s*(19[7-9]\d|20[0-4]\d)\b")
YEAR1 = re.compile(r"\b(19[7-9]\d|20[0-4]\d)\b")

def facets(text):
    t = text.lower()
    f = {"models": [], "engines": [], "trims": [], "turbo": None, "years": []}
    for name, pat in MODELS:
        if re.search(pat, t, re.I): f["models"].append(name)
    for name, pat in ENGINES:
        if re.search(pat, t): f["engines"].append(name)
    for name, pat in TRIMS:
        if re.search(pat, t): f["trims"].append(name)
    if re.search(r"بدون\s*(تيربو|توربو)", t): f["turbo"] = "na"
    elif re.search(r"تيربو|توربو", t):        f["turbo"] = "turbo"
    ys = [[int(a), int(b)] for a, b in YEARS.findall(t)]
    if not ys:
        singles = [int(y) for y in YEAR1.findall(t)]
        ys = [[y, y] for y in singles]
    seen, uniq = set(), []
    for y in ys:
        k = tuple(y)
        if k not in seen and 1970 <= y[0] <= 2049 and y[1] >= y[0]:
            seen.add(k); uniq.append(y)
    f["years"] = uniq[:3]
    return f

def year_span(fs):
    ys = [y for f in fs for y in f]
    return [min(y[0] for y in ys), max(y[1] for y in ys)] if ys else None

# ------------------------------------------------------------------ parsing
def parse(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("word/_rels/document.xml.rels"))}
    body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    return body, rels

def cell_blocks(tc, rels):
    return [tokens(p, rels) for p in tc.findall(W + "p")]

LETTERS_RE = re.compile(r"[\u0621-\u064AA-Za-z]")
def real_name(t):
    """A topic name, as opposed to an alternate-source marker (2, >, *, cx9)."""
    s = t.strip(" >*,،()")
    return len(s) >= 4 and len(LETTERS_RE.findall(s)) >= 3


def extract_topics(tbl, rels):
    topics, letter = [], None
    for tr in tbl.findall(W + "tr"):
        for tc in tr.findall(W + "tc"):
            flat = [t for blk in cell_blocks(tc, rels) for t in blk]
            plain = "".join(t[1] for t in flat).strip()
            if len(plain) <= 4 and not any(t[0] == "L" for t in flat):
                letter = plain
                continue
            cur, ctx, last = None, "", None
            for kind, text, url in flat:
                if kind == "T":
                    ctx = text
                    if SPLIT.search(text): cur = None
                    continue
                if cur is None and not real_name(text):
                    if last is not None:            # stray marker -> previous topic
                        last["sources"].append({"label": text.strip() or "↗", "url": url,
                                                "kind": classify(url)})
                    continue
                if cur is None or real_name(text):
                    cur = {"id": slug(text), "letter": letter, "name": text.strip(" >*,،"),
                           "note": ctx.strip(" ,،()>*")[:80], "sources": []}
                    topics.append(cur)
                    last = cur
                cur["sources"].append({"label": text.strip() or "↗", "url": url,
                                       "kind": classify(url)})
    # dedupe by id, merging sources
    merged = {}
    for t in topics:
        if not real_name(t["name"]): continue
        m = merged.setdefault(t["id"], {**t, "sources": []})
        seen = {s["url"] for s in m["sources"]}
        m["sources"] += [s for s in t["sources"] if s["url"] not in seen]
    out = []
    for t in merged.values():
        blob = t["name"] + " " + t["note"] + " " + " ".join(s["label"] for s in t["sources"])
        f = facets(t["name"] + " " + t["note"])
        kinds = sorted({s["kind"] for s in t["sources"]})
        out.append({**t, "norm": norm_ar(t["name"]), "snorm": norm_ar(blob),
                    "f": f, "kinds": kinds, "n": len(t["sources"])})
    order = {}
    for t in topics:
        order.setdefault(t["letter"], len(order))
    return sorted(out, key=lambda t: (order.get(t["letter"], 99), norm_ar(t["name"])))

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
KM = re.compile(r"(\d[\d,]*)\s*(الف|ألف|الاف|آلاف)?\s*(كيلو|كم)?")
def parse_interval(label):
    txt = label.translate(AR_DIGITS)
    km = None
    for m in KM.finditer(txt):
        n, thousands, unit = m.group(1), m.group(2), m.group(3)
        tail = txt[m.end():m.end() + 6]
        if not (thousands or unit) or "ملي" in tail or "مل" == tail.strip()[:2]:
            continue
        v = int(n.replace(",", ""))
        if thousands and v < 1000:
            v *= 1000
        km = v if km is None else max(km, v)   # the row's headline interval
        break
    months = None
    mm = re.search(r"(\d+)\s*(شهر|اشهر|أشهر)|(سنه|سنة|سنوات)|\bشهر\b", txt)
    if mm:
        months = int(mm.group(1)) if mm.group(1) else (12 if mm.group(3) else 1)
    return km, months

def cell_items(tc, rels):
    """One item per paragraph, carrying its own links — matches how the doc is written."""
    items = []
    for blk in cell_blocks(tc, rels):
        text = re.sub(r"[ \t]+", " ", "".join(t[1] for t in blk))
        text = re.sub(r"[\s*]{3,}", " ", text).strip(" ,،*-")
        links = [{"label": t[1].strip() or "↗", "url": t[2], "kind": classify(t[2])}
                 for t in blk if t[0] == "L"]
        if len(text) < 3 and not links:
            continue
        items.append({"t": text, "links": links[:12]})
    return items


def extract_schedule(tbl, rels):
    out = []
    for tr in tbl.findall(W + "tr")[1:]:
        cells = tr.findall(W + "tc")
        if len(cells) != 3:
            continue
        label = re.sub(r"[ \t]+", " ", rtext(cells[0])).strip()
        km, months = parse_interval(label)
        replace, inspect = cell_items(cells[1], rels), cell_items(cells[2], rels)
        out.append({"interval": label, "km": km, "months": months,
                    "replace": replace, "inspect": inspect,
                    "inherits": bool(re.search(r"صيان[هة]\s*\d+", 
                                     " ".join(i["t"] for i in replace)))})
    return out


def extract_articles(body, rels):
    """Everything after the index table, segmented by its oversized headings."""
    arts, cur, anchors = [], None, {}
    seen_index = False
    def size_of(p):
        for rPr in p.iter(W + "rPr"):
            sz = rPr.find(W + "sz")
            if sz is not None:
                try: return int(sz.get(W + "val"))
                except (TypeError, ValueError): pass
        return 22

    def note_bookmarks(node):
        for b in node.iter(W + "bookmarkStart"):
            name = b.get(W + "name")
            if name and name not in anchors and cur is not None:
                anchors[name] = {"a": cur["id"], "b": len(cur["blocks"])}

    def emit(node, is_row=False):
        nonlocal cur
        if cur is None:
            cur = {"id": "intro", "title": "مقدمة الدليل", "blocks": []}
            arts.append(cur)
        note_bookmarks(node)
        toks = tokens(node, rels) if node.tag == W + "p" else \
               [t for p in node.iter(W + "p") for t in tokens(p, rels)]
        text = re.sub(r"[ \t]+", " ", "".join(t[1] for t in toks)).strip()
        links = [{"label": t[1].strip() or "↗", "url": t[2], "kind": classify(t[2])}
                 for t in toks if t[0] == "L"]
        if not text and not links: return
        cur["blocks"].append({"t": text, "row": is_row, "links": links[:24]})

    for ch in body:
        if ch.tag == W + "tbl":
            if not seen_index:
                seen_index = True          # index table itself, handled elsewhere
                continue
            for tr in ch.findall(W + "tr"):
                for tc in tr.findall(W + "tc"):
                    emit(tc, is_row=True)
            continue
        if ch.tag != W + "p" or not seen_index:
            continue
        text = re.sub(r"[ \t]+", " ", rtext(ch)).strip()
        if not text: continue
        sz = size_of(ch)
        if sz >= 34 and len(text) < 95:
            cur = {"id": slug(text), "title": text, "blocks": []}
            arts.append(cur)
            note_bookmarks(ch)
            continue
        if sz >= 29 and len(text) < 120:
            if cur is None:
                cur = {"id": "intro", "title": "مقدمة الدليل", "blocks": []}
                arts.append(cur)
            toks = tokens(ch, rels)
            cur["blocks"].append({"t": text, "row": False, "h": True,
                                  "links": [{"label": t[1].strip() or "↗", "url": t[2],
                                             "kind": classify(t[2])}
                                            for t in toks if t[0] == "L"][:24]})
            continue
        emit(ch)

    for a in arts:
        a.setdefault("blocks", [])
    out, seen = [], {}
    for a in arts:
        if not a["blocks"]: continue
        seen[a["title"]] = seen.get(a["title"], 0) + 1
        if seen[a["title"]] > 1:
            a["title"] = f'{a["title"]} ({seen[a["title"]]})'
            a["id"] = slug(a["title"])
        blob = a["title"] + " " + " ".join(b["t"] for b in a["blocks"])
        a["f"] = facets(blob)
        a["norm"] = norm_ar(blob[:4000])
        a["nlinks"] = sum(len(b["links"]) for b in a["blocks"])
        a["chars"] = sum(len(b["t"]) for b in a["blocks"])
        out.append(a)
    live = {a["id"] for a in out}
    return out, {k: v for k, v in anchors.items() if v["a"] in live}

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    src = os.path.join(ROOT, "دليل صيانة مازدا.docx") if arg in ("", "--live") else arg
    raw = load(HUB if arg == "--live" or not os.path.exists(src) else src)
    body, rels = parse(raw)
    tbls = body.findall(W + "tbl")

    topics = extract_topics(tbls[0], rels)
    schedule = extract_schedule(tbls[1], rels)
    articles, anchors = extract_articles(body, rels)

    def resolve(links):
        for l in links:
            if l["url"].startswith("#"):
                hit = anchors.get(l["url"][1:])
                if hit: l["nav"] = hit
    for t in topics: resolve(t["sources"])
    for iv in schedule:
        for it in iv["replace"] + iv["inspect"]: resolve(it["links"])
    for a in articles:
        for b in a["blocks"]: resolve(b["links"])

    all_links = [{"text": t[1].strip(), "url": t[2], "kind": classify(t[2])}
                 for p in body.iter(W + "p") for t in tokens(p, rels) if t[0] == "L"]
    kinds = {}
    for l in all_links: kinds[l["kind"]] = kinds.get(l["kind"], 0) + 1
    text_only = "".join(rtext(p) for p in body.iter(W + "p"))

    data = {
        "source": "https://docs.google.com/document/d/%s/edit" % HUB,
        "sha": hashlib.sha256(text_only.encode()).hexdigest(),
        "stats": {"topics": len(topics), "sources": sum(t["n"] for t in topics),
                  "links": len(all_links), "articles": len(articles),
                  "intervals": len(schedule), "kinds": kinds},
        "letters": sorted({t["letter"] for t in topics if t["letter"]}),
        "anchors": len(anchors),
        "topics": topics, "schedule": schedule, "articles": articles,
    }
    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    json.dump(data, open(os.path.join(ROOT, "build", "data.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))

    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    html = tpl.replace("/*__DATA__*/null",
                       json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    os.makedirs(os.path.join(ROOT, "site"), exist_ok=True)
    out = os.path.join(ROOT, "site", "index.html")
    open(out, "w", encoding="utf-8").write(html)

    print("topics    ", len(topics))
    print("sources   ", sum(t["n"] for t in topics))
    print("articles  ", len(articles), "blocks",
          sum(len(a["blocks"]) for a in articles))
    print("intervals ", len(schedule))
    print("anchors   ", len(anchors), "internal links resolved to sections")
    print("facets    ", sum(1 for t in topics if t["f"]["models"]), "topics carry a model")
    print("site      ", out, f"{os.path.getsize(out)/1e6:.2f} MB")

if __name__ == "__main__":
    main()
