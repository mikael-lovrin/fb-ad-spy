# -*- coding: utf-8 -*-
"""
FB Ad Library HTML parser.

Extracts ad data from the server-side rendered page HTML.
FB embeds the full search_results_connection inside a large
<script type="application/json"> tag as a nested __bbox JSON blob.

Confirmed structure:
  script.json → require[0][3][0].__bbox.require[0][2][1].__bbox.result.data
                .ad_library_main.search_results_connection
                .count   (total result count)
                .edges[] .node.collated_results[]
                          .ad_archive_id
                          .collation_count   (scale signal)
                          .is_active
                          .page_id
                          .snapshot.page_name
                          .snapshot.body.text   (ad copy)
                          .snapshot.cta_text
                          .snapshot.cards[]     (media)
                          .snapshot.videos[]
                          .snapshot.images[]
"""

import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


def _walk_for_search_results(obj, depth=0):
    """
    Recursively walk a parsed JSON object to find search_results_connection.
    Returns the dict or None.
    """
    if depth > 20:
        return None
    if isinstance(obj, dict):
        if "search_results_connection" in obj:
            return obj["search_results_connection"]
        for v in obj.values():
            result = _walk_for_search_results(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _walk_for_search_results(item, depth + 1)
            if result:
                return result
    return None


def extract_search_results_from_html(html: str) -> tuple[int, list[dict]]:
    """
    Parse the FB Ad Library HTML and extract ad search results.

    Returns:
        (total_count, raw_collated_results_list)
        total_count: the "count" field from search_results_connection
        raw_collated_results_list: flat list of all collated_result dicts
    """
    # Find all large <script type="application/json"> tags
    # The ad data is in the one with data-content-len > 100k
    script_pattern = re.compile(
        r'<script[^>]+type="application/json"[^>]*data-content-len="(\d+)"[^>]*>(.*?)</script>',
        re.DOTALL,
    )

    # Collect all candidates sorted by content-len descending
    # (the ad data blob is typically the largest script on the page)
    candidates = []
    for match in script_pattern.finditer(html):
        content_len = int(match.group(1))
        if content_len > 50_000:
            candidates.append((content_len, match.group(2)))

    # Sort by size descending so we hit the biggest (and most likely correct) first
    candidates.sort(key=lambda x: x[0], reverse=True)

    if not candidates:
        logger.debug("No large script tags found in HTML")
        return 0, []

    src = None
    for _, script_content in candidates:
        # Quick pre-filter before expensive json.loads
        if "search_results_connection" not in script_content:
            continue
        try:
            data = json.loads(script_content)
        except json.JSONDecodeError:
            continue
        candidate_src = _walk_for_search_results(data)
        if candidate_src and candidate_src.get("edges"):
            src = candidate_src
            break

    if not src:
        logger.debug("search_results_connection with edges not found in any script")
        return 0, []

    total_count = src.get("count", 0)
    edges = src.get("edges") or []

    collated: list[dict] = []
    for edge in edges:
        node = edge.get("node") or {}
        results = node.get("collated_results") or []
        # Also check for start_date and platform at node level (sometimes there)
        node_start   = node.get("start_date")
        node_stop    = node.get("end_date")
        node_platforms = node.get("publisher_platforms") or []

        for item in results:
            # Merge node-level fields that may not be in the item itself
            if node_start and not item.get("start_date"):
                item["start_date"] = node_start
            if node_stop and not item.get("end_date"):
                item["end_date"] = node_stop
            if node_platforms and not item.get("publisher_platforms"):
                item["publisher_platforms"] = node_platforms
            collated.append(item)

    return total_count, collated


def parse_collated_result(item: dict, keyword: str) -> dict | None:
    """
    Normalize a collated_result dict to our internal ad schema.

    collated_result structure (confirmed from page HTML):
      ad_archive_id, collation_count, collation_id, is_active,
      page_id, page_is_deleted,
      snapshot: {page_name, page_profile_uri, body:{text}, cta_text,
                 cards:[], videos:[], images:[]}
    """
    ad_id = str(item.get("ad_archive_id") or "")
    if not ad_id:
        return None

    snapshot  = item.get("snapshot") or {}
    body_obj  = snapshot.get("body") or {}
    body_text = body_obj.get("text") or ""

    page_id   = str(item.get("page_id") or snapshot.get("page_id") or "")
    page_name = snapshot.get("page_name") or ""

    cta_text  = snapshot.get("cta_text") or ""
    link_url  = snapshot.get("link_url") or snapshot.get("caption") or ""

    # Media URLs — check snapshot.videos + snapshot.images + cards
    video_url = image_url = ""

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

    for card in snapshot.get("cards") or []:
        if not video_url:
            video_url = card.get("video_hd_url") or card.get("video_sd_url") or ""
        if not image_url:
            image_url = card.get("original_image_url") or card.get("resized_image_url") or ""

    # Dates
    start_ts = item.get("start_date") or snapshot.get("start_date")
    stop_ts  = item.get("end_date") or snapshot.get("end_date")
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

    return {
        "ad_archive_id":    ad_id,
        "page_id":          page_id,
        "page_name":        page_name,
        "ad_snapshot_url":  f"https://www.facebook.com/ads/archive/render_ad/?id={ad_id}",
        "ad_body":          body_text,
        "ad_title":         "",
        "ad_description":   cta_text,
        "ad_link_url":      link_url,
        "start_date":       start_date,
        "stop_date":        stop_date,
        "days_running":     days_running,
        "active_status":    "ACTIVE" if item.get("is_active") else "INACTIVE",
        "collation_count":  item.get("collation_count"),
        "impressions_min":  None,
        "impressions_max":  None,
        "spend_min":        None,
        "spend_max":        None,
        "currency":         None,
        "publisher_platforms": item.get("publisher_platforms") or [],
        "keyword_found":    keyword,
        "collected_at":     datetime.now().isoformat(),
        "_image_url":       image_url,
        "_video_url":       video_url,
        # Analysis fields (filled by analyze_agent)
        "ad_type":          "video" if video_url else ("image" if image_url else None),
        "industry":         None,
        "hook":             None,
        "text_summary":     None,
        "image_analysis":   None,
        "video_transcript": None,
        "video_analysis":   None,
        "swipe_score":      None,
    }


def extract_ads_from_html(html: str, keyword: str) -> tuple[int, list[dict]]:
    """
    High-level function: extract and normalize all ads from page HTML.

    Returns:
        (total_count, normalized_ads_list)
    """
    total, collated = extract_search_results_from_html(html)
    ads = []
    for item in collated:
        parsed = parse_collated_result(item, keyword)
        if parsed:
            ads.append(parsed)
    return total, ads
