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
from facebook import post_photo
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
  .flow-canvas { position:relative; min-height:700px; padding:40px; min-width:1100px; }

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
</style>
</head>
<body>
<div class="wrap">
  <h1>News Card Bot <button class="flow-btn" onclick="toggleFlow()">⚡ FLOW</button></h1>
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
      <div class="fnode fnode-blue" style="left:40px;top:170px" id="fn-dash2">
        <div class="fnode-head">INPUT</div>
        <div class="fnode-body"><div class="fnode-icon">🖥️</div><div class="fnode-name">Theme Input</div><div class="fnode-desc">თემა / საძიებო</div></div>
      </div>
      <div class="fnode fnode-green" style="left:240px;top:170px" id="fn-tavily">
        <div class="fnode-head">SEARCH</div>
        <div class="fnode-body"><div class="fnode-icon">🔍</div><div class="fnode-name">Tavily Search</div><div class="fnode-desc">ნიუსების ძიება</div></div>
      </div>
      <div class="fnode fnode-green" style="left:440px;top:170px" id="fn-gemini">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🤖</div><div class="fnode-name">Gemini Flash</div><div class="fnode-desc">სტატია + სათაური</div></div>
      </div>
      <div class="fnode fnode-green" style="left:640px;top:170px" id="fn-imagen">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🎨</div><div class="fnode-name">Imagen 3</div><div class="fnode-desc">ფოტო გენერაცია</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:840px;top:170px" id="fn-card2">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">📰</div><div class="fnode-name">Auto Card</div><div class="fnode-desc">ქარდი + სტატია</div></div>
      </div>

      <!-- ROW 3: Voice TTS -->
      <div class="fnode fnode-blue" style="left:40px;top:310px" id="fn-dash3">
        <div class="fnode-head">INPUT</div>
        <div class="fnode-body"><div class="fnode-icon">📝</div><div class="fnode-name">Text Input</div><div class="fnode-desc">ქართული ტექსტი</div></div>
      </div>
      <div class="fnode fnode-green" style="left:300px;top:310px" id="fn-tts">
        <div class="fnode-head">AI</div>
        <div class="fnode-body"><div class="fnode-icon">🎙️</div><div class="fnode-name">Gemini TTS</div><div class="fnode-desc">Charon voice</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:560px;top:310px" id="fn-wav">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">🔊</div><div class="fnode-name">WAV Audio</div><div class="fnode-desc">24kHz mono</div></div>
      </div>

      <!-- ROW 4: Telegram -->
      <div class="fnode fnode-purple" style="left:40px;top:450px" id="fn-tg">
        <div class="fnode-head">TELEGRAM</div>
        <div class="fnode-body"><div class="fnode-icon">💬</div><div class="fnode-name">Telegram Bot</div><div class="fnode-desc">/start, /voice</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:260px;top:450px" id="fn-tgstart">
        <div class="fnode-head">COMMAND</div>
        <div class="fnode-body"><div class="fnode-icon">📸</div><div class="fnode-name">/start</div><div class="fnode-desc">ფოტო → ქარდი</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:480px;top:450px" id="fn-tgvoice">
        <div class="fnode-head">COMMAND</div>
        <div class="fnode-body"><div class="fnode-icon">🎙️</div><div class="fnode-name">/voice</div><div class="fnode-desc">ტექსტი → აუდიო</div></div>
      </div>
      <div class="fnode fnode-orange" style="left:700px;top:450px" id="fn-tgout">
        <div class="fnode-head">OUTPUT</div>
        <div class="fnode-body"><div class="fnode-icon">📤</div><div class="fnode-name">TG Response</div><div class="fnode-desc">ქარდი / ხმა</div></div>
      </div>

      <!-- ROW 5: Scheduler + GitHub -->
      <div class="fnode fnode-cyan" style="left:40px;top:590px" id="fn-timer">
        <div class="fnode-head">SCHEDULER</div>
        <div class="fnode-body"><div class="fnode-icon">⏰</div><div class="fnode-name">Hourly Timer</div><div class="fnode-desc">ყოველ საათში</div></div>
      </div>
      <div class="fnode fnode-cyan" style="left:260px;top:590px" id="fn-report">
        <div class="fnode-head">ACTION</div>
        <div class="fnode-body"><div class="fnode-icon">📊</div><div class="fnode-name">Status Report</div><div class="fnode-desc">სტატუსი + uptime</div></div>
      </div>
      <div class="fnode fnode-purple" style="left:480px;top:590px" id="fn-tgadmin">
        <div class="fnode-head">TELEGRAM</div>
        <div class="fnode-body"><div class="fnode-icon">👤</div><div class="fnode-name">Admin Chat</div><div class="fnode-desc">შეტყობინება</div></div>
      </div>

      <div class="fnode fnode-cyan" style="left:700px;top:590px" id="fn-github">
        <div class="fnode-head">STORAGE</div>
        <div class="fnode-body"><div class="fnode-icon">🐙</div><div class="fnode-name">GitHub</div><div class="fnode-desc">photos/ sync</div></div>
      </div>
      <div class="fnode fnode-blue" style="left:920px;top:590px" id="fn-photos">
        <div class="fnode-head">LIBRARY</div>
        <div class="fnode-body"><div class="fnode-icon">📁</div><div class="fnode-name">Photo Library</div><div class="fnode-desc">ატვირთვა/წაშლა</div></div>
      </div>
    </div>
  </div>
  <div class="flow-legend">
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#60a5fa"></div> Input / Dashboard</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#4ade80"></div> AI / Process</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#fb923c"></div> Output</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#c084fc"></div> Telegram</div>
    <div class="flow-leg-item"><div class="flow-leg-dot" style="background:#22d3ee"></div> System / Storage</div>
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
      // Row 4: Telegram
      ['fn-tg','fn-tgstart','active'],
      ['fn-tg','fn-tgvoice','active'],
      ['fn-tgstart','fn-tgout',''],
      ['fn-tgvoice','fn-tgout',''],
      // Row 5: Scheduler
      ['fn-timer','fn-report','active'],
      ['fn-report','fn-tgadmin','active'],
      // GitHub sync
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
    return {"card_url": f"/cards/{card_id}_card.jpg"}


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
        await asyncio.to_thread(_upload_and_notify, str(card_path), name, fb_caption)
        return {"success": True}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)})


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
# interpressnews.ge scraper + auto-news state
# ---------------------------------------------------------------------------
_pending_news: dict = {}       # {news_id: {title, url, image_url, time}}
_seen_news_urls: set = set()   # already sent/processed URLs


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
        return f"📰 {title}\n\n{article_text[:300]}\n\n🔗 {url}"

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
            "- არ მოიგონო ფაქტები, მხოლოდ ტექსტში არსებული ინფორმაცია გამოიყენე\n\n"
            f"სათაური: {title}\n\n"
            f"სტატიის ტექსტი:\n{article_text[:1500]}\n\n"
            "დაწერე მხოლოდ Facebook პოსტის ტექსტი, სხვა არაფერი:"
        )

        resp = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        caption = resp.text.strip()

        # Append source link
        caption += f"\n\n🔗 წყარო: {url}"
        return caption

    except Exception as exc:
        print(f"[Caption] Gemini failed: {exc}")
        return f"📰 {title}\n\n{article_text[:300]}\n\n🔗 წყარო: {url}"


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

                    # Scrape full article text for better caption
                    article_text = await asyncio.to_thread(
                        _scrape_article_text, art["url"]
                    )

                    # Generate detailed Facebook caption with hashtags via Gemini
                    caption = await asyncio.to_thread(
                        _generate_fb_caption, art["title"], article_text, art["url"]
                    )

                    # Upload to Facebook
                    success = await asyncio.to_thread(post_photo, card_path, caption)

                    _add_history(art["title"], f"/cards/{card_id}_news.jpg")

                    if success:
                        _send_telegram(
                            f"✅ Facebook-ზე ატვირთულია!\n\n"
                            f"📰 {art['title']}"
                        )
                    else:
                        _send_telegram(
                            f"⚠️ Facebook ატვირთვა ვერ მოხერხდა\n\n"
                            f"📰 {art['title']}"
                        )

                except Exception as exc:
                    print(f"[News] Process failed: {exc}")
                    _send_telegram(f"❌ შეცდომა: {exc}")

            asyncio.create_task(_process_approved_news(article))

        elif action == "reject":
            _seen_news_urls.add(article["url"])
            await _edit_msg(
                f"❌ გამოტოვებულია\n\n"
                f"<s>{article['title']}</s>"
            )

    tg = Application.builder().token(TELEGRAM_TOKEN).build()
    tg.add_handler(CallbackQueryHandler(tg_news_callback, pattern=r"^news_"))
    tg.add_handler(CommandHandler("voice", tg_voice))
    tg.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", tg_start)],
        states={
            S_PHOTO: [MessageHandler(filters.PHOTO,                     tg_photo)],
            S_TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND,    tg_text)],
        },
        fallbacks=[CommandHandler("cancel", tg_cancel)],
    ))

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

            report = (
                f"📊 საათობრივი რეპორტი — {now.strftime('%H:%M  %d/%m/%Y')}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ სტატუსი: აქტიური\n"
                f"⏱ აქტიურია: {hours}სთ {minutes}წთ\n"
                f"🃏 შექმნილი ქარდები: {len(history)}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 რუსთავი 2-ის აგენტი აქტიურია და მზადყოფნაშია!"
            )

            await asyncio.to_thread(_send_telegram, report)
            print(f"[Status] Hourly report sent at {now.strftime('%H:%M')}")
        except Exception as exc:
            print(f"[Status] Report failed: {exc}")

        await asyncio.sleep(3600)  # wait 1 hour


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
    print("[News] Auto-news loop started (every 15 min)")

    while True:
        try:
            articles = await asyncio.to_thread(_scrape_interpressnews)

            if not articles:
                print("[News] No articles found, retrying in 15 min")
                await asyncio.sleep(900)
                continue

            # Find first unseen article
            chosen = None
            for art in articles:
                if art["url"] not in _seen_news_urls:
                    chosen = art
                    break

            if not chosen:
                print("[News] All articles already seen, retrying in 15 min")
                await asyncio.sleep(900)
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

        await asyncio.sleep(900)  # 15 minutes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
