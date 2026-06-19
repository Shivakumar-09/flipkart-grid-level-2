import cv2
import os
import re
import logging
import shutil
import numpy as np

logger = logging.getLogger("OcrEngine")

YOLOV8_ALPR_REPO = "Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8"


class OcrEngine:
    MIN_ACCEPT_CONFIDENCE = 0.50
    STATE_CODES = {
        "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN", "GA", "GJ",
        "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD", "MH", "ML", "MN", "MP",
        "MZ", "NL", "OD", "OR", "PB", "PY", "RJ", "SK", "TN", "TR", "TS", "UK",
        "UP", "WB"
    }

    def __init__(self):
        self.easy_reader = None
        self.paddle_reader = None
        self.easy_loaded = False
        self.paddle_loaded = False
        self.plate_model = None
        self.plate_model_path = ""
        self.plate_model_source = ""
        self.plate_model_error = ""
        self.paddle_error = ""
        self.last_debug = {}

        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.outputs_dir = os.path.join(self.project_root, "outputs")
        self.debug_dir = os.path.join(self.project_root, "ocr_debug")
        self.outputs_debug_dir = os.path.join(self.outputs_dir, "ocr_debug")
        os.makedirs(self.outputs_dir, exist_ok=True)
        os.makedirs(self.debug_dir, exist_ok=True)
        os.makedirs(self.outputs_debug_dir, exist_ok=True)

        try:
            import easyocr
            import warnings
            # Suppress easyocr CPU usage warning and other logs
            logging.getLogger('easyocr').setLevel(logging.ERROR)
            warnings.filterwarnings("ignore", category=UserWarning)
            self.easy_reader = easyocr.Reader(["en"], gpu=False)
            self.easy_loaded = True
            logger.info("EasyOCR engine initialized successfully.")
        except Exception as e:
            logger.warning(f"Could not load EasyOCR: {e}. EasyOCR attempts disabled.")

        try:
            from paddleocr import PaddleOCR
            try:
                self.paddle_reader = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            except TypeError:
                self.paddle_reader = PaddleOCR(use_angle_cls=True, lang="en")
            self.paddle_loaded = True
            logger.info("PaddleOCR engine initialized successfully.")
        except Exception as e:
            self.paddle_error = str(e)
            logger.info(f"Could not load PaddleOCR: {e}. PaddleOCR attempts disabled.")

        self._load_plate_detector()

    def _load_plate_detector(self):
        try:
            from ultralytics import YOLO
        except Exception as e:
            self.plate_model_error = f"ultralytics import failed: {e}"
            logger.error(self.plate_model_error)
            return

        detector_candidates = [
            (
                "license_plate_detector.pt",
                f"{YOLOV8_ALPR_REPO}: license_plate_detector.pt"
            ),
            (
                "yolov8n_license_plate.pt",
                "legacy local plate detector"
            ),
        ]

        errors = []
        for filename, source in detector_candidates:
            plate_model_path = os.path.join(self.project_root, filename)
            if not os.path.exists(plate_model_path):
                errors.append(f"{filename}: missing")
                continue
            try:
                self.plate_model = YOLO(plate_model_path)
                self.plate_model_path = plate_model_path
                self.plate_model_source = source
                self.plate_model_error = ""
                logger.info(f"YOLOv8 license plate model loaded from {filename} ({source}).")
                return
            except Exception as e:
                errors.append(f"{filename}: {e}")

        self.plate_model = None
        self.plate_model_error = "; ".join(errors) or "no plate detector candidates configured"
        logger.error(f"Failed to load YOLOv8 license plate model: {self.plate_model_error}")

    def extract_plate(self, image, vehicle_box):
        """
        Backward-compatible wrapper used by older code.
        Returns (plate_text, confidence, cropped_plate).
        """
        text, confidence, cropped_plate, _ = self.extract_plate_details(image, vehicle_box)
        return text, confidence, cropped_plate

    def extract_plate_details(self, image, vehicle_box, debug_name=None):
        """
        Vehicle -> plate localization -> enhancement -> EasyOCR/PaddleOCR comparison.
        Returns (plate_text, confidence, cropped_plate, diagnostics).
        """
        diagnostics = self._new_diagnostics(image, vehicle_box)
        run_debug_dir, run_outputs_debug_dir = self._prepare_debug_dirs(debug_name)

        if image is None or image.size == 0:
            diagnostics["failure_reason"] = "invalid_image"
            self.last_debug = diagnostics
            return "UNKNOWN", 0.0, None, diagnostics

        self._save_debug_image("original_image.jpg", image, run_debug_dir, run_outputs_debug_dir)

        h, w = image.shape[:2]
        clipped_vehicle_box = self._clip_box(vehicle_box, w, h)
        if clipped_vehicle_box is None:
            diagnostics["failure_reason"] = "invalid_vehicle_box"
            self.last_debug = diagnostics
            return "UNKNOWN", 0.0, None, diagnostics

        x1, y1, x2, y2 = clipped_vehicle_box
        diagnostics["vehicle_box"] = clipped_vehicle_box
        vehicle_crop = image[y1:y2, x1:x2]
        if vehicle_crop.size == 0:
            diagnostics["failure_reason"] = "empty_vehicle_crop"
            self.last_debug = diagnostics
            return "UNKNOWN", 0.0, None, diagnostics

        diagnostics["vehicle_crop_dimensions"] = self._dimensions(vehicle_crop)
        self._save_debug_image("vehicle_crop.jpg", vehicle_crop, run_debug_dir, run_outputs_debug_dir)

        candidates = self._detect_plate_candidates(vehicle_crop)
        diagnostics["plate_candidates"] = [
            {
                "box": item["box"],
                "source": item["source"],
                "score": round(float(item.get("score", 0.0)), 4),
                "confidence": round(float(item.get("confidence", 0.0)), 4)
            }
            for item in candidates[:10]
        ]

        if not candidates:
            candidates = self._default_plate_candidates(vehicle_crop)
            diagnostics["plate_candidates"] = [
                {"box": item["box"], "source": item["source"], "score": item["score"], "confidence": 0.0}
                for item in candidates
            ]

        best = self._evaluate_plate_candidates(vehicle_crop, candidates)

        if best["crop"] is not None and best["crop"].size > 0:
            self._save_debug_image("plate_crop.jpg", best["crop"], run_debug_dir, run_outputs_debug_dir)
            diagnostics["plate_dimensions"] = self._dimensions(best["crop"])
            diagnostics["crop_dimensions"] = self._dimensions(best["crop"])

        if best["enhanced"] is not None and best["enhanced"].size > 0:
            self._save_debug_image("enhanced_plate.jpg", best["enhanced"], run_debug_dir, run_outputs_debug_dir)
            diagnostics["enhanced_dimensions"] = self._dimensions(best["enhanced"])

        overlay = self._build_ocr_overlay(image, clipped_vehicle_box, best)
        self._save_debug_image("ocr_result.jpg", overlay, run_debug_dir, run_outputs_debug_dir)

        diagnostics["detector"] = best.get("source", "none")
        diagnostics["plate_box"] = best.get("box")
        diagnostics["plate_detection_confidence"] = float(best.get("plate_confidence", 0.0))
        diagnostics["ocr_confidence"] = float(best.get("confidence", 0.0))
        diagnostics["ocr_engine"] = best.get("engine", "none")
        diagnostics["raw_text"] = best.get("raw_text", "")
        diagnostics["detected_text_before_threshold"] = best.get("text", "")
        diagnostics["ocr_attempts"] = best.get("attempts", [])[:30]
        diagnostics["ocr_engines"] = self._summarize_engine_attempts(best.get("attempts", []))
        diagnostics["debug_paths"] = self._debug_paths(debug_name)

        selected_text = best.get("text", "")
        selected_confidence = float(best.get("confidence", 0.0))
        if not selected_text:
            diagnostics["failure_reason"] = "no_ocr_text_detected"
            selected_text = "UNKNOWN"
            selected_confidence = 0.0
        elif not self._is_valid_plate(selected_text):
            diagnostics["failure_reason"] = "ocr_text_does_not_match_indian_plate_format"
            selected_text = "UNKNOWN"
            selected_confidence = 0.0
        elif selected_confidence < self.MIN_ACCEPT_CONFIDENCE:
            diagnostics["failure_reason"] = "ocr_confidence_below_0.50"
            selected_text = "UNKNOWN"
            selected_confidence = 0.0
        else:
            diagnostics["failure_reason"] = "accepted"

        diagnostics["selected_text"] = selected_text
        diagnostics["selected_confidence"] = selected_confidence
        self.last_debug = diagnostics
        return selected_text, selected_confidence, best.get("crop"), diagnostics

    def _new_diagnostics(self, image, vehicle_box):
        return {
            "original_dimensions": self._dimensions(image) if image is not None else None,
            "vehicle_box": [int(v) for v in vehicle_box] if vehicle_box is not None else None,
            "vehicle_crop_dimensions": None,
            "plate_box": None,
            "plate_dimensions": None,
            "crop_dimensions": None,
            "enhanced_dimensions": None,
            "detector": "none",
            "plate_detection_confidence": 0.0,
            "ocr_confidence": 0.0,
            "ocr_engine": "none",
            "ocr_engines": {
                "easyocr": {"available": self.easy_loaded},
                "paddleocr": {"available": self.paddle_loaded, "error": self.paddle_error}
            },
            "ocr_attempts": [],
            "raw_text": "",
            "detected_text_before_threshold": "",
            "selected_text": "UNKNOWN",
            "selected_confidence": 0.0,
            "failure_reason": "",
            "plate_model_error": self.plate_model_error,
            "plate_model_path": self.plate_model_path,
            "plate_model_source": self.plate_model_source,
            "debug_paths": self._debug_paths(None)
        }

    def _prepare_debug_dirs(self, debug_name):
        if not debug_name:
            return self.debug_dir, self.outputs_debug_dir

        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", debug_name).strip("_") or "run"
        run_debug_dir = os.path.join(self.debug_dir, safe_name)
        run_outputs_debug_dir = os.path.join(self.outputs_debug_dir, safe_name)
        os.makedirs(run_debug_dir, exist_ok=True)
        os.makedirs(run_outputs_debug_dir, exist_ok=True)
        return run_debug_dir, run_outputs_debug_dir

    def _debug_paths(self, debug_name):
        prefix = "outputs/ocr_debug"
        if debug_name:
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", debug_name).strip("_") or "run"
            prefix = f"{prefix}/{safe_name}"

        return {
            "original_image": f"{prefix}/original_image.jpg",
            "vehicle_crop": f"{prefix}/vehicle_crop.jpg",
            "plate_crop": f"{prefix}/plate_crop.jpg",
            "enhanced_plate": f"{prefix}/enhanced_plate.jpg",
            "ocr_result": f"{prefix}/ocr_result.jpg",
            "legacy_vehicle_crop": "outputs/vehicle_crop.jpg",
            "legacy_plate_crop": "outputs/plate_crop.jpg",
            "legacy_enhanced_plate": "outputs/enhanced_plate.jpg"
        }

    def _save_debug_image(self, filename, image, debug_dir=None, outputs_debug_dir=None):
        if image is None or image.size == 0:
            return

        cv2.imwrite(os.path.join(self.project_root, filename), image)
        cv2.imwrite(os.path.join(self.outputs_dir, filename), image)

        if debug_dir:
            cv2.imwrite(os.path.join(debug_dir, filename), image)
        if outputs_debug_dir:
            cv2.imwrite(os.path.join(outputs_debug_dir, filename), image)

    def _dimensions(self, image):
        if image is None:
            return None
        h, w = image.shape[:2]
        return {"width": int(w), "height": int(h)}

    def _clip_box(self, box, width, height):
        if box is None or len(box) != 4:
            return None
        x1, y1, x2, y2 = [int(round(float(v))) for v in box]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(width, x2), min(height, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        return [x1, y1, x2, y2]

    def _crop_with_padding(self, image, box, padding_ratio=0.08):
        h, w = image.shape[:2]
        x1, y1, x2, y2 = box
        pad_x = int((x2 - x1) * padding_ratio)
        pad_y = int((y2 - y1) * padding_ratio)
        clipped = self._clip_box([x1 - pad_x, y1 - pad_y, x2 + pad_x, y2 + pad_y], w, h)
        if clipped is None:
            return None
        cx1, cy1, cx2, cy2 = clipped
        return image[cy1:cy2, cx1:cx2]

    def _detect_plate_candidates(self, vehicle_crop):
        candidates = []
        candidates.extend(self._detect_yolo_plate_candidates(vehicle_crop))
        candidates.extend(self._find_plate_candidates(vehicle_crop))
        candidates.extend(self._default_plate_candidates(vehicle_crop))
        return self._dedupe_plate_candidates(candidates)

    def _detect_yolo_plate_candidates(self, vehicle_crop):
        candidates = []
        if self.plate_model is None:
            return candidates

        try:
            results = self.plate_model(vehicle_crop, verbose=False)
            if not results:
                return candidates
            for box in results[0].boxes:
                conf = float(box.conf[0].item())
                xyxy = box.xyxy[0].cpu().numpy().tolist()
                clipped = self._clip_box(xyxy, vehicle_crop.shape[1], vehicle_crop.shape[0])
                if clipped is None:
                    continue
                candidates.append({
                    "box": clipped,
                    "source": "yolov8_license_plate",
                    "score": 10.0 + conf,
                    "confidence": conf,
                    "padding": 0.08
                })
        except Exception as e:
            self.plate_model_error = str(e)
            logger.error(f"YOLOv8 license plate detection failed: {e}")
        return candidates

    def _find_plate_candidates(self, vehicle_crop):
        h, w = vehicle_crop.shape[:2]
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
        candidates = []

        self._add_white_plate_candidates(candidates, vehicle_crop)
        self._add_edge_plate_candidates(candidates, vehicle_crop)
        self._add_text_plate_candidates(candidates, vehicle_crop)

        # Bright rectangle pass tuned for rear plates in road scenes.
        hsv = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 140), (180, 100, 255))
        mask[:int(h * 0.24), :] = 0
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 7)), iterations=1)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, box_w, box_h = cv2.boundingRect(contour)
            pad_x = max(8, int(box_w * 0.22))
            pad_y = max(6, int(box_h * 0.25))
            self._add_plate_candidate(
                candidates,
                vehicle_crop,
                [x - pad_x, y - pad_y, x + box_w + pad_x, y + box_h + pad_y],
                source="white_region",
                contour_area=cv2.contourArea(contour)
            )

        # Legacy-style blackhat text pass retained as a lower-priority detector.
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5)))
        _, text_mask = cv2.threshold(blackhat, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        text_mask[:int(h * 0.24), :] = 0
        text_mask = cv2.dilate(text_mask, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 7)), iterations=1)
        contours, _ = cv2.findContours(text_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, box_w, box_h = cv2.boundingRect(contour)
            pad_x = max(22, int(box_w * 0.90))
            pad_y = max(14, int(box_h * 0.85))
            self._add_plate_candidate(
                candidates,
                vehicle_crop,
                [x - pad_x, y - pad_y, x + box_w + pad_x, y + box_h + pad_y],
                source="blackhat_text",
                contour_area=cv2.contourArea(contour)
            )

        return candidates

    def _add_white_plate_candidates(self, candidates, vehicle_crop):
        h, w = vehicle_crop.shape[:2]
        hsv = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)

        for low_value, max_sat in [(150, 85), (130, 70), (170, 125)]:
            mask = cv2.inRange(hsv, (0, 0, low_value), (180, max_sat, 255))
            mask[:int(h * 0.28), :] = 0
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (19, 9)), iterations=1)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            for contour in contours:
                x, y, box_w, box_h = cv2.boundingRect(contour)
                if box_w * box_h > w * h * 0.10:
                    continue
                roi = gray[y:y + box_h, x:x + box_w]
                if roi.size == 0:
                    continue
                if float(roi.std()) < 18:
                    continue
                self._add_plate_candidate(
                    candidates,
                    vehicle_crop,
                    [x - int(box_w * 0.18), y - int(box_h * 0.22), x + int(box_w * 1.18), y + int(box_h * 1.22)],
                    source="white_plate",
                    contour_area=cv2.contourArea(contour)
                )

    def _add_edge_plate_candidates(self, candidates, vehicle_crop):
        h, w = vehicle_crop.shape[:2]
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        blur = cv2.bilateralFilter(clahe, 7, 60, 60)
        edges = cv2.Canny(blur, 40, 130)
        edges[:int(h * 0.25), :] = 0

        for kernel_size in [(21, 9), (17, 11), (9, 17), (33, 9), (11, 11)]:
            closed = cv2.morphologyEx(
                edges,
                cv2.MORPH_CLOSE,
                cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size),
                iterations=1
            )
            contours, _ = cv2.findContours(closed, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, box_w, box_h = cv2.boundingRect(contour)
                pad = max(3, int(min(box_w, box_h) * 0.08))
                self._add_plate_candidate(
                    candidates,
                    vehicle_crop,
                    [x - pad, y - pad, x + box_w + pad, y + box_h + pad],
                    source="edge_rectangle",
                    contour_area=cv2.contourArea(contour)
                )

    def _add_text_plate_candidates(self, candidates, vehicle_crop):
        h, w = vehicle_crop.shape[:2]
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)

        # Dark-character grouping: useful when the white plate body is broken by perspective/glare.
        dark = cv2.inRange(gray, 0, 105)
        dark[:int(h * 0.28), :] = 0
        dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
        dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 7)), iterations=1)
        contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x, y, box_w, box_h = cv2.boundingRect(contour)
            if box_w * box_h > w * h * 0.09:
                continue
            self._add_plate_candidate(
                candidates,
                vehicle_crop,
                [x - int(box_w * 0.55), y - int(box_h * 0.65), x + int(box_w * 1.55), y + int(box_h * 1.45)],
                source="dark_text",
                contour_area=cv2.contourArea(contour)
            )

    def _default_plate_candidates(self, vehicle_crop):
        h, w = vehicle_crop.shape[:2]
        boxes = [
            # Front motorcycle/scooter plates below the headlamp.
            ([int(w * 0.14), int(h * 0.34), int(w * 0.82), int(h * 0.61)], "front_center_plate", 8.0),
            ([int(w * 0.18), int(h * 0.36), int(w * 0.80), int(h * 0.58)], "front_tight_plate", 8.4),
            # Rear motorcycle plates in traffic scenes.
            ([int(w * 0.08), int(h * 0.58), int(w * 0.62), int(h * 0.90)], "rear_left_plate", 7.6),
            ([int(w * 0.18), int(h * 0.58), int(w * 0.82), int(h * 0.92)], "rear_center_plate", 7.2),
            ([int(w * 0.05), int(h * 0.68), int(w * 0.62), int(h * 0.96)], "rear_low_plate", 7.0),
            # Cars/trucks/auto-rickshaws.
            ([int(w * 0.25), int(h * 0.56), int(w * 0.78), int(h * 0.82)], "four_wheeler_center_plate", 6.8),
            ([int(w * 0.30), int(h * 0.62), int(w * 0.88), int(h * 0.90)], "four_wheeler_low_plate", 6.6),
        ]

        candidates = []
        for box, source, score in boxes:
            clipped = self._clip_box(box, w, h)
            if clipped is not None:
                candidates.append({
                    "box": clipped,
                    "source": source,
                    "score": score,
                    "confidence": 0.0,
                    "padding": 0.02
                })
        return candidates

    def _add_plate_candidate(self, candidates, vehicle_crop, box, source, contour_area=0.0):
        h, w = vehicle_crop.shape[:2]
        clipped = self._clip_box(box, w, h)
        if clipped is None:
            return

        x1, y1, x2, y2 = clipped
        box_w, box_h = x2 - x1, y2 - y1
        area = box_w * box_h
        if box_w < max(30, int(w * 0.045)) or box_h < max(16, int(h * 0.025)):
            return
        if area < w * h * 0.0012 or area > w * h * 0.18:
            return
        if y1 < h * 0.28:
            return

        aspect_ratio = box_w / float(max(box_h, 1))
        if not 0.45 <= aspect_ratio <= 5.8:
            return

        roi = vehicle_crop[y1:y2, x1:x2]
        if roi.size == 0:
            return
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        mean = float(gray_roi.mean())
        std = float(gray_roi.std())
        edges = cv2.Canny(gray_roi, 40, 130)
        edge_density = float(np.count_nonzero(edges)) / max(1, area)
        bright_ratio = float(np.count_nonzero(gray_roi > 145)) / max(1, area)
        dark_ratio = float(np.count_nonzero(gray_roi < 90)) / max(1, area)

        aspect_targets = [1.0, 1.55, 1.9, 2.6, 4.2]
        aspect_score = max(max(0.0, 1.0 - abs(aspect_ratio - target) / target) for target in aspect_targets)

        score = 0.0
        score += 1.65 * aspect_score
        score += 1.15 * min(std / 75.0, 1.0)
        score += 0.90 * min(edge_density * 5.0, 1.0)
        score += 0.85 * min(bright_ratio * 1.6, 1.0)
        score += 0.40 * min(max((mean - 95.0) / 130.0, 0.0), 1.0)
        score += 0.25 * (y1 / max(h, 1))
        score += 0.25 * min(contour_area / max(area, 1), 1.0)

        if 0.04 <= dark_ratio <= 0.62:
            score += 0.75
        if source in {"white_plate", "dark_text", "blackhat_text"}:
            score += 0.35
        if source == "edge_rectangle":
            score += 0.15
        if y2 > h * 0.97 and box_h < h * 0.10:
            score -= 1.3
        if area < w * h * 0.006:
            score -= 1.4
        if area > w * h * 0.10:
            score -= 0.8
        if bright_ratio < 0.08 and mean < 90:
            score -= 1.0

        candidates.append({
            "score": float(score),
            "box": clipped,
            "source": source,
            "confidence": 0.0,
            "padding": 0.08
        })

    def _dedupe_plate_candidates(self, candidates):
        deduped = []
        for candidate in sorted(candidates, key=lambda item: item.get("score", 0.0), reverse=True):
            x1, y1, x2, y2 = candidate["box"]
            area = (x2 - x1) * (y2 - y1)
            keep = True
            for selected in deduped:
                sx1, sy1, sx2, sy2 = selected["box"]
                inter_x1 = max(x1, sx1)
                inter_y1 = max(y1, sy1)
                inter_x2 = min(x2, sx2)
                inter_y2 = min(y2, sy2)
                inter_area = max(0, inter_x2 - inter_x1) * max(0, inter_y2 - inter_y1)
                selected_area = (sx2 - sx1) * (sy2 - sy1)
                union = area + selected_area - inter_area
                if inter_area / max(union, 1) > 0.42:
                    keep = False
                    break
            if keep:
                deduped.append(candidate)
            if len(deduped) >= 8:
                break
        return deduped

    def _evaluate_plate_candidates(self, vehicle_crop, candidates):
        best = {
            "text": "",
            "raw_text": "",
            "confidence": 0.0,
            "rank": 0.0,
            "engine": "none",
            "variant": "",
            "box": None,
            "source": "none",
            "plate_confidence": 0.0,
            "crop": None,
            "enhanced": None,
            "attempts": []
        }

        if not self.easy_loaded and not self.paddle_loaded:
            if candidates:
                crop = self._crop_with_padding(vehicle_crop, candidates[0]["box"], candidates[0].get("padding", 0.04))
                best.update({
                    "box": candidates[0]["box"],
                    "source": candidates[0]["source"],
                    "plate_confidence": candidates[0].get("confidence", 0.0),
                    "crop": crop,
                    "enhanced": crop,
                })
            return best

        # Fast Pass: Evaluate the top 3 candidates using only 3 primary variants.
        # This keeps the execution time under 5-10 seconds for clear images.
        for candidate in candidates[:3]:
            crop = self._crop_with_padding(vehicle_crop, candidate["box"], candidate.get("padding", 0.06))
            if crop is None or crop.size == 0:
                continue

            corrected_crop = self._perspective_correct(crop)
            corrected = self._upscale_if_needed(corrected_crop)
            gray = cv2.cvtColor(corrected, cv2.COLOR_BGR2GRAY) if len(corrected.shape) == 3 else corrected
            gray = cv2.copyMakeBorder(gray, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
            color_padded = cv2.copyMakeBorder(corrected, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            
            clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(gray)
            denoised = cv2.bilateralFilter(clahe, 7, 50, 50)
            sharp_kernel = np.array([[0, -1, 0], [-1, 5.4, -1], [0, -1, 0]], dtype=np.float32)
            sharpened = cv2.filter2D(denoised, -1, sharp_kernel)
            contrast = cv2.convertScaleAbs(sharpened, alpha=1.22, beta=8)
            
            block = max(21, (min(contrast.shape[:2]) // 6) * 2 + 1)
            adaptive = cv2.adaptiveThreshold(contrast, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 9)
            adaptive = self._ensure_dark_text_on_light(adaptive)
            
            primary_variants = [
                {"name": "original_crop", "image": color_padded},
                {"name": "contrast_enhanced", "image": contrast},
                {"name": "adaptive_threshold", "image": adaptive},
            ]
            
            candidate_attempts = self._run_ocr_attempts(primary_variants)

            for attempt in candidate_attempts:
                candidate_rank = self._candidate_rank(attempt["text"], attempt["confidence"])
                candidate_rank += min(float(candidate.get("score", 0.0)) / 12.0, 0.7)
                if candidate_rank > best["rank"]:
                    best.update({
                        "text": attempt["text"],
                        "raw_text": attempt["raw_text"],
                        "confidence": attempt["confidence"],
                        "rank": candidate_rank,
                        "engine": attempt["engine"],
                        "variant": attempt["variant"],
                        "box": candidate["box"],
                        "source": candidate["source"],
                        "plate_confidence": candidate.get("confidence", 0.0),
                        "crop": corrected_crop,
                        "enhanced": adaptive,
                    })

            best["attempts"].extend(candidate_attempts[:12])

            if self._is_valid_plate(best["text"]) and best["confidence"] >= 0.70:
                break

        # Comprehensive Fallback Pass: Only if no valid license plate with high confidence was found
        # in the fast pass, run the full 15 variants check ONLY on the best candidate (candidates[0]).
        if (not self._is_valid_plate(best["text"]) or best["confidence"] < 0.70) and candidates:
            candidate = candidates[0]
            crop = self._crop_with_padding(vehicle_crop, candidate["box"], candidate.get("padding", 0.06))
            if crop is not None and crop.size > 0:
                corrected_crop = self._perspective_correct(crop)
                variants, enhanced = self._build_ocr_inputs(corrected_crop)
                candidate_attempts = self._run_ocr_attempts(variants)

                for attempt in candidate_attempts:
                    candidate_rank = self._candidate_rank(attempt["text"], attempt["confidence"])
                    candidate_rank += min(float(candidate.get("score", 0.0)) / 12.0, 0.7)
                    if candidate_rank > best["rank"]:
                        best.update({
                            "text": attempt["text"],
                            "raw_text": attempt["raw_text"],
                            "confidence": attempt["confidence"],
                            "rank": candidate_rank,
                            "engine": attempt["engine"],
                            "variant": attempt["variant"],
                            "box": candidate["box"],
                            "source": candidate["source"],
                            "plate_confidence": candidate.get("confidence", 0.0),
                            "crop": corrected_crop,
                            "enhanced": enhanced,
                        })

                best["attempts"].extend(candidate_attempts[:12])

        if best["crop"] is None and candidates:
            crop = self._crop_with_padding(vehicle_crop, candidates[0]["box"], candidates[0].get("padding", 0.06))
            best.update({
                "box": candidates[0]["box"],
                "source": candidates[0]["source"],
                "plate_confidence": candidates[0].get("confidence", 0.0),
                "crop": crop,
                "enhanced": crop,
            })

        best["attempts"] = sorted(
            best["attempts"],
            key=lambda item: self._candidate_rank(item.get("text", ""), item.get("confidence", 0.0)),
            reverse=True
        )[:40]
        return best

    def _build_ocr_inputs(self, plate_crop):
        corrected = self._upscale_if_needed(plate_crop)
        gray = cv2.cvtColor(corrected, cv2.COLOR_BGR2GRAY) if len(corrected.shape) == 3 else corrected

        gray = cv2.copyMakeBorder(gray, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=255)
        color_padded = cv2.copyMakeBorder(corrected, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=(255, 255, 255))

        clahe = cv2.createCLAHE(clipLimit=2.8, tileGridSize=(8, 8)).apply(gray)
        denoised = cv2.fastNlMeansDenoising(clahe, h=10, templateWindowSize=7, searchWindowSize=21)
        denoised = cv2.bilateralFilter(denoised, 7, 50, 50)

        sharp_kernel = np.array([[0, -1, 0], [-1, 5.4, -1], [0, -1, 0]], dtype=np.float32)
        sharpened = cv2.filter2D(denoised, -1, sharp_kernel)
        contrast = cv2.convertScaleAbs(sharpened, alpha=1.22, beta=8)

        block = max(21, (min(contrast.shape[:2]) // 6) * 2 + 1)
        adaptive = cv2.adaptiveThreshold(
            contrast,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            9
        )
        _, otsu = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        adaptive = self._ensure_dark_text_on_light(adaptive)
        otsu = self._ensure_dark_text_on_light(otsu)

        variants = [
            {"name": "original_crop", "image": color_padded},
            {"name": "upscaled_crop", "image": corrected},
            {"name": "sharpened_crop", "image": sharpened},
            {"name": "contrast_enhanced", "image": contrast},
            {"name": "thresholded_crop", "image": otsu},
            {"name": "adaptive_threshold", "image": adaptive},
        ]

        variants.extend(self._line_focus_inputs(corrected))
        return variants, adaptive

    def _line_focus_inputs(self, plate_crop):
        h, w = plate_crop.shape[:2]
        if w < 90 or h < 55:
            return []

        boxes = [
            [int(w * 0.14), int(h * 0.10), int(w * 0.96), int(h * 0.57)],
            [int(w * 0.14), int(h * 0.42), int(w * 0.96), int(h * 0.92)],
            [int(w * 0.24), int(h * 0.08), int(w * 0.98), int(h * 0.94)],
        ]
        variants = []
        for index, box in enumerate(boxes):
            clipped = self._clip_box(box, w, h)
            if clipped is None:
                continue
            x1, y1, x2, y2 = clipped
            focus = plate_crop[y1:y2, x1:x2]
            if focus.size == 0:
                continue
            focus = self._upscale_if_needed(focus, min_width=180)
            gray = cv2.cvtColor(focus, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)
            sharpened = cv2.filter2D(
                clahe,
                -1,
                np.array([[0, -1, 0], [-1, 5.0, -1], [0, -1, 0]], dtype=np.float32)
            )
            _, thresholded = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append({"name": f"focus_{index}_original", "image": focus})
            variants.append({"name": f"focus_{index}_sharpened", "image": sharpened})
            variants.append({"name": f"focus_{index}_thresholded", "image": self._ensure_dark_text_on_light(thresholded)})
        return variants

    def _perspective_correct(self, crop):
        if crop is None or crop.size == 0:
            return crop
        h, w = crop.shape[:2]
        if w < 40 or h < 20:
            return crop

        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 40, 130)
            edges = cv2.dilate(edges, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)
            contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                return crop

            for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:6]:
                area = cv2.contourArea(contour)
                if area < w * h * 0.22:
                    continue
                peri = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.035 * peri, True)
                if len(approx) != 4:
                    continue
                pts = approx.reshape(4, 2).astype(np.float32)
                warped = self._four_point_transform(crop, pts)
                if warped is not None and warped.size > 0:
                    wh, ww = warped.shape[:2]
                    if ww >= 40 and wh >= 20:
                        return warped
        except Exception as e:
            logger.debug(f"Perspective correction skipped: {e}")
        return crop

    def _four_point_transform(self, image, pts):
        rect = self._order_points(pts)
        tl, tr, br, bl = rect
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        max_width = max(int(width_a), int(width_b), 1)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_height = max(int(height_a), int(height_b), 1)
        if max_width < 20 or max_height < 12:
            return None
        dst = np.array(
            [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
            dtype=np.float32
        )
        matrix = cv2.getPerspectiveTransform(rect, dst)
        return cv2.warpPerspective(image, matrix, (max_width, max_height))

    def _order_points(self, pts):
        rect = np.zeros((4, 2), dtype=np.float32)
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect

    def _upscale_if_needed(self, image, min_width=120):
        h, w = image.shape[:2]
        target_width = max(min_width, 360 if w < 180 else w)
        scale = max(1.0, target_width / max(w, 1))
        if w < min_width:
            scale = max(scale, min_width / max(w, 1))
        scale = min(max(scale, 1.0), 5.0)
        if scale <= 1.05:
            return image.copy()
        return cv2.resize(image, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LANCZOS4)

    def _ensure_dark_text_on_light(self, image):
        if float(np.mean(image)) < 127:
            return 255 - image
        return image

    def _run_ocr_attempts(self, variants):
        attempts = []
        for variant in variants:
            image = variant["image"]
            variant_name = variant["name"]
            if self.easy_loaded and self.easy_reader is not None:
                attempts.extend(self._run_easyocr(image, variant_name))
            if self.paddle_loaded and self.paddle_reader is not None:
                attempts.extend(self._run_paddleocr(image, variant_name))
        return attempts

    def _run_easyocr(self, image, variant_name):
        try:
            allowlist = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
            try:
                results = self.easy_reader.readtext(image, detail=1, paragraph=False, allowlist=allowlist)
            except TypeError:
                results = self.easy_reader.readtext(image)
            return self._attempts_from_easy_results(results, "easyocr", variant_name)
        except Exception as e:
            logger.error(f"EasyOCR failed for {variant_name}: {e}")
            return []

    def _run_paddleocr(self, image, variant_name):
        try:
            results = self.paddle_reader.ocr(image, cls=True)
            normalized = self._parse_paddle_results(results)
            return self._attempts_from_easy_results(normalized, "paddleocr", variant_name)
        except Exception as e:
            logger.error(f"PaddleOCR failed for {variant_name}: {e}")
            return []

    def _parse_paddle_results(self, results):
        parsed = []
        if not results:
            return parsed
        pages = results if isinstance(results, list) else [results]
        for page in pages:
            if not page:
                continue
            for item in page:
                try:
                    box = item[0]
                    text = item[1][0]
                    conf = float(item[1][1])
                    parsed.append((box, text, conf))
                except Exception:
                    continue
        return parsed

    def _attempts_from_easy_results(self, results, engine, variant_name):
        attempts = []
        if not results:
            return attempts

        normalized = []
        for result in results:
            try:
                box, raw_text, confidence = result[0], str(result[1]), float(result[2])
            except Exception:
                continue
            normalized.append((box, raw_text, confidence))
            text = self._normalize_plate_candidate(raw_text)
            attempts.append(self._attempt(engine, variant_name, raw_text, text, confidence))

        ordered = sorted(
            normalized,
            key=lambda item: (
                min(float(point[1]) for point in item[0]) if item[0] else 0.0,
                min(float(point[0]) for point in item[0]) if item[0] else 0.0
            )
        )

        for start in range(len(ordered)):
            joined = ""
            total_weight = 0
            weighted_confidence = 0.0
            for end in range(start, min(len(ordered), start + 5)):
                raw = ordered[end][1]
                clean_len = max(len(self._clean_plate_text(raw)), 1)
                joined += raw
                total_weight += clean_len
                weighted_confidence += float(ordered[end][2]) * clean_len
                if end == start:
                    continue
                confidence = weighted_confidence / max(total_weight, 1)
                text = self._normalize_plate_candidate(joined)
                attempts.append(self._attempt(engine, variant_name, joined, text, confidence))

        all_joined = "".join(item[1] for item in ordered)
        if all_joined:
            total_weight = sum(max(len(self._clean_plate_text(item[1])), 1) for item in ordered)
            confidence = sum(
                float(item[2]) * max(len(self._clean_plate_text(item[1])), 1)
                for item in ordered
            ) / max(total_weight, 1)
            text = self._normalize_plate_candidate(all_joined)
            attempts.append(self._attempt(engine, variant_name, all_joined, text, confidence))

        best_by_text = {}
        for attempt in attempts:
            key = (attempt["engine"], attempt["variant"], attempt["text"], attempt["raw_text"])
            previous = best_by_text.get(key)
            if previous is None or attempt["confidence"] > previous["confidence"]:
                best_by_text[key] = attempt
        return list(best_by_text.values())

    def _attempt(self, engine, variant, raw_text, text, confidence):
        return {
            "engine": engine,
            "variant": variant,
            "raw_text": str(raw_text),
            "text": text,
            "confidence": float(confidence),
            "valid": self._is_valid_plate(text)
        }

    def _summarize_engine_attempts(self, attempts):
        summary = {
            "easyocr": {"available": self.easy_loaded, "best_text": "", "confidence": 0.0, "variant": ""},
            "paddleocr": {"available": self.paddle_loaded, "best_text": "", "confidence": 0.0, "variant": "", "error": self.paddle_error}
        }
        for attempt in attempts:
            engine = attempt.get("engine")
            if engine not in summary:
                continue
            current = summary[engine]
            if self._candidate_rank(attempt.get("text", ""), attempt.get("confidence", 0.0)) > self._candidate_rank(
                current.get("best_text", ""), current.get("confidence", 0.0)
            ):
                current["best_text"] = attempt.get("text", "")
                current["confidence"] = float(attempt.get("confidence", 0.0))
                current["variant"] = attempt.get("variant", "")
        return summary

    def _candidate_rank(self, text, confidence):
        if not text:
            return 0.0
        if self._is_valid_plate(text):
            return 5.0 + confidence
        clean_len = len(self._clean_plate_text(text))
        if 7 <= clean_len <= 11:
            return 1.0 + confidence
        return confidence * 0.5

    def _clean_plate_text(self, text):
        return re.sub(r"[^A-Za-z0-9]", "", str(text)).upper()

    def _normalize_plate_candidate(self, text):
        clean = self._clean_plate_text(text)
        clean = re.sub(r"^IND", "", clean)
        clean = clean.replace("IND", "")
        if not clean:
            return ""

        spans = [clean]
        for length in range(8, 12):
            for start in range(0, max(len(clean) - length + 1, 0)):
                spans.append(clean[start:start + length])

        best_fallback = ""
        for span in spans:
            for variant in self._plate_variants(span):
                if self._is_valid_plate(variant):
                    return variant
                if 7 <= len(variant) <= 11 and len(variant) > len(best_fallback):
                    best_fallback = variant
        return best_fallback

    def _plate_variants(self, text):
        clean = self._clean_plate_text(text)
        variants = []
        seen = set()

        def add_variant(value):
            if value not in seen:
                seen.add(value)
                variants.append(value)

        add_variant(clean)
        if len(clean) < 8 or len(clean) > 11:
            return variants

        for district_len in (2, 1):
            for serial_len in (4, 3):
                series_len = len(clean) - 2 - district_len - serial_len
                if not 1 <= series_len <= 3:
                    continue
                groups = [
                    ("letters", clean[:2]),
                    ("digits", clean[2:2 + district_len]),
                    ("letters", clean[2 + district_len:2 + district_len + series_len]),
                    ("digits", clean[-serial_len:])
                ]
                expanded = [""]
                for group_type, group_text in groups:
                    group_options = self._expand_group(group_text, group_type)
                    expanded = [prefix + option for prefix in expanded for option in group_options]
                    if len(expanded) > 96:
                        expanded = expanded[:96]
                for value in expanded:
                    add_variant(value)

        return variants

    def _expand_group(self, text, group_type):
        options = [""]
        for char in text:
            replacements = self._letter_replacements(char) if group_type == "letters" else self._digit_replacements(char)
            options = [prefix + replacement for prefix in options for replacement in replacements]
            if len(options) > 48:
                options = options[:48]
        return options

    def _letter_replacements(self, char):
        mapping = {
            "0": ["O", "D"],
            "1": ["I", "L"],
            "2": ["Z"],
            "4": ["A"],
            "5": ["S"],
            "6": ["G"],
            "7": ["T", "Z"],
            "8": ["B"],
        }
        return [char] + [item for item in mapping.get(char, []) if item != char]

    def _digit_replacements(self, char):
        mapping = {
            "A": ["4"],
            "B": ["8"],
            "D": ["0"],
            "G": ["6"],
            "I": ["1"],
            "L": ["1"],
            "O": ["0"],
            "Q": ["0"],
            "S": ["5"],
            "T": ["7"],
            "Z": ["7", "2"],
        }
        return [char] + [item for item in mapping.get(char, []) if item != char]

    def _is_valid_plate(self, text):
        clean = self._clean_plate_text(text)
        if len(clean) < 7 or len(clean) > 11:
            return False
        if clean[:2] not in self.STATE_CODES:
            return False
        match = re.match(r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{1,4})$", clean)
        if not match:
            return False
        district = int(match.group(2))
        return district > 0

    def _build_ocr_overlay(self, image, vehicle_box, best):
        overlay = image.copy()
        x1, y1, x2, y2 = vehicle_box
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (255, 184, 0), 3)

        plate_box = best.get("box")
        if plate_box:
            px1, py1, px2, py2 = plate_box
            gx1, gy1 = x1 + px1, y1 + py1
            gx2, gy2 = x1 + px2, y1 + py2
            cv2.rectangle(overlay, (gx1, gy1), (gx2, gy2), (0, 255, 0), 3)
            label = f"{best.get('text') or 'UNKNOWN'} {best.get('confidence', 0.0) * 100:.0f}%"
            cv2.putText(
                overlay,
                label,
                (gx1, max(24, gy1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.75,
                (0, 255, 0),
                2
            )
        return overlay

    def copy_debug_artifacts(self, package_dir):
        """
        Copies latest OCR debug artifacts into a violation evidence package.
        Returns relative filenames copied into package_dir.
        """
        copied = {}
        for name in ["vehicle_crop.jpg", "plate_crop.jpg", "enhanced_plate.jpg", "ocr_result.jpg"]:
            src = os.path.join(self.outputs_debug_dir, name)
            if not os.path.exists(src):
                src = os.path.join(self.outputs_dir, name)
            if os.path.exists(src):
                dst = os.path.join(package_dir, name)
                shutil.copyfile(src, dst)
                copied[name] = dst
        return copied
