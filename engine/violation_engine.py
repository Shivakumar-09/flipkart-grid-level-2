import cv2
import time
import logging
import numpy as np
from models.vehicle_detector import VehicleDetector
from models.helmet_detector import HelmetDetector
from models.triple_riding_detector import TripleRidingDetector
from models.parking_detector import ParkingDetector
from models.ocr_engine import OcrEngine

logger = logging.getLogger("ViolationEngine")

class ViolationEngine:
    def __init__(self):
        logger.info("Initializing Violation Engine and loading detection modules...")
        self.vehicle_detector = VehicleDetector()
        self.helmet_detector = HelmetDetector()
        self.triple_riding_detector = TripleRidingDetector()
        self.parking_detector = ParkingDetector()
        self.ocr_engine = OcrEngine()
        
        import json
        import os
        self.camera_locations = {}
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            proj_root = os.path.dirname(current_dir)
            with open(os.path.join(proj_root, "camera_locations.json"), "r") as f:
                self.camera_locations = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load camera_locations.json in ViolationEngine: {e}")
            
        logger.info("All detection modules loaded successfully.")

    def associate_riders_to_motorcycle(self, persons, mc_box):
        """
        Associate persons (riders) to a motorcycle using the score formula:
        Score = IoU overlap + center point inside + (1.0 - normalized distance from center)
        """
        associated = []
        mc_x1, mc_y1, mc_x2, mc_y2 = mc_box
        mc_w = mc_x2 - mc_x1
        mc_h = mc_y2 - mc_y1
        mc_cx = (mc_x1 + mc_x2) / 2.0
        mc_cy = (mc_y1 + mc_y2) / 2.0
        mc_diag = np.sqrt(mc_w**2 + mc_h**2) if (mc_w**2 + mc_h**2) > 0 else 1.0
        
        for p in persons:
            p_box = p['box']
            px1, py1, px2, py2 = p_box
            pw = px2 - px1
            ph = py2 - py1
            pcx = (px1 + px2) / 2.0
            pcy = (py1 + py2) / 2.0
            
            # 1. IoU Overlap
            ix1 = max(mc_x1, px1)
            iy1 = max(mc_y1, py1)
            ix2 = min(mc_x2, px2)
            iy2 = min(mc_y2, py2)
            
            iw = max(0, ix2 - ix1)
            ih = max(0, iy2 - iy1)
            inter_area = iw * ih
            
            mc_area = mc_w * mc_h
            p_area = pw * ph
            union_area = mc_area + p_area - inter_area
            iou = inter_area / union_area if union_area > 0 else 0.0
            
            # 2. Center point inside
            center_inside = 1.0 if (mc_x1 <= pcx <= mc_x2 and mc_y1 <= pcy <= mc_y2) else 0.0
            
            # 3. Distance from motorcycle center
            dist = np.sqrt((mc_cx - pcx)**2 + (mc_cy - pcy)**2)
            norm_dist = dist / mc_diag
            dist_score = max(0.0, 1.0 - norm_dist)
            
            score = iou + center_inside + dist_score
            logger.info(f"Rider Association Score: {score:.3f} (IoU: {iou:.3f}, Inside: {center_inside}, DistScore: {dist_score:.3f})")
            
            if score >= 0.8:
                associated.append(p)
                
        return associated

    def process_image(self, image_path, location=None, camera_id=None):
        """
        Processes a single traffic surveillance image through the entire pipeline.
        Returns:
        - results: dict containing annotated image, violations list, performance metrics
        """
        # Resolve location dynamically using camera_locations.json mapping
        if not camera_id:
            camera_id = "CAM_BLR_001"
        if camera_id not in self.camera_locations:
            camera_id = "CAM_BLR_001"
        location = self.camera_locations[camera_id]

        start_time = time.time()
        
        # Load image
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Could not load image at {image_path}")
            
        h, w, _ = image.shape
        
        # 1. Image Quality Enhancement
        enhanced_image = self._enhance_image(image)
        
        # 2. Vehicle Detection
        detections = self.vehicle_detector.detect(enhanced_image)
        logger.info(f"Detected {len(detections)} objects in the frame.")
        
        violations = []
        annotated_image = image.copy()
        
        # 3. Extract motorcycles and persons
        motorcycles = [d for d in detections if d['label'] == 'motorcycle']
        persons = [d for d in detections if d['label'] == 'person']
        
        # Implicit Motorcycle Grouping:
        # If no motorcycle is detected, but multiple persons (>=2) are huddled, group them.
        if len(motorcycles) == 0 and len(persons) >= 2:
            logger.info("YOLOv8 did not detect a motorcycle. Running Implicit Motorcycle Grouping...")
            min_x = min([p['box'][0] for p in persons])
            min_y = min([p['box'][1] for p in persons])
            max_x = max([p['box'][2] for p in persons])
            max_y = max([p['box'][3] for p in persons])
            
            # Bottom padding for wheels
            max_y = min(h, max_y + int((max_y - min_y) * 0.15))
            
            motorcycles.append({
                "box": [min_x, min_y, max_x, max_y],
                "label": "motorcycle",
                "confidence": 0.90,
                "is_virtual": True
            })

        # Process each motorcycle (real or virtual)
        plate_num = "UNKNOWN"
        ocr_conf = 0.0
        best_ocr_debug = {}

        for mc in motorcycles:
            mc_box = mc['box']
            
            # Extract Plate OCR for this motorcycle
            p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, mc_box)
            if plate_num == "UNKNOWN" or o_conf > ocr_conf:
                plate_num = p_num
                ocr_conf = o_conf
                best_ocr_debug = ocr_debug

            ocr_metadata = {
                "plate_number": p_num if o_conf >= 0.50 else "UNKNOWN",
                "ocr_confidence": o_conf,
                "ocr_engine": ocr_debug.get("ocr_engine", "none") if ocr_debug else "none",
                "ocr_debug_paths": ocr_debug.get("debug_paths", {}) if ocr_debug else {},
                "plate_crop_path": (ocr_debug.get("debug_paths", {}) or {}).get("plate_crop", ""),
                "enhanced_plate_path": (ocr_debug.get("debug_paths", {}) or {}).get("enhanced_plate", ""),
                "ocr_result_path": (ocr_debug.get("debug_paths", {}) or {}).get("ocr_result", "")
            }
                
            # Associate persons to this bike using score-based algorithm (Task 2)
            associated_persons = self.associate_riders_to_motorcycle(persons, mc_box)
            rider_count = len(associated_persons)
            logger.info(f"Motorcycle at {mc_box} has {rider_count} riders associated.")
            
            # Check Triple Riding & Overloading (Task 3 & Task 5) - triggers when associated_riders >= 3
            if rider_count >= 3:
                # Triple Riding Violation
                violations.append({
                    "type": "TRIPLE_RIDING",
                    "box": mc_box,
                    "confidence": 0.92,
                    "details": f"Triple riding detected (Rider count: {rider_count})",
                    **ocr_metadata
                })
                # Draw Orange rectangle
                cv2.rectangle(annotated_image, (mc_box[0], mc_box[1]), (mc_box[2], mc_box[3]), (0, 165, 255), 3) # Orange
                cv2.putText(annotated_image, f"TRIPLE RIDING: {rider_count} Riders (92%)", 
                            (mc_box[0], mc_box[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2)
                            
                # Overloading Violation
                violations.append({
                    "type": "OVERLOADING",
                    "box": mc_box,
                    "confidence": 0.95,
                    "details": f"Overloading two-wheeler with {rider_count} passengers",
                    **ocr_metadata
                })
                # Draw Purple rectangle (offset slightly to not overlap)
                cv2.rectangle(annotated_image, (mc_box[0]+5, mc_box[1]+5), (mc_box[2]-5, mc_box[3]-5), (128, 0, 128), 3) # Purple
                cv2.putText(annotated_image, f"OVERLOADING: {rider_count} Pax (95%)", 
                            (mc_box[0], mc_box[1]+20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 0, 128), 2)

            # Check helmet for each associated rider (Task 4)
            for r_idx, rider in enumerate(associated_persons):
                r_box = rider['box']
                has_helmet, helmet_conf = self.helmet_detector.check_helmet(enhanced_image, r_box)
                
                if not has_helmet:
                    violations.append({
                        "type": "HELMET_VIOLATION",
                        "box": r_box,
                        "confidence": helmet_conf,
                        "details": f"Rider #{r_idx+1} without helmet",
                        **ocr_metadata
                    })
                    # Draw Red Box around head / body of rider
                    cv2.rectangle(annotated_image, (r_box[0], r_box[1]), (r_box[2], r_box[3]), (0, 0, 255), 3) # Red
                    cv2.putText(annotated_image, f"NO HELMET: Rider #{r_idx+1}", 
                                (r_box[0], r_box[1]-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        processing_time = (time.time() - start_time) * 1000 # convert to ms
        logger.info(f"Processed frame in {processing_time:.1f}ms. Found {len(violations)} violations.")
        
        return {
            "original_image": image,
            "annotated_image": annotated_image,
            "violations": violations,
            "detections_count": len(detections),
            "processing_time_ms": processing_time,
            "location": location,
            "camera_id": camera_id,
            "detected_plate": plate_num,
            "ocr_confidence": ocr_conf,
            "ocr_engine": best_ocr_debug.get("ocr_engine", "none") if best_ocr_debug else "none",
            "ocr_debug": best_ocr_debug,
            "ocr_debug_paths": best_ocr_debug.get("debug_paths", {}) if best_ocr_debug else {}
        }

    def _enhance_image(self, image):
        """
        Enhance image quality using CLAHE for noise/light equalization.
        """
        try:
            # Convert to YCrCb
            ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
            channels = list(cv2.split(ycrcb))
            
            # Apply CLAHE to Y (luminance) channel
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            channels[0] = clahe.apply(channels[0])
            
            # Merge back and convert to BGR
            equalized = cv2.merge(channels)
            enhanced = cv2.cvtColor(equalized, cv2.COLOR_YCrCb2BGR)
            return enhanced
        except Exception as e:
            logger.error(f"Image enhancement failed: {e}. Returning original.")
            return image

    def _check_wrong_side(self, detections, w, h):
        """
        Wrong-Side driving check:
        In India, traffic flows on the left. If a vehicle is detected on the right half of the image,
        moving in the opposite direction (heuristically flagged for demonstration/testing), we register a violation.
        """
        violations = []
        for det in detections:
            if det['label'] in ['car', 'motorcycle']:
                box = det['box']
                cx = (box[0] + box[2]) // 2
                cy = (box[1] + box[3]) // 2
                
                # Check: if vehicle box is wide and on the rightmost lane (e.g. w*0.7 to w*0.9)
                # and cy is relatively high (towards the bottom camera view, moving closer)
                # This indicates it is driving wrong way (counter-flow)
                if cx > w * 0.75 and cy > h * 0.6:
                    violations.append({
                        "box": box,
                        "label": det['label'],
                        "confidence": det['confidence'] - 0.05
                    })
        return violations
