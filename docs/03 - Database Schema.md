# Database Schema

Two tables in Supabase (PostgreSQL) / SQLite locally.
Auto-created on first run via `storage/database.py → init_db()`.

## keyword_snapshots

One row per keyword per run. Tracks counts over time for trend analysis.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `keyword` | TEXT | e.g. "blood sugar trick" |
| `niche` | TEXT | e.g. "diabetes" |
| `country` | TEXT | "US" |
| `active_ad_count` | INTEGER | Total active English ads (from DOM text) |
| `video_count` | INTEGER | Active video ads only |
| `image_count` | INTEGER | Active image/photo ads only |
| `top_pages` | JSON | `[{page_id, page_name, ad_count}]` — top advertisers |
| `snapshot_at` | TEXT | ISO timestamp |
| `fb_library_url` | TEXT | Direct link to FB Ad Library for this keyword |

### Key queries
```sql
-- Latest counts per keyword
SELECT keyword, active_ad_count, video_count, image_count, snapshot_at
FROM keyword_snapshots
ORDER BY snapshot_at DESC, active_ad_count DESC;

-- Trend for one keyword over 30 days
SELECT snapshot_at, active_ad_count, video_count, image_count
FROM keyword_snapshots
WHERE keyword = 'blood sugar trick'
ORDER BY snapshot_at ASC;

-- Top keywords by volume right now
SELECT keyword, niche, active_ad_count, video_count
FROM keyword_snapshots
WHERE snapshot_at >= NOW() - INTERVAL '24 hours'
ORDER BY active_ad_count DESC
LIMIT 20;
```

---

## ads

One row per ad archive ID. Populated by Stage 2, enriched by Stages 3+4.

| Column | Type | Description |
|--------|------|-------------|
| `ad_archive_id` | TEXT UNIQUE | FB Library ID — dedup key |
| `page_id` | TEXT | Advertiser page ID |
| `page_name` | TEXT | Advertiser name |
| `ad_body` | TEXT | Full copy text |
| `start_date` | TEXT | When ad started running |
| `days_running` | INTEGER | Days since start_date |
| `active_status` | TEXT | ACTIVE / INACTIVE |
| `collation_count` | INTEGER | **Scale signal** — active creatives from this advertiser |
| `keyword_found` | TEXT | Which keyword found this ad |
| `image_url` | TEXT | FB CDN URL (valid ~24-48h), used by Stage 3 to fetch + analyze then discard — not a local path, nothing is kept on disk |
| `video_url` | TEXT | Same as `image_url`, for video ads |
| `ad_format` | TEXT | `video` / `image` / `text` / **`catalog`** — catalog means a DPA/multi-card ad with no single fixed creative, see [[07 - Spy Methodology (Gustavo's Process)]] |
| `card_count` | INTEGER | Number of carousel cards (`snapshot.cards[]`) — only non-zero for `ad_format = catalog` |
| `video_transcript` | TEXT | Whisper transcription (Stage 4) |
| `video_analysis` | TEXT | Claude VSL analysis (Stage 4) |
| `image_analysis` | TEXT | Claude Vision analysis (Stage 4) |
| `hook` | TEXT | Opening hook extracted by Claude |
| `pain_points` | TEXT | Lead pains addressed |
| `cta` | TEXT | Call to action |
| `swipe_score` | INTEGER | 0-100 swipe worthiness score |
| `analyzed_at` | TEXT | When Stage 4 ran |

### Key queries
```sql
-- Top scaled ads (collation_count = # of active creatives)
SELECT page_name, collation_count, days_running, keyword_found, ad_body
FROM ads
WHERE active_status = 'ACTIVE'
ORDER BY collation_count DESC NULLS LAST
LIMIT 20;

-- Unanalyzed ads (feed to Stage 4)
SELECT * FROM ads WHERE analyzed_at IS NULL
ORDER BY collation_count DESC NULLS LAST;

-- Video ads with transcripts
SELECT page_name, keyword_found, video_transcript, video_analysis
FROM ads
WHERE video_transcript IS NOT NULL
ORDER BY swipe_score DESC;

-- Catalog/DPA ads (no single fixed creative — see docs/07)
SELECT page_name, card_count, collation_count, keyword_found
FROM ads
WHERE ad_format = 'catalog'
ORDER BY card_count DESC;
```

---

## Switching between SQLite and Supabase

```bash
# Local (SQLite) — no DATABASE_URL set
python -m agents.count_agent --niche diabetes

# Cloud (Supabase) — DATABASE_URL set in .env
DATABASE_URL=postgresql://... python -m agents.count_agent --niche diabetes
```

The code auto-detects based on whether `DATABASE_URL` is set.
