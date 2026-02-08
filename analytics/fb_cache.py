#!/usr/bin/env python3
"""Local JSON cache for FB analytics data — 6-month retention."""

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

TBILISI = timezone(timedelta(hours=4))
CACHE_DIR = Path(__file__).parent.parent / "data" / "fb_analytics"
RETENTION_DAYS = 180  # 6 months

_lock = threading.Lock()


def _ensure_dir():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def save_metrics(period_key: str, data: dict):
    """Save metrics for a given period key (e.g., '2026-W06' or '2026-01').

    period_key format:
        weekly:  '2026-W06'
        monthly: '2026-01'
        daily:   '2026-02-07'
    """
    _ensure_dir()
    cache_file = CACHE_DIR / "metrics_history.json"
    with _lock:
        history = _load_history()
        history[period_key] = {
            "fetched_at": datetime.now(TBILISI).isoformat(),
            "data": data,
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2, default=str)


def load_metrics(period_key: str) -> dict | None:
    """Load cached metrics for a period. Returns None if not cached."""
    history = _load_history()
    entry = history.get(period_key)
    if entry:
        return entry.get("data")
    return None


def load_all_history() -> dict:
    """Load all cached metrics history."""
    return _load_history()


def get_previous_period(period_key: str) -> dict | None:
    """Get metrics for the previous period (for MoM/WoW comparison)."""
    history = _load_history()
    if period_key.startswith("20") and "-W" in period_key:
        # Weekly: '2026-W06' → '2026-W05'
        year, week = period_key.split("-W")
        prev_week = int(week) - 1
        if prev_week < 1:
            prev_key = f"{int(year) - 1}-W52"
        else:
            prev_key = f"{year}-W{prev_week:02d}"
    elif len(period_key) == 7:
        # Monthly: '2026-02' → '2026-01'
        year, month = period_key.split("-")
        prev_month = int(month) - 1
        if prev_month < 1:
            prev_key = f"{int(year) - 1}-12"
        else:
            prev_key = f"{year}-{prev_month:02d}"
    else:
        return None

    entry = history.get(prev_key)
    if entry:
        return entry.get("data")
    return None


def cleanup_old_data():
    """Remove data older than RETENTION_DAYS."""
    _ensure_dir()
    history = _load_history()
    cutoff = (datetime.now(TBILISI) - timedelta(days=RETENTION_DAYS)).isoformat()
    removed = 0
    keys_to_remove = []
    for key, entry in history.items():
        fetched = entry.get("fetched_at", "")
        if fetched and fetched < cutoff:
            keys_to_remove.append(key)
            removed += 1

    if keys_to_remove:
        for k in keys_to_remove:
            del history[k]
        cache_file = CACHE_DIR / "metrics_history.json"
        with _lock:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2, default=str)
        print(f"[FBAnalytics] Cleaned up {removed} old cache entries")


def save_api_cache(endpoint: str, data: dict, ttl_minutes: int = 60):
    """Cache raw API response to avoid repeated calls within TTL."""
    _ensure_dir()
    cache_file = CACHE_DIR / "api_cache.json"
    with _lock:
        cache = _load_api_cache()
        cache[endpoint] = {
            "data": data,
            "cached_at": datetime.now(TBILISI).isoformat(),
            "ttl_minutes": ttl_minutes,
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2, default=str)


def load_api_cache(endpoint: str) -> dict | None:
    """Load cached API response if still valid (within TTL)."""
    cache = _load_api_cache()
    entry = cache.get(endpoint)
    if not entry:
        return None
    cached_at = entry.get("cached_at", "")
    ttl = entry.get("ttl_minutes", 60)
    try:
        cached_time = datetime.fromisoformat(cached_at)
        if datetime.now(TBILISI) - cached_time < timedelta(minutes=ttl):
            return entry.get("data")
    except (ValueError, TypeError):
        pass
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _load_history() -> dict:
    cache_file = CACHE_DIR / "metrics_history.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _load_api_cache() -> dict:
    cache_file = CACHE_DIR / "api_cache.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}
