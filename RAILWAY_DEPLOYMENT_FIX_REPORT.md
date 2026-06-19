# Railway Deployment Fix Report

Generated: 2026-06-19

## Root Cause

Railway deployment failed with:

```text
'$PORT' is not a valid port number.
```

The repository `Procfile` passed `--bind=0.0.0.0:$PORT` directly to Gunicorn. In the failing Railway startup path, `$PORT` was not expanded before Gunicorn parsed the bind address, so Gunicorn received the literal string `$PORT` as the port.

`app.py` already used the correct Flask fallback pattern for direct Python starts:

```python
port = int(os.environ.get("PORT", 5000))
app.run(host="0.0.0.0", port=port, ...)
```

The Docker `CMD` used shell-form expansion, but it was replaced with a shared startup script to keep Docker, Procfile, and Railway config consistent.

## Files Modified

- `Dockerfile`
- `Procfile`
- `app.py`
- `download_models.py`
- `railway.json`
- `start.sh`

## Dockerfile Changes

- Changed deployment comment from Render-only to Railway/Render.
- Kept `YOLO_CONFIG_DIR=/tmp/Ultralytics` for writable Ultralytics settings.
- Ensured runtime directories and `YOLO_CONFIG_DIR` are created.
- Marked `start.sh` executable during image build.
- Changed `EXPOSE` from `10000` to `5000` as the local fallback port.
- Replaced inline Gunicorn startup command with:

```dockerfile
CMD ["sh", "./start.sh"]
```

## Startup Command Changes

Added `start.sh`:

```sh
APP_PORT="${PORT:-5000}"

exec gunicorn app:app \
    --workers="${WEB_CONCURRENCY:-1}" \
    --threads="${GUNICORN_THREADS:-2}" \
    --timeout="${GUNICORN_TIMEOUT:-120}" \
    --bind="0.0.0.0:${APP_PORT}" \
    --log-level="${GUNICORN_LOG_LEVEL:-info}" \
    --access-logfile=-
```

Updated `Procfile`:

```text
web: sh ./start.sh
```

Added `railway.json` to force Dockerfile deployment settings in code:

```json
{
  "build": {
    "builder": "DOCKERFILE"
  },
  "deploy": {
    "startCommand": "sh ./start.sh",
    "healthcheckPath": "/health",
    "healthcheckTimeout": 300,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

Railway's config-as-code reference confirms that `railway.json` can define build/deploy settings, Dockerfile builder selection, start command, healthcheck path, timeout, and restart policy.

Source: https://docs.railway.com/config-as-code/reference

## Production Configuration Verification

- PostgreSQL: `database/postgres.py` reads `DATABASE_URL`; local initialization check returned `SessionLocal=True` and `engine=True`.
- Static files: Flask is configured with `dashboard/static` and `dashboard/templates`.
- Dashboard route: `/` returned `200 text/html`.
- Health routes: `/health` and `/api/health` return `{"status": "healthy"}`.
- OCR loading: EasyOCR loaded, Tesseract loaded, license plate YOLO model loaded.
- Optional OCR: PaddleOCR is not installed locally; app disables PaddleOCR attempts without failing startup.
- YOLO loading: `yolov8n.pt`, `yolov8n-pose.pt`, and `license_plate_detector.pt` loaded on CPU during local simulation.
- Dashboard APIs: `/api/metrics`, `/api/charts`, and `/api/analytics` returned HTTP 200.

## Deployment Validation Results

| Check | Result |
|---|---|
| Python syntax compile for `app.py`, `download_models.py`, `utils/runtime.py`, `database/postgres.py` | Passed |
| `railway.json` JSON parsing | Passed |
| `start.sh` POSIX syntax check with `sh -n` | Passed |
| Search for direct startup `0.0.0.0:$PORT` usage | Passed, removed |
| `/health` test-client request | Passed, HTTP 200 |
| `/api/health` test-client request | Passed, HTTP 200 |
| Dashboard `/` test-client request | Passed, HTTP 200 |
| `/api/metrics` | Passed, HTTP 200 |
| `/api/charts` | Passed, HTTP 200 |
| `/api/analytics` | Passed, HTTP 200 |
| PostgreSQL local initialization | Passed |
| YOLO/OCR model smoke test | Passed for loading/execution |
| Local Docker build | Not run: Docker CLI is not installed on this machine |
| Local Docker container run | Not run: Docker CLI is not installed on this machine |
| Direct `/api/upload` test | Not run against configured DB to avoid writing test analytics/evidence records |

## Git Commit

Deployment fix commit:

```text
1b7808007d317e1421c39eccb4a2a16188eed0c7
```

Commit message:

```text
fix: Railway deployment port configuration and production startup
```

## Expected Railway Outcome

- Railway injects `PORT`.
- `start.sh` converts it into `APP_PORT`.
- Gunicorn receives a concrete bind address like `0.0.0.0:12345`.
- The literal `$PORT` string is no longer passed as a port.
- Railway health checks use `/health` and receive `{"status": "healthy"}`.
