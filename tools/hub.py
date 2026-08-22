"""Parse the hub Google Doc (.docx export) into topics, schedule and articles."""
import io, re, zipfile
import xml.etree.ElementTree as ET

from common import (AR_DIGITS, HUB, classify, facets, norm_ar, normalize_url,
                    real_name, slug)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
SPLIT = re.compile(r"[,،()]")


def rtext(el):
    return "".join(n.text or "" for n in el.iter() if n.tag == W + "t")


def tokens(p, rels):
    """Paragraph -> [('T',text,None) | ('L',text,url)], merging runs of one anchor.

    Google Docs splits a single hyperlink into several w:hyperlink elements whenever
    formatting changes mid-link; merging them is what makes topic names come out whole.
    """
    out = []
    for ch in p:
        if ch.tag == W + "hyperlink":
            url = normalize_url(rels.get(ch.get(R + "id"),
                                         "#" + (ch.get(W + "anchor") or "")))
            if out and out[-1][0] == "L" and out[-1][2] == url:
                out[-1] = ("L", out[-1][1] + rtext(ch), url)
            else:
                out.append(("L", rtext(ch), url))
        elif ch.tag == W + "r":
            t = rtext(ch)
            if not t:
                continue
            if out and out[-1][0] == "T":
                out[-1] = ("T", out[-1][1] + t, None)
            else:
                out.append(("T", t, None))
    return out


def open_docx(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("word/_rels/document.xml.rels"))}
    body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    return body, rels


def cell_blocks(tc, rels):
    return [tokens(p, rels) for p in tc.findall(W + "p")]


# --------------------------------------------------------------- index table
def extract_topics(tbl, rels):
    topics, letter = [], None
    for tr in tbl.findall(W + "tr"):
        for tc in tr.findall(W + "tc"):
            flat = [t for blk in cell_blocks(tc, rels) for t in blk]
            plain = "".join(t[1] for t in flat).strip()
            if len(plain) <= 4 and not any(t[0] == "L" for t in flat):
                letter = plain                      # section letter: أ ب ت … / A-Z
                continue
            cur, ctx, last = None, "", None
            for kind, text, url in flat:
                if kind == "T":
                    ctx = text
                    if SPLIT.search(text):
                        cur = None                  # separator closes the group
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

    merged, order = {}, {}
    for t in topics:
        order.setdefault(t["letter"], len(order))
        if not real_name(t["name"]):
            continue
        m = merged.setdefault(t["id"], {**t, "sources": []})
        seen = {s["url"] for s in m["sources"]}
        m["sources"] += [s for s in t["sources"] if s["url"] not in seen]

    out = []
    for t in merged.values():
        blob = t["name"] + " " + t["note"] + " " + " ".join(s["label"] for s in t["sources"])
        out.append({**t, "norm": norm_ar(t["name"]), "snorm": norm_ar(blob),
                    "f": facets(t["name"] + " " + t["note"]),
                    "kinds": sorted({s["kind"] for s in t["sources"]}),
                    "n": len(t["sources"]), "doc": "hub"})
    return sorted(out, key=lambda t: (order.get(t["letter"], 99), t["norm"]))


# ---------------------------------------------------------- maintenance table
KM = re.compile(r"(\d[\d,]*)\s*(الف|ألف|الاف|آلاف)?\s*(كيلو|كم)?")

def parse_interval(label):
    txt = (label or "").translate(AR_DIGITS)
    km = None
    for m in KM.finditer(txt):
        n, thousands, unit = m.group(1), m.group(2), m.group(3)
        tail = txt[m.end():m.end() + 6]
        if not (thousands or unit) or "ملي" in tail:
            continue
        v = int(n.replace(",", ""))
        if thousands and v < 1000:
            v *= 1000
        km = v
        break
    months = None
    mm = re.search(r"(\d+)\s*(شهر|اشهر|أشهر)|(سنه|سنة|سنوات)|\bشهر\b", txt)
    if mm:
        months = int(mm.group(1)) if mm.group(1) else (12 if mm.group(3) else 1)
    return km, months


def as_runs(blk):
    """Keep text and links interleaved in reading order.

    Most of this document is prose whose key phrases *are* the links, so flattening a
    paragraph into text plus a separate link list prints every phrase twice."""
    runs = []
    for kind, text, url in blk:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"[\s*]{3,}", " ", text)
        if kind == "L":
            runs.append({"t": text.strip() or "↗", "u": url, "k": classify(url)})
        elif text.strip():
            if runs and "u" not in runs[-1]:
                runs[-1]["t"] += text
            else:
                runs.append({"t": text})
    return runs


def runs_text(runs):
    return re.sub(r"\s+", " ", " ".join(r["t"] for r in runs)).strip(" ,،*-")


def cell_items(tc, rels):
    """One item per paragraph, carrying its own links — matches how the doc is written."""
    items = []
    for blk in cell_blocks(tc, rels):
        runs = as_runs(blk)
        text = runs_text(runs)
        if len(text) < 3 and not any("u" in r for r in runs):
            continue
        items.append({"t": text, "runs": runs})
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


# ------------------------------------------------------------------ articles
def extract_articles(body, rels):
    """Everything after the index table, segmented by its oversized headings."""
    arts, cur, anchors = [], None, {}

    def size_of(p):
        for rPr in p.iter(W + "rPr"):
            sz = rPr.find(W + "sz")
            if sz is not None:
                try:
                    return int(sz.get(W + "val"))
                except (TypeError, ValueError):
                    pass
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
        runs = as_runs(toks)
        text = runs_text(runs)
        if not runs:
            return
        cur["blocks"].append({"t": text, "row": is_row, "runs": runs})

    seen_index = False
    for ch in body:
        if ch.tag == W + "tbl":
            if not seen_index:
                seen_index = True                  # the index table itself
                continue
            for tr in ch.findall(W + "tr"):
                for tc in tr.findall(W + "tc"):
                    emit(tc, is_row=True)
            continue
        if ch.tag != W + "p" or not seen_index:
            continue
        text = re.sub(r"[ \t]+", " ", rtext(ch)).strip()
        if not text:
            continue
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
            cur["blocks"].append({"t": text, "row": False, "h": True,
                                  "runs": as_runs(tokens(ch, rels))})
            continue
        emit(ch)

    out, seen = [], {}
    for a in arts:
        if not a["blocks"]:
            continue
        seen[a["title"]] = seen.get(a["title"], 0) + 1
        if seen[a["title"]] > 1:
            a["title"] = f'{a["title"]} ({seen[a["title"]]})'
            a["id"] = slug(a["title"])
        blob = a["title"] + " " + " ".join(b["t"] for b in a["blocks"])
        a["f"] = facets(blob)
        a["norm"] = norm_ar(blob[:6000])
        a["nlinks"] = sum(1 for b in a["blocks"] for r in b["runs"] if "u" in r)
        a["chars"] = sum(len(b["t"]) for b in a["blocks"])
        out.append(a)
    live = {a["id"] for a in out}
    return out, {k: v for k, v in anchors.items() if v["a"] in live}


def parse(raw):
    """Full hub parse -> dict of topics, schedule, articles, links, text hash input."""
    body, rels = open_docx(raw)
    tbls = body.findall(W + "tbl")
    topics = extract_topics(tbls[0], rels)
    schedule = extract_schedule(tbls[1], rels)
    articles, anchors = extract_articles(body, rels)

    def resolve(links, key="url"):
        """An in-document jump either lands on a section we extracted, or — for the many
        that point at places outside those sections — on that exact bookmark in the
        community's own document. Left as a bare "#anchor" it would just reload the page."""
        for l in links:
            url = l.get(key, "")
            if not url.startswith("#"):
                continue
            hit = anchors.get(url[1:])
            if hit:
                l["nav"] = hit
            else:
                l[key] = f"https://docs.google.com/document/d/{HUB}/edit#bookmark={url[1:]}"
                l["kind"] = "source-doc"
    for t in topics:
        resolve(t["sources"])
    for iv in schedule:
        for it in iv["replace"] + iv["inspect"]:
            resolve(it["runs"], key="u")
    for a in articles:
        for b in a["blocks"]:
            resolve(b["runs"], key="u")

    all_links = [{"text": t[1].strip(), "url": t[2], "kind": classify(t[2])}
                 for p in body.iter(W + "p") for t in tokens(p, rels) if t[0] == "L"]
    resolve(all_links)          # so link counts describe where a reader actually lands
    text = "".join(rtext(p) for p in body.iter(W + "p"))
    return {"topics": topics, "schedule": schedule, "articles": articles,
            "anchors": anchors, "links": all_links, "text": text}
