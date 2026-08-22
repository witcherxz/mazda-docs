"""Link-rot checker.

The doc leans on 6,800 outside links; some rot every month (the community already
hand-rescued 112 of them through archive.org). This walks the oldest-checked links
a slice at a time, records what it finds, and looks up a Wayback snapshot for the
dead ones so the site can offer a fallback.
"""
import json, re, urllib.error, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

from common import UA
from store import now

WAYBACK = "https://archive.org/wayback/available?url="
# instagram and twitter answer 200 for deleted posts, so a green check means little there
UNRELIABLE = {"instagram", "twitter", "internal-anchor"}
TG_RE = re.compile(r"https?://t\.me/([^/?#]+)/(\d+)")


def probe_telegram(url, timeout=20):
    """t.me answers 200 for deleted posts, so read the embed and look for the real
    markers: a message bubble with text means the post is alive."""
    m = TG_RE.match(url)
    if not m:
        return "unverified", None
    embed = f"https://t.me/{m.group(1)}/{m.group(2)}?embed=1&mode=tme"
    try:
        req = urllib.request.Request(embed, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            html = r.read().decode("utf-8", "replace")
    except Exception as e:                                 # noqa: BLE001
        return ("dead" if isinstance(e, urllib.error.HTTPError) and e.code in (404, 410)
                else "error"), None
    if "tgme_widget_message_text" in html:
        return "ok", None
    if "tgme_widget_message_error" in html:
        return "dead", None
    return "unverified", None


def probe(url, timeout=12):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, None
    except urllib.error.HTTPError as e:
        if e.code in (405, 403, 501):                     # HEAD refused — try a GET
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.status, None
            except urllib.error.HTTPError as e2:
                return e2.code, None
            except Exception as e2:                        # noqa: BLE001
                return None, type(e2).__name__
        return e.code, None
    except Exception as e:                                 # noqa: BLE001
        return None, type(e).__name__


def wayback(url, timeout=15):
    try:
        req = urllib.request.Request(WAYBACK + urllib.parse.quote(url, safe=""),
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        snap = data.get("archived_snapshots", {}).get("closest", {})
        return snap.get("url") if snap.get("available") else None
    except Exception:                                      # noqa: BLE001
        return None


def classify_status(code, err, kind):
    if code is None:
        return "dead" if err in ("URLError", "gaierror", "TimeoutError", "socket.timeout") \
            else "error"
    if code in (404, 410):
        return "dead"
    if code in (401, 403, 429):
        return "blocked"
    if 200 <= code < 400:
        return "unverified" if kind in UNRELIABLE else "ok"
    return "error"


def run(db, limit=200, workers=8, include_unreliable=False):
    q = ("SELECT url, kind FROM link "
         "WHERE (? OR kind NOT IN ('instagram','twitter','internal-anchor')) "
         "ORDER BY checked_at IS NOT NULL, checked_at ASC LIMIT ?")
    rows = [(r["url"], r["kind"]) for r in db.execute(q, (int(include_unreliable), limit))
            if r["url"].startswith("http")]
    results = []

    def work(item):
        url, kind = item
        if kind == "telegram":
            status, code = probe_telegram(url)
        else:
            code, err = probe(url)
            status = classify_status(code, err, kind)
        archive = wayback(url) if status == "dead" else None
        return url, status, code, archive

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for url, status, code, archive in pool.map(work, rows):
            results.append((status, url))
            db.execute("UPDATE link SET status=?, http_status=?, checked_at=?, "
                       "archive_url=COALESCE(?, archive_url) WHERE url=?",
                       (status, code, now(), archive, url))
    db.commit()
    tally = {}
    for status, _ in results:
        tally[status] = tally.get(status, 0) + 1
    tally["checked"] = len(results)
    tally["dead"] = tally.get("dead", 0)
    return tally


def dead_links(db, limit=200):
    return [dict(r) for r in db.execute(
        "SELECT url, kind, http_status, archive_url, refs FROM link "
        "WHERE status='dead' ORDER BY refs DESC LIMIT ?", (limit,))]
