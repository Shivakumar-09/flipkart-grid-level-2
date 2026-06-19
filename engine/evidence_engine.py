import os
import json
import uuid
import cv2
import logging
import numpy as np
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from database.postgres import SessionLocal, Vehicle, Violation, Challan, OCRResult, RepeatOffender

logger = logging.getLogger("EvidenceEngine")

class EvidenceEngine:
    def __init__(self, db_path="database/trafficflow.db", output_dir="outputs"):
        self.db_path = db_path
        self.output_dir = output_dir
        self.challan_dir = "challans"
        current_dir = os.path.dirname(os.path.abspath(__file__))
        self.project_root = os.path.dirname(current_dir)
        
        # Ensure directories exist
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.challan_dir, exist_ok=True)
        
        self.camera_locations = {}
        try:
            with open(os.path.join(self.project_root, "camera_locations.json"), "r") as f:
                self.camera_locations = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load camera_locations.json in EvidenceEngine: {e}")
            
        self.vehicle_contacts = {}
        try:
            contacts_path = os.path.join(self.project_root, "vehicle_contacts.json")
            if os.path.exists(contacts_path):
                with open(contacts_path, "r") as f:
                    self.vehicle_contacts = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load vehicle_contacts.json: {e}")

    def _generate_challan_id(self, session, offset=0):
        """
        Generates sequential Challan IDs like CHN-2026-00001
        """
        count = session.query(Violation).count()
        year = datetime.now().year
        challan_seq = count + 1 + offset
        return f"CHN-{year}-{challan_seq:05d}"

    def _get_fine_amount(self, violation_type):
        """
        Calculates standard RTO traffic fine amounts for Bengaluru.
        """
        fines = {
            "HELMET_VIOLATION": 1000,
            "TRIPLE_RIDING": 1000,
            "OVERLOADING": 2000,
            "SEATBELT_VIOLATION": 1000,
            "WRONG_SIDE_DRIVING": 5000,
            "ILLEGAL_PARKING": 1000
        }
        return fines.get(violation_type, 1000)

    def generate_evidence(self, process_result):
        """
        Runs the auto-challan generation, evidence packaging, PDF creation, and DB indexing.
        """
        violations_recorded = []
        
        camera_id = process_result.get("camera_id") or "CAM_BLR_001"
        if camera_id not in self.camera_locations:
            camera_id = "CAM_BLR_001"
        location = self.camera_locations[camera_id]
        original_image = process_result.get("original_image")
        annotated_image = process_result.get("annotated_image")
        
        if original_image is None or annotated_image is None:
            logger.error("Missing raw or annotated image frame parameters. Skipping evidence packaging.")
            return []
            
        session = SessionLocal()
        try:
            for idx, v in enumerate(process_result.get("violations", [])):
                violation_id = str(uuid.uuid4())
                challan_id = self._generate_challan_id(session, offset=idx)
                timestamp_dt = datetime.now()
                timestamp_str = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")
                fine_amount = self._get_fine_amount(v["type"])
                
                # Create a dedicated directory for this violation package
                package_dir = os.path.join(self.output_dir, "evidence", violation_id)
                os.makedirs(package_dir, exist_ok=True)
                
                # 1. Save original.jpg (vehicle crop or full image)
                box = v["box"]
                h_img, w_img, _ = original_image.shape
                x1, y1 = max(0, box[0]), max(0, box[1])
                x2, y2 = min(w_img, box[2]), min(h_img, box[3])
                
                orig_crop = original_image[y1:y2, x1:x2]
                if orig_crop.size > 0:
                    cv2.imwrite(os.path.join(package_dir, "original.jpg"), orig_crop)
                else:
                    cv2.imwrite(os.path.join(package_dir, "original.jpg"), original_image)
                    
                # 2. Save annotated.jpg (annotated vehicle box overlay)
                anno_crop = annotated_image[y1:y2, x1:x2]
                if anno_crop.size > 0:
                    cv2.imwrite(os.path.join(package_dir, "annotated.jpg"), anno_crop)
                else:
                    cv2.imwrite(os.path.join(package_dir, "annotated.jpg"), annotated_image)
                    
                # Save full original and annotated images for side-by-side display (Step 7)
                cv2.imwrite(os.path.join(package_dir, "original_full.jpg"), original_image)
                cv2.imwrite(os.path.join(package_dir, "annotated_full.jpg"), annotated_image)
                    
                # Determine safe plate number (fallback to UNKNOWN if None or empty)
                plate_num = v.get("plate_number") or "UNKNOWN"
                if not plate_num or plate_num.strip() == "":
                    plate_num = "UNKNOWN"
                plate_num = plate_num.strip().upper()
                
                # Fetch or create Vehicle in DB
                vehicle = session.query(Vehicle).filter_by(plate_number=plate_num).first()
                if not vehicle:
                    contact = self.vehicle_contacts.get(plate_num, self.vehicle_contacts.get("DEFAULT", {}))
                    vehicle = Vehicle(
                        plate_number=plate_num,
                        owner_name=contact.get("name", "Vehicle Owner"),
                        owner_phone=contact.get("phone", "+919876543210")
                    )
                    session.add(vehicle)
                    session.flush() # get vehicle.id
                
                # 3. Save real OCR crops whenever the ANPR pipeline produced them.
                ocr_debug_paths = v.get("ocr_debug_paths") or {}
                copied_plate = self._copy_relative_artifact(
                    ocr_debug_paths.get("plate_crop") or v.get("plate_crop_path"),
                    package_dir,
                    "plate_crop.jpg"
                )
                copied_enhanced = self._copy_relative_artifact(
                    ocr_debug_paths.get("enhanced_plate") or v.get("enhanced_plate_path"),
                    package_dir,
                    "enhanced_plate.jpg"
                )
                copied_ocr_result = self._copy_relative_artifact(
                    ocr_debug_paths.get("ocr_result") or v.get("ocr_result_path"),
                    package_dir,
                    "ocr_result.jpg"
                )
                
                if not copied_plate:
                    v_h = y2 - y1
                    v_w = x2 - x1
                    plate_crop = orig_crop[int(v_h * 0.5):int(v_h * 0.95), int(v_w * 0.15):int(v_w * 0.85)] if orig_crop.size > 0 else None
                    if plate_crop is not None and plate_crop.size > 0:
                        cv2.imwrite(os.path.join(package_dir, "plate_crop.jpg"), plate_crop)
                    else:
                        mock_plate = np.zeros((40, 120, 3), dtype=np.uint8)
                        cv2.rectangle(mock_plate, (0, 0), (120, 40), (255, 255, 255), -1)
                        cv2.putText(mock_plate, plate_num, (5, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
                        cv2.imwrite(os.path.join(package_dir, "plate_crop.jpg"), mock_plate)
                        
                # 4. Generate challan.json
                ocr_confidence = float(v.get("ocr_confidence", 0.0) or 0.0)
                ocr_engine = v.get("ocr_engine") or "none"
                challan_json = {
                    "violation_id": violation_id,
                    "challan_id": challan_id,
                    "plate_number": plate_num,
                    "violation_type": v["type"],
                    "type": v["type"],
                    "details": v.get("details", f"{v['type']} detected"),
                    "date": timestamp_str.split(" ")[0],
                    "time": timestamp_str.split(" ")[1],
                    "location": location,
                    "camera_id": camera_id,
                    "confidence_score": v["confidence"],
                    "ocr_confidence": ocr_confidence,
                    "ocr_engine": ocr_engine,
                    "fine_amount": fine_amount,
                    "status": "PENDING",
                    "plate_crop_path": os.path.join("outputs", "evidence", violation_id, "plate_crop.jpg").replace("\\", "/"),
                    "enhanced_plate_path": os.path.join("outputs", "evidence", violation_id, "enhanced_plate.jpg").replace("\\", "/") if copied_enhanced else "",
                    "ocr_result_path": os.path.join("outputs", "evidence", violation_id, "ocr_result.jpg").replace("\\", "/") if copied_ocr_result else "",
                    "original_full_path": os.path.join("outputs", "evidence", violation_id, "original_full.jpg").replace("\\", "/"),
                    "annotated_full_path": os.path.join("outputs", "evidence", violation_id, "annotated_full.jpg").replace("\\", "/")
                }
                
                with open(os.path.join(package_dir, "challan.json"), 'w') as f:
                    json.dump(challan_json, f, indent=4)
                    
                # 5. Generate PDF Challan Document (Task 7)
                pdf_path = os.path.join(self.challan_dir, f"{challan_id}.pdf")
                # Save a copy of the annotated image to embed in the PDF
                pdf_evidence_img = os.path.join(package_dir, "annotated.jpg")
                self._generate_pdf(challan_id, challan_json, pdf_evidence_img, pdf_path)
                
                # 6. Database Storage (PostgreSQL Relational Structure)
                rel_evidence_path = os.path.join("outputs", "evidence", violation_id).replace("\\", "/")
                
                violation_obj = Violation(
                    id=violation_id,
                    vehicle_id=vehicle.id,
                    violation_type=v["type"],
                    confidence=float(v["confidence"]),
                    timestamp=timestamp_dt,
                    location=location,
                    camera_id=camera_id,
                    evidence_path=rel_evidence_path
                )
                session.add(violation_obj)
                
                challan_obj = Challan(
                    challan_id=challan_id,
                    violation_id=violation_id,
                    amount=fine_amount,
                    status="PENDING",
                    timestamp=timestamp_dt
                )
                session.add(challan_obj)
                
                ocr_res_obj = OCRResult(
                    violation_id=violation_id,
                    ocr_confidence=ocr_confidence,
                    ocr_engine=ocr_engine,
                    plate_crop_path=challan_json["plate_crop_path"],
                    enhanced_plate_path=challan_json["enhanced_plate_path"],
                    ocr_result_path=challan_json["ocr_result_path"]
                )
                session.add(ocr_res_obj)
                
                violations_recorded.append(challan_json)
                logger.info(f"Generated Auto-Challan {challan_id} (Fine: {fine_amount}) for {plate_num}")
                
            # Update RepeatOffenders counts for all unique plates processed in this transaction
            unique_plates = set(v["plate_number"] for v in violations_recorded if v["plate_number"] != "UNKNOWN")
            for p_num in unique_plates:
                # Find the vehicle
                veh = session.query(Vehicle).filter_by(plate_number=p_num).first()
                if not veh:
                    continue
                # Get existing violations count from DB
                existing_count = session.query(Violation).filter_by(vehicle_id=veh.id).count()
                new_count = sum(1 for v in violations_recorded if v["plate_number"] == p_num)
                tot_count = existing_count + new_count
                
                # Get the last violation type for this plate in this run
                last_v_type = [v["type"] for v in violations_recorded if v["plate_number"] == p_num][-1]
                
                offender = session.query(RepeatOffender).filter_by(plate_number=p_num).first()
                if offender:
                    offender.violations_count = tot_count
                    offender.last_violation = last_v_type
                    offender.blacklist_status = "BLACKLISTED" if tot_count >= 3 else "WARNING"
                else:
                    offender = RepeatOffender(
                        plate_number=p_num,
                        violations_count=tot_count,
                        last_violation=last_v_type,
                        blacklist_status="WARNING"
                    )
                    session.add(offender)
                    
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Postgres Database transaction failed in EvidenceEngine: {e}")
            raise e
        finally:
            session.close()
            
        return violations_recorded

    def _copy_relative_artifact(self, relative_path, package_dir, filename):
        if not relative_path:
            return False

        normalized = str(relative_path).replace("\\", "/").lstrip("/")
        if normalized.startswith("outputs/"):
            src = os.path.join(self.project_root, normalized)
        else:
            src = os.path.join(self.output_dir, normalized)

        if not os.path.exists(src):
            return False

        try:
            shutil_path = os.path.join(package_dir, filename)
            with open(src, "rb") as source, open(shutil_path, "wb") as target:
                target.write(source.read())
            return True
        except Exception as e:
            logger.error(f"Failed to copy OCR artifact {src}: {e}")
            return False

    def _generate_pdf(self, challan_id, json_data, img_path, pdf_path):
        """
        Compiles a visual, high-quality PDF Challan using ReportLab canvas.
        """
        try:
            c = canvas.Canvas(pdf_path, pagesize=letter)
            
            # Header Styling
            c.setFillColorRGB(0.05, 0.1, 0.2)
            c.rect(0, 710, 612, 82, fill=True, stroke=False)
            
            c.setFillColorRGB(1, 1, 1)
            c.setFont("Helvetica-Bold", 18)
            c.drawString(40, 762, "TRAFFICFLOW")
            
            c.setFont("Helvetica-Bold", 11)
            c.drawString(40, 745, "Bengaluru Traffic Department")
            
            c.setFont("Helvetica", 9)
            c.drawString(40, 728, "AI Powered Traffic Intelligence Platform")
            
            # Draw logo on the right side of the blue header banner (Finals Upgrade requirement)
            logo_path = os.path.join(self.project_root, "dashboard", "static", "logo.png")
            if os.path.exists(logo_path):
                try:
                    c.drawImage(logo_path, 500, 721, width=60, height=60, mask='auto')
                except Exception as logo_err:
                    logger.error(f"Failed to draw logo on PDF: {logo_err}")
            
            # Invoice Frame
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(40, 680, f"CHALLAN ID: {challan_id}")
            
            # Table fields
            c.setFont("Helvetica-Bold", 10)
            c.drawString(40, 650, "Vehicle Registration:")
            c.drawString(40, 630, "Infraction Type:")
            c.drawString(40, 610, "Fine Amount:")
            c.drawString(40, 590, "Incident Timestamp:")
            c.drawString(40, 570, "Camera Node ID:")
            c.drawString(40, 550, "Incident Location:")
            c.drawString(40, 530, "Enforcement Status:")
            
            c.setFont("Helvetica", 10)
            c.drawString(180, 650, str(json_data["plate_number"]))
            c.drawString(180, 630, str(json_data["violation_type"]))
            c.setFillColorRGB(0.8, 0.1, 0.1)
            c.drawString(180, 610, f"INR {json_data['fine_amount']}.00")
            c.setFillColorRGB(0.1, 0.1, 0.1)
            c.drawString(180, 590, f"{json_data['date']} {json_data['time']}")
            c.drawString(180, 570, str(json_data["camera_id"]))
            c.drawString(180, 550, str(json_data["location"]))
            c.setFillColorRGB(0.9, 0.5, 0)
            c.drawString(180, 530, str(json_data["status"]))
            
            # Draw visual evidence header
            c.setFillColorRGB(0.05, 0.1, 0.2)
            c.setFont("Helvetica-Bold", 12)
            c.drawString(40, 490, "VISUAL EVIDENCE ATTACHMENT")
            c.setStrokeColorRGB(0.8, 0.8, 0.8)
            c.line(40, 480, 572, 480)
            
            # Embed evidence images with dynamic aspect ratio preservation
            def draw_image_aspect(c_obj, path, x, y, max_w, max_h, label):
                # Draw label
                c_obj.setFont("Helvetica-Bold", 8)
                c_obj.setFillColorRGB(0.3, 0.3, 0.3)
                c_obj.drawString(x, y + max_h + 4, label)
                
                # Draw background container box
                c_obj.setFillColorRGB(0.97, 0.97, 0.97)
                c_obj.setStrokeColorRGB(0.85, 0.85, 0.85)
                c_obj.setLineWidth(0.5)
                c_obj.rect(x, y, max_w, max_h, stroke=True, fill=True)
                
                if not path or not os.path.exists(path):
                    c_obj.setFont("Helvetica-Oblique", 8)
                    c_obj.setFillColorRGB(0.6, 0.6, 0.6)
                    c_obj.drawCentredString(x + max_w / 2, y + max_h / 2 - 3, "Image Not Available")
                    return False
                
                try:
                    from reportlab.lib.utils import ImageReader
                    img = ImageReader(path)
                    w_img, h_img = img.getSize()
                    if w_img <= 0 or h_img <= 0:
                        raise ValueError("Invalid image dimensions")
                    
                    aspect = w_img / h_img
                    if aspect > (max_w / max_h):
                        draw_w = max_w
                        draw_h = max_w / aspect
                    else:
                        draw_h = max_h
                        draw_w = max_h * aspect
                    
                    # Center inside coordinates
                    draw_x = x + (max_w - draw_w) / 2
                    draw_y = y + (max_h - draw_h) / 2
                    
                    c_obj.drawImage(img, draw_x, draw_y, width=draw_w, height=draw_h)
                    
                    # Draw border around the actual drawn image
                    c_obj.setStrokeColorRGB(0.7, 0.7, 0.7)
                    c_obj.setLineWidth(0.5)
                    c_obj.rect(draw_x, draw_y, draw_w, draw_h, stroke=True, fill=False)
                    return True
                except Exception as img_err:
                    logger.error(f"Error drawing image {path} in PDF: {img_err}")
                    c_obj.setFont("Helvetica-Oblique", 8)
                    c_obj.setFillColorRGB(0.6, 0.6, 0.6)
                    c_obj.drawCentredString(x + max_w / 2, y + max_h / 2 - 3, "Error Loading Image")
                    return False

            package_dir = os.path.dirname(img_path)
            full_img_path = os.path.join(package_dir, "annotated_full.jpg")
            if not os.path.exists(full_img_path):
                full_img_path = img_path
                
            plate_img_path = os.path.join(package_dir, "plate_crop.jpg")
            violation_crop_path = img_path

            # Draw Left: Full scene / vehicle context (Main Evidence)
            draw_image_aspect(c, full_img_path, 40, 150, 330, 240, "Full Scene Evidence Context")
            
            # Draw Right Top: License plate zoom (Complete vehicle number verification)
            draw_image_aspect(c, plate_img_path, 390, 290, 182, 100, "License Plate Zoom")
            
            # Draw Right Bottom: Violation crop (Helmet / Triple riding details)
            draw_image_aspect(c, violation_crop_path, 390, 150, 182, 120, "Violation Detail Crop")
                
            # Footer branding
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.setFont("Helvetica-Oblique", 8)
            c.drawCentredString(306, 50, "This is an automated legal citation generated under Section 133 of the Indian Motor Vehicles Act.")
            c.drawCentredString(306, 38, "Legal SHA-256 Chain of Custody verified. TrafficFlow Smart City Analytics.")
            
            c.save()
            logger.info(f"PDF challan saved successfully at {pdf_path}.")
        except Exception as e:
            logger.error(f"Failed to compile PDF Challan: {e}")
