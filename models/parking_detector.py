import logging

logger = logging.getLogger("ParkingDetector")

class ParkingDetector:
    def __init__(self):
        # Default prohibited parking zone polygon (normalized coords for demo, or absolute coords)
        # Defined as relative coordinates: e.g. [ [x, y], [x, y], ... ]
        self.default_zones = [
            # A polygon on the right side of the street where parking is illegal
            [[0.5, 0.5], [0.95, 0.5], [0.95, 0.95], [0.5, 0.95]]
        ]

    def check_illegal_parking(self, image, detections, custom_zones=None):
        """
        Check if any vehicle is parked illegally within defined zones.
        detections: list of dicts with 'box', 'label', 'confidence'
        Returns:
        - violations: list of dicts of illegally parked vehicles
        """
        h, w, _ = image.shape
        zones = custom_zones if custom_zones is not None else self.default_zones
        violations = []

        # Convert normalized default zones to absolute pixel coordinates
        pixel_zones = []
        for zone in zones:
            pixel_zone = [[int(pt[0] * w), int(pt[1] * h)] for pt in zone]
            pixel_zones.append(pixel_zone)

        vehicles = [d for d in detections if d['label'] in ['car', 'truck', 'bus']]

        for veh in vehicles:
            box = veh['box']
            # Calculate bottom center of the vehicle box (where the wheels touch the road)
            cx = (box[0] + box[2]) // 2
            cy = box[3]

            for idx, zone in enumerate(pixel_zones):
                if self._point_in_polygon(cx, cy, zone):
                    logger.warning(f"Illegal parking detected for {veh['label']} at coordinate ({cx}, {cy})")
                    violations.append({
                        "vehicle_box": box,
                        "vehicle_type": veh['label'],
                        "zone_index": idx,
                        "confidence": veh['confidence']
                    })

        return violations

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
