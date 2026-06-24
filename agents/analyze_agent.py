# -*- coding: utf-8 -*-
"""
Agent 4 — Analyze Agent
========================
Runs Claude analysis on ads that have metadata but no analysis yet.

Strategy: download → analyze → delete media files.
Only the TEXT output (transcript, analysis, hook, swipe_score) is stored
permanently in the DB. Media files are temp and deleted immediately after.

Why not keep media files:
  - FB CDN URLs expire in 24-48h anyway
  - Videos are 50-200MB each — storage would fill up fast
  - The transcript + Claude analysis is all you need for a swipe file

Per ad:
  1. Copy analysis (Claude) — always, when ad_body exists
  2. Video: download temp → ffmpeg audio → Whisper transcript → Claude VSL analysis → delete
  3. Image: download temp → Claude Vision → delete
  4. Swipe score (0-100): composite signal

Reads: ads WHERE analyzed_at IS NULL
Writes: hook, pain_points, cta, transcript, analysis, swipe_score, analyzed_at

Usage:
    python -m agents.analyze_agent
    python -m agents.analyze_agent --limit 20
    python -m agents.analyze_agent --video-only
    python -m agents.analyze_agent --image-only
"""

import argparse
import logging
import sys
from pathlib import Path

from storage.database import init_db, get_conn, update_analysis
from analysis.text_analyzer import analyze_ad_copy, calculate_swipe_score

logger = logging.getLogger(__name__)


def get_unanalyzed_ads(
    limit: int = 50,
    niche: str = None,
    video_only: bool = False,
    image_only: bool = False,
    min_days: int = 0,
    min_collation: int = 0,
) -> list[dict]:
    """Return ads that have metadata but haven't been analyzed yet."""
    clauses = ["analyzed_at IS NULL"]
    params: list = []

    if niche:
        clauses.append("industry LIKE ?")
        params.append(f"%{niche}%")
    if video_only:
        clauses.append("ad_type = 'video'")
    if image_only:
        clauses.append("ad_type = 'image'")
    if min_days > 0:
        clauses.append("days_running >= ?")
        params.append(min_days)
    if min_collation > 0:
        clauses.append("collation_count >= ?")
        params.append(min_collation)

    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM ads WHERE {' AND '.join(clauses)} "
            f"ORDER BY collation_count DESC NULLS LAST, days_running DESC NULLS LAST "
            f"LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def _analyze_video(video_url: str, ad_text: str) -> tuple[str, str]:
    """
    Download video to temp, extract audio, transcribe, analyze, then delete.
    Returns (transcript, analysis). Media file is deleted regardless of outcome.
    """
    if not video_url:
        return "", ""

    import tempfile, os
    from pathlib import Path as P
    from analysis.video_analyzer import _download_video, _extract_audio, transcribe_audio, analyze_video_transcript

    # Use a real temp directory so cleanup is guaranteed
    tmp_dir = P(tempfile.gettempdir()) / "fb_ad_spy"
    tmp_dir.mkdir(exist_ok=True)

    vid_hash  = abs(hash(video_url))
    video_path = tmp_dir / f"video_{vid_hash}.mp4"
    audio_path = tmp_dir / f"audio_{vid_hash}.mp3"

    transcript = analysis = ""
    try:
        _download_video(video_url, video_path)
        _extract_audio(video_path, audio_path)
        transcript = transcribe_audio(audio_path)
        if transcript:
            analysis = analyze_video_transcript(transcript)
    except Exception as e:
        logger.error(f"  Video pipeline error: {e}")
        analysis = f"Error: {e}"
    finally:
        for p in [video_path, audio_path]:
            try:
                if p.exists():
                    p.unlink()
            except Exception:
                pass

    return transcript, analysis


def _analyze_image(image_url: str, ad_text: str) -> str:
    """
    Download image to temp, run Claude Vision, delete image.
    Returns analysis string.
    """
    if not image_url:
        return ""

    import tempfile, requests
    from pathlib import Path as P
    from analysis.image_analyzer import analyze_image_ad

    # If it's already a local path, use it directly (no temp needed)
    if image_url.startswith("data/"):
        return analyze_image_ad(image_url, ad_text)

    # Download to temp, analyze, delete
    tmp_dir = P(tempfile.gettempdir()) / "fb_ad_spy"
    tmp_dir.mkdir(exist_ok=True)
    img_hash = abs(hash(image_url))
    ext = image_url.split("?")[0].rsplit(".", 1)[-1].lower()
    ext = ext if ext in ("jpg", "jpeg", "png", "webp", "gif") else "jpg"
    img_path = tmp_dir / f"img_{img_hash}.{ext}"

    result = ""
    try:
        resp = requests.get(image_url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        img_path.write_bytes(resp.content)
        result = analyze_image_ad(str(img_path), ad_text)
    except Exception as e:
        logger.error(f"  Image pipeline error: {e}")
        result = f"Error: {e}"
    finally:
        try:
            if img_path.exists():
                img_path.unlink()
        except Exception:
            pass

    return result


def run_analyze_agent(
    limit: int = 50,
    niche: str = None,
    video_only: bool = False,
    image_only: bool = False,
    min_days: int = 0,
    min_collation: int = 0,
) -> dict:
    ads = get_unanalyzed_ads(limit, niche, video_only, image_only, min_days, min_collation)
    logger.info(f"[analyze_agent] {len(ads)} ads to analyze")

    stats = {"copy": 0, "video": 0, "image": 0, "errors": 0}

    for i, ad in enumerate(ads):
        ad_id   = ad.get("ad_archive_id", f"unknown_{i}")
        page    = ad.get("page_name", "?")
        ad_type = ad.get("ad_type", "unknown")
        logger.info(f"[{i+1}/{len(ads)}] {page} | type={ad_type} | days={ad.get('days_running')} | scale={ad.get('collation_count')}")

        analysis: dict = {}
        ad_text = ad.get("ad_body") or ""

        # 1. Copy analysis — always when body text exists
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

        # 2. Video: download temp → Whisper → Claude → delete
        video_url = ad.get("video_url") or ""
        if ad.get("ad_format") == "catalog":
            analysis["notes"] = (
                "Catalog/DPA ad (card_count="
                f"{ad.get('card_count')}) — Meta assembles the creative "
                "per-viewer from a product feed, so there is no single fixed "
                "creative to transcribe. Skipped video/image analysis; copy "
                "analysis above still applies."
            )
        elif video_url and ad_type != "image":
            analysis["ad_type"] = "video"
            transcript, video_analysis = _analyze_video(video_url, ad_text)
            if transcript:
                analysis["video_transcript"] = transcript
                analysis["video_analysis"]   = video_analysis
                logger.info(f"  Transcript: {len(transcript)} chars")
                stats["video"] += 1
            else:
                stats["errors"] += 1

        # 3. Image: download temp → Claude Vision → delete
        elif ad.get("image_url"):
            image_url = ad.get("image_url")
            analysis["ad_type"] = "image"
            img_analysis = _analyze_image(image_url, ad_text)
            if img_analysis and not img_analysis.startswith("Error:"):
                analysis["image_analysis"] = img_analysis
                stats["image"] += 1
            else:
                stats["errors"] += 1

        # 4. Swipe score
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
    parser.add_argument("--limit",       type=int, default=50)
    parser.add_argument("--niche",       type=str, default=None)
    parser.add_argument("--video-only",  action="store_true")
    parser.add_argument("--image-only",  action="store_true")
    parser.add_argument("--min-days",    type=int, default=0,  help="Min days running")
    parser.add_argument("--min-scale",   type=int, default=0,  help="Min collation_count")
    args = parser.parse_args()

    init_db()
    stats = run_analyze_agent(
        limit=args.limit, niche=args.niche,
        video_only=args.video_only, image_only=args.image_only,
        min_days=args.min_days, min_collation=args.min_scale,
    )
    print(f"\nAnalyze agent complete: {stats}\n")
