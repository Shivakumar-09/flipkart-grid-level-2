import cv2
import logging
import numpy as np
from utils.runtime import get_yolo_model

logger = logging.getLogger("SeatbeltDetector")

class SeatbeltDetector:
    def __init__(self, model_path="yolov8n-pose.pt"):
        self.model_path = model_path
        self.model = None
        self.is_loaded = False
        self.device = "cpu"

    def detect_seatbelt(self, image, vehicle_box, vehicle_label="car", mock_result=None):
        """
        Processes a vehicle bounding box to locate the driver and detect if they are wearing a seatbelt.
        
        Args:
            image: BGR numpy image frame
            vehicle_box: [x1, y1, x2, y2] bounding box coordinates of the vehicle
            vehicle_label: class label of the vehicle ('car', 'truck', 'bus', etc.)
            mock_result: Optional override (True/False) to force seatbelt presence for testing
            
        Returns:
            seatbelt_present: bool (True if seatbelt is worn, False if not)
            confidence: float (classification confidence score between 0.70 and 0.99)
            driver_box: [dx1, dy1, dx2, dy2] bounding box coordinates of the driver cabin region
        """
        vx1, vy1, vx2, vy2 = vehicle_box
        h, w, _ = image.shape
        
        # 1. Driver Localization:
        # In a front-facing camera (standard for ANPR), the driver is in the front seat.
        # In right-hand drive (RHD) India, the driver is on the right side of the vehicle,
        # which corresponds to the LEFT side of the vehicle box in the camera's perspective.
        vw = vx2 - vx1
        vh = vy2 - vy1
        
        dx1 = max(0, vx1 + int(vw * 0.12))
        dy1 = max(0, vy1 + int(vh * 0.18))
        dx2 = min(w, vx1 + int(vw * 0.52))
        dy2 = min(h, vy1 + int(vh * 0.52))
        driver_box = [dx1, dy1, dx2, dy2]
        
        # Explicit mock override (useful for unit testing and seeding)
        if mock_result is not None:
            conf = 0.85 + (np.random.random() * 0.14)
            return mock_result, float(conf), driver_box

        driver_crop = image[dy1:dy2, dx1:dx2]
        if driver_crop.size == 0:
            return False, 0.70, driver_box

        # 2. Classical Computer Vision Seatbelt Detection:
        # Converts driver crop to grayscale, applies bilateral filter/gaussian blur, Canny, and Hough Lines
        try:
            gray = cv2.cvtColor(driver_crop, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)
            edges = cv2.Canny(blurred, 40, 130)
            
            # Hough Line Transform looking for diagonal seatbelt strap lines
            lines = cv2.HoughLinesP(
                edges, 
                rho=1, 
                theta=np.pi/180, 
                threshold=12, 
                minLineLength=15, 
                maxLineGap=8
            )
            
            matching_length = 0.0
            
            if lines is not None:
                for line in lines:
                    x1_l, y1_l, x2_l, y2_l = line[0]
                    dx_l = x2_l - x1_l
                    dy_l = y2_l - y1_l
                    if dx_l == 0:
                        angle = 90.0
                    else:
                        angle = np.abs(np.arctan2(dy_l, dx_l) * 180 / np.pi)
                    
                    # Seatbelts sit at a diagonal angle (25 to 65 degrees, or 115 to 155 degrees)
                    if (25.0 <= angle <= 65.0) or (115.0 <= angle <= 155.0):
                        matching_length += np.sqrt(dx_l**2 + dy_l**2)
            
            # 3. Decision Logic and Confidence Calculation
            # If total matching diagonal edges exceeds a minimal threshold, seatbelt is present
            threshold_len = int(driver_crop.shape[0] * 0.12)  # 12% of crop height
            threshold_len = max(10, threshold_len)
            
            if matching_length >= threshold_len:
                seatbelt_present = True
                confidence = 0.70 + min(0.29, (matching_length - threshold_len) / 250.0)
            else:
                seatbelt_present = False
                # If very few edges exist in the driver crop, we are highly confident the belt is missing
                edge_density = np.sum(edges > 0) / edges.size
                if edge_density < 0.05:
                    confidence = 0.88  # Clear flat chest region
                else:
                    confidence = 0.78
            
            # Scale to strictly fit [0.70, 0.99]
            confidence = min(0.99, max(0.70, float(confidence)))
            return seatbelt_present, confidence, driver_box
            
        except Exception as e:
            logger.error(f"Error in classical CV seatbelt detection: {e}. Falling back to default.")
            return False, 0.72, driver_box
