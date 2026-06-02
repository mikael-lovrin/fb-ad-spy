# -*- coding: utf-8 -*-
"""
Agent 4 — Analyze Agent
========================
Runs Claude analysis on ads that have been downloaded but not yet analyzed.

Per ad:
  - Copy analysis (always, when ad_body exists): industry, hook, pain points, CTA
  - Video ads: ffmpeg audio extraction → Whisper transcription → Claude VSL analysis
  - Image ads: Claude Vision → creative analysis
  - Swipe score (0–100): composite signal for swipe worthiness

Reads from ads WHERE analyzed_at IS NULL.
Writes back: all analysis fields + analyzed_at timestamp.

Usage:
    python -m agents.analyze_agent
    python -m agents.analyze_agent --limit 20 --niche diabetes
    python -m agents.analyze_agent --video-only
    python -m agents.analyze_agent --image-only
"""

import argparse
import logging
import sys

from storage.database import init_db, get_conn, update_analysis
from analysis.text_analyzer import analyze_ad_copy, calculate_swipe_score

logger = logging.getLogger(__name__)


def get_unanalyzed_ads(
    limit: int = 50,
    niche: str = None,
    video_only: bool = False,
    image_only: bool = False,
) -> list[dict]:
    clauses = ["analyzed_at IS NULL"]
    params: list = []

    if niche:
        clauses.append("industry LIKE ?")
        params.append(f"%{niche}%")
    if video_only:
        clauses.append("(video_url IS NOT NULL AND video_url != '')")
    if image_only:
        clauses.append("(image_url IS NOT NULL AND image_url != '') AND (video_url IS NULL OR video_url = '')")

    where = "WHERE " + " AND ".join(clauses)
    params.append(limit)

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM ads {where} ORDER BY collation_count DESC NULLS LAST LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def run_analyze_agent(
    limit: int = 50,
    niche: str = None,
    video_only: bool = False,
    image_only: bool = False,
) -> dict:
    ads = get_unanalyzed_ads(limit, niche, video_only, image_only)
    logger.info(f"[analyze_agent] {len(ads)} ads to analyze")

    stats = {"copy": 0, "video": 0, "image": 0, "errors": 0}

    for i, ad in enumerate(ads):
        ad_id = ad.get("ad_archive_id", f"unknown_{i}")
        page = ad.get("page_name", "?")
        logger.info(f"[{i+1}/{len(ads)}] {ad_id} | {page}")

        analysis: dict = {}

        # --- Copy analysis ---
        ad_text = ad.get("ad_body") or ""
        if ad_text.strip():
            try:
                result = analyze_ad_copy(ad_text)
                analysis.update({
                    "industry":     result.get("industry"),
                    "hook":         result.get("hook"),
                    "text_summary": result.get("summary"),
                    "pain_points":  result.get("pain_points"),
                    "benefits":     result.get("benefits"),
                    "cta":          result.get("cta"),
                    "format":       result.get("format"),
                })
                stats["copy"] += 1
            except Exception as e:
                logger.error(f"  Copy analysis error: {e}")
                stats["errors"] += 1

        # --- Video: Whisper + Claude VSL analysis ---
        video_path = ad.get("video_url") or ""
        if video_path:
            analysis["ad_type"] = "video"
            try:
                from analysis.video_analyzer import analyze_video_ad
                transcript, video_analysis = analyze_video_ad(video_path, ad_text)
                analysis["video_transcript"] = transcript
                analysis["video_analysis"] = video_analysis
                logger.info(f"  Transcript: {len(transcript)} chars")
                stats["video"] += 1
            except Exception as e:
                logger.error(f"  Video analysis error: {e}")
                analysis["video_analysis"] = f"Error: {e}"
                stats["errors"] += 1

        # --- Image: Claude Vision ---
        elif ad.get("image_url"):
            analysis["ad_type"] = "image"
            try:
                from analysis.image_analyzer import analyze_image_ad
                analysis["image_analysis"] = analyze_image_ad(ad["image_url"], ad_text)
                stats["image"] += 1
            except Exception as e:
                logger.error(f"  Image analysis error: {e}")
                analysis["image_analysis"] = f"Error: {e}"
                stats["errors"] += 1

        # --- Swipe score ---
        merged = {**ad, **analysis}
        analysis["swipe_score"] = calculate_swipe_score(merged)

        update_analysis(ad_id, analysis)

    logger.info(
        f"[analyze_agent] Done — "
        f"copy: {stats['copy']} | video: {stats['video']} | "
        f"image: {stats['image']} | errors: {stats['errors']}"
    )
    return stats


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Agent 4: Analyze ads with Claude")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--niche", type=str, default=None)
    parser.add_argument("--video-only", action="store_true")
    parser.add_argument("--image-only", action="store_true")
    args = parser.parse_args()

    init_db()
    stats = run_analyze_agent(
        limit=args.limit,
        niche=args.niche,
        video_only=args.video_only,
        image_only=args.image_only,
    )
    print(f"\nAnalyze agent complete: {stats}\n")
