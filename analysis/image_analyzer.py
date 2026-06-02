# -*- coding: utf-8 -*-
"""
Image ad analysis using Claude Vision.
Identifies DR creative patterns: visual hook, social proof elements, CTA design.
"""

import base64
import logging

import anthropic
import requests

from core.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def _fetch_image_as_base64(url: str) -> tuple[str, str]:
    """Download image and encode as base64. Returns (b64_data, media_type)."""
    resp = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "image/jpeg")
    if "png" in content_type:
        media_type = "image/png"
    elif "gif" in content_type:
        media_type = "image/gif"
    elif "webp" in content_type:
        media_type = "image/webp"
    else:
        media_type = "image/jpeg"

    b64 = base64.standard_b64encode(resp.content).decode("utf-8")
    return b64, media_type


def analyze_image_ad(image_url: str, ad_text: str = "") -> str:
    """
    Analyze a Facebook ad image with Claude Vision.

    Args:
        image_url: URL or local file path of the ad image.
        ad_text:   Optional ad copy text for additional context.

    Returns:
        String with the full creative analysis.
    """
    if not image_url:
        return ""

    # Handle local file paths
    if image_url.startswith("data/"):
        try:
            with open(image_url, "rb") as f:
                raw = f.read()
            ext = image_url.rsplit(".", 1)[-1].lower()
            type_map = {"png": "image/png", "gif": "image/gif", "webp": "image/webp"}
            media_type = type_map.get(ext, "image/jpeg")
            b64_data = base64.standard_b64encode(raw).decode("utf-8")
        except Exception as e:
            logger.error(f"Failed to read local image {image_url}: {e}")
            return f"Error reading image: {e}"
    else:
        try:
            b64_data, media_type = _fetch_image_as_base64(image_url)
        except Exception as e:
            logger.error(f"Failed to download image {image_url}: {e}")
            return f"Error downloading image: {e}"

    prompt = """You are a direct response marketing expert analyzing a Facebook ad creative.
Describe in paragraphs (no bullet points):

1. Visual elements and layout: colors, fonts, person/product images
2. Text visible in the image (reproduce exactly if legible)
3. CTA elements: buttons, arrows, highlighted text
4. Psychological triggers: urgency, social proof, authority, scarcity
5. Emotional angle: what pain or desire does this visual address?
6. Likely funnel type this creative opens (VSL, quiz, advertorial)
7. Overall assessment: does this look like a scaled DR ad? Why?

Be specific and detailed."""

    content = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64_data},
        },
        {"type": "text", "text": prompt},
    ]

    if ad_text:
        content.append({
            "type": "text",
            "text": f"\nAd copy for context:\n{ad_text}",
        })

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": content}],
        )
        return response.content[0].text

    except Exception as e:
        logger.error(f"Image analysis error: {e}")
        return f"Error: {e}"
