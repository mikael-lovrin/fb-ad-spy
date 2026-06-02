# -*- coding: utf-8 -*-
"""
FB Ad Spy — Pipeline Orchestrator
===================================
Runs the 4 agents in sequence for a given niche/country:

  Stage 1 — count_agent:    keyword × type counts → keyword_snapshots
  Stage 2 — metadata_agent: individual ad nodes  → ads table
  Stage 3 — download_agent: media files          → data/media/
  Stage 4 — analyze_agent:  Claude analysis      → ads analysis fields

Each stage can be run standalone or skipped via flags.

Usage:
    # Full pipeline
    python pipeline.py --niche diabetes

    # Just count (trend tracking, no API costs)
    python pipeline.py --niche diabetes --count-only

    # Skip counting, run metadata + download + analyze
    python pipeline.py --niche diabetes --skip-count

    # All niches, counting only
    python pipeline.py --all --count-only

    # Run all 4 stages, but only for keywords with >= 50 ads
    python pipeline.py --niche weight_loss --min-ads 50
"""

import argparse
import io
import logging
import sys
from datetime import datetime

# Fix Windows console encoding
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from core.keywords import get_available_nichos
from storage.database import init_db, get_stats


def run_pipeline(
    niches: list[str],
    country: str = "US",
    count: int = 50,
    min_ads: int = 0,
    skip_count: bool = False,
    skip_metadata: bool = False,
    skip_download: bool = False,
    skip_analyze: bool = False,
) -> None:
    init_db()

    start = datetime.now()
    logger.info(f"Pipeline start | niches={niches} | country={country}")

    for niche in niches:
        logger.info(f"\n{'='*60}")
        logger.info(f"  NICHE: {niche.upper()}")
        logger.info(f"{'='*60}")

        # ------------------------------------------------------------------
        # Stage 1: Count
        # ------------------------------------------------------------------
        if not skip_count:
            logger.info("[Stage 1] Count agent — keyword ad counts")
            from agents.count_agent import run_count_agent, print_count_report
            results = run_count_agent(niche, country=country)
            print_count_report(results)
        else:
            logger.info("[Stage 1] Skipped")

        # ------------------------------------------------------------------
        # Stage 2: Metadata
        # ------------------------------------------------------------------
        if not skip_metadata:
            logger.info("[Stage 2] Metadata agent — individual ad nodes")
            from agents.metadata_agent import run_metadata_agent
            ads = run_metadata_agent(
                niche=niche,
                country=country,
                count=count,
                min_total_ads=min_ads,
            )
            logger.info(f"[Stage 2] Collected {len(ads)} ads")
        else:
            logger.info("[Stage 2] Skipped")

        # ------------------------------------------------------------------
        # Stage 3: Download
        # ------------------------------------------------------------------
        if not skip_download:
            logger.info("[Stage 3] Download agent — media files")
            from agents.download_agent import run_download_agent
            dl_stats = run_download_agent(limit=count * 2, niche=niche)
            logger.info(f"[Stage 3] {dl_stats}")
        else:
            logger.info("[Stage 3] Skipped")

        # ------------------------------------------------------------------
        # Stage 4: Analyze
        # ------------------------------------------------------------------
        if not skip_analyze:
            logger.info("[Stage 4] Analyze agent — Claude analysis")
            from agents.analyze_agent import run_analyze_agent
            an_stats = run_analyze_agent(limit=count, niche=niche)
            logger.info(f"[Stage 4] {an_stats}")
        else:
            logger.info("[Stage 4] Skipped")

    elapsed = (datetime.now() - start).seconds
    stats = get_stats()
    logger.info(f"\nPipeline complete in {elapsed}s")
    logger.info(f"DB: {stats['total']} total ads | {stats['active']} active | {stats['analyzed']} analyzed")


def main():
    parser = argparse.ArgumentParser(description="FB Ad Spy Pipeline")
    parser.add_argument("--niche", type=str, help=f"Niche: {get_available_nichos()}")
    parser.add_argument("--all", action="store_true", help="Run all niches")
    parser.add_argument("--country", type=str, default="US")
    parser.add_argument("--count", type=int, default=50, help="Ads per keyword (metadata stage)")
    parser.add_argument("--min-ads", type=int, default=0,
                        help="Skip keywords with fewer than N ads in last snapshot")

    # Stage flags
    parser.add_argument("--count-only", action="store_true", help="Run Stage 1 only")
    parser.add_argument("--skip-count", action="store_true", help="Skip Stage 1")
    parser.add_argument("--skip-metadata", action="store_true", help="Skip Stage 2")
    parser.add_argument("--skip-download", action="store_true", help="Skip Stage 3")
    parser.add_argument("--skip-analyze", action="store_true", help="Skip Stage 4")

    args = parser.parse_args()

    niches = get_available_nichos() if args.all else ([args.niche] if args.niche else [])
    if not niches:
        print(f"Use --niche <name> or --all. Available: {get_available_nichos()}")
        sys.exit(1)

    run_pipeline(
        niches=niches,
        country=args.country,
        count=args.count,
        min_ads=args.min_ads,
        skip_count=args.skip_count,
        skip_metadata=args.skip_metadata or args.count_only,
        skip_download=args.skip_download or args.count_only,
        skip_analyze=args.skip_analyze or args.count_only,
    )


if __name__ == "__main__":
    main()
