import os
import json
import uuid
import shutil
from datetime import datetime, timedelta
import random
import cv2
import numpy as np
from database.postgres import (
    Base, engine, SessionLocal, initialize_database,
    Vehicle, Violation, Challan, OCRResult, RepeatOffender,
    PoliceAlert, SMSLog, Analytics, SafetyVideoView, CameraNode,
    Payment, PatrolDispatch, EvidencePackage
)
from engine.evidence_engine import EvidenceEngine

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

def seed():
    print("=== TrafficFlow Smart City Seeding Engine ===")
    
    # Initialize connection and clear data
    initialize_database()
    session = SessionLocal()
    print("Clearing existing data from tables using DELETE to avoid deadlocks...")
    try:
        # Delete from tables in correct dependency order
        for model in [Payment, OCRResult, Challan, Violation, Vehicle, RepeatOffender, PoliceAlert, PatrolDispatch, SMSLog, Analytics, SafetyVideoView, CameraNode]:
            try:
                session.query(model).delete()
            except Exception as e:
                print(f"Warning: Could not delete from {model.__tablename__}: {e}")
        session.commit()
        print("Existing data cleared successfully.")
    except Exception as ex:
        session.rollback()
        print(f"Error during clearing data: {ex}")
    finally:
        session.close()

    print("Ensuring all PostgreSQL tables exist...")
    Base.metadata.create_all(bind=engine)
    
    # Load camera locations
    with open("camera_locations.json", "r") as f:
        cam_locs = json.load(f)
        
    session = SessionLocal()
    
    try:
        # Seed CameraNode table
        print("Seeding camera nodes configurations...")
        for cam_id, loc in cam_locs.items():
            coords = COORDINATES.get(loc.split(",")[0], [12.9716, 77.5946])
            node = CameraNode(
                camera_id=cam_id,
                location=loc,
                latitude=coords[0],
                longitude=coords[1]
            )
            session.add(node)
        session.commit()
        
        # Clear and recreate output directories
        evidence_dir = os.path.join("outputs", "evidence")
        challans_dir = "challans"
        
        if os.path.exists(evidence_dir):
            try:
                shutil.rmtree(evidence_dir)
            except Exception as e:
                print(f"Warning: Could not clear evidence directory: {e}")
        if os.path.exists(challans_dir):
            try:
                shutil.rmtree(challans_dir)
            except Exception as e:
                print(f"Warning: Could not clear challans directory: {e}")
            
        os.makedirs(evidence_dir, exist_ok=True)
        os.makedirs(challans_dir, exist_ok=True)
        
        # Initialize EvidenceEngine
        ee = EvidenceEngine()
        
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
        
        violation_types = [
            "HELMET_VIOLATION",
            "TRIPLE_RIDING",
            "WRONG_SIDE_DRIVING",
            "ILLEGAL_PARKING",
            "SEATBELT_VIOLATION",
            "RED_LIGHT_VIOLATION",
            "STOP_LINE_VIOLATION"
        ]
        
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
        
        print("Seeding violations, vehicles, challans, and OCR results...")
        total_violations_inserted = 0
        challan_index = 1
        
        # Bulk pre-insert vehicles to save ~2000 remote DB roundtrips!
        print("Pre-inserting vehicles in bulk...")
        unique_plates = list({plates_pool[idx % len(plates_pool)].strip().upper() for idx in range(1, 726 + 1)})
        vehicles_to_insert = []
        for plate in unique_plates:
            contact = ee.vehicle_contacts.get(plate, ee.vehicle_contacts.get("DEFAULT", {}))
            vehicles_to_insert.append(Vehicle(
                plate_number=plate,
                owner_name=contact.get("name", "Vehicle Owner"),
                owner_phone=contact.get("phone", "+919876543210")
            ))
        session.bulk_save_objects(vehicles_to_insert)
        session.commit()
        
        # Load all vehicle IDs into vehicle_cache
        all_vehicles = session.query(Vehicle).all()
        vehicle_cache = {v.plate_number: v.id for v in all_vehicles}
        print(f"[OK] Pre-inserted and cached {len(vehicle_cache)} vehicles.")
        
        # Keep track of plate counts and last violation type for repeat offenders table
        plate_counts = {}
        plate_last_v = {}
        
        for cam_id, target_count in location_targets.items():
            loc = cam_locs[cam_id]
            
            for i in range(target_count):
                v_id = str(uuid.uuid4())
                challan_id = f"CHN-2026-{challan_index:05d}"
                
                # Draw a plate from pool
                plate = plates_pool[challan_index % len(plates_pool)].strip().upper()
                # Assign violation type
                v_type = violation_types[challan_index % len(violation_types)]
                amount = ee._get_fine_amount(v_type)
                conf = round(random.uniform(0.82, 0.98), 2)
                
                # Timestamps: span June 1 to June 17, 2026
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
                
                # Track repeat offenders stats
                plate_counts[plate] = plate_counts.get(plate, 0) + 1
                plate_last_v[plate] = v_type
                
                # Setup folders
                package_dir = os.path.join(evidence_dir, v_id)
                os.makedirs(package_dir, exist_ok=True)
                
                # Copy fallback images for original/annotated/full (very fast copy)
                shutil.copy(fallback_img, os.path.join(package_dir, "annotated.jpg"))
                shutil.copy(fallback_img, os.path.join(package_dir, "original.jpg"))
                shutil.copy(fallback_img, os.path.join(package_dir, "annotated_full.jpg"))
                shutil.copy(fallback_img, os.path.join(package_dir, "original_full.jpg"))
                if v_type == "SEATBELT_VIOLATION":
                    shutil.copy(fallback_img, os.path.join(package_dir, "seatbelt_evidence.jpg"))
                if v_type == "STOP_LINE_VIOLATION":
                    shutil.copy(fallback_img, os.path.join(package_dir, "stopline_evidence.jpg"))
                
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
                    
                # Copy PDF from master
                try:
                    if not os.path.exists(master_pdf_path):
                        ee._generate_pdf(master_challan_id, master_json, fallback_img, master_pdf_path)
                    shutil.copy(master_pdf_path, os.path.join(challans_dir, f"{challan_id}.pdf"))
                except Exception as e_master:
                    print(f"Warning: PDF copy failed, attempting regeneration: {e_master}")
                    try:
                        ee._generate_pdf(master_challan_id, master_json, fallback_img, master_pdf_path)
                        shutil.copy(master_pdf_path, os.path.join(challans_dir, f"{challan_id}.pdf"))
                    except Exception as e_copy:
                        print(f"Warning: Could not copy master PDF to {challan_id}.pdf: {e_copy}")
                
                # DB violation insertion
                rel_evidence_path = f"outputs/evidence/{v_id}"
                violation = Violation(
                    id=v_id,
                    vehicle_id=vehicle_cache[plate],
                    violation_type=v_type,
                    confidence=conf,
                    timestamp=ts_datetime,
                    location=loc,
                    camera_id=cam_id,
                    evidence_path=rel_evidence_path
                )
                session.add(violation)
                
                challan = Challan(
                    challan_id=challan_id,
                    violation_id=v_id,
                    amount=amount,
                    status="PENDING",
                    timestamp=ts_datetime
                )
                session.add(challan)
                
                ocr_res = OCRResult(
                    violation_id=v_id,
                    ocr_confidence=conf,
                    ocr_engine="tesseract",
                    plate_crop_path=f"{rel_evidence_path}/plate_crop.jpg"
                )
                session.add(ocr_res)
                
                evidence_pkg = EvidencePackage(
                    evidence_id=str(uuid.uuid4()),
                    violation_id=v_id,
                    image_paths=json.dumps({
                        "plate_crop": f"{rel_evidence_path}/plate_crop.jpg",
                        "original_full": f"{rel_evidence_path}/original_full.jpg",
                        "annotated_full": f"{rel_evidence_path}/annotated_full.jpg",
                        "seatbelt_evidence": f"{rel_evidence_path}/seatbelt_evidence.jpg" if v_type == "SEATBELT_VIOLATION" else "",
                        "stopline_evidence": f"{rel_evidence_path}/stopline_evidence.jpg" if v_type == "STOP_LINE_VIOLATION" else ""
                    }),
                    ocr_results=json.dumps({
                        "plate_number": plate,
                        "ocr_confidence": conf,
                        "ocr_engine": "tesseract"
                    }),
                    generated_timestamp=ts_datetime
                )
                session.add(evidence_pkg)
                
                challan_index += 1
                total_violations_inserted += 1
                if total_violations_inserted % 50 == 0:
                    session.commit()
                    print(f"Seeded {total_violations_inserted} violations...")
                
        session.commit()
        print(f"[OK] Seeded {total_violations_inserted} violations.")
        
        # Populate RepeatOffenders
        print("Seeding repeat offenders...")
        for plate, count in plate_counts.items():
            if count > 1 and plate != "UNKNOWN":
                ro = RepeatOffender(
                    plate_number=plate,
                    violations_count=count,
                    last_violation=plate_last_v[plate],
                    blacklist_status="BLACKLISTED" if count >= 3 else "WARNING"
                )
                session.add(ro)
        session.commit()
        print("[OK] Seeded repeat offenders.")
        
        # Remove the master temp PDF
        if os.path.exists(master_pdf_path):
            os.remove(master_pdf_path)
            
        # Seed analytics table (continuous hourly records for the last 7 days)
        # 10 cameras * 24 hours * 7 days = 1680 logs
        print("Seeding analytics (traffic density) table...")
        
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
            
            for day in range(7):
                current_day = end_date - timedelta(days=day)
                is_weekend = current_day.weekday() >= 5
                
                for hour in range(24):
                    a_id = str(uuid.uuid4())
                    
                    time_multiplier = 1.0
                    if 8 <= hour <= 10 or 17 <= hour <= 20:
                        time_multiplier = 1.4
                    elif hour < 6:
                        time_multiplier = 0.3
                        
                    weekend_multiplier = 0.85 if is_weekend else 1.0
                    
                    density = round(base_density * time_multiplier * weekend_multiplier + random.uniform(-0.5, 0.5), 1)
                    density = max(0.5, min(9.9, density))
                    
                    ts_log = current_day.replace(hour=hour, minute=0, second=0)
                    
                    an = Analytics(
                        id=a_id,
                        location=loc,
                        camera_id=cam_id,
                        traffic_density=density,
                        timestamp=ts_log
                    )
                    session.add(an)
                    analytics_count += 1
                    
        session.commit()
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
            
            al = PoliceAlert(
                alert_id=al_id,
                location=loc,
                severity=severity,
                timestamp=ts_alert,
                status=status_text
            )
            session.add(al)
            
        session.commit()
        print("[OK] Seeded alerts.")
        
        # Seed SMS notifications log (20 logs)
        print("Seeding Twilio SMS logs...")
        for idx in range(20):
            n_id = str(uuid.uuid4())
            n_type = "CUSTOMER_CHALLAN" if idx % 2 == 0 else "CONGESTION_ALERT"
            recipient = "+919876543210" if n_type == "CUSTOMER_CHALLAN" else "+919900000000"
            status = "DELIVERED"
            
            ts_notify = end_date - timedelta(days=idx // 3, hours=idx * 3)
            
            sms = SMSLog(
                notification_id=n_id,
                type=n_type,
                recipient=recipient,
                status=status,
                timestamp=ts_notify,
                message="TrafficFlow auto alert notification message log sample.",
                plate_number="KA03MM8812" if n_type == "CUSTOMER_CHALLAN" else None,
                challan_id=f"CHN-2026-0000{idx}" if n_type == "CUSTOMER_CHALLAN" else None
            )
            session.add(sms)
            
        session.commit()
        print("[OK] Seeded notifications.")
        
        # Seed video views (35 records)
        print("Seeding video views...")
        categories = [
            "Helmet Safety", "Triple Riding Risks", "Traffic Signal Rules", 
            "Seatbelt Awareness", "Wrong Side Driving", "Illegal Parking", 
            "Emergency Vehicles"
        ]
        video_ids = [
            "helmet_safety", "triple_riding", "traffic_signal", 
            "seatbelt_awareness", "wrong_way_driving", "illegal_parking", 
            "emergency_vehicle"
        ]
        video_titles = [
            "Why Helmets Save Lives", "Dangers of Triple Riding", "Obeying the Traffic Lights", 
            "Seatbelt Awareness Guide", "Wrong Side Driving Consequences", "Smart Municipal Parking Etiquettes", 
            "Yielding to Emergency Vehicles"
        ]
        for idx in range(35):
            vv_id = str(uuid.uuid4())
            cat_idx = idx % len(categories)
            cat = categories[cat_idx]
            v_id = video_ids[cat_idx]
            title = video_titles[cat_idx]
            
            ts_view = end_date - timedelta(days=idx // 2, hours=idx * 4)
            
            # Generate realistic watch metrics
            comp_pct = random.choice([25.0, 50.0, 75.0, 100.0, 100.0, 100.0])
            duration_sec = random.randint(110, 210)
            watch_sec = round((comp_pct / 100.0) * duration_sec, 1)
            
            vv = SafetyVideoView(
                id=vv_id,
                video_id=v_id,
                video_title=title,
                category=cat,
                watch_timestamp=ts_view,
                watch_duration=watch_sec,
                completion_percentage=comp_pct
            )
            session.add(vv)
            
        session.commit()
        print("=== Database seeding completed successfully! ===")
        
    except Exception as e:
        session.rollback()
        print(f"Error seeding database: {e}")
        raise e
    finally:
        session.close()

if __name__ == "__main__":
    seed()
