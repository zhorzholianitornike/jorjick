#!/usr/bin/env python3
"""Facebook Graph API — upload a photo to a Page.

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
        post_id = resp.json().get("id")
        print(f"[FB] Posted — id: {post_id}")
        return {"success": True, "post_id": post_id}

    except Exception as exc:
        print(f"[FB] Upload failed: {exc}")
        return {"success": False, "post_id": None}
