# -*- coding: utf-8 -*-
"""
Ad copy analysis using Claude (Anthropic).
Extracts DR-relevant signals: hook, pain points, CTA, funnel format, swipe score.
"""

import json
import logging

import anthropic

from core.config import ANTHROPIC_API_KEY, CLAUDE_MODEL

logger = logging.getLogger(__name__)
_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def analyze_ad_copy(text: str) -> dict:
    """
    Analyze ad copy text and extract direct-response signals.

    Returns a dict with keys:
        industry, hook, summary, pain_points, benefits, cta, format
    """
    if not text or not text.strip():
        return {k: "" for k in ["industry", "hook", "summary", "pain_points", "benefits", "cta", "format"]}

    prompt = f"""You are a direct response marketing expert.
Analyze this ad copy and extract the fields below.

Respond ONLY with the JSON object — no extra text or markdown:

{{
  "industry": "exact niche (e.g. weight loss, diabetes, erectile dysfunction, back pain, vision, relationship)",
  "hook": "the opening phrase or element that grabs attention",
  "summary": "2-3 sentence summary of the ad's core promise",
  "pain_points": "lead pains addressed, semicolon-separated",
  "benefits": "main benefits and promises, semicolon-separated",
  "cta": "call to action (e.g. click here, watch the video, discover now)",
  "format": "likely funnel format (VSL, quiz, sales letter, advertorial, catalog)"
}}

Ad copy:
{text}"""

    try:
        response = _get_client().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)

    except Exception as e:
        logger.error(f"Copy analysis error: {e}")
        return {
            "industry": "",
            "hook": "",
            "summary": f"Error: {e}",
            "pain_points": "",
            "benefits": "",
            "cta": "",
            "format": "",
        }


# DR niches — used by swipe score to identify high-value verticals
_DR_NICHES = {
    "weight loss", "diabetes", "erectile dysfunction", "ed",
    "back pain", "vision", "relationship", "cholesterol",
    "joint pain", "prostate",
}


def calculate_swipe_score(ad_data: dict) -> int:
    """
    Score 0-100 indicating how worth swiping an ad is.

    Criteria (based on Gustavo Rafaell's qualification method):
      - Days running:       long-running = market-validated (max 40 pts)
      - Impression volume:  large reach = budget confidence (max 30 pts)
      - Clear hook:         hook present = swipe-worthy creative (15 pts)
      - Known DR niche:     high-value vertical (15 pts)
    """
    score = 0

    days = ad_data.get("days_running") or 0
    if days >= 90:
        score += 40
    elif days >= 30:
        score += 25
    elif days >= 14:
        score += 15
    elif days >= 7:
        score += 5

    try:
        imp_max = int(
            str(ad_data.get("impressions_max") or 0)
            .replace(",", "")
            .replace("k", "000")
            .replace("K", "000")
        )
    except Exception:
        imp_max = 0

    if imp_max >= 1_000_000:
        score += 30
    elif imp_max >= 100_000:
        score += 20
    elif imp_max >= 10_000:
        score += 10

    if ad_data.get("hook"):
        score += 15

    industry = (ad_data.get("industry") or "").lower()
    if any(n in industry for n in _DR_NICHES):
        score += 15

    return min(score, 100)
