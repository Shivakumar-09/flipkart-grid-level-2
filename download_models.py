"""
TrafficFlow — AI Model Weights Downloader
==========================================
Downloads all required YOLO model weights at build time.
Run automatically by build.sh during Render deployment.

Models required:
  yolov8n.pt              — General vehicle/person detection
  yolov8n-pose.pt         — Pose estimation for helmet/rider detection
  license_plate_detector.pt — License plate detection (YOLOv8 fine-tuned)
  yolov8n_license_plate.pt  — Alternative plate detector
"""
import os
import sys
import logging
import urllib.request
import shutil

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("ModelDownloader")


def download_file(url, destination, description=""):
    """Download a file with progress logging. Skips if already present."""
    if os.path.exists(destination):
        size_mb = os.path.getsize(destination) / (1024 * 1024)
        logger.info(f"  SKIP (exists, {size_mb:.1f}MB): {destination}")
        return True

    logger.info(f"  Downloading {description or destination}...")
    logger.info(f"    URL: {url}")
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; TrafficFlow/1.0)",
                "Accept": "*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=300) as response:
            with open(destination, "wb") as out_file:
                shutil.copyfileobj(response, out_file)
        size_mb = os.path.getsize(destination) / (1024 * 1024)
        logger.info(f"  OK: {destination} ({size_mb:.1f}MB)")
        return True
    except Exception as e:
        logger.error(f"  FAILED to download {destination}: {e}")
        return False


def download_with_gdown(gdrive_id, destination, description=""):
    """Download from Google Drive using gdown (for large files)."""
    if os.path.exists(destination):
        size_mb = os.path.getsize(destination) / (1024 * 1024)
        logger.info(f"  SKIP (exists, {size_mb:.1f}MB): {destination}")
        return True

    logger.info(f"  Downloading {description or destination} via gdown...")
    try:
        import gdown
        url = f"https://drive.google.com/uc?id={gdrive_id}"
        gdown.download(url, destination, quiet=False)
        if os.path.exists(destination):
            size_mb = os.path.getsize(destination) / (1024 * 1024)
            logger.info(f"  OK: {destination} ({size_mb:.1f}MB)")
            return True
        else:
            logger.error(f"  FAILED: {destination} not found after gdown")
            return False
    except Exception as e:
        logger.error(f"  FAILED gdown for {destination}: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("  TrafficFlow Model Downloader")
    logger.info("=" * 60)

    project_root = os.path.dirname(os.path.abspath(__file__))
    success_all = True

    # ── Standard YOLOv8 Models (from Ultralytics GitHub releases) ──────────
    standard_models = {
        "yolov8n.pt": {
            "url": "https://github.com/ultralytics/assets/releases/download/v8.1.0/yolov8n.pt",
            "description": "YOLOv8n (vehicle + person detection)",
        },
        "yolov8n-pose.pt": {
            "url": "https://github.com/ultralytics/assets/releases/download/v8.1.0/yolov8n-pose.pt",
            "description": "YOLOv8n-Pose (rider pose estimation)",
        },
    }

    for filename, meta in standard_models.items():
        dest = os.path.join(project_root, filename)
        ok = download_file(meta["url"], dest, meta["description"])
        if not ok:
            success_all = False

    # ── License Plate Detector ─────────────────────────────────────────────
    # Primary: Muhammad-Zeerak-Khan Automatic-License-Plate-Recognition
    plate_dest = os.path.join(project_root, "license_plate_detector.pt")
    plate_ok = download_file(
        "https://github.com/Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8/raw/main/license_plate_detector.pt",
        plate_dest,
        "License plate detector (YOLOv8 fine-tuned)",
    )

    # ── Large Plate Model (yolov8n_license_plate.pt) ───────────────────────
    # This large model (~35MB) needs to be fetched from its original source.
    # If you hosted it on Google Drive, set PLATE_MODEL_GDRIVE_ID env var.
    large_plate_dest = os.path.join(project_root, "yolov8n_license_plate.pt")
    gdrive_id = os.environ.get("PLATE_MODEL_GDRIVE_ID", "")

    if gdrive_id:
        logger.info("Using Google Drive for yolov8n_license_plate.pt")
        ok = download_with_gdown(gdrive_id, large_plate_dest, "YOLOv8n License Plate (large)")
        if not ok:
            success_all = False
    elif not os.path.exists(large_plate_dest):
        logger.warning(
            "  yolov8n_license_plate.pt not found and PLATE_MODEL_GDRIVE_ID not set.\n"
            "  Upload it to Google Drive and set PLATE_MODEL_GDRIVE_ID in Render env vars.\n"
            "  Falling back to license_plate_detector.pt if available."
        )

    # ── Summary ────────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("  Download Summary")
    logger.info("=" * 60)
    for fname in [
        "yolov8n.pt",
        "yolov8n-pose.pt",
        "license_plate_detector.pt",
        "yolov8n_license_plate.pt",
    ]:
        path = os.path.join(project_root, fname)
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            logger.info(f"  ✓ {fname} ({size_mb:.1f}MB)")
        else:
            logger.warning(f"  ✗ {fname} MISSING")

    if not success_all:
        logger.warning("Some models failed to download, but continuing build anyway to allow fallback models to work.")
        logger.info("Model download step completed with fallback-compatible missing models.")
    else:
        logger.info("All required models downloaded successfully.")


if __name__ == "__main__":
    main()
