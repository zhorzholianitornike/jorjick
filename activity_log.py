#!/usr/bin/env python3
"""
Activity logging system for News Card Bot.

Persists to a JSON file (data/activity_log.json).
Thread-safe via threading.Lock.
"""

import json
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Tbilisi timezone
TBILISI = timezone(timedelta(hours=4))

# Storage path
DATA_DIR = Path(__file__).parent / "data"
LOG_FILE = DATA_DIR / "activity_log.json"

_lock = threading.Lock()
_logs: list[dict] = []


def _load():
    """Load logs from disk on startup."""
    global _logs
    DATA_DIR.mkdir(exist_ok=True)
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                _logs = json.load(f)
            print(f"[ActivityLog] Loaded {len(_logs)} entries")
        except Exception as e:
            print(f"[ActivityLog] Load error: {e}")
            _logs = []
    else:
        _logs = []


def _save():
    """Persist logs to disk (called under lock)."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_logs, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[ActivityLog] Save error: {e}")


# Load on import
_load()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def log_activity(
    source: str,
    title: str,
    status: str = "pending",
    card_image_url: Optional[str] = None,
    caption: Optional[str] = None,
    facebook_post_id: Optional[str] = None,
) -> str:
    """
    Create a new activity log entry. Returns the log ID.

    source: "interpressnews", "rss_cnn", "rss_bbc", "rss_other", "manual", "auto_card"
    status: "pending", "approved", "rejected"
    """
    log_id = uuid.uuid4().hex[:12]
    now = datetime.now(TBILISI).isoformat()

    entry = {
        "id": log_id,
        "timestamp": now,
        "published_at": now if facebook_post_id else None,
        "source": source,
        "title": title,
        "status": status,
        "facebook_post_id": facebook_post_id,
        "card_image_url": card_image_url,
        "caption": caption,
    }

    with _lock:
        _logs.append(entry)
        _save()

    print(f"[ActivityLog] +{source}/{status}: {title[:40]}...")
    return log_id


def update_activity(log_id: str, **kwargs):
    """
    Update fields of an existing log entry.
    Common: status, facebook_post_id, published_at, card_image_url, caption
    """
    with _lock:
        for entry in _logs:
            if entry["id"] == log_id:
                entry.update(kwargs)
                if "facebook_post_id" in kwargs and kwargs["facebook_post_id"]:
                    entry["published_at"] = datetime.now(TBILISI).isoformat()
                _save()
                return True
    return False


def get_logs(
    limit: int = 50,
    offset: int = 0,
    source: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[dict]:
    """Get logs with optional filtering. Returns newest first."""
    with _lock:
        filtered = list(reversed(_logs))

    if source:
        filtered = [e for e in filtered if e["source"] == source]
    if status:
        filtered = [e for e in filtered if e["status"] == status]
    if date_from:
        filtered = [e for e in filtered if e["timestamp"] >= date_from]
    if date_to:
        filtered = [e for e in filtered if e["timestamp"] <= date_to]

    return filtered[offset:offset + limit]


def get_summary() -> dict:
    """Get summary counts for today/week/month."""
    now = datetime.now(TBILISI)
    today_str = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    with _lock:
        all_logs = list(_logs)

    total = len(all_logs)
    today = sum(1 for e in all_logs if e["timestamp"].startswith(today_str))
    week = sum(1 for e in all_logs if e["timestamp"] >= week_ago)
    month = sum(1 for e in all_logs if e["timestamp"] >= month_ago)

    approved = sum(1 for e in all_logs if e["status"] == "approved")
    rejected = sum(1 for e in all_logs if e["status"] == "rejected")
    published = sum(1 for e in all_logs if e["facebook_post_id"])

    by_source = {}
    for e in all_logs:
        src = e["source"]
        by_source[src] = by_source.get(src, 0) + 1

    return {
        "total": total,
        "today": today,
        "week": week,
        "month": month,
        "approved": approved,
        "rejected": rejected,
        "published": published,
        "by_source": by_source,
    }


def get_top(limit: int = 10) -> list[dict]:
    """Get top posts (published ones, newest first). Ready for engagement sorting later."""
    with _lock:
        published = [e for e in _logs if e["facebook_post_id"]]
    return list(reversed(published))[:limit]
