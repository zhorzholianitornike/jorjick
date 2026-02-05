#!/usr/bin/env python3
"""Web-search and image-download helpers used by the agent as tools."""

import os
from pathlib import Path
from typing import Optional

import requests


# ---------------------------------------------------------------------------
# Web search  (DuckDuckGo, no API key needed)
# ---------------------------------------------------------------------------
def search_web(query: str, max_results: int = 5) -> list[dict]:
    """DuckDuckGo text search.  Returns [{title, snippet, url}, ...]."""
    try:
        from ddgs import DDGS
    except ImportError:
        return [{"error": "ddgs not installed. Run: pip install ddgs"}]

    try:
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append({
                    "title":   r.get("title", ""),
                    "snippet": r.get("body",  ""),
                    "url":     r.get("href",  ""),
                })
        return results
    except Exception as exc:
        return [{"error": str(exc)}]


# ---------------------------------------------------------------------------
# Image download
# ---------------------------------------------------------------------------
def download_image(url: str, dest: str = "temp/downloaded.jpg") -> Optional[str]:
    """Download an image from *url* → *dest*.  Returns local path or None."""
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = requests.get(
            url,
            timeout=15,
            stream=True,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        resp.raise_for_status()
        if "image" not in resp.headers.get("content-type", ""):
            return None
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return dest
    except Exception as exc:
        print(f"[download_image] {exc}")
        return None


# ---------------------------------------------------------------------------
# Placeholder image  (dark gradient — used when no photo is available)
# ---------------------------------------------------------------------------
def create_placeholder(dest: str = "temp/placeholder.jpg") -> str:
    """Generate a 1080×1350 dark-gradient placeholder and save as JPEG."""
    from PIL import Image, ImageDraw

    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    img  = Image.new("RGB", (1080, 1350), (25, 25, 40))
    draw = ImageDraw.Draw(img)
    # subtle fade to black at the bottom (rows 800 → 1350)
    for y in range(800, 1350):
        t = (y - 800) / 550.0
        v = int(25 * (1 - t))
        draw.rectangle([0, y, 1080, y + 1], fill=(v, v, int(40 * (1 - t))))
    img.save(dest, "JPEG", quality=90)
    return dest


# ---------------------------------------------------------------------------
# Tavily search  (needs TAVILY_API_KEY)
# ---------------------------------------------------------------------------
def search_tavily(query: str, max_results: int = 5) -> dict:
    """Tavily search with images.  Returns {results:[…], images:[…]} or {error:…}."""
    try:
        from tavily import TavilyClient
    except ImportError:
        return {"error": "tavily-python not installed"}

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {"error": "TAVILY_API_KEY env var is not set"}

    try:
        client = TavilyClient(api_key=api_key)
        return  client.search(query, max_results=max_results, include_images=True)
    except Exception as exc:
        return {"error": str(exc)}
