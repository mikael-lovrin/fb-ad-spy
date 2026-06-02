# -*- coding: utf-8 -*-
"""
Keyword snapshot runner.
For each keyword: scrapes FB, counts active ads, identifies top advertisers,
saves a point-in-time row to keyword_snapshots for trend tracking.

Usage:
    python -m core.snapshot_runner --niche diabetes --country US
    python -m core.snapshot_runner --all --country US
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlencode

from core.keywords import get_keywords_for_nicho, get_available_nichos, KEYWORDS
from core.playwright_scraper import PlaywrightAdScraper, build_search_url
from storage.database import init_db, save_snapshot

logger = logging.getLogger(__name__)

FB_LIBRARY_BASE = "https://www.facebook.com/ads/library/"


def run_snapshot(niche: str, country: str = "US", ads_per_keyword: int = 100) -> list[dict]:
    """
    Scrape all keywords for a niche, save a snapshot per keyword.
    Returns list of snapshot dicts (keyword, count, top_pages).
    """
    keywords = get_keywords_for_nicho(niche)
    if not keywords:
        logger.error(f"Niche '{niche}' not found. Available: {get_available_nichos()}")
        return []

    logger.info(f"[snapshot] Niche: {niche} | {len(keywords)} keywords | country: {country}")
    scraper = PlaywrightAdScraper(headless=True)
    results = []

    for keyword in keywords:
        logger.info(f"[snapshot] Keyword: '{keyword}'")
        try:
            ads = scraper.search(
                keywords=[keyword],
                country=country,
                count=ads_per_keyword,
                dedup_by_page=False,  # count all ads, not just unique pages
            )

            active_count = sum(1 for a in ads if a.get("active_status") == "ACTIVE")

            # Aggregate top advertisers by page_id
            page_counts: dict[str, dict] = defaultdict(lambda: {"page_name": "", "ad_count": 0})
            for ad in ads:
                pid = ad.get("page_id") or ""
                if pid:
                    page_counts[pid]["page_name"] = ad.get("page_name") or pid
                    page_counts[pid]["ad_count"] += 1
                    # collation_count from the ad node is more accurate than our local count
                    if ad.get("collation_count"):
                        page_counts[pid]["collation_count"] = ad["collation_count"]

            top_pages = sorted(
                [{"page_id": pid, **info} for pid, info in page_counts.items()],
                key=lambda x: x.get("collation_count") or x["ad_count"],
                reverse=True,
            )[:10]

            fb_url = build_search_url(keyword, country)

            save_snapshot(
                keyword=keyword,
                niche=niche,
                active_ad_count=active_count,
                top_pages=top_pages,
                country=country,
                fb_library_url=fb_url,
            )

            result = {
                "keyword": keyword,
                "niche": niche,
                "active_ad_count": active_count,
                "top_advertiser": top_pages[0]["page_name"] if top_pages else "",
                "top_advertiser_ads": top_pages[0].get("collation_count") or (top_pages[0]["ad_count"] if top_pages else 0),
                "fb_library_url": fb_url,
                "snapshot_at": datetime.now().isoformat(),
            }
            results.append(result)
            logger.info(
                f"  -> {active_count} active ads | "
                f"top: {result['top_advertiser']} ({result['top_advertiser_ads']} creatives)"
            )

        except Exception as e:
            logger.error(f"[snapshot] Error on '{keyword}': {e}")

    return results


def print_snapshot_report(results: list[dict]) -> None:
    print(f"\n{'='*65}")
    print(f"  SNAPSHOT REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*65}")
    for r in sorted(results, key=lambda x: x["active_ad_count"], reverse=True):
        print(f"\n  Keyword:      {r['keyword']}")
        print(f"  Active Ads:   {r['active_ad_count']:,}")
        if r["top_advertiser"]:
            print(f"  Top Adv:      {r['top_advertiser']} ({r['top_advertiser_ads']:,} creatives)")
        print(f"  Link:         {r['fb_library_url']}")
    print(f"\n{'='*65}")
    print(f"  Total keywords: {len(results)} | "
          f"Total active ads: {sum(r['active_ad_count'] for r in results):,}")
    print(f"{'='*65}\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Keyword snapshot runner")
    parser.add_argument("--niche", type=str, help="Niche to snapshot")
    parser.add_argument("--all", action="store_true", help="Snapshot all niches")
    parser.add_argument("--country", type=str, default="US")
    parser.add_argument("--count", type=int, default=100, help="Ads per keyword")
    args = parser.parse_args()

    init_db()

    niches = get_available_nichos() if args.all else [args.niche]
    if not niches or niches == [None]:
        print(f"Specify --niche or --all. Available: {get_available_nichos()}")
        sys.exit(1)

    all_results = []
    for niche in niches:
        results = run_snapshot(niche, country=args.country, ads_per_keyword=args.count)
        all_results.extend(results)

    print_snapshot_report(all_results)
