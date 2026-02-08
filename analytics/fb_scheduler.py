#!/usr/bin/env python3
"""Scheduling + Telegram command handlers for FB analytics reports.

- Weekly report: Monday 09:00 Tbilisi
- Monthly report: 1st of each month 09:00 Tbilisi
- Manual triggers via Telegram commands: /fb_weekly, /fb_monthly
- API endpoints for manual trigger and dashboard
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import requests as _requests

from analytics.fb_kpi import build_kpi_report
from analytics.fb_reports import (
    weekly_management_text,
    weekly_detail_json,
    monthly_strategy_text,
    monthly_detail_json,
)
from analytics.fb_cache import save_metrics, load_metrics, get_previous_period, cleanup_old_data

TBILISI = timezone(timedelta(hours=4))
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID")

# Latest report cache (in-memory for dashboard)
_latest_weekly: dict = {}
_latest_monthly: dict = {}


def _send_tg(text: str):
    """Send a message to Telegram admin (blocking)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        return
    # Telegram has 4096 char limit — split if needed
    chunks = []
    while len(text) > 4000:
        # Find last newline before 4000
        split_pos = text.rfind("\n", 0, 4000)
        if split_pos == -1:
            split_pos = 4000
        chunks.append(text[:split_pos])
        text = text[split_pos:]
    chunks.append(text)

    for chunk in chunks:
        try:
            _requests.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_ADMIN_ID, "text": chunk},
                timeout=10,
            )
        except Exception as exc:
            print(f"[FBAnalytics] TG send error: {exc}")


def _get_activity_posts(days: int = 7) -> list[dict]:
    """Get posts from activity_log for enrichment.

    Imports activity_log at call time to avoid circular imports.
    """
    try:
        from activity_log import get_logs
        all_logs = get_logs()
        # Return only published posts (with facebook_post_id)
        published = [e for e in all_logs if e.get("facebook_post_id")]
        print(f"[FBAnalytics] Got {len(published)} published posts from activity log")
        return published
    except Exception as e:
        print(f"[FBAnalytics] Failed to get activity posts: {e}")
        return []


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------
def run_weekly_report() -> dict:
    """Build and send weekly report. Returns detail JSON."""
    global _latest_weekly
    now = datetime.now(TBILISI)
    # Period: last 7 days
    until_date = now.strftime("%Y-%m-%d")
    since_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_key = f"{now.year}-W{now.isocalendar()[1]:02d}"

    print(f"[FBAnalytics] Running weekly report: {since_date} — {until_date} ({week_key})")

    activity_posts = _get_activity_posts(days=7)
    kpi = build_kpi_report(since_date, until_date, "weekly", activity_posts)

    # Save to cache
    save_metrics(week_key, kpi)

    # Generate reports
    text = weekly_management_text(kpi)
    detail = weekly_detail_json(kpi)

    # Send to Telegram
    _send_tg(text)
    print(f"[FBAnalytics] Weekly report sent to Telegram")

    # Cache for dashboard
    _latest_weekly = detail

    # Cleanup old data
    cleanup_old_data()

    return detail


def run_monthly_report() -> dict:
    """Build and send monthly report. Returns detail JSON."""
    global _latest_monthly
    now = datetime.now(TBILISI)
    # Period: last 30 days (or previous calendar month)
    until_date = now.strftime("%Y-%m-%d")
    since_date = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    month_key = now.strftime("%Y-%m")

    print(f"[FBAnalytics] Running monthly report: {since_date} — {until_date} ({month_key})")

    activity_posts = _get_activity_posts(days=30)
    kpi = build_kpi_report(since_date, until_date, "monthly", activity_posts)

    # Save to cache
    save_metrics(month_key, kpi)

    # Get previous month for MoM comparison
    prev_kpi = get_previous_period(month_key)

    # Generate reports
    text = monthly_strategy_text(kpi, prev_kpi)
    detail = monthly_detail_json(kpi, prev_kpi)

    # Send to Telegram
    _send_tg(text)
    print(f"[FBAnalytics] Monthly report sent to Telegram")

    # Cache for dashboard
    _latest_monthly = detail

    return detail


def get_latest_weekly() -> dict:
    """Get latest weekly report (for dashboard API)."""
    return _latest_weekly


def get_latest_monthly() -> dict:
    """Get latest monthly report (for dashboard API)."""
    return _latest_monthly


# ---------------------------------------------------------------------------
# Telegram command handlers
# ---------------------------------------------------------------------------
async def tg_fb_weekly(update, ctx):
    """Handle /fb_weekly command — generate and send weekly report."""
    await update.message.reply_text("📊 კვირის FB ანალიტიკა გენერირდება, დაელოდეთ...")
    try:
        detail = await asyncio.to_thread(run_weekly_report)
        posts_count = detail.get("distribution", {}).get("total_posts", 0)
        await update.message.reply_text(f"✅ კვირის რეპორტი გაიგზავნა! ({posts_count} პოსტი გაანალიზდა)")
    except Exception as exc:
        await update.message.reply_text(f"❌ შეცდომა: {exc}")
        print(f"[FBAnalytics] Weekly command error: {exc}")


async def tg_fb_monthly(update, ctx):
    """Handle /fb_monthly command — generate and send monthly report."""
    await update.message.reply_text("📊 თვის FB ანალიტიკა გენერირდება, დაელოდეთ...")
    try:
        detail = await asyncio.to_thread(run_monthly_report)
        posts_count = detail.get("distribution", {}).get("total_posts", 0)
        await update.message.reply_text(f"✅ თვის რეპორტი გაიგზავნა! ({posts_count} პოსტი გაანალიზდა)")
    except Exception as exc:
        await update.message.reply_text(f"❌ შეცდომა: {exc}")
        print(f"[FBAnalytics] Monthly command error: {exc}")


# ---------------------------------------------------------------------------
# Background scheduling loops
# ---------------------------------------------------------------------------
async def weekly_report_loop():
    """Background loop: send weekly report every Monday at 09:00 Tbilisi."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        print("[FBAnalytics] No TG credentials — weekly analytics disabled")
        return

    await asyncio.sleep(180)  # wait 3 min on startup
    print("[FBAnalytics] Weekly analytics loop started (Monday 09:00)")

    while True:
        try:
            now = datetime.now(TBILISI)
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and (now.hour > 9 or (now.hour == 9 and now.minute > 0)):
                days_until_monday = 7
            next_monday = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
            wait_seconds = (next_monday - now).total_seconds()
            print(f"[FBAnalytics] Next weekly report in {wait_seconds / 3600:.1f}h ({next_monday.strftime('%d/%m %H:%M')})")
            await asyncio.sleep(wait_seconds)

            await asyncio.to_thread(run_weekly_report)

        except Exception as exc:
            print(f"[FBAnalytics] Weekly loop error: {exc}")
            await asyncio.sleep(3600)


async def monthly_report_loop():
    """Background loop: send monthly report on 1st of each month at 09:00 Tbilisi."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        print("[FBAnalytics] No TG credentials — monthly analytics disabled")
        return

    await asyncio.sleep(240)  # wait 4 min on startup
    print("[FBAnalytics] Monthly analytics loop started (1st of month 09:00)")

    while True:
        try:
            now = datetime.now(TBILISI)
            # Calculate next 1st of month at 09:00
            if now.day == 1 and now.hour < 9:
                next_first = now.replace(hour=9, minute=0, second=0, microsecond=0)
            else:
                if now.month == 12:
                    next_first = now.replace(year=now.year + 1, month=1, day=1,
                                             hour=9, minute=0, second=0, microsecond=0)
                else:
                    next_first = now.replace(month=now.month + 1, day=1,
                                             hour=9, minute=0, second=0, microsecond=0)

            wait_seconds = (next_first - now).total_seconds()
            print(f"[FBAnalytics] Next monthly report in {wait_seconds / 3600:.1f}h ({next_first.strftime('%d/%m %H:%M')})")
            await asyncio.sleep(wait_seconds)

            await asyncio.to_thread(run_monthly_report)

        except Exception as exc:
            print(f"[FBAnalytics] Monthly loop error: {exc}")
            await asyncio.sleep(3600)
