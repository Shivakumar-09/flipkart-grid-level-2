import os
import urllib.request
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ModelDownloader")

def download_file(url, destination):
    if os.path.exists(destination):
        logger.info(f"{destination} already exists, skipping download.")
        return
        
    logger.info(f"Downloading {url} to {destination}...")
    try:
        # Use User-Agent header to prevent HTTP 403 Forbidden errors (especially from Hugging Face)
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req) as response:
            with open(destination, 'wb') as out_file:
                out_file.write(response.read())
        logger.info(f"Successfully downloaded {destination}.")
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")

def main():
    # Model weights URLs
    models = {
        "yolov8n.pt": "https://github.com/ultralytics/assets/releases/download/v8.1.0/yolov8n.pt",
        "yolov8n-pose.pt": "https://github.com/ultralytics/assets/releases/download/v8.1.0/yolov8n-pose.pt",
        # Plate detector from:
        # https://github.com/Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8
        "license_plate_detector.pt": "https://github.com/Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8/raw/main/license_plate_detector.pt"
    }

    # Ensure model weights are saved in the project root so YOLO() loads them directly
    for filename, url in models.items():
        download_file(url, filename)

if __name__ == "__main__":
    main()
