# Spy Methodology — Gustavo Rafaell's Process

This doc explains the *manual* process this whole pipeline automates: how a
human benchmark analyst finds scaled, validated direct-response (DR) offers
inside the FB Ad Library by hand. If you've never done "ad spying" before,
read this first — it explains *why* the code searches, ranks, and filters the
way it does, and lets you reproduce any step manually if the automation breaks.

Source material: `docs/reference/SPY - Gustavo Rafaell.pdf`,
`docs/reference/Processos Benchmarking - Gustavo Rafael.pdf`, and
`docs/reference/spy-tutorial.txt` (a transcript of his screen-recorded
walkthrough). This doc distills those into a reference; go to the originals
for the unfiltered version.

## 1. The core problem: too many ads, no obvious filter

The FB Ad Library lets anyone search active ads, but a niche term like
"diabetes" returns 50,000+ ads — mostly irrelevant (news, awareness
campaigns, unrelated products). Scrolling through that to find a handful of
validated DR offers isn't feasible. Gustavo's whole method is a set of search
tricks to make FB's own matching algorithm do the filtering for you.

## 2. Search like the algorithm, not like a person

FB's `keyword_unordered` search type (see `core/playwright_scraper.py →
build_search_url()`) matches any ad whose **transcript or copy contains all
your words, in any order**. That's the lever the whole technique pulls on.

### DR-signal words — the single most important trick
Don't search the niche name. Search a niche anchor word **plus** a word that
only appears in direct-response copy: **trick, ritual, hack, secret, recipe,
protocol, method**. Legitimate/editorial content never uses these words —
only DR funnels do. Adding one of these to any search instantly filters out
the noise.

```
"blood sugar"                  → 50,000 results, mostly noise
"blood sugar trick"            → DR-filtered, mostly real offers
"blood sugar trick morning"    → narrower, surfaces different advertisers
```

This is already implemented as the keyword position strategy in
[[02 - Keywords & Niches]] (position 3 = DR signal word). This doc explains
*why* that position exists; that doc has the mechanics.

### Mechanism words — for discovering *new* offers
A "mechanism" is the specific gimmick the offer is built around — "apple
cider vinegar trick," "cinnamon trick," "GLP-1 trick," "Japanese ritual."
Mechanisms **recycle across niches**: "apple cider vinegar" shows up in both
weight-loss and diabetes copy. Gustavo's practical use of this: when a niche
search goes stale (same ads every time), try mechanism words borrowed from a
*different* niche — there's a real chance the same copywriters are running
the same gimmick there too.

### Universal niche words — the words that never go away
Every niche has a handful of symptom/mechanism words that show up regardless
of which specific gimmick is being sold — e.g. diabetes ads almost always
mention "insulin," "blood sugar," or "type 2," no matter what the trick is.
These are good base keywords precisely because they're mechanism-agnostic:
they catch an offer even before you know what gimmick it's using. See the
keyword list in `core/keywords.py` and the original list in
`docs/reference/SPY - Gustavo Rafaell.pdf` for per-niche examples.

### Keep varying the combination
FB's matching shifts meaningfully when you reorder or swap even one word —
get the same 10 ads on every scroll, and the fix isn't to scroll harder, it's
to change the keyword combination. This is why `core/keywords.py` stores
*multiple* keyword variants per niche rather than one "best" keyword per
niche — variety is the point, not redundancy.

### Sort by most recent, not just by impressions
Sorting by total impressions surfaces the biggest *all-time* spenders, which
can include accounts that scaled once and then died. Sorting by most recent
catches what's live and growing *right now*. The pipeline currently sorts by
`total_impressions` (see `sort_data[mode]` in `build_search_url()`) — recency
sort is a manual technique not yet wired into the automation; worth
considering if Trends data shows stale leaders dominating.

## 3. Reading the signals on an ad once you find one

### Duplication = validation
If an advertiser is running dozens or hundreds of near-identical creative
variants, that's not noise — it's the strongest signal that the underlying
offer converts well enough to justify constant creative testing at scale.
This is exactly what `collation_count` measures (see [[03 - Database
Schema]]) — it IS the duplication count, captured automatically per ad.

### Domain-hopping = also validation, with a twist
The same funnel often runs under several different, sometimes
oddly-named domains (e.g. `yluxoee.com/lion1`, `earnbettern.com/lion1`) —
producers do this deliberately so that if Facebook bans/throttles one domain,
the others keep running. Seeing the *same* landing page pattern across
*different* domains for the same advertiser is itself a stronger validation
signal than one domain alone. The pipeline doesn't currently cluster ads by
domain pattern — `ad_link_url` is captured per ad but nothing groups them.
This is a real feature gap if you want to replicate this part by hand: open
a few of an advertiser's ads, compare `ad_link_url` domains, and look for a
shared path segment (`/lion1` in the example above).

### Catalog ads vs. CBO (traditional) ads — two different things to spy on
- **CBO ads** (the "normal" kind) — one fixed creative (one video or one
  image) per ad. You can watch it, download it, transcribe it. This is what
  Stage 3/4 (`agents/analyze_agent.py`) is built to fully analyze.
- **Catalog/DPA ads** — Meta assembles the creative per-viewer from a product
  feed, shown as a multi-image carousel (`snapshot.cards[]` in the raw data).
  There usually isn't one fixed creative to point at — Gustavo's own notes
  call this out explicitly: you generally can't download "the" creative for
  these, so the practical move is to log it as an *offer* (page name, niche,
  approximate scale) rather than try to swipe a specific ad.

  The pipeline detects this automatically: `core/html_parser.py` sets
  `ad_format = "catalog"` and `card_count = len(cards)` whenever an ad has
  cards. `analyze_agent.py` skips video/image download for catalog ads (since
  there's no single representative creative) but still runs copy analysis and
  records why in the `notes` field.

## 4. Validating an offer (not just an ad)

A single ad with high `collation_count` tells you one advertiser is scaling.
But the bigger validation signal in Gustavo's notes is at the **offer**
level, not the advertiser level:

> Method to identify a 6-figure+ offer:
> 1. At least 6,000-10,000 active ads for the offer.
> 2. Sum across affiliates — if 5 different affiliate accounts are each
>    running the same VSL/funnel at smaller scale (e.g. 50-200k BRL/day
>    each), that combined total still validates the offer, even though no
>    single account hits the 6-10k threshold alone.

**This is a real gap in the current pipeline.** Stage 1/2 rank and dedupe at
the `page_id` level (one row = one advertiser account). There's no logic
anywhere that clusters multiple `page_id`s running the *same* underlying
offer/VSL and sums their reach. To do this validation manually today: pull
the top accounts for a niche (`--top-accounts` mode in `metadata_agent.py`),
open a few ads from each, and check if the `ad_body` copy or landing page
matches across accounts — if it does, they're affiliates of the same offer
and their `collation_count`s should be added together, not compared
separately.

## 5. Quick reference: where each technique lives in the code

| Manual technique | Code location | Status |
|---|---|---|
| DR-signal-word search | `core/keywords.py`, [[02 - Keywords & Niches]] | Implemented |
| `keyword_unordered` matching | `core/playwright_scraper.py → build_search_url()` | Implemented |
| Duplication signal (collation_count) | `core/html_parser.py`, `ads.collation_count` | Implemented |
| Direct account targeting (skip keyword scroll) | `metadata_agent.py --top-accounts` | Implemented, not yet in daily cron |
| Catalog vs. CBO ad detection | `core/html_parser.py → ad_format/card_count` | Implemented |
| Sort by most recent (not impressions) | — | Manual only |
| Domain-hopping pattern clustering | — | Manual only |
| Multi-affiliate offer validation (6-10k rule) | — | Manual only |
