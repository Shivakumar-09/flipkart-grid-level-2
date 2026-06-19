import os
from dotenv import load_dotenv
load_dotenv()
import csv
import logging
import json
import uuid
import warnings
import numpy as np
import time
from datetime import datetime, timedelta, time as time_type
from functools import lru_cache, wraps
from flask import Flask, request, jsonify, render_template, send_from_directory, Response, has_request_context
from flask_compress import Compress
from sqlalchemy import func
from database.postgres import (
    SessionLocal, Vehicle, Violation, Challan, OCRResult,
    RepeatOffender, PoliceAlert, PatrolDispatch, Payment, SMSLog,
    Analytics, SafetyVideoView, CameraNode, EvidencePackage
)

# Suppress warnings
warnings.filterwarnings("ignore", category=UserWarning)

# Cache decorator for API responses
_cache_store = {}
_cache_timestamps = {}

def api_cache(timeout=300):
    """Simple in-memory cache decorator for API endpoints, context-aware for background warming"""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if has_request_context():
                if request.args:
                    sorted_args = sorted(request.args.items())
                    cache_key = f"{f.__name__}_{sorted_args}"
                else:
                    cache_key = f"{f.__name__}_default"
                
                now = time.time()
                hit = cache_key in _cache_store and cache_key in _cache_timestamps
                if hit:
                    valid = (now - _cache_timestamps[cache_key] < timeout)
                    logger.info(f"CACHE CHECK: {cache_key} | Hit: {hit} | Valid: {valid}")
                    if valid:
                        return _cache_store[cache_key]
                else:
                    logger.info(f"CACHE CHECK: {cache_key} | Hit: False")
            else:
                cache_key = f"{f.__name__}_default"
                logger.info(f"CACHE WARMING: Recalculating {cache_key}")
            
            # Recalculate/execute function
            result = f(*args, **kwargs)
            _cache_store[cache_key] = result
            _cache_timestamps[cache_key] = time.time()
            return result
        return decorated_function
    return decorator

# Setup absolute project path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Load camera locations dynamically
CAMERA_LOCATIONS = {}
try:
    with open(os.path.join(PROJECT_ROOT, "camera_locations.json"), "r") as f:
        CAMERA_LOCATIONS = json.load(f)
except Exception as e:
    logging.getLogger("TrafficFlowApp").error(f"Failed to load camera_locations.json: {e}")

VEHICLE_CONTACTS = {}
try:
    contacts_path = os.path.join(PROJECT_ROOT, "vehicle_contacts.json")
    if os.path.exists(contacts_path):
        with open(contacts_path, "r") as f:
            VEHICLE_CONTACTS = json.load(f)
except Exception as e:
    logging.getLogger("TrafficFlowApp").error(f"Failed to load vehicle_contacts.json: {e}")
TEMPLATE_DIR = os.path.join(PROJECT_ROOT, "dashboard", "templates")
STATIC_DIR = os.path.join(PROJECT_ROOT, "dashboard", "static")
OUTPUTS_DIR = os.path.join(PROJECT_ROOT, "outputs")
DATABASE_DIR = os.path.join(PROJECT_ROOT, "database")

# Ensure necessary directories exist
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(DATABASE_DIR, exist_ok=True)

# Configure Flask app
app = Flask(
    __name__, 
    template_folder=TEMPLATE_DIR, 
    static_folder=STATIC_DIR,
    static_url_path='/static'
)

# Enable Gzip compression for faster responses
Compress(app)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TrafficFlowApp")

# Import system engines
# (Delay engine import or wrap to handle potential runtime load anomalies cleanly)
try:
    from engine.violation_engine import ViolationEngine
    from engine.evidence_engine import EvidenceEngine
    from engine.analytics_engine import AnalyticsEngine

    violation_engine = ViolationEngine()
    evidence_engine = EvidenceEngine(
        db_path=os.path.join(DATABASE_DIR, "trafficflow.db"),
        output_dir=OUTPUTS_DIR
    )
    analytics_engine = AnalyticsEngine(
        db_path=os.path.join(DATABASE_DIR, "trafficflow.db")
    )
    logger.info("Engines integrated successfully.")
except Exception as e:
    logger.critical(f"Engine initialization failed: {e}")
    # Fallback placeholders if imports fail on fresh environment check
    violation_engine = None
    evidence_engine = None
    analytics_engine = None

def resolve_customer_contact(plate_number):
    plate_key = (plate_number or "UNKNOWN").strip().upper()
    contact = VEHICLE_CONTACTS.get(plate_key) or VEHICLE_CONTACTS.get("DEFAULT", {})
    return {
        "name": contact.get("name", "Vehicle Owner"),
        "phone": contact.get("phone") or os.environ.get("DEFAULT_CUSTOMER_PHONE", "+919876543210")
    }

def build_challan_message(violation, customer, location):
    plate = violation.get("plate_number") or "UNKNOWN"
    challan = violation.get("challan_id") or "PENDING"
    vtype = violation.get("violation_type") or violation.get("type") or "VIOLATION"
    amount = violation.get("fine_amount", violation.get("amount", 1000))
    base_url = os.environ.get("PUBLIC_BASE_URL", "http://localhost:5000").rstrip("/")
    payment_url = os.environ.get("CHALLAN_PAYMENT_URL", "BTP payment portal")
    evidence_url = f"{base_url}/challans/{challan}.pdf"
    return (
        f"TrafficFlow challan {challan}: {vtype} recorded for vehicle {plate} "
        f"at {location}. Fine INR {amount}. Evidence: {evidence_url}. Pay via {payment_url}."
    )

def send_sms(type_str, recipient, message, plate_number=None, challan_id=None):
    """
    Sends an SMS via Twilio (if credentials exist) or simulates it in demo mode.
    Logs notification to the SMSLog database table.
    """
    account_sid = os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_FROM_NUMBER")
    
    status = "DEMO_SENT"
    
    if account_sid and auth_token and from_number:
        try:
            from twilio.rest import Client
            client = Client(account_sid, auth_token)
            client.messages.create(
                body=message,
                from_=from_number,
                to=recipient
            )
            status = "DELIVERED"
            logger.info(f"SMS sent successfully to {recipient} via Twilio.")
        except Exception as e:
            status = "FAILED"
            logger.error(f"Failed to send Twilio SMS: {e}")
    else:
        # Mock details to console
        logger.info(f"[DEMO SMS] To: {recipient} | Message: {message}")
    
    # Log in sms_logs table
    try:
        session = SessionLocal()
        notification_id = str(uuid.uuid4())
        timestamp_dt = datetime.now()
        log = SMSLog(
            notification_id=notification_id,
            type=type_str,
            recipient=recipient,
            status=status,
            timestamp=timestamp_dt,
            message=message,
            plate_number=plate_number,
            challan_id=challan_id
        )
        session.add(log)
        session.commit()
        session.close()
        return {
            "notification_id": notification_id,
            "type": type_str,
            "recipient": recipient,
            "status": status,
            "timestamp": timestamp_dt.strftime("%Y-%m-%d %H:%M:%S"),
            "message": message,
            "plate_number": plate_number,
            "challan_id": challan_id
        }
    except Exception as e:
        logger.error(f"Failed to write notification to database: {e}")
        return {
            "type": type_str,
            "recipient": recipient,
            "status": "LOG_FAILED",
            "message": message,
            "plate_number": plate_number,
            "challan_id": challan_id
        }

# Custom route to serve output evidence images
@app.route('/outputs/<path:filename>')
def serve_outputs(filename):
    return send_from_directory(OUTPUTS_DIR, filename)

# Custom route to serve output evidence images under /evidence/ (Step 6)
@app.route('/evidence/<path:filename>')
def serve_evidence(filename):
    return send_from_directory(os.path.join(OUTPUTS_DIR, "evidence"), filename)

# Custom route to serve uploads under /uploads/ (Step 6)
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    return send_from_directory(os.path.join(OUTPUTS_DIR, "uploads"), filename)

# Custom route to serve sample outputs under /sample_outputs/ (Step 6)
@app.route('/sample_outputs/<path:filename>')
def serve_sample_outputs(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "sample_outputs"), filename)

# Custom route to serve generated PDF Challans (Task 7)
@app.route('/challans/<path:filename>')
def serve_challans(filename):
    return send_from_directory(os.path.join(PROJECT_ROOT, "challans"), filename)

# Serving dashboard HTML
@app.route('/')
def index():
    return render_template('index.html')

# API: Summary Metrics
@app.route('/api/metrics', methods=['GET'])
@api_cache(timeout=300)
def get_metrics():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
    metrics = analytics_engine.get_summary_metrics()
    return jsonify(metrics)

# API: Fallback Stats
@app.route('/api/stats', methods=['GET'])
def get_stats():
    return get_metrics()

# API: Chart Metrics
@app.route('/api/charts', methods=['GET'])
@api_cache(timeout=300)
def get_charts():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
    
    breakdown = analytics_engine.get_violation_breakdown()
    trends = analytics_engine.get_daily_trends()
    peak_hours = analytics_engine.get_peak_hours()
    weekend_vs_weekday = analytics_engine.get_weekend_vs_weekday_trends()
    
    return jsonify({
        "breakdown": breakdown,
        "trends": trends,
        "peak_hours": peak_hours,
        "weekend_vs_weekday": weekend_vs_weekday
    })

# API: City Analytics details
@app.route('/api/analytics', methods=['GET'])
@api_cache(timeout=300)
def get_analytics_details():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
        
    wards = analytics_engine.get_ward_stats()
    repeat_offenders = analytics_engine.get_repeat_offenders()
    hotspots = analytics_engine.get_violation_hotspots()
    top_congested_areas = analytics_engine.get_top_congested_areas()
    camera_nodes_heatmap = analytics_engine.get_camera_heatmap()
    live_alerts = analytics_engine.get_live_alerts()
    sms_logs = analytics_engine.get_sms_logs()
    
    return jsonify({
        "wards": wards,
        "repeat_offenders": repeat_offenders,
        "hotspots": hotspots,
        "top_congested_areas": top_congested_areas,
        "camera_nodes_heatmap": camera_nodes_heatmap,
        "live_alerts": live_alerts,
        "sms_logs": sms_logs
    })

# API: Model Evaluation details
@app.route('/api/evaluation', methods=['GET'])
@api_cache(timeout=300)
def get_evaluation_details():
    try:
        from evaluation.metrics import calculate_metrics
        return jsonify(calculate_metrics())
    except Exception as e:
        logger.error(f"Failed to fetch evaluation metrics: {e}")
        return jsonify({"error": str(e)}), 500

# API: Traffic Command Center details (Phase 1, 2, 3, 4, 10, 11)
@app.route('/api/command_center', methods=['GET'])
@api_cache(timeout=300)
def get_command_center():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
        
    kpis = analytics_engine.get_summary_metrics()
    hotspots = analytics_engine.get_violation_hotspots()
    alerts = analytics_engine.get_live_alerts()
    
    # Map coordinates to hotspots for Leaflet markers
    COORDINATES = {
        "Silk Board": [12.9176, 77.6244],
        "Whitefield": [12.9698, 77.7499],
        "Electronic City": [12.8452, 77.6755],
        "Marathahalli": [12.9562, 77.7011],
        "Hebbal": [13.0354, 77.5978],
        "KR Puram": [13.0040, 77.6780],
        "Koramangala": [12.9352, 77.6244],
        "HSR Layout": [12.9121, 77.6446],
        "Majestic": [12.9766, 77.5712],
        "Yelahanka": [13.1006, 77.5963]
    }
    
    markers = []
    for h in hotspots:
        loc_name = h["location"]
        coords = COORDINATES.get(loc_name, [12.9716, 77.5946])
        
        # Color coding spec: Green (0-20), Yellow (21-50), Orange (51-100), Red (100+)
        v_count = h["violation_count"]
        if v_count >= 100:
            color = "red"
        elif v_count >= 51:
            color = "orange"
        elif v_count >= 21:
            color = "yellow"
        else:
            color = "green"
            
        markers.append({
            "camera_id": h["camera_id"],
            "location": loc_name,
            "coordinates": coords,
            "violation_count": v_count,
            "traffic_density": h["avg_density"],
            "risk_score": h["hotspot_score"],
            "color": color,
            "action": h["action"]
        })
        
    # Generate Smart Insights (Phase 11)
    most_dangerous = hotspots[0]["location"] if hotspots else "None"
    
    congested_sorted = sorted(hotspots, key=lambda x: x["avg_density"], reverse=True)
    most_congested = congested_sorted[0]["location"] if congested_sorted else "None"
    
    breakdown = analytics_engine.get_violation_breakdown()
    most_common_violation = max(breakdown, key=breakdown.get).replace("_", " ").title() if breakdown else "None"
    
    peak_traffic_hour = kpis["peak_hour"]
    highest_revenue = hotspots[0]["location"] if hotspots else "None"
    
    repeat_sorted = sorted(hotspots, key=lambda x: x["repeat_offenders"], reverse=True)
    repeat_offender_zone = repeat_sorted[0]["location"] if repeat_sorted else "None"
    
    insights = {
        "most_dangerous_area": most_dangerous,
        "most_congested_area": most_congested,
        "most_common_violation": most_common_violation,
        "peak_traffic_hour": peak_traffic_hour,
        "highest_revenue_area": highest_revenue,
        "repeat_offender_zone": repeat_offender_zone
    }
    
    return jsonify({
        "kpis": kpis,
        "markers": markers,
        "alerts": alerts,
        "insights": insights
    })

# API: Detailed Chart Statistics (Phase 5, 6 & 7)
@app.route('/api/detailed_charts', methods=['GET'])
@api_cache(timeout=300)
def get_detailed_charts():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
        
    hourly = analytics_engine.get_peak_hours()
    weekday = analytics_engine.get_weekday_trends()
    weekend = analytics_engine.get_weekend_trends()
    monthly = analytics_engine.get_monthly_trends()
    location_wise = analytics_engine.get_location_wise_violations()
    weekend_vs_weekday = analytics_engine.get_weekend_vs_weekday_trends()
    
    return jsonify({
        "hourly": hourly,
        "weekday": weekday,
        "weekend": weekend,
        "monthly": monthly,
        "location_wise": location_wise,
        "weekend_vs_weekday": weekend_vs_weekday
    })

# API: Violation logs list - updated for new database schema and UI table format

@app.route('/api/logs', methods=['GET'])
@api_cache(timeout=300)
def get_logs():
    session = SessionLocal()
    try:
        # Use limit to reduce dataset size
        if has_request_context():
            limit = min(int(request.args.get('limit', 100)), 500)
        else:
            limit = 100
        
        results = session.query(
            Violation, Vehicle, Challan, OCRResult, EvidencePackage
        ).join(
            Vehicle, Violation.vehicle_id == Vehicle.id, isouter=True
        ).join(
            Challan, Violation.id == Challan.violation_id, isouter=True
        ).join(
            OCRResult, Violation.id == OCRResult.violation_id, isouter=True
        ).join(
            EvidencePackage, Violation.id == EvidencePackage.violation_id, isouter=True
        ).order_by(
            Violation.timestamp.desc()
        ).limit(limit).all()
        
        logs = []
        for violation, vehicle, challan, ocr_result, evidence_package in results:
            attempts = []
            vehicle_crop_path = f"{violation.evidence_path}/vehicle_crop.jpg"
            if evidence_package:
                if evidence_package.ocr_results:
                    try:
                        ocr_res_data = json.loads(evidence_package.ocr_results)
                        attempts = ocr_res_data.get("attempts", [])
                    except Exception:
                        pass
                if evidence_package.image_paths:
                    try:
                        img_paths = json.loads(evidence_package.image_paths)
                        if img_paths.get("vehicle_crop"):
                            vehicle_crop_path = img_paths["vehicle_crop"]
                    except Exception:
                        pass

            d = {
                "id": violation.id,
                "violation_id": violation.id,
                "violation_type": violation.violation_type,
                "confidence": violation.confidence,
                "timestamp": violation.timestamp.strftime("%Y-%m-%d %H:%M:%S") if violation.timestamp else "",
                "location": violation.location,
                "camera_id": violation.camera_id,
                "evidence_path": violation.evidence_path,
                "evidence_image_path": f"{violation.evidence_path}/annotated.jpg",
                
                "plate_number": vehicle.plate_number if vehicle else "UNKNOWN",
                "challan_id": challan.challan_id if challan else "NONE",
                "amount": challan.amount if challan else 0,
                "status": challan.status if challan else "PENDING",
                
                "ocr_confidence": ocr_result.ocr_confidence if ocr_result else 0.0,
                "ocr_engine": ocr_result.ocr_engine if ocr_result else "none",
                "plate_crop_path": ocr_result.plate_crop_path if ocr_result else "",
                "enhanced_plate_path": ocr_result.enhanced_plate_path if ocr_result else "",
                "ocr_result_path": ocr_result.ocr_result_path if ocr_result else "",
                "ocr_attempts": attempts,
                
                "ocr_debug_paths": {
                    "plate_crop": ocr_result.plate_crop_path if ocr_result else "",
                    "enhanced_plate": ocr_result.enhanced_plate_path if ocr_result else "",
                    "ocr_result": ocr_result.ocr_result_path if ocr_result else "",
                    "vehicle_crop": vehicle_crop_path
                }
            }
            logs.append(d)
        return jsonify(logs)
    except Exception as e:
        logger.error(f"Failed to fetch logs: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# API: Image/Video Upload violation analysis pipeline (Phase 9 & Phase 1)
@app.route('/api/upload', methods=['POST'])
def upload_frame():
    print("UPLOAD RECEIVED")
    _cache_store.clear()
    _cache_timestamps.clear()
    import time
    if violation_engine is None or evidence_engine is None:
        return jsonify({"error": "AI Inference engines are offline or loading"}), 503
        
    if 'image' not in request.files:
        return jsonify({"error": "No image or video file provided"}), 400
        
    file = request.files['image']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
        
    camera_id = request.form.get("camera_id", "CAM_BLR_001")
    if camera_id not in CAMERA_LOCATIONS:
        camera_id = "CAM_BLR_001"
    location = CAMERA_LOCATIONS[camera_id]
    
    unique_filename = f"{uuid.uuid4()}_{file.filename}"
    uploads_dir = os.path.join(OUTPUTS_DIR, "uploads")
    os.makedirs(uploads_dir, exist_ok=True)
    upload_path = os.path.join(uploads_dir, unique_filename)
    file.save(upload_path)
    
    is_video = file.filename.lower().split('.')[-1] in ['mp4', 'avi', 'mov', 'mkv']
    
    try:
        if is_video:
            print("PROCESSING VIDEO")
            # Open Video
            cap = cv2.VideoCapture(upload_path)
            if not cap.isOpened():
                return jsonify({"error": "Could not open video file"}), 400
                
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 100
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            
            violation_id = str(uuid.uuid4())
            package_dir = os.path.join(OUTPUTS_DIR, "evidence", violation_id)
            os.makedirs(package_dir, exist_ok=True)
            
            annotated_video_filename = "annotated_video.mp4"
            annotated_video_path = os.path.join(package_dir, annotated_video_filename)
            
            # Setup VideoWriter
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(annotated_video_path, fourcc, fps, (width, height))
            
            step = max(1, total_frames // 15) # Process ~15 frames for AI speed
            frame_count = 0
            violations_acc = []
            detections_acc = 0
            processing_start = time.time()
            import cv2
            
            # Mock or run core detection on key frames
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                    
                if frame_count % step == 0:
                    # Save frame temporarily
                    temp_frame_path = os.path.join(OUTPUTS_DIR, f"temp_frame_{frame_count}.jpg")
                    cv2.imwrite(temp_frame_path, frame)
                    try:
                        res = violation_engine.process_image(temp_frame_path, location, camera_id)
                        frame_annotated = res["annotated_image"]
                        detections_acc = max(detections_acc, res["detections_count"])
                        # Accumulate violations
                        for v in res["violations"]:
                            if not any(exist["type"] == v["type"] for exist in violations_acc):
                                violations_acc.append(v)
                    except Exception as e:
                        logger.error(f"Error processing frame {frame_count}: {e}")
                        frame_annotated = frame
                    finally:
                        if os.path.exists(temp_frame_path):
                            os.remove(temp_frame_path)
                else:
                    frame_annotated = frame
                    
                out.write(frame_annotated)
                frame_count += 1
                
            cap.release()
            out.release()
            
            print("INFERENCE COMPLETE")
            
            # Reconstruct dummy/aggregated process result to generate evidence
            # Save first frame as original visual evidence crop
            first_frame_path = os.path.join(package_dir, "original.jpg")
            first_anno_path = os.path.join(package_dir, "annotated.jpg")
            cap = cv2.VideoCapture(upload_path)
            ret, first_frame = cap.read()
            if ret:
                cv2.imwrite(first_frame_path, first_frame)
                cv2.imwrite(first_anno_path, first_frame)
                # Also save original_full.jpg and annotated_full.jpg to match evidence package expectations
                cv2.imwrite(os.path.join(package_dir, "original_full.jpg"), first_frame)
                cv2.imwrite(os.path.join(package_dir, "annotated_full.jpg"), first_frame)
            cap.release()
            
            # Generate DB logs & evidence files
            mock_process_result = {
                "original_image": first_frame if ret else np.zeros((480, 640, 3), dtype=np.uint8),
                "annotated_image": first_frame if ret else np.zeros((480, 640, 3), dtype=np.uint8),
                "violations": violations_acc,
                "detections_count": detections_acc,
                "camera_id": camera_id,
                "location": location
            }
            recorded_violations = evidence_engine.generate_evidence(mock_process_result)
            
            # Send SMS notifications (Phase 4)
            sent_notifications = []
            for violation in recorded_violations:
                try:
                    plate = violation.get("plate_number") or "UNKNOWN"
                    challan = violation.get("challan_id")
                    customer = resolve_customer_contact(plate)
                    sms_message = build_challan_message(violation, customer, location)
                    cit_noti = send_sms("CUSTOMER_CHALLAN", customer["phone"], sms_message, plate, challan)
                    sent_notifications.append(cit_noti)
                except Exception as ex:
                    logger.error(f"Failed to send SMS notice: {ex}")
            
            # Rel Paths
            rel_video_path = f"outputs/evidence/{violation_id}/{annotated_video_filename}"
            
            # Return JSON
            print("RETURNING RESPONSE")
            return jsonify({
                "status": "success",
                "success": True,
                "processing_time_ms": int((time.time() - processing_start) * 1000),
                "detections_count": detections_acc,
                "violations": recorded_violations,
                "challan": recorded_violations[-1] if recorded_violations else {},
                "violation_id": violation_id,
                "evidence_video_path": rel_video_path,
                "annotated_image": f"/evidence/{violation_id}/annotated.jpg",
                "original_image": f"/evidence/{violation_id}/original_full.jpg",
                "detected_plate": recorded_violations[-1].get("plate_number", "UNKNOWN") if recorded_violations else "UNKNOWN",
                "plate_number": recorded_violations[-1].get("plate_number", "UNKNOWN") if recorded_violations else "UNKNOWN",
                "challan_id": recorded_violations[-1].get("challan_id", "NONE") if recorded_violations else "NONE",
                "ocr_confidence": recorded_violations[-1].get("ocr_confidence", 0.0) if recorded_violations else 0.0,
                "notifications_sent": sent_notifications
            })
            
        else:
            # Process single image
            print("PROCESSING IMAGE")
            process_result = violation_engine.process_image(
                upload_path, 
                location=location, 
                camera_id=camera_id
            )
            print("INFERENCE COMPLETE")
            
            # Save evidence outputs and DB logs
            recorded_violations = evidence_engine.generate_evidence(process_result)
            sent_notifications = []
            
            # --- SMART CITY EXTENSIONS (Phase 5, 6 & 7) ---
            timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # 1. Log Traffic Density
            try:
                session = SessionLocal()
                analytics_id = str(uuid.uuid4())
                an = Analytics(
                    id=analytics_id,
                    location=location,
                    camera_id=camera_id,
                    traffic_density=float(process_result["detections_count"]),
                    timestamp=datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
                )
                session.add(an)
                session.commit()
                session.close()
            except Exception as ex:
                logger.error(f"Error logging traffic density: {ex}")
                
            # 2. Check Congestion Alert (Patrol dispatch)
            try:
                session = SessionLocal()
                today_start = datetime.combine(datetime.now().date(), datetime.min.time())
                today_end = datetime.combine(datetime.now().date(), datetime.max.time())
                loc_violations_today = session.query(Violation).filter(
                    Violation.location == location,
                    Violation.timestamp >= today_start,
                    Violation.timestamp <= today_end
                ).count()
                session.close()
            except Exception as ex:
                logger.error(f"Error checking violations count: {ex}")
                loc_violations_today = 0
    
            if loc_violations_today >= 3 or process_result["detections_count"] > 5:
                try:
                    alert_id = str(uuid.uuid4())
                    severity = "HIGH" if (loc_violations_today >= 5 or process_result["detections_count"] > 8) else "MEDIUM"
                    alert_msg = f"High traffic congestion detected at {location}. Recommended traffic unit deployment."
                    session = SessionLocal()
                    alert = PoliceAlert(
                        alert_id=alert_id,
                        location=location,
                        severity=severity,
                        timestamp=datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S"),
                        status=alert_msg
                    )
                    session.add(alert)
                    session.commit()
                    session.close()
                    
                    # Send mock/real SMS alert to control center
                    sms_message = f"🚨 TRAFFICFLOW ALERT: {alert_msg}"
                    alert_notification = send_sms(
                        type_str="CONGESTION_ALERT",
                        recipient="+919900000000",
                        message=sms_message
                    )
                    sent_notifications.append(alert_notification)
                except Exception as ex:
                    logger.error(f"Error creating police patrol alert: {ex}")
                    
            # 3. Send SMS Notices for each recorded violation
            for violation in recorded_violations:
                try:
                    vtype = violation.get("violation_type") or violation.get("type") or "VIOLATION"
                    plate = violation.get("plate_number") or "UNKNOWN"
                    challan = violation.get("challan_id")
                    amt = violation.get("fine_amount", 1000)
                    
                    customer = resolve_customer_contact(plate)
                    sms_message = build_challan_message(
                        {
                            "violation_type": vtype,
                            "plate_number": plate,
                            "challan_id": challan,
                            "fine_amount": amt
                        },
                        customer,
                        location
                    )
                    citation_notification = send_sms(
                        type_str="CUSTOMER_CHALLAN",
                        recipient=customer["phone"],
                        message=sms_message,
                        plate_number=plate,
                        challan_id=challan
                    )
                    sent_notifications.append(citation_notification)
                except Exception as ex:
                    logger.error(f"Error sending violation citation SMS: {ex}")
            
            # Get paths
            rel_img_path = ""
            violation_id = ""
            if recorded_violations:
                violation_id = recorded_violations[-1]["violation_id"]
                rel_img_path = f"outputs/evidence/{violation_id}/annotated.jpg"
            else:
                clean_filename = f"processed_clear_{unique_filename}"
                clean_path = os.path.join(OUTPUTS_DIR, "evidence", clean_filename)
                import cv2
                cv2.imwrite(clean_path, process_result["annotated_image"])
                rel_img_path = f"outputs/evidence/{clean_filename}"
                
            print("RETURNING RESPONSE")
            return jsonify({
                "status": "success",
                "success": True,
                "processing_time_ms": process_result["processing_time_ms"],
                "detections_count": process_result["detections_count"],
                "violations": recorded_violations,
                "challan": recorded_violations[-1] if recorded_violations else {},
                "violation_id": violation_id,
                "evidence_image_path": rel_img_path,
                "annotated_image": f"/evidence/{violation_id}/annotated_full.jpg" if recorded_violations else f"/{rel_img_path.replace('outputs/', '')}",
                "original_image": f"/evidence/{violation_id}/original_full.jpg" if recorded_violations else f"/uploads/{unique_filename}",
                "detected_plate": process_result.get("detected_plate", "UNKNOWN"),
                "plate_number": process_result.get("detected_plate", "UNKNOWN"),
                "challan_id": recorded_violations[-1]["challan_id"] if recorded_violations else "NONE",
                "ocr_confidence": process_result.get("ocr_confidence", 0.0),
                "ocr_engine": process_result.get("ocr_engine", "none"),
                "ocr_debug": process_result.get("ocr_debug", {}),
                "ocr_debug_paths": process_result.get("ocr_debug_paths", {}),
                "notifications_sent": sent_notifications
            })
            
    except Exception as e:
        import traceback
        print("="*80)
        traceback.print_exc()
        print("="*80)
        logger.error(f"Failed to process uploaded file: {e}")
        return jsonify({"error": f"Internal pipeline execution error: {str(e)}"}), 500

# API: Export violations to CSV file
@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    session = SessionLocal()
    try:
        results = session.query(
            Violation, Vehicle, Challan
        ).join(
            Vehicle, Violation.vehicle_id == Vehicle.id, isouter=True
        ).join(
            Challan, Violation.id == Challan.violation_id, isouter=True
        ).order_by(
            Violation.timestamp.desc()
        ).all()
        
        # Generate CSV stream in memory
        def generate():
            data = [["Violation ID", "Challan ID", "License Plate", "Violation Type", "Fine Amount", "Timestamp", "Location", "Camera ID", "Status"]]
            for violation, vehicle, challan in results:
                data.append([
                    violation.id,
                    challan.challan_id if challan else "NONE",
                    vehicle.plate_number if vehicle else "UNKNOWN",
                    violation.violation_type,
                    challan.amount if challan else 0,
                    violation.timestamp.strftime("%Y-%m-%d %H:%M:%S") if violation.timestamp else "",
                    violation.location,
                    violation.camera_id,
                    challan.status if challan else "PENDING"
                ])
                
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerows(data)
            return output.getvalue()
            
        return Response(
            generate(),
            mimetype="text/csv",
            headers={"Content-disposition": "attachment; filename=trafficflow_violations_report.csv"}
        )
    except Exception as e:
        logger.error(f"Failed to export CSV: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# API: Export violations PDF pack
@app.route('/api/export/pdf', methods=['GET'])
def export_pdf():
    # Simulated compilation of citation PDFs for officers
    session = SessionLocal()
    try:
        count = session.query(Violation).count()
        return jsonify({
            "status": "success",
            "package_name": "TrafficFlow_Bengaluru_Evidence_Pack.pdf",
            "records_compiled": count + 4820 # Baseline + actuals
        })
    except Exception as e:
        logger.error(f"Failed to export PDF pack: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# API: Expose Safety Rules Library (Feature 5)
@app.route('/api/rules', methods=['GET'])
def get_rules():
    rules = {
        "HELMET_VIOLATION": {
            "title": "Helmet Rule",
            "section": "Section 129, Indian Motor Vehicles Act",
            "description": "Every person riding a motorcycle of any category must wear protective headgear (helmet) conforming to Indian Standards, securely fastened.",
            "fine": 1000,
            "suspension": "3 months license suspension",
            "recommendation": "Always choose an ISI-certified helmet and secure the chin strap tight. Do not buy low-quality roadside headgear."
        },
        "TRIPLE_RIDING": {
            "title": "Triple Riding Rule",
            "section": "Section 128, Indian Motor Vehicles Act",
            "description": "No driver of a two-wheeled motorcycle shall carry more than one person in addition to himself.",
            "fine": 1000,
            "suspension": "Disqualification of driving license",
            "recommendation": "Never overload a two-wheeler. Carrying more than one passenger compromises the center of gravity and increases braking distance."
        },
        "SEATBELT_VIOLATION": {
            "title": "Seatbelt Rule",
            "section": "Section 138(3), Central Motor Vehicles Rules",
            "description": "The driver and the passengers sitting in the front seat or the forward facing seats must wear seat belts while the vehicle is in motion.",
            "fine": 1000,
            "recommendation": "Seatbelts reduce the risk of death by 45% in crashes. Buckle up before you start the ignition, regardless of how short the journey."
        },
        "ILLEGAL_PARKING": {
            "title": "Illegal Parking Rule",
            "section": "Section 122, Indian Motor Vehicles Act",
            "description": "No person in charge of a motor vehicle shall cause or allow the vehicle to remain at rest in a public place in a way that causes danger, obstruction or inconvenience.",
            "fine": 1000,
            "tow_charge": "Actual vehicle towing charges apply extra",
            "recommendation": "Always park in designated BBMP municipal zones. Avoid blocking intersections, yellow curves, or footpath zones."
        },
        "TRAFFIC_SIGNAL_RULE": {
            "title": "Traffic Signal Rule",
            "section": "Section 119, Indian Motor Vehicles Act",
            "description": "Every driver of a motor vehicle must obey the directions given by traffic signs, traffic signals, and police officers in charge of traffic control.",
            "fine": 1000,
            "consequence": "Imprisonment for repeated offenses",
            "recommendation": "Red means stop completely before the white stop-line. Never cross when the timer reads less than 3 seconds. Yellow is for stopping, not speeding up."
        },
        "WRONG_SIDE_DRIVING": {
            "title": "Wrong Side Driving Rule",
            "section": "Section 184, Indian Motor Vehicles Act (Dangerous Driving)",
            "description": "Driving a motor vehicle in a manner or direction which is dangerous to the public, including driving against the traffic flow direction.",
            "fine": 5000,
            "imprisonment": "Up to 6 months imprisonment for first offense",
            "recommendation": "Always follow the lane direction markings. Do not drive on the wrong side to save fuel or take a short-cut."
        },
        "RED_LIGHT_VIOLATION": {
            "title": "Red-Light Violation Rule",
            "section": "Section 119/177, Indian Motor Vehicles Act",
            "description": "No driver shall cross the stop-line or enter the intersection when the traffic signal displays a red light. Violations carry a fine of ₹1,000 to ₹5,000 or imprisonment up to 6 months, or both.",
            "fine": 10000,
            "imprisonment": "Up to 6 months for repeated offenses",
            "recommendation": "Always stop before the white stop-line when the signal turns red. Do not accelerate during yellow — it means prepare to stop, not speed up."
        },
        "STOP_LINE_VIOLATION": {
            "title": "Stop-Line Violation Rule",
            "section": "Section 119/177, Indian Motor Vehicles Act",
            "description": "Drivers must stop before the marked stop line at controlled junctions and pedestrian crossings. Crossing the line blocks pedestrians and creates collision risk at the intersection mouth.",
            "fine": 1000,
            "imprisonment": "Escalation for repeated dangerous driving offenses",
            "recommendation": "Keep the front bumper behind the white stop line until the signal and crossing are clear."
        }
    }
    return jsonify(rules)

# API: YouTube Links Configuration (Feature 4)
@app.route('/api/video_links', methods=['GET', 'POST'])
def handle_video_links():
    links_path = os.path.join(PROJECT_ROOT, "video_links.json")
    if request.method == 'POST':
        try:
            data = request.json
            with open(links_path, 'w') as f:
                json.dump(data, f, indent=2)
            return jsonify({"status": "success", "message": "Video links updated successfully."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        try:
            if os.path.exists(links_path):
                with open(links_path, 'r') as f:
                    return jsonify(json.load(f))
            else:
                return jsonify([])
        except Exception as e:
            return jsonify({"error": str(e)}), 500

# API: Record Video View Transactions (Feature 7)
@app.route('/api/video_views', methods=['POST'])
def add_video_view():
    try:
        data = request.json or {}
        video_id = data.get("video_id")
        video_title = data.get("video_title")
        category = data.get("category")
        watch_duration = float(data.get("watch_duration", 0.0))
        completion_percentage = float(data.get("completion_percentage", 0.0))
        
        if not video_id or not video_title or not category:
            return jsonify({"error": "Missing video_id, video_title, or category"}), 400
            
        session = SessionLocal()
        view_id = str(uuid.uuid4())
        watch_timestamp = datetime.now()
        view = SafetyVideoView(
            id=view_id,
            video_id=video_id,
            video_title=video_title,
            category=category,
            watch_timestamp=watch_timestamp,
            watch_duration=watch_duration,
            completion_percentage=completion_percentage
        )
        session.add(view)
        session.commit()
        session.close()
        return jsonify({"status": "success", "view_id": view_id, "watch_timestamp": watch_timestamp.strftime("%Y-%m-%d %H:%M:%S")})
    except Exception as e:
        logger.error(f"Failed to record video view: {e}")
        return jsonify({"error": str(e)}), 500

# API: Video Analytics calculations (Feature 7 - backward compatibility)
@app.route('/api/video_analytics', methods=['GET'])
def get_video_analytics():
    session = SessionLocal()
    try:
        # 1. Total watched
        total_watched = session.query(SafetyVideoView).count()
        
        # 2. Most viewed category
        row_cat = session.query(
            SafetyVideoView.category, func.count(SafetyVideoView.id).label('count')
        ).group_by(SafetyVideoView.category).order_by(func.count(SafetyVideoView.id).desc()).first()
        most_viewed_cat = row_cat.category if row_cat else "None"
        
        # 3. Most common violation
        row_violation = session.query(
            Violation.violation_type, func.count(Violation.id).label('count')
        ).group_by(Violation.violation_type).order_by(func.count(Violation.id).desc()).first()
        most_common_violation = row_violation.violation_type if row_violation else "None"
        
        # 4. Safety Awareness Score (computed based on average category completion)
        category_completion = session.query(
            SafetyVideoView.category, func.max(SafetyVideoView.completion_percentage).label('max_completion')
        ).group_by(SafetyVideoView.category).all()
        
        video_completion_sum = sum(min(100.0, float(c.max_completion or 0.0)) for c in category_completion)
        overall_video_completion = video_completion_sum / 7.0 if category_completion else 0.0
        
        # Base score representing average video watch percentage + placeholder default
        safety_score = min(100, int(overall_video_completion * 0.5 + 40))
        
        return jsonify({
            "total_videos_watched": total_watched,
            "most_viewed_category": most_viewed_cat,
            "most_common_violation": most_common_violation,
            "safety_awareness_score": safety_score
        })
    except Exception as e:
        logger.error(f"Failed to compute video analytics: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# API: Advanced Safety and Citizen Awareness Analytics (New)
@app.route('/api/safety_analytics', methods=['GET'])
def get_safety_analytics_advanced():
    session = SessionLocal()
    try:
        # 1. Total videos watched
        total_watched = session.query(SafetyVideoView).count()
        
        # 2. Total watch time in seconds
        total_duration = session.query(func.sum(SafetyVideoView.watch_duration)).scalar() or 0.0
        
        # Convert total duration to readable string e.g. "2h 15m 10s" or "45m 12s"
        total_seconds = int(total_duration)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        if hours > 0:
            watch_time_str = f"{hours}h {minutes}m {seconds}s"
        else:
            watch_time_str = f"{minutes}m {seconds}s"
            
        # 3. Most viewed videos (group by video_title)
        video_views = session.query(
            SafetyVideoView.video_title,
            SafetyVideoView.category,
            func.count(SafetyVideoView.id).label('count')
        ).group_by(SafetyVideoView.video_title, SafetyVideoView.category).order_by(func.count(SafetyVideoView.id).desc()).all()
        
        most_viewed_videos = []
        for title, cat, count in video_views:
            most_viewed_videos.append({
                "video_title": title,
                "category": cat,
                "view_count": count
            })
            
        # 4. Most popular categories
        cat_views = session.query(
            SafetyVideoView.category,
            func.count(SafetyVideoView.id).label('count')
        ).group_by(SafetyVideoView.category).order_by(func.count(SafetyVideoView.id).desc()).all()
        
        most_popular_categories = []
        for cat, count in cat_views:
            most_popular_categories.append({
                "category": cat,
                "view_count": count
            })
            
        # 5. Completed categories details
        completed_rows = session.query(
            SafetyVideoView.category,
            func.max(SafetyVideoView.completion_percentage).label('max_comp')
        ).group_by(SafetyVideoView.category).all()
        
        completed_categories = []
        video_completion_sum = 0.0
        
        for cat, max_comp in completed_rows:
            comp_val = float(max_comp or 0.0)
            video_completion_sum += min(100.0, comp_val)
            if comp_val >= 90.0:
                completed_categories.append(cat)
                
        # Overall video completion percentage (max 100)
        overall_video_completion = video_completion_sum / 7.0 if completed_rows else 0.0
        
        # 6. Education vs Violation Trends by camera ward/location
        loc_violations = session.query(
            Violation.location, func.count(Violation.id).label('count')
        ).group_by(Violation.location).all()
        violations_map = {loc.split(",")[0].strip(): count for loc, count in loc_violations}
        
        all_wards = [
            "Silk Board", "Whitefield", "Electronic City", "Marathahalli", 
            "Hebbal", "KR Puram", "Koramangala", "HSR Layout", "Majestic", "Yelahanka"
        ]
        
        awareness_trends = []
        for idx, ward in enumerate(all_wards):
            # Calculate actual violations count from DB
            v_count = violations_map.get(ward, 0)
            
            # Formulate simulated awareness rate that is negatively correlated with violation count
            import random
            random.seed(idx + 100)
            if v_count >= 100:
                awareness_rate = random.randint(25, 45)
            elif v_count >= 50:
                awareness_rate = random.randint(46, 68)
            elif v_count >= 20:
                awareness_rate = random.randint(69, 84)
            else:
                awareness_rate = random.randint(85, 96)
                
            # Simulated violation reduction rate (due to safety education campaigns)
            reduction_rate = max(5, min(95, int(awareness_rate * 0.85 + random.randint(-5, 5))))
            
            awareness_trends.append({
                "location": ward,
                "violation_count": v_count,
                "awareness_rate": awareness_rate,
                "reduction_percentage": reduction_rate
            })
            
        # Sort awareness trends by awareness_rate descending
        awareness_trends.sort(key=lambda x: x["awareness_rate"], reverse=True)
        
        return jsonify({
            "total_videos_watched": total_watched,
            "total_watch_time": total_duration,
            "total_watch_time_formatted": watch_time_str,
            "most_viewed_videos": most_viewed_videos,
            "most_popular_categories": most_popular_categories,
            "completed_categories": completed_categories,
            "completed_categories_count": len(completed_categories),
            "video_completion_rate": round(overall_video_completion, 1),
            "category_completion": {cat: float(max_comp or 0.0) for cat, max_comp in completed_rows},
            "awareness_trends": awareness_trends
        })
    except Exception as e:
        logger.error(f"Failed to fetch safety analytics: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# API: Challan details route
@app.route('/challan/<challan_id>')
def challan_details(challan_id):
    session = SessionLocal()
    try:
        row = session.query(
            Violation, Vehicle, Challan, OCRResult
        ).join(
            Challan, Violation.id == Challan.violation_id
        ).join(
            Vehicle, Violation.vehicle_id == Vehicle.id, isouter=True
        ).join(
            OCRResult, Violation.id == OCRResult.violation_id, isouter=True
        ).filter(
            Challan.challan_id == challan_id
        ).first()
        
        if not row:
            return "Challan Not Found", 404
            
        violation, vehicle, challan, ocr_result = row
        v_dict = {
            "id": violation.id,
            "violation_id": violation.id,
            "challan_id": challan.challan_id,
            "plate_number": vehicle.plate_number if vehicle else "UNKNOWN",
            "violation_type": violation.violation_type,
            "amount": challan.amount,
            "timestamp": violation.timestamp.strftime("%Y-%m-%d %H:%M:%S") if violation.timestamp else "",
            "location": violation.location,
            "camera_id": violation.camera_id,
            "status": challan.status,
            "evidence_path": violation.evidence_path,
            "confidence": violation.confidence,
            "ocr_confidence": ocr_result.ocr_confidence if ocr_result else 0.0,
            
            "owner_name": vehicle.owner_name if vehicle else "Vehicle Owner",
            "owner_phone": vehicle.owner_phone if vehicle else "+919876543210"
        }
        return render_template('challan.html', challan=v_dict)
    except Exception as e:
        logger.error(f"Failed to fetch challan details: {e}")
        return "Internal Error", 500
    finally:
        session.close()

# API: Pay Challan (Razorpay Standard Mock Checkout Integration)
@app.route('/api/pay_challan', methods=['POST'])
def pay_challan():
    try:
        data = request.json or {}
        challan_id = data.get("challan_id")
        if not challan_id:
            return jsonify({"error": "Missing challan_id"}), 400
            
        session = SessionLocal()
        challan_record = session.query(Challan).filter_by(challan_id=challan_id).first()
        if not challan_record:
            session.close()
            return jsonify({"error": "Challan not found"}), 404
            
        violation = session.query(Violation).filter_by(id=challan_record.violation_id).first()
        vehicle = session.query(Vehicle).filter_by(id=violation.vehicle_id).first() if violation else None
        
        plate_number = vehicle.plate_number if vehicle else "UNKNOWN"
        amount = challan_record.amount
        location = violation.location if violation else "UNKNOWN"
        violation_type = violation.violation_type if violation else "VIOLATION"
        
        # Update status
        challan_record.status = 'PAID'
        
        # Record payment transaction
        payment_id = f"PAY-{str(uuid.uuid4())[:8]}"
        payment = Payment(
            payment_id=payment_id,
            challan_id=challan_id,
            amount=amount,
            timestamp=datetime.now(),
            status="SUCCESS"
        )
        session.add(payment)
        session.commit()
        session.close()
        
        # Resolve owner contact
        customer = resolve_customer_contact(plate_number)
        recipient = customer["phone"]
        
        # Build success message & trigger mock SMS notification
        msg = f"Receipt for Challan {challan_id}: Payment of INR {amount} received for vehicle {plate_number} ({violation_type} at {location}). Thank you for driving safely!"
        noti = send_sms("PAYMENT_RECEIPT", recipient, msg, plate_number, challan_id)
        
        return jsonify({
            "status": "success",
            "message": "Challan paid successfully",
            "notification": noti
        })
    except Exception as e:
        logger.error(f"Failed to pay challan: {e}")
        return jsonify({"error": str(e)}), 500

# API: Update/Correct License Plate Registration
@app.route('/api/challan/<challan_id>/update_plate', methods=['POST'])
def update_challan_plate(challan_id):
    try:
        data = request.json or {}
        new_plate = data.get("plate_number")
        if not new_plate:
            return jsonify({"error": "Missing plate_number"}), 400
        
        new_plate = new_plate.strip().upper()
        if not new_plate:
            return jsonify({"error": "Invalid plate_number"}), 400
            
        session = SessionLocal()
        challan_record = session.query(Challan).filter_by(challan_id=challan_id).first()
        if not challan_record:
            session.close()
            return jsonify({"error": "Challan not found"}), 404
            
        violation = session.query(Violation).filter_by(id=challan_record.violation_id).first()
        if not violation:
            session.close()
            return jsonify({"error": "Associated violation not found"}), 404
            
        old_vehicle = violation.vehicle
        old_plate = old_vehicle.plate_number if old_vehicle else None

        # Find or create Vehicle
        vehicle = session.query(Vehicle).filter_by(plate_number=new_plate).first()
        if not vehicle:
            contact = VEHICLE_CONTACTS.get(new_plate, VEHICLE_CONTACTS.get("DEFAULT", {}))
            vehicle = Vehicle(
                plate_number=new_plate,
                owner_name=contact.get("name", "Vehicle Owner"),
                owner_phone=contact.get("phone", "+919876543210")
            )
            session.add(vehicle)
            session.flush() # Get vehicle.id
            
        # Update violation vehicle association
        violation.vehicle_id = vehicle.id
        
        # Update RepeatOffender table for the new plate
        new_count = session.query(Violation).filter_by(vehicle_id=vehicle.id).count()
        latest_violation = session.query(Violation).filter_by(vehicle_id=vehicle.id).order_by(Violation.timestamp.desc()).first()
        latest_v_type = latest_violation.violation_type if latest_violation else "VIOLATION"
        
        offender = session.query(RepeatOffender).filter_by(plate_number=new_plate).first()
        if offender:
            offender.violations_count = new_count
            offender.last_violation = latest_v_type
            offender.blacklist_status = "BLACKLISTED" if new_count >= 3 else "WARNING"
        else:
            offender = RepeatOffender(
                plate_number=new_plate,
                violations_count=new_count,
                last_violation=latest_v_type,
                blacklist_status="WARNING"
            )
            session.add(offender)

        # Update RepeatOffender table for the old plate (if any)
        if old_vehicle and old_plate and old_plate != new_plate:
            old_count = session.query(Violation).filter_by(vehicle_id=old_vehicle.id).count()
            old_offender = session.query(RepeatOffender).filter_by(plate_number=old_plate).first()
            if old_offender:
                if old_count == 0:
                    session.delete(old_offender)
                else:
                    latest_old_violation = session.query(Violation).filter_by(vehicle_id=old_vehicle.id).order_by(Violation.timestamp.desc()).first()
                    latest_old_v_type = latest_old_violation.violation_type if latest_old_violation else "VIOLATION"
                    old_offender.violations_count = old_count
                    old_offender.last_violation = latest_old_v_type
                    old_offender.blacklist_status = "BLACKLISTED" if old_count >= 3 else "WARNING"

        # Update EvidencePackage table
        evidence_pkg = session.query(EvidencePackage).filter_by(violation_id=violation.id).first()
        if evidence_pkg:
            try:
                ocr_results = json.loads(evidence_pkg.ocr_results)
                ocr_results["plate_number"] = new_plate
                evidence_pkg.ocr_results = json.dumps(ocr_results)
            except Exception as ocr_err:
                logger.error(f"Failed to update EvidencePackage ocr_results: {ocr_err}")
                
        session.commit()
        session.close()
        
        # Clear API caches so dashboard updates instantly
        _cache_store.clear()
        _cache_timestamps.clear()

        # Update challan.json file on disk
        package_dir = os.path.join(OUTPUTS_DIR, "evidence", violation.id)
        json_path = os.path.join(package_dir, "challan.json")
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    challan_json = json.load(f)
                challan_json["plate_number"] = new_plate
                with open(json_path, 'w') as f:
                    json.dump(challan_json, f, indent=4)
            except Exception as file_err:
                logger.error(f"Failed to update challan.json on disk: {file_err}")
                
        # Regenerate PDF challan on disk
        pdf_path = os.path.join(PROJECT_ROOT, "challans", f"{challan_id}.pdf")
        if evidence_engine and os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    updated_json = json.load(f)
                pdf_evidence_img = os.path.join(package_dir, "annotated.jpg")
                evidence_engine._generate_pdf(challan_id, updated_json, pdf_evidence_img, pdf_path)
            except Exception as pdf_err:
                logger.error(f"Failed to regenerate PDF Challan: {pdf_err}")
                
        return jsonify({
            "status": "success",
            "message": "Plate number updated successfully",
            "plate_number": new_plate
        })
    except Exception as e:
        logger.error(f"Failed to update plate number: {e}")
        return jsonify({"error": str(e)}), 500


# API: Dispatch Patrol Unit (simulates dispatch alerts and Twilio notifications)
@app.route('/api/dispatch', methods=['POST'])
def dispatch_patrol():
    try:
        data = request.json or {}
        location = data.get("location")
        action = data.get("action", "Surveillance coverage")
        camera_id = data.get("camera_id", "CAM_BLR_001")
        
        if not location:
            return jsonify({"error": "Missing location"}), 400
            
        session = SessionLocal()
        dispatch_id = str(uuid.uuid4())
        timestamp = datetime.now()
        status_msg = f"Patrol unit dispatched to {location}: {action}"
        
        # Write to PoliceAlert
        alert = PoliceAlert(
            alert_id=dispatch_id,
            location=location,
            severity="HIGH",
            timestamp=timestamp,
            status=status_msg
        )
        session.add(alert)
        
        # Write to PatrolDispatch
        dispatch = PatrolDispatch(
            dispatch_id=dispatch_id,
            location=location,
            action=action,
            camera_id=camera_id,
            timestamp=timestamp,
            status=status_msg
        )
        session.add(dispatch)
        
        session.commit()
        session.close()
        
        # Send dispatch SMS
        sms_msg = f"🚨 BTP DISPATCH: Patrol unit deployed to {location} node for urgent action: {action}."
        noti = send_sms("PATROL_DISPATCH", "+919900000000", sms_msg)
        
        return jsonify({
            "status": "success",
            "alert_id": dispatch_id,
            "message": status_msg,
            "notification": noti
        })
    except Exception as e:
        logger.error(f"Failed to dispatch patrol: {e}")
        return jsonify({"error": str(e)}), 500

# API: Repeat Offender Analytics (Phase 6)
@app.route('/api/repeat_offenders', methods=['GET'])
@api_cache(timeout=300)
def get_repeat_offenders_api():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
    try:
        offenders = analytics_engine.get_repeat_offenders()
        return jsonify(offenders)
    except Exception as e:
        logger.error(f"Failed to fetch repeat offenders: {e}")
        return jsonify({"error": str(e)}), 500

# API: Active Deployed Patrols Board (Phase 7 — shows dispatched officer locations)
@app.route('/api/deployed_patrols', methods=['GET'])
@api_cache(timeout=300)
def get_deployed_patrols():
    session = SessionLocal()
    try:
        results = session.query(PatrolDispatch).order_by(
            PatrolDispatch.timestamp.desc()
        ).limit(20).all()
        
        deployed = []
        for row in results:
            deployed.append({
                "location": row.location,
                "severity": "HIGH",
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S") if row.timestamp else "",
                "status": row.status,
                "alert_id": row.dispatch_id
            })
        return jsonify({"deployed": deployed, "count": len(deployed)})
    except Exception as e:
        logger.error(f"Failed to fetch deployed patrols: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        session.close()

# API: Police patrol deployment recommendation engine
@app.route('/api/recommendations', methods=['GET'])
@api_cache(timeout=300)
def get_recommendations():
    if analytics_engine is None:
        return jsonify({"error": "Analytics Engine unavailable"}), 500
    hotspots = analytics_engine.get_violation_hotspots()
    
    # Query database for dispatched locations
    dispatched_locations = set()
    session = SessionLocal()
    try:
        results = session.query(PatrolDispatch.location).distinct().all()
        dispatched_locations = {r[0] for r in results}
    except Exception as db_err:
        logger.error(f"Failed to query dispatched locations: {db_err}")
    finally:
        session.close()

    recommendations = []
    for h in hotspots:
        density = h["avg_density"]
        v_count = h["violation_count"]
        score = h["hotspot_score"]
        loc = h["location"]
        
        # Dynamic recommended officers
        if score > 50:
            officers = 3
        elif score > 25:
            officers = 2
        else:
            officers = 1
            
        status = "DISPATCHED" if loc in dispatched_locations else "PENDING_DEPLOYMENT"
            
        recommendations.append({
            "camera_id": h["camera_id"],
            "location": loc,
            "risk_score": score,
            "risk_level": h["risk_level"],
            "traffic_density": density,
            "violation_count": v_count,
            "officers_recommended": officers,
            "suggested_action": h["action"],
            "status": status
        })
    return jsonify(recommendations)

# API: Predictive violation probabilities and traffic forecasting
@app.route('/api/predictions', methods=['GET'])
def get_predictions():
    now = datetime.now()
    forecasts = []
    locations = list(CAMERA_LOCATIONS.values())
    if not locations:
        locations = ["Silk Board", "Whitefield", "Electronic City"]
        
    for i in range(6):
        future_time = now + timedelta(hours=i)
        hour_str = future_time.strftime("%H:00")
        hour = future_time.hour
        risk_factors = ["HELMET_VIOLATION", "WRONG_SIDE_DRIVING", "STOP_LINE_VIOLATION"]
        
        # Deterministic simulation peaking around rush hours (9 AM & 6 PM)
        dist_9 = abs(hour - 9)
        dist_18 = abs(hour - 18)
        min_dist = min(dist_9, dist_18)
        base_prob = 0.15 + 0.65 * max(0, (1.0 - min_dist / 6.0))
        congestion_idx = 30 + int(60 * max(0, (1.0 - min_dist / 6.0)))
        
        forecasts.append({
            "time": hour_str,
            "violation_probability": round(max(0.05, min(0.95, base_prob)), 2),
            "congestion_index": max(10, min(100, congestion_idx)),
            "primary_risk_factor": risk_factors[hour % len(risk_factors)]
        })
        
    return jsonify({
        "status": "success",
        "forecast": forecasts,
        "insights": {
            "peak_hour": "18:00 - 19:00",
            "highest_probability_location": locations[0] if locations else "Silk Board",
            "recommended_surveillance_alert": "Increase CCTV scanning density in zone " + (locations[0] if locations else "Silk Board"),
            "system_status": "STABLE"
        }
    })

# API: AI Traffic Assistant Chatbot with PostgreSQL query integration
@app.route('/api/ai_assistant', methods=['POST'])
def ai_assistant():
    try:
        data = request.json or {}
        query = data.get("query", "").lower().strip()
        if not query:
            return jsonify({"response": "Hello Officer! How can I assist you with Bengaluru Traffic Intelligence today?"})
            
        session = SessionLocal()
        response_text = ""
        
        if "unpaid" in query or "pending" in query:
            cnt = session.query(Challan).filter_by(status='PENDING').count()
            revenue = session.query(func.sum(Challan.amount)).filter_by(status='PENDING').scalar() or 0
            response_text = f"There are currently **{cnt} pending unpaid challans** in the system, totaling **INR {revenue}** in unpaid fines."
            
        elif "paid" in query:
            cnt = session.query(Challan).filter_by(status='PAID').count()
            revenue = session.query(func.sum(Challan.amount)).filter_by(status='PAID').scalar() or 0
            response_text = f"A total of **{cnt} challans have been paid** successfully, generating **INR {revenue}** in traffic enforcement revenue."
            
        elif "helmet" in query:
            cnt = session.query(Violation).filter_by(violation_type='HELMET_VIOLATION').count()
            response_text = f"Our AI models have detected **{cnt} Helmet Violations** across all monitored intersections."

        elif "stop line" in query or "stop-line" in query or "stopline" in query:
            cnt = session.query(Violation).filter_by(violation_type='STOP_LINE_VIOLATION').count()
            response_text = f"Our AI models have detected **{cnt} Stop-Line Violations** across all monitored intersections."
            
        elif "silk" in query or "board" in query:
            cnt = session.query(Violation).filter(Violation.location.like('%Silk Board%')).count()
            pending = session.query(Challan).join(Violation).filter(Violation.location.like('%Silk Board%'), Challan.status == 'PENDING').count()
            response_text = f"**Silk Board Junction** has recorded **{cnt} total violations**, with **{pending}** still pending payment resolution."
            
        elif "total" in query or "count" in query or "how many violations" in query:
            cnt = session.query(Violation).count()
            response_text = f"The TrafficFlow database currently registers a total of **{cnt} infraction events** across Bengaluru."
            
        elif "fine" in query or "revenue" in query or "amount" in query:
            total = session.query(func.sum(Challan.amount)).scalar() or 0
            paid = session.query(func.sum(Challan.amount)).filter_by(status='PAID').scalar() or 0
            response_text = f"The total fines levied amount to **INR {total}**, out of which **INR {paid}** has been recovered (paid)."
            
        elif "repeat" in query or "offender" in query:
            rows = session.query(RepeatOffender).filter(RepeatOffender.plate_number != 'UNKNOWN').order_by(RepeatOffender.violations_count.desc()).limit(3).all()
            if rows:
                list_str = ", ".join([f"**{r.plate_number}** ({r.violations_count} times)" for r in rows])
                response_text = f"Top repeat offenders detected: {list_str}."
            else:
                response_text = "No repeat offenders currently identified with multiple violations."
                
        else:
            response_text = (
                "I can query database statistics for you! Try asking questions like:\n"
                "- *'How many unpaid/pending challans do we have?'*\n"
                "- *'List violations at Silk Board Junction.'*\n"
                "- *'What is our total revenue collected?'*\n"
                "- *'How many helmet violations were recorded?'*\n"
                "- *'Show repeat offenders.'*"
            )
            
        session.close()
        return jsonify({"response": response_text})
    except Exception as e:
        logger.error(f"Error in AI assistant query processing: {e}")
        return jsonify({"response": f"Error running query helper: {str(e)}"})

import threading
import time

def start_cache_warming_thread(app_instance):
    def run_warming():
        logger.info("Background cache warming thread started.")
        # Wait 3 seconds to let Flask server bind and initialize completely
        time.sleep(3)
        
        while True:
            try:
                with app_instance.app_context():
                    logger.info("Warming API caches from PostgreSQL database...")
                    t0 = time.time()
                    
                    # Force executes and caches Flask GET handlers under app_context
                    get_metrics()
                    get_charts()
                    get_analytics_details()
                    get_command_center()
                    get_detailed_charts()
                    get_logs()
                    get_repeat_offenders_api()
                    get_deployed_patrols()
                    get_recommendations()
                    get_evaluation_details()
                    
                    logger.info(f"API caches warmed successfully in {time.time() - t0:.2f} seconds.")
            except Exception as e:
                logger.error(f"Error in background cache warming: {e}")
            
            # Refresh every 30 seconds
            time.sleep(30)
            
    t = threading.Thread(target=run_warming, daemon=True)
    t.start()

if __name__ == '__main__':
    # Start cache warming thread
    start_cache_warming_thread(app)
    # Initialize port and host for developer binding, disable reloader to avoid conflict when writing evidence files
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True, use_reloader=False)
