# -*- coding: utf-8 -*-
"""
Agent 2 — Metadata Agent
========================
Fetches individual ad metadata by scraping the FB Ad Library page HTML.

The ad data is server-side rendered into the page as a large
<script type="application/json"> tag (~391KB). This is more reliable than
intercepting GraphQL calls (which get rate-limited).

Confirmed structure:
  search_results_connection.count          — real total
  edges[].node.collated_results[]
    .ad_archive_id, .collation_count, .page_id
    .snapshot.page_name, .snapshot.body.text (copy)
    .snapshot.cta_text, .snapshot.videos[], .snapshot.images[]

Page version detection:
  Full page  ~2.2MB — has the 391KB script tag with ad data  → extracts ads
  Throttled  ~1.2MB — simplified page, no ad data script      → retries once

Usage:
    python -m agents.metadata_agent --niche diabetes --min-ads 5000
    python -m agents.metadata_agent --keyword "blood sugar trick" --count 50
"""

import argparse
import asyncio
import logging
import sys

from playwright.async_api import async_playwright

from core.html_parser import extract_ads_from_html
from core.keywords import get_keywords_for_nicho, get_available_nichos
from core.playwright_scraper import build_search_url
from storage.database import (
    init_db, bulk_upsert, get_latest_snapshots, update_snapshot_media_counts,
)

logger = logging.getLogger(__name__)

# A full (non-throttled) FB Ad Library page is ~2.2MB.
# If content is below this threshold the throttled version was served.
_FULL_PAGE_MIN_BYTES = 1_800_000


async def _load_page_with_retry(page, url: str, max_attempts: int = 2) -> str:
    """
    Load the FB Ad Library URL and return the page HTML.
    If the throttled (small) page is served, waits 60s and retries once.
    """
    for attempt in range(1, max_attempts + 1):
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

        # Wait for deferred SSR script tags to inject
        await page.wait_for_timeout(8_000)

        html = await page.content()
        size = len(html.encode("utf-8", errors="replace"))

        if size >= _FULL_PAGE_MIN_BYTES:
            logger.debug(f"  Full page served ({size/1e6:.1f}MB)")
            return html

        logger.warning(
            f"  Throttled page ({size/1e6:.1f}MB) on attempt {attempt}/{max_attempts}"
        )
        if attempt < max_attempts:
            logger.info("  Waiting 60s for throttle to clear...")
            await asyncio.sleep(60)
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

    return html  # return whatever we have after all attempts


async def _scrape_keyword_metadata(
    browser,
    keyword: str,
    country: str,
    count: int,
    scroll_pages: int = 4,
) -> tuple[int, list[dict]]:
    """
    Load FB Ad Library for one keyword and extract all ads from the page HTML.

    Uses a fresh browser context per keyword to avoid accumulated session state.
    Returns (total_available_count, ads_list).
    """
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
    page = await context.new_page()

    try:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    except ImportError:
        pass

    all_ads:  list[dict] = []
    seen_ids: set[str]   = set()
    total_count = 0
    url = build_search_url(keyword, country, media_type="all", language="en")

    try:
        html = await _load_page_with_retry(page, url)
        total, ads = extract_ads_from_html(html, keyword)
        total_count = total

        for ad in ads:
            aid = ad.get("ad_archive_id", "")
            if aid and aid not in seen_ids:
                seen_ids.add(aid)
                all_ads.append(ad)

        logger.info(
            f"  '{keyword}': {len(all_ads)} ads loaded "
            f"(total available: {total_count:,})"
        )

        # Scroll to load more result pages
        for scroll_n in range(scroll_pages):
            if len(all_ads) >= count:
                break
            prev = len(all_ads)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(3_000)

            html = await page.content()
            _, ads = extract_ads_from_html(html, keyword)
            for ad in ads:
                aid = ad.get("ad_archive_id", "")
                if aid and aid not in seen_ids:
                    seen_ids.add(aid)
                    all_ads.append(ad)

            new = len(all_ads) - prev
            logger.info(f"    Scroll {scroll_n + 1}: +{new} ads (total: {len(all_ads)})")
            if new == 0:
                break

    except Exception as e:
        logger.error(f"  Error scraping '{keyword}': {e}")
    finally:
        await page.close()
        await context.close()

    return total_count, all_ads[:count]


async def run_metadata_agent_async(
    niche: str = None,
    keywords: list[str] = None,
    country: str = "US",
    count: int = 50,
    min_total_ads: int = 0,
    inter_keyword_delay: float = 10.0,
) -> list[dict]:
    """
    Collect individual ad metadata for all keywords in a niche.

    Args:
        min_total_ads:        Only process keywords with >= N ads in last Stage 1 snapshot.
        inter_keyword_delay:  Seconds between keywords (allows throttle to reset).
    """
    if keywords:
        kw_list = keywords
    else:
        kw_list = get_keywords_for_nicho(niche or "")
        if not kw_list:
            logger.error(f"No keywords for niche '{niche}'")
            return []

    if min_total_ads > 0 and niche:
        snapshots = {
            s["keyword"]: s["active_ad_count"]
            for s in get_latest_snapshots(niche, country)
        }
        kw_list = [k for k in kw_list if snapshots.get(k, 0) >= min_total_ads]
        logger.info(
            f"  After min-ads filter (>={min_total_ads:,}): {len(kw_list)} keywords"
        )

    logger.info(f"[metadata_agent] {len(kw_list)} keywords | country={country}")
    all_ads: list[dict] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        for i, kw in enumerate(kw_list):
            if i > 0:
                await asyncio.sleep(inter_keyword_delay)

            total, ads = await _scrape_keyword_metadata(browser, kw, country, count)
            all_ads.extend(ads)

        await browser.close()

    if all_ads:
        stats = bulk_upsert(all_ads)
        logger.info(f"[metadata_agent] Saved: {stats}")

        # Update snapshot video/image counts from actual ad_type values
        seen_kw = {a.get("keyword_found", "") for a in all_ads if a.get("keyword_found")}
        for kw in seen_kw:
            try:
                update_snapshot_media_counts(kw, country)
            except Exception:
                pass

    return all_ads


def run_metadata_agent(
    niche: str = None,
    keywords: list[str] = None,
    country: str = "US",
    count: int = 50,
    min_total_ads: int = 0,
) -> list[dict]:
    return asyncio.run(
        run_metadata_agent_async(niche, keywords, country, count, min_total_ads)
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Agent 2: Scrape individual ad metadata")
    parser.add_argument("--niche", type=str)
    parser.add_argument("--keyword", type=str, help="Single keyword override")
    parser.add_argument("--count", type=int, default=50, help="Ads per keyword")
    parser.add_argument("--country", type=str, default="US")
    parser.add_argument(
        "--min-ads", type=int, default=0,
        help="Only process keywords with >= N ads in last Stage 1 snapshot",
    )
    args = parser.parse_args()

    init_db()

    keywords = [args.keyword] if args.keyword else None
    ads = run_metadata_agent(
        niche=args.niche,
        keywords=keywords,
        country=args.country,
        count=args.count,
        min_total_ads=args.min_ads,
    )

    print(f"\nMetadata agent: {len(ads)} ads saved.")
    for ad in ads[:5]:
        print(f"\n  [{ad.get('ad_type', '?')}] {ad.get('page_name')}")
        print(f"  Scale:    {ad.get('collation_count')} creatives")
        print(f"  Days:     {ad.get('days_running')}")
        print(f"  Copy:     {str(ad.get('ad_body', ''))[:100]}...")
