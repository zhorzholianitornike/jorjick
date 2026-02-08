#!/usr/bin/env python3
"""KPI computation engine for Facebook analytics.

Computes 6 pillars: Distribution, Attention, Engagement, Audience, Trust, Editorial.
All formulas documented inline.
"""

from datetime import datetime, timedelta, timezone

from analytics.fb_fetcher import (
    fetch_period_metrics,
    fetch_post_impressions,
    fetch_post_clicks,
    fetch_video_metrics,
    fetch_post_comments,
)
from analytics.fb_topics import classify_post, topic_performance, best_posting_times
from analytics.fb_sentiment import batch_analyze

TBILISI = timezone(timedelta(hours=4))


def _safe_int(val) -> int:
    try:
        return int(val or 0)
    except (ValueError, TypeError):
        return 0


def _safe_pct(numerator, denominator, decimals=1) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, decimals)


def _trend_pct(current, previous) -> float:
    """Calculate percentage change. Returns 0 if no previous data."""
    if not previous:
        return 0.0
    return round((current - previous) / previous * 100, 1) if previous != 0 else 0.0


# ---------------------------------------------------------------------------
# Post-level enrichment
# ---------------------------------------------------------------------------
def _enrich_posts(posts: list[dict], activity_posts: list[dict]) -> list[dict]:
    """Enrich API posts with activity log data (engagement metrics).

    Merges Graph API post data with locally stored engagement data.
    """
    # Build lookup from activity log by facebook_post_id
    activity_by_id = {}
    for ap in activity_posts:
        fb_id = ap.get("facebook_post_id", "")
        if fb_id:
            activity_by_id[fb_id] = ap

    enriched = []
    for post in posts:
        pid = post.get("id", "")
        activity = activity_by_id.get(pid, {})

        likes = _safe_int(activity.get("likes", 0))
        comments = _safe_int(activity.get("comments", 0))
        shares = _safe_int(activity.get("shares", 0)) or post.get("shares", 0)
        reactions = {
            "love": _safe_int(activity.get("reactions_love", 0)),
            "haha": _safe_int(activity.get("reactions_haha", 0)),
            "wow": _safe_int(activity.get("reactions_wow", 0)),
            "sad": _safe_int(activity.get("reactions_sad", 0)),
            "angry": _safe_int(activity.get("reactions_angry", 0)),
        }
        reach = _safe_int(activity.get("post_reach", 0))
        clicks = _safe_int(activity.get("clicks", 0))

        engagement_total = likes + comments + shares
        engagement_rate = _safe_pct(engagement_total, reach) if reach else 0.0
        share_rate = _safe_pct(shares, reach) if reach else 0.0

        enriched.append({
            "id": pid,
            "message": post.get("message", "") or activity.get("title", "") or activity.get("caption", ""),
            "created_time": post.get("created_time", "") or activity.get("published_at", ""),
            "type": post.get("type", ""),
            "source": activity.get("source", "unknown"),
            "likes": likes,
            "comments": comments,
            "shares": shares,
            "reactions": reactions,
            "reach": reach,
            "clicks": clicks,
            "engagement_total": engagement_total,
            "engagement_rate": engagement_rate,
            "share_rate": share_rate,
        })

    return enriched


# ---------------------------------------------------------------------------
# Pillar computations
# ---------------------------------------------------------------------------
def compute_distribution(page_reach: dict, posts: list[dict]) -> dict:
    """Pillar 1: Distribution — reach, impressions, frequency, by content type.

    Formula:
        Frequency = Impressions / Reach
    """
    reach = page_reach.get("reach", 0)
    impressions = page_reach.get("impressions", 0)
    frequency = page_reach.get("frequency", 0.0)

    # Breakdown by content type
    by_type = {}
    for p in posts:
        ptype = p.get("type", "unknown") or "unknown"
        if ptype not in by_type:
            by_type[ptype] = {"count": 0, "reach": 0}
        by_type[ptype]["count"] += 1
        by_type[ptype]["reach"] += p.get("reach", 0)

    return {
        "total_reach": reach,
        "total_impressions": impressions,
        "frequency": frequency,
        "total_posts": len(posts),
        "by_content_type": by_type,
    }


def compute_attention(posts: list[dict]) -> dict:
    """Pillar 2: Attention — clicks, CTR, video metrics.

    Formula:
        CTR = Link Clicks / Impressions * 100
    """
    total_clicks = sum(p.get("clicks", 0) for p in posts)
    total_reach = sum(p.get("reach", 0) for p in posts)
    ctr = _safe_pct(total_clicks, total_reach)

    # Video metrics (aggregate if any video posts)
    video_posts = [p for p in posts if p.get("type") in ("video", "reel")]
    video_views = 0
    video_count = len(video_posts)

    return {
        "total_clicks": total_clicks,
        "ctr": ctr,
        "video_posts_count": video_count,
        "video_views": video_views,
    }


def compute_engagement(posts: list[dict]) -> dict:
    """Pillar 3: Engagement & Virality.

    Formula:
        Engagement Rate = (Likes + Comments + Shares) / Reach * 100
        Share Rate = Shares / Reach * 100
    """
    total_likes = sum(p.get("likes", 0) for p in posts)
    total_comments = sum(p.get("comments", 0) for p in posts)
    total_shares = sum(p.get("shares", 0) for p in posts)
    total_reach = sum(p.get("reach", 0) for p in posts)
    total_engagement = total_likes + total_comments + total_shares

    reactions_agg = {"love": 0, "haha": 0, "wow": 0, "sad": 0, "angry": 0}
    for p in posts:
        for key in reactions_agg:
            reactions_agg[key] += p.get("reactions", {}).get(key, 0)

    engagement_rate = _safe_pct(total_engagement, total_reach)
    share_rate = _safe_pct(total_shares, total_reach)
    avg_engagement = round(total_engagement / len(posts), 1) if posts else 0

    return {
        "total_likes": total_likes,
        "total_comments": total_comments,
        "total_shares": total_shares,
        "total_engagement": total_engagement,
        "engagement_rate": engagement_rate,
        "share_rate": share_rate,
        "avg_engagement_per_post": avg_engagement,
        "reactions": reactions_agg,
    }


def compute_audience(fans_data: dict, previous_fans: dict = None) -> dict:
    """Pillar 4: Audience Growth & Loyalty.

    Net Growth = Fan Adds - Fan Removes
    """
    total_adds = fans_data.get("total_adds", 0)
    total_removes = fans_data.get("total_removes", 0)
    net = fans_data.get("net", total_adds - total_removes)
    daily = fans_data.get("daily", [])

    prev_net = 0
    if previous_fans:
        prev_net = previous_fans.get("net", 0)
    growth_trend = _trend_pct(net, prev_net)

    return {
        "new_followers": total_adds,
        "unfollows": total_removes,
        "net_growth": net,
        "growth_trend_pct": growth_trend,
        "daily_trend": daily,
    }


def compute_trust(negative_data: dict, posts: list[dict],
                  page_reach: int = 0) -> dict:
    """Pillar 5: Trust & Brand Safety.

    Negative Rate = Negative Feedback / Reach * 100
    Sentiment: aggregated from comment analysis.
    """
    neg_total = negative_data.get("negative_feedback", 0)
    neg_by_type = negative_data.get("negative_by_type", {})
    neg_rate = _safe_pct(neg_total, page_reach)

    # Comment sentiment (aggregate across posts)
    all_comments = []
    for p in posts:
        pid = p.get("id", "")
        if pid:
            comments = fetch_post_comments(pid, limit=20)
            all_comments.extend(comments)

    sentiment = batch_analyze([c.get("message", "") for c in all_comments])

    # Flag spikes
    alert = ""
    if neg_rate > 2.0:
        alert = "ნეგატიური უკუკავშირის მაღალი დონე"
    if sentiment.get("negative_pct", 0) > 30:
        alert = alert + " | ნეგატიური სენტიმენტის სპიკი" if alert else "ნეგატიური სენტიმენტის სპიკი"

    return {
        "negative_feedback": neg_total,
        "negative_by_type": neg_by_type,
        "negative_rate": neg_rate,
        "sentiment": sentiment,
        "alert": alert,
    }


def compute_editorial(posts: list[dict]) -> dict:
    """Pillar 6: Editorial Intelligence — topics, best times."""
    # Topic clustering
    topics = topic_performance(posts)
    times = best_posting_times(posts)

    return {
        "topics": topics,
        "best_posting_times": times,
    }


# ---------------------------------------------------------------------------
# Full KPI report builder
# ---------------------------------------------------------------------------
def build_kpi_report(since: str, until: str, period_type: str = "weekly",
                     activity_posts: list[dict] = None) -> dict:
    """Build comprehensive KPI report for a period.

    Args:
        since: Start date ISO string
        until: End date ISO string
        period_type: 'weekly' or 'monthly'
        activity_posts: Posts from activity_log for enrichment

    Returns: Full KPI dict with all 6 pillars.
    """
    print(f"[FBAnalytics] Building {period_type} KPI report: {since} — {until}")

    # Fetch raw metrics
    raw = fetch_period_metrics(since, until)
    page_reach = raw["page"]["reach"]
    page_engagement = raw["page"]["engagement"]
    negative = raw["page"]["negative_feedback"]
    fans = raw["page"]["fans"]
    api_posts = raw["posts"]

    # Enrich posts with activity log data
    enriched = _enrich_posts(api_posts, activity_posts or [])

    # Compute all 6 pillars
    distribution = compute_distribution(page_reach, enriched)
    attention = compute_attention(enriched)
    engagement = compute_engagement(enriched)
    audience = compute_audience(fans)
    trust = compute_trust(negative, enriched, page_reach.get("reach", 0))
    editorial = compute_editorial(enriched)

    # Sort posts by engagement for top/bottom
    sorted_posts = sorted(enriched, key=lambda x: x.get("engagement_total", 0), reverse=True)
    top_posts = sorted_posts[:3]
    bottom_posts = list(reversed(sorted_posts[-3:])) if len(sorted_posts) >= 3 else []

    # Unavailable metrics
    unavailable = []
    if not any(p.get("type") == "video" for p in enriched):
        unavailable.append("ვიდეოს ThruPlays/Retention (ვიდეო პოსტები არ მოიძებნა)")
    if page_reach.get("reach", 0) == 0:
        unavailable.append("Page Reach (შესაძლოა read_insights permission არ არის)")

    return {
        "period": {"since": since, "until": until, "type": period_type},
        "distribution": distribution,
        "attention": attention,
        "engagement": engagement,
        "audience": audience,
        "trust": trust,
        "editorial": editorial,
        "top_posts": top_posts,
        "bottom_posts": bottom_posts,
        "unavailable_metrics": unavailable,
        "computed_at": datetime.now(TBILISI).isoformat(),
    }
