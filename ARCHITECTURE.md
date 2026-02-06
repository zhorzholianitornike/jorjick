# 🏗️ News Card Bot - არქიტექტურა

> **სრული სისტემის არქიტექტურის დოკუმენტაცია**
> პროექტი: News Card Generator Bot (jorjick)
> Railway Deployment: https://web-production-a33ea.up.railway.app

---

## 📋 სარჩევი

1. [სისტემის მიმოხილვა](#სისტემის-მიმოხილვა)
2. [ძირითადი კომპონენტები](#ძირითადი-კომპონენტები)
3. [არქიტექტურული სქემა](#არქიტექტურული-სქემა)
4. [ფაილების სტრუქტურა](#ფაილების-სტრუქტურა)
5. [API Endpoints](#api-endpoints)
6. [Environment Variables](#environment-variables)
7. [დეპლოიმენტი](#დეპლოიმენტი)
8. [Data Flow](#data-flow)

---

## 🎯 სისტემის მიმოხილვა

**News Card Bot** არის მულტიფუნქციური სისტემა სიახლეების ბარათების ავტომატური გენერაციისთვის.

### მთავარი ფუნქციები:

1. **🌐 Web Dashboard** - ბრაუზერული ინტერფეისი (FastAPI)
2. **💬 Telegram Bot** - მობილური ინტერფეისი
3. **🤖 AI Agent** - ავტომატური კონტენტის გენერაცია (Claude/Kimi/Gemini)
4. **🎨 Card Generator** - HTML/CSS → PNG რენდერინგი (Playwright)
5. **📱 Facebook Integration** - ავტომატური პოსტინგი

### ტექნოლოგიური Stack:

- **Backend:** Python 3.11, FastAPI, Uvicorn
- **AI Models:** Claude Sonnet 4.5, Kimi K2, Gemini 2.0
- **Telegram:** python-telegram-bot 20.0+
- **Rendering:** Playwright (headless browser)
- **Search:** DuckDuckGo (DDGS), Tavily API
- **Storage:** File-based (photos/, cards/, uploads/)
- **Deployment:** Railway (Dockerfile + Procfile)

---

## 🧩 ძირითადი კომპონენტები

### 1. **web_app.py** - მთავარი სერვისი ⭐

**როლი:** FastAPI აპლიკაცია + Telegram bot orchestrator

**პასუხისმგებლობები:**
- ✅ FastAPI web server (PORT 8000/8080)
- ✅ Static files serving (/cards, /photos)
- ✅ REST API endpoints
- ✅ Telegram bot-ის ასინქრონული გაშვება startup-ზე
- ✅ GitHub photos sync (Railway startup)
- ✅ In-memory history management

**მთავარი Endpoints:**
```python
GET  /              → Dashboard UI (HTML)
POST /api/generate  → Manual card generation
POST /api/generate-auto → AI-powered auto generation
GET  /api/history   → Recent cards list
GET  /api/status    → Bot status + stats
GET  /api/library   → Photo library
POST /api/upload-photo → Photo upload
```

**Startup Logic:**
1. Railway-ზე startup-ის დროს ავტომატურად აკეთებს `git pull`-ს
2. სინქრონიზებს `photos/` საქაღალდეს GitHub-დან
3. იწყებს Telegram bot-ს background task-ად

---

### 2. **telegram_bot.py** - Telegram ინტერფეისი 💬

**როლი:** Conversation-based bot სიახლის ბარათების შესაქმნელად

**Flow:**
```
user → /start
bot  → "Send a photo"
user → [photo]
bot  → "Now send name + text"
user → ირაკლი კობახიძე
       "ტექსტი ..."
bot  → [generated card.jpg]
```

**States:**
- `PHOTO = 0` - ელოდება ფოტოს
- `TEXT = 1`  - ელოდება სახელს + ტექსტს

**გამოყენება:**
- ConversationHandler (python-telegram-bot)
- temp/ საქაღალდე დროებითი ფაილებისთვის
- CardGenerator-ის გამოძახება

---

### 3. **card_generator.py** - ბარათების რენდერერი 🎨

**როლი:** HTML/CSS template → PNG screenshot

**დიზაინის მახასიათებლები:**
- 📐 ზომა: 1080×1350 px (Instagram/Facebook optimized)
- 🎨 Dark gradient overlay (80% from bottom)
- 🔺 Geometric diagonal triangle shape
- 🟥 Red branding bar at bottom
- 🔤 ქართული ფონტი: Helvetica Georgian / Noto Sans Georgian

**Rendering Process:**
```python
1. HTML template-ის შექმნა
2. ფოტოს base64 encoding
3. ფონტის embedding
4. Playwright headless browser გაშვება
5. Screenshot (PNG)
6. JPEG conversion + compression
```

**მეთოდები:**
```python
generate(photo_path, name, text, output_path)
generate_from_url(photo_url, name, text, output_path)
```

---

### 4. **agent.py** - AI Agent სისტემა 🤖

**როლი:** Multi-backend AI agent with tool calling

**მხარდაჭერილი Backends:**
- **claude** → Anthropic Claude Sonnet 4.5 (Extended Thinking)
- **kimi** → Moonshot Kimi K2 (OpenAI-compatible)
- **gemini** → Google Gemini 2.0 Flash

**ხელმისაწვდომი Tools:**
```python
1. search_web      → DuckDuckGo internet search
2. download_image  → image download from URL
3. generate_card   → render 1080×1350 news card
```

**Agent Flow:**
```
user request → agent thinks → tool calls → results → final answer
                     ↓
                search_web("news topic")
                     ↓
                download_image(url)
                     ↓
                generate_card(photo, name, text)
                     ↓
                return card_path
```

**Safety:**
- `MAX_TOOL_ROUNDS = 10` - infinite loop prevention
- Tool result validation
- Error handling & fallbacks

---

### 5. **search.py** - Search & Image Tools 🔍

**Functions:**

**a) search_web(query, max_results=5)**
- DuckDuckGo text search
- არ სჭირდება API key
- Returns: `[{title, snippet, url}, ...]`

**b) download_image(url, dest)**
- Downloads image from URL
- User-Agent spoofing
- Content-type validation
- Returns local path or None

**c) create_placeholder(dest)**
- Generates 1080×1350 dark gradient
- Used when no photo available
- PIL-based generation

**d) search_tavily(query, max_results)**
- Tavily search API
- Includes images
- Requires TAVILY_API_KEY

---

### 6. **facebook.py** - Facebook გამოქვეყნება 📱

**როლი:** Facebook Page-ზე ფოტოს ატვირთვა

**API:** Facebook Graph API v18.0

**Configuration:**
- `FB_PAGE_ID` - Page-ის ID
- `FB_PAGE_TOKEN` - Long-lived Page Access Token

**Function:**
```python
post_photo(image_path, caption="") → bool
```

**Process:**
1. POST to `/v18.0/{PAGE_ID}/photos`
2. Multipart form data
3. Returns post ID on success

---

## 📊 არქიტექტურული სქემა

```
┌─────────────────────────────────────────────────────────┐
│                    Railway Deployment                    │
│                 (Port: 8080, Auto-scaling)               │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
   ┌────▼────┐              ┌─────▼─────┐
   │ Web UI  │              │ Telegram  │
   │ FastAPI │              │    Bot    │
   └────┬────┘              └─────┬─────┘
        │                         │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │   Card Generator        │
        │  (HTML/CSS → PNG)       │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │   AI Agent (optional)   │
        │ Claude/Kimi/Gemini      │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │  External Services      │
        ├─────────────────────────┤
        │ • DuckDuckGo Search     │
        │ • Tavily API            │
        │ • Facebook Graph API    │
        │ • GitHub (photos sync)  │
        └─────────────────────────┘
```

---

## 📁 ფაილების სტრუქტურა

```
jorjick/
├── 🐍 web_app.py               # FastAPI main server
├── 🐍 telegram_bot.py          # Telegram bot (standalone + embedded)
├── 🐍 agent.py                 # AI agent (Claude/Kimi/Gemini)
├── 🐍 card_generator.py        # HTML → PNG renderer
├── 🐍 search.py                # Search & download tools
├── 🐍 facebook.py              # FB Graph API integration
├── 🐍 setup_fonts.py           # Font downloader
├── 🐍 screenshot_worker.py     # Playwright worker (v1)
├── 🐍 screenshot_worker_2.py   # Playwright worker (v2)
├── 🐍 test_upload.py           # FB upload testing
│
├── 📁 fonts/                   # ქართული ფონტები
│   ├── HELVETICANEUELTGEO-55ROMAN.otf
│   └── NotoSansGeorgian.ttf
│
├── 📁 photos/                  # Photo library (synced from GitHub)
│   └── [person_name].jpg
│
├── 📁 skills/                  # Additional modules
│   ├── card-generate/
│   ├── deploy/
│   └── restore-v2/
│
├── 📁 uploads/                 # User uploads (temporary)
├── 📁 cards/                   # Generated cards (persistent)
├── 📁 temp/                    # Temporary files
│
├── 🐳 Dockerfile               # Container configuration
├── 📄 Procfile                 # Railway startup: web_app.py
├── 📄 requirements.txt         # Python dependencies
├── 📄 runtime.txt              # Python 3.11
└── 📄 .gitignore               # Git exclusions
```

---

## 🌐 API Endpoints

### Dashboard

```http
GET /
Content-Type: text/html
```
Returns: Full web dashboard UI

---

### Manual Card Generation

```http
POST /api/generate
Content-Type: multipart/form-data

Form data:
  - photo: File (image/jpeg, image/png)
  - name: string (person name)
  - text: string (quote text)

Response:
{
  "card_url": "/cards/abc123.jpg",
  "timestamp": "2026-02-06T19:00:00+04:00"
}
```

---

### AI Auto-Generation

```http
POST /api/generate-auto
Content-Type: application/json

Body:
{
  "topic": "საქართველოს პოლიტიკა"
}

Response: StreamingResponse (SSE)
data: {"status": "thinking", "message": "..."}
data: {"status": "searching", "query": "..."}
data: {"status": "complete", "card_url": "/cards/xyz.jpg", "article": "..."}
```

---

### History

```http
GET /api/history

Response:
[
  {
    "id": "abc123",
    "name": "ირაკლი კობახიძე",
    "text": "ციტატა...",
    "card_url": "/cards/abc123.jpg",
    "timestamp": "2026-02-06T19:00:00+04:00"
  }
]
```

---

### Status

```http
GET /api/status

Response:
{
  "bot_running": true,
  "total_cards": 42,
  "library_photos": 15
}
```

---

### Photo Library

```http
GET /api/library

Response:
[
  {
    "filename": "irakli_kobakhidze.jpg",
    "url": "/photos/irakli_kobakhidze.jpg"
  }
]
```

---

### Upload Photo

```http
POST /api/upload-photo
Content-Type: multipart/form-data

Form data:
  - photo: File
  - filename: string (optional)

Response:
{
  "url": "/photos/uploaded_photo.jpg",
  "filename": "uploaded_photo.jpg"
}
```

---

## 🔐 Environment Variables

### Required (Railway Variables)

```bash
# Railway auto-assigns
PORT=8080

# Telegram Bot
TELEGRAM_BOT_TOKEN="123456789:ABC-DEF..."
TELEGRAM_ADMIN_ID="123456789"  # Your chat_id

# GitHub (for photos sync)
GITHUB_TOKEN="ghp_xxxxxxxxxxxx"

# Railway detection
RAILWAY_ENVIRONMENT="production"
```

---

### Optional (AI Agent)

```bash
# AI Backend Selection
BACKEND="claude"  # claude | kimi | gemini

# API Keys
ANTHROPIC_API_KEY="sk-ant-..."    # for Claude
MOONSHOT_API_KEY="sk-..."         # for Kimi
GEMINI_API_KEY="..."              # for Gemini

# Search
TAVILY_API_KEY="tvly-..."         # optional, better search
```

---

### Optional (Facebook)

```bash
# Facebook Page Publishing
FB_PAGE_ID="123456789012345"
FB_PAGE_TOKEN="EAAG..."  # Long-lived Page Access Token
```

---

## 🚀 დეპლოიმენტი

### Railway Setup

1. **Connect GitHub Repository:**
   - Repository: `zhorzholianitornike/jorjick`
   - Branch: `main`

2. **Project Configuration:**
   - Project: `incredible-heart`
   - Service: `web`
   - Domain: `web-production-a33ea.up.railway.app`

3. **Build:**
   - Builder: Dockerfile
   - Start Command: `python3 web_app.py` (from Procfile)

4. **Environment Variables:**
   - Set all required variables in Railway dashboard

---

### Local Development

```bash
# 1. Clone repository
git clone https://github.com/zhorzholianitornike/jorjick.git
cd jorjick

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browsers
playwright install chromium

# 4. Set environment variables
export TELEGRAM_BOT_TOKEN="..."
export PORT=8000

# 5. Run
python3 web_app.py
```

---

### Railway CLI Deploy

```bash
# Link to project
railway link --project incredible-heart --service web

# Deploy
railway up --detach

# Check logs
railway logs

# Check status
railway status
```

---

## 🔄 Data Flow

### Manual Card Creation (Web UI)

```
User uploads photo + enters name/text
             ↓
POST /api/generate (multipart)
             ↓
CardGenerator.generate()
             ↓
HTML template with embedded photo
             ↓
Playwright screenshot → PNG
             ↓
Save to cards/[uuid].jpg
             ↓
Add to history[]
             ↓
Return {card_url, timestamp}
             ↓
User sees card + download/FB buttons
```

---

### AI Auto-Generation

```
User enters topic
             ↓
POST /api/generate-auto {topic}
             ↓
Agent initialized (Claude/Kimi/Gemini)
             ↓
Agent calls search_web(topic)
             ↓
Agent extracts person + quote + photo URL
             ↓
Agent calls download_image(url)
             ↓
Agent calls generate_card(photo, name, text)
             ↓
StreamingResponse sends progress updates
             ↓
Final card returned
             ↓
User sees card + article text
```

---

### Telegram Bot Flow

```
User → /start
             ↓
Bot asks for photo
             ↓
User sends photo → saved to temp/
             ↓
Bot asks for name + text
             ↓
User sends:
  ირაკლი კობახიძე
  "ციტატა..."
             ↓
Parse name + text
             ↓
CardGenerator.generate()
             ↓
Bot sends generated card
             ↓
Cleanup temp files
             ↓
Ready for next card
```

---

### GitHub Photos Sync (Railway Startup)

```
Railway container starts
             ↓
web_app.py @app.on_event("startup")
             ↓
Check if .git exists
             ↓
   NO → git clone with GITHUB_TOKEN
   YES → git pull
             ↓
photos/ folder synced
             ↓
Web UI photo library updated
```

---

## 🎨 Card Design Specifications

- **Resolution:** 1080×1350 px (4:5 aspect ratio)
- **Format:** JPEG (quality: 90)
- **Background:** Photo (cover, center-top aligned)
- **Overlay:** Dark gradient (bottom 80%, opacity fade)
- **Shape:** Diagonal triangle (geometric accent)
- **Name Box:** Red square with white text
- **Quote:** White text, Georgian font, bottom section
- **Branding:** Red bar at bottom with logo/text
- **Font:** Helvetica Georgian (primary), Noto Sans Georgian (fallback)

---

## 📈 მომავალი გაუმჯობესებები

- [ ] Database integration (SQLite/PostgreSQL)
- [ ] User authentication
- [ ] Scheduled auto-posting
- [ ] Multiple card templates
- [ ] Video card generation
- [ ] Analytics dashboard
- [ ] Webhook integration
- [ ] Multi-language support

---

## 🛠️ Troubleshooting

### Bot არ რეაგირებს
- შეამოწმეთ `TELEGRAM_BOT_TOKEN`
- შეამოწმეთ Railway logs: `railway logs`
- გადაამოწმეთ bot-ის username BotFather-ში

### ფონტი არ ჩანს
- დარწმუნდით რომ `fonts/` საქაღალდეში არის `.otf` ფაილები
- შეამოწმეთ font base64 encoding

### Photos არ ტვირთავს
- შეამოწმეთ `GITHUB_TOKEN` permissions
- გადაამოწმეთ Railway startup logs
- მანუალურად დაამატეთ ფოტოები `/api/upload-photo`-ზე

### Railway deploy ჩავარდა
- შეამოწმეთ `requirements.txt` dependencies
- შეამოწმეთ Dockerfile syntax
- გადაამოწმეთ Python version (3.11)

---

## 📞 კონტაქტი & Resources

- **GitHub Repo:** https://github.com/zhorzholianitornike/jorjick
- **Railway Dashboard:** https://railway.app
- **Live App:** https://web-production-a33ea.up.railway.app

---

*დოკუმენტაცია განახლებულია: 2026-02-06*
*Version: 2.0*
