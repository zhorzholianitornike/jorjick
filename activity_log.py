#!/usr/bin/env python3
"""
Activity logging system for News Card Bot.

Primary storage: Google Sheets (persistent across Railway restarts).
Fallback: local JSON file (data/activity_log.json).
Thread-safe via threading.Lock.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# Tbilisi timezone
TBILISI = timezone(timedelta(hours=4))

# Google Sheet config
SHEET_ID = "1oTom_4hmc8-qFgEhtdeNc3Iype9gY8V7taKGKwmR3Vo"
SHEET_NAME = "Sheet1"

# Local fallback storage
DATA_DIR = Path(__file__).parent / "data"
LOG_FILE = DATA_DIR / "activity_log.json"

# Column headers for Google Sheet
HEADERS = ["id", "timestamp", "published_at", "source", "title",
           "status", "facebook_post_id", "card_image_url", "caption",
           "likes", "comments", "shares", "reach"]

_lock = threading.Lock()
_logs: list[dict] = []
_gs_client = None   # gspread client (lazy init)
_gs_sheet = None     # gspread worksheet (lazy init)


# ---------------------------------------------------------------------------
# Google Sheets connection
# ---------------------------------------------------------------------------
def _get_sheet():
    """Get or create gspread worksheet connection."""
    global _gs_client, _gs_sheet
    if _gs_sheet is not None:
        return _gs_sheet

    creds_json = os.environ.get("GOOGLE_SHEETS_CREDS")
    if not creds_json:
        return None

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        # Parse creds from env var (JSON string or base64)
        try:
            creds_data = json.loads(creds_json)
        except json.JSONDecodeError:
            import base64
            creds_data = json.loads(base64.b64decode(creds_json))

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)
        _gs_client = gspread.authorize(credentials)
        spreadsheet = _gs_client.open_by_key(SHEET_ID)

        # Get or create worksheet
        try:
            _gs_sheet = spreadsheet.worksheet(SHEET_NAME)
        except gspread.WorksheetNotFound:
            _gs_sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows=1000, cols=len(HEADERS))

        # Ensure headers exist
        existing = _gs_sheet.row_values(1)
        if not existing or existing[0] != HEADERS[0]:
            _gs_sheet.update("A1", [HEADERS])

        print(f"[ActivityLog] Google Sheets connected: {SHEET_ID}")
        return _gs_sheet

    except Exception as e:
        print(f"[ActivityLog] Google Sheets init failed: {e} — using local JSON")
        return None


_sheet_formatted = False


def format_sheet():
    """Apply professional formatting to Google Sheet (idempotent per process)."""
    global _sheet_formatted
    if _sheet_formatted:
        return
    try:
        sheet = _get_sheet()
        if sheet is None:
            return

        spreadsheet = sheet.spreadsheet
        sheet_id = sheet._properties['sheetId']

        # Header styling
        header_range = f"A1:{chr(64 + len(HEADERS))}1"
        sheet.format(header_range, {
            "backgroundColor": {"red": 0.12, "green": 0.14, "blue": 0.22},
            "textFormat": {"bold": True, "foregroundColor": {"red": 0.9, "green": 0.93, "blue": 0.96}},
            "horizontalAlignment": "CENTER",
        })

        requests_body = []

        # Column widths
        col_widths = [120, 180, 180, 130, 300, 100, 150, 250, 300, 80, 80, 80, 80]
        for i, w in enumerate(col_widths):
            requests_body.append({
                "updateDimensionProperties": {
                    "range": {"sheetId": sheet_id, "dimension": "COLUMNS", "startIndex": i, "endIndex": i + 1},
                    "properties": {"pixelSize": w},
                    "fields": "pixelSize",
                }
            })

        # Conditional formatting: approved = green
        status_col = HEADERS.index("status")
        requests_body.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": status_col, "endColumnIndex": status_col + 1}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "approved"}]},
                        "format": {"backgroundColor": {"red": 0.2, "green": 0.5, "blue": 0.2},
                                   "textFormat": {"foregroundColor": {"red": 0.29, "green": 0.87, "blue": 0.5}}},
                    },
                },
                "index": 0,
            }
        })

        # Conditional formatting: rejected = red
        requests_body.append({
            "addConditionalFormatRule": {
                "rule": {
                    "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": status_col, "endColumnIndex": status_col + 1}],
                    "booleanRule": {
                        "condition": {"type": "TEXT_EQ", "values": [{"userEnteredValue": "rejected"}]},
                        "format": {"backgroundColor": {"red": 0.5, "green": 0.15, "blue": 0.15},
                                   "textFormat": {"foregroundColor": {"red": 0.97, "green": 0.44, "blue": 0.44}}},
                    },
                },
                "index": 1,
            }
        })

        # Auto-filter on headers
        requests_body.append({
            "setBasicFilter": {
                "filter": {"range": {"sheetId": sheet_id, "startRowIndex": 0, "startColumnIndex": 0, "endColumnIndex": len(HEADERS)}}
            }
        })

        # Freeze header row
        requests_body.append({
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        })

        spreadsheet.batch_update({"requests": requests_body})
        _sheet_formatted = True
        print("[ActivityLog] Sheet formatting applied")

    except Exception as e:
        print(f"[ActivityLog] format_sheet error: {e}")


def _gs_append(entry: dict):
    """Append a row to Google Sheet (non-blocking, ignore errors)."""
    try:
        sheet = _get_sheet()
        if sheet is None:
            return
        row = [str(entry.get(h, "") or "") for h in HEADERS]
        sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"[ActivityLog] GSheets append error: {e}")


def _gs_update_row(log_id: str, updates: dict):
    """Find and update a row in Google Sheet by ID."""
    try:
        sheet = _get_sheet()
        if sheet is None:
            return
        cell = sheet.find(log_id, in_column=1)
        if cell:
            row_num = cell.row
            for key, value in updates.items():
                if key in HEADERS:
                    col_idx = HEADERS.index(key) + 1
                    sheet.update_cell(row_num, col_idx, str(value or ""))
    except Exception as e:
        print(f"[ActivityLog] GSheets update error: {e}")


def _gs_load_all() -> list[dict]:
    """Load all entries from Google Sheet."""
    try:
        sheet = _get_sheet()
        if sheet is None:
            return []
        rows = sheet.get_all_records()
        print(f"[ActivityLog] Loaded {len(rows)} entries from Google Sheets")
        return rows
    except Exception as e:
        print(f"[ActivityLog] GSheets load error: {e}")
        return []


# ---------------------------------------------------------------------------
# Local JSON storage (fallback)
# ---------------------------------------------------------------------------
def _load_local():
    """Load logs from local JSON file."""
    global _logs
    DATA_DIR.mkdir(exist_ok=True)
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r", encoding="utf-8") as f:
                _logs = json.load(f)
            print(f"[ActivityLog] Loaded {len(_logs)} entries from local JSON")
        except Exception as e:
            print(f"[ActivityLog] Local load error: {e}")
            _logs = []
    else:
        _logs = []


def _save_local():
    """Persist logs to local JSON (called under lock)."""
    try:
        DATA_DIR.mkdir(exist_ok=True)
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(_logs, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[ActivityLog] Local save error: {e}")


# ---------------------------------------------------------------------------
# Startup: load from Google Sheets first, fallback to local JSON
# ---------------------------------------------------------------------------
def _startup():
    """Load data on startup."""
    global _logs
    # Try Google Sheets first
    gs_data = _gs_load_all()
    if gs_data:
        _logs = gs_data
    else:
        _load_local()
    # Apply sheet formatting (idempotent)
    format_sheet()


_startup()


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
        "published_at": now if facebook_post_id else "",
        "source": source,
        "title": title,
        "status": status,
        "facebook_post_id": facebook_post_id or "",
        "card_image_url": card_image_url or "",
        "caption": caption or "",
        "likes": 0,
        "comments": 0,
        "shares": 0,
        "reach": 0,
    }

    with _lock:
        _logs.append(entry)
        _save_local()

    # Async write to Google Sheets (in background thread)
    threading.Thread(target=_gs_append, args=(entry,), daemon=True).start()

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
                _save_local()
                # Async update Google Sheet
                threading.Thread(target=_gs_update_row, args=(log_id, kwargs), daemon=True).start()
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
        filtered = [e for e in filtered if e.get("source") == source]
    if status:
        filtered = [e for e in filtered if e.get("status") == status]
    if date_from:
        filtered = [e for e in filtered if e.get("timestamp", "") >= date_from]
    if date_to:
        filtered = [e for e in filtered if e.get("timestamp", "") <= date_to]

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
    today = sum(1 for e in all_logs if e.get("timestamp", "").startswith(today_str))
    week = sum(1 for e in all_logs if e.get("timestamp", "") >= week_ago)
    month = sum(1 for e in all_logs if e.get("timestamp", "") >= month_ago)

    approved = sum(1 for e in all_logs if e.get("status") == "approved")
    rejected = sum(1 for e in all_logs if e.get("status") == "rejected")
    published = sum(1 for e in all_logs if e.get("facebook_post_id"))

    by_source = {}
    for e in all_logs:
        src = e.get("source", "unknown")
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


def get_today_detail() -> dict:
    """Get today's breakdown: by_source, approved/rejected/published counts."""
    now = datetime.now(TBILISI)
    today_str = now.strftime("%Y-%m-%d")

    with _lock:
        today_logs = [e for e in _logs if str(e.get("timestamp", "")).startswith(today_str)]

    by_source = {}
    for e in today_logs:
        src = e.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    return {
        "total_today": len(today_logs),
        "by_source": by_source,
        "approved": sum(1 for e in today_logs if e.get("status") == "approved"),
        "rejected": sum(1 for e in today_logs if e.get("status") == "rejected"),
        "published": sum(1 for e in today_logs if e.get("facebook_post_id")),
    }


def get_top(limit: int = 10) -> list[dict]:
    """Get top posts (published ones, newest first). Ready for engagement sorting later."""
    with _lock:
        published = [e for e in _logs if e.get("facebook_post_id")]
    return list(reversed(published))[:limit]
