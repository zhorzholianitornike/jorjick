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

    Tries post_id first. If it looks like a bare photo ID (no underscore),
    also tries PAGE_ID_PHOTO_ID format as fallback.
    """
    if not PAGE_TOKEN or not post_id:
        return {"likes": 0, "comments": 0, "shares": 0}

    ids_to_try = [post_id]
    # If stored ID has no underscore, it's a photo ID — also try post format
    if "_" not in str(post_id) and PAGE_ID:
        ids_to_try.append(f"{PAGE_ID}_{post_id}")

    for fb_id in ids_to_try:
        try:
            resp = requests.get(
                f"{GRAPH_URL}/{fb_id}",
                params={
                    "access_token": PAGE_TOKEN,
                    "fields": "likes.summary(true),comments.summary(true),shares",
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            result = {
                "likes": data.get("likes", {}).get("summary", {}).get("total_count", 0),
                "comments": data.get("comments", {}).get("summary", {}).get("total_count", 0),
                "shares": data.get("shares", {}).get("count", 0),
            }
            if result["likes"] or result["comments"] or result["shares"]:
                return result
        except Exception as e:
            print(f"[FB] Post insights error ({fb_id}): {e}")

    return {"likes": 0, "comments": 0, "shares": 0}


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
