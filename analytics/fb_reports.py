#!/usr/bin/env python3
"""Report generators — Georgian text + JSON output.

Two report types per period:
1. Management one-pager (5-7 KPIs, concise)
2. Team detail report (granular breakdown)

Two period types:
- Weekly (operational)
- Monthly (strategic, with MoM trends)

All output in Georgian.
"""

from datetime import datetime, timedelta, timezone

from analytics.fb_cache import get_previous_period

TBILISI = timezone(timedelta(hours=4))


def _fmt_num(n) -> str:
    """Format number with thousands separator."""
    try:
        n = int(n)
        if n >= 1_000_000:
            return f"{n / 1_000_000:.1f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return f"{n:,}".replace(",", " ")
    except (ValueError, TypeError):
        return str(n)


def _trend_arrow(pct: float) -> str:
    """Return trend arrow based on percentage."""
    if pct > 0:
        return f"+{pct:.1f}%"
    elif pct < 0:
        return f"{pct:.1f}%"
    return "0%"


def _truncate(text: str, max_len: int = 60) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


# ---------------------------------------------------------------------------
# WEEKLY MANAGEMENT REPORT (Telegram text — concise)
# ---------------------------------------------------------------------------
def weekly_management_text(kpi: dict) -> str:
    """Generate concise weekly management summary for Telegram.

    5-7 core KPIs, top 3 posts, bottom 3, 3 recommendations.
    """
    period = kpi.get("period", {})
    since = period.get("since", "")
    until = period.get("until", "")
    dist = kpi.get("distribution", {})
    att = kpi.get("attention", {})
    eng = kpi.get("engagement", {})
    aud = kpi.get("audience", {})
    trust = kpi.get("trust", {})
    editorial = kpi.get("editorial", {})

    lines = [
        f"📊 კვირის შეჯამება — {since} — {until}",
        "━" * 36,
        "",
        "📡 დისტრიბუცია:",
        f"   მიღწევა: {_fmt_num(dist.get('total_reach', 0))} | "
        f"შთაბეჭდილებები: {_fmt_num(dist.get('total_impressions', 0))} | "
        f"სიხშირე: {dist.get('frequency', 0):.1f}",
        f"   პოსტები: {dist.get('total_posts', 0)}",
        "",
        "👁 ყურადღება:",
        f"   კლიკები: {_fmt_num(att.get('total_clicks', 0))} | CTR: {att.get('ctr', 0):.1f}%",
    ]

    if att.get("video_posts_count", 0):
        lines.append(f"   ვიდეო ნახვები: {_fmt_num(att.get('video_views', 0))}")

    lines.extend([
        "",
        "💬 ჩართულობა:",
        f"   👍 {_fmt_num(eng.get('total_likes', 0))} | "
        f"💬 {_fmt_num(eng.get('total_comments', 0))} | "
        f"🔄 {_fmt_num(eng.get('total_shares', 0))}",
        f"   📈 Engagement Rate: {eng.get('engagement_rate', 0):.1f}% | "
        f"Share Rate: {eng.get('share_rate', 0):.1f}%",
        f"   საშ. ჩართულობა/პოსტი: {eng.get('avg_engagement_per_post', 0):.1f}",
    ])

    # Reactions
    rx = eng.get("reactions", {})
    if any(rx.values()):
        lines.append(
            f"   ❤️ {rx.get('love', 0)} | 😂 {rx.get('haha', 0)} | "
            f"😮 {rx.get('wow', 0)} | 😢 {rx.get('sad', 0)} | 😠 {rx.get('angry', 0)}"
        )

    lines.extend([
        "",
        "📈 აუდიტორია:",
        f"   ახალი: +{aud.get('new_followers', 0)} | "
        f"წასული: -{aud.get('unfollows', 0)} | "
        f"წმინდა: {'+' if aud.get('net_growth', 0) >= 0 else ''}{aud.get('net_growth', 0)}",
    ])

    # Trust
    sent = trust.get("sentiment", {})
    lines.extend([
        "",
        "🛡 ნდობა:",
        f"   ნეგატიური: {trust.get('negative_rate', 0):.1f}%",
    ])
    if sent.get("available"):
        lines.append(
            f"   სენტიმენტი: ✅ {sent.get('positive_pct', 0):.0f}% | "
            f"⚠️ {sent.get('negative_pct', 0):.0f}% | "
            f"➖ {sent.get('neutral_pct', 0):.0f}%"
        )
    else:
        lines.append("   სენტიმენტი: მიუწვდომელი (კომენტარები არ მოიძებნა)")

    if trust.get("alert"):
        lines.append(f"   ⚠️ შეტყობინება: {trust['alert']}")

    # Editorial
    topics = editorial.get("topics", {})
    times = editorial.get("best_posting_times", {})
    if topics:
        lines.extend(["", "📰 თემები (ჩართულობით):"])
        for i, (topic, data) in enumerate(list(topics.items())[:5]):
            lines.append(
                f"   {i + 1}. {topic} — "
                f"{data.get('count', 0)} პოსტი, "
                f"საშ. ჩართ.: {data.get('avg_engagement', 0):.1f}"
            )

    if times.get("best_hour") is not None:
        lines.extend([
            "",
            f"🎯 საუკეთესო დრო: {times['best_hour']:02d}:00"
            + (f" | {times.get('best_day', '')}" if times.get("best_day") else ""),
        ])

    # Top 3 posts
    top = kpi.get("top_posts", [])
    if top:
        lines.extend(["", "━" * 36, "🏆 ტოპ 3 პოსტი:"])
        for i, p in enumerate(top[:3]):
            title = _truncate(p.get("message", "") or p.get("title", ""), 50)
            lines.append(
                f"   {i + 1}. \"{title}\"\n"
                f"      👍{p.get('likes', 0)} 💬{p.get('comments', 0)} "
                f"🔄{p.get('shares', 0)} | reach: {_fmt_num(p.get('reach', 0))}"
            )

    # Bottom 3 posts
    bottom = kpi.get("bottom_posts", [])
    if bottom:
        lines.extend(["", "📉 სუსტი 3 პოსტი:"])
        for i, p in enumerate(bottom[:3]):
            title = _truncate(p.get("message", "") or p.get("title", ""), 50)
            lines.append(
                f"   {i + 1}. \"{title}\"\n"
                f"      👍{p.get('likes', 0)} 💬{p.get('comments', 0)} "
                f"🔄{p.get('shares', 0)} | reach: {_fmt_num(p.get('reach', 0))}"
            )

    # Recommendations
    recs = _generate_weekly_recommendations(kpi)
    if recs:
        lines.extend(["", "━" * 36, "📋 რეკომენდაციები:"])
        for i, rec in enumerate(recs[:3]):
            lines.append(f"   {i + 1}. {rec}")

    # Unavailable metrics
    unavailable = kpi.get("unavailable_metrics", [])
    if unavailable:
        lines.extend(["", "⚠️ მიუწვდომელი მეტრიკები:"])
        for m in unavailable:
            lines.append(f"   · {m}")

    lines.extend([
        "",
        "━" * 36,
        "🤖 კვირის ანალიტიკა — აგენტი აქტიურია!",
    ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# WEEKLY DETAIL REPORT (JSON for dashboard)
# ---------------------------------------------------------------------------
def weekly_detail_json(kpi: dict) -> dict:
    """Generate detailed weekly report as JSON for dashboard consumption."""
    return {
        "report_type": "weekly_detail",
        "period": kpi.get("period", {}),
        "distribution": kpi.get("distribution", {}),
        "attention": kpi.get("attention", {}),
        "engagement": kpi.get("engagement", {}),
        "audience": kpi.get("audience", {}),
        "trust": kpi.get("trust", {}),
        "editorial": kpi.get("editorial", {}),
        "top_posts": _sanitize_posts(kpi.get("top_posts", [])),
        "bottom_posts": _sanitize_posts(kpi.get("bottom_posts", [])),
        "recommendations": _generate_weekly_recommendations(kpi),
        "unavailable_metrics": kpi.get("unavailable_metrics", []),
        "computed_at": kpi.get("computed_at", ""),
    }


# ---------------------------------------------------------------------------
# MONTHLY STRATEGY REPORT (Telegram text)
# ---------------------------------------------------------------------------
def monthly_strategy_text(kpi: dict, prev_kpi: dict = None) -> str:
    """Generate monthly strategic summary for Telegram.

    Includes MoM trends, winners/losers by topic, brand safety, test plan.
    """
    period = kpi.get("period", {})
    since = period.get("since", "")
    until = period.get("until", "")
    dist = kpi.get("distribution", {})
    eng = kpi.get("engagement", {})
    aud = kpi.get("audience", {})
    trust = kpi.get("trust", {})
    editorial = kpi.get("editorial", {})

    lines = [
        f"📊 თვის სტრატეგიული შეჯამება — {since} — {until}",
        "━" * 40,
    ]

    # MoM Trends
    lines.append("\n📈 MoM ტრენდები:")
    if prev_kpi:
        prev_dist = prev_kpi.get("distribution", {})
        prev_eng = prev_kpi.get("engagement", {})
        prev_aud = prev_kpi.get("audience", {})

        reach_change = _trend_arrow(
            _pct_change(dist.get("total_reach", 0), prev_dist.get("total_reach", 0))
        )
        eng_change = _trend_arrow(
            _pct_change(eng.get("engagement_rate", 0), prev_eng.get("engagement_rate", 0))
        )
        growth_change = _trend_arrow(
            _pct_change(aud.get("net_growth", 0), prev_aud.get("net_growth", 0))
        )

        lines.extend([
            f"   მიღწევა: {_fmt_num(dist.get('total_reach', 0))} ({reach_change})",
            f"   Engagement Rate: {eng.get('engagement_rate', 0):.1f}% ({eng_change})",
            f"   წმინდა ზრდა: {aud.get('net_growth', 0)} ({growth_change})",
            f"   პოსტები: {dist.get('total_posts', 0)}",
        ])
    else:
        lines.append("   წინა თვის მონაცემები არ არსებობს (პირველი თვეა)")
        lines.extend([
            f"   მიღწევა: {_fmt_num(dist.get('total_reach', 0))}",
            f"   Engagement Rate: {eng.get('engagement_rate', 0):.1f}%",
            f"   წმინდა ზრდა: {aud.get('net_growth', 0)}",
            f"   პოსტები: {dist.get('total_posts', 0)}",
        ])

    # Winners & Losers by topic
    topics = editorial.get("topics", {})
    if topics:
        topic_list = list(topics.items())
        lines.extend(["\n🏆 გამარჯვებული თემები:"])
        for topic, data in topic_list[:3]:
            lines.append(
                f"   ✅ {topic}: {data.get('count', 0)} პოსტი, "
                f"საშ. ჩართ.: {data.get('avg_engagement', 0):.1f}, "
                f"share: {data.get('share_rate', 0):.1f}%"
            )

        if len(topic_list) > 3:
            lines.extend(["\n📉 სუსტი თემები:"])
            for topic, data in topic_list[-2:]:
                lines.append(
                    f"   ⚠️ {topic}: {data.get('count', 0)} პოსტი, "
                    f"საშ. ჩართ.: {data.get('avg_engagement', 0):.1f}"
                )

    # Content type performance
    by_type = dist.get("by_content_type", {})
    if by_type:
        lines.extend(["\n📋 ფორმატის ეფექტურობა:"])
        for ctype, data in by_type.items():
            lines.append(f"   · {ctype}: {data.get('count', 0)} პოსტი, reach: {_fmt_num(data.get('reach', 0))}")

    # Brand safety
    lines.extend(["\n🛡 ბრენდის უსაფრთხოება:"])
    lines.append(f"   ნეგატიური: {trust.get('negative_rate', 0):.1f}%")
    sent = trust.get("sentiment", {})
    if sent.get("available"):
        lines.append(
            f"   სენტიმენტი: ✅{sent.get('positive_pct', 0):.0f}% "
            f"⚠️{sent.get('negative_pct', 0):.0f}% "
            f"➖{sent.get('neutral_pct', 0):.0f}%"
        )
    if trust.get("alert"):
        lines.append(f"   🚨 {trust['alert']}")

    # Test plan for next month
    tests = _generate_monthly_tests(kpi, prev_kpi)
    if tests:
        lines.extend(["\n🧪 შემდეგი თვის ტესტ-გეგმა:"])
        for i, test in enumerate(tests[:5]):
            lines.append(f"   {i + 1}. {test}")

    lines.extend([
        "",
        "━" * 40,
        "🤖 თვის სტრატეგიული ანალიტიკა — აგენტი აქტიურია!",
    ])

    return "\n".join(lines)


def monthly_detail_json(kpi: dict, prev_kpi: dict = None) -> dict:
    """Generate detailed monthly report as JSON for dashboard."""
    return {
        "report_type": "monthly_detail",
        "period": kpi.get("period", {}),
        "distribution": kpi.get("distribution", {}),
        "attention": kpi.get("attention", {}),
        "engagement": kpi.get("engagement", {}),
        "audience": kpi.get("audience", {}),
        "trust": kpi.get("trust", {}),
        "editorial": kpi.get("editorial", {}),
        "top_posts": _sanitize_posts(kpi.get("top_posts", [])),
        "bottom_posts": _sanitize_posts(kpi.get("bottom_posts", [])),
        "mom_comparison": _build_mom(kpi, prev_kpi),
        "tests": _generate_monthly_tests(kpi, prev_kpi),
        "unavailable_metrics": kpi.get("unavailable_metrics", []),
        "computed_at": kpi.get("computed_at", ""),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sanitize_posts(posts: list) -> list:
    """Remove internal fields from posts for JSON output."""
    clean = []
    for p in posts:
        clean.append({
            "id": p.get("id", ""),
            "message": _truncate(p.get("message", ""), 100),
            "created_time": p.get("created_time", ""),
            "type": p.get("type", ""),
            "source": p.get("source", ""),
            "likes": p.get("likes", 0),
            "comments": p.get("comments", 0),
            "shares": p.get("shares", 0),
            "reach": p.get("reach", 0),
            "engagement_total": p.get("engagement_total", 0),
            "engagement_rate": p.get("engagement_rate", 0),
            "topic": p.get("topic", ""),
        })
    return clean


def _pct_change(current, previous) -> float:
    if not previous:
        return 0.0
    return round((current - previous) / abs(previous) * 100, 1) if previous != 0 else 0.0


def _build_mom(kpi, prev_kpi):
    """Build MoM comparison dict."""
    if not prev_kpi:
        return {"available": False}
    return {
        "available": True,
        "reach_change": _pct_change(
            kpi.get("distribution", {}).get("total_reach", 0),
            prev_kpi.get("distribution", {}).get("total_reach", 0)
        ),
        "engagement_rate_change": _pct_change(
            kpi.get("engagement", {}).get("engagement_rate", 0),
            prev_kpi.get("engagement", {}).get("engagement_rate", 0)
        ),
        "growth_change": _pct_change(
            kpi.get("audience", {}).get("net_growth", 0),
            prev_kpi.get("audience", {}).get("net_growth", 0)
        ),
        "posts_change": _pct_change(
            kpi.get("distribution", {}).get("total_posts", 0),
            prev_kpi.get("distribution", {}).get("total_posts", 0)
        ),
    }


def _generate_weekly_recommendations(kpi: dict) -> list[str]:
    """Generate 3 actionable recommendations based on KPI data."""
    recs = []
    eng = kpi.get("engagement", {})
    att = kpi.get("attention", {})
    aud = kpi.get("audience", {})
    editorial = kpi.get("editorial", {})
    trust = kpi.get("trust", {})

    # Engagement rate check
    rate = eng.get("engagement_rate", 0)
    if rate < 1.0:
        recs.append("ჩართულობის გაზრდა: დამატეთ CTA (Call to Action) პოსტებში, დასვით კითხვები აუდიტორიას")
    elif rate > 5.0:
        recs.append("მაღალი ჩართულობა — გააგრძელეთ მიმდინარე სტრატეგია, გაზარდეთ პოსტების სიხშირე")

    # Share rate
    if eng.get("share_rate", 0) < 0.3:
        recs.append("გაზიარების გაზრდა: შექმენით უფრო ვირალური კონტენტი — ინფოგრაფიკა, სტატისტიკა, ციტატები")

    # Best time
    times = editorial.get("best_posting_times", {})
    if times.get("best_hour") is not None:
        recs.append(f"პოსტების გამოქვეყნება {times['best_hour']:02d}:00 საათზე — ეს არის საუკეთესო დრო ჩართულობისთვის")

    # Audience
    if aud.get("net_growth", 0) < 0:
        recs.append("მიმდევრების კლება: გადახედეთ კონტენტის ხარისხს და პოსტების სიხშირეს")

    # Trust
    if trust.get("negative_rate", 0) > 1.5:
        recs.append("ნეგატიური უკუკავშირის მაღალი დონე — შეამცირეთ კლიკბეიტ სტილის სათაურები")

    # Topic diversity
    topics = editorial.get("topics", {})
    if len(topics) <= 2:
        recs.append("თემების დივერსიფიკაცია: დაამატეთ მრავალფეროვანი თემები — სპორტი, კულტურა, ტექნოლოგიები")

    # CTR
    if att.get("ctr", 0) > 0 and att.get("ctr", 0) < 1.0:
        recs.append("CTR-ის გაზრდა: გაუმჯობესეთ სათაურები და სურათები — გამოიყენეთ ემოციური ტრიგერები")

    return recs[:3]


def _generate_monthly_tests(kpi: dict, prev_kpi: dict = None) -> list[str]:
    """Generate 3-5 tests for next month based on analysis."""
    tests = []
    eng = kpi.get("engagement", {})
    editorial = kpi.get("editorial", {})
    dist = kpi.get("distribution", {})

    # Video test
    by_type = dist.get("by_content_type", {})
    video_count = by_type.get("video", {}).get("count", 0)
    if video_count < 3:
        tests.append("ვიდეო კონტენტის ტესტი: გამოაქვეყნეთ კვირაში 2-3 მოკლე ვიდეო/Reels")

    # Posting frequency
    total_posts = dist.get("total_posts", 0)
    if total_posts < 20:
        tests.append("სიხშირის ტესტი: გაზარდეთ პოსტების რაოდენობა 30%-ით შემდეგ თვეში")
    elif total_posts > 60:
        tests.append("ხარისხი vs რაოდენობა: შეამცირეთ პოსტები 20%-ით და გაზარდეთ ხარისხი")

    # Topic test
    topics = editorial.get("topics", {})
    if topics:
        top_topic = list(topics.keys())[0]
        tests.append(f"ტოპ თემის გაძლიერება: გამოაქვეყნეთ მეტი \"{top_topic}\" კონტენტი")

    # Engagement test
    if eng.get("engagement_rate", 0) < 2.0:
        tests.append("ჩართულობის ტესტი: გამოაქვეყნეთ გამოკითხვები და კითხვა-პასუხის პოსტები")

    # Time test
    times = editorial.get("best_posting_times", {})
    if times.get("best_hour") is not None:
        h = times["best_hour"]
        tests.append(f"დროის ტესტი: შეადარეთ {h:02d}:00 vs {(h + 2) % 24:02d}:00 პოსტების შედეგები")

    return tests[:5]
