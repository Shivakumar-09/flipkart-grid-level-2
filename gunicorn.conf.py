# =============================================================
# TrafficFlow — Gunicorn Production Configuration
# =============================================================
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
threads = 2
timeout = 120
accesslog = "-"
errorlog = "-"
loglevel = "info"
preload_app = False
