import cv2
import time
import logging
import numpy as np
import os
from datetime import datetime
import uuid
from utils.runtime import empty_stage_profile, add_ms, get_resource_snapshot

logger = logging.getLogger("ViolationEngine")

class ViolationEngine:
    def __init__(self):
        logger.info("Initializing Violation Engine (detection modules will load lazily)...")
        self._vehicle_detector = None
        self._helmet_detector = None
        self._triple_riding_detector = None
        self._parking_detector = None
        self._ocr_engine = None
        self._seatbelt_detector = None
        self._traffic_light_detector = None
        self.max_inference_width = int(os.environ.get("TRAFFICFLOW_MAX_INFERENCE_WIDTH", "1280"))
        self.camera_locations = {}
        import json
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            proj_root = os.path.dirname(current_dir)
            with open(os.path.join(proj_root, "camera_locations.json"), "r") as f:
                self.camera_locations = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load camera_locations.json in ViolationEngine: {e}")

    @property
    def vehicle_detector(self):
        if self._vehicle_detector is None:
            from models.vehicle_detector import VehicleDetector
            self._vehicle_detector = VehicleDetector()
        return self._vehicle_detector

    @property
    def helmet_detector(self):
        if self._helmet_detector is None:
            from models.helmet_detector import HelmetDetector
            self._helmet_detector = HelmetDetector()
        return self._helmet_detector

    @property
    def triple_riding_detector(self):
        if self._triple_riding_detector is None:
            from models.triple_riding_detector import TripleRidingDetector
            self._triple_riding_detector = TripleRidingDetector()
        return self._triple_riding_detector

    @property
    def parking_detector(self):
        if self._parking_detector is None:
            from models.parking_detector import ParkingDetector
            self._parking_detector = ParkingDetector()
        return self._parking_detector

    @property
    def ocr_engine(self):
        if self._ocr_engine is None:
            from models.ocr_engine import OcrEngine
            self._ocr_engine = OcrEngine()
        return self._ocr_engine

    @property
    def seatbelt_detector(self):
        if self._seatbelt_detector is None:
            from models.seatbelt_detector import SeatbeltDetector
            self._seatbelt_detector = SeatbeltDetector()
        return self._seatbelt_detector

    @property
    def traffic_light_detector(self):
        if self._traffic_light_detector is None:
            from models.traffic_light_detector import TrafficLightDetector
            self._traffic_light_detector = TrafficLightDetector()
        return self._traffic_light_detector

    def _resize_for_inference(self, image):
        h, w = image.shape[:2]
        if w <= self.max_inference_width:
            return image, 1.0
        scale = self.max_inference_width / float(w)
        resized = cv2.resize(
            image,
            (self.max_inference_width, int(round(h * scale))),
            interpolation=cv2.INTER_AREA
        )
        return resized, scale

    def _ocr_metadata(self, image, vehicle_box, ocr_cache, profile):
        key = tuple(int(v) for v in vehicle_box)
        if key not in ocr_cache:
            debug_id = str(uuid.uuid4())
            p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, vehicle_box, debug_name=debug_id)
            ocr_profile = (ocr_debug or {}).get("profile", {})
            profile["plate_detection_ms"] = round(
                profile.get("plate_detection_ms", 0.0) + float(ocr_profile.get("plate_detection_ms", 0.0)),
                2
            )
            profile["ocr_ms"] = round(
                profile.get("ocr_ms", 0.0) + float(ocr_profile.get("ocr_recognition_ms", 0.0)),
                2
            )

            ocr_cache[key] = {
                "plate_number": p_num,
                "ocr_confidence": o_conf,
                "ocr_debug": ocr_debug or {},
                "metadata": {
                    "plate_number": p_num if o_conf >= 0.50 else "UNKNOWN",
                    "ocr_confidence": o_conf,
                    "ocr_engine": (ocr_debug or {}).get("ocr_engine", "none"),
                    "ocr_debug_paths": (ocr_debug or {}).get("debug_paths", {}),
                    "plate_crop_path": ((ocr_debug or {}).get("debug_paths", {}) or {}).get("plate_crop", ""),
                    "enhanced_plate_path": ((ocr_debug or {}).get("debug_paths", {}) or {}).get("enhanced_plate", ""),
                    "ocr_result_path": ((ocr_debug or {}).get("debug_paths", {}) or {}).get("ocr_result", ""),
                    "ocr_attempts": (ocr_debug or {}).get("ocr_attempts", [])
                }
            }
        return ocr_cache[key]

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
            p["association"] = {
                "iou": round(float(iou), 4),
                "center_inside": bool(center_inside),
                "center_distance_px": round(float(dist), 2),
                "center_distance_norm": round(float(norm_dist), 4),
                "association_score": round(float(score), 4),
            }
            logger.info(
                "Rider Association Score: %.3f (IoU: %.3f, Inside: %s, Dist: %.1fpx, DistScore: %.3f)",
                score, iou, center_inside, dist, dist_score
            )
            
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

        start_time = time.perf_counter()
        profile = empty_stage_profile()
        
        # Load image
        stage_started = time.perf_counter()
        image = cv2.imread(image_path)
        if image is None:
            raise ValueError(f"Could not load image at {image_path}")
        add_ms(profile, "image_load_ms", stage_started)

        original_h, original_w = image.shape[:2]
        stage_started = time.perf_counter()
        image, resize_scale = self._resize_for_inference(image)
        add_ms(profile, "image_resize_ms", stage_started)
        profile["input_width"] = int(original_w)
        profile["input_height"] = int(original_h)
        profile["inference_width"] = int(image.shape[1])
        profile["inference_height"] = int(image.shape[0])
        profile["resize_scale"] = round(float(resize_scale), 4)
            
        h, w, _ = image.shape
        
        # 1. Image Quality Enhancement
        stage_started = time.perf_counter()
        enhanced_image = self._enhance_image(image)
        add_ms(profile, "preprocess_ms", stage_started)
        
        # 2. Vehicle Detection
        stage_started = time.perf_counter()
        detections = self.vehicle_detector.detect(enhanced_image)
        add_ms(profile, "vehicle_detection_ms", stage_started)
        logger.info(f"Detected {len(detections)} objects in the frame.")
        
        violations = []
        helmet_debug = []
        annotated_image = image.copy()
        ocr_cache = {}
        helmet_debug_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "outputs",
            "debug",
            "helmet",
        )
        os.makedirs(helmet_debug_dir, exist_ok=True)
        
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
            debug_id = str(uuid.uuid4())
            p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, mc_box, debug_name=debug_id)
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
                "ocr_result_path": (ocr_debug.get("debug_paths", {}) or {}).get("ocr_result", ""),
                "ocr_attempts": ocr_debug.get("ocr_attempts", []) if ocr_debug else []
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
                helmet_result = self.helmet_detector.check_helmet(
                    enhanced_image,
                    r_box,
                    rider_id=r_idx,
                    debug_dir=helmet_debug_dir,
                )
                helmet_result["association"] = rider.get("association", {})
                helmet_debug.append(helmet_result)

                head_bbox = helmet_result.get("head_bbox") or r_box
                helmet_bbox = helmet_result.get("helmet_bbox")

                if helmet_result["decision"] == "HELMET_VIOLATION":
                    violations.append({
                        "type": "HELMET_VIOLATION",
                        "box": r_box,
                        "confidence": helmet_result["helmet_missing_confidence"],
                        "details": (
                            f"Rider #{r_idx + 1} without helmet "
                            f"(missing_conf={helmet_result['helmet_missing_confidence']:.2f}, "
                            f"reason={helmet_result['violation_trigger_reason']})"
                        ),
                        "helmet_debug": helmet_result,
                        **ocr_metadata
                    })
                    cv2.rectangle(annotated_image, (r_box[0], r_box[1]), (r_box[2], r_box[3]), (0, 0, 255), 3)
                    cv2.rectangle(
                        annotated_image,
                        (head_bbox[0], head_bbox[1]),
                        (head_bbox[2], head_bbox[3]),
                        (0, 0, 255),
                        2,
                    )
                    cv2.putText(
                        annotated_image,
                        f"NO HELMET: Rider #{r_idx + 1} ({helmet_result['helmet_missing_confidence']:.0%})",
                        (r_box[0], r_box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 0, 255),
                        2,
                    )
                elif helmet_result["decision"] == "REVIEW_REQUIRED":
                    violations.append({
                        "type": "REVIEW_REQUIRED",
                        "subtype": "HELMET_UNCERTAIN",
                        "box": r_box,
                        "confidence": helmet_result["helmet_missing_confidence"],
                        "details": (
                            f"Rider #{r_idx + 1} helmet status uncertain "
                            f"(reason={helmet_result['violation_trigger_reason']})"
                        ),
                        "helmet_debug": helmet_result,
                        **ocr_metadata
                    })
                    cv2.rectangle(annotated_image, (r_box[0], r_box[1]), (r_box[2], r_box[3]), (0, 165, 255), 2)
                    cv2.putText(
                        annotated_image,
                        f"HELMET REVIEW: Rider #{r_idx + 1}",
                        (r_box[0], r_box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 165, 255),
                        2,
                    )
                elif helmet_bbox:
                    cv2.rectangle(
                        annotated_image,
                        (helmet_bbox[0], helmet_bbox[1]),
                        (helmet_bbox[2], helmet_bbox[3]),
                        (0, 255, 0),
                        2,
                    )
                    cv2.putText(
                        annotated_image,
                        f"HELMET OK: Rider #{r_idx + 1} ({helmet_result['helmet_confidence']:.0%})",
                        (r_box[0], r_box[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (0, 255, 0),
                        2,
                    )

        # Check Wrong Side Driving (Task 13)
        wrong_side_detections = self._check_wrong_side(detections, w, h)
        for ws in wrong_side_detections:
            ws_box = ws["box"]
            debug_id = str(uuid.uuid4())
            p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, ws_box, debug_name=debug_id)
            ocr_metadata = {
                "plate_number": p_num if o_conf >= 0.50 else "UNKNOWN",
                "ocr_confidence": o_conf,
                "ocr_engine": ocr_debug.get("ocr_engine", "none") if ocr_debug else "none",
                "ocr_debug_paths": ocr_debug.get("debug_paths", {}) if ocr_debug else {},
                "plate_crop_path": (ocr_debug.get("debug_paths", {}) or {}).get("plate_crop", ""),
                "enhanced_plate_path": (ocr_debug.get("debug_paths", {}) or {}).get("enhanced_plate", ""),
                "ocr_result_path": (ocr_debug.get("debug_paths", {}) or {}).get("ocr_result", ""),
                "ocr_attempts": ocr_debug.get("ocr_attempts", []) if ocr_debug else []
            }
            
            violations.append({
                "type": "WRONG_SIDE_DRIVING",
                "box": ws_box,
                "confidence": float(ws["confidence"]),
                "details": "Wrong side driving detected (vehicles must keep left)",
                **ocr_metadata
            })
            
            # Draw Red rectangle and text on annotated_image
            cv2.rectangle(annotated_image, (ws_box[0], ws_box[1]), (ws_box[2], ws_box[3]), (0, 0, 255), 3) # Red
            cv2.putText(annotated_image, "WRONG SIDE DRIVING", (ws_box[0], ws_box[1]-10), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        # Check Seatbelt Non-Compliance (Phase 3 & 4)
        vehicles = []
        for d in detections:
            if d['label'] in ['car', 'truck', 'bus']:
                vw = d['box'][2] - d['box'][0]
                vh = d['box'][3] - d['box'][1]
                # Filter out small or background vehicles where seatbelts are invisible
                if vw > 150 and vh > 100:
                    vehicles.append(d)
        
        for veh in vehicles:
            veh_box = veh['box']
            veh_label = veh['label']
            
            # Check if seatbelt is present
            seatbelt_present, sb_conf, driver_box = self.seatbelt_detector.detect_seatbelt(
                image, veh_box, veh_label
            )
            
            if not seatbelt_present:
                debug_id = str(uuid.uuid4())
                p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, veh_box, debug_name=debug_id)
                ocr_metadata = {
                    "plate_number": p_num if o_conf >= 0.50 else "UNKNOWN",
                    "ocr_confidence": o_conf,
                    "ocr_engine": ocr_debug.get("ocr_engine", "none") if ocr_debug else "none",
                    "ocr_debug_paths": ocr_debug.get("debug_paths", {}) if ocr_debug else {},
                    "plate_crop_path": (ocr_debug.get("debug_paths", {}) or {}).get("plate_crop", ""),
                    "enhanced_plate_path": (ocr_debug.get("debug_paths", {}) or {}).get("enhanced_plate", ""),
                    "ocr_result_path": (ocr_debug.get("debug_paths", {}) or {}).get("ocr_result", ""),
                    "ocr_attempts": ocr_debug.get("ocr_attempts", []) if ocr_debug else []
                }
                
                violations.append({
                    "type": "SEATBELT_VIOLATION",
                    "box": driver_box,
                    "confidence": sb_conf,
                    "details": f"Driver in {veh_label} non-compliant with seatbelt safety regulations",
                    **ocr_metadata
                })
                
                # Draw Vehicle Box
                cv2.rectangle(annotated_image, (veh_box[0], veh_box[1]), (veh_box[2], veh_box[3]), (0, 255, 255), 2) # Yellow (BGR: 0, 255, 255)
                # Draw Driver Region (Blue)
                cv2.rectangle(annotated_image, (driver_box[0], driver_box[1]), (driver_box[2], driver_box[3]), (255, 0, 0), 3) # Blue (BGR: 255, 0, 0)
                # Draw Violation Label & Seatbelt Status
                cv2.putText(annotated_image, "NO SEATBELT", (driver_box[0], driver_box[1]-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                # Draw Plate Number & Timestamp
                cv2.putText(annotated_image, f"Plate: {ocr_metadata['plate_number']}", (veh_box[0], veh_box[3]+20), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)
                cv2.putText(annotated_image, f"TS: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", (veh_box[0], veh_box[3]+40), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        # Detect traffic signal state once for the entire frame to check both stop-line and red-light violations
        signal_state, signal_conf, light_box = self.traffic_light_detector.detect_traffic_light(image)

        # Check Stop-Line Violations
        all_road_vehicles = [d for d in detections if d['label'] in ['car', 'motorcycle', 'truck', 'bus']]
        for veh in all_road_vehicles:
            veh_box = veh['box']
            is_stopline_violation, sl_conf, sl_details = self.traffic_light_detector.check_stop_line_violation(
                image,
                veh_box,
                veh.get('label', 'vehicle'),
                camera_id=camera_id,
                detection_confidence=veh.get('confidence', 0.90),
                signal_state=signal_state,
                signal_confidence=signal_conf
            )

            if is_stopline_violation:
                debug_id = str(uuid.uuid4())
                p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, veh_box, debug_name=debug_id)
                ocr_metadata_sl = {
                    "plate_number": p_num if o_conf >= 0.50 else "UNKNOWN",
                    "ocr_confidence": o_conf,
                    "ocr_engine": ocr_debug.get("ocr_engine", "none") if ocr_debug else "none",
                    "ocr_debug_paths": ocr_debug.get("debug_paths", {}) if ocr_debug else {},
                    "plate_crop_path": (ocr_debug.get("debug_paths", {}) or {}).get("plate_crop", ""),
                    "enhanced_plate_path": (ocr_debug.get("debug_paths", {}) or {}).get("enhanced_plate", ""),
                    "ocr_result_path": (ocr_debug.get("debug_paths", {}) or {}).get("ocr_result", ""),
                    "ocr_attempts": ocr_debug.get("ocr_attempts", []) if ocr_debug else []
                }

                violations.append({
                    "type": "STOP_LINE_VIOLATION",
                    "box": veh_box,
                    "confidence": sl_conf,
                    "details": (
                        f"{veh.get('label', 'Vehicle').title()} front bumper crossed configured stop line "
                        f"by {sl_details['crossing_distance_px']:.0f}px"
                    ),
                    "front_bumper": sl_details["front_bumper"],
                    "stop_line": sl_details["stop_line"],
                    "crossing_ratio": sl_details["crossing_ratio"],
                    "crossing_distance_px": sl_details["crossing_distance_px"],
                    **ocr_metadata_sl
                })

                annotated_image = self.traffic_light_detector.annotate_stop_line_violation(
                    annotated_image,
                    veh_box,
                    stop_line=sl_details["stop_line"],
                    plate_text=ocr_metadata_sl["plate_number"],
                    location=location
                )

        # Check Red-Light Violations
        if signal_state == "RED":
            all_vehicles = [d for d in detections if d['label'] in ['car', 'motorcycle', 'truck', 'bus']]
            stop_zone = self.traffic_light_detector.define_stop_zone(h, w)
            
            for veh in all_vehicles:
                veh_box = veh['box']
                is_violation, rl_conf, rl_details = self.traffic_light_detector.check_red_light_violation(
                    image, veh_box, veh['label'],
                    signal_state=signal_state, signal_confidence=signal_conf
                )
                
                if is_violation:
                    debug_id = str(uuid.uuid4())
                    p_num, o_conf, _, ocr_debug = self.ocr_engine.extract_plate_details(image, veh_box, debug_name=debug_id)
                    ocr_metadata_rl = {
                        "plate_number": p_num if o_conf >= 0.50 else "UNKNOWN",
                        "ocr_confidence": o_conf,
                        "ocr_engine": ocr_debug.get("ocr_engine", "none") if ocr_debug else "none",
                        "ocr_debug_paths": ocr_debug.get("debug_paths", {}) if ocr_debug else {},
                        "plate_crop_path": (ocr_debug.get("debug_paths", {}) or {}).get("plate_crop", ""),
                        "enhanced_plate_path": (ocr_debug.get("debug_paths", {}) or {}).get("enhanced_plate", ""),
                        "ocr_result_path": (ocr_debug.get("debug_paths", {}) or {}).get("ocr_result", ""),
                        "ocr_attempts": ocr_debug.get("ocr_attempts", []) if ocr_debug else []
                    }
                    
                    violations.append({
                        "type": "RED_LIGHT_VIOLATION",
                        "box": veh_box,
                        "confidence": rl_conf,
                        "details": f"{veh['label'].title()} crossed stop zone during RED signal (penetration: {rl_details['penetration_ratio']:.0%})",
                        "signal_confidence": rl_details['signal_confidence'],
                        "penetration_ratio": rl_details['penetration_ratio'],
                        **ocr_metadata_rl
                    })
                    
                    # Annotate red-light violation on image
                    annotated_image = self.traffic_light_detector.annotate_red_light_violation(
                        annotated_image, veh_box, light_box, stop_zone, 
                        ocr_metadata_rl['plate_number']
                    )

        processing_time = (time.perf_counter() - start_time) * 1000 # convert to ms
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
            "ocr_debug_paths": best_ocr_debug.get("debug_paths", {}) if best_ocr_debug else {},
            "helmet_debug": helmet_debug,
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
