# Deployment Root Cause Analysis Report

## Executive Summary
This report analyzes the root causes of the Railway production deployment failures for the TrafficFlow application, detailing issues with database connectivity, startup memory pressure, health check failures, and Docker image bloat.

## Root Cause Diagnostics

### 1. Database Connection Blocking Startup
- **Symptom**: Startup processes hang or crash, failing Railway health checks after 5 minutes.
- **Root Cause**: In `database/postgres.py`, the module-level `initialize_database()` is invoked immediately upon import. If `DATABASE_URL` is missing or incorrect, it tries to connect to a default `localhost` PostgreSQL engine. In containerized environments like Railway, no local PostgreSQL exists on `localhost`, leading to blocking connection attempts (5 retries * 3 seconds delay = 15 seconds block) or eventual crashes.
- **Impact**: App startup is blocked or fails, resulting in health check timeouts.

### 2. Gunicorn Worker Memory Pressure (SIGKILL)
- **Symptom**: Railway logs show workers receiving `SIGKILL`.
- **Root Cause**: Gunicorn launches multiple worker processes. If `WEB_CONCURRENCY` is set to 2 or 4, each worker imports `app.py`, which instantiates `ViolationEngine`. This triggers immediate loading of multiple heavy AI models (YOLOv8, YOLOv8-Pose, EasyOCR, PaddleOCR) at startup.
- **Impact**: Combined RAM footprint of 2-4 workers loading 7 distinct model instances exceeds the 512MB/1GB memory limits of standard hosting plans, triggering the system Out-Of-Memory (OOM) killer.

### 3. CPU PyTorch vs. GPU PyTorch Bloat
- **Symptom**: Docker image size is ~2.9GB, leading to long build and pull times.
- **Root Cause**: Standard `pip install -r requirements.txt` fetches the default PyTorch (`torch` and `torchvision`) packages from PyPI. These default packages bundle extensive CUDA/NVIDIA GPU libraries, which are not used in CPU-only production containers.
- **Impact**: The container size swells by ~1.7GB with unused GPU binaries.

---
*Generated automatically by TrafficFlow Deployment Analyzer.*
