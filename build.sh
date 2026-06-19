#!/usr/bin/env bash
# =============================================================
# TrafficFlow — Render Build Script
# Runs ONCE at deploy time to download AI model weights.
# Model weights are excluded from git (too large).
# =============================================================

set -e  # Exit immediately on any error

echo "======================================================"
echo "  TrafficFlow Build — Downloading AI Model Weights"
echo "======================================================"

# Install system dependencies for OpenCV and Tesseract OCR
apt-get update -qq
apt-get install -y -qq tesseract-ocr libgl1-mesa-glx libglib2.0-0 libsm6 libxrender1 libxext6

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Download AI model weights
echo "Downloading model weights..."
python download_models.py

echo "======================================================"
echo "  Build complete!"
echo "======================================================"
