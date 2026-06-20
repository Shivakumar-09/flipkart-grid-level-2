import cv2
import json
import logging
import numpy as np
import os

logger = logging.getLogger("TrafficLightDetector")


class TrafficLightDetector:
    """
    Traffic Light Detection and Red-Light Violation Analysis Module.
    
    Pipeline:
        1. Detect traffic light regions using HSV color filtering and contour analysis
        2. Classify signal state: RED / YELLOW / GREEN
        3. Define stop zone boundary
        4. Check if vehicles crossed stop zone during RED signal
        5. Generate RED_LIGHT_VIOLATION with confidence scoring
    
    Supported detection methods:
        - HSV Color Space Analysis (primary)
        - Circular Hough Transform (auxiliary validation)
    """

    # HSV ranges for traffic light colors (tuned for real-world conditions)
    RED_LOWER_1 = np.array([0, 100, 100])
    RED_UPPER_1 = np.array([10, 255, 255])
    RED_LOWER_2 = np.array([160, 100, 100])
    RED_UPPER_2 = np.array([180, 255, 255])
    
    YELLOW_LOWER = np.array([15, 100, 100])
    YELLOW_UPPER = np.array([35, 255, 255])
    
    GREEN_LOWER = np.array([36, 50, 50])
    GREEN_UPPER = np.array([90, 255, 255])
    
    # Stop zone is defined as a percentage of image height from the bottom
    STOP_ZONE_TOP_RATIO = 0.55   # Top boundary of stop zone (55% from top)
    STOP_ZONE_BOTTOM_RATIO = 1.0  # Bottom boundary (full bottom)

    def __init__(self):
        self.camera_config = self._load_camera_config()
        logger.info("TrafficLightDetector initialized with HSV color space analysis.")

    def _load_camera_config(self):
        """
        Load per-camera traffic geometry. Missing configs fall back to the
        detector's default frame-ratio stop line.
        """
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            config_path = os.path.join(project_root, "camera_config.json")
            if not os.path.exists(config_path):
                return {}

            with open(config_path, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load camera_config.json: {e}")
            return {}

    def detect_traffic_light(self, image, roi=None):
        """
        Detect traffic light in the image and classify its state.
        
        Args:
            image: BGR numpy array
            roi: Optional [x1, y1, x2, y2] region of interest for traffic light search
            
        Returns:
            signal_state: str ("RED", "YELLOW", "GREEN", "UNKNOWN")
            confidence: float (0.0 to 1.0)
            light_box: [x1, y1, x2, y2] bounding box of detected traffic light (or None)
        """
        h, w = image.shape[:2]
        
        # Default ROI: upper portion of image where traffic lights are typically located (restricted to top 25%)
        if roi is None:
            search_region = image[0:int(h * 0.25), :]
            roi_offset = (0, 0)
        else:
            rx1, ry1, rx2, ry2 = roi
            search_region = image[ry1:ry2, rx1:rx2]
            roi_offset = (rx1, ry1)
        
        if search_region.size == 0:
            return "UNKNOWN", 0.0, None
        
        # Convert to HSV for color-based detection
        hsv = cv2.cvtColor(search_region, cv2.COLOR_BGR2HSV)
        
        # Create masks for each color
        red_mask1 = cv2.inRange(hsv, self.RED_LOWER_1, self.RED_UPPER_1)
        red_mask2 = cv2.inRange(hsv, self.RED_LOWER_2, self.RED_UPPER_2)
        red_mask = cv2.bitwise_or(red_mask1, red_mask2)
        
        yellow_mask = cv2.inRange(hsv, self.YELLOW_LOWER, self.YELLOW_UPPER)
        green_mask = cv2.inRange(hsv, self.GREEN_LOWER, self.GREEN_UPPER)
        
        # Apply morphological operations to reduce noise
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_OPEN, kernel)
        yellow_mask = cv2.morphologyEx(yellow_mask, cv2.MORPH_OPEN, kernel)
        green_mask = cv2.morphologyEx(green_mask, cv2.MORPH_OPEN, kernel)
        
        # Calculate pixel areas for each color
        red_area = cv2.countNonZero(red_mask)
        yellow_area = cv2.countNonZero(yellow_mask)
        green_area = cv2.countNonZero(green_mask)
        
        total_area = search_region.shape[0] * search_region.shape[1]
        # Require at least 0.5% of search region AND a real circular blob
        min_area = total_area * 0.005
        
        # Determine dominant signal color
        areas = {
            "RED": red_area,
            "YELLOW": yellow_area,
            "GREEN": green_area
        }
        
        max_color = max(areas, key=areas.get)
        max_area = areas[max_color]
        
        # Ignore large yellow regions to prevent false triggers from ambient backgrounds, signs, vehicles
        if max_color == "YELLOW" and max_area > total_area * 0.05:
            logger.info(f"Traffic light: yellow region too large ({max_area}px / {total_area}px) — returning UNKNOWN to prevent false positives.")
            return "UNKNOWN", 0.0, None

        if max_area < min_area:
            logger.info("Traffic light: no dominant color area found — returning UNKNOWN")
            return "UNKNOWN", 0.0, None
        
        # CRITICAL: Validate with circular Hough Transform — must find an actual light blob
        mask = {"RED": red_mask, "YELLOW": yellow_mask, "GREEN": green_mask}[max_color]
        light_box = self._find_circular_region(mask, roi_offset)
        
        # Without a confirmed circular traffic-light region we cannot reliably say the
        # signal is RED/YELLOW/GREEN — ambient colors in the scene (buildings, vehicles,
        # posters) will otherwise cause constant false positives.
        if light_box is None:
            logger.info(
                f"Traffic light: dominant color={max_color} area={max_area}px but NO "
                f"circular blob found — returning UNKNOWN to avoid false positives."
            )
            return "UNKNOWN", 0.0, None
        
        # Calculate confidence based on dominance ratio
        total_color_area = red_area + yellow_area + green_area
        if total_color_area > 0:
            confidence = max_area / total_color_area
        else:
            confidence = 0.0
        
        # Boost confidence because we confirmed a circular region
        confidence = min(0.99, confidence + 0.15)
        # Do NOT apply an artificial floor — if confidence is low, keep it low
        confidence = min(0.99, max(0.0, float(confidence)))
        
        logger.info(f"Traffic light detected: {max_color} (confidence: {confidence:.2f}, area: {max_area}px, box: {light_box})")
        return max_color, confidence, light_box
    
    def _find_circular_region(self, mask, roi_offset):
        """
        Use contour analysis to find circular traffic light regions.
        
        Returns bounding box [x1, y1, x2, y2] in original image coordinates, or None.
        """
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None
        
        # Image dimensions for size-based filtering
        img_h, img_w = mask.shape[:2]
        max_allowed_dim = img_w * 0.12  # Traffic light blobs are small, < 12% of width

        # Find the best traffic-light-shaped contour
        best_contour = None
        best_score = 0.0
        
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 150:
                continue
            
            perimeter = cv2.arcLength(cnt, True)
            if perimeter == 0:
                continue
            
            x, y, bw, bh = cv2.boundingRect(cnt)
            
            # Reject very large blobs (cars, buildings, billboards)
            if bw > max_allowed_dim or bh > max_allowed_dim:
                continue
            
            # Aspect ratio: traffic light circles are roughly square (0.5 – 2.0)
            aspect = bw / float(bh) if bh > 0 else 0
            if not (0.5 <= aspect <= 2.0):
                continue
            
            # Height and width check: require circular bounding box dimensions strictly > 20px
            if bw <= 20 or bh <= 20:
                continue
            
            # Circularity check: 4π * area / perimeter²
            # Perfect circle ≈ 1.0; traffic lights in practice ≥ 0.60
            circularity = 4 * np.pi * area / (perimeter * perimeter)
            if circularity < 0.60:
                continue
            
            score = circularity * area  # Prefer large, circular blobs
            if score > best_score:
                best_score = score
                best_contour = cnt
        
        if best_contour is None:
            return None
        
        x, y, bw, bh = cv2.boundingRect(best_contour)
        ox, oy = roi_offset
        return [x + ox, y + oy, x + ox + bw, y + oy + bh]

    def define_stop_zone(self, image_height, image_width):
        """
        Define the stop zone boundary.
        
        In Indian traffic systems, the stop line is typically marked at a fixed distance
        from the traffic signal. For camera-based detection, we define the stop zone
        as the lower portion of the frame.
        
        Returns:
            stop_zone: dict with 'top', 'bottom', 'left', 'right' pixel coordinates
        """
        return {
            "top": int(image_height * self.STOP_ZONE_TOP_RATIO),
            "bottom": image_height,
            "left": 0,
            "right": image_width
        }

    def _scale_x(self, value, image_width):
        if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
            return int(round(float(value) * image_width))
        return int(max(0, min(image_width, float(value))))

    def _scale_y(self, value, image_height):
        if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
            return int(round(float(value) * image_height))
        return int(max(0, min(image_height, float(value))))

    def _scale_point(self, point, image_width, image_height):
        return [
            self._scale_x(point[0], image_width),
            self._scale_y(point[1], image_height)
        ]

    def get_camera_stop_line(self, camera_id, image_height, image_width):
        """
        Resolve the configured stop line or stop-line polygon for a camera.

        Supports either:
        - stop_line_y: horizontal line, normalized ratio (0..1) or pixel y.
        - stop_line_polygon: normalized or pixel points defining the violation zone.
        """
        camera_cfg = self.camera_config.get(camera_id or "", {})
        stop_cfg = camera_cfg.get("stop_line", camera_cfg)

        polygon = stop_cfg.get("stop_line_polygon")
        if polygon:
            pixel_polygon = [
                self._scale_point(point, image_width, image_height)
                for point in polygon
            ]
            if len(pixel_polygon) >= 3:
                return {
                    "type": "polygon",
                    "polygon": pixel_polygon,
                    "y": min(point[1] for point in pixel_polygon),
                    "x1": min(point[0] for point in pixel_polygon),
                    "x2": max(point[0] for point in pixel_polygon)
                }

        line_y = self._scale_y(
            stop_cfg.get("stop_line_y", self.STOP_ZONE_TOP_RATIO),
            image_height
        )
        line_x1 = self._scale_x(stop_cfg.get("stop_line_x1", 0), image_width)
        line_x2 = self._scale_x(stop_cfg.get("stop_line_x2", 1), image_width)

        return {
            "type": "line",
            "y": line_y,
            "x1": min(line_x1, line_x2),
            "x2": max(line_x1, line_x2),
            "polygon": None
        }

    def calculate_front_bumper_position(self, vehicle_box):
        """
        Estimate the front bumper for fixed CCTV road views as the bottom-center
        of the detected vehicle bounding box.
        """
        vx1, vy1, vx2, vy2 = [int(v) for v in vehicle_box]
        return int((vx1 + vx2) / 2), int(vy2)

    def is_front_bumper_past_stop_line(self, vehicle_box, stop_line):
        """
        Compare the vehicle front bumper against a line or configured polygon.

        Returns:
            crossed: bool
            crossing_ratio: float, normalized by vehicle height
            crossing_distance_px: float
        """
        vx1, vy1, vx2, vy2 = [int(v) for v in vehicle_box]
        vehicle_height = max(1, vy2 - vy1)
        front_x, front_y = self.calculate_front_bumper_position(vehicle_box)

        if stop_line.get("type") == "polygon" and stop_line.get("polygon"):
            polygon = np.array(stop_line["polygon"], dtype=np.int32)
            inside = cv2.pointPolygonTest(polygon, (float(front_x), float(front_y)), False) >= 0
            if inside:
                crossing_distance = max(1.0, float(front_y - stop_line["y"]))
                crossing_ratio = min(1.0, crossing_distance / vehicle_height)
                return True, crossing_ratio, crossing_distance
            return False, 0.0, 0.0

        line_y = int(stop_line["y"])
        within_line_span = stop_line["x1"] <= front_x <= stop_line["x2"]
        crossing_distance = float(front_y - line_y)

        if within_line_span and crossing_distance > 0:
            crossing_ratio = min(1.0, crossing_distance / vehicle_height)
            return True, crossing_ratio, crossing_distance

        return False, 0.0, max(0.0, crossing_distance)

    def check_stop_line_violation(self, image, vehicle_box, vehicle_label="car",
                                  camera_id="CAM_BLR_001", detection_confidence=0.90,
                                  mock_result=None, signal_state="RED",
                                  signal_confidence=0.90):
        """
        Detect whether a vehicle's front bumper has crossed the configured
        camera stop line during a RED traffic signal.
        """
        h, w = image.shape[:2]

        # Stop-line violation only occurs if the signal is RED
        # AND we have a high-confidence signal detection (>= 0.65).
        # This guards against false positives from ambient red colors in the scene.
        signal_is_confirmed_red = (
            signal_state == "RED" and float(signal_confidence or 0.0) >= 0.65
        )
        if not signal_is_confirmed_red and mock_result is None:
            stop_line = self.get_camera_stop_line(camera_id, h, w)
            front_x, front_y = self.calculate_front_bumper_position(vehicle_box)
            logger.info(
                f"Stop-line check skipped: signal_state={signal_state!r} "
                f"signal_conf={float(signal_confidence or 0.0):.2f} (need RED >= 0.65)"
            )
            return False, 0.0, {
                "camera_id": camera_id,
                "vehicle_label": vehicle_label,
                "front_bumper": [front_x, front_y],
                "stop_line": stop_line,
                "stop_line_crossed": False,
                "crossing_ratio": 0.0,
                "crossing_distance_px": 0.0
            }

        if mock_result is not None:
            conf = 0.82 + (np.random.random() * 0.15)
            stop_line = self.get_camera_stop_line(camera_id, h, w)
            front_x, front_y = self.calculate_front_bumper_position(vehicle_box)
            return mock_result, float(conf if mock_result else 0.0), {
                "camera_id": camera_id,
                "vehicle_label": vehicle_label,
                "front_bumper": [front_x, front_y],
                "stop_line": stop_line,
                "stop_line_crossed": bool(mock_result),
                "crossing_ratio": 0.65 if mock_result else 0.0,
                "crossing_distance_px": 45.0 if mock_result else 0.0
            }

        stop_line = self.get_camera_stop_line(camera_id, h, w)
        front_x, front_y = self.calculate_front_bumper_position(vehicle_box)
        crossed, crossing_ratio, crossing_distance = self.is_front_bumper_past_stop_line(
            vehicle_box, stop_line
        )

        details = {
            "camera_id": camera_id,
            "vehicle_label": vehicle_label,
            "front_bumper": [front_x, front_y],
            "stop_line": stop_line,
            "stop_line_crossed": crossed,
            "crossing_ratio": float(crossing_ratio),
            "crossing_distance_px": float(crossing_distance)
        }

        if crossed:
            det_conf = float(detection_confidence or 0.90)
            confidence = min(0.99, (det_conf * 0.50) + (crossing_ratio * 0.35) + 0.15)
            confidence = max(0.72, confidence)
            return True, float(confidence), details

        return False, 0.0, details

    def is_vehicle_in_stop_zone(self, vehicle_box, stop_zone):
        """
        Check if a vehicle has crossed into the stop zone.
        
        A vehicle is considered to have crossed the stop zone if the bottom edge
        of its bounding box is beyond the stop zone top boundary.
        
        Args:
            vehicle_box: [x1, y1, x2, y2] vehicle bounding box
            stop_zone: dict with zone boundaries
            
        Returns:
            crossed: bool
            penetration_ratio: float (0.0 to 1.0, how far into the zone)
        """
        vx1, vy1, vx2, vy2 = vehicle_box
        vh = vy2 - vy1
        
        zone_top = stop_zone["top"]
        zone_bottom = stop_zone["bottom"]
        zone_height = zone_bottom - zone_top
        
        # Vehicle center Y position
        v_center_y = (vy1 + vy2) / 2.0
        
        # Check if center or bottom of vehicle is in the stop zone
        if v_center_y > zone_top:
            # Calculate penetration depth
            penetration = min(vy2, zone_bottom) - zone_top
            penetration_ratio = min(1.0, penetration / zone_height)
            return True, penetration_ratio
        
        return False, 0.0

    def check_red_light_violation(self, image, vehicle_box, vehicle_label="car", 
                                   signal_state=None, signal_confidence=None, mock_result=None):
        """
        Full red-light violation check pipeline for a single vehicle.
        
        Args:
            image: BGR numpy array
            vehicle_box: [x1, y1, x2, y2]
            vehicle_label: vehicle class label
            signal_state: Pre-computed signal state (skip detection if provided)
            signal_confidence: Pre-computed signal confidence
            mock_result: Override for testing (True = violation, False = no violation)
            
        Returns:
            is_violation: bool
            confidence: float
            details: dict with signal_state, stop_zone_crossed, penetration_ratio
        """
        h, w = image.shape[:2]
        
        # Mock override for testing/seeding
        if mock_result is not None:
            conf = 0.80 + (np.random.random() * 0.19)
            return mock_result, float(conf), {
                "signal_state": "RED" if mock_result else "GREEN",
                "signal_confidence": float(conf),
                "stop_zone_crossed": mock_result,
                "penetration_ratio": 0.75 if mock_result else 0.0,
                "vehicle_label": vehicle_label
            }
        
        # Step 1: Detect traffic light if not pre-computed
        if signal_state is None:
            signal_state, signal_confidence = self.detect_traffic_light(image)[:2]
        
        # Step 2: Only check for violations if signal is RED
        if signal_state != "RED":
            return False, 0.0, {
                "signal_state": signal_state,
                "signal_confidence": signal_confidence or 0.0,
                "stop_zone_crossed": False,
                "penetration_ratio": 0.0,
                "vehicle_label": vehicle_label
            }
        
        # Step 3: Define stop zone and check vehicle position
        stop_zone = self.define_stop_zone(h, w)
        crossed, penetration_ratio = self.is_vehicle_in_stop_zone(vehicle_box, stop_zone)
        
        if crossed and penetration_ratio > 0.15:
            # Violation detected: RED signal + vehicle crossed stop zone
            # Confidence combines signal detection confidence and penetration depth
            violation_confidence = min(0.99, (signal_confidence * 0.6) + (penetration_ratio * 0.35) + 0.05)
            violation_confidence = max(0.70, violation_confidence)
            
            return True, float(violation_confidence), {
                "signal_state": "RED",
                "signal_confidence": float(signal_confidence),
                "stop_zone_crossed": True,
                "penetration_ratio": float(penetration_ratio),
                "vehicle_label": vehicle_label
            }
        
        return False, 0.0, {
            "signal_state": "RED",
            "signal_confidence": float(signal_confidence),
            "stop_zone_crossed": crossed,
            "penetration_ratio": float(penetration_ratio),
            "vehicle_label": vehicle_label
        }

    def annotate_red_light_violation(self, image, vehicle_box, light_box=None, 
                                       stop_zone=None, plate_text="UNKNOWN"):
        """
        Draw red-light violation annotations on the image.
        
        Args:
            image: BGR numpy array (will be modified in-place)
            vehicle_box: [x1, y1, x2, y2]
            light_box: Optional [x1, y1, x2, y2] traffic light bounding box
            stop_zone: Optional stop zone dict
            plate_text: Detected plate number
            
        Returns:
            annotated_image: BGR numpy array with annotations
        """
        h, w = image.shape[:2]
        annotated = image.copy()
        
        vx1, vy1, vx2, vy2 = vehicle_box
        
        # Draw vehicle bounding box (Crimson Red)
        cv2.rectangle(annotated, (vx1, vy1), (vx2, vy2), (0, 0, 220), 3)
        
        # Draw RED LIGHT VIOLATION label
        cv2.putText(annotated, "RED LIGHT VIOLATION", (vx1, vy1 - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 220), 2)
        
        # Draw plate number
        cv2.putText(annotated, f"Plate: {plate_text}", (vx1, vy2 + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
        
        # Draw traffic light box if detected
        if light_box is not None:
            lx1, ly1, lx2, ly2 = light_box
            cv2.rectangle(annotated, (lx1, ly1), (lx2, ly2), (0, 0, 255), 2)
            cv2.putText(annotated, "RED SIGNAL", (lx1, ly1 - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        # Draw stop zone line
        if stop_zone is None:
            stop_zone = self.define_stop_zone(h, w)
        
        zone_top = stop_zone["top"]
        cv2.line(annotated, (0, zone_top), (w, zone_top), (0, 255, 255), 2)
        cv2.putText(annotated, "STOP LINE", (10, zone_top - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        
        # Timestamp
        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(annotated, f"TS: {ts}", (vx1, vy2 + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
        
        return annotated

    def annotate_stop_line_violation(self, image, vehicle_box, stop_line=None,
                                      plate_text="UNKNOWN", location="UNKNOWN"):
        """
        Draw stop-line evidence: configured line/zone, vehicle box, label,
        timestamp, and location.
        """
        h, w = image.shape[:2]
        annotated = image.copy()
        vx1, vy1, vx2, vy2 = [int(v) for v in vehicle_box]

        if stop_line is None:
            stop_line = self.get_camera_stop_line("CAM_BLR_001", h, w)

        line_color = (0, 255, 255)
        violation_color = (255, 0, 255)

        if stop_line.get("type") == "polygon" and stop_line.get("polygon"):
            polygon = np.array(stop_line["polygon"], dtype=np.int32)
            overlay = annotated.copy()
            cv2.fillPoly(overlay, [polygon], (0, 255, 255))
            annotated = cv2.addWeighted(overlay, 0.18, annotated, 0.82, 0)
            cv2.polylines(annotated, [polygon], True, line_color, 3)
            label_x, label_y = polygon[0]
        else:
            y = int(stop_line["y"])
            x1 = int(stop_line.get("x1", 0))
            x2 = int(stop_line.get("x2", w))
            cv2.line(annotated, (x1, y), (x2, y), line_color, 3)
            label_x, label_y = x1 + 10, y

        cv2.putText(annotated, "STOP LINE", (max(10, label_x), max(25, label_y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, line_color, 2)

        cv2.rectangle(annotated, (vx1, vy1), (vx2, vy2), violation_color, 3)
        cv2.putText(annotated, "STOP-LINE VIOLATION", (vx1, max(25, vy1 - 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, violation_color, 2)

        front_x, front_y = self.calculate_front_bumper_position(vehicle_box)
        cv2.circle(annotated, (front_x, front_y), 5, (255, 255, 255), -1)
        cv2.putText(annotated, "Front bumper", (front_x + 8, min(h - 10, front_y + 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        from datetime import datetime
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(annotated, f"Plate: {plate_text}", (vx1, min(h - 45, vy2 + 25)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 2)
        cv2.putText(annotated, f"TS: {ts}", (10, h - 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)
        cv2.putText(annotated, f"Location: {location}", (10, h - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 200, 255), 2)

        return annotated
