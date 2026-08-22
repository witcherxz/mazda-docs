#!/usr/bin/env python3
"""One command: fetch → parse → store → diff → build the site.

    python3 tools/pipeline.py                 # local snapshot, cached satellites
    python3 tools/pipeline.py --live          # pull the doc from Google first
    python3 tools/pipeline.py --no-satellites # hub only, fastest
    python3 tools/pipeline.py --live --linkcheck 300
"""
import argparse, hashlib, json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hub, render, satellites, store
from common import DOCX, HUB, ROOT, fetch, gdoc_id

SNAPSHOT = os.path.join(ROOT, "دليل صيانة مازدا.docx")
BUILD = os.path.join(ROOT, "build")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_hub(live, snapshot):
    if live or not os.path.exists(snapshot):
        return fetch(DOCX.format(HUB), ttl=0, timeout=600), "live"
    return open(snapshot, "rb").read(), "snapshot"


def aliases():
    """Curated synonym lists that widen fuzzy search (see data/aliases.json)."""
    path = os.path.join(ROOT, "data", "aliases.json")
    if not os.path.exists(path):
        return []
    return json.load(open(path, encoding="utf-8"))


def apply_aliases(topics, groups):
    from common import norm_ar
    index = []
    for g in groups:
        index.append(([norm_ar(x) for x in g], " ".join(norm_ar(x) for x in g)))
    hits = 0
    for t in topics:
        extra = []
        for terms, blob in index:
            if any(term and term in t["snorm"] for term in terms):
                extra.append(blob)
        if extra:
            t["snorm"] = (t["snorm"] + " " + " ".join(extra))[:900]
            hits += 1
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="fetch the hub doc from Google")
    ap.add_argument("--snapshot", default=SNAPSHOT)
    ap.add_argument("--no-satellites", action="store_true")
    ap.add_argument("--satellite-ttl", type=int, default=6 * 3600,
                    help="reuse cached satellite fetches this many seconds")
    ap.add_argument("--max-satellites", type=int, default=0, help="0 = all")
    ap.add_argument("--linkcheck", type=int, default=0,
                    help="check this many links for rot after building")
    ap.add_argument("--db", default=store.DB_PATH)
    args = ap.parse_args()

    t0 = time.time()
    os.makedirs(BUILD, exist_ok=True)
    print("→ hub document")
    raw, origin = load_hub(args.live, args.snapshot)
    parsed = hub.parse(raw)
    doc_sha = sha(parsed["text"])
    print(f"  {origin}: {len(raw)/1e6:.1f} MB · sha {doc_sha[:12]} · "
          f"{len(parsed['topics'])} topics · {len(parsed['links'])} links")

    sats, sat_errors = [], []
    if not args.no_satellites:
        ids, seen = [], set()
        for l in parsed["links"]:
            gid = gdoc_id(l["url"])
            if gid and gid != HUB and gid not in seen:
                seen.add(gid); ids.append(gid)
        if args.max_satellites:
            ids = ids[:args.max_satellites]
        print(f"→ satellite documents ({len(ids)})")
        sats, sat_errors = satellites.crawl(ids, ttl=args.satellite_ttl)

    topics = list(parsed["topics"])
    for d in sats:
        for t in d["topics"]:
            first = next((c for c in t["norm"] if c.strip()), "")
            t["letter"] = first if "\u0621" <= first <= "\u064a" else "A-Z"
        topics.extend(d["topics"])
    groups = aliases()
    widened = apply_aliases(topics, groups)
    print(f"→ aliases: {len(groups)} groups widened {widened} topics")

    all_links = list(parsed["links"])
    for d in sats:
        all_links += [{"text": l["label"], "url": l["url"], "kind": l["kind"]}
                      for l in d["links"]]

    print("→ store")
    db = store.connect(args.db)
    sync = store.Sync(db)
    sync.docs([{"id": "hub", "kind": "hub", "title": "دليل صيانة مازدا", "sha": doc_sha,
                "bytes": len(raw), "topics": len(parsed["topics"]),
                "links": len(parsed["links"])}] +
              [{"id": d["id"], "kind": "satellite", "title": d["title"],
                "sha": sha(d["text"]), "bytes": d["bytes"], "topics": len(d["topics"]),
                "links": len(d["links"])} for d in sats])
    sync.topics(topics)
    sync.schedule(parsed["schedule"])
    sync.articles(parsed["articles"])
    sync.links(all_links)
    stats = {"sha": doc_sha, "topics": len(topics),
             "sources": sum(t["n"] for t in topics), "links": len(all_links),
             "docs": 1 + len(sats)}
    changes = sync.commit(stats, ok=not sat_errors,
                          note=f"{origin}; {len(sat_errors)} satellite errors")
    print(f"  {len(changes)} changes recorded")

    if args.linkcheck:
        import linkcheck
        print(f"  link health: {linkcheck.run(db, limit=args.linkcheck)}")

    health = {r["url"]: [r["status"], r["archive_url"]] for r in db.execute(
        "SELECT url,status,archive_url FROM link WHERE status IN ('dead','blocked','error')")}
    dead_total = sum(1 for v in health.values() if v[0] == "dead")
    checked_total = db.execute(
        "SELECT COUNT(*) c FROM link WHERE checked_at IS NOT NULL").fetchone()["c"]

    kinds = {}
    for l in all_links:
        kinds[l["kind"]] = kinds.get(l["kind"], 0) + 1

    data = {
        "source": f"https://docs.google.com/document/d/{HUB}/edit",
        "sha": doc_sha,
        "built_at": store.now(),
        "origin": origin,
        "stats": {"topics": len(topics), "hub_topics": len(parsed["topics"]),
                  "sources": stats["sources"], "links": len(all_links),
                  "articles": len(parsed["articles"]), "intervals": len(parsed["schedule"]),
                  "docs": 1 + len(sats), "kinds": kinds,
                  "dead": dead_total, "checked": checked_total},
        "letters": sorted({t["letter"] for t in topics if t["letter"]}),
        "topics": topics,
        "schedule": parsed["schedule"],
        "articles": parsed["articles"],
        "docs": [{"id": d["id"], "title": d["title"], "topics": len(d["topics"]),
                  "links": len(d["links"]), "chars": d["chars"],
                  "sections": d["sections"][:60], "f": d["f"],
                  "url": f"https://docs.google.com/document/d/{d['id']}/edit"}
                 for d in sats],
        "health": health,
        "changes": store.recent_changes(db, 300),
        "runs": [{"at": r["finished_at"], "topics": r["topics"], "changes": r["changes"],
                  "sha": (r["sha"] or "")[:12]} for r in store.runs(db, 20)],
    }
    json.dump(data, open(os.path.join(BUILD, "data.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    json.dump({"changes": changes, "errors": sat_errors, "stats": stats},
              open(os.path.join(BUILD, "run.json"), "w"), ensure_ascii=False, indent=1)
    open(os.path.join(BUILD, "snapshot.sha"), "w").write(doc_sha + "\n")

    out, size = render.build(data)
    print(f"→ site {out} ({size/1e6:.2f} MB) in {time.time()-t0:.1f}s")
    if sat_errors:
        print(f"  ⚠ {len(sat_errors)} satellite fetch errors (see build/run.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
