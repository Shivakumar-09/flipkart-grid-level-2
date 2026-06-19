import cv2
import logging
import os
import numpy as np
from utils.runtime import get_yolo_model

logger = logging.getLogger("HelmetDetector")

HELMET_MISSING_THRESHOLD = 0.80
HELMET_DETECTED_THRESHOLD = 0.55


class HelmetDetector:
    def __init__(self, model_path="yolov8n-pose.pt"):
        self.model_path = model_path
        self.model = None
        self.is_loaded = False
        self.device = "cpu"
        try:
            self.model, self.device, load_ms, from_cache = get_yolo_model(model_path)
            self.is_loaded = True
            source = "cache" if from_cache else f"{load_ms:.1f}ms"
            logger.info(f"YOLOv8 Pose Model ready from {model_path} on {self.device} ({source}).")
        except Exception as e:
            logger.warning(f"Could not load YOLOv8-Pose model: {e}. Running in simulation/fallback mode.")

    def _abs_bbox(self, parent_box, local_bbox):
        px1, py1, _, _ = parent_box
        lx1, ly1, lx2, ly2 = local_bbox
        return [int(px1 + lx1), int(py1 + ly1), int(px1 + lx2), int(py1 + ly2)]

    def _extract_head_region(self, rider_crop, person_box):
        head_local = None
        keypoint_debug = {"valid_points": 0, "source": "fallback_top_20pct"}

        if self.is_loaded and self.model is not None:
            try:
                results = self.model(rider_crop, verbose=False, device=self.device)
                if len(results) > 0 and len(results[0].keypoints) > 0:
                    keypoints = results[0].keypoints.xy[0].cpu().numpy()
                    if len(keypoints) > 0:
                        head_pts = keypoints[0:5]
                        valid_head_pts = head_pts[(head_pts[:, 0] > 0) & (head_pts[:, 1] > 0)]
                        keypoint_debug["valid_points"] = int(len(valid_head_pts))

                        if len(valid_head_pts) > 0:
                            min_hx = np.min(valid_head_pts[:, 0])
                            max_hx = np.max(valid_head_pts[:, 0])
                            min_hy = np.min(valid_head_pts[:, 1])
                            max_hy = np.max(valid_head_pts[:, 1])

                            w_h = max_hx - min_hx
                            h_h = max_hy - min_hy

                            pad_w = int(w_h * 0.3) if w_h > 0 else int(rider_crop.shape[1] * 0.1)
                            pad_h = int(h_h * 0.4) if h_h > 0 else int(rider_crop.shape[0] * 0.1)

                            hx1 = max(0, int(min_hx - pad_w))
                            hy1 = max(0, int(min_hy - pad_h * 1.5))
                            hx2 = min(rider_crop.shape[1], int(max_hx + pad_w))
                            hy2 = min(rider_crop.shape[0], int(max_hy + pad_h * 0.5))

                            if (hx2 - hx1) < 15 or (hy2 - hy1) < 15:
                                mean_x = np.mean(valid_head_pts[:, 0])
                                mean_y = np.mean(valid_head_pts[:, 1])
                                head_size = int(rider_crop.shape[1] * 0.35)
                                hx1 = max(0, int(mean_x - head_size / 2))
                                hy1 = max(0, int(mean_y - head_size * 0.7))
                                hx2 = min(rider_crop.shape[1], int(mean_x + head_size / 2))
                                hy2 = min(rider_crop.shape[0], int(mean_y + head_size * 0.3))

                            head_local = [hx1, hy1, hx2, hy2]
                            keypoint_debug["source"] = "pose_keypoints"
            except Exception as e:
                logger.error(f"Error checking helmet via pose estimation: {e}")

        if head_local is None:
            h_c = int(rider_crop.shape[0] * 0.2)
            head_local = [0, 0, rider_crop.shape[1], max(h_c, 1)]

        return head_local, keypoint_debug

    def _analyze_head_crop(self, head_crop):
        hsv = cv2.cvtColor(head_crop, cv2.COLOR_BGR2HSV)
        h_ch, s_ch, v_ch = cv2.split(hsv)
        total_pixels = head_crop.shape[0] * head_crop.shape[1]
        if total_pixels <= 0:
            return {
                "helmet_shell_ratio": 0.0,
                "skin_ratio": 0.0,
                "bare_hair_ratio": 0.0,
                "bare_head_ratio": 1.0,
                "dark_coverage_ratio": 0.0,
            }

        skin_mask = (
            (h_ch >= 0) & (h_ch <= 25)
            & (s_ch >= 20) & (s_ch <= 150)
            & (v_ch >= 50) & (v_ch <= 255)
        )

        # Dark regions can be bare hair OR a full-face helmet visor/shell.
        dark_mask = (v_ch <= 90)

        light_helmet_mask = (s_ch <= 70) & (v_ch >= 130)
        colored_helmet_mask = (s_ch >= 35) & (v_ch >= 45) & ~skin_mask
        dark_helmet_shell_mask = dark_mask & ~skin_mask

        helmet_shell_mask = light_helmet_mask | colored_helmet_mask | dark_helmet_shell_mask

        # Bare hair only counts when dark pixels are NOT part of a dominant helmet shell.
        bare_hair_mask = dark_mask & ~helmet_shell_mask & (s_ch <= 55)

        skin_ratio = float(np.sum(skin_mask)) / total_pixels
        helmet_shell_ratio = float(np.sum(helmet_shell_mask)) / total_pixels
        bare_hair_ratio = float(np.sum(bare_hair_mask)) / total_pixels
        dark_coverage_ratio = float(np.sum(dark_mask)) / total_pixels
        bare_head_ratio = skin_ratio + bare_hair_ratio

        return {
            "helmet_shell_ratio": helmet_shell_ratio,
            "skin_ratio": skin_ratio,
            "bare_hair_ratio": bare_hair_ratio,
            "bare_head_ratio": bare_head_ratio,
            "dark_coverage_ratio": dark_coverage_ratio,
        }

    def _classify(self, metrics):
        helmet_shell_ratio = metrics["helmet_shell_ratio"]
        skin_ratio = metrics["skin_ratio"]
        bare_head_ratio = metrics["bare_head_ratio"]
        dark_coverage_ratio = metrics["dark_coverage_ratio"]

        # Full-face helmet with dark visor: large dark coverage, minimal exposed skin.
        if dark_coverage_ratio >= 0.40 and skin_ratio <= 0.25:
            helmet_confidence = min(0.99, 0.72 + dark_coverage_ratio * 0.25)
            return True, 1.0 - helmet_confidence, helmet_confidence, "dark_full_face_helmet"

        if helmet_shell_ratio >= 0.28:
            helmet_confidence = min(0.99, 0.70 + helmet_shell_ratio * 0.29)
            return True, 1.0 - helmet_confidence, helmet_confidence, "helmet_shell_detected"

        if bare_head_ratio > 0.60 and helmet_shell_ratio < 0.15:
            missing_confidence = min(0.99, 0.70 + bare_head_ratio * 0.29)
            return False, missing_confidence, 1.0 - missing_confidence, "bare_head_exceeds_threshold"

        if bare_head_ratio > 0.45 and helmet_shell_ratio < 0.20:
            missing_confidence = min(0.85, 0.55 + bare_head_ratio * 0.30)
            return False, missing_confidence, 1.0 - missing_confidence, "probable_bare_head"

        return None, 0.50, 0.50, "insufficient_evidence"

    def _estimate_helmet_bbox(self, head_local, metrics, rider_crop_shape):
        hx1, hy1, hx2, hy2 = head_local
        head_w = max(1, hx2 - hx1)
        head_h = max(1, hy2 - hy1)

        if metrics["dark_coverage_ratio"] >= 0.40:
            pad_x = int(head_w * 0.08)
            pad_y_top = int(head_h * 0.20)
            pad_y_bottom = int(head_h * 0.05)
        else:
            pad_x = int(head_w * 0.12)
            pad_y_top = int(head_h * 0.25)
            pad_y_bottom = int(head_h * 0.10)

        helmet_local = [
            max(0, hx1 - pad_x),
            max(0, hy1 - pad_y_top),
            min(rider_crop_shape[1], hx2 + pad_x),
            min(rider_crop_shape[0], hy2 + pad_y_bottom),
        ]
        return helmet_local

    def _render_debug_panel(self, rider_crop, head_crop, helmet_crop, result, output_path):
        panel_h = 220
        rider_w = max(1, rider_crop.shape[1])
        head_w = max(1, head_crop.shape[1] if head_crop is not None else 1)
        helmet_w = max(1, helmet_crop.shape[1] if helmet_crop is not None else 1)
        text_w = 360
        panel_w = rider_w + head_w + helmet_w + text_w + 40

        panel = np.zeros((panel_h, panel_w, 3), dtype=np.uint8)
        panel[:] = (24, 24, 24)

        x_offset = 10
        for crop, label in (
            (rider_crop, "Rider"),
            (head_crop, "Head"),
            (helmet_crop, "Helmet"),
        ):
            if crop is None or crop.size == 0:
                continue
            resized = cv2.resize(crop, (crop.shape[1], panel_h - 30))
            h, w = resized.shape[:2]
            panel[20:20 + h, x_offset:x_offset + w] = resized
            cv2.putText(
                panel, label, (x_offset, 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1
            )
            x_offset += w + 10

        tx = x_offset + 10
        lines = [
            f"Rider ID: {result['rider_id']}",
            f"Decision: {result['decision']}",
            f"Helmet Detected: {result['helmet_detected']}",
            f"Helmet Conf: {result['helmet_confidence']:.2f}",
            f"Missing Conf: {result['helmet_missing_confidence']:.2f}",
            f"Reason: {result['violation_trigger_reason'] or 'none'}",
        ]
        for i, line in enumerate(lines):
            cv2.putText(
                panel, line, (tx, 35 + i * 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1
            )

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, panel)
        return output_path

    def check_helmet(self, image, person_box, rider_id=0, debug_dir=None):
        """
        Check if the person specified by person_box is wearing a helmet.

        Returns a debug dictionary:
        {
            rider_id, helmet_detected, helmet_confidence, helmet_missing_confidence,
            head_bbox, helmet_bbox, decision, violation_trigger_reason, metrics, debug_paths
        }
        """
        x1, y1, x2, y2 = person_box
        h, w, _ = image.shape

        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)

        empty_result = {
            "rider_id": rider_id,
            "helmet_detected": None,
            "helmet_confidence": 0.0,
            "helmet_missing_confidence": 0.0,
            "head_bbox": [x1, y1, x2, y2],
            "helmet_bbox": None,
            "decision": "REVIEW_REQUIRED",
            "violation_trigger_reason": "invalid_rider_crop",
            "metrics": {},
            "debug_paths": {},
        }

        rider_crop = image[y1:y2, x1:x2]
        if rider_crop.size == 0:
            logger.warning(f"Helmet check rider #{rider_id}: empty rider crop")
            return empty_result

        head_local, keypoint_debug = self._extract_head_region(rider_crop, person_box)
        hx1, hy1, hx2, hy2 = head_local
        head_crop = rider_crop[hy1:hy2, hx1:hx2]
        head_bbox = self._abs_bbox(person_box, head_local)

        if head_crop is None or head_crop.size == 0:
            logger.warning(f"Helmet check rider #{rider_id}: empty head crop, marking REVIEW_REQUIRED")
            empty_result["head_bbox"] = head_bbox
            empty_result["violation_trigger_reason"] = "head_crop_unavailable"
            return empty_result

        metrics = self._analyze_head_crop(head_crop)
        helmet_detected, missing_conf, helmet_conf, reason = self._classify(metrics)

        helmet_local = self._estimate_helmet_bbox(head_local, metrics, rider_crop.shape)
        helmet_bbox = self._abs_bbox(person_box, helmet_local)
        helmet_crop = rider_crop[helmet_local[1]:helmet_local[3], helmet_local[0]:helmet_local[2]]

        if helmet_detected is True:
            decision = "HELMET_OK"
            violation_trigger_reason = None
        elif helmet_detected is False and missing_conf >= HELMET_MISSING_THRESHOLD:
            decision = "HELMET_VIOLATION"
            violation_trigger_reason = reason
        else:
            decision = "REVIEW_REQUIRED"
            violation_trigger_reason = reason if helmet_detected is False else "insufficient_evidence"

        result = {
            "rider_id": rider_id,
            "helmet_detected": bool(helmet_detected) if helmet_detected is not None else None,
            "helmet_confidence": round(float(helmet_conf), 4),
            "helmet_missing_confidence": round(float(missing_conf), 4),
            "head_bbox": head_bbox,
            "helmet_bbox": helmet_bbox,
            "decision": decision,
            "violation_trigger_reason": violation_trigger_reason,
            "metrics": {**metrics, **keypoint_debug},
            "debug_paths": {},
        }

        logger.info(
            "Helmet debug rider #%s: detected=%s helmet_conf=%.2f missing_conf=%.2f "
            "decision=%s reason=%s head_bbox=%s helmet_bbox=%s metrics=%s",
            rider_id,
            result["helmet_detected"],
            result["helmet_confidence"],
            result["helmet_missing_confidence"],
            result["decision"],
            result["violation_trigger_reason"],
            result["head_bbox"],
            result["helmet_bbox"],
            result["metrics"],
        )

        if debug_dir:
            panel_path = os.path.join(debug_dir, f"helmet_debug_rider_{rider_id}.jpg")
            result["debug_paths"]["debug_panel"] = self._render_debug_panel(
                rider_crop, head_crop, helmet_crop, result, panel_path
            )

        return result
