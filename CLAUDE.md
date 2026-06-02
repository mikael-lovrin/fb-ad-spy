# FB Ad Spy — Claude Code Instructions

## Environment

- Python venv at `.venv/` — always activate before running: `.venv\Scripts\activate`
- Database: SQLite locally (`data/ads.db`) OR Supabase if `DATABASE_URL` is set in `.env`
- All code and communication in **English** — professional, well-commented

## What this project does

Automates the FB Ad Library competitive intelligence process described by Gustavo Rafaell.
Monitors active DR (Direct Response) ads across 10 niches, twice daily (6AM and 6PM BRT).
Stores keyword counts, ad metadata, copy, transcriptions, and Claude analysis in Supabase.

## 4-stage pipeline

| Stage | Agent | What it does |
|-------|-------|-------------|
| 1 | `agents/count_agent.py` | Counts active ads per keyword (total / video / image) → keyword_snapshots |
| 2 | `agents/metadata_agent.py` | Extracts individual ad data from HTML → ads table |
| 3 | `agents/download_agent.py` | Downloads video/image files to data/media/ |
| 4 | `agents/analyze_agent.py` | Claude copy + Vision + Whisper analysis → ads table |

## Key technical discoveries

### FB Ad Library data location (Stage 2)
Ad data is server-side rendered into the page HTML inside a large `<script>` tag (~391KB).
**NOT** in a separate API/GraphQL response.
Path: `script → require → __bbox → result.data.ad_library_main.search_results_connection.edges[].node.collated_results[]`
Parser: `core/html_parser.py`

### Throttle detection
If `total == video == image == 100` for 3+ keywords → FB is serving simplified pages.
Auto-fix: count_agent waits 90s after 3 consecutive throttled keywords.
Recovery: wait 30-90 min, use `--delay 30`.

### URL format (critical)
Must use `keyword_unordered` + `sort_data[direction]=desc&sort_data[mode]=total_impressions`.
Brackets in `sort_data[...]` must NOT be URL-encoded (FB rejects `%5B%5D`).
Builder: `core/playwright_scraper.py → build_search_url()`

## File structure

```
agents/          4 pipeline agents (count, metadata, download, analyze)
analysis/        Claude copy, image, video analyzers
core/            config, keywords, playwright scraper, HTML parser
storage/         database layer (dual SQLite/PostgreSQL), media downloader
dashboard/       Streamlit dashboard
docs/            Obsidian project notes
.github/workflows/ GitHub Actions (Stage 1×2/day, Stage 2, Stage 3+4)
Dockerfile       Playwright + ffmpeg production image
```

## Commands

```bash
# Stage 1 — count
python -m agents.count_agent --niche diabetes --delay 30

# Stage 2 — metadata
python -m agents.metadata_agent --niche diabetes --min-ads 5000

# Full pipeline
python pipeline.py --niche weight_loss

# Count only (no Claude API costs)
python pipeline.py --niche weight_loss --count-only
```

## Nichos / niches (10 total)

`weight_loss`, `diabetes`, `ed`, `memory`, `back_pain`, `vision`, `prostate`, `sleep`, `blood_pressure`, `neuropathy`

Keywords in `core/keywords.py` — 129 total, all English, organized by DR position strategy:
- Position 1-2: symptom anchor ("blood sugar", "belly fat")
- Position 3: DR signal ("trick", "ritual") — filters to DR content only
- Position 4: qualifier ("morning", "recipe") — surfaces different advertisers

## Cloud

- **GitHub:** github.com/mikael-lovrin/fb-ad-spy
- **Supabase:** PostgreSQL at `db.lbyimeiifhusrsbshxvg.supabase.co`
- **Schedules:** Stage 1 at 08:00 UTC + 20:00 UTC, Stage 2 at 13:00 UTC, Stage 3+4 at 17:00 UTC
- **IP rotation:** each GitHub Actions matrix niche = different runner = different IP
