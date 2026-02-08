#!/usr/bin/env python3
"""Facebook Graph API — upload photos & read insights.

Env vars (set in Railway Variables tab):
    FB_PAGE_ID     — numeric Page ID
    FB_PAGE_TOKEN  — long-lived Page Access Token
"""

import os
import requests

PAGE_ID    = os.environ.get("FB_PAGE_ID")
PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")

GRAPH_URL  = "https://graph.facebook.com/v18.0"


def post_photo(image_path: str, caption: str = "") -> bool:
    """POST image to {PAGE_ID}/photos.  Returns True on success."""
    result = post_photo_ext(image_path, caption)
    return result["success"]


def post_photo_ext(image_path: str, caption: str = "") -> dict:
    """POST image to {PAGE_ID}/photos.  Returns {success, post_id}."""
    if not PAGE_ID or not PAGE_TOKEN:
        print("[FB] Skipped — FB_PAGE_ID / FB_PAGE_TOKEN not set")
        return {"success": False, "post_id": None}

    try:
        with open(image_path, "rb") as f:
            resp = requests.post(
                f"{GRAPH_URL}/{PAGE_ID}/photos",
                data={
                    "access_token": PAGE_TOKEN,
                    "caption":      caption,
                },
                files={
                    "source": ("card.jpg", f, "image/jpeg"),
                },
                timeout=30,
            )
        resp.raise_for_status()
        data = resp.json()
        # Prefer post_id (feed post) over id (photo object) for engagement tracking
        post_id = data.get("post_id") or data.get("id")
        photo_id = data.get("id")
        print(f"[FB] Posted — post_id: {post_id}, photo_id: {photo_id}")
        return {"success": True, "post_id": post_id}

    except Exception as exc:
        print(f"[FB] Upload failed: {exc}")
        return {"success": False, "post_id": None}


def get_post_insights(post_id: str) -> dict:
    """Get engagement metrics for a post or photo.

    Tries full Post fields first. If that fails (e.g. Photo node doesn't
    support 'shares'), retries with Photo-compatible fields.
    Also tries PAGE_ID_PHOTO_ID format as fallback for bare IDs.
    """
    _zero = {"likes": 0, "comments": 0, "shares": 0,
             "reactions_love": 0, "reactions_haha": 0, "reactions_wow": 0,
             "reactions_sad": 0, "reactions_angry": 0, "created_time": ""}
    if not PAGE_TOKEN or not post_id:
        return _zero

    # Fields for Post nodes (includes shares)
    POST_FIELDS = (
        "likes.summary(true),comments.summary(true),shares,"
        "reactions.type(LOVE).limit(0).summary(true).as(reactions_love),"
        "reactions.type(HAHA).limit(0).summary(true).as(reactions_haha),"
        "reactions.type(WOW).limit(0).summary(true).as(reactions_wow),"
        "reactions.type(SAD).limit(0).summary(true).as(reactions_sad),"
        "reactions.type(ANGRY).limit(0).summary(true).as(reactions_angry),"
        "created_time"
    )
    # Fields for Photo nodes (no shares — Photos don't have that field)
    PHOTO_FIELDS = (
        "likes.summary(true),comments.summary(true),"
        "reactions.type(LOVE).limit(0).summary(true).as(reactions_love),"
        "reactions.type(HAHA).limit(0).summary(true).as(reactions_haha),"
        "reactions.type(WOW).limit(0).summary(true).as(reactions_wow),"
        "reactions.type(SAD).limit(0).summary(true).as(reactions_sad),"
        "reactions.type(ANGRY).limit(0).summary(true).as(reactions_angry),"
        "created_time"
    )

    ids_to_try = [post_id]
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        # Try Post fields first, then Photo fields as fallback
        for fields in [POST_FIELDS, PHOTO_FIELDS]:
            try:
                resp = requests.get(
                    f"{GRAPH_URL}/{fb_id}",
                    params={
                        "access_token": PAGE_TOKEN,
                        "fields": fields,
                    },
                    timeout=15,
                )
                # Check for Photo node error before raise_for_status
                if resp.status_code == 400 and fields == POST_FIELDS:
                    body = resp.text
                    if "nonexisting field" in body or "node type (Photo)" in body:
                        print(f"[FB] {fb_id} is a Photo node, retrying without shares")
                        continue
                resp.raise_for_status()
                data = resp.json()
                result = {
                    "likes": data.get("likes", {}).get("summary", {}).get("total_count", 0),
                    "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                    "shares": data.get("shares", {}).get("count", 0),
                    "reactions_love": data.get("reactions_love", {}).get("summary", {}).get("total_count", 0),
                    "reactions_haha": data.get("reactions_haha", {}).get("summary", {}).get("total_count", 0),
                    "reactions_wow": data.get("reactions_wow", {}).get("summary", {}).get("total_count", 0),
                    "reactions_sad": data.get("reactions_sad", {}).get("summary", {}).get("total_count", 0),
                    "reactions_angry": data.get("reactions_angry", {}).get("summary", {}).get("total_count", 0),
                    "created_time": data.get("created_time", ""),
                }
                if result["likes"] or result["comments"] or result["shares"]:
                    return result
                break  # Query succeeded but no engagement — skip Photo retry
            except Exception as e:
                print(f"[FB] Post insights error ({fb_id}): {e}")
                break  # Other error — skip Photo retry, try next ID

    return _zero


def get_page_stats() -> dict:
    """Get page followers and fan count."""
    if not PAGE_ID or not PAGE_TOKEN:
        return {"followers": 0, "fans": 0, "name": ""}
    try:
        resp = requests.get(
            f"{GRAPH_URL}/{PAGE_ID}",
            params={
                "access_token": PAGE_TOKEN,
                "fields": "followers_count,fan_count,name",
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "followers": data.get("followers_count", 0),
            "fans": data.get("fan_count", 0),
            "name": data.get("name", ""),
        }
    except Exception as e:
        print(f"[FB] Page stats error: {e}")
        return {"followers": 0, "fans": 0, "name": ""}


def get_page_insights() -> dict:
    """Get page-level daily insights (requires read_insights permission)."""
    if not PAGE_ID or not PAGE_TOKEN:
        return {}
    try:
        resp = requests.get(
            f"{GRAPH_URL}/{PAGE_ID}/insights",
            params={
                "access_token": PAGE_TOKEN,
                "metric": "page_impressions,page_engaged_users,page_post_engagements",
                "period": "day",
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = {}
        for item in resp.json().get("data", []):
            name = item.get("name", "")
            values = item.get("values", [])
            if values:
                result[name] = values[-1].get("value", 0)
        return result
    except Exception as e:
        print(f"[FB] Page insights error: {e}")
        return {}


def get_post_reach(post_id: str) -> dict:
    """Get reach and clicks for a post (requires read_insights permission)."""
    if not PAGE_TOKEN or not post_id:
        return {"post_reach": 0, "clicks": 0}

    ids_to_try = [post_id]
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        try:
            resp = requests.get(
                f"{GRAPH_URL}/{fb_id}/insights",
                params={
                    "access_token": PAGE_TOKEN,
                    "metric": "post_impressions_unique,post_clicks",
                },
                timeout=15,
            )
            resp.raise_for_status()
            result = {"post_reach": 0, "clicks": 0}
            for item in resp.json().get("data", []):
                name = item.get("name", "")
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value", 0)
                    if name == "post_impressions_unique":
                        result["post_reach"] = val
                    elif name == "post_clicks":
                        result["clicks"] = val if isinstance(val, int) else 0
            if result["post_reach"] or result["clicks"]:
                return result
        except Exception as e:
            print(f"[FB] Post reach error ({fb_id}): {e}")

    return {"post_reach": 0, "clicks": 0}


def get_page_growth() -> dict:
    """Get page fan adds/removes for the last 7 days (requires read_insights)."""
    if not PAGE_ID or not PAGE_TOKEN:
        return {"fan_adds": 0, "fan_removes": 0}
    try:
        resp = requests.get(
            f"{GRAPH_URL}/{PAGE_ID}/insights",
            params={
                "access_token": PAGE_TOKEN,
                "metric": "page_fan_adds,page_fan_removes",
                "period": "day",
            },
            timeout=15,
        )
        resp.raise_for_status()
        result = {"fan_adds": 0, "fan_removes": 0}
        for item in resp.json().get("data", []):
            name = item.get("name", "")
            values = item.get("values", [])
            total = sum(v.get("value", 0) for v in values)
            if name == "page_fan_adds":
                result["fan_adds"] = total
            elif name == "page_fan_removes":
                result["fan_removes"] = total
        return result
    except Exception as e:
        print(f"[FB] Page growth error: {e}")
        return {"fan_adds": 0, "fan_removes": 0}


def get_page_views() -> dict:
    """Get page views total for the latest day (requires read_insights)."""
    if not PAGE_ID or not PAGE_TOKEN:
        return {"page_views": 0}
    try:
        resp = requests.get(
            f"{GRAPH_URL}/{PAGE_ID}/insights",
            params={
                "access_token": PAGE_TOKEN,
                "metric": "page_views_total",
                "period": "day",
            },
            timeout=15,
        )
        resp.raise_for_status()
        for item in resp.json().get("data", []):
            values = item.get("values", [])
            if values:
                return {"page_views": values[-1].get("value", 0)}
        return {"page_views": 0}
    except Exception as e:
        print(f"[FB] Page views error: {e}")
        return {"page_views": 0}
