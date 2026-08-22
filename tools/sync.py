#!/usr/bin/env python3
"""Mazda community doc -> structured JSON.

Fetches (or reads) the hub Google Doc as .docx, parses OOXML directly
(stdlib only) and emits:
  build/topics.json       index topics + their ranked sources
  build/maintenance.json  the interval matrix (interval | replace | inspect)
  build/links.json        every link with classification (link-rot input)
  build/snapshot.sha      content hash for change detection
"""
import hashlib, io, json, os, re, sys, urllib.request, zipfile
import xml.etree.ElementTree as ET

HUB = "1Yj0AP9xVrkLqIf01mdelU4m4OcQR-NGxuTNYpGeiIvM"
EXPORT = "https://docs.google.com/document/d/{}/export?format=docx"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
OUT = os.path.join(os.path.dirname(__file__), "..", "build")

ORD_ONLY = re.compile(r"[\s>*\d.،,«»\-–—:؛]*")      # "2", ">", "*" = another source, same topic
SPLIT    = re.compile(r"[,،()]")                      # topic-group separators


def load(path_or_id):
    if os.path.exists(path_or_id):
        return open(path_or_id, "rb").read()
    return urllib.request.urlopen(EXPORT.format(path_or_id), timeout=300).read()


def rtext(el):
    return "".join(n.text or "" for n in el.iter() if n.tag == W + "t")


def tokens(p, rels):
    """Paragraph -> [('T',text) | ('L',text,url)], merging runs of one anchor."""
    out = []
    for ch in p:
        if ch.tag == W + "hyperlink":
            url = rels.get(ch.get(R + "id"), "#" + (ch.get(W + "anchor") or ""))
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


def classify(url):
    table = [("t.me", "telegram"), ("youtu", "youtube"), ("docs.google.com", "google-doc"),
             ("drive.google", "gdrive"), ("web.archive.org", "archive"), ("goo.gl", "shortlink"),
             ("ibb.co", "image"), ("maps.app", "maps"), ("nhtsa", "nhtsa"),
             ("instagram", "instagram"), ("twitter", "twitter"), ("x.com", "twitter")]
    if url.startswith("#") or "kix." in url:
        return "internal-anchor"
    for key, name in table:
        if key in url:
            return name
    return "web"


def is_topic_name(t):
    s = t.strip()
    return len(s) > 3 and not ORD_ONLY.fullmatch(s)


def slug(name):
    return hashlib.sha1(re.sub(r"\s+", " ", name).strip().encode()).hexdigest()[:12]


def main():
    raw = load(sys.argv[1] if len(sys.argv) > 1 else HUB)
    z = zipfile.ZipFile(io.BytesIO(raw))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("word/_rels/document.xml.rels"))}
    body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    tbls = body.findall(W + "tbl")

    # ---- index table: letter -> topics -> ranked sources -------------------
    topics, links, letter = [], [], None
    for tr in tbls[0].findall(W + "tr"):
        for tc in tr.findall(W + "tc"):
            flat = [t for p in tc.findall(W + "p") for t in tokens(p, rels)]
            plain = "".join(t[1] for t in flat).strip()
            if len(plain) <= 4 and not any(t[0] == "L" for t in flat):
                letter = plain                      # section letter (أ ب ت ... / A-Z)
                continue
            cur = None
            for kind, text, url in flat:
                if kind == "T":
                    if SPLIT.search(text):
                        cur = None                  # separator closes the group
                    continue
                if cur is None or is_topic_name(text):
                    cur = {"id": slug(text), "letter": letter,
                           "name": text.strip(" >*,،"), "sources": []}
                    topics.append(cur)
                cur["sources"].append({"label": text.strip(), "url": url,
                                       "kind": classify(url)})

    # ---- maintenance matrix ------------------------------------------------
    sched = []
    rows = tbls[1].findall(W + "tr")
    for tr in rows[1:]:
        cells = tr.findall(W + "tc")
        if len(cells) != 3:
            continue
        col = [re.sub(r"[ \t]+", " ", rtext(c)).strip() for c in cells]
        sched.append({"interval": col[0], "replace_clean": col[1], "inspect": col[2],
                      "inherits": bool(re.search(r"صيانة\s*\d+", col[1]))})

    # ---- every link in the document ---------------------------------------
    for p in body.iter(W + "p"):
        for kind, text, url in tokens(p, rels):
            if kind == "L":
                links.append({"text": text.strip(), "url": url, "kind": classify(url)})

    os.makedirs(OUT, exist_ok=True)
    text_only = "".join(rtext(p) for p in body.iter(W + "p"))
    digest = hashlib.sha256(text_only.encode()).hexdigest()
    for name, data in [("topics.json", topics), ("maintenance.json", sched),
                       ("links.json", links)]:
        json.dump(data, open(os.path.join(OUT, name), "w"),
                  ensure_ascii=False, indent=1)
    open(os.path.join(OUT, "snapshot.sha"), "w").write(digest + "\n")

    named = [t for t in topics if is_topic_name(t["name"])]
    print(f"topics={len(topics)} named={len(named)} unique={len({t['id'] for t in named})}")
    print(f"sources={sum(len(t['sources']) for t in topics)} links={len(links)} "
          f"intervals={len(sched)}")
    print("content-sha256", digest[:16])


if __name__ == "__main__":
    main()
