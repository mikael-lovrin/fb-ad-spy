# -*- coding: utf-8 -*-
"""
Agent 1 — Count Agent
=====================
For every keyword, loads FB Ad Library three times (all / video / image) and records:
  - total active English ad count  (from content_languages["en"].count)
  - video count                    (from media_type=video query)
  - image count                    (from media_type=image query)
  - top advertisers by ad volume   (from dynamic_filter_options.pages)

Key findings from reverse-engineering dynamic_filter_options:
  - content_languages[lang].count  = total active ads in that language for the query
  - pages[advertiser].count        = capped display count per advertiser (not exact total)
  - The REAL total (50k+ for "gelatin trick") comes from search_results_connection
    which requires a separate, currently unresolved request (rate limited if concurrent)
  - Requests must be SEQUENTIAL with delay — concurrent pages trigger rate limit 1675004

Keyword expansion: --expand flag adds 3-word variants per the Gustavo Rafaell method.

Usage:
    python -m agents.count_agent --niche diabetes
    python -m agents.count_agent --keyword "gelatin trick" --niche weight_loss
    python -m agents.count_agent --niche weight_loss --expand
    python -m agents.count_agent --all
"""

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime

from playwright.async_api import async_playwright

from core.keywords import get_keywords_for_nicho, get_keywords_expanded, get_available_nichos
from core.playwright_scraper import build_search_url
from storage.database import init_db, save_snapshot

# Matches "50,000 results" or "~2 results" in FB Ad Library page DOM
_RESULT_COUNT_RE = re.compile(r"([\d,]+)\s+results?", re.IGNORECASE)


def _parse_dom_count(text: str) -> int:
    """Extract result count from FB Ad Library DOM text. Returns 0 if not found."""
    match = _RESULT_COUNT_RE.search(text)
    if not match:
        return 0
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return 0

logger = logging.getLogger(__name__)


async def _fetch_page_data(context, url: str, delay_before: float = 0.0) -> dict:
    """
    Load one FB Ad Library URL and return a dict with:
      - dfo:         dynamic_filter_options (GraphQL)
      - dom_count:   result count from page DOM text ("50,000 results")

    Sequential requests only — FB rate-limits concurrent GraphQL calls (1675004).
    delay_before: seconds to sleep before loading (space sequential calls).
    """
    if delay_before > 0:
        await asyncio.sleep(delay_before)

    page = await context.new_page()
    dfo: dict = {}
    rate_limited = False

    async def on_response(response):
        nonlocal dfo, rate_limited
        if "facebook.com/api/graphql" not in response.url:
            return
        if response.status != 200:
            return
        try:
            text = await response.text()
            text = re.sub(r"^for\s*\(;;\s*\)\s*;", "", text.strip())
            data = json.loads(text)

            errors = data.get("errors") or []
            if any(e.get("code") == 1675004 for e in errors):
                rate_limited = True
                logger.warning("Rate limit hit — slowing down")
                return

            candidate = (
                (data.get("data") or {})
                .get("ad_library_main", {})
                .get("dynamic_filter_options")
            )
            if candidate:
                dfo = candidate
        except Exception:
            pass

    page.on("response", on_response)
    dom_count = 0

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        for sel in [
            'button:has-text("Allow all cookies")',
            'button:has-text("Accept all")',
            '[data-testid="cookie-policy-manage-dialog-accept-button"]',
        ]:
            try:
                await page.click(sel, timeout=1_500)
                break
            except Exception:
                pass

        # Wait for both GraphQL and DOM content
        for _ in range(12):
            await page.wait_for_timeout(700)
            if dfo or rate_limited:
                break

        # Extract result count from DOM — more reliable than capped GraphQL counts
        try:
            body_text = await page.inner_text("body")
            dom_count = _parse_dom_count(body_text)
        except Exception:
            pass

    except Exception as e:
        logger.warning(f"Page load error: {e}")
    finally:
        await page.close()

    return {"dfo": dfo, "dom_count": dom_count}


def _extract_counts(dfo: dict, language: str = "en") -> tuple[int, list[dict]]:
    """
    Extract counts from dynamic_filter_options.

    English ad count: content_languages[lang].count — more accurate than summing pages[].count
    because pages[].count is capped (shows top advertisers only, count capped at 10/100).

    Top pages: sorted by count, useful for identifying scale leaders.

    Returns (english_count, top_10_pages).
    """
    # Get total English count from content_languages
    lang_count = 0
    for lang_entry in dfo.get("content_languages") or []:
        if lang_entry.get("key") == language:
            lang_count = lang_entry.get("count", 0)
            break

    # Get top advertisers
    pages = dfo.get("pages") or []
    top = sorted(pages, key=lambda p: p.get("count", 0), reverse=True)[:10]
    top_normalized = [
        {
            "page_id":    p.get("key", ""),
            "page_name":  p.get("display_name", ""),
            "ad_count":   p.get("count", 0),
        }
        for p in top
    ]

    return lang_count, top_normalized


async def _count_keyword_sequential(context, keyword: str, country: str) -> dict:
    """
    Count ads for one keyword via three sequential FB queries (all / video / image).
    Sequential with 3-second gaps to avoid FB rate limit (code 1675004).

    Count strategy (priority order):
      1. DOM text "N results"   — actual total shown in UI (most accurate)
      2. content_languages["en"].count — capped at 100, but shows relative scale
      3. sum(pages[].count)     — last resort, only top advertisers
    """
    all_url   = build_search_url(keyword, country, media_type="all",   language="en")
    video_url = build_search_url(keyword, country, media_type="video",  language="en")
    image_url = build_search_url(keyword, country, media_type="image",  language="en")

    all_data   = await _fetch_page_data(context, all_url,   delay_before=0.0)
    video_data = await _fetch_page_data(context, video_url, delay_before=3.0)
    image_data = await _fetch_page_data(context, image_url, delay_before=3.0)

    # Total: prefer DOM count (actual UI total), fallback to lang count
    _, top_pages     = _extract_counts(all_data["dfo"])
    _, _             = _extract_counts(video_data["dfo"])
    _, _             = _extract_counts(image_data["dfo"])

    total_count = all_data["dom_count"]
    video_count = video_data["dom_count"]
    image_count = image_data["dom_count"]

    # Fallback chain if DOM didn't return counts
    if total_count == 0:
        lang_count, _ = _extract_counts(all_data["dfo"])
        total_count = lang_count or sum(p.get("count", 0) for p in (all_data["dfo"].get("pages") or []))
    if video_count == 0:
        video_count, _ = _extract_counts(video_data["dfo"])
    if image_count == 0:
        image_count, _ = _extract_counts(image_data["dfo"])

    return {
        "keyword":        keyword,
        "country":        country,
        "total":          total_count,
        "video_count":    video_count,
        "image_count":    image_count,
        "top_pages":      top_pages,
        "fb_library_url": all_url,
    }


async def run_count_agent_async(
    niche: str,
    country: str = "US",
    keywords: list[str] = None,
    expand: bool = False,
    inter_keyword_delay: float = 15.0,
) -> list[dict]:
    """
    inter_keyword_delay: seconds between keywords (default 15s).
    Increase to 30s+ if seeing counts of exactly 100 across all keywords,
    which indicates FB is serving throttled pages for the IP.
    """
    if keywords:
        kw_list = keywords
    elif expand:
        kw_list = get_keywords_expanded(niche, max_words=3)
    else:
        kw_list = get_keywords_for_nicho(niche)

    if not kw_list:
        logger.error(f"No keywords for niche '{niche}'")
        return []

    logger.info(
        f"[count_agent] niche={niche} | {len(kw_list)} keywords "
        f"| country={country} | expand={expand}"
    )
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1280, "height": 900},
        )

        throttled_streak = 0  # consecutive keywords returning 100 (throttle signal)

        for i, keyword in enumerate(kw_list):
            # Space out requests to stay below FB's soft throttle threshold.
            if i > 0:
                await asyncio.sleep(inter_keyword_delay)
            try:
                data = await _count_keyword_sequential(context, keyword, country)

                # Throttle detection: if total == video == image == 100,
                # FB is serving the simplified "rate-limited" page.
                is_throttled = (
                    data["total"] == 100
                    and data["video_count"] == 100
                    and data["image_count"] == 100
                )
                if is_throttled:
                    throttled_streak += 1
                    logger.warning(
                        f"  [throttle] {keyword!r} → 100/100/100 "
                        f"(streak: {throttled_streak})"
                    )
                    if throttled_streak >= 3:
                        logger.warning(
                            "  [throttle] 3 consecutive throttled keywords — "
                            "waiting 90s for IP cooldown"
                        )
                        await asyncio.sleep(90)
                        throttled_streak = 0
                else:
                    throttled_streak = 0  # reset on a good result

                save_snapshot(
                    keyword=keyword,
                    niche=niche,
                    active_ad_count=data["total"],
                    top_pages=data["top_pages"],
                    video_count=data["video_count"],
                    image_count=data["image_count"],
                    country=country,
                    fb_library_url=data["fb_library_url"],
                )
                results.append(data)

                top_name = data["top_pages"][0]["page_name"] if data["top_pages"] else "-"
                top_cnt  = data["top_pages"][0]["ad_count"]  if data["top_pages"] else 0
                logger.info(
                    f"  {keyword!r:42s} "
                    f"total={data['total']:>5}  "
                    f"vid={data['video_count']:>4}  "
                    f"img={data['image_count']:>4}  "
                    f"| top: {top_name} ({top_cnt})"
                )
            except Exception as e:
                logger.error(f"  Error on '{keyword}': {e}")

        await browser.close()

    return results


def run_count_agent(
    niche: str,
    country: str = "US",
    keywords: list[str] = None,
    expand: bool = False,
    inter_keyword_delay: float = 15.0,
) -> list[dict]:
    return asyncio.run(
        run_count_agent_async(niche, country, keywords, expand, inter_keyword_delay)
    )


def print_count_report(results: list[dict]) -> None:
    if not results:
        print("No results.")
        return

    print(f"\n{'='*73}")
    print(f"  COUNT REPORT  {datetime.now().strftime('%Y-%m-%d %H:%M')}  (English ads, US)")
    print(f"  {'KEYWORD':<38} {'TOTAL':>6}  {'VIDEO':>5}  {'IMAGE':>5}")
    print(f"{'='*73}")

    for r in sorted(results, key=lambda x: x["total"], reverse=True):
        top_name = r["top_pages"][0]["page_name"] if r["top_pages"] else ""
        top_cnt  = r["top_pages"][0]["ad_count"]  if r["top_pages"] else 0
        print(
            f"  {r['keyword']:<38} "
            f"{r['total']:>6,}  "
            f"{r['video_count']:>5,}  "
            f"{r['image_count']:>5,}"
        )
        if top_name:
            print(f"    -> top: {top_name} ({top_cnt:,})")

    total_ads = sum(r["total"] for r in results)
    print(f"\n{'='*73}")
    print(f"  {len(results)} keywords | {total_ads:,} total active English ads")
    print(f"{'='*73}\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Agent 1: Count active ads per keyword")
    parser.add_argument("--niche", type=str, help="Niche name")
    parser.add_argument("--keyword", type=str, help="Single keyword")
    parser.add_argument("--all", action="store_true", help="Run all niches")
    parser.add_argument("--country", type=str, default="US")
    parser.add_argument(
        "--expand", action="store_true",
        help="Also search 3-word keyword variants (Gustavo method)"
    )
    parser.add_argument(
        "--delay", type=float, default=15.0,
        help="Seconds between keywords (default 15). Use 30+ if getting 100 counts"
    )
    args = parser.parse_args()

    init_db()

    keywords = [args.keyword] if args.keyword else None
    niches   = get_available_nichos() if args.all else ([args.niche] if args.niche else [])
    if not niches:
        print(f"Use --niche <name> or --all. Available: {get_available_nichos()}")
        sys.exit(1)

    all_results = []
    for niche in niches:
        all_results.extend(
            run_count_agent(
                niche, country=args.country,
                keywords=keywords, expand=args.expand,
                inter_keyword_delay=args.delay,
            )
        )

    print_count_report(all_results)
