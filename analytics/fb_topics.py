#!/usr/bin/env python3
"""Topic clustering for Georgian news posts.

Uses configurable keyword dictionary from config/topic_keywords.json.
Classifies posts by keyword matching in title/message/caption text.
"""

import json
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config" / "topic_keywords.json"
_topic_keywords: dict[str, list[str]] = {}


def _load_keywords():
    """Load topic keywords from config file (cached after first load)."""
    global _topic_keywords
    if _topic_keywords:
        return _topic_keywords
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _topic_keywords = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[Topics] Failed to load keywords: {e}")
        _topic_keywords = {}
    return _topic_keywords


def classify_post(text: str) -> str:
    """Classify a post into a topic based on keyword matching.

    Returns the topic with the most keyword matches, or 'სხვა' (other).
    """
    if not text:
        return "სხვა"

    keywords = _load_keywords()
    text_lower = text.lower()
    scores = {}

    for topic, words in keywords.items():
        count = 0
        for word in words:
            if word.lower() in text_lower:
                count += 1
        if count > 0:
            scores[topic] = count

    if not scores:
        return "სხვა"

    return max(scores, key=scores.get)


def classify_posts_batch(posts: list[dict]) -> list[dict]:
    """Add 'topic' field to each post based on its text content."""
    for post in posts:
        text = post.get("message", "") or post.get("title", "") or post.get("caption", "")
        post["topic"] = classify_post(text)
    return posts


def topic_performance(posts: list[dict]) -> dict:
    """Compute performance by topic.

    Returns: {
        topic_name: {
            count, total_engagement, avg_engagement, total_reach,
            avg_reach, share_rate, top_post
        }
    }
    """
    # Classify posts first
    posts = classify_posts_batch(posts)

    by_topic = {}
    for p in posts:
        topic = p.get("topic", "სხვა")
        if topic not in by_topic:
            by_topic[topic] = {
                "count": 0,
                "total_engagement": 0,
                "total_reach": 0,
                "total_shares": 0,
                "posts": [],
            }
        by_topic[topic]["count"] += 1
        eng = p.get("engagement_total", 0)
        by_topic[topic]["total_engagement"] += eng
        by_topic[topic]["total_reach"] += p.get("reach", 0)
        by_topic[topic]["total_shares"] += p.get("shares", 0)
        by_topic[topic]["posts"].append(p)

    result = {}
    for topic, data in by_topic.items():
        count = data["count"]
        eng = data["total_engagement"]
        reach = data["total_reach"]
        shares = data["total_shares"]

        # Find top post in this topic
        top_post = max(data["posts"], key=lambda x: x.get("engagement_total", 0)) if data["posts"] else None
        top_post_title = ""
        if top_post:
            top_post_title = (top_post.get("message", "") or "")[:80]

        result[topic] = {
            "count": count,
            "total_engagement": eng,
            "avg_engagement": round(eng / count, 1) if count else 0,
            "total_reach": reach,
            "avg_reach": round(reach / count) if count else 0,
            "share_rate": round(shares / reach * 100, 1) if reach else 0,
            "top_post": top_post_title,
        }

    # Sort by total engagement descending
    result = dict(sorted(result.items(), key=lambda x: x[1]["total_engagement"], reverse=True))
    return result


def best_posting_times(posts: list[dict]) -> dict:
    """Analyze best posting times by hour and day.

    Returns: {
        best_hour: int,
        best_day: str,
        by_hour: {hour: {count, avg_engagement}},
        by_day: {day: {count, avg_engagement}}
    }
    """
    hour_data = {}
    day_data = {}

    day_names_ka = {
        0: "ორშაბათი", 1: "სამშაბათი", 2: "ოთხშაბათი",
        3: "ხუთშაბათი", 4: "პარასკევი", 5: "შაბათი", 6: "კვირა",
    }

    for p in posts:
        ct = p.get("created_time", "") or p.get("published_at", "")
        if not ct:
            continue
        try:
            dt = _parse_datetime(ct)
            hour = dt.hour
            day = dt.weekday()
            eng = p.get("engagement_total", 0)

            if hour not in hour_data:
                hour_data[hour] = {"total_eng": 0, "count": 0}
            hour_data[hour]["total_eng"] += eng
            hour_data[hour]["count"] += 1

            if day not in day_data:
                day_data[day] = {"total_eng": 0, "count": 0}
            day_data[day]["total_eng"] += eng
            day_data[day]["count"] += 1
        except (ValueError, TypeError):
            continue

    # Calculate averages
    by_hour = {}
    for h, d in sorted(hour_data.items()):
        by_hour[h] = {
            "count": d["count"],
            "avg_engagement": round(d["total_eng"] / d["count"], 1) if d["count"] else 0,
        }

    by_day = {}
    for d_num, d in sorted(day_data.items()):
        by_day[day_names_ka.get(d_num, str(d_num))] = {
            "count": d["count"],
            "avg_engagement": round(d["total_eng"] / d["count"], 1) if d["count"] else 0,
        }

    # Best hour and day
    best_hour = max(hour_data, key=lambda h: hour_data[h]["total_eng"] / hour_data[h]["count"]
                    if hour_data[h]["count"] else 0) if hour_data else None
    best_day_num = max(day_data, key=lambda d: day_data[d]["total_eng"] / day_data[d]["count"]
                       if day_data[d]["count"] else 0) if day_data else None
    best_day = day_names_ka.get(best_day_num, "") if best_day_num is not None else ""

    return {
        "best_hour": best_hour,
        "best_day": best_day,
        "by_hour": by_hour,
        "by_day": by_day,
    }


def _parse_datetime(dt_str: str):
    """Parse various datetime formats from Facebook API and activity log."""
    from datetime import datetime as dt
    # Facebook API format: 2026-02-07T15:30:00+0000
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S+0000",
                "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return dt.strptime(dt_str[:25], fmt)
        except ValueError:
            continue
    # Try ISO format as fallback
    try:
        return dt.fromisoformat(dt_str.replace("+0000", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError(f"Cannot parse datetime: {dt_str}")
