#!/usr/bin/env python3
"""Facebook Analytics module — isolated, does not modify existing code.

Usage (in web_app.py):
    from analytics import setup_analytics
    asyncio.create_task(setup_analytics(app))

This registers:
- 2 API endpoints: /api/analytics/weekly, /api/analytics/monthly
- 1 test endpoint: /api/analytics/test-weekly, /api/analytics/test-monthly
- 2 background loops: weekly (Mon 09:00), monthly (1st 09:00)
"""

import asyncio

from analytics.fb_scheduler import (
    weekly_report_loop,
    monthly_report_loop,
    run_weekly_report,
    run_monthly_report,
    get_latest_weekly,
    get_latest_monthly,
)


async def setup_analytics(app):
    """Wire analytics into FastAPI app — call from on_startup().

    Registers API endpoints + starts background scheduling loops.
    """
    from fastapi.responses import JSONResponse

    # -----------------------------------------------------------------------
    # API endpoints
    # -----------------------------------------------------------------------
    @app.get("/api/analytics/weekly")
    async def api_analytics_weekly():
        """Get latest weekly analytics report (JSON for dashboard)."""
        data = get_latest_weekly()
        if not data:
            return JSONResponse({"ok": False, "message": "No weekly report yet. Trigger via /fb_weekly or wait for Monday 09:00."})
        return JSONResponse({"ok": True, "report": data})

    @app.get("/api/analytics/monthly")
    async def api_analytics_monthly():
        """Get latest monthly analytics report (JSON for dashboard)."""
        data = get_latest_monthly()
        if not data:
            return JSONResponse({"ok": False, "message": "No monthly report yet. Trigger via /fb_monthly or wait for 1st of month."})
        return JSONResponse({"ok": True, "report": data})

    @app.get("/api/analytics/test-weekly")
    async def api_test_weekly():
        """Trigger weekly report manually (for testing)."""
        try:
            detail = await asyncio.to_thread(run_weekly_report)
            return JSONResponse({"ok": True, "message": "Weekly analytics report sent to Telegram", "posts": detail.get("distribution", {}).get("total_posts", 0)})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.get("/api/analytics/test-monthly")
    async def api_test_monthly():
        """Trigger monthly report manually (for testing)."""
        try:
            detail = await asyncio.to_thread(run_monthly_report)
            return JSONResponse({"ok": True, "message": "Monthly analytics report sent to Telegram", "posts": detail.get("distribution", {}).get("total_posts", 0)})
        except Exception as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    print("[FBAnalytics] API endpoints registered: /api/analytics/*")

    # -----------------------------------------------------------------------
    # Background loops
    # -----------------------------------------------------------------------
    asyncio.create_task(weekly_report_loop())
    asyncio.create_task(monthly_report_loop())

    print("[FBAnalytics] Scheduling loops started (weekly Mon 09:00, monthly 1st 09:00)")
