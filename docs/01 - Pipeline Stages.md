# Pipeline Stages

The pipeline has 3 scraping/analysis agents (run daily via GitHub Actions) plus a 4th,
human-triggered benchmark agent that synthesizes their output into a readable report.
Each can run standalone or as part of the full pipeline (`pipeline.py`).

## Stage 1 — Count Agent
**File:** `agents/count_agent.py`
**Command:** `python -m agents.count_agent --niche diabetes`

### What it does
- Loads FB Ad Library page for each keyword (headless Chromium)
- Runs 3 sequential page loads per keyword: `media_type=all`, `video`, `image`
- Extracts the "N results" text from the page DOM — this is the REAL count FB shows in UI
- Saves to `keyword_snapshots` table

### Output per keyword
```
blood sugar trick  →  total=15,000  video=10,000  image=1,800
```

### Key detail: why `keyword_unordered`
FB transcribes every video ad. `keyword_unordered` finds any ad where ALL your words appear anywhere in the transcript/copy (any order). This gives 10-100x more results than `keyword_exact_phrase`.

### Why counts are sometimes 100
FB detects automated requests and serves a simplified page that caps at "100 results". Signs of throttling:
- `total == video == image == 100` for multiple keywords in a row
- HTML is ~1.2MB instead of ~2.2MB
- Fix: wait 30-90 min, use longer delays (`--delay 30`)

---

## Stage 2 — Metadata Agent
**File:** `agents/metadata_agent.py`
**Command:** `python -m agents.metadata_agent --niche diabetes --min-ads 5000`

### What it does
- Loads the FB Ad Library page and parses the server-side rendered HTML
- Finds the large `<script type="application/json">` tag (~391KB) containing `search_results_connection`
- Extracts individual ad nodes from `edges[].node.collated_results[]`
- Saves to `ads` table

### Data extracted per ad
| Field | Source |
|-------|--------|
| `ad_archive_id` | Library ID (unique key) |
| `page_name` | Publisher name |
| `ad_body` | Full copy text |
| `collation_count` | Active creatives from this advertiser ← scale signal |
| `start_date` | When the ad started running |
| `days_running` | Calculated from start_date |
| `video_url` / `image_url` | FB CDN URL, valid ~24-48h — fetched and discarded by Stage 3, never stored locally |
| `ad_format` / `card_count` | `catalog` when `snapshot.cards[]` is non-empty (DPA/carousel ad, no single fixed creative) — see [[07 - Spy Methodology (Gustavo's Process)]] |

### Scale signal — collation_count
Gustavo's method: advertisers with 10,000+ active creatives = validated scaled offer.
`collation_count` is the number of active ad variations running from that page.

### HTML extraction path
```
<script type="application/json" data-content-len="391241">
  → require[...] → __bbox → result.data
    → ad_library_main.search_results_connection
      → count (real total)
      → edges[].node.collated_results[]
          → ad_archive_id, collation_count, snapshot.body.text, ...
```

---

## Stage 3 — Analyze Agent
**File:** `agents/analyze_agent.py`
**Command:** `python -m agents.analyze_agent --limit 50`

### What it does
For each unanalyzed ad (download → analyze → delete; nothing is kept on disk):
1. **Copy analysis** (Claude): extracts industry, hook, pain points, benefits, CTA, funnel format
2. **Video** (if `video_url` and not `ad_format == "catalog"`): download temp → ffmpeg audio extraction → Whisper transcription → Claude VSL analysis → delete
3. **Image** (if `image_url` and not catalog): download temp → Claude Vision → delete
4. **Catalog ads**: skipped for video/image (no single fixed creative — see [[07 - Spy Methodology (Gustavo's Process)]]), copy analysis still runs
5. **Swipe score** (0-100): composite signal based on days running + impression volume + hook presence + DR niche

### Swipe score formula
```
days_running >= 90:  +40 pts   (market validated)
days_running >= 30:  +25 pts
impressions >= 1M:   +30 pts   (big budget)
impressions >= 100k: +20 pts
hook present:        +15 pts
known DR niche:      +15 pts
```

---

## Stage 4 — Benchmark Agent (human-triggered)
**File:** `agents/benchmark_agent.py`
**Command:** `python -m agents.benchmark_agent --niche weight_loss` or `--all`

### What it does
Synthesizes Stages 1-3 output into a per-niche markdown report — the judgment call a human
benchmark analyst makes when reviewing spy results, automated. Three Python data passes feed
one Claude call (not three, to avoid paying for separate LLM round-trips on plain arithmetic):

1. `get_trend_summary` — % change in `active_ad_count` per keyword over the trend window,
   excluding throttled snapshots (100/100/100)
2. `get_new_entrants` — advertisers in a keyword's `top_pages` now but not N days ago
3. `get_top_offers` — top ads by `collation_count` / `days_running` / `swipe_score`

Report sections: Niche Pulse, Rising/Declining Keywords, New Scale-Leader Advertisers,
Top Swipe Candidates, Recommended Action. Saved to `benchmark_reports` table, shown on the
dashboard's "Benchmark Reports" tab.

Daily cron + Slack delivery is a stated future goal, not built — this agent is designed to be
schedulable later (call it from a workflow, post `report_md` to a webhook) without changes.
