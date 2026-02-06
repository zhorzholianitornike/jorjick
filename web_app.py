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

from card_generator import CardGenerator
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
    <h2>Create Card</h2>

    <div class="drop" id="drop">
      <div class="ico">📷</div>
      <p>Upload Photo</p>
      <input type="file" id="fi" accept="image/*" style="display:none">
      <img id="prev" alt="">
    </div>

    <div class="row">
      <div class="g"><label>Name</label>
        <input id="inp-name" placeholder="John Doe">
      </div>
    </div>
    <div class="row">
      <div class="g"><label>Text</label>
        <textarea id="inp-text" placeholder="Enter text..."></textarea>
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

  <!-- auto-generate panel -->
  <div class="panel">
    <h2>Auto Card <span style="font-size:11px;color:#64748b;font-weight:400">[Tavily + Gemini]</span></h2>
    <p style="color:#64748b;font-size:12px;margin-bottom:14px">Tavily Search → Gemini AI → Card → Facebook</p>
    <div class="row">
      <div class="g"><label>Topic</label>
        <input id="inp-theme" placeholder="AI news, politics, sports...">
      </div>
    </div>
    <button class="btn" id="btn-auto" onclick="autoGen()">Generate</button>
    <div class="spin" id="spin-auto"></div>
    <div class="result" id="res-auto">
      <img id="res-auto-img" alt="">
      <br>
      <a class="dl" id="res-auto-dl" href="" download="auto_card.jpg">⬇ Download</a>
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
  function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

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
    if (!file || !name || !text) { toast('Photo, name and text required!'); return; }

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
              resEl.style.display = 'block';
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
    if (d.gemini_key === false) miss.push('GEMINI_API_KEY');
    if (miss.length) {
      document.getElementById('auto-log').innerHTML =
        '<span style="color:#f59e0b">⚠ Railway env vars missing: ' + miss.join(', ') +
        ' — Auto card disabled</span>';
    }
  });

  // ── toast helper ──────────────────────────────────────────────────
  window.toast = function(msg) {
    const t = document.getElementById('toast');
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
            "cards":    len(history),
            "ai_backend": os.environ.get("BACKEND", "claude").upper(),
            "tavily_key": bool(os.environ.get("TAVILY_API_KEY")),
            "gemini_key": bool(os.environ.get("GEMINI_API_KEY"))}


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

            # 2. AI picks the best story  (Gemini first, Claude/Kimi fallback)
            yield _e({"t": "log", "m": "Gemini picking story..."})
            card_info = await asyncio.to_thread(_pick_gemini, tavily_res)
            if "error" in card_info:
                # Gemini failed (429 quota, key missing, …) → try Claude / Kimi
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

            # 3. Generate complete news card with Gemini Imagen
            card_path = CARDS / f"{card_id}_auto.jpg"
            card_prompt = (
                f"Professional BBC/CNN style news card image. "
                f"Dark gradient background. "
                f"Headline: {name}. "
                f"Subtext: {text}. "
                f"Modern news graphics design. Red accent color. "
                f"1080x1350 portrait format. High quality."
            )
            yield _e({"t": "log", "m": "Gemini generating card..."})
            gen_path = await asyncio.to_thread(
                _generate_image_gemini, card_prompt, str(card_path)
            )

            # Fallback: if Gemini fails, download image and use template
            if not gen_path:
                yield _e({"t": "log", "m": "Gemini failed, using template..."})
                photo_path = None
                if image_url:
                    photo_path = await asyncio.to_thread(
                        download_image, image_url, f"temp/auto_{card_id}.jpg"
                    )
                if not photo_path:
                    photo_path = await asyncio.to_thread(create_placeholder)
                    yield _e({"t": "log", "m": "Using placeholder image"})

                yield _e({"t": "log", "m": "Generating card..."})
                await asyncio.to_thread(
                    generator.generate, photo_path, name, text, str(card_path)
                )

            # 4. Facebook upload in background
            asyncio.create_task(asyncio.to_thread(_upload_and_notify, str(card_path), name))
            card_url = f"/cards/{card_id}_auto.jpg"
            _add_history(name, card_url)
            yield _e({"t": "log", "m": "Uploading to Facebook..."})
            yield _e({"t": "done", "card_url": card_url, "name": name})

        except Exception as exc:
            yield _e({"t": "err", "m": str(exc)})

    return StreamingResponse(
        _stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


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
    now     = datetime.now(TBILISI).strftime("%H:%M  %d/%m/%Y")
    success = post_photo(card_path, name)
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
        "You are given news search results. Pick the MOST interesting story and extract:\n"
        "- name: person name or short topic headline (max 40 chars)\n"
        "- text: 1-2 sentence summary (max 120 chars)\n"
        "- image_url: a URL from the results that likely contains an image, or null\n\n"
        "Results:\n" + json.dumps(results, ensure_ascii=False) + "\n\n"
        "Reply ONLY with valid JSON:\n"
        '{"name":"…","text":"…","image_url":"… or null"}'
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
        "You are a news editor. Pick the MOST interesting story from these results.\n"
        "Write the summary IN GEORGIAN (ქართული ენა).\n"
        "Reply ONLY with valid JSON, no other text:\n"
        '{"name":"headline 3-4 words","text":"summary in Georgian 30-40 words","image_url":"best image URL or null"}\n\n'
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
