"""
test_pipeline.py — TrafficFlow Quick Validation Test
======================================================
Run this script to verify that all core engines and
API endpoints are working correctly before submission.

Usage:
    python test_pipeline.py
"""

import os
import sys
# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import requests
import time
from database.postgres import SessionLocal, engine, initialize_database, Violation

BASE_URL = "http://127.0.0.1:5000"
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results = []

def test(name, fn):
    try:
        result = fn()
        status = PASS if result else FAIL
        results.append((name, status, ""))
        print(f"  {status}  {name}")
    except Exception as e:
        results.append((name, FAIL, str(e)))
        print(f"  {FAIL}  {name} — {e}")

print("\n" + "="*60)
print("  TrafficFlow -- Pipeline Validation Suite")
print("  Team Vardhamans | Flipkart Grid Hackathon")
print("="*60)

# ── 1. File Existence Tests ──────────────────────────────────
print("\n[1] Core File Checks")
def check_file_exists(rel_path):
    return os.path.exists(os.path.join(PROJECT_ROOT, rel_path))

test("app.py exists",              lambda: check_file_exists("app.py"))
test("requirements.txt exists",    lambda: check_file_exists("requirements.txt"))
test("engine/violation_engine.py", lambda: check_file_exists("engine/violation_engine.py"))
test("engine/evidence_engine.py",  lambda: check_file_exists("engine/evidence_engine.py"))
test("engine/analytics_engine.py", lambda: check_file_exists("engine/analytics_engine.py"))
test("models/ocr_engine.py",       lambda: check_file_exists("models/ocr_engine.py"))
test("dashboard/templates/index.html", lambda: check_file_exists("dashboard/templates/index.html"))
test("dashboard/static/app.js",    lambda: check_file_exists("dashboard/static/app.js"))
test(".gitignore exists",          lambda: check_file_exists(".gitignore"))

# ── 2. Import Tests ──────────────────────────────────────────
print("\n[2] Python Import Checks")
test("Flask importable",   lambda: __import__("flask") and True)
test("SQLAlchemy importable", lambda: __import__("sqlalchemy") and True)
test("NumPy importable",   lambda: __import__("numpy") and True)
test("OpenCV importable",  lambda: __import__("cv2") and True)
test("UUID importable",    lambda: __import__("uuid") and True)

# ── 3. Database Tests ────────────────────────────────────────
print("\n[3] Database Checks")
def check_postgres_conn():
    try:
        initialize_database()
        return True
    except Exception as e:
        print(f"PostgreSQL connection error: {e}")
        return False

def check_db_tables():
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = {"violations", "sms_logs", "police_alerts", "traffic_analytics", "challans", "vehicles"}
    return required.issubset(tables)

test("PostgreSQL connection", check_postgres_conn)
test("Required tables present", check_db_tables)

def check_db_has_data():
    session = SessionLocal()
    try:
        count = session.query(Violation).count()
        return count > 0
    except Exception:
        return False
    finally:
        session.close()

test("Database has violation records", check_db_has_data)

# ── 4. API Endpoint Tests ────────────────────────────────────
print("\n[4] API Endpoint Checks")

def api_get(endpoint):
    r = requests.get(BASE_URL + endpoint, timeout=25)
    return r.status_code == 200

def api_post(endpoint, payload):
    r = requests.post(BASE_URL + endpoint, json=payload, timeout=25)
    return r.status_code in (200, 201)

try:
    test("GET  /",                    lambda: api_get("/"))
    test("GET  /api/logs",            lambda: api_get("/api/logs"))
    test("GET  /api/command_center",  lambda: api_get("/api/command_center"))
    test("GET  /api/analytics",       lambda: api_get("/api/analytics"))
    test("GET  /api/recommendations", lambda: api_get("/api/recommendations"))
    test("GET  /api/predictions",     lambda: api_get("/api/predictions"))
    test("GET  /api/repeat_offenders",lambda: api_get("/api/repeat_offenders"))
    test("GET  /api/deployed_patrols",lambda: api_get("/api/deployed_patrols"))
    test("POST /api/ai_assistant",    lambda: api_post("/api/ai_assistant", {"query": "How many violations?"}))
except requests.exceptions.ConnectionError:
    print(f"  {WARN}  Flask server not running — start with: python app.py")

# ── 5. Summary ───────────────────────────────────────────────
print("\n" + "="*60)
passed = sum(1 for _, s, _ in results if s == PASS)
failed = sum(1 for _, s, _ in results if s == FAIL)
total  = len(results)

print(f"  Results: {passed}/{total} passed  |  {failed} failed")
if failed == 0:
    print("  TrafficFlow is READY for submission!")
else:
    print("  Some checks failed. Review the errors above.")
print("="*60 + "\n")
