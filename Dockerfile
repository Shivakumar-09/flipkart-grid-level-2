# =============================================================
# TrafficFlow — Dockerfile
# Multi-stage build for Render deployment
# =============================================================

FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*


# ── Working directory ────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ──────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip --no-cache-dir \
 && pip install --no-cache-dir -r requirements.txt

# ── Copy application source ──────────────────────────────────
COPY . .

# ── Download AI model weights at build time ──────────────────
RUN python download_models.py

# ── Ensure runtime output directories exist ──────────────────
RUN mkdir -p outputs/uploads outputs/debug/helmet challans ocr_debug

# ── Expose port ──────────────────────────────────────────────
EXPOSE 10000

# ── Start gunicorn ───────────────────────────────────────────
CMD gunicorn app:app \
    --workers=1 \
    --threads=2 \
    --timeout=120 \
    --bind 0.0.0.0:${PORT:-10000} \
    --log-level info \
    --access-logfile -
