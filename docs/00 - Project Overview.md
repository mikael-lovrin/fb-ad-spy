# FB Ad Spy — Project Overview

> Automates the FB Ad Library benchmark process described by Gustavo Rafaell.
> Monitors active DR (Direct Response) ads across 10 niches, twice daily, and stores everything in Supabase for trend analysis.

## What this project does

1. Searches Facebook Ad Library for DR keywords (no login required — public tool)
2. Counts active ads per keyword, separated by video vs image
3. Extracts individual ad metadata: publisher, copy, dates, scale signal
4. Downloads video/image creatives to disk
5. Analyzes copy with Claude, transcribes video with Whisper

## Quick links

- [[01 - Pipeline Stages]] — the 4-stage architecture
- [[02 - Keywords & Niches]] — 10 niches, 129 keywords, position strategy
- [[03 - Database Schema]] — Supabase tables and fields
- [[04 - Cloud Setup]] — GitHub Actions, Supabase, Docker
- [[05 - How to Run]] — local and cloud commands
- [[06 - Known Issues & Limits]] — FB throttling, anti-bot behavior
- [[07 - Spy Methodology (Gustavo's Process)]] — the manual technique this automates, for newcomers

## Daily schedule (Brazil Time / BRT = UTC-3)

| Time BRT | Action |
|----------|--------|
| 5:00 AM  | Stage 1 starts — count keywords for all 10 niches |
| ~6:00 AM | Results available in Supabase |
| 10:00 AM | Stage 2 starts — collect individual ad metadata |
| 2:00 PM  | Stage 3+4 — download media + Claude analysis |
| 5:00 PM  | Stage 1 again — evening trend check |
| ~6:00 PM | Evening counts available in Supabase |

## Tech stack

| Layer | Tool |
|-------|------|
| Scraping | Playwright (headless Chromium) |
| Data source | FB Ad Library public HTML |
| Database | Supabase (PostgreSQL) / SQLite local |
| Copy analysis | Anthropic Claude (claude-sonnet-4) |
| Video transcription | Whisper (local faster-whisper or OpenAI API) |
| Image analysis | Claude Vision |
| Cloud CI | GitHub Actions (IP rotation per niche) |
| Container | Docker |
