"""Parse the satellite Google Docs via their `mobilebasic` view.

That view is ~1 MB per doc (vs up to 324 MB for the .docx export), keeps every
hyperlink, and carries real <h1>-<h3> headings — so satellites cost little to
crawl and still yield titles, sections and the same topic/source pattern as the hub.
"""
import html as htmlmod
import re
import urllib.parse
from html.parser import HTMLParser

from common import MOBILE, classify, facets, fetch, norm_ar, real_name, slug

SKIP_TAGS = {"script", "style"}
HEADINGS = {"h1", "h2", "h3", "h4"}


def unwrap(url):
    """Google wraps outbound links as /url?q=REAL&sa=D&… — take the real target."""
    if "google.com/url?" in url:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("q")
        if q:
            return q[0]
    return url


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


def topics_from_blocks(blocks, doc_id, doc_title):
    """Same rule as the hub: a named link is a topic, bare markers are extra sources."""
    topics, section = [], doc_title
    for b in blocks:
        if b["h"]:
            section = b["t"][:90] or section
            continue
        cur, last = None, None
        for l in b["links"]:
            if cur is None and not real_name(l["label"]):
                if last is not None:
                    last["sources"].append(l)
                continue
            if cur is None or real_name(l["label"]):
                cur = {"id": slug(doc_id[:6] + l["label"]), "letter": None,
                       "name": l["label"].strip(" >*,،"), "note": section,
                       "sources": [], "doc": doc_id}
                topics.append(cur)
                last = cur
            cur["sources"].append(l)
    out, seen = [], {}
    for t in topics:
        if not real_name(t["name"]):
            continue
        m = seen.get(t["id"])
        if m:
            urls = {s["url"] for s in m["sources"]}
            m["sources"] += [s for s in t["sources"] if s["url"] not in urls]
            continue
        seen[t["id"]] = t
        out.append(t)
    for t in out:
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
