# Deploying and running the stack

The whole product is three static files (`dist/index.html`, `dist/data.json`,
`dist/manifest.webmanifest`) plus a scheduled job that regenerates them. There is no
server, no database to host, and no API key anywhere — the Google Doc export endpoint
is public.

## Recommended: GitHub Pages (free, zero-maintenance)

The workflow in `.github/workflows/sync.yml` already does everything: runs the tests,
pulls the doc live, rebuilds, commits the refreshed dataset, and publishes `dist/`.

```bash
# from the project directory
git remote add origin git@github.com:<you>/mazda-docs.git
git push -u origin main
```

Then in the repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
The site lands at `https://<you>.github.io/mazda-docs/`. The first run takes ~3 minutes
(most of it crawling the 48 satellite documents); later runs reuse the cache and take ~1.

What the schedule does daily at 03:17 UTC:

1. `python3 -m unittest discover -s tests` — if an extraction rule broke, the run stops here.
2. `tools/pipeline.py --live --linkcheck 300` — fetch, parse, diff against the stored
   snapshot, health-check 300 links, rebuild.
3. Commits `build/data.json` + `build/mazda.db` so the change history is versioned.
4. Publishes `dist/` to Pages, and writes a summary of what the community changed into the
   Actions run page.

Trigger it by hand any time from the Actions tab (`workflow_dispatch`), where you can also
turn the satellite crawl off or change how many links get checked.

### Custom domain

The site is served from **mazda-community.org**. `tools/render.py` writes `dist/CNAME` on every
build (with the canonical URL, robots.txt and sitemap), so the domain survives each redeploy —
a Pages artifact without a CNAME file drops the custom domain.

DNS at the registrar, for the apex:

| Type | Name | Value |
|---|---|---|
| A | @ | 185.199.108.153 |
| A | @ | 185.199.109.153 |
| A | @ | 185.199.110.153 |
| A | @ | 185.199.111.153 |
| AAAA | @ | 2606:50c0:8000::153 |
| AAAA | @ | 2606:50c0:8001::153 |
| AAAA | @ | 2606:50c0:8002::153 |
| AAAA | @ | 2606:50c0:8003::153 |
| CNAME | www | witcherxz.github.io. |

Then Settings → Pages → Custom domain → `mazda-community.org` → Save, and tick **Enforce HTTPS**
once the certificate is issued (a few minutes after DNS resolves).

To change the domain later, edit `DOMAIN` in `tools/render.py` — everything else follows.

## Alternatives

| Host | Setup | Notes |
|---|---|---|
| **Cloudflare Pages** | build `pip install nothing; python3 tools/pipeline.py --live`, output `dist` | Best if you want the site served from inside Saudi Arabia's nearest PoP; also gives free analytics |
| **Netlify** | same build command, publish `dist` | Deploy previews per PR |
| **Any static host / S3 / nginx** | `make build` then upload `dist/` | Serve `data.json` with gzip — it drops 2.5 MB to ~458 KB |
| **No host at all** | `make build` then open `site/index.html` | Single self-contained file, works offline, easy to share on Telegram |

## Sizes and cost

| Thing | Size | Note |
|---|---|---|
| `dist/index.html` | ~38 KB | shell: markup, styles, search engine |
| `dist/data.json` | ~2.5 MB (~458 KB gzipped) | fetched once, cached by the browser |
| `site/index.html` | ~2.6 MB | same data inlined, for offline/file sharing |
| Hub doc fetch | 16.7 MB per sync | the .docx export |
| Satellite crawl | ~55 MB per full crawl | 48 docs via `mobilebasic`; cached 6 h by default |
| GitHub Actions | ~2 min per run | far inside the free tier |

Serve `data.json` with a long `Cache-Control` and rely on the content hash in the page
footer to tell readers whether they are looking at a fresh copy.

## Operating it

```bash
make build      # rebuild from the local snapshot, satellites from cache
make live       # pull the doc from Google first
make fast       # hub only — 2 seconds, good while editing the UI
make test       # extraction guardrails
make serve      # http://localhost:8000
make links      # health-check 300 links and record the results

# any pipeline call takes --dry-run: reports the diff, records nothing
python3 tools/pipeline.py --live --dry-run
```

**Watching for breakage.** Every run records a row in the `run` table and writes
`build/run.json`. Two signals matter: a sudden drop in topic count (a parse rule broke, or
the community restructured the index table), and a spike in `removed` changes. The workflow
summary shows both. The tests in `tests/test_pipeline.py` assert the floors — >800 topics,
14 interval rows, every topic having at least one source — so a structural break fails CI
before it reaches the site.

**When the doc's structure changes for real.** Fix the rule in `tools/hub.py`, add a case to
the tests, and re-run. Never key on colours or font sizes; the parsers deliberately use only
the hyperlink graph and table geometry, because formatting in the source doc is inconsistent.

**Rollback.** `build/data.json` and `build/mazda.db` are committed on every sync, so
`git revert` restores any previous day's dataset, and the `change` table explains what
differed.

## Search engines

The app is one URL with its state in hash fragments, and search engines ignore fragments —
so on its own only the home page could ever be indexed. Every build therefore also writes a
static page per topic, article, document and index letter (783 pages today) under
`/t/…`, `/a/…`, `/d/…`, `/l/…`, each with its own title, description, canonical URL and the
sources in the markup, linking into the app for the interactive view. `sitemap.xml` lists
them all, `robots.txt` points at it, and the deployed home page carries a crawlable nav of
letter and document links so crawlers can walk the index without the sitemap.

To get them indexed:

1. **Google Search Console** → Add property → Domain → `mazda-community.org`. Verify with the
   DNS TXT record it gives you (Cloudflare → DNS → Add record → TXT).
2. Sitemaps → submit `sitemap.xml`.
3. URL Inspection on a couple of topic pages → *Request indexing*, to seed the crawl.
4. Optional: the same at [Bing Webmaster Tools](https://www.bing.com/webmasters), which also
   feeds DuckDuckGo; it can import the Search Console property directly.

Expect days for the home page and weeks for the long tail. The pages that will actually pull
search traffic are the symptom-shaped ones — "فتحة السقف ماتنزل", "تطفى المكينة فجأة" — which
is exactly what someone types into Google.

## Before you publish it publicly

The content belongs to the Saudi Mazda owners' community — [t.me/mzda6](https://t.me/mzda6)
and the channels around it — not to this repository. The site
carries their disclaimer and links back to the original document on every screen, and the
pipeline never writes to their doc. Even so: tell the maintainers before putting a public
mirror online, credit them by name if they want it, and take it down if they ask. If you add
analytics, use something that does not profile readers.
