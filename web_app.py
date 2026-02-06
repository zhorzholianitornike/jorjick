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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import requests
import uvicorn
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
            # Clone repository
            print("[Startup] Cloning repository...")
            subprocess.run(
                ["git", "clone", repo_url, "."],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                timeout=30
            )
            print("[Startup] ✓ Repository cloned")
        else:
            # Pull latest changes
            print("[Startup] Pulling latest changes...")
            subprocess.run(
                ["git", "config", "--local", "user.name", "Railway Bot"],
                cwd=repo_dir,
                capture_output=True,
                timeout=5
            )
            subprocess.run(
                ["git", "config", "--local", "user.email", "bot@railway.app"],
                cwd=repo_dir,
                capture_output=True,
                timeout=5
            )
            subprocess.run(
                ["git", "pull", "origin", "main"],
                cwd=repo_dir,
                check=True,
                capture_output=True,
                timeout=20
            )
            print("[Startup] ✓ Repository updated")

        # Ensure photos directory exists
        PHOTOS.mkdir(exist_ok=True)
        print(f"[Startup] ✓ Photos directory ready")

    except subprocess.CalledProcessError as e:
        print(f"[Startup] ✗ Git operation failed: {e.stderr if hasattr(e, 'stderr') else e}")
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
  <h1>News Card Bot</h1>
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
    <h2>2 — ავტომატური ქარდი <span style="font-size:11px;color:#64748b;font-weight:400" id="ai-badge">[Tavily + OpenAI Thinking]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">Tavily Search → OpenAI o3-mini (Thinking) → Card → Facebook</p>
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

  <!-- history -->
  <div class="history">
    <h2>Recent Cards</h2>
    <div class="hgrid" id="hgrid"></div>
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

            # 2. AI picks the best story  (OpenAI Thinking → Gemini → Claude/Kimi)
            card_info = None

            # Try OpenAI Thinking first (best copywriting)
            if os.environ.get("OPENAI_API_KEY"):
                yield _e({"t": "log", "m": "OpenAI o3-mini thinking..."})
                card_info = await asyncio.to_thread(_pick_openai_thinking, tavily_res)
                if "error" in card_info:
                    yield _e({"t": "log", "m": f"OpenAI: {card_info['error'][:60]} — fallback Gemini..."})
                    card_info = None

            # Fallback: Gemini
            if card_info is None:
                yield _e({"t": "log", "m": "Gemini picking story..."})
                card_info = await asyncio.to_thread(_pick_gemini, tavily_res)
                if "error" in card_info:
                    # Gemini failed → try Claude / Kimi
                    yield _e({"t": "log", "m": "Gemini: " + ("429 — " if "429" in card_info["error"] else "") + "fallback Claude/Kimi..."})
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
        # Configure git credentials if on Railway
        if os.environ.get("RAILWAY_ENVIRONMENT"):
            github_token = os.environ.get("GITHUB_TOKEN")
            if github_token:
                subprocess.run(
                    ["git", "config", "--local", "credential.helper", "store"],
                    capture_output=True,
                    cwd=repo_dir,
                    timeout=2
                )
                # Setup credentials
                subprocess.run(
                    ["git", "config", "--local", "user.name", "Railway Bot"],
                    capture_output=True,
                    cwd=repo_dir,
                    timeout=2
                )
                subprocess.run(
                    ["git", "config", "--local", "user.email", "bot@railway.app"],
                    capture_output=True,
                    cwd=repo_dir,
                    timeout=2
                )

        # Add the specific file
        subprocess.run(["git", "add", file_path], check=True, capture_output=True, cwd=repo_dir, timeout=5)
        # Commit with message
        subprocess.run(
            ["git", "commit", "-m", commit_message],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo_dir,
            timeout=5
        )
        # Push to remote (credentials already configured)
        push_result = subprocess.run(
            ["git", "push"],
            check=True,
            capture_output=True,
            text=True,
            cwd=repo_dir,
            timeout=15
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

    prompt = (
        "შენ ხარ CNN/BBC-ს დონის ქართველი ჟურნალისტი და კოპირაიტერი.\n"
        "ამოცანა: აირჩიე ყველაზე აქტუალური კონკრეტული ამბავი და დაწერე სრულფასოვანი სტატია.\n\n"
        "## name (სათაური):\n"
        "- 3-5 სიტყვა, კონკრეტული და ყურადღების წამკიდე\n"
        "- მაგ: 'OpenAI-მ GPT-5 წარადგინა', 'NASA-მ მარსზე წყალი აღმოაჩინა'\n\n"
        "## text (სტატია):\n"
        "- სრულფასოვანი სტატია, 150-250 სიტყვა\n"
        "- პირველ აბზაცში: ვინ, რა, სად, როდის (მთავარი ფაქტი)\n"
        "- მეორე აბზაცში: დეტალები, კონტექსტი, ექსპერტების მოსაზრებები\n"
        "- მესამე აბზაცში: რას ნიშნავს ეს მომავლისთვის, შედეგები\n"
        "- გამოიყენე პროფესიონალური ჟურნალისტური ენა\n"
        "- მოქმედებითი ზმნები: 'გამოაცხადა', 'წარადგინა', 'აიკრძალა'\n"
        "- არ გამოიყენო ენციკლოპედიური ენა\n\n"
        "## image_url — აირჩიე რეალური ფოტო (არა ილუსტრაცია)\n\n"
        "სტატიები:\n" + "\n".join(lines) + "\n\n"
        "ფოტოების URL-ები:\n" + "\n".join(images[:10] or ["none"]) + "\n\n"
        "უპასუხე მხოლოდ JSON-ით:\n"
        '{"name":"სათაური","text":"სრული სტატია აქ...","image_url":"URL ან null"}'
    )

    try:
        resp = client.chat.completions.create(
            model="o3-mini",
            max_completion_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content or ""

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
            model="gemini-2.0-flash",
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
# Telegram bot  (background asyncio task)
# ---------------------------------------------------------------------------
async def _run_telegram():
    if not TELEGRAM_TOKEN:
        print("[!] TELEGRAM_BOT_TOKEN not set — Telegram bot skipped")
        return

    from telegram import Update
    from telegram.ext import (
        Application, CommandHandler, ConversationHandler,
        MessageHandler, filters,
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

    tg = Application.builder().token(TELEGRAM_TOKEN).build()
    tg.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", tg_start)],
        states={
            S_PHOTO: [MessageHandler(filters.PHOTO,                     tg_photo)],
            S_TEXT:  [MessageHandler(filters.TEXT & ~filters.COMMAND,    tg_text)],
        },
        fallbacks=[CommandHandler("cancel", tg_cancel)],
    ))

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


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
