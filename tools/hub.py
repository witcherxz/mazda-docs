"""Parse the hub Google Doc (.docx export) into topics, schedule and articles."""
import io, re, zipfile
import xml.etree.ElementTree as ET

from common import (AR_DIGITS, HUB, classify, facets, norm_ar, normalize_url,
                    real_name, slug)

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
SPLIT = re.compile(r"[,،()]")
# ">" and "او" chain alternatives onto the phrase before them: "x>y" and "x او y" are one
# topic with two sources, while a comma starts a new one.
MARKER_ONLY = re.compile(r"^[\s>*«»·،,.\d]+$")
# strip the connectors and stray digits that surround a caption inside a chain
CAPTION_EDGE = re.compile(r"^[\s>‹›«»<=+\\/\-–—*.:؛\d]+|[\s>‹›«»<=+\\/\-–—*.:؛]+$")
CONNECTOR = re.compile(r"^[\s>‹›«»<=+\\/\-–—*.:؛]*(او|أو)?[\s>‹›«»<=+\\/\-–—*.:؛]*$")


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
def extract_topics(tbl, rels, anchors=None):
    """anchors, when given, collects bookmark -> topic so in-document jumps can land
    on the topic itself rather than bouncing out to the source document."""
    topics, letter = [], None
    for tr in tbl.findall(W + "tr"):
        for tc in tr.findall(W + "tc"):
            flat = [t for blk in cell_blocks(tc, rels) for t in blk]
            plain = "".join(t[1] for t in flat).strip()
            if len(plain) <= 4 and not any(t[0] == "L" for t in flat):
                letter = plain                      # section letter: أ ب ت … / A-Z
                continue
            cur, ctx, last, chained, synonym = None, "", None, False, False
            caption = None
            flat_len = len(flat)
            if anchors is not None:
                for p in tc.findall(W + "p"):
                    for b in p.iter(W + "bookmarkStart"):
                        name = b.get(W + "name")
                        if name:
                            anchors.setdefault(name, {"cell": id(tc)})
            for pos, (kind, text, url) in enumerate(flat):
                if kind == "T":
                    ctx = text
                    if SPLIT.search(text):
                        cur = None                  # a comma or bracket closes the group
                        chained = False
                    else:
                        chained = bool(CONNECTOR.match(text))
                        synonym = chained and "=" in text
                    # Plain text carrying markers means one of two things, told apart by
                    # what comes before it. After a separator it is a topic the community
                    # never hyperlinked (الفحص الدوري للمرور>1>2). Mid-chain it is a caption
                    # describing the numbered sources that follow (>شروط وأحكام التأمين>0>1).
                    nxt = flat[pos + 1] if pos + 1 < flat_len else None
                    if nxt and nxt[0] == "L":
                        marker_next = bool(MARKER_ONLY.match(nxt[1] or ""))
                        phrase = CAPTION_EDGE.sub("", SPLIT.split(text)[-1])
                        if real_name(phrase):
                            if cur is not None and not SPLIT.search(text) and marker_next:
                                caption = phrase          # stays inside this topic
                            else:
                                cur = {"id": slug(phrase), "letter": letter, "name": phrase,
                                       "note": ctx.strip(" ,،()>*")[:80], "sources": [],
                                       "syn_chain": False}
                                topics.append(cur)
                                last = cur
                                caption = None
                                synonym = False
                                # whatever follows belongs to this phrase, titled or not
                                chained = True
                    continue
                if cur is None and not real_name(text):
                    if last is not None:            # stray marker -> previous topic
                        last["sources"].append({"label": text.strip() or "↗", "url": url,
                                                "kind": classify(url)})
                    continue
                named = real_name(text)
                if named:
                    caption = None            # a titled source speaks for itself
                if chained and cur is not None:
                    # "تصفية = تفتفه = تذبذب" names one thing three times: keep every spelling
                    # in the name so any of them finds it. Only while the chain has been
                    # nothing but "=" — once a ">" source lands, later "=" belong to it.
                    if synonym and real_name(text) and cur.get("syn_chain"):
                        cur["name"] = f'{cur["name"]} = {text.strip(" >*,،=")}'
                    else:
                        cur["syn_chain"] = False
                    src = {"label": text.strip() or "↗", "url": url, "kind": classify(url)}
                    if caption and not named:
                        src["g"] = caption
                    cur["sources"].append(src)
                    chained = synonym = False
                    continue
                if cur is None or real_name(text):
                    cur = {"id": slug(text), "letter": letter, "name": text.strip(" >*,،"),
                           "note": ctx.strip(" ,،()>*")[:80], "sources": [], "syn_chain": True}
                    topics.append(cur)
                    last = cur
                    if anchors is not None:      # first topic in the cell owns its bookmarks
                        for name, target in anchors.items():
                            if target.get("cell") == id(tc):
                                anchors[name] = {"topic": cur["id"]}
                src = {"label": text.strip() or "↗", "url": url, "kind": classify(url)}
                if caption and not named:
                    src["g"] = caption
                cur["sources"].append(src)

    merged, order = {}, {}
    for t in topics:
        order.setdefault(t["letter"], len(order))
        if not real_name(t["name"]) or not t["sources"]:
            continue
        m = merged.setdefault(t["id"], {**t, "sources": []})
        seen = {s["url"] for s in m["sources"]}
        m["sources"] += [s for s in t["sources"] if s["url"] not in seen]

    out = []
    for t in merged.values():
        blob = t["name"] + " " + t["note"] + " " + " ".join(s["label"] for s in t["sources"])
        t.pop("syn_chain", None)
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

    def ensure_article():
        nonlocal cur
        if cur is None:
            cur = {"id": "intro", "title": "مقدمة الدليل", "blocks": []}
            arts.append(cur)
        return cur

    seen_index = False
    for ch in body:
        if ch.tag == W + "bookmarkStart" and seen_index:
            # Word writes many bookmarks as siblings of the paragraphs, not inside them
            name = ch.get(W + "name")
            if name and name not in anchors:
                anchors[name] = {"a": ensure_article()["id"], "b": len(cur["blocks"])}
            continue
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
    return out, {k: v for k, v in anchors.items() if v.get("a") in live}


def parse(raw):
    """Full hub parse -> dict of topics, schedule, articles, links, text hash input."""
    body, rels = open_docx(raw)
    tbls = body.findall(W + "tbl")
    cell_anchors = {}
    topics = extract_topics(tbls[0], rels, cell_anchors)
    schedule = extract_schedule(tbls[1], rels)
    articles, anchors = extract_articles(body, rels)
    for name, target in cell_anchors.items():     # sections win; index topics fill the rest
        if "topic" in target:
            anchors.setdefault(name, target)

    def resolve(links, key="url"):
        """An in-document jump either lands on a section we extracted, or — for the many
        that point at places outside those sections — on that exact bookmark in the
        community's own document. Left as a bare "#anchor" it would just reload the page."""
        for l in links:
            url = l.get(key, "")
            if not url.startswith("#"):
                continue
            hit = anchors.get(url[1:])
            if hit and ("a" in hit or "topic" in hit):
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
