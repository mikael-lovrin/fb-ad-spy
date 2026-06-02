# Pipeline Stages

The pipeline has 4 independent agents. Each can run standalone or as part of the full pipeline.

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
| `_video_url` | Video URL (for Stage 3) |
| `_image_url` | Image URL (for Stage 3) |

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

## Stage 3 — Download Agent
**File:** `agents/download_agent.py`
**Command:** `python -m agents.download_agent --limit 200`

### What it does
- Finds ads with remote `video_url` or `image_url` in the DB
- Downloads to `data/media/<ad_archive_id>.<ext>`
- Updates the DB with the local file path
- Skips if file already exists

---

## Stage 4 — Analyze Agent
**File:** `agents/analyze_agent.py`
**Command:** `python -m agents.analyze_agent --limit 50`

### What it does
For each unanalyzed ad:
1. **Copy analysis** (Claude): extracts industry, hook, pain points, benefits, CTA, funnel format
2. **Video** (if `video_url` exists): ffmpeg audio extraction → Whisper transcription → Claude VSL analysis
3. **Image** (if `image_url` exists): Claude Vision → creative analysis
4. **Swipe score** (0-100): composite signal based on days running + impression volume + hook presence + DR niche

### Swipe score formula
```
days_running >= 90:  +40 pts   (market validated)
days_running >= 30:  +25 pts
impressions >= 1M:   +30 pts   (big budget)
impressions >= 100k: +20 pts
hook present:        +15 pts
known DR niche:      +15 pts
```
