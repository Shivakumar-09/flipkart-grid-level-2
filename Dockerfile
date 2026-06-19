# =============================================================
# TrafficFlow — Dockerfile
# Multi-stage build for Railway/Render deployment
# =============================================================

FROM python:3.11-slim

# ── System dependencies ──────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgomp1 \
    wget \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ────────────────────────────────────────
WORKDIR /app

# Keep Ultralytics from trying to write under /root/.config on Render.
ENV YOLO_CONFIG_DIR=/tmp/Ultralytics

# ── Python dependencies ──────────────────────────────────────
COPY requirements.txt .
RUN pip install --upgrade pip --no-cache-dir \
 && pip install --no-cache-dir -r requirements.txt

# ── Copy application source ──────────────────────────────────
COPY . .

# ── Download AI model weights at build time ──────────────────
RUN python download_models.py

# ── Ensure runtime output directories exist ──────────────────
RUN mkdir -p outputs/uploads outputs/debug/helmet challans ocr_debug "$YOLO_CONFIG_DIR" \
 && chmod -R 777 "$YOLO_CONFIG_DIR" \
 && chmod +x start.sh

# ── Expose port ──────────────────────────────────────────────
EXPOSE 5000

# ── Start gunicorn ───────────────────────────────────────────
CMD ["sh", "./start.sh"]
