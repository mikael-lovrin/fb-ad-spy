# -*- coding: utf-8 -*-
"""
FB Ad Library URL builders for Playwright-driven scraping.

The actual page scraping + parsing lives in agents/metadata_agent.py (browser
control) and core/html_parser.py (extracting ad data from the page's embedded
JSON script tag) — this module just builds the search/page URLs they load.

Earlier approach (superseded): intercepting internal GraphQL responses
directly. That worked for dynamic_filter_options but the ads response itself
got rate-limited (error code 1675004) — see docs/06.
"""

import logging
from urllib.parse import quote

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


def build_page_url(
    page_id: str,
    country: str = "US",
    media_type: str = "all",
    sort_mode: str = "total_impressions",
) -> str:
    """
    Build an FB Ad Library URL filtered to a single advertiser (view_all_page_id).

    Used to spy on one account's full active ad set directly, instead of a
    keyword search — avoids the 50k-result wall on saturated niches and targets
    the specific scale leaders identified by count_agent's top_pages.
    """
    params = [
        ("active_status", "active"),
        ("ad_type", "all"),
        ("country", country),
        ("is_targeted_country", "false"),
        ("media_type", media_type),
        ("view_all_page_id", page_id),
        ("sort_data[direction]", "desc"),
        ("sort_data[mode]", sort_mode),
    ]
    qs = "&".join(
        f"{k}={quote(str(v), safe='')}" for k, v in params
    )
    return FB_LIBRARY_BASE + "?" + qs
