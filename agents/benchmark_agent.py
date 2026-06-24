# -*- coding: utf-8 -*-
"""
Agent 4 — Benchmark Analyst Agent
===================================
Synthesizes Stage 1 (keyword volume trends) and Stage 2/3 (top ads, swipe
candidates) into a human-readable benchmark report per niche — the same
judgment call a human benchmark analyst makes when reviewing Gustavo
Rafaell's spy results, but over the full keyword set instead of by hand.
See docs/07 for the manual process this automates.

Human-triggered for now. Daily cron + Slack delivery is a stated goal, not
built — wire it later by scheduling this script and posting report_md to a
webhook; nothing here assumes a schedule.

Three data passes feed one Claude call per niche (kept to one call to avoid
paying for three separate LLM round-trips when the arithmetic itself is
plain Python):
  1. get_trend_summary    — % change in active_ad_count per keyword
  2. get_new_entrants     — advertisers in top_pages now but not N days ago
  3. get_top_offers       — top ads by collation_count/days_running/swipe_score

Usage:
    python -m agents.benchmark_agent --niche weight_loss
    python -m agents.benchmark_agent --all
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

import anthropic

from core.config import ANTHROPIC_API_KEY, CLAUDE_MODEL
from core.keywords import get_available_nichos, get_keywords_for_nicho
from storage.database import init_db, get_conn, save_benchmark_report

logger = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# A throttled snapshot (FB serving the simplified page) always reads
# exactly 100/100/100 — never a real count. Exclude these from trend math,
# same detection logic as count_agent.
def _is_throttled(row: dict) -> bool:
    return row.get("active_ad_count") == 100 and row.get("video_count") == 100 and row.get("image_count") == 100


def get_trend_summary(niche: str, days: int = 14) -> list[dict]:
    """
    For each keyword in the niche, compare the latest snapshot's active_ad_count
    against the snapshot closest to `days` ago. Returns one row per keyword with
    pct_change, sorted descending (biggest gainers first, biggest decliners last).
    Skips keywords with fewer than 2 usable (non-throttled) snapshots.
    """
    keywords = get_keywords_for_nicho(niche)
    if not keywords:
        return []

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    results = []

    with get_conn() as conn:
        for kw in keywords:
            rows = [
                dict(r) for r in conn.execute(
                    "SELECT active_ad_count, video_count, image_count, snapshot_at "
                    "FROM keyword_snapshots WHERE keyword=? AND niche=? "
                    "ORDER BY snapshot_at ASC",
                    (kw, niche),
                ).fetchall()
            ]
            usable = [r for r in rows if not _is_throttled(r)]
            if len(usable) < 2:
                continue

            latest = usable[-1]
            older = next((r for r in usable if r["snapshot_at"] >= cutoff), usable[0])
            if older is latest:
                continue

            prev_count = older["active_ad_count"] or 0
            cur_count  = latest["active_ad_count"] or 0
            pct_change = ((cur_count - prev_count) / prev_count * 100) if prev_count else 0.0

            results.append({
                "keyword": kw,
                "prev_count": prev_count,
                "cur_count": cur_count,
                "pct_change": round(pct_change, 1),
                "prev_at": older["snapshot_at"],
                "cur_at": latest["snapshot_at"],
            })

    return sorted(results, key=lambda r: r["pct_change"], reverse=True)


def get_new_entrants(niche: str, days: int = 14) -> list[dict]:
    """
    Advertisers (page_id) present in a keyword's latest top_pages list but
    absent from that keyword's top_pages snapshot ~`days` ago. A new name in
    the leaderboard is a candidate for "this offer is newly scaling."
    """
    keywords = get_keywords_for_nicho(niche)
    if not keywords:
        return []

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    new_entrants: dict[str, dict] = {}

    with get_conn() as conn:
        for kw in keywords:
            rows = [
                dict(r) for r in conn.execute(
                    "SELECT top_pages, snapshot_at FROM keyword_snapshots "
                    "WHERE keyword=? AND niche=? ORDER BY snapshot_at ASC",
                    (kw, niche),
                ).fetchall()
            ]
            if len(rows) < 2:
                continue

            latest = rows[-1]
            older = next((r for r in rows if r["snapshot_at"] >= cutoff), rows[0])
            if older is latest:
                continue

            try:
                old_ids = {p.get("page_id") for p in json.loads(older["top_pages"] or "[]")}
                new_pages = json.loads(latest["top_pages"] or "[]")
            except (TypeError, ValueError):
                continue

            for p in new_pages:
                pid = p.get("page_id")
                if pid and pid not in old_ids and pid not in new_entrants:
                    new_entrants[pid] = {
                        "page_id": pid,
                        "page_name": p.get("page_name"),
                        "ad_count": p.get("ad_count"),
                        "keyword": kw,
                    }

    return sorted(new_entrants.values(), key=lambda p: p.get("ad_count") or 0, reverse=True)


def get_top_offers(niche: str, limit: int = 15) -> list[dict]:
    """Top ACTIVE ads for this niche's keywords, ranked by scale + validation signals."""
    keywords = get_keywords_for_nicho(niche)
    if not keywords:
        return []

    placeholders = ", ".join(["?"] * len(keywords))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT page_name, ad_body, hook, cta, collation_count, days_running,
                       swipe_score, keyword_found, ad_archive_id, ad_format
                FROM ads
                WHERE active_status='ACTIVE' AND keyword_found IN ({placeholders})
                ORDER BY collation_count DESC NULLS LAST, days_running DESC NULLS LAST
                LIMIT ?""",
            (*keywords, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def generate_niche_report(niche: str, trend_days: int = 14, top_n: int = 15) -> dict:
    """Run all three data passes, send one Claude call, save + return the report."""
    trend = get_trend_summary(niche, days=trend_days)
    entrants = get_new_entrants(niche, days=trend_days)
    offers = get_top_offers(niche, limit=top_n)

    data = {"trend": trend, "new_entrants": entrants, "top_offers": offers}

    rising = trend[:5]
    declining = [r for r in reversed(trend[-5:]) if r["pct_change"] < 0]

    prompt = f"""You are a senior direct-response (DR) media-buying benchmark analyst.
Below is structured data scraped from the Facebook Ad Library for the "{niche}" niche
over the last {trend_days} days. Write a concise benchmark report a media buyer could
act on today. Use markdown with these sections exactly:

## {niche} Benchmark Report
### Niche Pulse
### Rising Keywords
### Declining Keywords
### New Scale-Leader Advertisers
### Top Swipe Candidates
### Recommended Action

Keep it tight — sentences, not walls of bullet points. "Recommended Action" must be one
concrete, specific next step (e.g. "swipe X's hook", "stop targeting keyword Y, it's dead").
If a section has no data, write "Nothing notable this period" instead of inventing content.

RISING KEYWORDS (pct change over {trend_days}d):
{json.dumps(rising, indent=2, ensure_ascii=False)}

DECLINING KEYWORDS:
{json.dumps(declining, indent=2, ensure_ascii=False)}

NEW SCALE-LEADER ADVERTISERS (top_pages entries not seen {trend_days}d ago):
{json.dumps(entrants[:10], indent=2, ensure_ascii=False)}

TOP OFFERS (by collation_count = active creative duplication, days_running, swipe_score):
{json.dumps(offers[:10], indent=2, ensure_ascii=False)}
"""

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1200,
            messages=[{"role": "user", "content": prompt}],
        )
        report_md = response.content[0].text.strip()
    except Exception as e:
        logger.error(f"Benchmark synthesis error: {e}")
        report_md = f"# {niche} Benchmark Report\n\nError generating report: {e}"

    save_benchmark_report(niche, report_md, data)
    return {"niche": niche, "report_md": report_md, "data": data}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Agent 4: Benchmark analyst report per niche")
    parser.add_argument("--niche", type=str, help="Single niche")
    parser.add_argument("--all", action="store_true", help="Run all active niches")
    parser.add_argument("--days", type=int, default=14, help="Trend window in days (default 14)")
    parser.add_argument("--top", type=int, default=15, help="Top offers to consider (default 15)")
    args = parser.parse_args()

    init_db()

    niches = get_available_nichos() if args.all else ([args.niche] if args.niche else [])
    if not niches:
        print(f"Use --niche <name> or --all. Available: {get_available_nichos()}")
        sys.exit(1)

    for niche in niches:
        logger.info(f"[benchmark_agent] Generating report for '{niche}'...")
        result = generate_niche_report(niche, trend_days=args.days, top_n=args.top)
        print(f"\n{'='*80}\n{result['report_md']}\n{'='*80}\n")
