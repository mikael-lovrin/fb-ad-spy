# -*- coding: utf-8 -*-
"""
FB Ad Spy — main pipeline
Usage:
    python main.py --niche weight_loss --count 50
    python main.py --niche diabetes --count 100 --country US
    python main.py --collect-only --niche ed
    python main.py --analyze-only
    python main.py --test-token
    python main.py --use-playwright --niche diabetes --count 10
"""

import argparse
import io
import logging
import sys
from datetime import datetime

from core.config import FB_ACCESS_TOKEN, APIFY_ACTOR_URL
from core.keywords import get_keywords_for_nicho, get_available_nichos
from storage.database import init_db, bulk_upsert, get_unanalyzed_ads, update_analysis, get_stats
from analysis.text_analyzer import analyze_ad_copy, calculate_swipe_score

# Fix Windows console encoding (avoids UnicodeEncodeError on special chars)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("fb_ad_spy.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def collect_ads(
    nicho: str,
    count: int,
    country: str,
    use_apify: bool = False,
    use_playwright: bool = False,
) -> list[dict]:
    """
    Collect ads using Playwright (default), FB Graph API, or Apify.
    Priority: Playwright > FB API (if token) > Apify
    """
    keywords = get_keywords_for_nicho(nicho)
    if not keywords:
        logger.error(f"Niche '{nicho}' not found. Available: {get_available_nichos()}")
        return []

    logger.info(
        f"Starting collection | niche: {nicho} | {len(keywords)} keywords "
        f"| count: {count} | country: {country}"
    )

    if use_playwright or (not FB_ACCESS_TOKEN and not use_apify):
        logger.info("Using Playwright scraper (free, no API key needed)...")
        from core.playwright_scraper import PlaywrightAdScraper
        scraper = PlaywrightAdScraper(headless=True)
        normalized = scraper.search(keywords=keywords, country=country, count=count)

    elif use_apify:
        logger.info("Using Apify scraper...")
        from core.apify_scraper import ApifyScraper
        scraper = ApifyScraper()
        raw_ads = scraper.search(keywords=keywords, country=country, count=count)
        normalized = [ApifyScraper.normalize_ad(ad) for ad in raw_ads]

    else:
        from core.fb_api import FacebookAdLibraryAPI
        client = FacebookAdLibraryAPI()
        raw_ads = client.search(keywords=keywords, country=country, count=count)
        normalized = [FacebookAdLibraryAPI.normalize_ad(ad) for ad in raw_ads]

    logger.info(f"Coletados: {len(normalized)} anúncios")
    return normalized


def analyze_ads(ads: list[dict] = None, batch_size: int = 50) -> None:
    """
    Download media + analyze with Claude (copy, image, video).
    If ads=None, fetches unanalyzed ads from the DB.
    """
    from storage.media_downloader import download_ad_media

    if ads is None:
        ads = get_unanalyzed_ads(limit=batch_size)
        logger.info(f"Analyzing {len(ads)} ads from DB...")
    else:
        logger.info(f"Analyzing {len(ads)} freshly collected ads...")

    for i, ad in enumerate(ads):
        ad_id = ad.get("ad_archive_id", f"ad_{i}")
        logger.info(f"[{i+1}/{len(ads)}] {ad_id} | page: {ad.get('page_name', '?')}")

        analysis = {}

        # Download media to local disk first
        media = download_ad_media(ad)
        if media["video_url"] or media["image_url"]:
            analysis.update(media)

        # Use local paths if available, else fall back to remote URLs
        video_url = media["video_url"] or ad.get("_video_url") or ""
        image_url = media["image_url"] or ad.get("_image_url") or ""

        # Copy analysis (always, when body text exists)
        ad_text = ad.get("ad_body", "")
        if ad_text:
            try:
                copy_result = analyze_ad_copy(ad_text)
                analysis.update({
                    "industry": copy_result.get("industry"),
                    "hook": copy_result.get("hook"),
                    "text_summary": copy_result.get("summary"),
                    "pain_points": copy_result.get("pain_points"),
                    "benefits": copy_result.get("benefits"),
                    "cta": copy_result.get("cta"),
                    "format": copy_result.get("format"),
                })
            except Exception as e:
                logger.error(f"Copy analysis failed for {ad_id}: {e}")

        # Video: download -> ffmpeg -> Whisper -> Claude
        if video_url:
            analysis["ad_type"] = "video"
            try:
                from analysis.video_analyzer import analyze_video_ad
                transcript, video_analysis = analyze_video_ad(video_url, ad_text)
                analysis["video_transcript"] = transcript
                analysis["video_analysis"] = video_analysis
                logger.info(f"  Video transcript: {len(transcript)} chars")
            except Exception as e:
                logger.error(f"Video analysis failed for {ad_id}: {e}")
                analysis["video_analysis"] = f"Error: {e}"

        # Static image: Claude Vision
        elif image_url:
            analysis["ad_type"] = "image"
            try:
                from analysis.image_analyzer import analyze_image_ad
                analysis["image_analysis"] = analyze_image_ad(image_url, ad_text)
            except Exception as e:
                logger.error(f"Image analysis failed for {ad_id}: {e}")
                analysis["image_analysis"] = f"Error: {e}"

        # Swipe score
        merged = {**ad, **analysis}
        analysis["swipe_score"] = calculate_swipe_score(merged)

        update_analysis(ad_id, analysis)

    logger.info(f"Analysis complete. Processed {len(ads)} ads.")


def export_csv(output_path: str = "analyzed_ads.csv") -> None:
    """Exporta todos os anúncios analisados para CSV."""
    import csv
    from storage.database import query_ads

    ads = query_ads(limit=10000)
    if not ads:
        logger.warning("Nenhum anúncio para exportar.")
        return

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ads[0].keys())
        writer.writeheader()
        writer.writerows(ads)

    logger.info(f"Exportado: {output_path} ({len(ads)} anúncios)")


def main():
    parser = argparse.ArgumentParser(description="FB Ad Spy")
    parser.add_argument("--niche", "--nicho", type=str, default="diabetes",
                        help=f"Niche to search. Available: {get_available_nichos()}")
    parser.add_argument("--count", type=int, default=50,
                        help="Number of ads to collect")
    parser.add_argument("--country", type=str, default="US",
                        help="Country code (US, BR, ALL)")
    parser.add_argument("--collect-only", action="store_true",
                        help="Collect only, skip analysis")
    parser.add_argument("--analyze-only", action="store_true",
                        help="Analyze unprocessed ads in DB only")
    parser.add_argument("--use-apify", action="store_true",
                        help="Force Apify scraper")
    parser.add_argument("--use-playwright", action="store_true",
                        help="Force Playwright scraper (default when no FB token)")
    parser.add_argument("--export-csv", action="store_true",
                        help="Export DB to CSV after run")
    parser.add_argument("--test-token", action="store_true",
                        help="Test FB API token and exit")
    parser.add_argument("--stats", action="store_true",
                        help="Show DB statistics and exit")
    parser.add_argument("--snapshot", action="store_true",
                        help="Run keyword snapshot (count active ads per keyword, save trend data)")
    parser.add_argument("--snapshot-all", action="store_true",
                        help="Run snapshot for all niches")
    args = parser.parse_args()

    init_db()

    if args.test_token:
        from core.fb_api import test_token
        ok = test_token()
        sys.exit(0 if ok else 1)

    if args.stats:
        stats = get_stats()
        print("\nDB Statistics:")
        print(f"  Total ads:    {stats['total']}")
        print(f"  Active:       {stats['active']}")
        print(f"  Analyzed:     {stats['analyzed']}")
        print("\n  By industry:")
        for row in stats["by_industry"]:
            print(f"    {row['industry']}: {row['n']}")
        sys.exit(0)

    if args.snapshot or args.snapshot_all:
        from core.snapshot_runner import run_snapshot, print_snapshot_report
        niches = get_available_nichos() if args.snapshot_all else [args.niche]
        all_results = []
        for niche in niches:
            results = run_snapshot(niche, country=args.country, ads_per_keyword=args.count)
            all_results.extend(results)
        print_snapshot_report(all_results)
        sys.exit(0)

    if args.analyze_only:
        analyze_ads()
    else:
        ads = collect_ads(
            args.niche, args.count, args.country,
            use_apify=args.use_apify,
            use_playwright=args.use_playwright,
        )
        if ads:
            db_stats = bulk_upsert(ads)
            logger.info(f"Saved to DB: {db_stats}")

            if not args.collect_only:
                analyze_ads(ads)

    if args.export_csv:
        export_csv()

    logger.info("Pipeline complete.")


if __name__ == "__main__":
    main()
