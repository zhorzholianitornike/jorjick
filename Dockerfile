FROM python:3.12-slim

WORKDIR /app

# ── dependencies (cached layer) ──────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── source ────────────────────────────────────────────────────────────
COPY . .

# Railway injects PORT automatically; default 8000 for local testing
EXPOSE 8000

CMD ["python3", "web_app.py"]
