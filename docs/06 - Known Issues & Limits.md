# Known Issues & Limits

## FB Ad Library behavior

### Throttling (most common issue)
**Symptom:** All keyword counts return exactly 100 (or 10), video == image == total.
**Cause:** FB detects automated requests (too many in short window) and serves a simplified 1.2MB page instead of the full 2.2MB page.
**Diagnosis:** The full page has a `~391KB <script>` tag with ad data. Throttled page has only 2 large scripts (~117KB, ~184KB).
**Fix:**
- Wait 30-90 minutes before retrying
- Use `--delay 30` to space keywords further apart
- Count agent now auto-detects: if 3 consecutive keywords return 100/100/100, it waits 90s automatically

### 100 is sometimes genuine
`dynamic_filter_options.content_languages["en"].count` is hard-capped at 100 by FB's API — this is not throttling. The real count comes from the DOM text ("50,000 results"). The agent prefers DOM count → falls back to the API cap.

### Video count = image count = total
Happens when the DOM text returns the same number regardless of `media_type` URL param. This means the throttled page is being served. In the full page, counts differ correctly (e.g., gelatin trick: 50k video, 180 image).

---

## Stage 2 HTML extraction

### 0 ads extracted
The large script tag (`data-content-len ~391000`) wasn't found. Causes:
1. Throttled page served (1.2MB instead of 2.2MB) — wait and retry
2. FB changed the page structure — check `data/tmp/page.html` after a debug run

### Location of ad data in HTML
```
<script type="application/json" data-content-len="~391000" data-sjs="">
  → require → __bbox → result.data.ad_library_main.search_results_connection
    → count   (total ads)
    → edges[].node.collated_results[]
        → ad_archive_id, collation_count, snapshot.body.text, ...
```
The parser (`core/html_parser.py`) tries all large scripts sorted by size, takes the first one containing `search_results_connection`.

---

## Database

### `%40` in Supabase URL
The `@` character in a PostgreSQL password must be percent-encoded as `%40` in the connection string.
Example: password `Abc@123` → URL uses `Abc%40123`.

### Column migration errors
If `table ads has no column named collation_count` → run `init_db()` again. The migration function adds missing columns idempotently.

---

## GitHub Actions minutes

Private repo free tier: 2,000 min/month.
Stage 1 twice/day for 10 niches ≈ 160 min/day × 30 = 4,800 min/month — exceeds free tier.

**Solution:** Make the repo **public** → unlimited free minutes.
Keys are all in GitHub Secrets (not in the code), so public repo is safe.

---

## FB Ad Library legal note

FB Ad Library is a legally mandated transparency tool (EU Digital Services Act + US election transparency laws). Scraping it is legal. FB cannot sue for reading their public transparency tool. The only risk is IP throttling (temporary).
