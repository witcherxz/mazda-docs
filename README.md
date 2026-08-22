# دليل مازدا المنظم — organized Mazda community guide

A browsable, searchable view of the Saudi Mazda owners' community knowledge base, generated
automatically from their Google Doc
([دليل صيانة مازدا](https://docs.google.com/document/d/1Yj0AP9xVrkLqIf01mdelU4m4OcQR-NGxuTNYpGeiIvM/edit))
and the 48 satellite documents it links to.

**The doc stays the single source of truth.** The community keeps editing exactly as they do
today; this repository only reads, and never writes back.

```
3,584 topics · 6,269 ranked sources · 49 documents · 18,053 links
14 maintenance intervals · 19 curated sections · 2,958 links health-checked (91 dead)
```

## Run it

```bash
make fast     # hub document only, ~1 second — writes build/preview.html, not the site
make build    # everything, satellites from cache
make live     # pull the doc from Google first
make test     # extraction guardrails (22 tests)
make serve    # http://localhost:8000
# add --dry-run to any pipeline call to see the diff without recording it
```

Python 3 standard library only. No pandoc, no python-docx, no npm, no build step.

Two outputs, one template:

| Output | What it is |
|---|---|
| `site/index.html` | everything inlined in one 2.6 MB file — opens from the filesystem, works offline, easy to share |
| `dist/` | shell + `data.json` — what gets deployed, so the payload is fetched once and served gzipped (~480 KB) |

## Search

Fuzzy, fzf-style: query characters only have to appear **in order**, so `زجج جنب` finds
الزجاج الجانبي and `حسهوا` finds حساس الهواء — it even reaches `الزجاجالجانبي`, the entry in
the source doc with the missing space. Scoring rewards contiguous runs, matches at word
starts and shorter names; matched characters are highlighted. Space separates terms (all must
match), and `data/aliases.json` widens 60 synonym groups so الدعسة also finds الثروتل.

Arabic is normalized identically on both sides — diacritics stripped, أإآ→ا, ة→ه, ى→ي.

One query searches **every** section at once: the tab badges turn into live match counts
(`الفهرس 42 · جدول الصيانة 5 · الشروحات 5 · المستندات 4`), and a section with nothing to
show points at the ones that do. Short strings — topic names, document titles, change rows —
match with full fuzzy scoring; long text like the maintenance cells and article bodies
matches per word, so `زجج` still finds الزجاج inside a paragraph without every query matching
everything. Every section highlights its hits: character-level inside short names, whole-word
inside paragraphs, where scattered marks would just be noise.

The page is dark by default; the ☾/☀ button switches it and the choice is remembered.
A colour legend (◍ in the header) explains what each source colour means; it stays closed
until asked for.

`/` focuses · `↑` `↓` walk the results · `Enter` opens the top source · `Esc` clears.
State lives in the URL (`#tab=docs&q=…`), so any view is shareable.

## What the site shows

- **الفهرس** — every topic with its ranked sources, colour-coded by kind (Telegram, YouTube,
  document, site), filtered by model / engine / year / source / document.
- **جدول الصيانة** — the maintenance matrix: interval → replace/clean vs inspect, with the
  "includes the previous service" inheritance the doc encodes. The doc writes each cell as one
  comma-separated paragraph; the UI splits it back into one task per row, with the task's
  sources as numbered references at the end of its line and `>` between phrases rendered as
  procedure steps (`‹`), which is what it means in this document.
- **الشروحات** — the long-form sections, with internal doc links turned into in-app jumps.
- **المستندات** — the 48 satellite documents, their sections, and a jump into their topics.
- **التحديثات** — what the community changed, run by run.

Dead links are struck through and, where the Wayback Machine has a copy, they open the
archived version instead — Telegram links are verified through the message embed, since
`t.me` answers 200 even for deleted posts. The deployed build registers a service worker, so
the guide keeps working in a workshop with no signal.

## Pipeline

```
tools/pipeline.py           fetch → parse → store → diff → build
├── common.py               normalization, link classification, facets, cached fetch
├── hub.py                  .docx (OOXML) parser: topics, schedule, articles, anchors
├── satellites.py           the 48 linked docs via mobilebasic (1 MB each, not 300 MB)
├── store.py                SQLite mirror + change log (build/mazda.db)
├── linkcheck.py            link rot detection + Wayback fallback
├── render.py               builds site/ and dist/
└── template.html           the UI — data is injected at build time
```

Change detection hashes the doc's *extracted text*, never the .docx bytes (the zip is not
reproducible). Topic IDs hash the normalized name, so a topic keeps its identity when the
community reorders the index, and renames surface as changes instead of duplicates.

`build/mazda.db` is committed on purpose: it carries the history of what changed and when.

## Deploying

See [DEPLOY.md](DEPLOY.md). Short version: push to GitHub, set Pages to "GitHub Actions",
and `.github/workflows/sync.yml` rebuilds and republishes daily.

## Background

[FEASIBILITY.md](FEASIBILITY.md) is the study this was built from — the structural patterns
in the source document, what parses reliably, what needs human curation, and the risks.

## Credit

All content is written and maintained by the Saudi Mazda owners' community —
**[قروب مازدا 6 على تيليقرام](https://t.me/mzda6)** and the channels around it. This
repository only generates a view of their work; every page credits them and links back to
the original document, and the pipeline never writes to it.

The document's own disclaimer stands: المعلومات الوارده لأغراض نشر الثقافه فقط.
