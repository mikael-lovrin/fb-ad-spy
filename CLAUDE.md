# FB Ad Spy — Claude Code Instructions

## Environment

- Python venv at `.venv/` — always activate before running: `.venv\Scripts\activate`
- Database: SQLite locally (`data/ads.db`) OR Supabase if `DATABASE_URL` is set in `.env`
- All code and communication in **English** — professional, well-commented

## What this project does

Automates the FB Ad Library competitive intelligence process described by Gustavo Rafaell.
Monitors active DR (Direct Response) ads across 10 niches, twice daily (6AM and 6PM BRT).
Stores keyword counts, ad metadata, copy, transcriptions, and Claude analysis in Supabase.

**New to "ad spying"?** Read `docs/07 - Spy Methodology (Gustavo's Process).md` first —
it explains the manual technique (DR-signal words, mechanism words, duplication/domain
signals, catalog vs. CBO ads, offer-validation thresholds) that this codebase automates.
The original source material is in `docs/reference/`.

## Pipeline

| Stage | Agent | What it does |
|-------|-------|-------------|
| 1 | `agents/count_agent.py` | Counts active ads per keyword (total / video / image) → keyword_snapshots |
| 2 | `agents/metadata_agent.py` | Extracts individual ad data from HTML → ads table |
| 3 | `agents/analyze_agent.py` | Downloads media to temp → Claude copy + Vision + Whisper → deletes media, keeps only analysis text |
| 4 | `agents/benchmark_agent.py` | Human-triggered. Synthesizes Stages 1-3 into a per-niche markdown report → benchmark_reports table, shown on the dashboard |

(Stages 1-3 run daily via GitHub Actions. Originally a 4-stage design with a separate download
agent — merged into Stage 3 since media is temporary anyway; `agents/download_agent.py` no
longer exists. Stage 4 is new and not yet scheduled — see docs/01.)

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

### Catalog/DPA ads have no single fixed creative
When `snapshot.cards[]` is non-empty, the ad is a Meta-assembled catalog/DPA carousel, not a
fixed video/image. `html_parser.py` flags these as `ad_format = "catalog"` with `card_count`
set; `analyze_agent.py` skips video/image download for them (nothing representative to
transcribe) but still runs copy analysis. See `docs/07 - Spy Methodology (Gustavo's Process).md`.
Builder: `core/playwright_scraper.py → build_search_url()`

## File structure

```
agents/          4 agents (count, metadata, analyze, benchmark)
analysis/        Claude copy, image, video analyzers
core/            config, keywords, playwright URL builders, HTML parser
storage/         database layer (dual SQLite/PostgreSQL)
dashboard/       Streamlit dashboard
docs/            Obsidian project notes + docs/reference/ source PDFs/transcripts
.github/workflows/ GitHub Actions (Stage 1 daily, Stage 2 daily, Stage 3 daily — Stage 4 not scheduled)
Dockerfile       Playwright + ffmpeg production image
```

## Commands

```bash
# Stage 1 — count
python -m agents.count_agent --niche weight_loss --delay 30

# Stage 2 — metadata
python -m agents.metadata_agent --niche weight_loss --min-ads 5000

# Stage 4 — benchmark report (human-triggered)
python -m agents.benchmark_agent --niche weight_loss
python -m agents.benchmark_agent --all

# Full pipeline (stages 1-3)
python pipeline.py --niche weight_loss

# Count only (no Claude API costs)
python pipeline.py --niche weight_loss --count-only
```

## Nichos / niches (5 total)

`weight_loss`, `ed`, `memory`, `prostate`, `sleep`

(`back_pain`, `neuropathy`, `diabetes`, `blood_pressure`, `vision` dropped 2026-06-24
during a niche-list review.)

Keywords in `core/keywords.py` — 129 total, all English, organized by DR position strategy:
- Position 1-2: symptom anchor ("blood sugar", "belly fat")
- Position 3: DR signal ("trick", "ritual") — filters to DR content only
- Position 4: qualifier ("morning", "recipe") — surfaces different advertisers

## Cloud

- **GitHub:** github.com/mikael-lovrin/fb-ad-spy
- **Supabase:** PostgreSQL at `db.lbyimeiifhusrsbshxvg.supabase.co`
- **Schedules:** Stage 1 at 08:00 UTC + 20:00 UTC, Stage 2 at 13:00 UTC, Stage 3+4 at 17:00 UTC
- **IP rotation:** each GitHub Actions matrix niche = different runner = different IP
