#!/usr/bin/env python3
"""
FastAPI web dashboard  +  Telegram bot — single Railway service.

• GET  /              → dashboard UI
• POST /api/generate  → upload photo + name + text → returns card
• GET  /api/history   → recent cards list
• GET  /api/status    → bot + stats

The Telegram bot starts as an asyncio background task on startup,
so both the web UI and the Telegram flow share the same card engine
and history list.

Env vars (set in Railway dashboard):
    PORT                  — assigned by Railway automatically
    TELEGRAM_BOT_TOKEN    — your Telegram bot token
"""

import asyncio
import json
import os
import uuid
import urllib3
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
import uvicorn

# Suppress SSL warnings (interpressnews.ge has cert issues)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from card_generator import CardGenerator, generate_auto_card
from facebook import post_photo, post_photo_ext, get_post_insights, get_page_stats, get_page_insights, get_post_reach, get_page_growth, get_page_views
from activity_log import log_activity, update_activity, get_logs, get_summary, get_top, get_today_detail, get_weekly_summary
from analytics.fb_scheduler import tg_fb_weekly, tg_fb_monthly
from setup_fonts import download as ensure_font

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
PORT              = int(os.environ.get("PORT", 8000))
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID")   # chat_id to receive FB upload status

TBILISI = timezone(timedelta(hours=4))   # Asia/Tbilisi — UTC+4, no DST

UPLOADS = Path("uploads")
CARDS   = Path("cards")
PHOTOS  = Path("photos")   # photo library folder
UPLOADS.mkdir(exist_ok=True)
CARDS.mkdir(exist_ok=True)
PHOTOS.mkdir(exist_ok=True)

logo = "logo.png" if os.path.exists("logo.png") else None
generator = CardGenerator(logo_path=logo)

# shared in-memory history (web + telegram write here)
history: list[dict] = []

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI()
app.mount("/cards", StaticFiles(directory=str(CARDS)), name="cards")
app.mount("/photos", StaticFiles(directory=str(PHOTOS)), name="photos")

# Voice generation directory
VOICES = Path("voices")
VOICES.mkdir(exist_ok=True)
app.mount("/voices", StaticFiles(directory=str(VOICES)), name="voices")


# ---------------------------------------------------------------------------
# Startup: Clone/Pull photos from GitHub (Railway)
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """On Railway startup: clone/pull photos from GitHub."""
    import subprocess
    import os

    github_token = os.environ.get("GITHUB_TOKEN")
    railway_env = os.environ.get("RAILWAY_ENVIRONMENT")

    # Only run on Railway with GITHUB_TOKEN
    if not railway_env or not github_token:
        print("[Startup] Not on Railway or no GITHUB_TOKEN - skipping git sync")
        return

    repo_url = f"https://zhorzholianitornike:{github_token}@github.com/zhorzholianitornike/jorjick.git"
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    git_dir = os.path.join(repo_dir, ".git")

    try:
        if not os.path.exists(git_dir):
            # Init git repo and add remote
            print("[Startup] Initializing git repo...")
            subprocess.run(["git", "init"], cwd=repo_dir, capture_output=True, timeout=5)
            subprocess.run(
                ["git", "remote", "add", "origin", repo_url],
                cwd=repo_dir, capture_output=True, timeout=5
            )

        # Configure git
        subprocess.run(
            ["git", "config", "user.name", "Railway Bot"],
            cwd=repo_dir, capture_output=True, timeout=5
        )
        subprocess.run(
            ["git", "config", "user.email", "bot@railway.app"],
            cwd=repo_dir, capture_output=True, timeout=5
        )

        # Fetch and sync photos from remote
        print("[Startup] Fetching from GitHub...")
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=repo_dir, check=True, capture_output=True, timeout=30
        )

        # Checkout only the photos/ directory from remote
        print("[Startup] Syncing photos...")
        subprocess.run(
            ["git", "checkout", "origin/main", "--", "photos/"],
            cwd=repo_dir, check=True, capture_output=True, timeout=15
        )
        print("[Startup] ✓ Photos synced from GitHub")

        PHOTOS.mkdir(exist_ok=True)
        print(f"[Startup] ✓ Photos directory ready")

    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else str(e.stderr)
        print(f"[Startup] ✗ Git operation failed: {stderr}")
    except Exception as e:
        print(f"[Startup] ✗ Error: {e}")


# ---------------------------------------------------------------------------
# Dashboard HTML  (single-page, no template engine needed)
# ---------------------------------------------------------------------------
DASHBOARD = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>News Card Bot</title>
<style>
  *            { margin:0; padding:0; box-sizing:border-box; }
  body         { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                 background:#0f1117; color:#e2e8f0; min-height:100vh; padding:36px 20px; }
  .wrap        { max-width:860px; margin:0 auto; }
  h1           { font-size:26px; color:#fff; }
  .sub         { color:#64748b; font-size:13px; margin-bottom:28px; }

  /* status bar */
  .stats       { display:flex; gap:12px; margin-bottom:28px; }
  .stat        { flex:1; background:#1e2030; border:1px solid #2d3148; border-radius:10px;
                 padding:14px 18px; }
  .stat .lbl   { font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.5px; }
  .stat .val   { font-size:20px; font-weight:600; margin-top:3px; }
  .green       { color:#4ade80; }

  /* form panel */
  .panel       { background:#1e2030; border:1px solid #2d3148; border-radius:12px;
                 padding:24px; margin-bottom:28px; }
  .panel h2   { font-size:16px; color:#fff; margin-bottom:18px; }

  /* upload zone */
  .drop        { border:2px dashed #2d3148; border-radius:9px; padding:28px; text-align:center;
                 cursor:pointer; transition:border-color .2s, background .2s; }
  .drop:hover, .drop.over { border-color:#1e94b9; background:#151620; }
  .drop .ico   { font-size:26px; }
  .drop p      { color:#64748b; font-size:13px; margin-top:6px; }
  .drop img    { max-width:180px; max-height:120px; border-radius:7px; margin-top:10px; display:none; }

  /* inputs */
  .row         { display:flex; gap:14px; margin-top:14px; }
  .row label   { display:block; font-size:12px; color:#94a3b8; margin-bottom:5px; }
  .row .g      { flex:1; }
  .row input, .row textarea {
                 width:100%; background:#151620; border:1px solid #2d3148; border-radius:7px;
                 padding:9px 12px; color:#e2e8f0; font-size:14px; outline:none;
                 transition:border-color .2s; font-family:inherit; }
  .row input:focus, .row textarea:focus { border-color:#1e94b9; }
  .row textarea { min-height:64px; resize:vertical; }

  /* buttons */
  .btn         { margin-top:18px; width:100%; padding:11px; background:#1e94b9; color:#fff;
                 border:none; border-radius:7px; font-size:15px; font-weight:600;
                 cursor:pointer; transition:background .2s; }
  .btn:hover   { background:#1a7fa0; }
  .btn:disabled{ background:#2d3148; color:#64748b; cursor:not-allowed; }

  /* spinner */
  .spin        { width:32px; height:32px; border:3px solid #2d3148; border-top-color:#1e94b9;
                 border-radius:50%; animation:sp .5s linear infinite; margin:18px auto; display:none; }
  @keyframes sp{ to{ transform:rotate(360deg); } }

  /* result */
  .result      { text-align:center; margin-top:16px; display:none; }
  .result img  { max-width:100%; border-radius:9px; border:1px solid #2d3148; }
  .dl          { display:inline-block; margin-top:10px; color:#1e94b9; font-size:13px;
                 cursor:pointer; text-decoration:none; }
  .dl:hover    { text-decoration:underline; }

  /* facebook button */
  .btn-fb      { margin-top:12px; padding:10px 20px; background:#1877f2; color:#fff;
                 border:none; border-radius:7px; font-size:14px; font-weight:600;
                 cursor:pointer; transition:background .2s; }
  .btn-fb:hover{ background:#166fe5; }
  .btn-fb:disabled { background:#2d3148; color:#64748b; cursor:not-allowed; }
  .btn-fb.done { background:#4ade80; }
  .btn-fb.fail { background:#ef4444; }

  /* toast */
  .toast       { position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
                 background:#ef4444; color:#fff; padding:12px 22px; border-radius:8px;
                 font-size:14px; display:none; z-index:99; }
  .toast.success { background:#16a34a; }

  /* photo library */
  .lib-label   { font-size:12px; color:#94a3b8; margin:16px 0 8px 0; display:flex; align-items:center; justify-content:space-between; }
  .lib-upload-btn { padding:5px 12px; background:#2d3148; color:#94a3b8; border:1px solid #3d4158;
                 border-radius:5px; font-size:11px; cursor:pointer; transition:all .2s; }
  .lib-upload-btn:hover { background:#3d4158; color:#e2e8f0; border-color:#4d5168; }
  .lib-grid    { display:grid; grid-template-columns:repeat(auto-fill,minmax(100px,1fr)); gap:10px; margin-bottom:16px; }
  .lib-item    { text-align:center; position:relative; }
  .lib-item img { width:100%; aspect-ratio:1; object-fit:cover; border-radius:6px;
                 border:2px solid transparent; transition:border-color .2s, transform .1s; cursor:pointer; }
  .lib-item:hover img { border-color:#1e94b9; transform:scale(1.02); }
  .lib-item.selected img { border-color:#4ade80; box-shadow:0 0 0 2px rgba(74,222,128,0.3); }
  .lib-item .lib-name { font-size:10px; color:#94a3b8; margin-top:4px; overflow:hidden;
                 text-overflow:ellipsis; white-space:nowrap; cursor:pointer; }
  .lib-actions { position:absolute; top:4px; right:4px; display:flex; gap:4px; z-index:10; }
  .lib-action-btn { width:24px; height:24px; border-radius:4px; border:none; cursor:pointer;
                 font-size:12px; display:flex; align-items:center; justify-content:center;
                 transition:all .2s; box-shadow:0 2px 4px rgba(0,0,0,0.3); }
  .lib-action-btn.rename { background:rgba(30,148,185,0.9); color:#fff; }
  .lib-action-btn.rename:hover { background:rgba(30,148,185,1); }
  .lib-action-btn.delete { background:rgba(239,68,68,0.9); color:#fff; }
  .lib-action-btn.delete:hover { background:rgba(239,68,68,1); }
  .lib-empty   { color:#64748b; font-size:12px; text-align:center; padding:20px;
                 background:#151620; border-radius:6px; }
  .or-divider  { text-align:center; color:#64748b; font-size:12px; margin:12px 0; }

  /* flow button */
  .flow-btn    { padding:6px 16px; background:#2d3148; color:#94a3b8; border:1px solid #3d4158;
                 border-radius:6px; font-size:13px; font-weight:600; cursor:pointer;
                 transition:all .2s; margin-left:12px; vertical-align:middle; }
  .flow-btn:hover { background:#3d4158; color:#fff; border-color:#1e94b9; }

  /* flow overlay */
  .flow-overlay { position:fixed; inset:0; background:rgba(10,12,20,0.95); z-index:100;
                  display:none; overflow:auto; }
  .flow-overlay.open { display:block; }
  .flow-header { display:flex; justify-content:space-between; align-items:center;
                 padding:20px 30px; border-bottom:1px solid #2d3148; }
  .flow-header h2 { font-size:20px; color:#fff; }
  .flow-close  { width:36px; height:36px; border-radius:8px; border:1px solid #3d4158;
                 background:#1e2030; color:#94a3b8; font-size:18px; cursor:pointer;
                 display:flex; align-items:center; justify-content:center; transition:all .2s; }
  .flow-close:hover { background:#ef4444; color:#fff; border-color:#ef4444; }

  /* flow canvas */
  .flow-canvas { position:relative; min-height:1200px; padding:40px; min-width:1200px; }

  /* flow nodes */
  .fnode        { position:absolute; width:160px; background:#1e2030; border:1px solid #2d3148;
                  border-radius:10px; overflow:hidden; box-shadow:0 4px 16px rgba(0,0,0,0.3);
                  transition:transform .15s, box-shadow .15s; }
  .fnode:hover  { transform:translateY(-2px); box-shadow:0 8px 24px rgba(0,0,0,0.5); }
  .fnode-head   { padding:8px 12px; font-size:11px; font-weight:700; text-transform:uppercase;
                  letter-spacing:.5px; }
  .fnode-body   { padding:10px 12px; }
  .fnode-icon   { font-size:20px; margin-bottom:4px; }
  .fnode-name   { font-size:12px; font-weight:600; color:#fff; }
  .fnode-desc   { font-size:10px; color:#64748b; margin-top:2px; }

  /* node colors */
  .fnode-blue .fnode-head   { background:#1e3a5f; color:#60a5fa; }
  .fnode-green .fnode-head  { background:#14532d; color:#4ade80; }
  .fnode-orange .fnode-head { background:#431407; color:#fb923c; }
  .fnode-purple .fnode-head { background:#3b0764; color:#c084fc; }
  .fnode-red .fnode-head    { background:#450a0a; color:#f87171; }
  .fnode-cyan .fnode-head   { background:#083344; color:#22d3ee; }

  /* flow lines SVG */
  .flow-svg     { position:absolute; top:0; left:0; width:100%; height:100%; pointer-events:none; }
  .flow-line    { fill:none; stroke:#3d4158; stroke-width:2; }
  .flow-line-active { stroke:#1e94b9; stroke-dasharray:6 4; animation:flowdash 1s linear infinite; }
  @keyframes flowdash { to { stroke-dashoffset:-10; } }

  /* flow legend */
  .flow-legend  { display:flex; gap:16px; padding:16px 30px; border-top:1px solid #2d3148;
                  flex-wrap:wrap; }
  .flow-leg-item { display:flex; align-items:center; gap:6px; font-size:11px; color:#94a3b8; }
  .flow-leg-dot { width:10px; height:10px; border-radius:3px; }

  /* history grid */
  .history h2  { font-size:16px; color:#fff; margin-bottom:14px; }
  .hgrid       { display:grid; grid-template-columns:repeat(auto-fill,minmax(170px,1fr)); gap:10px; }
  .hcard       { background:#1e2030; border:1px solid #2d3148; border-radius:9px;
                 overflow:hidden; cursor:pointer; transition:border-color .2s; }
  .hcard:hover { border-color:#1e94b9; }
  .hcard img   { width:100%; display:block; }
  .hcard .inf  { padding:9px 11px; }
  .hcard .inf .n { font-size:13px; font-weight:600; color:#fff; }
  .hcard .inf .t { font-size:11px; color:#64748b; margin-top:2px; }
  /* analytics panel */
  .a-grid   { display:grid; grid-template-columns:repeat(auto-fill,minmax(130px,1fr)); gap:10px; margin-bottom:18px; }
  .a-card   { background:#151620; border:1px solid #2d3148; border-radius:8px; padding:14px; text-align:center; }
  .a-card .av { font-size:22px; font-weight:700; color:#1e94b9; }
  .a-card .al { font-size:11px; color:#94a3b8; margin-top:4px; text-transform:uppercase; letter-spacing:.3px; }
  .a-src    { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:18px; }
  .a-src-tag { padding:6px 14px; background:#151620; border:1px solid #2d3148; border-radius:20px; font-size:12px; color:#e2e8f0; }
  .a-src-tag .cnt { font-weight:700; color:#1e94b9; margin-left:4px; }
  .a-filters { display:flex; gap:10px; margin-bottom:12px; flex-wrap:wrap; }
  .a-filters select { background:#151620; border:1px solid #2d3148; border-radius:7px; padding:8px 12px; color:#e2e8f0; font-size:13px; outline:none; }
  .a-tbl    { width:100%; border-collapse:collapse; font-size:12px; margin-top:8px; }
  .a-tbl th { text-align:left; padding:8px 10px; color:#94a3b8; border-bottom:1px solid #2d3148; font-size:11px; text-transform:uppercase; }
  .a-tbl td { padding:8px 10px; border-bottom:1px solid #1a1c2e; color:#cbd5e1; }
  .a-tbl tr:hover td { background:#151620; }
  .st-badge { padding:3px 8px; border-radius:4px; font-size:11px; font-weight:600; }
  .st-ok  { background:rgba(74,222,128,0.15); color:#4ade80; }
  .st-no  { background:rgba(248,113,113,0.15); color:#f87171; }
  .st-wait { background:rgba(251,191,36,0.15); color:#fbbf24; }
  /* fb insights */
  .fb-section { border-top:1px solid #2d3148; padding-top:16px; margin-top:16px; }
  .fb-section h3 { font-size:14px; color:#1877f2; margin-bottom:12px; }
  .fb-stats { display:grid; grid-template-columns:repeat(auto-fill,minmax(140px,1fr)); gap:10px; margin-bottom:14px; }
  .fb-stat { background:#151620; border:1px solid #2d3148; border-radius:8px; padding:12px; text-align:center; }
  .fb-stat .fv { font-size:20px; font-weight:700; color:#1877f2; }
  .fb-stat .fl { font-size:11px; color:#94a3b8; margin-top:3px; }
  .fb-top { margin-top:10px; }
  .fb-top-item { display:flex; justify-content:space-between; align-items:center; padding:8px 10px; border-bottom:1px solid #1a1c2e; font-size:12px; }
  .fb-top-item:hover { background:#151620; }
  .fb-top-title { color:#cbd5e1; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-right:12px; }
  .fb-top-eng { display:flex; gap:10px; color:#94a3b8; font-size:11px; white-space:nowrap; }
  .fb-top-eng span { color:#1877f2; font-weight:600; }
  .fb-reactions { display:flex; gap:12px; flex-wrap:wrap; margin:10px 0; }
  .fb-rx { background:#151620; border:1px solid #2d3148; border-radius:20px; padding:6px 14px; font-size:12px; color:#e2e8f0; }
  .fb-rx .rx-n { font-weight:700; color:#1877f2; margin-left:4px; }
  .fb-growth { display:inline-block; font-size:12px; font-weight:600; margin-left:6px; }
  .fb-growth.pos { color:#4ade80; }
  .fb-growth.neg { color:#f87171; }
  .fb-insight-row { display:flex; gap:10px; flex-wrap:wrap; margin:10px 0; }
  .fb-insight-card { background:#151620; border:1px solid #2d3148; border-radius:8px; padding:10px 14px; flex:1; min-width:120px; }
  .fb-insight-card .fic-v { font-size:18px; font-weight:700; color:#e2e8f0; }
  .fb-insight-card .fic-l { font-size:10px; color:#64748b; margin-top:2px; }
  .fb-src-perf { margin:10px 0; }
  .fb-src-row { display:flex; justify-content:space-between; padding:6px 10px; border-bottom:1px solid #1a1c2e; font-size:12px; }
  .fb-src-row:hover { background:#151620; }
  .fb-src-name { color:#cbd5e1; }
  .fb-src-val { color:#1877f2; font-weight:600; }
</style>
</head>
<body>
<div class="wrap">
  <h1>News Card Bot <button class="flow-btn" onclick="toggleFlow()">⚡ FLOW</button> <a href="/analytics" class="flow-btn" style="text-decoration:none">📊 Analytics</a></h1>
  <p class="sub">BBC / CNN style news cards — Web &amp; Telegram</p>

  <div class="stats">
    <div class="stat">
      <div class="lbl">Telegram</div>
      <div class="val green" id="s-bot">● Running</div>
    </div>
    <div class="stat">
      <div class="lbl">Cards Created</div>
      <div class="val" id="s-count">0</div>
    </div>
  </div>

  <!-- generate form -->
  <div class="panel">
    <h2>1 — ქარდის შექმნა</h2>

    <div class="lib-label">
      <span>📁 ფოტო ბიბლიოთეკა</span>
      <button class="lib-upload-btn" onclick="document.getElementById('lib-fi').click()">📤 ფოტო ატვირთე</button>
      <input type="file" id="lib-fi" accept="image/*" style="display:none">
    </div>
    <div class="lib-grid" id="lib-grid">
      <div class="lib-empty">ფოტოები არ არის</div>
    </div>

    <div class="or-divider">— ან ატვირთე ახალი —</div>

    <div class="drop" id="drop">
      <div class="ico">📷</div>
      <p>ფოტოს ატვირთვა</p>
      <input type="file" id="fi" accept="image/*" style="display:none">
      <img id="prev" alt="">
    </div>

    <div class="row">
      <div class="g"><label>სახელი</label>
        <input id="inp-name" placeholder="სახელი გვარი">
      </div>
    </div>
    <div class="row">
      <div class="g"><label>ტექსტი</label>
        <textarea id="inp-text" placeholder="ტექსტი..."></textarea>
      </div>
    </div>

    <button class="btn" id="btn-gen" onclick="gen()">ქარდის გენერაცია</button>
    <div class="spin" id="spin"></div>

    <div class="result" id="res">
      <img id="res-img" alt="">
      <br>
      <a class="dl" id="res-dl" href="" download="card.jpg">⬇ Download</a>
      <br>
      <button class="btn-fb" id="btn-fb" onclick="uploadFB('res')">📘 Upload to Facebook</button>
    </div>
  </div>

  <!-- auto-generate panel -->
  <div class="panel">
    <h2>2 — ავტომატური ქარდი <span style="font-size:11px;color:#64748b;font-weight:400" id="ai-badge">[Tavily + Gemini 3 Flash]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">Tavily Search → Gemini 3 Flash Preview → Card → Facebook</p>
    <div class="row">
      <div class="g"><label>თემა</label>
        <input id="inp-theme" placeholder="AI სიახლეები, პოლიტიკა, სპორტი...">
      </div>
    </div>
    <button class="btn" id="btn-auto" onclick="autoGen()">გენერაცია</button>
    <div class="spin" id="spin-auto"></div>
    <div class="result" id="res-auto">
      <img id="res-auto-img" alt="" style="max-width:400px">
      <br>
      <a class="dl" id="res-auto-dl" href="" download="auto_card.jpg">⬇ Download</a>
      <br>
      <button class="btn-fb" id="btn-fb-auto" onclick="uploadFB('res-auto')">📘 Upload to Facebook</button>
    </div>
    <div id="auto-article" style="display:none;margin-top:16px;background:#151620;border:1px solid #2d3148;border-radius:8px;padding:20px;">
      <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">სტატია</div>
      <h3 id="auto-article-title" style="font-size:18px;color:#fff;margin-bottom:12px"></h3>
      <div id="auto-article-text" style="font-size:14px;color:#cbd5e1;line-height:1.7;white-space:pre-wrap"></div>
      <button onclick="copyArticle()" style="margin-top:12px;padding:8px 16px;background:#2d3148;color:#94a3b8;border:1px solid #3d4158;border-radius:5px;font-size:12px;cursor:pointer">📋 კოპირება</button>
    </div>
    <div id="auto-log" style="margin-top:14px;font-size:12px;line-height:1.8;max-height:160px;overflow-y:auto;background:#151620;border-radius:6px;padding:8px 12px"></div>
  </div>

  <!-- voice generation panel -->
  <div class="panel">
    <h2>3 — ხმოვანი გენერაცია 🎙️ <span style="font-size:11px;color:#64748b;font-weight:400">[Gemini TTS]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">ქართული ტექსტი → Gemini TTS → WAV Audio</p>

    <div class="row">
      <div class="g"><label>ტექსტი (ქართულად)</label>
        <textarea id="inp-voice-text" placeholder="შეიყვანეთ ტექსტი ქართულად...&#10;მაგალითი: გამარჯობა, ეს არის ხმოვანი გენერაცია." style="min-height:100px"></textarea>
      </div>
    </div>

    <div class="row">
      <div class="g"><label>ხმა</label>
        <select id="sel-voice" style="width:100%; background:#151620; border:1px solid #2d3148; border-radius:7px; padding:9px 12px; color:#e2e8f0; font-size:14px;">
          <option value="Charon">Charon (მამაკაცი - ინფორმატიული)</option>
          <option value="Kore">Kore (ქალი - მკაფიო)</option>
          <option value="Puck">Puck (მამაკაცი - ენერგიული)</option>
          <option value="Fenrir">Fenrir (მამაკაცი - ექსპრესიული)</option>
        </select>
      </div>
    </div>

    <div style="margin-top:8px;font-size:11px;color:#64748b;">
      <span>სიმბოლოები: </span><span id="char-count">0</span><span> / 5000 (ლიმიტი ერთ voice-over-ზე)</span>
    </div>

    <button class="btn" id="btn-voice" onclick="generateVoice()">🎙️ ხმის გენერაცია</button>
    <div class="spin" id="spin-voice"></div>

    <div class="result" id="res-voice">
      <audio id="audio-player" controls style="width:100%;max-width:400px;margin-top:16px;display:none;"></audio>
      <br>
      <a class="dl" id="res-voice-dl" href="" download="voice.wav" style="display:none;">⬇️ Download Audio</a>
    </div>
  </div>

  <!-- news auto-scraper control panel -->
  <div class="panel">
    <h2>4 — ავტო-სიახლეები 📰 <span style="font-size:11px;color:#64748b;font-weight:400">[interpressnews.ge]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">interpressnews.ge/politika → Telegram დასტური → Facebook</p>

    <div class="row">
      <div class="g"><label>ინტერვალი (წუთებში)</label>
        <div style="display:flex;gap:8px;align-items:center;">
          <input type="number" id="inp-news-interval" min="5" max="1440" value="15"
            style="width:100px;background:#151620;border:1px solid #2d3148;border-radius:7px;padding:9px 12px;color:#e2e8f0;font-size:16px;text-align:center;">
          <span style="color:#64748b;font-size:12px;" id="interval-label">ყოველ 15 წუთში</span>
        </div>
      </div>
    </div>

    <div style="display:flex;gap:8px;margin-top:4px;flex-wrap:wrap;">
      <button onclick="setNewsInterval(5)" style="background:#2d3148;border:none;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">5 წთ</button>
      <button onclick="setNewsInterval(15)" style="background:#2d3148;border:none;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">15 წთ</button>
      <button onclick="setNewsInterval(30)" style="background:#2d3148;border:none;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">30 წთ</button>
      <button onclick="setNewsInterval(45)" style="background:#2d3148;border:none;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">45 წთ</button>
      <button onclick="setNewsInterval(60)" style="background:#2d3148;border:none;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">1 სთ</button>
      <button onclick="setNewsInterval(120)" style="background:#2d3148;border:none;color:#94a3b8;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:12px;">2 სთ</button>
    </div>

    <div style="display:flex;gap:8px;margin-top:12px;">
      <button class="btn" onclick="applyNewsInterval()" style="flex:1;">⏱ ინტერვალის შეცვლა</button>
      <button class="btn" onclick="sendTestNews()" style="flex:1;background:#1a5c2e;">📰 სატესტო გაგზავნა</button>
    </div>
    <div class="spin" id="spin-news"></div>
    <div class="result" id="res-news"></div>
  </div>

  <!-- RSS source management panel -->
  <div class="panel">
    <h2>5 — RSS წყაროების მართვა 📡 <span style="font-size:11px;color:#64748b;font-weight:400">[International News]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">RSS Feeds → Gemini თარგმანი → Telegram დასტური → Facebook</p>

    <!-- Existing sources table -->
    <div style="overflow-x:auto;margin-bottom:14px;">
      <table id="rss-table" style="width:100%;border-collapse:collapse;font-size:13px;">
        <thead>
          <tr style="border-bottom:1px solid #2d3148;text-align:left;">
            <th style="padding:8px;color:#94a3b8;">სახელი</th>
            <th style="padding:8px;color:#94a3b8;">კატეგორია</th>
            <th style="padding:8px;color:#94a3b8;">ინტერვალი</th>
            <th style="padding:8px;color:#94a3b8;">სტატუსი</th>
            <th style="padding:8px;color:#94a3b8;"></th>
          </tr>
        </thead>
        <tbody id="rss-tbody"></tbody>
      </table>
    </div>

    <!-- Add new source -->
    <div style="border-top:1px solid #2d3148;padding-top:14px;">
      <p style="color:#e2e8f0;font-size:13px;margin-bottom:8px;font-weight:600;">ახალი წყაროს დამატება</p>
      <div class="row">
        <div class="g" style="flex:2"><label>სახელი</label>
          <input id="rss-new-name" placeholder="მაგ: BBC World">
        </div>
        <div class="g" style="flex:1"><label>კატეგორია</label>
          <input id="rss-new-cat" placeholder="მაგ: World" value="World">
        </div>
      </div>
      <div class="row">
        <div class="g" style="flex:3"><label>RSS URL</label>
          <input id="rss-new-url" placeholder="https://feeds.bbci.co.uk/news/world/rss.xml">
        </div>
        <div class="g" style="flex:1"><label>ინტერვალი (წთ)</label>
          <input type="number" id="rss-new-interval" value="30" min="5" max="1440" style="text-align:center;">
        </div>
      </div>
      <button class="btn" onclick="addRssSource()" style="margin-top:4px;">➕ წყაროს დამატება</button>
    </div>

    <!-- Min interval between posts -->
    <div style="border-top:1px solid #2d3148;padding-top:14px;margin-top:14px;">
      <div class="row" style="align-items:center;">
        <div class="g" style="flex:2">
          <label>მინ. დრო პოსტებს შორის (წუთი)</label>
          <div style="display:flex;gap:8px;align-items:center;">
            <input type="number" id="rss-min-interval" value="30" min="5" max="1440"
              style="width:80px;background:#151620;border:1px solid #2d3148;border-radius:7px;padding:9px 12px;color:#e2e8f0;font-size:16px;text-align:center;">
            <button class="btn" onclick="setRssMinInterval()" style="padding:8px 16px;margin-top:0;width:auto;">შეცვლა</button>
            <span style="color:#64748b;font-size:12px;" id="rss-queue-info">რიგში: 0</span>
          </div>
        </div>
      </div>
    </div>

    <button class="btn" onclick="sendTestRss()" style="margin-top:8px;background:#1a5c2e;">📡 სატესტო RSS გაგზავნა</button>
    <div class="spin" id="spin-rss"></div>
    <div class="result" id="res-rss"></div>
  </div>

  <!-- analytics panel -->
  <div class="panel">
    <h2>6 — ანალიტიკა 📊 <span style="font-size:11px;color:#64748b;font-weight:400">[Activity Log]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">აქტივობის სტატისტიკა და ლოგები</p>
    <button class="btn" data-action="load-analytics" style="margin-top:0;margin-bottom:18px;">🔄 სტატისტიკის განახლება</button>
    <div class="spin" id="spin-analytics"></div>

    <div class="a-grid" id="a-grid">
      <div class="a-card"><div class="av" id="a-today">-</div><div class="al">დღეს</div></div>
      <div class="a-card"><div class="av" id="a-week">-</div><div class="al">კვირა</div></div>
      <div class="a-card"><div class="av" id="a-month">-</div><div class="al">თვე</div></div>
      <div class="a-card"><div class="av" id="a-total">-</div><div class="al">სულ</div></div>
      <div class="a-card"><div class="av" id="a-approved" style="color:#4ade80">-</div><div class="al">დამტკიცებული</div></div>
      <div class="a-card"><div class="av" id="a-rejected" style="color:#f87171">-</div><div class="al">უარყოფილი</div></div>
      <div class="a-card"><div class="av" id="a-published" style="color:#1877f2">-</div><div class="al">გამოქვეყნებული</div></div>
    </div>

    <div style="font-size:12px;color:#94a3b8;margin-bottom:6px;">წყაროების მიხედვით:</div>
    <div class="a-src" id="a-src"></div>

    <div class="fb-section">
      <h3>📘 Facebook Insights</h3>
      <div class="fb-stats">
        <div class="fb-stat"><div class="fv" id="fb-followers">—</div><div class="fl">მიმდევრები <span class="fb-growth" id="fb-growth-badge"></span></div></div>
        <div class="fb-stat"><div class="fv" id="fb-fans">—</div><div class="fl">ფანები</div></div>
        <div class="fb-stat"><div class="fv" id="fb-impressions">—</div><div class="fl">შთაბეჭდილებები</div></div>
        <div class="fb-stat"><div class="fv" id="fb-engagements">—</div><div class="fl">ჩართულობა</div></div>
      </div>
      <div class="fb-insight-row">
        <div class="fb-insight-card"><div class="fic-v" id="fb-eng-rate">—</div><div class="fic-l">Engagement Rate</div></div>
        <div class="fb-insight-card"><div class="fic-v" id="fb-page-views">—</div><div class="fic-l">გვერდის ნახვები</div></div>
        <div class="fb-insight-card"><div class="fic-v" id="fb-avg-eng">—</div><div class="fic-l">საშ. ჩართულობა</div></div>
        <div class="fb-insight-card"><div class="fic-v" id="fb-week-reach">—</div><div class="fic-l">კვირის Reach</div></div>
      </div>
      <p style="color:#94a3b8;font-size:11px;margin-bottom:4px;">რეაქციები (კვირა):</p>
      <div class="fb-reactions" id="fb-reactions-row">
        <div class="fb-rx">❤️ <span class="rx-n" id="fb-rx-love">0</span></div>
        <div class="fb-rx">😂 <span class="rx-n" id="fb-rx-haha">0</span></div>
        <div class="fb-rx">😮 <span class="rx-n" id="fb-rx-wow">0</span></div>
        <div class="fb-rx">😢 <span class="rx-n" id="fb-rx-sad">0</span></div>
        <div class="fb-rx">😠 <span class="rx-n" id="fb-rx-angry">0</span></div>
      </div>
      <p style="color:#94a3b8;font-size:11px;margin-bottom:4px;" id="fb-best-hour-label">🎯 საუკეთესო დრო: —</p>
      <p style="color:#94a3b8;font-size:11px;margin-bottom:8px;">📈 წყაროების ეფექტურობა:</p>
      <div class="fb-src-perf" id="fb-src-perf"></div>
      <button class="btn" data-action="fb-refresh" style="margin-bottom:12px;font-size:12px;padding:8px 16px;">🔄 Engagement განახლება</button>
      <div class="spin" id="spin-fb" style="display:none;"></div>
      <div id="fb-refresh-msg" style="font-size:12px;color:#4ade80;display:none;margin-bottom:10px;"></div>
      <p style="color:#94a3b8;font-size:12px;margin-bottom:6px;">ტოპ პოსტები (engagement):</p>
      <div class="fb-top" id="fb-top-list"></div>
    </div>

    <div style="border-top:1px solid #2d3148;padding-top:14px;margin-top:8px;">
      <p style="color:#e2e8f0;font-size:13px;margin-bottom:8px;font-weight:600;">აქტივობის ლოგი</p>
      <div class="a-filters">
        <select id="a-fsrc" data-action="filter-analytics">
          <option value="">ყველა წყარო</option>
          <option value="interpressnews">interpressnews</option>
          <option value="rss_cnn">RSS CNN</option>
          <option value="rss_bbc">RSS BBC</option>
          <option value="rss_other">RSS Other</option>
          <option value="manual">manual</option>
          <option value="auto_card">auto_card</option>
        </select>
        <select id="a-fst" data-action="filter-analytics">
          <option value="">ყველა სტატუსი</option>
          <option value="approved">დამტკიცებული</option>
          <option value="rejected">უარყოფილი</option>
          <option value="pending">მოლოდინში</option>
        </select>
      </div>
      <div style="overflow-x:auto;">
        <table class="a-tbl">
          <thead><tr><th>დრო</th><th>წყარო</th><th>სათაური</th><th>სტატუსი</th><th>FB</th></tr></thead>
          <tbody id="a-tbody"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- history -->
  <div class="history">
    <h2>Recent Cards</h2>
    <div class="hgrid" id="hgrid"></div>
  </div>
</div>

<!-- FLOW OVERLAY -->
<div class="flow-overlay" id="flow-overlay">
  <div class="flow-header">
    <h2>⚡ Agent Architecture Flow</h2>
    <button class="flow-close" onclick="toggleFlow()">✕</button>
  </div>
  <div style="overflow:auto;flex:1;">
    <div class="flow-canvas" id="flow-canvas">
      <svg class="flow-svg" id="flow-svg"></svg>

      <!-- ROW 1: Manual Card -->
      <div class="fnode fnode-blue" style="left:40px;top:30px" id="fn-dash1">
        <div class="fnode-head">INPUT</div>
        <div class="fnode-body"><div class="fnode-icon">🖥️</div><div class="fnode-name">Dashboard</div><div class="fnode-desc">ვებ ინტერფეისი</div></div>
      </div>
      <div class="fnode fnode-blue" style="left:240px;top:30px" id="fn-photo">
        <div class="fnode-head">DATA</div>
        <div class="fnode-body"><div class="fnode-icon">📷</div><div class="fnode-name">Photo + Text</div><div class="fnode-desc">ფოტო, სახელი, ტექსტი</div></div>
      </div>
      <div class="fnode fnode-green" style="left:440px;top:30px" id="fn-cardgen">
        <div class="fnode-head">PROCESS</div>
        <div class="fnode-body"><div class="fnode-icon">🃏</div><div class="fnode-name">Card Generator</div><div class="fnode-desc">Playwright render</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:640px;top:30px" id="fn-card1">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">🖼️</div><div class="fnode-name">Card Image</div><div class="fnode-desc">JPG 1080×1350</div></div>
      </div>
      <div class="fnode fnode-red" style="left:840px;top:30px" id="fn-fb1">
        <div class="fnode-head">PUBLISH</div>
        <div class="fnode-body"><div class="fnode-icon">📘</div><div class="fnode-name">Facebook</div><div class="fnode-desc">ავტო-ატვირთვა</div></div>
      </div>

      <!-- ROW 2: Auto Card -->
      <div class="fnode fnode-blue" style="left:40px;top:150px" id="fn-dash2">
        <div class="fnode-head">INPUT</div>
        <div class="fnode-body"><div class="fnode-icon">🖥️</div><div class="fnode-name">Theme Input</div><div class="fnode-desc">თემა / საძიებო</div></div>
      </div>
      <div class="fnode fnode-green" style="left:240px;top:150px" id="fn-tavily">
        <div class="fnode-head">SEARCH</div>
        <div class="fnode-body"><div class="fnode-icon">🔍</div><div class="fnode-name">Tavily Search</div><div class="fnode-desc">ნიუსების ძიება</div></div>
      </div>
      <div class="fnode fnode-green" style="left:440px;top:150px" id="fn-gemini">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🤖</div><div class="fnode-name">Gemini Flash</div><div class="fnode-desc">სტატია + სათაური</div></div>
      </div>
      <div class="fnode fnode-green" style="left:640px;top:150px" id="fn-imagen">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🎨</div><div class="fnode-name">Imagen 3</div><div class="fnode-desc">ფოტო გენერაცია</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:840px;top:150px" id="fn-card2">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">📰</div><div class="fnode-name">Auto Card</div><div class="fnode-desc">ქარდი + სტატია</div></div>
      </div>

      <!-- ROW 3: Voice TTS -->
      <div class="fnode fnode-blue" style="left:40px;top:270px" id="fn-dash3">
        <div class="fnode-head">INPUT</div>
        <div class="fnode-body"><div class="fnode-icon">📝</div><div class="fnode-name">Text Input</div><div class="fnode-desc">ქართული ტექსტი</div></div>
      </div>
      <div class="fnode fnode-green" style="left:300px;top:270px" id="fn-tts">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🎙️</div><div class="fnode-name">Gemini TTS</div><div class="fnode-desc">Charon voice</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:560px;top:270px" id="fn-wav">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">🔊</div><div class="fnode-name">WAV Audio</div><div class="fnode-desc">24kHz mono</div></div>
      </div>

      <!-- ROW 4: IPN Auto-News -->
      <div class="fnode fnode-cyan" style="left:40px;top:390px" id="fn-ipn">
        <div class="fnode-head">SCRAPER</div>
        <div class="fnode-body"><div class="fnode-icon">🇬🇪</div><div class="fnode-name">interpressnews</div><div class="fnode-desc">პოლიტიკა კატეგორია</div></div>
      </div>
      <div class="fnode fnode-green" style="left:240px;top:390px" id="fn-ipn-scrape">
        <div class="fnode-head">PROCESS</div>
        <div class="fnode-body"><div class="fnode-icon">🕷️</div><div class="fnode-name">BS4 Scraper</div><div class="fnode-desc">schema.org/Article</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:440px;top:390px" id="fn-ipn-tg">
        <div class="fnode-head">APPROVAL</div>
        <div class="fnode-body"><div class="fnode-icon">✅</div><div class="fnode-name">TG Approval</div><div class="fnode-desc">დადასტურება / უარყოფა</div></div>
      </div>
      <div class="fnode fnode-green" style="left:640px;top:390px" id="fn-ipn-caption">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🤖</div><div class="fnode-name">Gemini Caption</div><div class="fnode-desc">FB კაფშენი + ჰეშთეგი</div></div>
      </div>
      <div class="fnode fnode-red" style="left:840px;top:390px" id="fn-ipn-fb">
        <div class="fnode-head">PUBLISH</div>
        <div class="fnode-body"><div class="fnode-icon">📘</div><div class="fnode-name">Card + Facebook</div><div class="fnode-desc">ქარდი → FB გვერდი</div></div>
      </div>

      <!-- ROW 5: RSS International News -->
      <div class="fnode fnode-cyan" style="left:40px;top:510px" id="fn-rss">
        <div class="fnode-head">SOURCE</div>
        <div class="fnode-body"><div class="fnode-icon">📡</div><div class="fnode-name">RSS Feeds</div><div class="fnode-desc">CNN / BBC</div></div>
      </div>
      <div class="fnode fnode-green" style="left:210px;top:510px" id="fn-rss-parse">
        <div class="fnode-head">PROCESS</div>
        <div class="fnode-body"><div class="fnode-icon">📋</div><div class="fnode-name">feedparser</div><div class="fnode-desc">RSS → სტატიები</div></div>
      </div>
      <div class="fnode fnode-green" style="left:380px;top:510px" id="fn-rss-translate">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🌐</div><div class="fnode-name">Gemini Translate</div><div class="fnode-desc">EN → KA თარგმანი</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:550px;top:510px" id="fn-rss-queue">
        <div class="fnode-head">QUEUE</div>
        <div class="fnode-body"><div class="fnode-icon">📦</div><div class="fnode-name">Queue System</div><div class="fnode-desc">რიგი + ინტერვალი</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:720px;top:510px" id="fn-rss-tg">
        <div class="fnode-head">APPROVAL</div>
        <div class="fnode-body"><div class="fnode-icon">✅</div><div class="fnode-name">TG Approval</div><div class="fnode-desc">დადასტურება / უარყოფა</div></div>
      </div>
      <div class="fnode fnode-red" style="left:890px;top:510px" id="fn-rss-fb">
        <div class="fnode-head">PUBLISH</div>
        <div class="fnode-body"><div class="fnode-icon">📘</div><div class="fnode-name">Card + Facebook</div><div class="fnode-desc">ქარდი → FB გვერდი</div></div>
      </div>

      <!-- ROW 6: Telegram Bot -->
      <div class="fnode fnode-purple" style="left:40px;top:640px" id="fn-tg">
        <div class="fnode-head">TELEGRAM</div>
        <div class="fnode-body"><div class="fnode-icon">💬</div><div class="fnode-name">Telegram Bot</div><div class="fnode-desc">/start, /voice, free text</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:240px;top:630px" id="fn-tgstart">
        <div class="fnode-head">COMMAND</div>
        <div class="fnode-body"><div class="fnode-icon">📸</div><div class="fnode-name">/start</div><div class="fnode-desc">ფოტო → ქარდი</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:440px;top:630px" id="fn-tgvoice">
        <div class="fnode-head">COMMAND</div>
        <div class="fnode-body"><div class="fnode-icon">🎙️</div><div class="fnode-name">/voice</div><div class="fnode-desc">ტექსტი → აუდიო</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:640px;top:630px" id="fn-tgfree">
        <div class="fnode-head">QUERY</div>
        <div class="fnode-body"><div class="fnode-icon">💬</div><div class="fnode-name">Free Text</div><div class="fnode-desc">თანამშრომლის ძიება</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:840px;top:640px" id="fn-tgout">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">📤</div><div class="fnode-name">TG Response</div><div class="fnode-desc">ქარდი / ხმა / ინფო</div></div>
      </div>

      <!-- ROW 7: Employee Lookup -->
      <div class="fnode fnode-blue" style="left:40px;top:770px" id="fn-gsheet">
        <div class="fnode-head">DATA</div>
        <div class="fnode-body"><div class="fnode-icon">📊</div><div class="fnode-name">Google Sheet</div><div class="fnode-desc">თანამშრომლების DB</div></div>
      </div>
      <div class="fnode fnode-green" style="left:300px;top:770px" id="fn-openai">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🧠</div><div class="fnode-name">OpenAI gpt-4o-mini</div><div class="fnode-desc">ბუნებრივი ენის ძიება</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:560px;top:770px" id="fn-emp-tg">
        <div class="fnode-head">TELEGRAM</div>
        <div class="fnode-body"><div class="fnode-icon">👤</div><div class="fnode-name">TG Response</div><div class="fnode-desc">თანამშრომლის ინფო</div></div>
      </div>

      <!-- ROW 8: System / Scheduler + GitHub -->
      <div class="fnode fnode-cyan" style="left:40px;top:900px" id="fn-timer">
        <div class="fnode-head">SCHEDULER</div>
        <div class="fnode-body"><div class="fnode-icon">⏰</div><div class="fnode-name">Hourly Timer</div><div class="fnode-desc">ყოველ საათში</div></div>
      </div>
      <div class="fnode fnode-cyan" style="left:260px;top:900px" id="fn-report">
        <div class="fnode-head">ACTION</div>
        <div class="fnode-body"><div class="fnode-icon">📊</div><div class="fnode-name">Status Report</div><div class="fnode-desc">სტატუსი + uptime</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:480px;top:900px" id="fn-tgadmin">
        <div class="fnode-head">TELEGRAM</div>
        <div class="fnode-body"><div class="fnode-icon">👤</div><div class="fnode-name">Admin Chat</div><div class="fnode-desc">შეტყობინება</div></div>
      </div>
      <div class="fnode fnode-cyan" style="left:700px;top:900px" id="fn-github">
        <div class="fnode-head">STORAGE</div>
        <div class="fnode-body"><div class="fnode-icon">🐙</div><div class="fnode-name">GitHub</div><div class="fnode-desc">photos/ sync</div></div>
      </div>
      <div class="fnode fnode-blue" style="left:920px;top:900px" id="fn-photos">
        <div class="fnode-head">LIBRARY</div>
        <div class="fnode-body"><div class="fnode-icon">📁</div><div class="fnode-name">Photo Library</div><div class="fnode-desc">ატვირთვა/წაშლა</div></div>
      </div>
    </div>
  </div>
  <div class="flow-legend">
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#60a5fa"></div> Input / Data</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#4ade80"></div> AI / Process</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#fb923c"></div> Output / Queue</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#c084fc"></div> Telegram</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#22d3ee"></div> Source / System</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#f87171"></div> Publish</div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
(function(){
  const drop   = document.getElementById('drop');
  const fi     = document.getElementById('fi');
  const prev   = document.getElementById('prev');
  let   file   = null;
  let   libPhoto = null;     // selected library photo path (e.g., /photos/person1.jpg)
  let   lastCardUrl  = '';   // store last generated card URL
  let   lastCardName = '';   // store last generated card name
  let   lastAutoUrl  = '';   // store last auto-generated card URL
  let   lastAutoName = '';   // store last auto-generated card name
  let   lastAutoArticle = '';  // store last auto-generated article text
  function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

  // ── photo library ──────────────────────────────────────────────────
  async function loadLibrary() {
    try {
      const res = await fetch('/api/library');
      const photos = await res.json();
      const grid = document.getElementById('lib-grid');
      if (photos.length === 0) {
        grid.innerHTML = '<div class="lib-empty">ფოტოები არ არის</div>';
        return;
      }
      grid.innerHTML = '';
      photos.forEach(p => {
        const item = document.createElement('div');
        item.className = 'lib-item';
        item.innerHTML = `
          <div class="lib-actions">
            <button class="lib-action-btn rename" onclick="renamePhoto('${p.name}'); event.stopPropagation();" title="გადარქმევა">✏️</button>
            <button class="lib-action-btn delete" onclick="deletePhoto('${p.name}'); event.stopPropagation();" title="წაშლა">🗑️</button>
          </div>
          <img src="${p.url}" alt="${p.name}" onclick="selectLibPhoto('${p.url}', '${p.name}', this.parentElement)">
          <div class="lib-name" onclick="selectLibPhoto('${p.url}', '${p.name}', this.parentElement)">${p.name.replace(/_/g,' ')}</div>
        `;
        grid.appendChild(item);
      });
    } catch(e) {
      console.error('Library load failed:', e);
    }
  }

  // upload photo to library
  document.getElementById('lib-fi').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;

    const fd = new FormData();
    fd.append('photo', file);

    try {
      const r = await fetch('/api/upload-library', { method: 'POST', body: fd });
      const data = await r.json();
      if (data.success) {
        toast('ფოტო ატვირთულია ბიბლიოთეკაში!', 'success');
        loadLibrary();  // reload library
        e.target.value = '';  // clear input
      } else {
        toast('შეცდომა: ' + (data.error || 'unknown'));
      }
    } catch(err) {
      toast('ნეტვორკის შეცდომა: ' + err.message);
    }
  });

  window.selectLibPhoto = function(url, name, itemEl) {
    // clear previous selection
    document.querySelectorAll('.lib-item').forEach(el => el.classList.remove('selected'));
    // clear file upload
    file = null;
    prev.src = '';
    prev.style.display = 'none';
    fi.value = '';
    // select this one
    itemEl.classList.add('selected');
    libPhoto = url;
    // auto-fill name field with photo name
    document.getElementById('inp-name').value = name.replace(/_/g, ' ');
  };

  // delete photo from library
  window.deletePhoto = async function(photoName) {
    if (!confirm('წაშალოთ ფოტო: ' + photoName.replace(/_/g, ' ') + '?')) return;

    const fd = new FormData();
    fd.append('photo_name', photoName);

    try {
      const r = await fetch('/api/delete-library', { method: 'POST', body: fd });
      const data = await r.json();
      if (data.success) {
        toast('ფოტო წაშლილია!', 'success');
        loadLibrary();  // reload library
      } else {
        toast('შეცდომა: ' + (data.error || 'unknown'));
      }
    } catch(err) {
      toast('ნეტვორკის შეცდომა: ' + err.message);
    }
  };

  // rename photo in library
  window.renamePhoto = async function(oldName) {
    const newName = prompt('ახალი სახელი:', oldName.replace(/_/g, ' '));
    if (!newName || newName.trim() === '') return;

    const fd = new FormData();
    fd.append('old_name', oldName);
    fd.append('new_name', newName.trim());

    try {
      const r = await fetch('/api/rename-library', { method: 'POST', body: fd });
      const data = await r.json();
      if (data.success) {
        toast('ფოტო გადარქმდა!', 'success');
        loadLibrary();  // reload library
      } else {
        toast('შეცდომა: ' + (data.error || 'unknown'));
      }
    } catch(err) {
      toast('ნეტვორკის შეცდომა: ' + err.message);
    }
  };

  loadLibrary();

  // ── upload wiring ─────────────────────────────────────────────────
  drop.addEventListener('click',    () => fi.click());
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave',() => drop.classList.remove('over'));
  drop.addEventListener('drop',     e => {
    e.preventDefault(); drop.classList.remove('over');
    if (e.dataTransfer.files[0]) pick(e.dataTransfer.files[0]);
  });
  fi.addEventListener('change', e => { if (e.target.files[0]) pick(e.target.files[0]); });

  function pick(f) {
    file = f;
    // clear library selection
    libPhoto = null;
    document.querySelectorAll('.lib-item').forEach(el => el.classList.remove('selected'));
    const r = new FileReader();
    r.onload = () => { prev.src = r.result; prev.style.display = 'block'; };
    r.readAsDataURL(f);
  }

  // ── generate ──────────────────────────────────────────────────────
  window.gen = async function() {
    const name = document.getElementById('inp-name').value.trim();
    const text = document.getElementById('inp-text').value.trim();
    if ((!file && !libPhoto) || !name || !text) { toast('ფოტო, სახელი და ტექსტი საჭიროა!'); return; }

    document.getElementById('btn-gen').disabled = true;
    document.getElementById('spin').style.display = 'block';
    document.getElementById('res').style.display  = 'none';

    const fd = new FormData();
    if (file) {
      fd.append('photo', file);
    } else if (libPhoto) {
      fd.append('lib_photo', libPhoto);
    }
    fd.append('name',  name);
    fd.append('text',  text);

    try {
      const r    = await fetch('/api/generate', { method:'POST', body:fd });
      const data = await r.json();
      if (data.card_url) {
        document.getElementById('res-img').src = data.card_url;
        document.getElementById('res-dl').href = data.card_url;
        document.getElementById('res').style.display = 'block';
        document.getElementById('btn-fb').className = 'btn-fb';
        document.getElementById('btn-fb').textContent = '📘 Upload to Facebook';
        document.getElementById('btn-fb').disabled = false;
        lastCardUrl  = data.card_url;
        lastCardName = name;
        loadHistory();
        // reload library to show newly uploaded photo
        if (file) {
          loadLibrary();
          toast('ქარდი შეიქმნა და ფოტო შეინახა ბიბლიოთეკაში!', 'success');
          // clear upload preview
          file = null;
          prev.src = '';
          prev.style.display = 'none';
          fi.value = '';
        } else {
          toast('ქარდი შეიქმნა!', 'success');
        }
      } else { toast('Error: ' + (data.error || 'unknown')); }
    } catch(e) { toast('Network error: ' + e.message); }

    document.getElementById('btn-gen').disabled = false;
    document.getElementById('spin').style.display = 'none';
  };

  // ── auto-generate (SSE stream) ────────────────────────────────────
  window.autoGen = async function() {
    const theme = document.getElementById('inp-theme').value.trim();
    if (!theme) { toast('Topic required!'); return; }

    const btn   = document.getElementById('btn-auto');
    const spin  = document.getElementById('spin-auto');
    const logEl = document.getElementById('auto-log');
    const resEl = document.getElementById('res-auto');

    btn.disabled     = true;
    btn.textContent  = 'Processing...';
    spin.style.display  = 'block';
    resEl.style.display = 'none';
    logEl.innerHTML     = '';
    document.getElementById('auto-article').style.display = 'none';

    const fd = new FormData();
    fd.append('theme', theme);

    try {
      const r      = await fetch('/api/auto-generate', { method:'POST', body:fd });
      const reader = r.body.getReader();
      const dec    = new TextDecoder();
      let   buf    = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });

        const parts = buf.split('\\n\\n');
        buf = parts.pop();                              // keep incomplete tail

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data: ')) continue;
          try {
            const evt = JSON.parse(line.slice(6));
            if      (evt.t === 'log')  { logEl.innerHTML += '<span style="color:#94a3b8">· ' + esc(evt.m) + '</span><br>'; }
            else if (evt.t === 'err')  { logEl.innerHTML += '<span style="color:#ef4444">✕ ' + esc(evt.m) + '</span><br>'; toast('Error: ' + evt.m); }
            else if (evt.t === 'done') {
              logEl.innerHTML += '<span style="color:#4ade80">✓ Card created</span><br>';
              document.getElementById('res-auto-img').src  = evt.card_url;
              document.getElementById('res-auto-dl').href  = evt.card_url;
              document.getElementById('btn-fb-auto').className = 'btn-fb';
              document.getElementById('btn-fb-auto').textContent = '📘 Upload to Facebook';
              document.getElementById('btn-fb-auto').disabled = false;
              lastAutoUrl  = evt.card_url;
              lastAutoName = evt.name || '';
              lastAutoArticle = evt.article || '';
              resEl.style.display = 'block';
              // show article
              if (evt.article) {
                document.getElementById('auto-article-title').textContent = evt.name || '';
                document.getElementById('auto-article-text').textContent = evt.article;
                document.getElementById('auto-article').style.display = 'block';
              }
              loadHistory();
            }
          } catch(_) {}
        }
        logEl.scrollTop = logEl.scrollHeight;
      }
    } catch(e) {
      logEl.innerHTML += '<span style="color:#ef4444">✕ Network error: ' + esc(e.message) + '</span><br>';
      toast('Network error: ' + e.message);
    }

    btn.disabled    = false;
    btn.textContent = 'Generate';
    spin.style.display = 'none';
  };

  // ── history ───────────────────────────────────────────────────────
  async function loadHistory() {
    const items = await (await fetch('/api/history')).json();
    document.getElementById('s-count').textContent = items.length;
    const g = document.getElementById('hgrid');
    g.innerHTML = '';
    items.forEach(it => {
      const d = document.createElement('div');
      d.className = 'hcard';
      d.innerHTML =
        '<img src="'+it.card_url+'" alt="'+it.name+'">' +
        '<div class="inf"><div class="n">'+it.name+'</div><div class="t">'+it.time+'</div></div>';
      d.onclick = () => window.open(it.card_url);
      g.appendChild(d);
    });
  }
  loadHistory();

  // ── status check + env-var warning ───────────────────────────────
  fetch('/api/status').then(r=>r.json()).then(d=>{
    const b = document.getElementById('ai-badge');
    if (b && d.ai_backend) b.textContent = '[' + d.ai_backend + ']';
    const miss = [];
    if (d.tavily_key === false) miss.push('TAVILY_API_KEY');
    if (d.openai_key === false) miss.push('OPENAI_API_KEY');
    if (d.gemini_key === false) miss.push('GEMINI_API_KEY (fallback)');
    if (miss.length) {
      document.getElementById('auto-log').innerHTML =
        '<span style="color:#f59e0b">⚠ Missing: ' + miss.join(', ') +
        '</span>';
    }
  });

  // ── upload to Facebook ─────────────────────────────────────────────
  window.uploadFB = async function(resultId) {
    const isAuto  = resultId === 'res-auto';
    const cardUrl = isAuto ? lastAutoUrl  : lastCardUrl;
    const name    = isAuto ? lastAutoName : lastCardName;
    const btn     = document.getElementById(isAuto ? 'btn-fb-auto' : 'btn-fb');

    if (!cardUrl) { toast('No card to upload'); return; }

    btn.disabled = true;
    btn.textContent = 'Uploading...';

    try {
      const fd = new FormData();
      fd.append('card_url', cardUrl);
      fd.append('name', name);
      // send article as caption for Facebook
      if (isAuto && lastAutoArticle) {
        fd.append('caption', name + '\\n\\n' + lastAutoArticle);
      }
      const r = await fetch('/api/upload-facebook', { method:'POST', body:fd });
      const data = await r.json();
      if (data.success) {
        btn.className = 'btn-fb done';
        btn.textContent = '✓ Uploaded to Facebook';
        toast('Card uploaded to Facebook!', 'success');
      } else {
        btn.className = 'btn-fb fail';
        btn.textContent = '✕ Upload failed';
        toast('Facebook upload failed: ' + (data.error || 'unknown'));
        btn.disabled = false;
      }
    } catch(e) {
      btn.className = 'btn-fb fail';
      btn.textContent = '✕ Upload failed';
      toast('Network error: ' + e.message);
      btn.disabled = false;
    }
  };

  // ── copy article ─────────────────────────────────────────────────
  window.copyArticle = function() {
    const title = document.getElementById('auto-article-title').textContent;
    const text = document.getElementById('auto-article-text').textContent;
    navigator.clipboard.writeText(title + '\\n\\n' + text).then(() => {
      toast('სტატია კოპირებულია!', 'success');
    });
  };

  // ── toast helper ──────────────────────────────────────────────────
  window.toast = function(msg, type) {
    const t = document.getElementById('toast');
    t.className = type === 'success' ? 'toast success' : 'toast';
    t.textContent = msg; t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 5000);
  };

  // ── news interval control ────────────────────────────────────────
  window.setNewsInterval = function(min) {
    document.getElementById('inp-news-interval').value = min;
    updateIntervalLabel(min);
  };

  function updateIntervalLabel(min) {
    const lbl = document.getElementById('interval-label');
    if (min >= 60) {
      const h = Math.floor(min/60), m = min%60;
      lbl.textContent = 'ყოველ ' + h + ' საათ' + (m ? ' ' + m + ' წუთში' : 'ში');
    } else {
      lbl.textContent = 'ყოველ ' + min + ' წუთში';
    }
  }

  document.getElementById('inp-news-interval').addEventListener('input', function() {
    updateIntervalLabel(parseInt(this.value) || 15);
  });

  // helper: show result div with content
  function showResult(el, html) {
    el.innerHTML = html;
    el.style.display = 'block';
  }

  window.applyNewsInterval = async function() {
    const min = parseInt(document.getElementById('inp-news-interval').value) || 15;
    const res = document.getElementById('res-news');
    try {
      const r = await fetch('/api/news-interval', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({minutes: min})
      });
      const d = await r.json();
      if (d.success) {
        showResult(res, '<span style="color:#4ade80">✅ ინტერვალი შეიცვალა: ყოველ ' + d.minutes + ' წუთში</span>');
        toast('ინტერვალი: ' + d.minutes + ' წუთი', 'success');
      } else {
        showResult(res, '<span style="color:#ef4444">შეცდომა</span>');
      }
    } catch(e) {
      showResult(res, '<span style="color:#ef4444">შეცდომა: ' + e.message + '</span>');
    }
  };

  window.sendTestNews = async function() {
    const spin = document.getElementById('spin-news');
    const res = document.getElementById('res-news');
    spin.style.display = 'block';
    res.style.display = 'none';
    try {
      const r = await fetch('/api/test-news', {method:'POST'});
      const d = await r.json();
      spin.style.display = 'none';
      if (d.success) {
        showResult(res, '<span style="color:#4ade80">📰 გაგზავნილია: ' + d.title.substring(0,60) + '...</span>');
        toast('სიახლე გაგზავნილია Telegram-ზე!', 'success');
      } else {
        showResult(res, '<span style="color:#ef4444">' + (d.error || 'შეცდომა') + '</span>');
      }
    } catch(e) {
      spin.style.display = 'none';
      showResult(res, '<span style="color:#ef4444">შეცდომა: ' + e.message + '</span>');
    }
  };

  // Load current interval on page load
  fetch('/api/news-interval').then(r=>r.json()).then(d=>{
    const min = Math.round(d.interval / 60);
    document.getElementById('inp-news-interval').value = min;
    updateIntervalLabel(min);
  });

  // ── RSS source management ────────────────────────────────────────
  async function loadRssSources() {
    try {
      const r = await fetch('/api/rss-sources');
      const d = await r.json();
      const tbody = document.getElementById('rss-tbody');
      tbody.innerHTML = '';
      d.sources.forEach(s => {
        const tr = document.createElement('tr');
        tr.style.borderBottom = '1px solid #1a1d2e';
        const sid = s.id;
        const bg = s.enabled ? '#1a5c2e' : '#5c1a1a';
        const label = s.enabled ? '✅ ჩართული' : '❌ გამორთული';
        tr.innerHTML =
          '<td style="padding:8px;color:#e2e8f0;">' + s.name + '</td>' +
          '<td style="padding:8px;color:#94a3b8;">' + s.category + '</td>' +
          '<td style="padding:8px;color:#94a3b8;">' + s.interval_min + ' წთ</td>' +
          '<td style="padding:8px;">' +
            '<button data-action="toggle" data-id="' + sid + '" style="background:' + bg +
            ';border:none;color:#fff;padding:4px 10px;border-radius:4px;cursor:pointer;font-size:11px;">' +
            label + '</button></td>' +
          '<td style="padding:8px;">' +
            '<button data-action="delete" data-id="' + sid + '" style="background:none;border:1px solid #5c1a1a;color:#ef4444;padding:4px 8px;border-radius:4px;cursor:pointer;font-size:11px;">✕</button>' +
          '</td>';
        tr.addEventListener('click', function(e) {
          const btn = e.target.closest('[data-action]');
          if (!btn) return;
          const action = btn.dataset.action;
          const id = btn.dataset.id;
          if (action === 'toggle') toggleRss(id);
          else if (action === 'delete') deleteRss(id);
        });
        tbody.appendChild(tr);
      });
      document.getElementById('rss-min-interval').value = d.min_interval;
      document.getElementById('rss-queue-info').textContent = 'რიგში: ' + d.queue_size;
    } catch(e) { console.error('RSS load failed', e); }
  }

  window.addRssSource = async function() {
    const name = document.getElementById('rss-new-name').value.trim();
    const url = document.getElementById('rss-new-url').value.trim();
    const cat = document.getElementById('rss-new-cat').value.trim() || 'General';
    const interval = parseInt(document.getElementById('rss-new-interval').value) || 30;
    if (!name || !url) { toast('სახელი და URL სავალდებულოა'); return; }
    const r = await fetch('/api/rss-sources', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({name, url, category: cat, interval_min: interval})
    });
    const d = await r.json();
    if (d.success) {
      toast(name + ' დამატებულია!', 'success');
      document.getElementById('rss-new-name').value = '';
      document.getElementById('rss-new-url').value = '';
      loadRssSources();
    } else { toast(d.error || 'შეცდომა'); }
  };

  window.toggleRss = async function(id) {
    await fetch('/api/rss-toggle/' + id, {method:'POST'});
    loadRssSources();
  };

  window.deleteRss = async function(id) {
    await fetch('/api/rss-sources/' + id, {method:'DELETE'});
    loadRssSources();
  };

  window.setRssMinInterval = async function() {
    const min = parseInt(document.getElementById('rss-min-interval').value) || 30;
    const res = document.getElementById('res-rss');
    try {
      const r = await fetch('/api/rss-settings', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({min_interval: min})
      });
      const d = await r.json();
      if (d.success) {
        showResult(res, '<span style="color:#4ade80">✅ მინ. ინტერვალი: ' + d.min_interval + ' წუთი</span>');
        toast('მინ. ინტერვალი: ' + d.min_interval + ' წუთი', 'success');
      }
    } catch(e) {
      showResult(res, '<span style="color:#ef4444">შეცდომა: ' + e.message + '</span>');
    }
  };

  window.sendTestRss = async function() {
    const spin = document.getElementById('spin-rss');
    const res = document.getElementById('res-rss');
    spin.style.display = 'block';
    res.style.display = 'none';
    try {
      const r = await fetch('/api/test-rss', {method:'POST'});
      const d = await r.json();
      spin.style.display = 'none';
      if (d.success) {
        showResult(res, '<span style="color:#4ade80">📡 ' + d.source + ': ' + d.title.substring(0,60) + '...</span>');
        toast('RSS სიახლე გაგზავნილია Telegram-ზე!', 'success');
      } else {
        showResult(res, '<span style="color:#ef4444">' + (d.error || 'შეცდომა') + '</span>');
      }
    } catch(e) {
      spin.style.display = 'none';
      showResult(res, '<span style="color:#ef4444">შეცდომა: ' + e.message + '</span>');
    }
  };

  loadRssSources();

  // ── voice generation ──────────────────────────────────────────────
  const voiceText = document.getElementById('inp-voice-text');
  const charCount = document.getElementById('char-count');

  // Character counter
  voiceText.addEventListener('input', () => {
    const len = voiceText.value.length;
    charCount.textContent = len;
    if (len > 5000) {
      charCount.style.color = '#ef4444';
    } else if (len > 4000) {
      charCount.style.color = '#f59e0b';
    } else {
      charCount.style.color = '#4ade80';
    }
  });

  window.generateVoice = async function() {
    const text = voiceText.value.trim();
    const voice = document.getElementById('sel-voice').value;
    const btn = document.getElementById('btn-voice');
    const spin = document.getElementById('spin-voice');
    const result = document.getElementById('res-voice');
    const player = document.getElementById('audio-player');
    const dl = document.getElementById('res-voice-dl');

    if (!text) {
      toast('გთხოვთ შეიყვანოთ ტექსტი');
      return;
    }

    if (text.length > 5000) {
      toast('ტექსტი ძალიან გრძელია (მაქს 5000 სიმბოლო)');
      return;
    }

    btn.disabled = true;
    spin.style.display = 'block';
    result.style.display = 'none';

    try {
      const res = await fetch('/api/generate-voice', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text, voice})
      });

      const data = await res.json();

      if (data.success && data.audio_url) {
        player.src = data.audio_url;
        player.style.display = 'block';
        dl.href = data.audio_url;
        dl.style.display = 'inline-block';
        result.style.display = 'block';
        toast('ხმა წარმატებით გენერირდა! 🎉', 'success');
      } else {
        toast('შეცდომა: ' + (data.error || 'unknown'));
      }
    } catch(e) {
      toast('Network error: ' + e.message);
    } finally {
      btn.disabled = false;
      spin.style.display = 'none';
    }
  };
  // ── flow visualization ──────────────────────────────────────────
  window.toggleFlow = function() {
    const overlay = document.getElementById('flow-overlay');
    overlay.classList.toggle('open');
    if (overlay.classList.contains('open')) drawFlowLines();
  };

  function drawFlowLines() {
    const svg = document.getElementById('flow-svg');
    const canvas = document.getElementById('flow-canvas');
    svg.setAttribute('width', canvas.scrollWidth);
    svg.setAttribute('height', canvas.scrollHeight);
    svg.innerHTML = '';

    const connections = [
      // Row 1: Manual card
      ['fn-dash1','fn-photo','active'],
      ['fn-photo','fn-cardgen','active'],
      ['fn-cardgen','fn-card1','active'],
      ['fn-card1','fn-fb1',''],
      // Row 2: Auto card
      ['fn-dash2','fn-tavily','active'],
      ['fn-tavily','fn-gemini','active'],
      ['fn-gemini','fn-imagen','active'],
      ['fn-imagen','fn-card2','active'],
      // Row 3: TTS
      ['fn-dash3','fn-tts','active'],
      ['fn-tts','fn-wav','active'],
      // Row 4: IPN Auto-News
      ['fn-ipn','fn-ipn-scrape','active'],
      ['fn-ipn-scrape','fn-ipn-tg','active'],
      ['fn-ipn-tg','fn-ipn-caption','active'],
      ['fn-ipn-caption','fn-ipn-fb','active'],
      // Row 5: RSS International News
      ['fn-rss','fn-rss-parse','active'],
      ['fn-rss-parse','fn-rss-translate','active'],
      ['fn-rss-translate','fn-rss-queue','active'],
      ['fn-rss-queue','fn-rss-tg','active'],
      ['fn-rss-tg','fn-rss-fb','active'],
      // Row 6: Telegram
      ['fn-tg','fn-tgstart','active'],
      ['fn-tg','fn-tgvoice','active'],
      ['fn-tg','fn-tgfree','active'],
      ['fn-tgstart','fn-tgout',''],
      ['fn-tgvoice','fn-tgout',''],
      ['fn-tgfree','fn-tgout',''],
      // Row 7: Employee Lookup
      ['fn-gsheet','fn-openai','active'],
      ['fn-openai','fn-emp-tg','active'],
      // Row 8: Scheduler + GitHub
      ['fn-timer','fn-report','active'],
      ['fn-report','fn-tgadmin','active'],
      ['fn-github','fn-photos','active'],
    ];

    connections.forEach(([fromId, toId, type]) => {
      const fromEl = document.getElementById(fromId);
      const toEl = document.getElementById(toId);
      if (!fromEl || !toEl) return;

      const fx = fromEl.offsetLeft + fromEl.offsetWidth;
      const fy = fromEl.offsetTop + fromEl.offsetHeight / 2;
      const tx = toEl.offsetLeft;
      const ty = toEl.offsetTop + toEl.offsetHeight / 2;

      const mx = (fx + tx) / 2;
      const d = 'M'+fx+','+fy+' C'+mx+','+fy+' '+mx+','+ty+' '+tx+','+ty;

      const path = document.createElementNS('http://www.w3.org/2000/svg','path');
      path.setAttribute('d', d);
      path.setAttribute('class', type === 'active' ? 'flow-line flow-line-active' : 'flow-line');
      svg.appendChild(path);

      // Arrow
      const arrow = document.createElementNS('http://www.w3.org/2000/svg','polygon');
      const ax = tx - 6;
      arrow.setAttribute('points', tx+','+ty+' '+ax+','+(ty-4)+' '+ax+','+(ty+4));
      arrow.setAttribute('fill', type === 'active' ? '#1e94b9' : '#3d4158');
      svg.appendChild(arrow);
    });
  }
  // -- analytics --
  async function loadAnalytics() {
    var spin = document.getElementById('spin-analytics');
    spin.style.display = 'block';
    try {
      var r = await fetch('/api/analytics/summary');
      var s = await r.json();
      document.getElementById('a-today').textContent = s.today;
      document.getElementById('a-week').textContent = s.week;
      document.getElementById('a-month').textContent = s.month;
      document.getElementById('a-total').textContent = s.total;
      document.getElementById('a-approved').textContent = s.approved;
      document.getElementById('a-rejected').textContent = s.rejected;
      document.getElementById('a-published').textContent = s.published;
      var srcDiv = document.getElementById('a-src');
      srcDiv.innerHTML = '';
      for (var k in (s.by_source || {})) {
        srcDiv.innerHTML += '<div class="a-src-tag">' + esc(k) + '<span class="cnt">' + s.by_source[k] + '</span></div>';
      }
      await loadALogs();
    } catch(e) { toast('ანალიტიკა: ' + e.message); }
    finally { spin.style.display = 'none'; }
  }
  async function loadALogs() {
    var src = document.getElementById('a-fsrc').value;
    var st = document.getElementById('a-fst').value;
    var url = '/api/analytics/logs?limit=30';
    if (src) url += '&source=' + encodeURIComponent(src);
    if (st) url += '&status=' + encodeURIComponent(st);
    var d = await (await fetch(url)).json();
    var tb = document.getElementById('a-tbody');
    tb.innerHTML = '';
    (d.logs || []).forEach(function(l) {
      var ts = (l.timestamp || '').replace('T',' ').slice(0,16);
      var sc = l.status === 'approved' ? 'st-ok' : l.status === 'rejected' ? 'st-no' : 'st-wait';
      var sl = l.status === 'approved' ? 'დამტკ.' : l.status === 'rejected' ? 'უარყ.' : 'მოლოდ.';
      var fb = l.facebook_post_id ? '✅' : '—';
      tb.innerHTML += '<tr><td>' + esc(ts) + '</td><td>' + esc(l.source||'') + '</td><td>' + esc((l.title||'').slice(0,40)) + '</td><td><span class="st-badge ' + sc + '">' + sl + '</span></td><td>' + fb + '</td></tr>';
    });
  }
  async function loadFBStats() {
    try {
      var r = await fetch('/api/fb/page-stats');
      var d = await r.json();
      document.getElementById('fb-followers').textContent = (d.followers || 0).toLocaleString();
      document.getElementById('fb-fans').textContent = (d.fans || 0).toLocaleString();
      var imp = d.page_impressions || 0;
      var eng = d.page_post_engagements || 0;
      document.getElementById('fb-impressions').textContent = imp.toLocaleString();
      document.getElementById('fb-engagements').textContent = eng.toLocaleString();
      // Growth badge
      var net = (d.fan_adds || 0) - (d.fan_removes || 0);
      var badge = document.getElementById('fb-growth-badge');
      if (net !== 0) {
        badge.textContent = (net > 0 ? '+' : '') + net;
        badge.className = 'fb-growth ' + (net >= 0 ? 'pos' : 'neg');
      }
      // Page views
      if (d.page_views) document.getElementById('fb-page-views').textContent = d.page_views.toLocaleString();
    } catch(e) { console.log('FB stats error:', e); }
    // Computed analytics
    try {
      var r3 = await fetch('/api/fb/computed-analytics');
      var c = await r3.json();
      if (!c.error) {
        document.getElementById('fb-eng-rate').textContent = (c.engagement_rate || 0).toFixed(1) + '%';
        document.getElementById('fb-avg-eng').textContent = (c.avg_engagement || 0).toFixed(1);
        document.getElementById('fb-week-reach').textContent = (c.week_reach || 0).toLocaleString();
        // Reactions
        var rx = c.reactions || {};
        document.getElementById('fb-rx-love').textContent = rx.love || 0;
        document.getElementById('fb-rx-haha').textContent = rx.haha || 0;
        document.getElementById('fb-rx-wow').textContent = rx.wow || 0;
        document.getElementById('fb-rx-sad').textContent = rx.sad || 0;
        document.getElementById('fb-rx-angry').textContent = rx.angry || 0;
        // Best hour
        if (c.best_hour && c.best_hour !== '—') {
          document.getElementById('fb-best-hour-label').textContent = '🎯 საუკეთესო დრო: ' + c.best_hour + ':00';
        }
        // Source performance
        var sp = c.source_performance || {};
        var spDiv = document.getElementById('fb-src-perf');
        spDiv.innerHTML = '';
        Object.keys(sp).forEach(function(src) {
          var info = sp[src];
          spDiv.innerHTML += '<div class="fb-src-row"><span class="fb-src-name">' + esc(src) + ' (' + (info.count||0) + ' პოსტი)</span><span class="fb-src-val">საშ. ' + (info.avg_engagement||0).toFixed(1) + '</span></div>';
        });
        if (!Object.keys(sp).length) spDiv.innerHTML = '<div style="color:#64748b;font-size:11px;padding:4px;">მონაცემები არ არის</div>';
      }
    } catch(e) { console.log('FB analytics error:', e); }
    // Top posts
    try {
      var r2 = await fetch('/api/fb/top-engaged?limit=5');
      var d2 = await r2.json();
      var list = document.getElementById('fb-top-list');
      list.innerHTML = '';
      (d2.posts || []).forEach(function(p) {
        var likes = parseInt(p.likes||0), cmts = parseInt(p.comments||0), shares = parseInt(p.shares||0);
        var rxBadge = '';
        if (p.reactions) {
          var rr = p.reactions;
          if (rr.love) rxBadge += ' ❤️' + rr.love;
          if (rr.haha) rxBadge += ' 😂' + rr.haha;
          if (rr.wow) rxBadge += ' 😮' + rr.wow;
        }
        list.innerHTML += '<div class="fb-top-item"><div class="fb-top-title">' + esc((p.title||'').slice(0,50)) + '</div><div class="fb-top-eng">👍 <span>' + likes + '</span> 💬 <span>' + cmts + '</span> 🔄 <span>' + shares + '</span>' + rxBadge + '</div></div>';
      });
      if (!(d2.posts || []).length) list.innerHTML = '<div style="color:#64748b;font-size:12px;padding:8px;">ჯერ არ არის გამოქვეყნებული პოსტები</div>';
    } catch(e) { console.log('FB top error:', e); }
  }
  async function refreshFBEngagement() {
    var spin = document.getElementById('spin-fb');
    var msg = document.getElementById('fb-refresh-msg');
    spin.style.display = 'block'; msg.style.display = 'none';
    try {
      var r = await fetch('/api/fb/refresh-engagement');
      var d = await r.json();
      msg.textContent = 'განახლდა ' + d.updated + '/' + d.total + ' პოსტი';
      msg.style.display = 'block';
      await loadFBStats();
    } catch(e) { toast('FB refresh: ' + e.message); }
    finally { spin.style.display = 'none'; }
  }
  document.addEventListener('click', function(e) {
    if (e.target.dataset.action === 'load-analytics') loadAnalytics();
    if (e.target.dataset.action === 'fb-refresh') refreshFBEngagement();
  });
  document.addEventListener('change', function(e) {
    if (e.target.dataset.action === 'filter-analytics') loadALogs();
  });
  loadAnalytics();
  loadFBStats();
})();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return DASHBOARD


@app.post("/api/generate")
async def api_generate(
    photo: Optional[UploadFile] = File(None),
    lib_photo: Optional[str] = Form(None),
    name:  str = Form(...),
    text:  str = Form(...),
):
    card_id    = uuid.uuid4().hex[:8]
    card_path  = CARDS   / f"{card_id}_card.jpg"

    # determine photo source: upload or library
    if photo and photo.filename:
        # Read upload bytes first (UploadFile can only be read once)
        photo_bytes = await photo.read()
        if not photo_bytes:
            return JSONResponse(status_code=400, content={"error": "Uploaded file is empty"})

        # save uploaded photo to library (photos/) folder to persist across redeployments
        import re
        safe_name = name.strip().replace(' ', '_')
        # remove unsafe characters but keep Georgian Unicode
        safe_name = re.sub(r'[<>:"/\\|?*]', '', safe_name)  # only remove filesystem-unsafe chars
        if not safe_name:
            safe_name = f"person_{card_id}"

        # determine file extension from uploaded file
        file_ext = Path(photo.filename).suffix or ".jpg"

        # Ensure photos directory exists
        PHOTOS.mkdir(exist_ok=True)

        # ensure unique filename
        photo_path = PHOTOS / f"{safe_name}{file_ext}"
        counter = 1
        while photo_path.exists():
            photo_path = PHOTOS / f"{safe_name}_{counter}{file_ext}"
            counter += 1

        # save to photos/ folder — persists regardless of card generation outcome
        photo_path.write_bytes(photo_bytes)

        # Auto-commit and push new photo to GitHub
        asyncio.create_task(asyncio.to_thread(
            _git_commit_and_push,
            str(photo_path),
            f"ფოტო დაემატა (ქარდიდან): {photo_path.name}"
        ))

    elif lib_photo:
        # use library photo (lib_photo is like /photos/person.jpg)
        filename = lib_photo.replace("/photos/", "")
        photo_path = PHOTOS / filename
        if not photo_path.exists():
            return JSONResponse(status_code=400, content={"error": "Library photo not found"})
    else:
        return JSONResponse(status_code=400, content={"error": "No photo provided"})

    try:
        generator.generate(str(photo_path), name, text, str(card_path))
    except Exception as exc:
        # Photo stays in library even if card generation fails
        return JSONResponse(status_code=500, content={"error": str(exc)})

    # No auto-upload — user clicks "Upload to Facebook" button
    _add_history(name, f"/cards/{card_id}_card.jpg")
    log_id = log_activity(source="manual", title=name, status="approved", card_image_url=f"/cards/{card_id}_card.jpg")
    return {"card_url": f"/cards/{card_id}_card.jpg", "log_id": log_id}


@app.get("/api/history")
async def api_history():
    return history


@app.get("/api/library")
async def api_library():
    """List all photos in the library folder."""
    photos = []
    for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        for f in PHOTOS.glob(ext):
            if f.name.startswith("."):
                continue
            photos.append({
                "name": f.stem,
                "url": f"/photos/{f.name}",
            })
    # sort by name
    photos.sort(key=lambda x: x["name"].lower())
    return photos


@app.post("/api/upload-library")
async def api_upload_library(photo: UploadFile = File(...)):
    """Upload a photo to the library folder."""
    if not photo.filename:
        return JSONResponse(status_code=400, content={"error": "No file provided"})

    # sanitize filename - keep Georgian Unicode, only remove filesystem-unsafe chars
    import re
    safe_name = photo.filename.replace(' ', '_')
    safe_name = re.sub(r'[<>:"/\\|?*]', '', safe_name)  # remove only unsafe chars

    # Read upload bytes up-front and validate
    photo_bytes = await photo.read()
    if not photo_bytes:
        return JSONResponse(status_code=400, content={"error": "Uploaded file is empty"})

    # Ensure photos directory exists
    PHOTOS.mkdir(exist_ok=True)

    # ensure unique filename
    photo_path = PHOTOS / safe_name
    counter = 1
    stem = Path(safe_name).stem
    ext = Path(safe_name).suffix
    while photo_path.exists():
        photo_path = PHOTOS / f"{stem}_{counter}{ext}"
        counter += 1

    try:
        photo_path.write_bytes(photo_bytes)

        # Auto-commit and push to GitHub
        await asyncio.to_thread(
            _git_commit_and_push,
            str(photo_path),
            f"ფოტო დაემატა: {photo_path.name}"
        )

        return {"success": True, "name": photo_path.stem, "url": f"/photos/{photo_path.name}"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/api/delete-library")
async def api_delete_library(photo_name: str = Form(...)):
    """Delete a photo from the library folder."""
    # no need to sanitize - we're searching within PHOTOS folder only
    safe_name = photo_name.strip()

    # find the photo file (could be jpg, jpeg, png, webp)
    photo_path = None
    for ext in (".jpg", ".jpeg", ".png", ".webp", ".JPG", ".JPEG", ".PNG", ".WEBP"):
        candidate = PHOTOS / f"{safe_name}{ext}"
        if candidate.exists():
            photo_path = candidate
            break

    if not photo_path:
        return JSONResponse(status_code=404, content={"error": "Photo not found"})

    try:
        photo_name = photo_path.name
        photo_path.unlink()

        # Auto-commit and push deletion to GitHub
        await asyncio.to_thread(
            _git_commit_and_push,
            str(photo_path),
            f"ფოტო წაიშალა: {photo_name}"
        )

        return {"success": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/api/rename-library")
async def api_rename_library(old_name: str = Form(...), new_name: str = Form(...)):
    """Rename a photo in the library folder."""
    import re
    # sanitize names - keep Georgian Unicode, only remove filesystem-unsafe characters
    safe_old = old_name.strip()
    safe_new = new_name.strip().replace(' ', '_')
    # remove only filesystem-unsafe characters: < > : " / \ | ? *
    safe_new = re.sub(r'[<>:"/\\|?*]', '', safe_new)

    if not safe_new:
        return JSONResponse(status_code=400, content={"error": "Invalid new name"})

    # find the old photo file
    old_path = None
    ext = None
    for e in (".jpg", ".jpeg", ".png", ".webp", ".JPG", ".JPEG", ".PNG", ".WEBP"):
        candidate = PHOTOS / f"{safe_old}{e}"
        if candidate.exists():
            old_path = candidate
            ext = e
            break

    if not old_path:
        return JSONResponse(status_code=404, content={"error": f"Photo not found: {safe_old}"})

    # ensure new name is unique
    new_path = PHOTOS / f"{safe_new}{ext}"
    counter = 1
    while new_path.exists():
        new_path = PHOTOS / f"{safe_new}_{counter}{ext}"
        counter += 1

    try:
        old_name = old_path.name
        old_path.rename(new_path)

        # Auto-commit and push rename to GitHub (delete old, add new)
        import subprocess
        try:
            subprocess.run(["git", "rm", str(old_path)], capture_output=True)
            subprocess.run(["git", "add", str(new_path)], capture_output=True)
        except:
            pass  # if git operations fail, continue anyway

        await asyncio.to_thread(
            _git_commit_and_push,
            str(new_path),
            f"ფოტო გადარქმდა: {old_name} → {new_path.name}"
        )

        return {"success": True, "name": new_path.stem, "url": f"/photos/{new_path.name}"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.get("/api/status")
async def api_status():
    return {"telegram": "running" if TELEGRAM_TOKEN else "disabled",
            "cards":    len(history),
            "ai_backend": os.environ.get("BACKEND", "claude").upper(),
            "tavily_key": bool(os.environ.get("TAVILY_API_KEY")),
            "gemini_key": bool(os.environ.get("GEMINI_API_KEY")),
            "openai_key": bool(os.environ.get("OPENAI_API_KEY"))}


@app.post("/api/generate-voice")
async def api_generate_voice(request: dict):
    """Generate voice-over from Georgian text using Gemini TTS."""
    text = request.get("text", "").strip()
    voice_name = request.get("voice", "Charon")

    if not text:
        return JSONResponse(status_code=400, content={"error": "ტექსტი ცარიელია"})

    if len(text) > 5000:
        return JSONResponse(status_code=400, content={"error": "ტექსტი ძალიან გრძელია (მაქს 5000)"})

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return JSONResponse(status_code=500, content={"error": "GEMINI_API_KEY არ არის დაყენებული"})

    try:
        from google import genai
        from google.genai import types
        import wave
        import io

        client = genai.Client(api_key=api_key)

        response = await asyncio.to_thread(
            lambda: client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=f"Read the following Georgian text naturally:\n{text}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        voice_config=types.VoiceConfig(
                            prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=voice_name,
                            )
                        )
                    ),
                )
            )
        )

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        if not audio_data:
            return JSONResponse(status_code=500, content={"error": "Audio არ გენერირდა"})

        # Save as WAV
        voice_id = uuid.uuid4().hex[:8]
        voice_file = VOICES / f"voice_{voice_id}.wav"

        with wave.open(str(voice_file), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(audio_data)

        return {
            "success": True,
            "audio_url": f"/voices/{voice_file.name}",
            "characters": len(text),
            "voice": voice_name
        }

    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/api/upload-facebook")
async def api_upload_facebook(
    card_url: str = Form(...),
    name: str = Form(...),
    caption: Optional[str] = Form(None),
):
    """Upload a generated card to Facebook (user-triggered)."""
    # card_url is like /cards/abc123_card.jpg — convert to file path
    if not card_url.startswith("/cards/"):
        return JSONResponse(status_code=400, content={"success": False, "error": "Invalid card URL"})

    filename = card_url.replace("/cards/", "")
    card_path = CARDS / filename

    if not card_path.exists():
        return JSONResponse(status_code=404, content={"success": False, "error": "Card not found"})

    # Use article as caption, fallback to name
    fb_caption = caption if caption else name

    # Upload to Facebook + notify via Telegram
    try:
        result = await asyncio.to_thread(post_photo_ext, str(card_path), fb_caption)
        if result["success"]:
            _send_telegram(f"ქარდი ატვირთულია\nქარდის სახელი: {name}")
            # Determine source from card filename
            src = "auto_card" if "_auto." in filename else "manual"
            log_activity(source=src, title=name, status="approved",
                         card_image_url=card_url, caption=fb_caption,
                         facebook_post_id=result["post_id"])
        else:
            _send_telegram(f"ქარდი ატვირთვა ჩამიდა\nქარდის სახელი: {name}")
        return {"success": result["success"]}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


@app.get("/api/news-interval")
async def api_get_news_interval():
    """Get current news scraping interval."""
    return {"interval": _news_interval}


@app.post("/api/news-interval")
async def api_set_news_interval(request: dict):
    """Set news scraping interval in minutes."""
    global _news_interval
    minutes = request.get("minutes", 15)
    minutes = max(5, min(1440, int(minutes)))  # clamp 5min–24h
    _news_interval = minutes * 60
    print(f"[News] Interval changed to {minutes} min ({_news_interval}s)")
    return {"success": True, "minutes": minutes, "seconds": _news_interval}


@app.post("/api/test-news")
async def api_test_news():
    """Manually trigger one news scrape + send to Telegram for testing."""
    articles = await asyncio.to_thread(_scrape_interpressnews)
    if not articles:
        return {"success": False, "error": "No articles found"}

    # Pick first unseen, or first if all seen
    chosen = None
    for art in articles:
        if art["url"] not in _seen_news_urls:
            chosen = art
            break
    if not chosen:
        chosen = articles[0]

    _seen_news_urls.add(chosen["url"])
    news_id = uuid.uuid4().hex[:8]
    _pending_news[news_id] = chosen

    await asyncio.to_thread(_send_news_to_telegram, news_id, chosen)
    return {"success": True, "title": chosen["title"], "news_id": news_id}


# ---------------------------------------------------------------------------
# RSS API endpoints
# ---------------------------------------------------------------------------
@app.get("/api/rss-sources")
async def api_get_rss_sources():
    return {"sources": _rss_sources, "min_interval": _rss_min_interval // 60, "queue_size": len(_rss_queue)}


@app.post("/api/rss-sources")
async def api_add_rss_source(request: dict):
    global _rss_id_counter
    name = request.get("name", "").strip()
    url = request.get("url", "").strip()
    category = request.get("category", "General").strip()
    interval = max(5, min(1440, int(request.get("interval_min", 30))))
    if not name or not url:
        return JSONResponse(status_code=400, content={"error": "name and url required"})
    _rss_id_counter += 1
    source = {
        "id": f"custom-{_rss_id_counter}",
        "name": name,
        "url": url,
        "category": category,
        "enabled": True,
        "interval_min": interval,
        "last_checked": 0,
    }
    _rss_sources.append(source)
    return {"success": True, "source": source}


@app.post("/api/rss-toggle/{source_id}")
async def api_toggle_rss(source_id: str):
    for s in _rss_sources:
        if s["id"] == source_id:
            s["enabled"] = not s["enabled"]
            return {"success": True, "id": source_id, "enabled": s["enabled"]}
    return JSONResponse(status_code=404, content={"error": "source not found"})


@app.delete("/api/rss-sources/{source_id}")
async def api_delete_rss(source_id: str):
    global _rss_sources
    before = len(_rss_sources)
    _rss_sources = [s for s in _rss_sources if s["id"] != source_id]
    if len(_rss_sources) < before:
        return {"success": True}
    return JSONResponse(status_code=404, content={"error": "source not found"})


@app.post("/api/rss-interval/{source_id}")
async def api_set_rss_source_interval(source_id: str, request: dict):
    minutes = max(5, min(1440, int(request.get("interval_min", 30))))
    for s in _rss_sources:
        if s["id"] == source_id:
            s["interval_min"] = minutes
            return {"success": True, "id": source_id, "interval_min": minutes}
    return JSONResponse(status_code=404, content={"error": "source not found"})


@app.get("/api/rss-settings")
async def api_get_rss_settings():
    return {"min_interval": _rss_min_interval // 60, "queue_size": len(_rss_queue)}


@app.post("/api/rss-settings")
async def api_set_rss_settings(request: dict):
    global _rss_min_interval
    minutes = max(5, min(1440, int(request.get("min_interval", 30))))
    _rss_min_interval = minutes * 60
    return {"success": True, "min_interval": minutes}


@app.post("/api/test-rss")
async def api_test_rss():
    """Manually fetch one RSS article, translate, and send to Telegram."""
    enabled = [s for s in _rss_sources if s["enabled"]]
    if not enabled:
        return {"success": False, "error": "No enabled RSS sources"}

    for source in enabled:
        articles = await asyncio.to_thread(_fetch_rss_feed, source)
        new_arts = [a for a in articles if a["url"] not in _rss_seen_urls]
        if not new_arts:
            continue

        art = new_arts[0]
        _rss_seen_urls.add(art["url"])

        tr = await asyncio.to_thread(_translate_to_georgian, art["title"], art["description"])
        art["title_ka"] = tr["title_ka"]
        art["desc_ka"] = tr["desc_ka"]

        news_id = uuid.uuid4().hex[:8]
        _pending_news[news_id] = art
        await asyncio.to_thread(_send_rss_news_to_telegram, news_id, art)
        return {"success": True, "title": art["title_ka"], "source": source["name"]}

    return {"success": False, "error": "No new articles in any feed"}


# ---------------------------------------------------------------------------
# Analytics API endpoints
# ---------------------------------------------------------------------------
@app.get("/api/analytics/summary")
async def api_analytics_summary():
    """Today/week/month counts, by source, approved/rejected."""
    return get_summary()


@app.get("/api/analytics/logs")
async def api_analytics_logs(
    limit: int = 50,
    offset: int = 0,
    source: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Recent log entries with optional filtering."""
    logs = get_logs(limit=limit, offset=offset, source=source,
                    status=status, date_from=date_from, date_to=date_to)
    return {"logs": logs, "count": len(logs)}


@app.get("/api/analytics/top")
async def api_analytics_top(limit: int = 10):
    """Top published posts (newest first, ready for engagement sorting)."""
    return {"posts": get_top(limit=limit)}


@app.get("/api/analytics/sheets-test")
async def api_analytics_sheets_test():
    """Diagnostic: test Google Sheets connection directly."""
    import json as _json
    creds_env = os.environ.get("GOOGLE_SHEETS_CREDS", "")
    info = {"has_creds": bool(creds_env), "creds_len": len(creds_env)}
    try:
        creds_data = _json.loads(creds_env)
        info["client_email"] = creds_data.get("client_email", "MISSING")
        info["project_id"] = creds_data.get("project_id", "MISSING")
    except Exception as e:
        info["json_parse_error"] = str(e)
        return {"ok": False, **info}
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_data, scopes=scopes)
        client = gspread.authorize(credentials)
        sheet = client.open_by_key("1oTom_4hmc8-qFgEhtdeNc3Iype9gY8V7taKGKwmR3Vo").worksheet("Sheet1")
        info["row_count"] = sheet.row_count
        return {"ok": True, **info}
    except Exception as e:
        import traceback
        info["error"] = repr(e)
        info["traceback"] = traceback.format_exc()[-500:]
        return {"ok": False, **info}


@app.get("/api/test-hourly-report")
async def api_test_hourly_report():
    """Send a test hourly report to Telegram."""
    try:
        now = datetime.now(TBILISI)
        uptime = now - _start_time
        hours = int(uptime.total_seconds() // 3600)
        minutes = int((uptime.total_seconds() % 3600) // 60)

        try:
            detail = await asyncio.to_thread(get_today_detail)
        except Exception:
            detail = {"total_today": 0, "by_source": {}, "approved": 0, "rejected": 0, "published": 0}

        src_lines = ""
        for src, count in detail["by_source"].items():
            src_lines += f"  · {src}: {count}\n"
        if not src_lines:
            src_lines = "  · —\n"

        report = (
            f"📊 საათობრივი რეპორტი — {now.strftime('%H:%M  %d/%m/%Y')}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ სტატუსი: აქტიური\n"
            f"⏱ აქტიურია: {hours}სთ {minutes}წთ\n"
            f"🃏 შექმნილი ქარდები: {len(history)}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📰 დღევანდელი აქტივობა: {detail['total_today']}\n"
            f"{src_lines}"
            f"✅ დამტკიცებული: {detail['approved']}\n"
            f"❌ უარყოფილი: {detail['rejected']}\n"
            f"📘 გამოქვეყნებული: {detail['published']}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        )

        fb_section = ""
        try:
            fb_stats = _fb_page_cache if _fb_page_cache else await asyncio.to_thread(get_page_stats)
            if fb_stats.get("followers"):
                fb_section = f"📘 Facebook გვერდი:\n"
                net = fb_stats.get("fan_adds", 0) - fb_stats.get("fan_removes", 0)
                sign = "+" if net >= 0 else ""
                fb_section += f"  👥 მიმდევრები: {fb_stats.get('followers', 0):,} ({sign}{net})\n"
                if fb_stats.get("page_views"):
                    fb_section += f"  👀 გვერდის ნახვები: {fb_stats['page_views']:,}\n"
                top_posts = get_top(1)
                if top_posts:
                    tp = top_posts[0]
                    likes = int(tp.get('likes', 0) or 0)
                    cmts = int(tp.get('comments', 0) or 0)
                    title = (tp.get('title', '') or '')[:30]
                    fb_section += f"  🏆 ტოპ პოსტი: \"{title}\" (👍{likes} 💬{cmts})\n"
                fb_section += f"━━━━━━━━━━━━━━━━━━━━━\n"
        except Exception:
            pass

        report += fb_section
        report += f"🤖 აგენტი აქტიურია და მზადყოფნაშია!"

        await asyncio.to_thread(_send_telegram, report)
        return {"ok": True, "message": "Report sent to Telegram"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/test-weekly-report")
async def api_test_weekly_report():
    """Send a test weekly report to Telegram."""
    try:
        report = _build_weekly_report()
        await asyncio.to_thread(_send_telegram, report)
        return {"ok": True, "message": "Weekly report sent to Telegram"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.get("/api/debug/fb-post/{post_id}")
async def api_debug_fb_post(post_id: str):
    """Debug: try multiple field sets and show raw Graph API responses."""
    from facebook import GRAPH_URL, PAGE_TOKEN, PAGE_ID
    if not PAGE_TOKEN:
        return {"error": "No FB_PAGE_TOKEN"}
    results = {}
    # Test 1: Post fields (with shares)
    try:
        r1 = requests.get(f"{GRAPH_URL}/{post_id}", params={
            "access_token": PAGE_TOKEN,
            "fields": "likes.summary(true),comments.summary(true),shares,"
                      "reactions.type(LOVE).limit(0).summary(true).as(reactions_love),"
                      "reactions.type(HAHA).limit(0).summary(true).as(reactions_haha),created_time"
        }, timeout=15)
        results["post_fields"] = {"status": r1.status_code, "data": r1.json()}
    except Exception as e:
        results["post_fields"] = {"error": str(e)}
    # Test 2: Bare Photo fields (just likes + comments, no reactions)
    try:
        r2 = requests.get(f"{GRAPH_URL}/{post_id}", params={
            "access_token": PAGE_TOKEN,
            "fields": "likes.summary(true),comments.summary(true),created_time"
        }, timeout=15)
        results["photo_bare"] = {"status": r2.status_code, "data": r2.json()}
    except Exception as e:
        results["photo_bare"] = {"error": str(e)}
    # Test 4: PAGE_ID_post_id format
    if PAGE_ID and "_" not in str(post_id):
        compound = f"{PAGE_ID}_{post_id}"
        try:
            r4 = requests.get(f"{GRAPH_URL}/{compound}", params={
                "access_token": PAGE_TOKEN,
                "fields": "likes.summary(true),comments.summary(true),shares,"
                          "reactions.type(LOVE).limit(0).summary(true).as(reactions_love),created_time"
            }, timeout=15)
            results["compound_id"] = {"status": r4.status_code, "data": r4.json(), "id": compound}
        except Exception as e:
            results["compound_id"] = {"error": str(e)}
    return results


_fb_page_cache = {}  # cached page stats


@app.get("/api/fb/page-stats")
async def api_fb_page_stats():
    """Facebook page stats: followers, fans, name, growth, views."""
    global _fb_page_cache
    stats = await asyncio.to_thread(get_page_stats)
    insights = await asyncio.to_thread(get_page_insights)
    growth = await asyncio.to_thread(get_page_growth)
    views = await asyncio.to_thread(get_page_views)
    _fb_page_cache = {**stats, **insights, **growth, **views}
    return _fb_page_cache


@app.get("/api/fb/refresh-engagement")
async def api_fb_refresh_engagement():
    """Refresh engagement metrics (incl. reactions, reach) for all published posts."""
    posts = get_top(20)
    updated = 0
    for post in posts:
        fb_id = post.get("facebook_post_id")
        if not fb_id:
            continue
        metrics = await asyncio.to_thread(get_post_insights, fb_id)
        reach = await asyncio.to_thread(get_post_reach, fb_id)
        combined = {**metrics, **reach}
        if combined.get("likes", 0) or combined.get("comments", 0) or combined.get("shares", 0):
            update_activity(post["id"], **combined)
            updated += 1
    return {"updated": updated, "total": len(posts)}


@app.get("/api/fb/top-engaged")
async def api_fb_top_engaged(limit: int = 10):
    """Top posts sorted by engagement (likes+comments+shares), with reactions."""
    posts = get_top(50)
    for p in posts:
        p["engagement"] = int(p.get("likes", 0) or 0) + int(p.get("comments", 0) or 0) + int(p.get("shares", 0) or 0)
        p["reactions"] = {
            "love": int(p.get("reactions_love", 0) or 0),
            "haha": int(p.get("reactions_haha", 0) or 0),
            "wow": int(p.get("reactions_wow", 0) or 0),
            "sad": int(p.get("reactions_sad", 0) or 0),
            "angry": int(p.get("reactions_angry", 0) or 0),
        }
    posts.sort(key=lambda x: x["engagement"], reverse=True)
    return {"posts": posts[:limit]}


@app.get("/api/fb/computed-analytics")
async def api_fb_computed_analytics():
    """Computed analytics: engagement rate, best hour, source performance, reactions."""
    try:
        summary = await asyncio.to_thread(get_weekly_summary)
        return {
            "total_posts": summary.get("total_posts", 0),
            "likes": summary.get("likes", 0),
            "comments": summary.get("comments", 0),
            "shares": summary.get("shares", 0),
            "engagement_rate": summary.get("engagement_rate", 0),
            "avg_engagement": summary.get("avg_engagement", 0),
            "best_hour": summary.get("best_hour", "—"),
            "week_reach": summary.get("week_reach", 0),
            "reactions": summary.get("reactions", {}),
            "source_performance": summary.get("source_performance", {}),
            "top_posts": summary.get("top_posts", [])[:5],
            "by_source": summary.get("by_source", {}),
        }
    except Exception as e:
        print(f"[FB] Computed analytics error: {e}")
        return {"error": str(e)}


@app.post("/api/auto-generate")
async def api_auto_generate(theme: str = Form(...)):
    """Tavily → Gemini → card → Facebook.  Streams progress via SSE."""
    from search import search_tavily, download_image, create_placeholder

    card_id = uuid.uuid4().hex[:8]

    async def _stream():
        def _e(payload: dict) -> str:
            return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

        try:
            # 1. Tavily search
            yield _e({"t": "log", "m": f'Searching: "{theme}"'})
            tavily_res = await asyncio.to_thread(search_tavily, theme, 5)
            if "error" in tavily_res:
                yield _e({"t": "err", "m": tavily_res["error"]})
                return
            n_res = len(tavily_res.get("results", []))
            n_img = len(tavily_res.get("images",  []))
            yield _e({"t": "log", "m": f"Found: {n_res} articles, {n_img} images"})

            # 2. AI picks the best story  (Gemini → OpenAI Thinking → Claude/Kimi)
            card_info = None

            # Try Gemini first (best Georgian copywriting)
            if os.environ.get("GEMINI_API_KEY"):
                yield _e({"t": "log", "m": "Gemini 3 Flash Preview..."})
                card_info = await asyncio.to_thread(_pick_gemini, tavily_res)
                if "error" in card_info:
                    yield _e({"t": "log", "m": f"Gemini: {card_info['error'][:60]} — fallback OpenAI..."})
                    card_info = None

            # Fallback: OpenAI o3-mini
            if card_info is None and os.environ.get("OPENAI_API_KEY"):
                yield _e({"t": "log", "m": "OpenAI o3-mini fallback..."})
                card_info = await asyncio.to_thread(_pick_openai_thinking, tavily_res)
                if "error" in card_info:
                    yield _e({"t": "log", "m": f"OpenAI: {card_info['error'][:60]} — fallback Agent..."})
                    card_info = None

            # Last resort: Claude/Kimi Agent
            if card_info is None:
                yield _e({"t": "log", "m": "Agent system fallback..."})
                card_info = await asyncio.to_thread(_ai_pick_story, tavily_res.get("results", []))
                if "error" in card_info:
                    yield _e({"t": "err", "m": card_info["error"]})
                    return
                # if fallback didn't pick an image, grab the first Tavily image
                if not card_info.get("image_url"):
                    imgs = tavily_res.get("images", [])
                    if imgs:
                        card_info["image_url"] = imgs[0]

            name      = card_info.get("name", "Unknown")
            text      = card_info.get("text", "")
            image_url = card_info.get("image_url")
            yield _e({"t": "log", "m": f"AI: {name}"})

            # 3. Get photo — prefer real web photo over AI-generated
            photo_path = None

            # First: try downloading real photo from Tavily/AI-selected URL
            if image_url:
                yield _e({"t": "log", "m": "Downloading real photo..."})
                photo_path = await asyncio.to_thread(
                    download_image, image_url, f"temp/auto_{card_id}.jpg"
                )
                if photo_path:
                    yield _e({"t": "log", "m": "Real photo OK"})

            # Second: try other Tavily images if first failed
            if not photo_path:
                for img_url in tavily_res.get("images", [])[:5]:
                    if img_url == image_url:
                        continue
                    yield _e({"t": "log", "m": "Trying alternative photo..."})
                    photo_path = await asyncio.to_thread(
                        download_image, img_url, f"temp/auto_{card_id}.jpg"
                    )
                    if photo_path:
                        yield _e({"t": "log", "m": "Alternative photo OK"})
                        break

            # Third: Gemini Imagen as last resort
            if not photo_path:
                img_prompt = (
                    f"Professional news photograph: {name}. "
                    f"{text}. "
                    "Photojournalism style, realistic, no text/watermarks/illustrations."
                )
                yield _e({"t": "log", "m": "Gemini Imagen generating..."})
                photo_path = await asyncio.to_thread(
                    _generate_image_gemini, img_prompt, f"temp/auto_{card_id}.jpg"
                )

            if not photo_path:
                yield _e({"t": "log", "m": "Using placeholder..."})
                photo_path = await asyncio.to_thread(create_placeholder)

            # 4. Save photo as card (no text overlay — just the photo)
            yield _e({"t": "log", "m": "Saving card..."})
            card_path = CARDS / f"{card_id}_auto.jpg"
            await asyncio.to_thread(
                _save_photo_as_card, photo_path, str(card_path)
            )

            # No auto-upload — user clicks "Upload to Facebook" button
            card_url = f"/cards/{card_id}_auto.jpg"
            _add_history(name, card_url)
            log_activity(source="auto_card", title=name, status="approved", card_image_url=card_url, caption=text)
            yield _e({"t": "log", "m": "Ready!"})
            yield _e({"t": "done", "card_url": card_url, "name": name, "article": text})

        except Exception as exc:
            yield _e({"t": "err", "m": str(exc)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


# ---------------------------------------------------------------------------
# Git automation helper (works on Railway with GITHUB_TOKEN)
# ---------------------------------------------------------------------------
def _git_commit_and_push(file_path: str, commit_message: str) -> bool:
    """Auto-commit and push a file to GitHub. Returns True on success."""
    import subprocess
    import os

    # Skip git operations if not available
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, timeout=2)
        if result.returncode != 0:
            print(f"[Git] ⚠ Git not available, skipping commit")
            return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"[Git] ⚠ Git not found, skipping commit")
        return False

    # Check if we're in a git repository
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    git_dir = os.path.join(repo_dir, ".git")
    if not os.path.exists(git_dir):
        print(f"[Git] ⚠ Not a git repository, skipping commit")
        return False

    try:
        github_token = os.environ.get("GITHUB_TOKEN")

        # Configure git
        subprocess.run(["git", "config", "user.name", "Railway Bot"],
                        capture_output=True, cwd=repo_dir, timeout=2)
        subprocess.run(["git", "config", "user.email", "bot@railway.app"],
                        capture_output=True, cwd=repo_dir, timeout=2)

        # Add the specific file
        subprocess.run(["git", "add", file_path], check=True, capture_output=True, cwd=repo_dir, timeout=5)
        # Commit with message
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            check=True, capture_output=True, text=True, cwd=repo_dir, timeout=5
        )
        # Push with token URL (works even without upstream set)
        push_url = f"https://zhorzholianitornike:{github_token}@github.com/zhorzholianitornike/jorjick.git" if github_token else "origin"
        subprocess.run(
            ["git", "push", push_url, "HEAD:main"],
            check=True, capture_output=True, text=True, cwd=repo_dir, timeout=15
        )
        print(f"[Git] ✓ {file_path} committed and pushed")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Git] ✗ Failed: {e.stderr if hasattr(e, 'stderr') else e}")
        return False
    except subprocess.TimeoutExpired:
        print(f"[Git] ✗ Timeout - git operation too slow")
        return False
    except Exception as e:
        print(f"[Git] ✗ Error: {e}")
        return False


# ---------------------------------------------------------------------------
# Facebook upload + Telegram notification
# ---------------------------------------------------------------------------
def _send_telegram(text: str):
    """Send a message to TELEGRAM_ADMIN_ID via Bot API (blocking, run in thread)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_ADMIN_ID, "text": text},
            timeout=10,
        )
    except Exception as exc:
        print(f"[TG] Notification failed: {exc}")


def _upload_and_notify(card_path: str, name: str, caption: str = ""):
    """Upload to Facebook, then notify via Telegram. Meant to run in a thread."""
    now     = datetime.now(TBILISI).strftime("%H:%M  %d/%m/%Y")
    fb_caption = caption if caption else name
    success = post_photo(card_path, fb_caption)
    if success:
        _send_telegram(f"ქარდი ატვირთულია\nქარდის სახელი: {name}\n{now}")
    else:
        _send_telegram(f"ქარდი ატვირთვა ჩამიდა\nქარდის სახელი: {name}\n{now}")


# ---------------------------------------------------------------------------
# AI story picker  (single-turn, no tool loop)
# ---------------------------------------------------------------------------
def _ai_pick_story(results: list[dict]) -> dict:
    """Send search results to Kimi / Claude → {name, text, image_url}."""
    prompt = (
        "You are a Georgian news editor. Pick the MOST interesting story and extract:\n"
        "IMPORTANT: Write EVERYTHING in Georgian language (ქართული ენა)!\n"
        "- name: headline in Georgian (max 40 chars)\n"
        "- text: summary in Georgian 1-2 sentences (max 120 chars)\n"
        "- image_url: a URL from the results that likely contains an image, or null\n\n"
        "Results:\n" + json.dumps(results, ensure_ascii=False) + "\n\n"
        "Reply ONLY with valid JSON:\n"
        '{"name":"სათაური ქართულად","text":"შეჯამება ქართულად","image_url":"… or null"}'
    )

    backend = os.environ.get("BACKEND", "claude").lower()

    try:
        if backend == "kimi":
            from openai import OpenAI
            client = OpenAI(
                api_key=os.environ.get("MOONSHOT_API_KEY"),
                base_url="https://api.moonshot.ai/v1",
            )
            resp = client.chat.completions.create(
                model="kimi-k2-0905-preview",
                max_tokens=256,
                temperature=0.3,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.choices[0].message.content or ""
        else:
            import anthropic as _anthropic
            client = _anthropic.Anthropic(
                api_key=os.environ.get("ANTHROPIC_API_KEY")
            )
            resp = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text

        # strip markdown code-block wrapper if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        # extract outermost JSON object
        start = raw.index("{")
        end   = raw.rindex("}")
        data  = json.loads(raw[start:end + 1])

        # normalise null-like values
        if data.get("image_url") in (None, "null", ""):
            data["image_url"] = None

        return data

    except Exception as exc:
        return {"error": f"AI: {exc}"}


# ---------------------------------------------------------------------------
# OpenAI Thinking story picker  (o3-mini with reasoning for better copywriting)
# ---------------------------------------------------------------------------
def _pick_openai_thinking(tavily_res: dict) -> dict:
    """Use OpenAI o3-mini (thinking model) for superior copywriting.
    Returns {name, text, image_url} or {error: ...}."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY env var is not set"}

    client = OpenAI(api_key=api_key)

    # format articles for the prompt
    lines = []
    for i, r in enumerate(tavily_res.get("results", []), 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('content', '')[:300]}")

    images = tavily_res.get("images", [])

    # --- Step 1: Extract structured facts ---
    facts_prompt = (
        "შენ ხარ ნიუს რედაქტორი. აირჩიე ყველაზე საინტერესო ამბავი და ამოიღე ფაქტები.\n\n"
        "სტატიები:\n" + "\n".join(lines) + "\n\n"
        "ფოტოების URL-ები:\n" + "\n".join(images[:10] or ["none"]) + "\n\n"
        "უპასუხე მხოლოდ JSON-ით:\n"
        '{"headline":"სათაური ქართულად 3-5 სიტყვა",'
        '"who":"ვინ არის მთავარი მოქმედი პირი/ორგანიზაცია",'
        '"what":"რა მოხდა (1 წინადადება)",'
        '"where":"სად (ქალაქი/ქვეყანა ან null)",'
        '"event_date":"თარიღი ან null",'
        '"why_it_matters":"რატომ არის მნიშვნელოვანი (1 წინადადება)",'
        '"confidence":85,'
        '"image_url":"საუკეთესო რეალური ფოტოს URL ან null"}'
    )

    try:
        # Step 1: facts
        resp1 = client.chat.completions.create(
            model="o3-mini",
            max_completion_tokens=2048,
            messages=[{"role": "user", "content": facts_prompt}],
        )
        raw1 = resp1.choices[0].message.content or ""
        if "```" in raw1:
            raw1 = raw1.split("```")[1]
            if raw1.startswith("json"):
                raw1 = raw1[4:]
        facts = json.loads(raw1[raw1.index("{"):raw1.rindex("}") + 1])

        if facts.get("image_url") in (None, "null", ""):
            facts["image_url"] = None

        # --- Step 2: Generate Facebook caption from facts ---
        caption_prompt = (
            "You are a Georgian social media copywriter.\n"
            "Write a Facebook caption based ONLY on the JSON facts below.\n\n"
            "Constraints:\n"
            "- 1 short hook line + 2-4 short sentences.\n"
            "- Mention only facts present in JSON.\n"
            "- If event_date is null, do NOT mention dates.\n"
            "- Add 3-6 relevant hashtags. No spam.\n"
            '- If confidence < 80, add "დეტალები ზუსტდება."\n\n'
            "JSON:\n" + json.dumps(facts, ensure_ascii=False)
        )

        resp2 = client.chat.completions.create(
            model="o3-mini",
            max_completion_tokens=2048,
            messages=[{"role": "user", "content": caption_prompt}],
        )
        caption = resp2.choices[0].message.content or ""
        # clean up any markdown wrapping
        caption = caption.strip().strip("`").strip()
        if caption.startswith("json"):
            caption = caption[4:].strip()

        data = {
            "name": facts.get("headline", "Unknown"),
            "text": caption,
            "image_url": facts.get("image_url"),
        }

        return data

    except Exception as exc:
        return {"error": f"OpenAI Thinking: {exc}"}


# ---------------------------------------------------------------------------
# Gemini story picker  (single-turn, used by /api/auto-generate)
# ---------------------------------------------------------------------------
def _pick_gemini(tavily_res: dict) -> dict:
    """Send Tavily results to Gemini → {name, text, image_url}."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"error": "GEMINI_API_KEY env var is not set"}

    client = genai.Client(api_key=api_key)

    # format articles for the prompt
    lines = []
    for i, r in enumerate(tavily_res.get("results", []), 1):
        lines.append(f"{i}. {r.get('title', '')}\n   {r.get('content', '')[:200]}")

    images = tavily_res.get("images", [])

    prompt = (
        "You are a Georgian news editor. Pick the MOST interesting story from these results.\n"
        "IMPORTANT: Write EVERYTHING in Georgian language (ქართული ენა)!\n"
        "Reply ONLY with valid JSON, no other text:\n"
        '{"name":"სათაური ქართულად 3-4 სიტყვა","text":"შეჯამება ქართულად 30-40 სიტყვა","image_url":"best image URL or null"}\n\n'
        "Results:\n" + "\n".join(lines) + "\n\n"
        "Available image URLs:\n" + "\n".join(images[:10] or ["none"]) + "\n"
    )

    try:
        resp = client.models.generate_content(
            model="gemini-3-flash-preview",
            contents=prompt,
        )
        raw  = resp.text

        # strip markdown code-block wrapper if present
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        start = raw.index("{")
        end   = raw.rindex("}")
        data  = json.loads(raw[start:end + 1])

        if data.get("image_url") in (None, "null", ""):
            data["image_url"] = None

        return data

    except Exception as exc:
        return {"error": f"Gemini: {exc}"}


# ---------------------------------------------------------------------------
# Gemini Imagen  (generate a photo from a text prompt)
# ---------------------------------------------------------------------------
def _generate_image_gemini(prompt: str, dest: str) -> Optional[str]:
    """Generate an image via Imagen 3.  Returns local path or None on any error."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_image(
            model="imagen-3.0-generate-001",
            prompt=prompt,
        )
        # response.generated_images[0].image  →  PIL Image
        img = response.generated_images[0].image
        img.save(dest, "JPEG", quality=90)
        print(f"[GenImg] saved → {dest}")
        return dest
    except Exception as exc:
        print(f"[GenImg] {exc}")
        return None


# ---------------------------------------------------------------------------
# Save photo as card (just resize/crop, no text overlay)
# ---------------------------------------------------------------------------
def _save_photo_as_card(photo_path: str, output_path: str) -> str:
    """Resize and crop photo to card dimensions (1080x1350). No text overlay."""
    from PIL import Image

    W, H = 1080, 1350
    img = Image.open(photo_path).convert("RGB")
    ratio = max(W / img.width, H / img.height)
    nw, nh = int(img.width * ratio), int(img.height * ratio)
    img = img.resize((nw, nh), Image.LANCZOS)
    left = (nw - W) // 2
    top = (nh - H) // 2
    img = img.crop((left, top, left + W, top + H))

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=95)
    return output_path


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------
def _add_history(name: str, card_url: str):
    history.insert(0, {
        "name":     name,
        "card_url": card_url,
        "time":     datetime.now().strftime("%H:%M  %d/%m"),
    })
    del history[20:]          # keep last 20


# ---------------------------------------------------------------------------
# Google Sheet employee database
# ---------------------------------------------------------------------------
SHEET_ID = "15lWgliZOzTojrTOmO3LyM-T_CWhOc-e5C6ARXg6LVSI"
_employee_cache: list[dict] = []
_employee_cache_time: float = 0


def _load_employees() -> list[dict]:
    """Load employee data from Google Sheet (CSV export). Cached for 5 min."""
    global _employee_cache, _employee_cache_time
    import time, csv, io

    now = time.time()
    if _employee_cache and (now - _employee_cache_time) < 300:
        return _employee_cache

    try:
        url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        resp.encoding = "utf-8"

        reader = csv.reader(io.StringIO(resp.text))
        rows = list(reader)

        # Find header row (contains "სახელი")
        header_idx = 0
        for i, row in enumerate(rows):
            if any("სახელი" in cell for cell in row):
                header_idx = i
                break

        employees = []
        for row in rows[header_idx + 1:]:
            if len(row) >= 4 and row[0].strip():
                employees.append({
                    "first_name": row[0].strip(),
                    "last_name": row[1].strip(),
                    "phone": row[2].strip(),
                    "internal": row[3].strip(),
                })

        _employee_cache = employees
        _employee_cache_time = now
        print(f"[Sheet] Loaded {len(employees)} employees")
        return employees

    except Exception as exc:
        print(f"[Sheet] Load failed: {exc}")
        return _employee_cache  # return stale cache on error


def _employee_lookup_openai(question: str) -> str:
    """Use OpenAI to answer employee-related questions from Sheet data."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY არ არის დაყენებული."

    employees = _load_employees()
    if not employees:
        return "თანამშრომლების ბაზა ცარიელია ან ვერ ჩაიტვირთა."

    # Format employee data for context
    emp_lines = []
    for e in employees:
        emp_lines.append(
            f"- {e['first_name']} {e['last_name']}: "
            f"მობილური: {e['phone']}, შიდა ნომერი: {e['internal']}"
        )
    emp_text = "\n".join(emp_lines)

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "შენ ხარ რუსთავი 2-ის ასისტენტი. შენ გაქვს თანამშრომლების მონაცემთა ბაზა.\n"
                        "უპასუხე მომხმარებლის კითხვას ქართულად, მხოლოდ ბაზაში არსებული ინფორმაციის საფუძველზე.\n"
                        "თუ თანამშრომელი ვერ მოიძებნა, თქვი რომ ბაზაში ასეთი თანამშრომელი არ მოიძებნა.\n"
                        "პასუხი იყოს მოკლე და კონკრეტული.\n\n"
                        f"თანამშრომლების ბაზა:\n{emp_text}"
                    ),
                },
                {"role": "user", "content": question},
            ],
            max_tokens=500,
        )
        return resp.choices[0].message.content or "პასუხი ვერ დაგენერირდა."

    except Exception as exc:
        print(f"[AI Lookup] Error: {exc}")
        return f"შეცდომა: {exc}"


# ---------------------------------------------------------------------------
# RSS Feed Management — sources, fetcher, queue, translation
# ---------------------------------------------------------------------------
import time as _time

_rss_sources: list[dict] = [
    {"id": "cnn-top",     "name": "CNN Top Stories", "url": "http://rss.cnn.com/rss/edition.rss",       "category": "World",    "enabled": True, "interval_min": 30, "last_checked": 0},
    {"id": "cnn-world",   "name": "CNN World",       "url": "http://rss.cnn.com/rss/edition_world.rss", "category": "World",    "enabled": True, "interval_min": 30, "last_checked": 0},
    {"id": "cnn-business","name": "CNN Business",     "url": "http://rss.cnn.com/rss/money_latest.rss",  "category": "Business", "enabled": True, "interval_min": 30, "last_checked": 0},
    {"id": "bbc-news",    "name": "BBC News",         "url": "https://feeds.bbci.co.uk/news/rss.xml",    "category": "World",    "enabled": True, "interval_min": 30, "last_checked": 0},
]
_rss_seen_urls: set = set()
_rss_queue: list[dict] = []       # [{title, title_ka, desc_ka, url, image_url, source_name, source_cat}]
_rss_min_interval: int = 1800     # min seconds between two posts (default 30 min)
_rss_id_counter: int = 100


def _fetch_rss_feed(source: dict) -> list[dict]:
    """Fetch and parse a single RSS feed. Returns list of new articles."""
    import feedparser

    try:
        feed = feedparser.parse(source["url"])
        articles = []
        for entry in feed.entries[:10]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            if not link or not title:
                continue
            if link in _rss_seen_urls:
                continue

            # Try to extract image
            image_url = None
            if hasattr(entry, "media_content") and entry.media_content:
                image_url = entry.media_content[0].get("url")
            elif hasattr(entry, "media_thumbnail") and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get("url")
            elif hasattr(entry, "enclosures") and entry.enclosures:
                for enc in entry.enclosures:
                    if "image" in enc.get("type", ""):
                        image_url = enc.get("href")
                        break

            desc = entry.get("summary", entry.get("description", ""))
            # Strip HTML from description
            if desc and "<" in desc:
                from bs4 import BeautifulSoup
                desc = BeautifulSoup(desc, "html.parser").get_text(strip=True)

            articles.append({
                "title": title,
                "url": link,
                "description": desc[:500] if desc else "",
                "image_url": image_url,
                "source_name": source["name"],
                "source_cat": source["category"],
            })

        return articles
    except Exception as exc:
        print(f"[RSS] Fetch failed for {source['name']}: {exc}")
        return []


def _translate_to_georgian(title: str, description: str) -> dict:
    """Translate title + description to Georgian via Gemini."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"title_ka": title, "desc_ka": description}

    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "თარგმნე შემდეგი ინგლისური სიახლე ქართულად.\n"
            "პასუხი მხოლოდ JSON ფორმატში, სხვა არაფერი:\n"
            '{"title_ka":"სათაური ქართულად","desc_ka":"აღწერა ქართულად 2-3 წინადადებით"}\n\n'
            f"Title: {title}\n"
            f"Description: {description[:400]}"
        )

        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        raw = resp.text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        start = raw.index("{")
        end = raw.rindex("}")
        data = json.loads(raw[start:end + 1])
        return {
            "title_ka": data.get("title_ka", title),
            "desc_ka": data.get("desc_ka", description),
        }
    except Exception as exc:
        print(f"[RSS] Translation failed: {exc}")
        return {"title_ka": title, "desc_ka": description}


def _send_rss_news_to_telegram(news_id: str, article: dict):
    """Send an RSS news article to Telegram with approve/reject buttons."""
    source_label = f"📡 {article.get('source_name', 'RSS')}"
    caption = (
        f"📰 <b>ახალი სიახლე</b> — {source_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{article.get('title_ka', article['title'])}</b>\n\n"
        f"{article.get('desc_ka', '')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ დადასტურება", "callback_data": f"news_approve:{news_id}"},
            {"text": "❌ უარყოფა", "callback_data": f"news_reject:{news_id}"},
        ]]
    }

    if article.get("image_url"):
        result = _send_telegram_photo(article["image_url"], caption, reply_markup)
        if result and result.get("ok"):
            return

    # Fallback to text
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_ADMIN_ID,
                "text": caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
            timeout=10,
        )
    except Exception as exc:
        print(f"[RSS] TG send failed: {exc}")


# ---------------------------------------------------------------------------
# interpressnews.ge scraper + auto-news state
# ---------------------------------------------------------------------------
_pending_news: dict = {}       # {news_id: {title, url, image_url, time}}
_seen_news_urls: set = set()   # already sent/processed URLs
_news_interval: int = 900      # seconds between news checks (default 15 min)


def _scrape_interpressnews() -> list[dict]:
    """Scrape latest politics news from interpressnews.ge.
    Returns [{title, url, image_url, time}, ...]."""
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(
            "https://interpressnews.ge/ka/category/5-politika/",
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
            timeout=15,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as exc:
        print(f"[IPN] Scrape failed: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    articles = []

    for item in soup.find_all("div", itemscope=True, itemtype="http://schema.org/Article"):
        a_tag = item.find("a", itemprop="url")
        h2_tag = item.find("h2", itemprop="name")
        img_tag = item.find("img", itemprop="image")
        time_tag = item.find("time")

        if not a_tag or not h2_tag:
            continue

        href = a_tag.get("href", "")
        if href and not href.startswith("http"):
            href = "https://interpressnews.ge" + href

        image_url = None
        if img_tag:
            image_url = img_tag.get("data-src") or img_tag.get("src")

        articles.append({
            "title": h2_tag.get_text(strip=True),
            "url": href,
            "image_url": image_url,
            "time": time_tag.get("datetime", "") if time_tag else "",
        })

    print(f"[IPN] Scraped {len(articles)} articles")
    return articles


def _scrape_article_text(url: str) -> str:
    """Scrape full article text from an interpressnews.ge article page."""
    from bs4 import BeautifulSoup

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            verify=False,
            timeout=15,
        )
        resp.raise_for_status()
        resp.encoding = "utf-8"
    except Exception as exc:
        print(f"[IPN] Article scrape failed: {exc}")
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")
    paragraphs = soup.find_all("p")
    texts = [p.get_text(strip=True) for p in paragraphs if len(p.get_text(strip=True)) > 20]
    return "\n".join(texts)


def _generate_fb_caption(title: str, article_text: str, url: str) -> str:
    """Use Gemini to generate a detailed Facebook caption with hashtags."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return f"📰 {title}\n\n{article_text[:300]}"

    try:
        client = genai.Client(api_key=api_key)
        prompt = (
            "შენ ხარ ქართული მედიის სოციალური ქსელების რედაქტორი.\n"
            "დაწერე Facebook-ის პოსტი შემდეგი სიახლისთვის.\n\n"
            "წესები:\n"
            "- დაწერე ქართულად\n"
            "- პირველი ხაზი: მოკლე, ყურადღების მიპყრობა (hook)\n"
            "- შემდეგ 3-5 წინადადებით აღწერე სიახლე დეტალურად\n"
            "- ბოლოს დაამატე 5-8 რელევანტური ჰეშთეგი ქართულად და ინგლისურად\n"
            "- არ გამოიყენო emoji ტექსტში, მხოლოდ ჰეშთეგებამდე ერთი 📰\n"
            "- არ მოიგონო ფაქტები, მხოლოდ ტექსტში არსებული ინფორმაცია გამოიყენე\n"
            "- არ ჩასვა წყაროს ბმული ან URL — მხოლოდ ტექსტი და ჰეშთეგები\n\n"
            f"სათაური: {title}\n\n"
            f"სტატიის ტექსტი:\n{article_text[:1500]}\n\n"
            "დაწერე მხოლოდ Facebook პოსტის ტექსტი, სხვა არაფერი:"
        )

        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        caption = resp.text.strip()
        return caption

    except Exception as exc:
        print(f"[Caption] Gemini failed: {exc}")
        return f"📰 {title}\n\n{article_text[:300]}"


def _send_telegram_photo(image_url: str, caption: str, reply_markup: dict = None):
    """Send a photo message to TELEGRAM_ADMIN_ID (blocking)."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        return None
    try:
        data = {
            "chat_id": TELEGRAM_ADMIN_ID,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if reply_markup:
            data["reply_markup"] = json.dumps(reply_markup)
        resp = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto",
            data=data,
            timeout=15,
        )
        return resp.json()
    except Exception as exc:
        print(f"[TG] Photo send failed: {exc}")
        return None


def _send_news_to_telegram(news_id: str, article: dict):
    """Send a news article to Telegram with approve/reject buttons."""
    caption = (
        f"📰 <b>ახალი სიახლე</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>{article['title']}</b>\n\n"
        f"🔗 {article['url']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ დადასტურება", "callback_data": f"news_approve:{news_id}"},
            {"text": "❌ უარყოფა", "callback_data": f"news_reject:{news_id}"},
        ]]
    }

    if article.get("image_url"):
        result = _send_telegram_photo(article["image_url"], caption, reply_markup)
        if result and result.get("ok"):
            return
        # fallback to text if photo send fails

    # Send as text message
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_ADMIN_ID,
                "text": caption,
                "parse_mode": "HTML",
                "reply_markup": reply_markup,
            },
            timeout=10,
        )
    except Exception as exc:
        print(f"[TG] News send failed: {exc}")


# ---------------------------------------------------------------------------
# Telegram bot  (background asyncio task)
# ---------------------------------------------------------------------------
async def _run_telegram():
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_BOT_TOKEN not set — Telegram bot skipped")
        return

    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import (
        Application, CallbackQueryHandler, CommandHandler,
        ConversationHandler, MessageHandler, filters,
    )

    S_PHOTO, S_TEXT = 0, 1

    async def tg_start(update: Update, ctx):
        await update.message.reply_text(
            "News Card Bot\n\n"
            "1. Send a photo\n"
            "2. Then send:\n\n"
            "    Name\n"
            '    "text"\n\n'
            "/cancel — stop"
        )
        return S_PHOTO

    async def tg_photo(update: Update, ctx):
        f    = await update.message.photo[-1].get_file()
        path = UPLOADS / f"tg_{update.effective_user.id}.jpg"
        path.write_bytes(await f.download_as_bytearray())
        ctx.user_data["photo"] = str(path)
        await update.message.reply_text('Photo saved.\n\nName\n"text"')
        return S_TEXT

    async def tg_text(update: Update, ctx):
        parts = update.message.text.strip().split("\n", 1)
        if len(parts) < 2:
            await update.message.reply_text('Two lines needed:\n\nName\n"text"')
            return S_TEXT

        name, desc = parts[0].strip(), parts[1].strip().strip('"')
        photo_path = ctx.user_data.get("photo")
        if not photo_path:
            await update.message.reply_text("/start again.")
            return ConversationHandler.END

        cid  = uuid.uuid4().hex[:8]
        out  = CARDS / f"{cid}_card.jpg"
        try:
            generator.generate(photo_path, name, desc, str(out))
            with open(out, "rb") as fh:
                await update.message.reply_photo(photo=fh)
            _add_history(name, f"/cards/{cid}_card.jpg")
            asyncio.create_task(asyncio.to_thread(_upload_and_notify, str(out), name))
        except Exception as exc:
            await update.message.reply_text(f"Error: {exc}")

        Path(photo_path).unlink(missing_ok=True)
        ctx.user_data.clear()
        await update.message.reply_text("Done! /start for another.")
        return ConversationHandler.END

    async def tg_cancel(update: Update, ctx):
        ctx.user_data.clear()
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END

    # ── voice generation via /voice command ──────────────────────────
    async def tg_voice(update: Update, ctx):
        """Handle /voice command — generate TTS from text."""
        text = update.message.text.replace("/voice", "", 1).strip()
        if not text:
            await update.message.reply_text(
                "🎙️ ხმოვანი გენერაცია\n\n"
                "გამოყენება:\n"
                "/voice შენი ტექსტი აქ\n\n"
                "მაგალითი:\n"
                "/voice გამარჯობა, ეს არის ტესტი"
            )
            return

        if len(text) > 5000:
            await update.message.reply_text("ტექსტი ძალიან გრძელია (მაქს 5000 სიმბოლო)")
            return

        await update.message.reply_text("🎙️ ხმა გენერირდება, დაელოდეთ...")

        try:
            from google import genai
            from google.genai import types
            import wave

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                await update.message.reply_text("GEMINI_API_KEY არ არის დაყენებული")
                return

            client = genai.Client(api_key=api_key)

            response = await asyncio.to_thread(
                lambda: client.models.generate_content(
                    model="gemini-2.5-flash-preview-tts",
                    contents=f"Read the following Georgian text naturally:\n{text}",
                    config=types.GenerateContentConfig(
                        response_modalities=["AUDIO"],
                        speech_config=types.SpeechConfig(
                            voice_config=types.VoiceConfig(
                                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                    voice_name="Charon",
                                )
                            )
                        ),
                    )
                )
            )

            audio_data = response.candidates[0].content.parts[0].inline_data.data
            if not audio_data:
                await update.message.reply_text("Audio ვერ გენერირდა")
                return

            # Save as WAV
            voice_id = uuid.uuid4().hex[:8]
            voice_file = VOICES / f"tg_voice_{voice_id}.wav"

            with wave.open(str(voice_file), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(audio_data)

            # Send audio file
            with open(voice_file, "rb") as af:
                await update.message.reply_voice(voice=af)

        except Exception as exc:
            await update.message.reply_text(f"შეცდომა: {exc}")

    # ── news approval callback handler ──────────────────────────────
    async def tg_news_callback(update: Update, ctx):
        """Handle approve/reject callbacks for auto-news."""
        query = update.callback_query
        await query.answer()

        data = query.data or ""
        if not data.startswith("news_"):
            return

        parts = data.split(":", 1)
        if len(parts) != 2:
            return

        action, news_id = parts[0].replace("news_", ""), parts[1]
        article = _pending_news.pop(news_id, None)

        # Helper: edit caption (photo msg) or text (text msg)
        async def _edit_msg(text, parse_mode="HTML"):
            try:
                await query.edit_message_caption(caption=text, parse_mode=parse_mode)
            except Exception:
                await query.edit_message_text(text=text, parse_mode=parse_mode)

        if not article:
            await _edit_msg("⚠️ სიახლე ვერ მოიძებნა ან უკვე დამუშავებულია.")
            return

        if action == "approve":
            await _edit_msg(
                f"✅ დადასტურებულია!\n\n"
                f"<b>{article['title']}</b>\n\n"
                f"⏳ ქარდი მზადდება და Facebook-ზე იტვირთება..."
            )

            # Generate card and upload to Facebook in background
            async def _process_approved_news(art):
                try:
                    from search import download_image, create_placeholder

                    card_id = uuid.uuid4().hex[:8]
                    photo_path = None

                    # Download article image
                    if art.get("image_url"):
                        photo_path = await asyncio.to_thread(
                            download_image, art["image_url"], f"temp/news_{card_id}.jpg"
                        )

                    # Fallback to placeholder
                    if not photo_path:
                        photo_path = await asyncio.to_thread(create_placeholder)

                    # Generate card
                    card_path = str(CARDS / f"{card_id}_news.jpg")
                    await asyncio.to_thread(
                        _save_photo_as_card, photo_path, card_path
                    )

                    # Generate Facebook caption
                    display_title = art.get("title_ka") or art["title"]

                    if art.get("title_ka"):
                        # RSS article — already translated, use desc_ka
                        caption = await asyncio.to_thread(
                            _generate_fb_caption, display_title, art.get("desc_ka", ""), ""
                        )
                    else:
                        # IPN article — scrape full text
                        article_text = await asyncio.to_thread(
                            _scrape_article_text, art["url"]
                        )
                        caption = await asyncio.to_thread(
                            _generate_fb_caption, display_title, article_text, ""
                        )

                    # Upload to Facebook
                    fb_result = await asyncio.to_thread(post_photo_ext, card_path, caption)

                    _add_history(display_title, f"/cards/{card_id}_news.jpg")

                    # Determine source for logging
                    _src = "interpressnews"
                    sn = art.get("source_name", "").lower()
                    if "cnn" in sn:
                        _src = "rss_cnn"
                    elif "bbc" in sn:
                        _src = "rss_bbc"
                    elif art.get("title_ka"):
                        _src = "rss_other"

                    log_activity(
                        source=_src, title=display_title, status="approved",
                        card_image_url=f"/cards/{card_id}_news.jpg",
                        caption=caption,
                        facebook_post_id=fb_result.get("post_id"),
                    )

                    if fb_result["success"]:
                        _send_telegram(
                            f"✅ Facebook-ზე ატვირთულია!\n\n"
                            f"📰 {display_title}"
                        )
                    else:
                        _send_telegram(
                            f"⚠️ Facebook ატვირთვა ვერ მოხერხდა\n\n"
                            f"📰 {display_title}"
                        )

                except Exception as exc:
                    print(f"[News] Process failed: {exc}")
                    _send_telegram(f"❌ შეცდომა: {exc}")

            asyncio.create_task(_process_approved_news(article))

        elif action == "reject":
            _seen_news_urls.add(article["url"])
            # Log rejection
            _src = "interpressnews"
            sn = article.get("source_name", "").lower()
            if "cnn" in sn:
                _src = "rss_cnn"
            elif "bbc" in sn:
                _src = "rss_bbc"
            elif article.get("title_ka"):
                _src = "rss_other"
            log_activity(source=_src, title=article["title"], status="rejected")
            await _edit_msg(
                f"❌ გამოტოვებულია\n\n"
                f"<s>{article['title']}</s>"
            )

    # ── employee lookup via natural language ─────────────────────────
    async def tg_employee_query(update: Update, ctx):
        """Handle free-text messages — employee lookup via OpenAI."""
        text = update.message.text.strip()
        if not text or len(text) < 3:
            return

        await update.message.reply_text("🔍 ვეძებ...")

        try:
            answer = await asyncio.to_thread(_employee_lookup_openai, text)
            await update.message.reply_text(answer)
        except Exception as exc:
            await update.message.reply_text(f"შეცდომა: {exc}")

    tg = Application.builder().token(TELEGRAM_TOKEN).build()
    tg.add_handler(CallbackQueryHandler(tg_news_callback, pattern=r"^news_"))
    tg.add_handler(CommandHandler("voice", tg_voice))
    tg.add_handler(CommandHandler("fb_weekly", tg_fb_weekly))
    tg.add_handler(CommandHandler("fb_monthly", tg_fb_monthly))
    tg.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", tg_start)],
        states={
            S_PHOTO: [MessageHandler(filters.PHOTO,                     tg_photo)],
            S_TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND,    tg_text)],
        },
        fallbacks=[CommandHandler("cancel", tg_cancel)],
    ))
    # Free-text handler (lowest priority — after ConversationHandler)
    tg.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, tg_employee_query))

    await tg.initialize()
    await tg.start()
    await tg.updater.start_polling()
    print("[>>] Telegram bot is polling …")


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    ensure_font()                                   # download Georgian font if missing
    asyncio.create_task(_run_telegram())            # telegram runs alongside FastAPI
    asyncio.create_task(_hourly_status_report())    # hourly status reports
    asyncio.create_task(_auto_news_loop())          # auto-news every 15 min
    asyncio.create_task(_rss_checker_loop())         # RSS feed checker
    asyncio.create_task(_rss_queue_sender_loop())    # RSS queue sender
    asyncio.create_task(_fb_insights_loop())           # FB engagement refresh
    asyncio.create_task(_weekly_report_loop())          # weekly summary (Monday 10:00)
    from analytics import setup_analytics               # FB analytics module
    asyncio.create_task(setup_analytics(app))            # analytics loops + endpoints


# ---------------------------------------------------------------------------
# Hourly status report via Telegram
# ---------------------------------------------------------------------------
_start_time = datetime.now(TBILISI)

async def _hourly_status_report():
    """Send hourly status report to Telegram admin."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        print("[Status] No TELEGRAM_BOT_TOKEN or ADMIN_ID — hourly reports disabled")
        return

    # Wait until the next full hour
    now = datetime.now(TBILISI)
    minutes_to_wait = 60 - now.minute
    seconds_to_wait = minutes_to_wait * 60 - now.second
    if seconds_to_wait > 0:
        await asyncio.sleep(seconds_to_wait)

    while True:
        try:
            now = datetime.now(TBILISI)
            uptime = now - _start_time
            hours = int(uptime.total_seconds() // 3600)
            minutes = int((uptime.total_seconds() % 3600) // 60)

            # Get today's analytics
            try:
                detail = await asyncio.to_thread(get_today_detail)
            except Exception:
                detail = {"total_today": 0, "by_source": {}, "approved": 0, "rejected": 0, "published": 0}

            src_lines = ""
            for src, count in detail["by_source"].items():
                src_lines += f"  · {src}: {count}\n"
            if not src_lines:
                src_lines = "  · —\n"

            report = (
                f"📊 საათობრივი რეპორტი — {now.strftime('%H:%M  %d/%m/%Y')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ სტატუსი: აქტიური\n"
                f"⏱ აქტიურია: {hours}სთ {minutes}წთ\n"
                f"🃏 შექმნილი ქარდები: {len(history)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📰 დღევანდელი აქტივობა: {detail['total_today']}\n"
                f"{src_lines}"
                f"✅ დამტკიცებული: {detail['approved']}\n"
                f"❌ უარყოფილი: {detail['rejected']}\n"
                f"📘 გამოქვეყნებული: {detail['published']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
            )

            # Facebook stats section
            fb_section = ""
            try:
                fb_stats = _fb_page_cache if _fb_page_cache else await asyncio.to_thread(get_page_stats)
                if fb_stats.get("followers"):
                    fb_section = f"📘 Facebook გვერდი:\n"
                    net = fb_stats.get("fan_adds", 0) - fb_stats.get("fan_removes", 0)
                    sign = "+" if net >= 0 else ""
                    fb_section += f"  👥 მიმდევრები: {fb_stats.get('followers', 0):,} ({sign}{net})\n"
                    if fb_stats.get("page_views"):
                        fb_section += f"  👀 გვერდის ნახვები: {fb_stats['page_views']:,}\n"
                    # Find top post
                    top_posts = get_top(1)
                    if top_posts:
                        tp = top_posts[0]
                        likes = int(tp.get('likes', 0) or 0)
                        cmts = int(tp.get('comments', 0) or 0)
                        title = (tp.get('title', '') or '')[:30]
                        fb_section += f"  🏆 ტოპ პოსტი: \"{title}\" (👍{likes} 💬{cmts})\n"
                    fb_section += f"━━━━━━━━━━━━━━━━━━━━━\n"
            except Exception:
                pass

            report += fb_section
            report += (
                f"🤖 აგენტი აქტიურია და მზადყოფნაშია!"
            )

            await asyncio.to_thread(_send_telegram, report)
            print(f"[Status] Hourly report sent at {now.strftime('%H:%M')}")
        except Exception as exc:
            print(f"[Status] Report failed: {exc}")

        await asyncio.sleep(3600)  # wait 1 hour


# ---------------------------------------------------------------------------
# Facebook insights loop — refresh engagement every hour
# ---------------------------------------------------------------------------
async def _fb_insights_loop():
    """Every hour: refresh page stats + growth + views + engagement for recent posts."""
    global _fb_page_cache
    await asyncio.sleep(120)  # wait 2 min on startup
    print("[FB-Insights] Background loop started (every 1h)")

    while True:
        try:
            # 1. Page stats + growth + views
            stats = await asyncio.to_thread(get_page_stats)
            insights = await asyncio.to_thread(get_page_insights)
            growth = await asyncio.to_thread(get_page_growth)
            views = await asyncio.to_thread(get_page_views)
            _fb_page_cache = {**stats, **insights, **growth, **views}
            print(f"[FB-Insights] Page stats: followers={stats.get('followers', 0)}, "
                  f"fan_adds={growth.get('fan_adds', 0)}, views={views.get('page_views', 0)}")

            # 2. Refresh engagement + reach for last 20 published posts
            posts = get_top(20)
            updated = 0
            for post in posts:
                fb_id = post.get("facebook_post_id")
                if not fb_id:
                    continue
                metrics = await asyncio.to_thread(get_post_insights, fb_id)
                reach = await asyncio.to_thread(get_post_reach, fb_id)
                combined = {**metrics, **reach}
                if combined.get("likes", 0) or combined.get("comments", 0) or combined.get("shares", 0):
                    update_activity(post["id"], **combined)
                    updated += 1
            print(f"[FB-Insights] Updated engagement for {updated}/{len(posts)} posts")

        except Exception as exc:
            print(f"[FB-Insights] Loop error: {exc}")

        await asyncio.sleep(3600)  # 1 hour


# ---------------------------------------------------------------------------
# Weekly report — every Monday 10:00 Tbilisi time
# ---------------------------------------------------------------------------
def _build_weekly_report() -> str:
    """Build a comprehensive weekly summary report in Georgian."""
    now = datetime.now(TBILISI)
    week_end = now
    week_start = now - timedelta(days=7)

    summary = get_weekly_summary()

    # Source breakdown
    src_lines = ""
    for src, cnt in summary.get("by_source", {}).items():
        src_lines += f"  · {src}: {cnt}"
    if not src_lines:
        src_lines = "  · —"

    # Top posts
    top_lines = ""
    for i, tp in enumerate(summary.get("top_posts", [])[:3], 1):
        title = (tp.get("title", "") or "")[:35]
        eng = tp.get("engagement", 0)
        likes = tp.get("likes", 0)
        cmts = tp.get("comments", 0)
        shares = tp.get("shares", 0)
        top_lines += f"  {i}. \"{title}\" — 👍{likes} 💬{cmts} 🔄{shares}\n"
    if not top_lines:
        top_lines = "  —\n"

    # Reactions
    rx = summary.get("reactions", {})
    rx_line = (f"  ❤️ {rx.get('love', 0)} · 😂 {rx.get('haha', 0)} · "
               f"😮 {rx.get('wow', 0)} · 😢 {rx.get('sad', 0)} · 😠 {rx.get('angry', 0)}")

    # Source performance
    src_perf_lines = ""
    for src, data in summary.get("source_performance", {}).items():
        avg = data.get("avg_engagement", 0)
        cnt = data.get("count", 0)
        src_perf_lines += f"  · {src}: {cnt} პოსტი, საშ. ჩართ. {avg:.1f}\n"

    # Page stats
    fb = _fb_page_cache or {}
    followers = fb.get("followers", 0)
    fan_adds = fb.get("fan_adds", 0)
    fan_removes = fb.get("fan_removes", 0)
    net_change = fan_adds - fan_removes
    change_sign = "+" if net_change >= 0 else ""

    report = (
        f"📊 კვირის შეჯამება — {week_start.strftime('%d/%m')} – {week_end.strftime('%d/%m/%Y')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 გამოქვეყნებული პოსტები: {summary.get('total_posts', 0)}\n"
        f"{src_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 ჩართულობა:\n"
        f"  👍 ლაიქები: {summary.get('likes', 0)} / 💬 კომენტარები: {summary.get('comments', 0)} / 🔄 გაზიარებები: {summary.get('shares', 0)}\n"
        f"  📈 Engagement Rate: {summary.get('engagement_rate', 0):.1f}%\n"
        f"  📊 საშუალო ჩართულობა: {summary.get('avg_engagement', 0):.1f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💫 რეაქციები:\n"
        f"{rx_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 ტოპ 3 პოსტი:\n"
        f"{top_lines}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📘 Facebook გვერდი:\n"
        f"  👥 მიმდევრები: {followers:,} ({change_sign}{net_change})\n"
        f"  📊 Reach: {summary.get('week_reach', 0):,}\n"
        f"  🎯 საუკეთესო დრო: {summary.get('best_hour', '—')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    if src_perf_lines:
        report += (
            f"📈 წყაროების ეფექტურობა:\n"
            f"{src_perf_lines}"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        )

    report += f"🤖 კვირის რეპორტი — აგენტი აქტიურია!"

    return report


async def _weekly_report_loop():
    """Send weekly summary every Monday at 10:00 Tbilisi time."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        print("[Weekly] No TELEGRAM_BOT_TOKEN or ADMIN_ID — weekly reports disabled")
        return

    print("[Weekly] Weekly report loop started (Monday 10:00 Tbilisi)")

    while True:
        try:
            now = datetime.now(TBILISI)
            # Calculate seconds until next Monday 10:00
            days_until_monday = (7 - now.weekday()) % 7
            if days_until_monday == 0 and (now.hour > 10 or (now.hour == 10 and now.minute > 0)):
                days_until_monday = 7
            next_monday = now.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
            wait_seconds = (next_monday - now).total_seconds()
            print(f"[Weekly] Next report in {wait_seconds / 3600:.1f}h ({next_monday.strftime('%d/%m %H:%M')})")
            await asyncio.sleep(wait_seconds)

            # Build and send report
            report = _build_weekly_report()
            await asyncio.to_thread(_send_telegram, report)
            print(f"[Weekly] Weekly report sent at {datetime.now(TBILISI).strftime('%H:%M %d/%m')}")

        except Exception as exc:
            print(f"[Weekly] Report error: {exc}")
            await asyncio.sleep(3600)  # retry in 1h on error


# ---------------------------------------------------------------------------
# Auto-news loop — scrape interpressnews.ge every 15 minutes
# ---------------------------------------------------------------------------
async def _auto_news_loop():
    """Every 15 minutes: scrape interpressnews.ge, send unseen news to Telegram."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        print("[News] No TELEGRAM_BOT_TOKEN or ADMIN_ID — auto-news disabled")
        return

    # Wait 60s on startup to let Telegram bot initialize first
    await asyncio.sleep(60)
    print(f"[News] Auto-news loop started (every {_news_interval}s)")

    while True:
        try:
            articles = await asyncio.to_thread(_scrape_interpressnews)

            if not articles:
                print(f"[News] No articles found, retrying in {_news_interval}s")
                await asyncio.sleep(_news_interval)
                continue

            # Find first unseen article
            chosen = None
            for art in articles:
                if art["url"] not in _seen_news_urls:
                    chosen = art
                    break

            if not chosen:
                print(f"[News] All articles already seen, retrying in {_news_interval}s")
                await asyncio.sleep(_news_interval)
                continue

            # Mark as seen and store as pending
            _seen_news_urls.add(chosen["url"])
            news_id = uuid.uuid4().hex[:8]
            _pending_news[news_id] = chosen

            # Send to Telegram for approval
            await asyncio.to_thread(_send_news_to_telegram, news_id, chosen)
            print(f"[News] Sent for approval: {chosen['title'][:50]}...")

        except Exception as exc:
            print(f"[News] Loop error: {exc}")

        await asyncio.sleep(_news_interval)


# ---------------------------------------------------------------------------
# RSS checker loop — checks all active feeds on their individual intervals
# ---------------------------------------------------------------------------
async def _rss_checker_loop():
    """Check all active RSS feeds and add new articles to the queue."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        print("[RSS] No TELEGRAM_BOT_TOKEN or ADMIN_ID — RSS checker disabled")
        return

    await asyncio.sleep(90)  # wait for bot to initialize
    print("[RSS] Checker loop started")

    while True:
        try:
            now = _time.time()
            for source in _rss_sources:
                if not source["enabled"]:
                    continue
                interval_sec = source["interval_min"] * 60
                if now - source["last_checked"] < interval_sec:
                    continue

                source["last_checked"] = now
                articles = await asyncio.to_thread(_fetch_rss_feed, source)
                new_count = 0

                for art in articles:
                    if art["url"] in _rss_seen_urls:
                        continue
                    _rss_seen_urls.add(art["url"])

                    # Translate to Georgian via Gemini
                    tr = await asyncio.to_thread(
                        _translate_to_georgian, art["title"], art["description"]
                    )
                    art["title_ka"] = tr["title_ka"]
                    art["desc_ka"] = tr["desc_ka"]

                    _rss_queue.append(art)
                    new_count += 1

                if new_count:
                    print(f"[RSS] {source['name']}: +{new_count} new → queue={len(_rss_queue)}")

        except Exception as exc:
            print(f"[RSS] Checker error: {exc}")

        await asyncio.sleep(60)  # check every 60s which feeds are due


# ---------------------------------------------------------------------------
# RSS queue sender — sends queued articles at min_interval spacing
# ---------------------------------------------------------------------------
async def _rss_queue_sender_loop():
    """Send queued RSS articles to Telegram, respecting min_interval."""
    if not TELEGRAM_TOKEN or not TELEGRAM_ADMIN_ID:
        return

    await asyncio.sleep(120)  # wait for checker to populate
    print("[RSS] Queue sender started")

    while True:
        try:
            if _rss_queue:
                article = _rss_queue.pop(0)
                news_id = uuid.uuid4().hex[:8]
                _pending_news[news_id] = article  # reuse same approval flow

                await asyncio.to_thread(_send_rss_news_to_telegram, news_id, article)
                print(f"[RSS] Sent from queue: {article.get('title_ka', article['title'])[:50]}...")

                # Wait min_interval before sending next
                await asyncio.sleep(_rss_min_interval)
            else:
                await asyncio.sleep(30)  # check queue every 30s

        except Exception as exc:
            print(f"[RSS] Sender error: {exc}")
            await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
