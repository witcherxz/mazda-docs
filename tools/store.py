"""SQLite store with a change log.

The Google Doc is the source of truth; this database is a derived mirror that
remembers what the doc looked like on previous runs, so every sync can report
exactly what the community changed.
"""
import json, os, sqlite3, time

from common import ROOT

DB_PATH = os.path.join(ROOT, "build", "mazda.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS doc(
  id TEXT PRIMARY KEY, kind TEXT, title TEXT, sha TEXT, bytes INTEGER,
  topics INTEGER, links INTEGER, first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS topic(
  id TEXT PRIMARY KEY, doc_id TEXT, name TEXT, letter TEXT, note TEXT,
  norm TEXT, facets TEXT, n_sources INTEGER,
  first_seen TEXT, last_seen TEXT, status TEXT DEFAULT 'live');
CREATE TABLE IF NOT EXISTS source(
  topic_id TEXT, rank INTEGER, label TEXT, url TEXT, kind TEXT,
  PRIMARY KEY(topic_id, url));
CREATE TABLE IF NOT EXISTS interval(
  id INTEGER PRIMARY KEY, label TEXT, km INTEGER, months INTEGER,
  inherits INTEGER, items TEXT);
CREATE TABLE IF NOT EXISTS article(
  id TEXT PRIMARY KEY, title TEXT, chars INTEGER, nlinks INTEGER,
  first_seen TEXT, last_seen TEXT);
CREATE TABLE IF NOT EXISTS link(
  url TEXT PRIMARY KEY, kind TEXT, refs INTEGER,
  first_seen TEXT, last_seen TEXT,
  status TEXT, http_status INTEGER, checked_at TEXT, archive_url TEXT);
CREATE TABLE IF NOT EXISTS change(
  id INTEGER PRIMARY KEY AUTOINCREMENT, run_at TEXT, entity TEXT,
  entity_id TEXT, field TEXT, before TEXT, after TEXT, label TEXT);
CREATE TABLE IF NOT EXISTS run(
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
  sha TEXT, topics INTEGER, sources INTEGER, links INTEGER,
  docs INTEGER, changes INTEGER, ok INTEGER, note TEXT);
CREATE INDEX IF NOT EXISTS idx_change_run ON change(run_at);
CREATE INDEX IF NOT EXISTS idx_topic_doc ON topic(doc_id);
"""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def connect(path=DB_PATH):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.row_factory = sqlite3.Row
    if path != ":memory:":
        try:                                       # link checks run alongside builds
            db.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass                                   # another writer holds it; busy_timeout covers us
    db.execute("PRAGMA busy_timeout=60000")
    db.executescript(SCHEMA)
    return db


class Sync:
    """One pipeline run: diff the incoming snapshot against the stored one."""

    def __init__(self, db):
        self.db = db
        self.at = now()
        self.changes = []
        self.bootstrap = db.execute("SELECT COUNT(*) c FROM topic").fetchone()["c"] == 0

    def log(self, entity, entity_id, field, before, after, label=""):
        self.changes.append({"entity": entity, "id": entity_id, "field": field,
                             "before": before, "after": after, "label": label,
                             "at": self.at})

    # -------------------------------------------------------------- documents
    def docs(self, docs):
        for d in docs:
            row = self.db.execute("SELECT * FROM doc WHERE id=?", (d["id"],)).fetchone()
            if row is None:
                if not self.bootstrap:
                    self.log("doc", d["id"], "added", None, d["title"], d["title"])
                self.db.execute(
                    "INSERT INTO doc(id,kind,title,sha,bytes,topics,links,first_seen,last_seen)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (d["id"], d.get("kind", "satellite"), d["title"], d.get("sha"),
                     d.get("bytes"), d.get("topics", 0), d.get("links", 0), self.at, self.at))
                continue
            if row["sha"] != d.get("sha"):
                self.log("doc", d["id"], "content", row["sha"], d.get("sha"), d["title"])
            if row["title"] != d["title"]:
                self.log("doc", d["id"], "title", row["title"], d["title"], d["title"])
            self.db.execute(
                "UPDATE doc SET title=?,sha=?,bytes=?,topics=?,links=?,last_seen=? WHERE id=?",
                (d["title"], d.get("sha"), d.get("bytes"), d.get("topics", 0),
                 d.get("links", 0), self.at, d["id"]))

    # ----------------------------------------------------------------- topics
    def topics(self, topics):
        old = {r["id"]: r for r in self.db.execute(
            "SELECT id,name,doc_id,n_sources,status FROM topic")}
        seen = set()
        for t in topics:
            seen.add(t["id"])
            prev = old.get(t["id"])
            if prev is None:
                if not self.bootstrap:      # first run would log every topic as new
                    self.log("topic", t["id"], "added", None, t["name"], t["name"])
                self.db.execute(
                    "INSERT INTO topic(id,doc_id,name,letter,note,norm,facets,n_sources,"
                    "first_seen,last_seen,status) VALUES(?,?,?,?,?,?,?,?,?,?,'live')",
                    (t["id"], t.get("doc", "hub"), t["name"], t.get("letter"), t.get("note"),
                     t["norm"], json.dumps(t["f"], ensure_ascii=False), t["n"],
                     self.at, self.at))
            else:
                if prev["n_sources"] != t["n"]:
                    self.log("topic", t["id"], "sources", prev["n_sources"], t["n"], t["name"])
                if prev["status"] != "live":
                    self.log("topic", t["id"], "restored", prev["status"], "live", t["name"])
                self.db.execute(
                    "UPDATE topic SET name=?,letter=?,note=?,norm=?,facets=?,n_sources=?,"
                    "last_seen=?,status='live' WHERE id=?",
                    (t["name"], t.get("letter"), t.get("note"), t["norm"],
                     json.dumps(t["f"], ensure_ascii=False), t["n"], self.at, t["id"]))
            self.db.execute("DELETE FROM source WHERE topic_id=?", (t["id"],))
            self.db.executemany(
                "INSERT OR REPLACE INTO source(topic_id,rank,label,url,kind) VALUES(?,?,?,?,?)",
                [(t["id"], i, s["label"], s["url"], s["kind"])
                 for i, s in enumerate(t["sources"])])
        for tid, row in old.items():
            if tid not in seen and row["status"] == "live":
                self.log("topic", tid, "removed", row["name"], None, row["name"])
                self.db.execute("UPDATE topic SET status='gone', last_seen=? WHERE id=?",
                                (self.at, tid))

    # -------------------------------------------------------------- schedule
    def schedule(self, intervals):
        old = {r["label"]: r for r in self.db.execute("SELECT * FROM interval")}
        self.db.execute("DELETE FROM interval")
        for i, iv in enumerate(intervals):
            items = json.dumps({"replace": iv["replace"], "inspect": iv["inspect"]},
                               ensure_ascii=False)
            prev = old.get(iv["interval"])
            if prev is None:
                if not self.bootstrap:
                    self.log("interval", str(iv.get("km") or i), "added", None,
                             iv["interval"], iv["interval"])
            elif prev["items"] != items:
                self.log("interval", str(iv.get("km") or i), "items",
                         f'{len(json.loads(prev["items"])["replace"])} بند',
                         f'{len(iv["replace"])} بند', iv["interval"])
            self.db.execute(
                "INSERT INTO interval(id,label,km,months,inherits,items) VALUES(?,?,?,?,?,?)",
                (i, iv["interval"], iv["km"], iv["months"], int(iv["inherits"]), items))

    # -------------------------------------------------------------- articles
    def articles(self, articles):
        old = {r["id"]: r for r in self.db.execute("SELECT * FROM article")}
        for a in articles:
            prev = old.get(a["id"])
            if prev is None:
                if not self.bootstrap:
                    self.log("article", a["id"], "added", None, a["title"], a["title"])
                self.db.execute(
                    "INSERT INTO article(id,title,chars,nlinks,first_seen,last_seen)"
                    " VALUES(?,?,?,?,?,?)",
                    (a["id"], a["title"], a["chars"], a["nlinks"], self.at, self.at))
            else:
                if abs(prev["chars"] - a["chars"]) > 40:
                    self.log("article", a["id"], "text", prev["chars"], a["chars"], a["title"])
                self.db.execute(
                    "UPDATE article SET title=?,chars=?,nlinks=?,last_seen=? WHERE id=?",
                    (a["title"], a["chars"], a["nlinks"], self.at, a["id"]))

    # ----------------------------------------------------------------- links
    def links(self, links):
        counts, kinds = {}, {}
        for l in links:
            url = l["url"]
            counts[url] = counts.get(url, 0) + 1
            kinds.setdefault(url, l["kind"])
        known = {r["url"] for r in self.db.execute("SELECT url FROM link")}
        fresh = [(url, kinds[url], refs, self.at, self.at)
                 for url, refs in counts.items() if url not in known]
        seen_again = [(refs, self.at, url)
                      for url, refs in counts.items() if url in known]
        self.db.executemany(
            "INSERT INTO link(url,kind,refs,first_seen,last_seen,status)"
            " VALUES(?,?,?,?,?,'unknown')", fresh)
        self.db.executemany("UPDATE link SET refs=?, last_seen=? WHERE url=?", seen_again)

    # ------------------------------------------------------------------ done
    def commit(self, stats, ok=True, note=""):
        self.db.executemany(
            "INSERT INTO change(run_at,entity,entity_id,field,before,after,label)"
            " VALUES(?,?,?,?,?,?,?)",
            [(c["at"], c["entity"], c["id"], c["field"],
              None if c["before"] is None else str(c["before"]),
              None if c["after"] is None else str(c["after"]), c["label"])
             for c in self.changes])
        self.db.execute(
            "INSERT INTO run(started_at,finished_at,sha,topics,sources,links,docs,changes,ok,note)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (self.at, now(), stats.get("sha"), stats.get("topics"), stats.get("sources"),
             stats.get("links"), stats.get("docs"), len(self.changes), int(ok), note))
        self.db.commit()
        return self.changes


def recent_changes(db, limit=200):
    return [dict(r) for r in db.execute(
        "SELECT run_at,entity,entity_id,field,before,after,label FROM change"
        " ORDER BY id DESC LIMIT ?", (limit,))]


def runs(db, limit=30):
    return [dict(r) for r in db.execute(
        "SELECT * FROM run ORDER BY id DESC LIMIT ?", (limit,))]
