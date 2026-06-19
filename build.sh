#!/usr/bin/env bash
# =============================================================
# TrafficFlow — Build Script (Python native runtime fallback)
# NOTE: For Docker-based Render deployment, system deps are
#       handled in the Dockerfile — this script only downloads
#       model weights.
# =============================================================

set -e

echo "======================================================"
echo "  TrafficFlow Build — Downloading AI Model Weights"
echo "======================================================"

# Install / upgrade Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Download AI model weights
python download_models.py

echo "======================================================"
echo "  Build complete!"
echo "======================================================"
