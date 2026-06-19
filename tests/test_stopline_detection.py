"""
test_stopline_detection.py - Test Suite for TrafficFlow Stop-Line Violation Detection
====================================================================================
Validates camera stop-line configuration, front bumper geometry, multi-vehicle checks,
and camera-specific stop-line behavior.
"""

import os
import sys
import cv2
import numpy as np

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.traffic_light_detector import TrafficLightDetector

PASS = "[PASS]"
FAIL = "[FAIL]"


def run_tests():
    print("=" * 60)
    print("  TrafficFlow -- Stop-Line Violation Detection Test Suite")
    print("=" * 60)

    detector = TrafficLightDetector()
    frame = np.zeros((400, 600, 3), dtype=np.uint8)

    # Test 1: Camera config line resolution
    print("\n[Test 1] Camera stop-line configuration resolution")
    stop_line = detector.get_camera_stop_line("CAM_BLR_001", 400, 600)
    expected_y = int(round(400 * 0.58))
    print(f"  Stop Line: {stop_line}")
    if stop_line["type"] == "line" and stop_line["y"] == expected_y:
        print(f"  {PASS} CAM_BLR_001 stop_line_y resolved correctly.")
    else:
        print(f"  {FAIL} CAM_BLR_001 stop line did not resolve as expected.")
        sys.exit(1)

    # Test 2: Vehicle before line
    print("\n[Test 2] Vehicle before stop line")
    before_box = [200, 110, 320, 220]  # front bumper y=220, line y=232
    is_viol, conf, details = detector.check_stop_line_violation(
        frame, before_box, "car", camera_id="CAM_BLR_001", detection_confidence=0.95
    )
    print(f"  Violation: {is_viol}, Confidence: {conf:.2f}, Details: {details}")
    if not is_viol and not details["stop_line_crossed"]:
        print(f"  {PASS} Vehicle before the stop line was not flagged.")
    else:
        print(f"  {FAIL} Vehicle before the stop line was incorrectly flagged.")
        sys.exit(1)

    # Test 3: Vehicle crossing line
    print("\n[Test 3] Vehicle crossing stop line")
    crossing_box = [200, 150, 320, 270]  # front bumper y=270, line y=232
    is_viol, conf, details = detector.check_stop_line_violation(
        frame, crossing_box, "car", camera_id="CAM_BLR_001", detection_confidence=0.96
    )
    print(f"  Violation: {is_viol}, Confidence: {conf:.2f}, Crossing Distance: {details['crossing_distance_px']:.1f}px")
    if is_viol and conf >= 0.72 and details["stop_line_crossed"]:
        print(f"  {PASS} Vehicle crossing the stop line was correctly flagged.")
    else:
        print(f"  {FAIL} Vehicle crossing the stop line was not flagged.")
        sys.exit(1)

    # Test 4: Multiple vehicles in one frame
    print("\n[Test 4] Multiple vehicles")
    vehicle_boxes = [
        [40, 120, 150, 225],   # before line
        [190, 160, 310, 260],  # crossing
        [360, 180, 500, 300]   # crossing
    ]
    results = [
        detector.check_stop_line_violation(frame, box, "car", camera_id="CAM_BLR_001")[0]
        for box in vehicle_boxes
    ]
    print(f"  Results: {results}")
    if results == [False, True, True]:
        print(f"  {PASS} Multiple vehicles were classified correctly.")
    else:
        print(f"  {FAIL} Multiple vehicle classification failed.")
        sys.exit(1)

    # Test 5: Different cameras have different stop-line thresholds
    print("\n[Test 5] Different camera stop lines")
    camera_sensitive_box = [220, 145, 340, 240]
    is_blr_001, _, details_001 = detector.check_stop_line_violation(
        frame, camera_sensitive_box, "car", camera_id="CAM_BLR_001"
    )
    is_blr_002, _, details_002 = detector.check_stop_line_violation(
        frame, camera_sensitive_box, "car", camera_id="CAM_BLR_002"
    )
    print(f"  CAM_BLR_001 line_y={details_001['stop_line']['y']} -> {is_blr_001}")
    print(f"  CAM_BLR_002 line_y={details_002['stop_line']['y']} -> {is_blr_002}")
    if is_blr_001 and not is_blr_002:
        print(f"  {PASS} Camera-specific stop-line positions are respected.")
    else:
        print(f"  {FAIL} Camera-specific stop-line behavior is incorrect.")
        sys.exit(1)

    # Test 6: Polygon-based stop-line zone
    print("\n[Test 6] Polygon stop-line zone")
    polygon_box = [250, 150, 350, 240]  # front bumper inside CAM_BLR_003 polygon band
    is_polygon_viol, _, polygon_details = detector.check_stop_line_violation(
        frame, polygon_box, "bus", camera_id="CAM_BLR_003"
    )
    print(f"  Stop Line Type: {polygon_details['stop_line']['type']}, Violation: {is_polygon_viol}")
    if is_polygon_viol and polygon_details["stop_line"]["type"] == "polygon":
        print(f"  {PASS} Polygon-based stop-line zone was evaluated correctly.")
    else:
        print(f"  {FAIL} Polygon-based stop-line zone check failed.")
        sys.exit(1)

    # Test 7: Annotation rendering
    print("\n[Test 7] Stop-line evidence annotation")
    annotated = detector.annotate_stop_line_violation(
        frame,
        crossing_box,
        stop_line=details["stop_line"],
        plate_text="KA03MM8812",
        location="Silk Board"
    )
    if annotated is not None and annotated.shape == frame.shape and np.any(annotated != frame):
        print(f"  {PASS} Stop-line evidence annotation rendered successfully.")
    else:
        print(f"  {FAIL} Stop-line evidence annotation failed.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ALL STOP-LINE VIOLATION DETECTION TESTS PASSED!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_tests()
