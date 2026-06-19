import logging
import numpy as np

logger = logging.getLogger("ParkingDetector")

class ParkingDetector:
    def __init__(self):
        # Default prohibited parking zone polygon (normalized coords for demo, or absolute coords)
        # Defined as relative coordinates: e.g. [ [x, y], [x, y], ... ]
        self.default_zones = [
            # A polygon on the right side of the street where parking is illegal
            [[0.5, 0.5], [0.95, 0.5], [0.95, 0.95], [0.5, 0.95]]
        ]

    def check_illegal_parking(self, vehicle_bbox, camera_id, location, frame, custom_zones=None):
        """
        Check if the specified vehicle is parked illegally within defined prohibited zones.
        """
        h, w, _ = frame.shape
        # Map specialized prohibited zones per camera_id for realistic coverage
        camera_zones = {
            "CAM_BLR_001": [[[0.4, 0.4], [0.95, 0.4], [0.95, 0.95], [0.4, 0.95]]], # Silk Board
            "CAM_BLR_002": [[[0.5, 0.5], [0.98, 0.5], [0.98, 0.98], [0.5, 0.98]]], # Whitefield
            "CAM_BLR_003": [[[0.3, 0.3], [0.85, 0.3], [0.85, 0.85], [0.3, 0.85]]], # Electronic City
            "CAM_BLR_004": [[[0.5, 0.5], [0.95, 0.5], [0.95, 0.95], [0.5, 0.95]]], # Marathahalli
        }
        
        zones = custom_zones if custom_zones is not None else camera_zones.get(camera_id, self.default_zones)
        
        # Convert normalized zones to absolute pixel coordinates
        pixel_zones = []
        for zone in zones:
            pixel_zone = [[int(pt[0] * w), int(pt[1] * h)] for pt in zone]
            pixel_zones.append(pixel_zone)
            
        cx = (vehicle_bbox[0] + vehicle_bbox[2]) // 2
        cy = vehicle_bbox[3]
        
        for zone in pixel_zones:
            if self._point_in_polygon(cx, cy, zone):
                logger.warning(f"Illegal parking detected for vehicle at ({cx}, {cy}) in camera {camera_id}")
                return True, 0.92, zone
                
        return False, 0.0, None

    def _point_in_polygon(self, x, y, poly):
        """
        Ray Casting Algorithm to determine if point (x, y) is inside polygon poly.
        poly: list of [x, y] coordinates of vertices
        """
        n = len(poly)
        inside = False
        p1x, p1y = poly[0]
        for i in range(n + 1):
            p2x, p2y = poly[i % n]
            if y > min(p1y, p2y):
                if y <= max(p1y, p2y):
                    if x <= max(p1x, p2x):
                        if p1y != p2y:
                            xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                        if p1x == p2x or x <= xinters:
                            inside = not inside
            p1x, p1y = p2x, p2y
        return inside
