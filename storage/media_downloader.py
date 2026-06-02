# -*- coding: utf-8 -*-
"""
Persistent media download for ad creatives.
Saves images and videos to data/media/<ad_archive_id>.<ext>
Returns local file path so it can be stored in the DB.
"""

import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

MEDIA_DIR = Path("data/media")
TIMEOUT = 60  # seconds per download
CHUNK_SIZE = 8192


def _ext_from_url(url: str, fallback: str) -> str:
    path = url.split("?")[0].rstrip("/")
    suffix = Path(path).suffix.lower()
    return suffix if suffix in (".mp4", ".jpg", ".jpeg", ".png", ".webp", ".gif") else fallback


def download_media(url: str, ad_archive_id: str, media_type: str) -> str:
    """
    Download a remote media URL to disk.

    Args:
        url: Remote HTTP URL for the media.
        ad_archive_id: Used as the filename stem.
        media_type: 'video' or 'image'.

    Returns:
        Local file path string, or "" on failure.
    """
    if not url:
        return ""

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    fallback_ext = ".mp4" if media_type == "video" else ".jpg"
    ext = _ext_from_url(url, fallback_ext)
    dest = MEDIA_DIR / f"{ad_archive_id}{ext}"

    if dest.exists():
        logger.debug(f"[media] Already exists: {dest}")
        return str(dest)

    try:
        resp = requests.get(url, stream=True, timeout=TIMEOUT, headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        })
        resp.raise_for_status()

        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=CHUNK_SIZE):
                f.write(chunk)

        size_kb = dest.stat().st_size // 1024
        logger.info(f"[media] Downloaded {media_type}: {dest.name} ({size_kb} KB)")
        return str(dest)

    except Exception as e:
        logger.warning(f"[media] Failed to download {url[:60]}: {e}")
        if dest.exists():
            dest.unlink()
        return ""


def download_ad_media(ad: dict) -> dict:
    """
    Download image and/or video for an ad dict.
    Returns a dict with keys 'image_url' and 'video_url' set to local paths (or "").
    Skips download if local path already stored.
    """
    ad_id = ad.get("ad_archive_id", "unknown")
    result = {"image_url": ad.get("image_url") or "", "video_url": ad.get("video_url") or ""}

    raw_video = ad.get("_video_url") or ad.get("video_url") or ""
    raw_image = ad.get("_image_url") or ad.get("image_url") or ""

    # Don't re-download if already a local path
    if raw_video and not raw_video.startswith("data/"):
        local = download_media(raw_video, ad_id, "video")
        if local:
            result["video_url"] = local

    if raw_image and not raw_image.startswith("data/"):
        local = download_media(raw_image, ad_id, "image")
        if local:
            result["image_url"] = local

    return result
