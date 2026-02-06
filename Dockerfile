FROM python:3.12-slim

WORKDIR /app

# ── system dependencies for Playwright/Chromium + Git ──────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# ── Python dependencies (cached layer) ──────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Install Playwright Chromium browser ─────────────────────────────────
RUN playwright install chromium

# ── Configure git (for Railway deployment) ──────────────────────────────
RUN git config --global user.name "Railway Bot" && \
    git config --global user.email "bot@railway.app" && \
    git config --global init.defaultBranch main

# ── source ────────────────────────────────────────────────────────────
COPY . .

# Railway injects PORT automatically; default 8000 for local testing
EXPOSE 8000

CMD ["python3", "web_app.py"]
