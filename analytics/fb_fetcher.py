#!/usr/bin/env python3
"""Facebook Graph API metric fetchers — new endpoints for analytics.

Reuses PAGE_ID, PAGE_TOKEN, GRAPH_URL from the existing facebook.py module.
Does NOT modify facebook.py — only imports its constants.
Adds: rate limiting (500ms), retry with exponential backoff, local caching.
"""

import os
import time
import requests as _requests
from datetime import datetime, timedelta, timezone

from analytics.fb_cache import save_api_cache, load_api_cache

# Reuse existing FB credentials (same env vars as facebook.py)
PAGE_ID = os.environ.get("FB_PAGE_ID")
PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")
GRAPH_URL = "https://graph.facebook.com/v18.0"  # same version as facebook.py

TBILISI = timezone(timedelta(hours=4))

# Rate limiting
_last_api_call = 0.0
_RATE_LIMIT_MS = 500  # 500ms between calls
_MAX_RETRIES = 3


def _rate_limit():
    """Enforce minimum delay between API calls."""
    global _last_api_call
    now = time.time()
    elapsed_ms = (now - _last_api_call) * 1000
    if elapsed_ms < _RATE_LIMIT_MS:
        time.sleep((_RATE_LIMIT_MS - elapsed_ms) / 1000)
    _last_api_call = time.time()


def _api_get(endpoint: str, params: dict, cache_key: str = None,
             cache_ttl: int = 60) -> dict | None:
    """GET request with rate limiting, caching, and retry.

    Returns parsed JSON or None on failure.
    """
    # Check cache first
    if cache_key:
        cached = load_api_cache(cache_key)
        if cached is not None:
            return cached

    for attempt in range(_MAX_RETRIES):
        try:
            _rate_limit()
            resp = _requests.get(
                f"{GRAPH_URL}/{endpoint}",
                params={"access_token": PAGE_TOKEN, **params},
                timeout=15,
            )
            if resp.status_code == 429:
                # Rate limited — back off
                wait = (2 ** attempt) * 2
                print(f"[FBFetcher] Rate limited, waiting {wait}s (attempt {attempt + 1})")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                error_msg = resp.text[:200] if resp.text else str(resp.status_code)
                print(f"[FBFetcher] API error {resp.status_code}: {error_msg}")
                return None
            data = resp.json()
            # Cache successful response
            if cache_key:
                save_api_cache(cache_key, data, cache_ttl)
            return data
        except Exception as e:
            wait = (2 ** attempt) * 1
            print(f"[FBFetcher] Request error (attempt {attempt + 1}): {e}")
            if attempt < _MAX_RETRIES - 1:
                time.sleep(wait)

    return None


# ---------------------------------------------------------------------------
# Page-level metrics
# ---------------------------------------------------------------------------
def fetch_page_reach(since: str = None, until: str = None) -> dict:
    """Fetch page reach & impressions (daily period).

    Returns: {reach: int, impressions: int, frequency: float}
    """
    result = {"reach": 0, "impressions": 0, "frequency": 0.0}
    if not PAGE_ID or not PAGE_TOKEN:
        return result

    params = {
        "metric": "page_impressions_unique,page_impressions",
        "period": "day",
    }
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    cache_key = f"page_reach_{since}_{until}"
    data = _api_get(f"{PAGE_ID}/insights", params, cache_key, cache_ttl=120)
    if not data:
        return result

    for item in data.get("data", []):
        name = item.get("name", "")
        values = item.get("values", [])
        total = sum(v.get("value", 0) for v in values if isinstance(v.get("value"), (int, float)))
        if name == "page_impressions_unique":
            result["reach"] = total
        elif name == "page_impressions":
            result["impressions"] = total

    if result["reach"] > 0:
        result["frequency"] = round(result["impressions"] / result["reach"], 2)

    return result


def fetch_page_engagement(since: str = None, until: str = None) -> dict:
    """Fetch page-level engagement metrics.

    Returns: {engaged_users: int, post_engagements: int}
    """
    result = {"engaged_users": 0, "post_engagements": 0}
    if not PAGE_ID or not PAGE_TOKEN:
        return result

    params = {
        "metric": "page_engaged_users,page_post_engagements",
        "period": "day",
    }
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    cache_key = f"page_engagement_{since}_{until}"
    data = _api_get(f"{PAGE_ID}/insights", params, cache_key, cache_ttl=120)
    if not data:
        return result

    for item in data.get("data", []):
        name = item.get("name", "")
        values = item.get("values", [])
        total = sum(v.get("value", 0) for v in values if isinstance(v.get("value"), (int, float)))
        if name == "page_engaged_users":
            result["engaged_users"] = total
        elif name == "page_post_engagements":
            result["post_engagements"] = total

    return result


def fetch_negative_feedback(since: str = None, until: str = None) -> dict:
    """Fetch negative feedback metrics (hides, unlikes, reports).

    Returns: {negative_feedback: int, negative_by_type: dict}
    """
    result = {"negative_feedback": 0, "negative_by_type": {}}
    if not PAGE_ID or not PAGE_TOKEN:
        return result

    params = {
        "metric": "page_negative_feedback,page_negative_feedback_by_type",
        "period": "day",
    }
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    cache_key = f"negative_feedback_{since}_{until}"
    data = _api_get(f"{PAGE_ID}/insights", params, cache_key, cache_ttl=120)
    if not data:
        return result

    for item in data.get("data", []):
        name = item.get("name", "")
        values = item.get("values", [])
        if name == "page_negative_feedback":
            total = sum(v.get("value", 0) for v in values if isinstance(v.get("value"), (int, float)))
            result["negative_feedback"] = total
        elif name == "page_negative_feedback_by_type":
            aggregated = {}
            for v in values:
                val = v.get("value", {})
                if isinstance(val, dict):
                    for k, count in val.items():
                        aggregated[k] = aggregated.get(k, 0) + (count if isinstance(count, (int, float)) else 0)
            result["negative_by_type"] = aggregated

    return result


def fetch_page_fans_daily(since: str = None, until: str = None) -> dict:
    """Fetch daily fan adds/removes for detailed trend.

    Returns: {daily: [{date, adds, removes, net}], total_adds, total_removes, net}
    """
    result = {"daily": [], "total_adds": 0, "total_removes": 0, "net": 0}
    if not PAGE_ID or not PAGE_TOKEN:
        return result

    params = {
        "metric": "page_fan_adds,page_fan_removes",
        "period": "day",
    }
    if since:
        params["since"] = since
    if until:
        params["until"] = until

    cache_key = f"fans_daily_{since}_{until}"
    data = _api_get(f"{PAGE_ID}/insights", params, cache_key, cache_ttl=120)
    if not data:
        return result

    adds_by_date = {}
    removes_by_date = {}
    for item in data.get("data", []):
        name = item.get("name", "")
        for v in item.get("values", []):
            date = v.get("end_time", "")[:10]
            val = v.get("value", 0) if isinstance(v.get("value"), (int, float)) else 0
            if name == "page_fan_adds":
                adds_by_date[date] = val
            elif name == "page_fan_removes":
                removes_by_date[date] = val

    all_dates = sorted(set(list(adds_by_date.keys()) + list(removes_by_date.keys())))
    for date in all_dates:
        adds = adds_by_date.get(date, 0)
        removes = removes_by_date.get(date, 0)
        result["daily"].append({
            "date": date,
            "adds": adds,
            "removes": removes,
            "net": adds - removes,
        })

    result["total_adds"] = sum(d["adds"] for d in result["daily"])
    result["total_removes"] = sum(d["removes"] for d in result["daily"])
    result["net"] = result["total_adds"] - result["total_removes"]

    return result


# ---------------------------------------------------------------------------
# Post-level metrics (extended)
# ---------------------------------------------------------------------------
def fetch_post_details(post_id: str) -> dict:
    """Fetch extended post details: type, message, created_time.

    Returns: {type, message, created_time, status_type}
    """
    result = {"type": "", "message": "", "created_time": "", "status_type": ""}
    if not PAGE_TOKEN or not post_id:
        return result

    cache_key = f"post_detail_{post_id}"
    data = _api_get(
        post_id,
        {"fields": "type,message,created_time,status_type"},
        cache_key,
        cache_ttl=1440,  # 24h — post details don't change
    )
    if data:
        result["type"] = data.get("type", "")
        result["message"] = data.get("message", "")
        result["created_time"] = data.get("created_time", "")
        result["status_type"] = data.get("status_type", "")

    return result


def fetch_post_impressions(post_id: str) -> dict:
    """Fetch post-level impressions (total + unique/reach).

    Returns: {impressions: int, reach: int}
    """
    result = {"impressions": 0, "reach": 0}
    if not PAGE_TOKEN or not post_id:
        return result

    ids_to_try = [post_id]
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        cache_key = f"post_impressions_{fb_id}"
        data = _api_get(
            f"{fb_id}/insights",
            {"metric": "post_impressions,post_impressions_unique"},
            cache_key,
            cache_ttl=60,
        )
        if data and data.get("data"):
            for item in data["data"]:
                name = item.get("name", "")
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value", 0)
                    if isinstance(val, (int, float)):
                        if name == "post_impressions":
                            result["impressions"] = val
                        elif name == "post_impressions_unique":
                            result["reach"] = val
            if result["impressions"] or result["reach"]:
                return result

    return result


def fetch_video_metrics(post_id: str) -> dict:
    """Fetch video-specific metrics (views, avg watch time).

    Returns: {video_views: int, avg_watch_ms: int, video_complete_views: int}
    Only works for video posts — returns zeros for non-video.
    """
    result = {"video_views": 0, "avg_watch_ms": 0, "video_complete_views": 0}
    if not PAGE_TOKEN or not post_id:
        return result

    ids_to_try = [post_id]
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        cache_key = f"video_metrics_{fb_id}"
        data = _api_get(
            f"{fb_id}/insights",
            {"metric": "post_video_views,post_video_avg_time_watched,post_video_complete_views_organic"},
            cache_key,
            cache_ttl=60,
        )
        if data and data.get("data"):
            for item in data["data"]:
                name = item.get("name", "")
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value", 0)
                    if isinstance(val, (int, float)):
                        if name == "post_video_views":
                            result["video_views"] = val
                        elif name == "post_video_avg_time_watched":
                            result["avg_watch_ms"] = val
                        elif name == "post_video_complete_views_organic":
                            result["video_complete_views"] = val
            if result["video_views"]:
                return result

    return result


def fetch_post_clicks(post_id: str) -> dict:
    """Fetch click details for a post.

    Returns: {link_clicks: int, other_clicks: int, total_clicks: int}
    """
    result = {"link_clicks": 0, "other_clicks": 0, "total_clicks": 0}
    if not PAGE_TOKEN or not post_id:
        return result

    ids_to_try = [post_id]
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        cache_key = f"post_clicks_{fb_id}"
        data = _api_get(
            f"{fb_id}/insights",
            {"metric": "post_clicks_by_type"},
            cache_key,
            cache_ttl=60,
        )
        if data and data.get("data"):
            for item in data["data"]:
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value", {})
                    if isinstance(val, dict):
                        result["link_clicks"] = val.get("link clicks", 0)
                        result["other_clicks"] = val.get("other clicks", 0)
                        total = sum(v for v in val.values() if isinstance(v, (int, float)))
                        result["total_clicks"] = total
                        if total:
                            return result

    return result


def fetch_post_comments(post_id: str, limit: int = 50) -> list[dict]:
    """Fetch recent comments for sentiment analysis.

    Returns: [{message, created_time}]
    """
    if not PAGE_TOKEN or not post_id:
        return []

    ids_to_try = [post_id]
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        cache_key = f"comments_{fb_id}"
        data = _api_get(
            f"{fb_id}/comments",
            {"fields": "message,created_time", "limit": str(limit)},
            cache_key,
            cache_ttl=30,
        )
        if data and data.get("data"):
            return [
                {"message": c.get("message", ""), "created_time": c.get("created_time", "")}
                for c in data["data"]
                if c.get("message")
            ]

    return []


def fetch_recent_posts(limit: int = 50, since: str = None) -> list[dict]:
    """Fetch recent published posts from the page feed.

    Returns: [{id, message, created_time, type, status_type}]
    """
    if not PAGE_ID or not PAGE_TOKEN:
        return []

    params = {
        "fields": "id,message,created_time,type,status_type,shares",
        "limit": str(limit),
    }
    if since:
        params["since"] = since

    cache_key = f"recent_posts_{since}_{limit}"
    data = _api_get(f"{PAGE_ID}/posts", params, cache_key, cache_ttl=30)
    if not data:
        return []

    return [
        {
            "id": p.get("id", ""),
            "message": p.get("message", ""),
            "created_time": p.get("created_time", ""),
            "type": p.get("type", ""),
            "status_type": p.get("status_type", ""),
            "shares": p.get("shares", {}).get("count", 0) if isinstance(p.get("shares"), dict) else 0,
        }
        for p in data.get("data", [])
    ]


# ---------------------------------------------------------------------------
# Convenience: fetch all metrics for a time window
# ---------------------------------------------------------------------------
def fetch_period_metrics(since: str, until: str) -> dict:
    """Fetch all page-level metrics for a period.

    Args:
        since: ISO date string (e.g., '2026-02-01')
        until: ISO date string (e.g., '2026-02-08')

    Returns comprehensive dict with all page metrics.
    """
    print(f"[FBFetcher] Fetching metrics for {since} — {until}")

    reach = fetch_page_reach(since, until)
    engagement = fetch_page_engagement(since, until)
    negative = fetch_negative_feedback(since, until)
    fans = fetch_page_fans_daily(since, until)
    posts = fetch_recent_posts(limit=100, since=since)

    return {
        "period": {"since": since, "until": until},
        "page": {
            "reach": reach,
            "engagement": engagement,
            "negative_feedback": negative,
            "fans": fans,
        },
        "posts": posts,
        "fetched_at": datetime.now(TBILISI).isoformat(),
    }
