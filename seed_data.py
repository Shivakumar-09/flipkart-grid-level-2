import os
import json
import uuid
import sqlite3
import shutil
from datetime import datetime, timedelta
import random
import cv2
import numpy as np
from engine.evidence_engine import EvidenceEngine

def seed():
    print("=== TrafficFlow Smart City Seeding Engine ===")
    
    # Load camera locations
    with open("camera_locations.json", "r") as f:
        cam_locs = json.load(f)
        
    db_path = "database/trafficflow.db"
    
    # Recreate tables to clear any old records
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    tables = ["violations", "notifications", "alerts", "analytics", "video_views"]
    for t in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {t}")
        
    # Recreate tables
    cursor.execute("""
        CREATE TABLE violations (
            id TEXT PRIMARY KEY,
            challan_id TEXT NOT NULL UNIQUE,
            plate_number TEXT,
            violation_type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            location TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            status TEXT DEFAULT 'PENDING',
            evidence_path TEXT NOT NULL,
            confidence REAL NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE notifications (
            notification_id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            recipient TEXT NOT NULL,
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            message TEXT,
            plate_number TEXT,
            challan_id TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE alerts (
            alert_id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            severity TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            status TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE analytics (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            traffic_density REAL NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE video_views (
            id TEXT PRIMARY KEY,
            video_id TEXT NOT NULL,
            category TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    
    # Clear and recreate output directories
    evidence_dir = os.path.join("outputs", "evidence")
    challans_dir = "challans"
    
    if os.path.exists(evidence_dir):
        shutil.rmtree(evidence_dir)
    if os.path.exists(challans_dir):
        shutil.rmtree(challans_dir)
        
    os.makedirs(evidence_dir, exist_ok=True)
    os.makedirs(challans_dir, exist_ok=True)
    
    # Initialize EvidenceEngine
    ee = EvidenceEngine(db_path=db_path)
    
    # Setup baseline mock image
    fallback_img = "outputs/vehicle_crop.jpg"
    if not os.path.exists(fallback_img):
        # Create a small blank image as fallback
        blank_img = np.zeros((300, 500, 3), dtype=np.uint8)
        cv2.putText(blank_img, "TrafficFlow Evidence Frame", (20, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        os.makedirs("outputs", exist_ok=True)
        cv2.imwrite(fallback_img, blank_img)
    
    # Generate one master PDF to copy (for speed)
    temp_v_id = str(uuid.uuid4())
    master_challan_id = "CHN-2026-00000"
    master_json = {
        "violation_id": temp_v_id,
        "challan_id": master_challan_id,
        "plate_number": "KA03MM8812",
        "violation_type": "HELMET_VIOLATION",
        "date": "2026-06-17",
        "time": "12:00:00",
        "location": "Silk Board, Bengaluru",
        "camera_id": "CAM_BLR_001",
        "confidence_score": 0.95,
        "fine_amount": 1000,
        "status": "PENDING"
    }
    master_pdf_path = os.path.join(challans_dir, "master.pdf")
    ee._generate_pdf(master_challan_id, master_json, fallback_img, master_pdf_path)
    
    # Core target violation counts to trigger exact color code ranges:
    # Green (0-20), Yellow (21-50), Orange (51-100), Red (100+)
    location_targets = {
        "CAM_BLR_001": 125, # Silk Board - Red
        "CAM_BLR_002": 115, # Whitefield - Red
        "CAM_BLR_003": 105, # Electronic City - Red
        "CAM_BLR_004": 85,  # Marathahalli - Orange
        "CAM_BLR_005": 72,  # Hebbal - Orange
        "CAM_BLR_006": 102, # KR Puram - Red
        "CAM_BLR_007": 18,  # Koramangala - Green
        "CAM_BLR_008": 32,  # HSR Layout - Yellow
        "CAM_BLR_009": 45,  # Majestic - Yellow
        "CAM_BLR_010": 12   # Yelahanka - Green
    }
    
    violation_types = ["HELMET_VIOLATION", "TRIPLE_RIDING", "WRONG_SIDE_DRIVING", "ILLEGAL_PARKING", "SEATBELT_VIOLATION"]
    
    # Pre-defined plates (some repeat offenders, some unique)
    repeat_plates = {
        "KA03MM8812": 18,
        "KA51HA0492": 15,
        "KA01AB7734": 12,
        "KA05XY1234": 10,
        "KA04CD5678": 8,
        "KA53EQ9011": 8,
        "KA02GH3456": 6,
        "KA09JK7890": 5
    }
    
    plates_pool = []
    for plate, cnt in repeat_plates.items():
        plates_pool.extend([plate] * cnt)
    
    # Fill up with random plates
    random.seed(42)
    for _ in range(1000):
        plates_pool.append(f"KA{random.randint(10,99)}{chr(random.randint(65,90))}{chr(random.randint(65,90))}{random.randint(1000,9999)}")
        
    start_date = datetime(2026, 6, 1)
    
    print("Seeding violations table...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    total_violations_inserted = 0
    
    # We will generate sequential challans
    challan_index = 1
    
    for cam_id, target_count in location_targets.items():
        loc = cam_locs[cam_id]
        
        for i in range(target_count):
            v_id = str(uuid.uuid4())
            challan_id = f"CHN-2026-{challan_index:05d}"
            
            # Draw a plate from pool
            plate = plates_pool[challan_index % len(plates_pool)]
            # Assign violation type
            v_type = violation_types[challan_index % len(violation_types)]
            amount = ee._get_fine_amount(v_type)
            conf = round(random.uniform(0.82, 0.98), 2)
            
            # Timestamps: span June 1 to June 17, 2026
            # Distribute hours so peak hour is 17:00 - 19:00
            days_offset = random.randint(0, 16)
            
            # Focus on Peak hours
            if random.random() < 0.4:
                hour = random.choice([17, 18, 19])
            else:
                hour = random.randint(0, 23)
                
            minute = random.randint(0, 59)
            second = random.randint(0, 59)
            
            ts_datetime = start_date + timedelta(days=days_offset, hours=hour, minutes=minute, seconds=second)
            timestamp_str = ts_datetime.strftime("%Y-%m-%d %H:%M:%S")
            
            # Setup folders
            package_dir = os.path.join(evidence_dir, v_id)
            os.makedirs(package_dir, exist_ok=True)
            
            # Copy fallback images for original/annotated (very fast copy)
            shutil.copy(fallback_img, os.path.join(package_dir, "annotated.jpg"))
            shutil.copy(fallback_img, os.path.join(package_dir, "original.jpg"))
            
            # Create plate placeholder
            mock_plate = np.zeros((40, 120, 3), dtype=np.uint8)
            cv2.rectangle(mock_plate, (0, 0), (120, 40), (255, 255, 255), -1)
            cv2.putText(mock_plate, plate, (5, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 2)
            cv2.imwrite(os.path.join(package_dir, "plate_crop.jpg"), mock_plate)
            
            # Generate challan.json
            challan_json = {
                "violation_id": v_id,
                "challan_id": challan_id,
                "plate_number": plate,
                "violation_type": v_type,
                "type": v_type,
                "details": f"{v_type.replace('_', ' ').title()} recorded",
                "date": timestamp_str.split(" ")[0],
                "time": timestamp_str.split(" ")[1],
                "location": loc,
                "camera_id": cam_id,
                "confidence_score": conf,
                "fine_amount": amount,
                "status": "PENDING"
            }
            
            with open(os.path.join(package_dir, "challan.json"), 'w') as json_f:
                json.dump(challan_json, json_f, indent=4)
                
            # Copy PDF from master (much faster than rendering 700 ReportLab canvases)
            shutil.copy(master_pdf_path, os.path.join(challans_dir, f"{challan_id}.pdf"))
            
            # Insert record
            rel_evidence_path = f"outputs/evidence/{v_id}"
            cursor.execute("""
                INSERT INTO violations (
                    id, challan_id, plate_number, violation_type, 
                    amount, timestamp, location, camera_id, status, 
                    evidence_path, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (v_id, challan_id, plate, v_type, amount, timestamp_str, loc, cam_id, "PENDING", rel_evidence_path, conf))
            
            challan_index += 1
            total_violations_inserted += 1
            
    conn.commit()
    print(f"[OK] Seeded {total_violations_inserted} violations.")
    
    # Remove the master temp PDF
    if os.path.exists(master_pdf_path):
        os.remove(master_pdf_path)
        
    # Seed analytics table (continuous hourly records for the last 7 days)
    # 10 cameras * 24 hours * 7 days = 1680 logs
    print("Seeding analytics (traffic density) table...")
    
    # Baseline densities for locations
    loc_base_densities = {
        "CAM_BLR_001": 8.0, # Silk Board
        "CAM_BLR_002": 7.5, # Whitefield
        "CAM_BLR_003": 7.0, # Electronic City
        "CAM_BLR_004": 6.5, # Marathahalli
        "CAM_BLR_005": 6.0, # Hebbal
        "CAM_BLR_006": 7.2, # KR Puram
        "CAM_BLR_007": 3.5, # Koramangala
        "CAM_BLR_008": 4.0, # HSR Layout
        "CAM_BLR_009": 5.5, # Majestic
        "CAM_BLR_010": 2.0  # Yelahanka
    }
    
    analytics_count = 0
    end_date = datetime(2026, 6, 17)
    
    for cam_id, base_density in loc_base_densities.items():
        loc = cam_locs[cam_id]
        
        # Seed hourly logs for past 7 days
        for day in range(7):
            current_day = end_date - timedelta(days=day)
            is_weekend = current_day.weekday() >= 5
            
            for hour in range(24):
                a_id = str(uuid.uuid4())
                
                # Model peak hours (8-10 AM, 5-8 PM)
                time_multiplier = 1.0
                if 8 <= hour <= 10 or 17 <= hour <= 20:
                    time_multiplier = 1.4
                elif hour < 6:
                    time_multiplier = 0.3
                    
                # Adjust for weekend vs weekday
                weekend_multiplier = 0.85 if is_weekend else 1.0
                
                density = round(base_density * time_multiplier * weekend_multiplier + random.uniform(-0.5, 0.5), 1)
                density = max(0.5, min(9.9, density)) # Keep bounded
                
                ts_log = current_day.replace(hour=hour, minute=0, second=0)
                timestamp_str = ts_log.strftime("%Y-%m-%d %H:%M:%S")
                
                cursor.execute("""
                    INSERT INTO analytics (id, location, camera_id, traffic_density, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (a_id, loc, cam_id, density, timestamp_str))
                
                analytics_count += 1
                
    conn.commit()
    print(f"[OK] Seeded {analytics_count} traffic density analytics records.")
    
    # Seed alerts table (12 alerts)
    print("Seeding alerts table...")
    alert_messages = [
        "High traffic congestion detected. Recommended traffic unit deployment.",
        "Excess helmet violations. Deploy mobile patrol unit.",
        "Triple riding incidents increasing. Increase surveillance coverage."
    ]
    
    for idx in range(12):
        al_id = str(uuid.uuid4())
        cam_id = f"CAM_BLR_{((idx % 10) + 1):03d}"
        loc = cam_locs[cam_id]
        
        severity = "HIGH" if idx % 3 == 0 else ("MEDIUM" if idx % 3 == 1 else "LOW")
        status_text = f"{'⚠️ ' if severity != 'LOW' else ''}{random.choice(alert_messages).replace('detected.', 'detected at ' + loc).replace('violations.', 'violations at ' + loc).replace('increasing.', 'increasing at ' + loc)}"
        
        ts_alert = end_date - timedelta(days=idx // 2, hours=idx * 2)
        timestamp_str = ts_alert.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO alerts (alert_id, location, severity, timestamp, status)
            VALUES (?, ?, ?, ?, ?)
        """, (al_id, loc, severity, timestamp_str, status_text))
        
    conn.commit()
    print("[OK] Seeded alerts.")
    
    # Seed notifications (20 logs)
    print("Seeding notifications logs...")
    for idx in range(20):
        n_id = str(uuid.uuid4())
        n_type = "CUSTOMER_CHALLAN" if idx % 2 == 0 else "CONGESTION_ALERT"
        recipient = "+919876543210" if n_type == "CUSTOMER_CHALLAN" else "+919900000000"
        status = "DELIVERED"
        
        ts_notify = end_date - timedelta(days=idx // 3, hours=idx * 3)
        timestamp_str = ts_notify.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO notifications (notification_id, type, recipient, status, timestamp, message, plate_number, challan_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (n_id, n_type, recipient, status, timestamp_str, "TrafficFlow auto alert notification message log sample.", "KA03MM8812" if n_type == "CUSTOMER_CHALLAN" else None, f"CHN-2026-0000{idx}" if n_type == "CUSTOMER_CHALLAN" else None))
        
    conn.commit()
    print("[OK] Seeded notifications.")
    
    # Seed video views (35 records)
    print("Seeding video views...")
    categories = [
        "Helmet Safety", "Triple Riding Risks", "Traffic Signal Rules", 
        "Seatbelt Awareness", "Wrong Side Driving", "Illegal Parking", 
        "Emergency Vehicle Awareness"
    ]
    video_ids = [
        "helmet_safety", "triple_riding", "traffic_signal", 
        "seatbelt_awareness", "wrong_way_driving", "illegal_parking", 
        "emergency_vehicle"
    ]
    for idx in range(35):
        vv_id = str(uuid.uuid4())
        cat_idx = idx % len(categories)
        cat = categories[cat_idx]
        v_id = video_ids[cat_idx]
        
        ts_view = end_date - timedelta(days=idx // 2, hours=idx * 4)
        timestamp_str = ts_view.strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("""
            INSERT INTO video_views (id, video_id, category, timestamp)
            VALUES (?, ?, ?, ?)
        """, (vv_id, v_id, cat, timestamp_str))
        
    conn.commit()
    conn.close()
    print("=== Database seeding completed successfully! ===")

if __name__ == "__main__":
    seed()
