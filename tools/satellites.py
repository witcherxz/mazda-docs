"""Parse the satellite Google Docs via their `mobilebasic` view.

That view is ~1 MB per doc (vs up to 324 MB for the .docx export), keeps every
hyperlink, and carries real <h1>-<h3> headings — so satellites cost little to
crawl and still yield titles, sections and the same topic/source pattern as the hub.
"""
import html as htmlmod
import re
import urllib.parse
from html.parser import HTMLParser

from common import MOBILE, classify, facets, fetch, norm_ar, normalize_url, real_name, slug

SKIP_TAGS = {"script", "style"}
HEADINGS = {"h1", "h2", "h3", "h4"}


def unwrap(url):
    """Google wraps outbound links as /url?q=REAL&sa=D&… — take the real target."""
    if "google.com/url?" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q")
        if q:
            return normalize_url(q[0])
    return normalize_url(url)


class DocParser(HTMLParser):
    """Flatten the document into blocks: headings, paragraphs, and their links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.blocks = []                 # {"h": level|0, "t": text, "links": [...]}
        self._skip = 0
        self._in_title = False
        self._cur = None
        self._a = None
        self._ids = []                   # ids seen inside the current block

    # -- helpers
    def _open(self, level=0):
        self._close()
        self._cur = {"h": level, "t": "", "links": [], "ids": []}

    def _close(self):
        if self._cur and (self._cur["t"].strip() or self._cur["links"]):
            self._cur["t"] = re.sub(r"[ \t]+", " ", self._cur["t"]).strip()
            self.blocks.append(self._cur)
        self._cur = None

    # -- HTMLParser API
    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in HEADINGS:
            self._open(int(tag[1]))
            if at.get("id"):
                self._cur["ids"].append(at["id"])
        elif tag in ("p", "li", "td"):
            self._open(0)
            if at.get("id"):
                self._cur["ids"].append(at["id"])
        elif tag == "a":
            if self._cur is None:
                self._open(0)
            if at.get("id"):
                self._cur["ids"].append(at["id"])
            href = at.get("href")
            if href:
                self._a = {"label": "", "url": unwrap(htmlmod.unescape(href))}
        elif tag in ("span", "h5", "h6") and at.get("id") and self._cur is not None:
            self._cur["ids"].append(at["id"])

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._a:
            label = re.sub(r"\s+", " ", self._a["label"]).strip()
            url = self._a["url"]
            if url and self._cur is not None:
                prev = self._cur["links"][-1] if self._cur["links"] else None
                if prev and prev["url"] == url:      # merge split anchors, as in the hub
                    prev["label"] = (prev["label"] + label).strip()
                else:
                    self._cur["links"].append({"label": label, "url": url,
                                               "kind": classify(url)})
            self._a = None
        elif tag in HEADINGS or tag in ("p", "li", "td"):
            self._close()

    def handle_data(self, data):
        if self._skip:
            return
        if self._in_title:
            self.title += data
            return
        if self._cur is None:
            self._open(0)
        self._cur["t"] += data
        if self._a is not None:
            self._a["label"] += data


PRICE_OR_DATE = re.compile(r"(ريال|رس\b|بتاريخ|\d{1,2}[\\/]\d{2,4})")

def strong_name(label):
    """Satellite docs link mid-sentence, so their anchor text is often a price, a date
    or a fragment. Only well-formed multi-word labels become topics of their own."""
    s = (label or "").strip(" >*,،()")
    if len(s) < 8 or PRICE_OR_DATE.search(s):
        return False
    if s[0].isdigit():
        return False
    words = [w for w in s.split() if len(w) > 1]
    return len(words) >= 2 and len(re.findall(r"[ء-يA-Za-z]", s)) >= 6


def topics_from_blocks(blocks, doc_id, doc_title):
    """Headings carry this document's real structure, so they become the topics and the
    links under them become their sources; a strongly-named link also earns its own entry."""
    topics, section = [], None

    def new_topic(name, note, key):
        t = {"id": slug(doc_id[:6] + key), "letter": None, "name": name.strip(" >*,،"),
             "note": note or doc_title, "sources": [], "doc": doc_id}
        topics.append(t)
        return t

    for b in blocks:
        if b["h"]:
            title = b["t"][:90]
            if title:
                section = new_topic(title, doc_title, "h:" + title)
                section["sources"].extend(b["links"])
            continue
        for l in b["links"]:
            if section is not None:
                section["sources"].append(l)
            if strong_name(l["label"]):
                t = new_topic(l["label"], section["name"] if section else doc_title,
                              "l:" + l["label"])
                t["sources"].append(l)

    out, seen = [], {}
    for t in topics:
        if not real_name(t["name"]) or not t["sources"]:
            continue
        prev = seen.get(t["id"])
        if prev:
            urls = {s["url"] for s in prev["sources"]}
            prev["sources"] += [s for s in t["sources"] if s["url"] not in urls]
            continue
        seen[t["id"]] = t
        out.append(t)
    for t in out:
        urls, uniq = set(), []
        for s in t["sources"]:                      # keep source order, drop repeats
            if s["url"] not in urls:
                urls.add(s["url"]); uniq.append(s)
        t["sources"] = uniq[:40]
        blob = t["name"] + " " + t["note"] + " " + " ".join(s["label"] for s in t["sources"])
        t.update(norm=norm_ar(t["name"]), snorm=norm_ar(blob),
                 f=facets(t["name"] + " " + t["note"]),
                 kinds=sorted({s["kind"] for s in t["sources"]}), n=len(t["sources"]))
    return out


def parse(html_text, doc_id):
    p = DocParser()
    p.feed(html_text)
    p._close()
    title = re.sub(r"\s+", " ", p.title).strip() or doc_id[:8]
    sections = [{"level": b["h"], "title": b["t"][:120]} for b in p.blocks if b["h"]]
    links = [l for b in p.blocks for l in b["links"]]
    topics = topics_from_blocks(p.blocks, doc_id, title)
    text = " ".join(b["t"] for b in p.blocks)
    return {"id": doc_id, "title": title, "sections": sections, "topics": topics,
            "links": links, "chars": len(text), "text": text,
            "f": facets(title + " " + " ".join(s["title"] for s in sections[:40]))}


def crawl(doc_ids, ttl=0, log=print):
    """Fetch and parse each satellite. Failures are reported, never fatal."""
    docs, errors = [], []
    for i, gid in enumerate(doc_ids, 1):
        try:
            raw = fetch(MOBILE.format(gid), ttl=ttl, timeout=180)
            doc = parse(raw.decode("utf-8", "replace"), gid)
            doc["bytes"] = len(raw)
            docs.append(doc)
            log(f"  [{i}/{len(doc_ids)}] {doc['title'][:44]:<46} "
                f"{len(doc['topics']):4d} topics  {len(doc['links']):5d} links")
        except Exception as e:                      # noqa: BLE001 - keep crawling
            errors.append({"id": gid, "error": str(e)})
            log(f"  [{i}/{len(doc_ids)}] {gid[:12]} FAILED: {e}")
    return docs, errors
