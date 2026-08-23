# Mazda Community Doc → Structured Database: Feasibility Study

**Source:** [دليل صيانة مازدا](https://docs.google.com/document/d/1Yj0AP9xVrkLqIf01mdelU4m4OcQR-NGxuTNYpGeiIvM/edit) (hub doc), snapshot taken 2026-08-22
**Question:** can the community keep editing the Google Doc while we scrape it programmatically and regenerate an organized, synced knowledge base?
**Verdict:** yes for the link/topic layer (the doc's real substance), partly for the tabular layer, no for free prose. Proven with a working prototype: `tools/sync.py`.

---

## 1. What the document actually is

Measured, not estimated — all numbers from parsing `word/document.xml` of the export:

| Metric | Value |
|---|---|
| Paragraphs | 1,861 |
| Plain text | 131 KB (~131,000 chars) |
| Hyperlink runs (raw) | 17,315 |
| Distinct link references (after merging split runs) | 6,713 |
| Named topics in the master index | 968 unique (1,095 named entries) |
| Avg. sources per topic | 3.2 (median 1, max 35) |
| Tables | 11 top-level |
| Word heading styles | 14 total — effectively unused |
| Embedded images | 53 files / 16 MB (98% of file size) |
| Satellite Google Docs linked | 49 distinct doc IDs |
| Telegram channels referenced | 35 |

**The key insight: this is not a prose document, it is a hand-maintained link index.** 131 KB of text carries 6,713 links — roughly one link per 20 characters. The value is in *topic → ranked sources*, not in paragraphs. That makes it far more machine-extractable than "messy doc" suggests.

Link targets by class:

| Class | Count | Meaning |
|---|---|---|
| telegram (`t.me`) | 2,852 | permalinks to community messages = the evidence layer |
| general web | 1,380 | forums, vendors, part catalogs |
| youtube | 1,127 | repair procedure videos |
| google-doc | 510 | 49 satellite docs = topic deep-dives |
| internal anchor | 372 | in-document jumps (bookmarks) |
| nhtsa | 162 | recall/TSB PDFs |
| archive.org | 112 | already-rescued dead links |
| shortlink (`goo.gl`) | 76 | **at risk — Google shut down goo.gl resolution** |
| instagram / image hosts / maps / twitter | 122 | mixed |

Top Telegram sources: `Mazda3Group` (2,797), `mzda6` (1,402), `MAZDACX9KSA` (803), `mazda6ksa` (568), `MazdaCX5_SA` (177).

---

## 2. Sync mechanics — verified working

- `https://docs.google.com/document/d/<ID>/export?format=docx` returns **HTTP 200 with no authentication** for the hub doc and for the satellite docs tested. No OAuth, no API key, no scraping of the editor UI.
- Formats available: `docx` (keeps links + structure + media), `html` (keeps links, inlines images as base64 → 47 MB for the hub), `txt` (89 KB but **loses all URLs — unusable for this doc**).
- **No `Last-Modified` or `ETag`** is returned (`cache-control: no-store`). Change detection must be content-based: `tools/sync.py` writes a SHA-256 of the extracted text to `build/snapshot.sha`.
- Zip bytes are non-deterministic between exports, so never hash the `.docx` itself — hash the extracted text.
- Satellite docs are image-heavy: one is **324 MB**, another 100 MB as `.docx`. Pulling all 49 daily is ~1 GB of transfer, mostly photos. Mitigation: fetch satellites weekly, or use the Docs API (`docs.googleapis.com/v1/documents/{id}`) which returns structure + links as JSON with no image bytes — that path needs a service account and the docs shared with it, so verify before committing to it.

**Recommended cadence:** hub doc hourly or daily (16 MB, cheap), satellites weekly, link-rot check monthly.

---

## 3. Structural patterns found

These are the extraction handles, ranked by how reliable each is under community editing.

### Pattern A — the alphabetical master index (reliability: high)
Table 0 is a 28-row, 2-column grid: column 1 is an Arabic letter (أ ب ت ث … ي, then `A-Z`), column 2 is a dense run of topics for that letter. This is a real taxonomy the community already maintains. 3,453 links live here.

### Pattern B — link text *is* the topic name (reliability: high)
The topic label is not plain text next to a link — it is the anchor text itself:
`[ارتفاع الحرارة](docs.google.com/…)`, `[الاستبنة](docs.google.com/…)`, `[استدعاء واصلاحات مازدا](mazdaproblems.com/tsbs)`.
**Caveat that breaks naïve parsers:** Google Docs splits one anchor into multiple `w:hyperlink` elements whenever formatting changes mid-link, so "انوار م3 كاملة" arrives as three separate links. Merging consecutive hyperlinks that share a target collapses 17,315 raw runs into 6,713 real links and fixes the names. This single rule is the difference between garbage output and clean output.

### Pattern C — `>` `او` `=` chain, `,` separates (reliability: high)
`الشاشة تضغط من نفسها>1>2>3>4>5>6>7>8`. A link whose text is only a number, `*`, or `>` is *another source for the preceding named topic*, ordered roughly best-first. This is the community's own ranking signal — it maps directly onto a `sources[]` array with a `rank`.

### Pattern D — the maintenance interval matrix (reliability: high)
Table 1 is a clean 3-column grid: `الصيانة` (interval) | `تغيير \ تنظيف` (replace/clean) | `فحص` (inspect), 14 interval rows: 1,000 km → 3,500 → 8,000 → 16,000 → 24,000 → 40,000 → 60,000 …
It also encodes **inheritance**: `صيانة 16 الف +` means "everything from the 16k service, plus". That's a resolvable graph, not free text.

### Pattern E — symptom → ranked causes (reliability: medium)
Tables 2, 3, 4, 9 group causes by severity with explicit headers:
`أخطرها ويستدعي الفحص والإصلاح العاجل` (most dangerous, needs urgent inspection) → `أسباب اعراضها غالبا خفيفة` (usually mild) → `أسباب نادرة الحدوث` (rare).
Causes are listed `مرتبة من الأشهر للأقل` — ordered most-common to least. Severity tier and rank are extractable from the row grouping; the cause text itself needs light cleanup.

### Pattern F — parts, part numbers, prices, dates (reliability: medium)
Prose but highly regular, e.g. `PE11-13-ZE0 بالوكالة 286 ريال زاد الى 320 ريال \ خارج الوكالة 240 ريال بتاريخ 1\2023`.
Across the doc: 77 Mazda part numbers (`[A-Z]{2,4}…-\d\d-\d\d\d`), 133 prices in ريال, and prices are *dated* (`بتاريخ 7/2023`) — the community already versions its own price data. Regex extraction plus a review queue gets this into a proper `parts` table with price history.

### Pattern G — vehicle applicability tokens (reliability: medium)
Model/year/engine scoping is written inline and consistently enough to parse: 228 year ranges (`2015-2019`), 173 `cx3/cx5/cx9/cx30/cx50/cx60/cx90` mentions, 123 `مازدا 3 / مازدا 6`, 146 engine displacements (`1.6`, `2.0`, `2.5`), plus `توربو` / `بدون توربو`, `فل` / `ستاندر` / `سقنتشر` trims. This becomes the faceted filter that makes the generated site actually usable.

### Anti-pattern — do NOT rely on formatting
Colors (`#e69138`, `#1155cc`, `#ff9900`), font sizes (sz18–sz68), and highlights *look* semantic but are not applied consistently, and 14 stray heading styles land on random part numbers. Any parser keyed to color or font size will break the first time a volunteer edits on their phone. **Key on the hyperlink graph and table geometry only.**

---

## 4. Proposed data model

```
topic(id, name_ar, name_norm, letter, section, first_seen, last_seen, status)
source(id, topic_id, rank, label, url, kind, channel, dead_since, archive_url)
vehicle(id, model, year_from, year_to, engine, drivetrain, trim)
topic_vehicle(topic_id, vehicle_id)          -- applicability facets
symptom(id, topic_id, tier, rank, text_ar)   -- tier: urgent|moderate|mild|rare
part(id, part_no, name_ar, oem, supersedes)
price(part_id, vendor, amount_sar, observed_on, source_id)
interval(id, km, months, condition, inherits_from)
interval_item(interval_id, action, kind)     -- kind: replace|clean|inspect
doc_node(id, gdoc_id, title, parent_id, sha, fetched_at)   -- the 49-doc graph
change(id, run_at, entity, entity_id, field, before, after)
```

Stable IDs come from a hash of the normalized topic name, so a topic keeps its identity across runs even when the community reorders the index. Renames surface in `change` for review rather than silently creating a duplicate.

---

## 5. Pipeline

```
fetch (docx export, no auth)
  → hash extracted text; skip if unchanged
  → parse OOXML (stdlib zipfile + ElementTree; no pandoc, no python-docx)
  → merge split hyperlink runs                 [Pattern B]
  → walk index table → topics + ranked sources [A, C]
  → walk matrix table → intervals              [D]
  → walk symptom tables → causes by tier       [E]
  → regex pass → parts, prices, vehicles       [F, G]
  → upsert into SQLite, write change log
  → emit JSON + static site (RTL Arabic, full-text search)
  → review queue: anything unparsed, renamed, or dead-linked
```

One-way by design: **the Google Doc stays the single source of truth and is never written back to.** The community's workflow is untouched; they keep editing exactly as they do today.

---

## 6. What will *not* extract cleanly

Stating this plainly, because it decides how much human effort the project needs:

- **Free-prose sections** (~40% of the body): the deep dives on suspension noise, catalytic converter cleaning, spark plugs. Extractable as *sections* with their links, not as structured facts. Treat as articles.
- **Colloquial Saudi vocabulary**, non-standard and inconsistent: `الاستبنة` (spare tyre), `بواجي` (spark plugs), `الثروتل\الدعسة\بوابة هواء المحرك` (three names for one throttle body), `الاصطب` (headlight?/stabilizer — context-dependent). No parser resolves these; they need a **hand-maintained synonym/alias table**, seeded once (a few hundred entries) and grown by the community. This is the single largest human cost in the project.
- **Typos and spacing damage** in the source (`الزجاجالجانبي`, `علامةسير المكينة`) — needs normalization plus fuzzy matching on topic identity.
- **Telegram content**: 2,852 links point into channels. `t.me/<channel>/<id>?embed=1` returns rendered message HTML (verified), so text and image URLs can be archived, but private/deleted messages and channels that disable embeds will fail. Archiving other people's community posts is also a consent question worth raising with the maintainers before doing it at scale.

---

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Volunteer edit breaks a parse rule | High likelihood, low damage | Never key on color/size; alert on row-count or topic-count deltas > 10%; changes land in a review queue, not straight to publish |
| Link rot (76 `goo.gl` already at risk; 112 links are archive.org rescues the community made by hand) | High | Monthly HTTP check, auto-submit to web.archive.org, store `archive_url` |
| Satellite doc weight (~1 GB across 49) | Medium | Weekly cadence; evaluate Docs API for structure-only fetch |
| Google changes/limits the export endpoint | Low, fatal if it happens | Keep every raw export snapshot; a service-account Drive path is the fallback |
| Topic identity churn on rename | Medium | Hash-based IDs + rename review, never silent re-create |
| Ownership/attribution | — | Content is the community's; publish with credit, keep the disclaimer already in the doc (`المعلومات الوارده لأغراض نشر الثقافه فقط`), and get the maintainers' blessing before publishing a derived site |

---

## 8. Effort estimate

| Phase | Scope | Effort |
|---|---|---|
| 1 — Extractor + sync | Patterns A–D, hash-based change detection, JSON output | **Done** (`tools/sync.py`) |
| 2 — Storage + change log | SQLite, stable IDs, diff per run | 1–2 days |
| 3 — Symptoms, parts, vehicles | Patterns E–G + alias table seeding | 3–5 days |
| 4 — Static site | RTL Arabic, faceted by model/year/engine, full-text search | 3–4 days |
| 5 — Link health | Rot detection + archive fallback | 1–2 days |
| 6 — Satellite crawl | 49-doc graph, dedupe against hub | 2–3 days |
| Ongoing | Alias curation + review queue | ~2 h/week |

---

## 9. Prototype results

`tools/sync.py` (stdlib only — no pandoc, no python-docx) runs against either the local snapshot or the live doc:

```
$ python3 tools/sync.py            # fetches live export
topics=1149 named=1095 unique=983
sources=3453 links=6806 intervals=14
content-sha256 b2f76fdfc59740b1
```

The live fetch produced a byte-identical text hash to the local snapshot, confirming the round trip. Outputs land in `build/`: `topics.json`, `maintenance.json`, `links.json`, `snapshot.sha`.

Sample of extracted topics:

| Letter | Topic | Sources |
|---|---|---|
| أ | اختيار سيارة | 1 × google-doc |
| أ | اسعار قطع الغيار | 1 × google-doc |
| أ | اسعار صيانة الوكالة الغير الزامية لاستمرار الضمان | 1 × telegram |
| أ | استدعاء واصلاحات مازدا | 14 (web, forums, NHTSA) |

## Recommendation

Build it, phased as above, starting from the link/topic layer — it is 80% of the doc's value and the part that parses cleanly today. Budget the alias table as real ongoing work, not a one-off. Talk to the doc's maintainers before publishing anything derived from it.
