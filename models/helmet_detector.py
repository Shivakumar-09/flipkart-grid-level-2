import cv2
import logging
import numpy as np

logger = logging.getLogger("HelmetDetector")

class HelmetDetector:
    def __init__(self, model_path="yolov8n-pose.pt"):
        self.model_path = model_path
        self.model = None
        self.is_loaded = False
        try:
            from ultralytics import YOLO
            self.model = YOLO(model_path)
            self.is_loaded = True
            logger.info(f"YOLOv8 Pose Model loaded successfully from {model_path}.")
        except Exception as e:
            logger.warning(f"Could not load YOLOv8-Pose model: {e}. Running in simulation/fallback mode.")

    def check_helmet(self, image, person_box):
        """
        Check if the person specified by person_box is wearing a helmet.
        Returns:
        - has_helmet: bool
        - confidence: float
        """
        x1, y1, x2, y2 = person_box
        h, w, _ = image.shape
        
        # Guard rails for box coordinate bounds
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        
        rider_crop = image[y1:y2, x1:x2]
        if rider_crop.size == 0:
            return False, 0.0
            
        head_crop = None
        
        if self.is_loaded and self.model is not None:
            try:
                # Run pose estimation to find head keypoints
                results = self.model(rider_crop, verbose=False)
                if len(results) > 0 and len(results[0].keypoints) > 0:
                    # Look at the head/ears/eyes keypoints (keypoint indices 0 to 4 in COCO Pose)
                    keypoints = results[0].keypoints.xy[0].cpu().numpy()
                    
                    if len(keypoints) > 0:
                        # Find the mean y-coordinate of the head keypoints to crop head
                        head_pts = keypoints[0:5]
                        valid_head_pts = head_pts[(head_pts[:, 0] > 0) & (head_pts[:, 1] > 0)]
                        
                        if len(valid_head_pts) > 0:
                            # Let's define the head bounding box based on keypoints
                            min_hx = np.min(valid_head_pts[:, 0])
                            max_hx = np.max(valid_head_pts[:, 0])
                            min_hy = np.min(valid_head_pts[:, 1])
                            max_hy = np.max(valid_head_pts[:, 1])
                            
                            w_h = max_hx - min_hx
                            h_h = max_hy - min_hy
                            
                            # Expand upwards for helmet area
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
                            
                            head_crop = rider_crop[hy1:hy2, hx1:hx2]
            except Exception as e:
                logger.error(f"Error checking helmet via pose estimation: {e}")
                
        # Fallback if keypoints fail or model is offline: crop top 20% of rider box
        if head_crop is None or head_crop.size == 0:
            h_c = int(rider_crop.shape[0] * 0.2)
            head_crop = rider_crop[0:h_c, :]
            
        if head_crop is not None and head_crop.size > 0:
            try:
                hsv = cv2.cvtColor(head_crop, cv2.COLOR_BGR2HSV)
                h_ch, s_ch, v_ch = cv2.split(hsv)
                
                # Skin tone mask in HSV
                skin_mask = ((h_ch >= 0) & (h_ch <= 25) & (s_ch >= 20) & (s_ch <= 150) & (v_ch >= 50) & (v_ch <= 255))
                # Hair mask in HSV (black/dark brown)
                hair_mask = ((s_ch <= 55) & (v_ch <= 80))
                
                bare_head_mask = skin_mask | hair_mask
                bare_head_pixels = np.sum(bare_head_mask)
                total_pixels = head_crop.shape[0] * head_crop.shape[1]
                bare_head_ratio = bare_head_pixels / total_pixels if total_pixels > 0 else 1.0
                
                # If bare_head_ratio is high, it is classified as bare head (NO HELMET)
                if bare_head_ratio > 0.60:
                    has_helmet = False
                    confidence = float(bare_head_ratio)
                else:
                    has_helmet = True
                    confidence = float(1.0 - bare_head_ratio)
                    
                # Scale confidence to [0.70, 0.99]
                confidence = 0.70 + (confidence * 0.29)
                confidence = min(0.99, max(0.70, confidence))
                return has_helmet, confidence
            except Exception as e:
                logger.error(f"Error in helmet color analysis: {e}")
                
        return False, 0.75
