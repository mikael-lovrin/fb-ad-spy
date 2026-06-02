# -*- coding: utf-8 -*-
"""
Agent 3 — Download Agent
=========================
Downloads video and image files for ads that have remote URLs but no local file yet.
Saves to data/media/<ad_archive_id>.<ext> and updates the DB.

Runs after metadata_agent (which populates _image_url / _video_url fields).

Output: updates ads.image_url and ads.video_url to local file paths.

Usage:
    python -m agents.download_agent
    python -m agents.download_agent --limit 100 --niche diabetes
"""

import argparse
import logging
import sys
from pathlib import Path

from storage.database import init_db, get_conn, update_analysis
from storage.media_downloader import download_media

logger = logging.getLogger(__name__)


def get_ads_needing_download(limit: int = 200, niche: str = None) -> list[dict]:
    """Fetch ads that have a remote URL but no local file stored yet."""
    niche_clause = "AND industry LIKE ?" if niche else ""
    params = [limit]
    if niche:
        params = [f"%{niche}%", limit]

    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT ad_archive_id, image_url, video_url, industry
                FROM ads
                WHERE (
                    (video_url IS NOT NULL AND video_url != '' AND video_url NOT LIKE 'data/%')
                    OR
                    (image_url IS NOT NULL AND image_url != '' AND image_url NOT LIKE 'data/%')
                )
                {niche_clause}
                ORDER BY collation_count DESC NULLS LAST
                LIMIT ?""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def run_download_agent(limit: int = 200, niche: str = None) -> dict:
    """
    Download media for all ads with remote URLs.
    Returns stats dict.
    """
    ads = get_ads_needing_download(limit, niche)
    logger.info(f"[download_agent] {len(ads)} ads need media download")

    stats = {"downloaded_video": 0, "downloaded_image": 0, "failed": 0, "skipped": 0}

    for ad in ads:
        ad_id = ad["ad_archive_id"]
        updates = {}

        video_url = ad.get("video_url") or ""
        image_url = ad.get("image_url") or ""

        if video_url and not video_url.startswith("data/"):
            local = download_media(video_url, ad_id, "video")
            if local:
                updates["video_url"] = local
                stats["downloaded_video"] += 1
            else:
                stats["failed"] += 1

        if image_url and not image_url.startswith("data/"):
            local = download_media(image_url, ad_id, "image")
            if local:
                updates["image_url"] = local
                stats["downloaded_image"] += 1
            else:
                stats["failed"] += 1

        if not video_url and not image_url:
            stats["skipped"] += 1
            continue

        if updates:
            update_analysis(ad_id, updates)

    logger.info(
        f"[download_agent] Done — "
        f"videos: {stats['downloaded_video']} | "
        f"images: {stats['downloaded_image']} | "
        f"failed: {stats['failed']}"
    )
    return stats


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Agent 3: Download ad media files")
    parser.add_argument("--limit", type=int, default=200, help="Max ads to process")
    parser.add_argument("--niche", type=str, default=None, help="Filter by niche/industry")
    args = parser.parse_args()

    init_db()
    stats = run_download_agent(limit=args.limit, niche=args.niche)
    print(f"\nDownload agent complete: {stats}\n")
