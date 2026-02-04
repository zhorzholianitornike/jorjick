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
import os
import uuid
from datetime import datetime
from pathlib import Path

import requests
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from card_generator import CardGenerator
from facebook import post_photo
from setup_fonts import download as ensure_font

# ---------------------------------------------------------------------------
# Paths & config
# ---------------------------------------------------------------------------
PORT              = int(os.environ.get("PORT", 8000))
TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_ADMIN_ID = os.environ.get("TELEGRAM_ADMIN_ID")   # chat_id to receive FB upload status

UPLOADS = Path("uploads")
CARDS   = Path("cards")
UPLOADS.mkdir(exist_ok=True)
CARDS.mkdir(exist_ok=True)

logo = "logo.png" if os.path.exists("logo.png") else None
generator = CardGenerator(logo_path=logo)

# shared in-memory history (web + telegram write here)
history: list[dict] = []

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI()
app.mount("/cards", StaticFiles(directory=str(CARDS)), name="cards")


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

  /* toast */
  .toast       { position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
                 background:#ef4444; color:#fff; padding:12px 22px; border-radius:8px;
                 font-size:14px; display:none; z-index:99; }

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
  <p class="sub">BBC / CNN style news graphics — web &amp; Telegram</p>

  <div class="stats">
    <div class="stat">
      <div class="lbl">Telegram</div>
      <div class="val green" id="s-bot">● Running</div>
    </div>
    <div class="stat">
      <div class="lbl">Cards generated</div>
      <div class="val" id="s-count">0</div>
    </div>
  </div>

  <!-- generate form -->
  <div class="panel">
    <h2>Generate a card</h2>

    <div class="drop" id="drop">
      <div class="ico">📷</div>
      <p>Click or drag &amp; drop a photo</p>
      <input type="file" id="fi" accept="image/*" style="display:none">
      <img id="prev" alt="">
    </div>

    <div class="row">
      <div class="g"><label>Name</label>
        <input id="inp-name" placeholder="ირაკლი კობახიძე">
      </div>
    </div>
    <div class="row">
      <div class="g"><label>Text</label>
        <textarea id="inp-text" placeholder="ტექსტი …"></textarea>
      </div>
    </div>

    <button class="btn" id="btn-gen" onclick="gen()">Generate Card</button>
    <div class="spin" id="spin"></div>

    <div class="result" id="res">
      <img id="res-img" alt="">
      <br>
      <a class="dl" id="res-dl" href="" download="card.jpg">⬇ Download</a>
    </div>
  </div>

  <!-- history -->
  <div class="history">
    <h2>Recent cards</h2>
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
    const r = new FileReader();
    r.onload = () => { prev.src = r.result; prev.style.display = 'block'; };
    r.readAsDataURL(f);
  }

  // ── generate ──────────────────────────────────────────────────────
  window.gen = async function() {
    const name = document.getElementById('inp-name').value.trim();
    const text = document.getElementById('inp-text').value.trim();
    if (!file || !name || !text) { toast('Photo, name and text are required.'); return; }

    document.getElementById('btn-gen').disabled = true;
    document.getElementById('spin').style.display = 'block';
    document.getElementById('res').style.display  = 'none';

    const fd = new FormData();
    fd.append('photo', file);
    fd.append('name',  name);
    fd.append('text',  text);

    try {
      const r    = await fetch('/api/generate', { method:'POST', body:fd });
      const data = await r.json();
      if (data.card_url) {
        document.getElementById('res-img').src = data.card_url;
        document.getElementById('res-dl').href = data.card_url;
        document.getElementById('res').style.display = 'block';
        loadHistory();
      } else { toast('Error: ' + (data.error || 'unknown')); }
    } catch(e) { toast('Network error: ' + e.message); }

    document.getElementById('btn-gen').disabled = false;
    document.getElementById('spin').style.display = 'none';
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

  // ── toast helper ──────────────────────────────────────────────────
  window.toast = function(msg) {
    const t = document.getElementById('toast');
    t.textContent = msg; t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 3000);
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
    photo: UploadFile = File(...),
    name:  str        = Form(...),
    text:  str        = Form(...),
):
    card_id    = uuid.uuid4().hex[:8]
    photo_path = UPLOADS / f"{card_id}.jpg"
    card_path  = CARDS   / f"{card_id}_card.jpg"

    # save upload
    photo_path.write_bytes(await photo.read())

    try:
        generator.generate(str(photo_path), name, text, str(card_path))
    except Exception as exc:
        photo_path.unlink(missing_ok=True)
        return JSONResponse(status_code=500, content={"error": str(exc)})

    photo_path.unlink(missing_ok=True)          # source no longer needed

    # upload to Facebook + notify via Telegram in background
    asyncio.create_task(asyncio.to_thread(_upload_and_notify, str(card_path), name))

    _add_history(name, f"/cards/{card_id}_card.jpg")
    return {"card_url": f"/cards/{card_id}_card.jpg"}


@app.get("/api/history")
async def api_history():
    return history


@app.get("/api/status")
async def api_status():
    return {"telegram": "running" if TELEGRAM_TOKEN else "disabled",
            "cards": len(history)}


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


def _upload_and_notify(card_path: str, name: str):
    """Upload to Facebook, then notify via Telegram. Meant to run in a thread."""
    success = post_photo(card_path, name)
    if success:
        _send_telegram(f"Facebook upload done\nName: {name}")
    else:
        _send_telegram(f"Facebook upload FAILED\nName: {name}")


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
