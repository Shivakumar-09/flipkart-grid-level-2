import logging

logger = logging.getLogger("TripleRidingDetector")

class TripleRidingDetector:
    def __init__(self):
        pass

    def check_triple_riding(self, detections):
        """
        Detects triple riding cases by analyzing overlapping boxes of persons and motorcycles.
        detections: list of dicts with 'box', 'label', 'confidence'
        Returns:
        - violations: list of dicts containing the offending motorcycle's bbox and confidence
        """
        motorcycles = [d for d in detections if d['label'] == 'motorcycle']
        persons = [d for d in detections if d['label'] == 'person']
        violations = []

        for mc in motorcycles:
            mc_box = mc['box']
            riders_on_mc = []

            for p in persons:
                p_box = p['box']
                # Calculate overlap between person box and motorcycle box
                overlap_pct = self._calculate_overlap(p_box, mc_box)
                # If a person box overlaps with motorcycle by > 30% area or vice versa
                if overlap_pct > 0.3:
                    riders_on_mc.append(p)

            # If more than 2 people are detected on a single motorcycle
            if len(riders_on_mc) > 2:
                logger.warning(f"Triple riding violation detected! Rider count: {len(riders_on_mc)}")
                violations.append({
                    "motorcycle_box": mc_box,
                    "rider_count": len(riders_on_mc),
                    "confidence": min([r['confidence'] for r in riders_on_mc]) if riders_on_mc else 0.85
                })

        # High-fidelity simulation backup if no natural detections trigger it
        # (e.g. during a test run without motorcycle data)
        # If we have a motorcycle and a person count, let's simulate it under specific testing conditions
        return violations

    def _calculate_overlap(self, box1, box2):
        """
        Calculate the ratio of intersection area to the area of box1.
        box1: person box [x1, y1, x2, y2]
        box2: motorcycle box [x1, y1, x2, y2]
        """
        # Coordinates of intersection
        ix1 = max(box1[0], box2[0])
        iy1 = max(box1[1], box2[1])
        ix2 = min(box1[2], box2[2])
        iy2 = min(box1[3], box2[3])

        # Width and height of intersection
        iw = max(0, ix2 - ix1)
        ih = max(0, iy2 - iy1)

        intersection_area = iw * ih
        box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])

        if box1_area == 0:
            return 0.0

        return intersection_area / box1_area
