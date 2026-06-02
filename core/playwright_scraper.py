# -*- coding: utf-8 -*-
"""
FB Ad Library scraper using Playwright.
Strategy: intercept internal GraphQL responses — structured JSON without API key.

GraphQL path confirmed: data.ad_library_main.search_results_connection.edges[].node
Scale signal captured from: data.ad_library_main.dynamic_filter_options.pages
"""

import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright, Response

logger = logging.getLogger(__name__)

FB_LIBRARY_BASE = "https://www.facebook.com/ads/library/"


def build_search_url(
    keyword: str,
    country: str = "US",
    media_type: str = "all",
    language: str = "en",
    sort_mode: str = "total_impressions",
) -> str:
    """
    Build an FB Ad Library search URL using keyword_unordered search with
    impression-sorted results and English language filter.

    keyword_unordered finds far more results than keyword_exact_phrase because
    FB matches any ad whose transcript/copy contains ALL the given words in any
    order — the same technique used in the Gustavo Rafaell benchmark process.

    sort_data uses literal brackets to match the format FB expects (not URL-encoded).
    """
    params = [
        ("active_status", "active"),
        ("ad_type", "all"),
        ("content_languages[0]", language),
        ("country", country),
        ("is_targeted_country", "false"),
        ("media_type", media_type),
        ("q", keyword),
        ("search_type", "keyword_unordered"),
        ("sort_data[direction]", "desc"),
        ("sort_data[mode]", sort_mode),
    ]
    # Build manually to keep literal brackets in sort_data keys (FB rejects %5B%5D)
    qs = "&".join(
        f"{k}={quote(str(v), safe='')}" for k, v in params
    )
    return FB_LIBRARY_BASE + "?" + qs


class PlaywrightAdScraper:
    """
    Scrapes the Facebook Ad Library by controlling a real Chromium browser.

    Usage:
        scraper = PlaywrightAdScraper(headless=True)
        ads = scraper.search(keywords=["blood sugar trick"], country="US", count=20)
    """

    def __init__(self, headless: bool = True, debug: bool = False):
        self.headless = headless
        self.debug = debug  # saves raw GraphQL JSON to data/tmp/ when True

    def search(
        self,
        keywords: list[str],
        country: str = "US",
        count: int = 50,
        active_status: str = "active",
        dedup_by_page: bool = True,
    ) -> list[dict]:
        """Collect ads for a list of keywords. Returns normalized ad dicts."""
        return asyncio.run(
            self._search_async(keywords, country, count, active_status, dedup_by_page)
        )

    async def _search_async(
        self, keywords, country, count, active_status, dedup_by_page
    ) -> list[dict]:
        all_ads: dict[str, dict] = {}
        seen_pages: set[str] = set()

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
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

            for keyword in keywords:
                if len(all_ads) >= count:
                    break

                url = build_search_url(keyword, country, active_status)
                logger.info(f"[Playwright] Searching: '{keyword}' | country: {country}")

                try:
                    ads = await self._scrape_keyword(
                        context, url, keyword, count - len(all_ads)
                    )
                    for ad in ads:
                        ad_id = ad.get("ad_archive_id", "")
                        page_id = str(ad.get("page_id", ""))

                        if not ad_id or ad_id in all_ads:
                            continue
                        if dedup_by_page and page_id and page_id in seen_pages:
                            continue

                        all_ads[ad_id] = ad
                        if page_id:
                            seen_pages.add(page_id)

                    logger.info(f"  -> {len(ads)} ads captured for '{keyword}'")

                except Exception as e:
                    logger.error(f"[Playwright] Error on '{keyword}': {e}")

            await browser.close()

        logger.info(f"[Playwright] Total unique ads: {len(all_ads)}")
        return list(all_ads.values())

    async def _scrape_keyword(self, context, url: str, keyword: str, want: int) -> list[dict]:
        page = await context.new_page()
        captured: list[dict] = []
        raw_responses: list[dict] = []

        async def on_response(response: Response):
            if "facebook.com/api/graphql" not in response.url:
                return
            if response.status != 200:
                return
            try:
                text = await response.text()
                text = re.sub(r"^for\s*\(;;\s*\)\s*;", "", text.strip())
                data = json.loads(text)

                if self.debug:
                    raw_responses.append(data)

                ads = _extract_ads_from_graphql(data, keyword)
                if ads:
                    captured.extend(ads)
                    logger.debug(f"  [intercept] +{len(ads)} ads from GraphQL")
                else:
                    # Log what keys we got so we can diagnose misses
                    top_keys = list((data.get("data") or {}).keys())
                    if top_keys:
                        logger.debug(f"  [intercept] No ads — data keys: {top_keys}")

            except (json.JSONDecodeError, Exception):
                pass

        page.on("response", on_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            for selector in [
                '[data-testid="cookie-policy-manage-dialog-accept-button"]',
                'div[aria-label="Allow all cookies"]',
                'button:has-text("Allow all cookies")',
                'button:has-text("Accept all")',
            ]:
                try:
                    await page.click(selector, timeout=2_000)
                    break
                except Exception:
                    pass

            await page.wait_for_timeout(4_000)

            max_scrolls = max(6, (want // 5) + 3)
            for i in range(max_scrolls):
                if len(captured) >= want:
                    break
                prev = len(captured)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2_500)
                if len(captured) == prev and i > 3:
                    break

            if not captured:
                logger.warning("[Playwright] GraphQL yielded no ads — trying DOM fallback")
                captured = await _scrape_dom_fallback(page, keyword)

        finally:
            if self.debug and raw_responses:
                Path("data/tmp").mkdir(parents=True, exist_ok=True)
                fname = f"data/tmp/graphql_{keyword[:20].replace(' ', '_')}.json"
                with open(fname, "w", encoding="utf-8") as f:
                    json.dump(raw_responses, f, ensure_ascii=False, indent=2, default=str)
                logger.info(f"[debug] Raw GraphQL saved: {fname}")

            await page.close()

        return captured[:want]


# ------------------------------------------------------------------
# GraphQL parser — explicit path + generic walk fallback
# ------------------------------------------------------------------

def _extract_ads_from_graphql(data: dict, keyword: str) -> list[dict]:
    """
    Extract ads from a FB GraphQL response.
    Tries the known explicit path first, falls back to generic walk.
    """
    ads: list[dict] = []

    # Primary path: data.ad_library_main.search_results_connection.edges
    ad_lib = (data.get("data") or {}).get("ad_library_main") or {}
    conn = ad_lib.get("search_results_connection") or {}
    edges = conn.get("edges") or []

    if edges:
        for edge in edges:
            node = edge.get("node") or {}
            ad = _parse_ad_node(node, keyword)
            if ad:
                ads.append(ad)
        return ads

    # Fallback: walk entire response looking for ad_archive_id nodes
    def walk(obj, depth: int = 0):
        if depth > 12:
            return
        if isinstance(obj, dict):
            if "ad_archive_id" in obj:
                ad = _parse_ad_node(obj, keyword)
                if ad:
                    ads.append(ad)
                return
            for v in obj.values():
                walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                walk(item, depth + 1)

    walk(data)
    return ads


def _parse_ad_node(node: dict, keyword: str) -> dict | None:
    """Normalize a raw GraphQL ad node to our internal schema."""
    ad_archive_id = str(node.get("ad_archive_id") or "")
    if not ad_archive_id:
        return None

    snapshot = node.get("snapshot") or {}
    body_obj = snapshot.get("body") or {}

    # Body text: snapshot.body.text preferred, fallback to ad_creative_bodies
    body_text = (
        body_obj.get("text")
        or " | ".join(node.get("ad_creative_bodies") or [])
        or ""
    )

    # Title
    titles = node.get("ad_creative_link_titles") or []
    title_text = " | ".join(titles) if isinstance(titles, list) else str(titles)

    # Dates
    start_ts = node.get("start_date") or node.get("ad_delivery_start_time")
    stop_ts = node.get("end_date") or node.get("ad_delivery_stop_time")
    start_date = stop_date = ""
    days_running = None

    if start_ts:
        try:
            start_dt = (
                datetime.fromtimestamp(int(start_ts))
                if isinstance(start_ts, (int, float))
                else datetime.fromisoformat(str(start_ts).replace("Z", "+00:00"))
            )
            start_date = start_dt.isoformat()
            end_dt = datetime.now()

            if stop_ts:
                end_dt = (
                    datetime.fromtimestamp(int(stop_ts))
                    if isinstance(stop_ts, (int, float))
                    else datetime.fromisoformat(str(stop_ts).replace("Z", "+00:00"))
                )
                stop_date = end_dt.isoformat()

            days_running = max(0, (end_dt.replace(tzinfo=None) - start_dt.replace(tzinfo=None)).days)
        except Exception:
            pass

    # Media URLs — check snapshot.videos and snapshot.images first, then cards
    image_url = video_url = ""

    for vid in snapshot.get("videos") or []:
        if not video_url:
            video_url = (
                vid.get("video_hd_url")
                or vid.get("video_sd_url")
                or vid.get("watermarked_video_hd_url")
                or ""
            )

    for img in snapshot.get("images") or []:
        if not image_url:
            image_url = (
                img.get("original_image_url")
                or img.get("resized_image_url")
                or ""
            )

    # Fallback: cards array (older API structure)
    if not video_url and not image_url:
        for card in node.get("cards") or []:
            if not video_url:
                video_url = card.get("video_hd_url") or card.get("video_sd_url") or ""
            if not image_url:
                image_url = card.get("original_image_url") or card.get("resized_image_url") or ""

    link_url = snapshot.get("link_url") or node.get("ad_creative_link_url") or ""
    cta_text = snapshot.get("cta_text") or ""

    return {
        "ad_archive_id": ad_archive_id,
        "page_id": str(node.get("page_id") or ""),
        "page_name": node.get("page_name") or "",
        "ad_snapshot_url": node.get("ad_snapshot_url") or "",
        "ad_body": body_text,
        "ad_title": title_text,
        "ad_description": cta_text,
        "ad_link_url": link_url,
        "start_date": start_date,
        "stop_date": stop_date,
        "days_running": days_running,
        "active_status": "ACTIVE" if not stop_ts else "INACTIVE",
        "collation_count": node.get("collation_count"),
        "impressions_min": None,
        "impressions_max": None,
        "spend_min": None,
        "spend_max": None,
        "currency": None,
        "publisher_platforms": node.get("publisher_platforms") or node.get("publisher_platform") or [],
        "keyword_found": keyword,
        "collected_at": datetime.now().isoformat(),
        "_image_url": image_url,
        "_video_url": video_url,
        "ad_type": None,
        "industry": None,
        "hook": None,
        "text_summary": None,
        "image_analysis": None,
        "video_transcript": None,
        "video_analysis": None,
        "swipe_score": None,
    }


# ------------------------------------------------------------------
# DOM fallback
# ------------------------------------------------------------------

async def _scrape_dom_fallback(page, keyword: str) -> list[dict]:
    """Last-resort: take a screenshot for debugging, return empty list."""
    Path("data/tmp").mkdir(parents=True, exist_ok=True)
    try:
        path = f"data/tmp/debug_{keyword[:20].replace(' ', '_')}.png"
        await page.screenshot(path=path, full_page=False)
        logger.info(f"[DOM fallback] Screenshot saved: {path}")
        content = await page.inner_text("body")
        logger.info(f"[DOM fallback] Page text (first 300): {content[:300]}")
    except Exception as e:
        logger.error(f"[DOM fallback] Error: {e}")
    return []
