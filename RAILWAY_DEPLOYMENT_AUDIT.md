# TrafficFlow Railway Deployment Audit

## Executive Summary
This audit reviews the current state of the codebase for Railway deployment, identifying critical bottlenecks that prevent successful deployment and contribute to high memory usage. 

## 1. Dockerfile & Image Optimization
- **Current State**: Builds from `python:3.11-slim` and installs heavy dependencies (tesseract-ocr, pytorch). Models are downloaded during the build step.
- **Issue**: The current `.dockerignore` misses several directories like `venv`, `docs/reports` (though docs/reports is partially covered, we must ensure it strictly follows the phase 6 prompt), which can increase the image size.
- **Action Required**: Create a robust `.dockerignore` to keep image size <1.5GB as requested.

## 2. start.sh & Gunicorn
- **Current State**: `start.sh` executes `gunicorn app:app -c gunicorn.conf.py`.
- **Issue**: `gunicorn.conf.py` currently has `timeout = 120` but doesn't explicitly limit threads. 
- **Action Required**: Update `gunicorn.conf.py` to use `workers = 1`, `threads = 2`, and `preload_app = False`.

## 3. app.py Startup & Healthcheck
- **Current State**: `app.py` globally imports engines (`ViolationEngine`, `EvidenceEngine`, `AnalyticsEngine`) immediately upon initialization. The imports are inside a try/except block, but they still instantiate the engines directly (`violation_engine = ViolationEngine()`), causing memory allocation and potential timeouts.
- **Issue**: The `/health` endpoint is defined *after* the engines are imported, so the healthcheck will fail or timeout if the engines take too long to initialize or block on DB connections. It also currently returns `{"status": "healthy", "service": "TrafficFlow"}` which needs to be adjusted to `{"status":"ok"}`.
- **Action Required**: Move engine imports to lazy initialization inside the request lifecycle or route functions, and decouple the `/health` endpoint so it does not query the DB or load models.

## 4. Database Initialization
- **Current State**: `postgres.py` aggressively checks for `localhost` or `127.0.0.1` and disables the DB by setting `DATABASE_URL = None` if it finds it.
- **Issue**: The fallback logic is restrictive.
- **Action Required**: Enforce `DATABASE_URL = os.getenv("DATABASE_URL")` with no localhost fallback. Log a warning and use the `DummySessionMaker` if unavailable to ensure the app continues starting up without crashing.

## 5. Memory & Lazy Loading
- **Current State**: Models are instantiated within the properties of `ViolationEngine` or eagerly on first use. Some components trigger heavy memory allocation unnecessarily.
- **Issue**: Peak RAM exceeds limits.
- **Action Required**: Implement true lazy-loaded singletons for all models (`VehicleDetector`, `HelmetDetector`, `OcrEngine`, `TrafficLightDetector`, `SeatbeltDetector`), explicitly clear memory buffers, and streamline OCR processing to target <700MB startup memory.
