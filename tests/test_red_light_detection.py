"""
test_red_light_detection.py — Test Suite for TrafficFlow Red-Light Violation Detection
======================================================================================
Validates traffic light detection, signal classification, stop zone logic, and full violation pipeline.
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
    print("  TrafficFlow -- Red-Light Violation Detection Test Suite")
    print("=" * 60)

    detector = TrafficLightDetector()

    # Test 1: RED Signal Detection
    print("\n[Test 1] RED Signal Detection (HSV color filtering)")
    img_red = np.zeros((400, 600, 3), dtype=np.uint8)
    # Draw a bright red circle in the upper portion (simulating traffic light)
    cv2.circle(img_red, (300, 60), 25, (0, 0, 255), -1)  # Pure red in BGR

    state, conf, light_box = detector.detect_traffic_light(img_red)
    print(f"  Detected State: {state}, Confidence: {conf:.2f}, Light Box: {light_box}")
    if state == "RED" and conf > 0.5:
        print(f"  {PASS} RED signal correctly detected.")
    else:
        print(f"  {FAIL} Failed to detect RED signal.")
        sys.exit(1)

    # Test 2: GREEN Signal Detection
    print("\n[Test 2] GREEN Signal Detection")
    img_green = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.circle(img_green, (300, 60), 25, (0, 255, 0), -1)  # Green in BGR

    state, conf, light_box = detector.detect_traffic_light(img_green)
    print(f"  Detected State: {state}, Confidence: {conf:.2f}")
    if state == "GREEN":
        print(f"  {PASS} GREEN signal correctly detected.")
    else:
        print(f"  {FAIL} Failed to detect GREEN signal. Got: {state}")
        sys.exit(1)

    # Test 3: YELLOW Signal Detection
    print("\n[Test 3] YELLOW Signal Detection")
    img_yellow = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.circle(img_yellow, (300, 60), 25, (0, 200, 255), -1)  # Yellow in BGR

    state, conf, light_box = detector.detect_traffic_light(img_yellow)
    print(f"  Detected State: {state}, Confidence: {conf:.2f}")
    if state == "YELLOW":
        print(f"  {PASS} YELLOW signal correctly detected.")
    else:
        print(f"  {FAIL} Failed to detect YELLOW signal. Got: {state}")
        sys.exit(1)

    # Test 4: No Traffic Light (UNKNOWN)
    print("\n[Test 4] No Traffic Light (dark frame)")
    img_dark = np.zeros((400, 600, 3), dtype=np.uint8)
    state, conf, light_box = detector.detect_traffic_light(img_dark)
    print(f"  Detected State: {state}, Confidence: {conf:.2f}")
    if state == "UNKNOWN":
        print(f"  {PASS} Correctly returned UNKNOWN for empty frame.")
    else:
        print(f"  {FAIL} Should return UNKNOWN for dark frame. Got: {state}")
        sys.exit(1)

    # Test 5: Stop Zone Calculation
    print("\n[Test 5] Stop Zone Boundary Definition")
    stop_zone = detector.define_stop_zone(800, 1200)
    expected_top = int(800 * 0.55)
    print(f"  Stop Zone: top={stop_zone['top']}, bottom={stop_zone['bottom']}")
    if stop_zone["top"] == expected_top and stop_zone["bottom"] == 800:
        print(f"  {PASS} Stop zone boundaries correctly calculated.")
    else:
        print(f"  {FAIL} Stop zone boundaries incorrect.")
        sys.exit(1)

    # Test 6: Vehicle IN Stop Zone
    print("\n[Test 6] Vehicle Inside Stop Zone Detection")
    stop_zone = detector.define_stop_zone(400, 600)
    # Vehicle box centered at bottom of image (well inside stop zone)
    vehicle_box = [100, 250, 250, 380]
    crossed, ratio = detector.is_vehicle_in_stop_zone(vehicle_box, stop_zone)
    print(f"  Crossed: {crossed}, Penetration Ratio: {ratio:.2f}")
    if crossed and ratio > 0.1:
        print(f"  {PASS} Vehicle correctly detected inside stop zone.")
    else:
        print(f"  {FAIL} Failed to detect vehicle in stop zone.")
        sys.exit(1)

    # Test 7: Vehicle OUTSIDE Stop Zone
    print("\n[Test 7] Vehicle Outside Stop Zone Detection")
    # Vehicle box at top of image (far from stop zone)
    vehicle_box_top = [100, 20, 250, 80]
    crossed, ratio = detector.is_vehicle_in_stop_zone(vehicle_box_top, stop_zone)
    print(f"  Crossed: {crossed}, Penetration Ratio: {ratio:.2f}")
    if not crossed:
        print(f"  {PASS} Vehicle correctly identified as outside stop zone.")
    else:
        print(f"  {FAIL} Vehicle should not be in stop zone.")
        sys.exit(1)

    # Test 8: Full Red-Light Violation Pipeline (violation detected)
    print("\n[Test 8] Full Violation Pipeline - RED signal + vehicle in stop zone")
    img_violation = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.circle(img_violation, (300, 60), 25, (0, 0, 255), -1)  # RED light
    vehicle_box = [100, 280, 250, 380]  # Vehicle in lower portion

    is_viol, conf, details = detector.check_red_light_violation(
        img_violation, vehicle_box, "car"
    )
    print(f"  Violation: {is_viol}, Confidence: {conf:.2f}")
    print(f"  Signal: {details['signal_state']}, Penetration: {details['penetration_ratio']:.2f}")
    if is_viol and details["signal_state"] == "RED" and details["stop_zone_crossed"]:
        print(f"  {PASS} Red-light violation correctly detected end-to-end.")
    else:
        print(f"  {FAIL} Full pipeline failed to detect violation.")
        sys.exit(1)

    # Test 9: No Violation - GREEN signal
    print("\n[Test 9] No Violation - GREEN signal + vehicle in stop zone")
    img_no_violation = np.zeros((400, 600, 3), dtype=np.uint8)
    cv2.circle(img_no_violation, (300, 60), 25, (0, 255, 0), -1)  # GREEN
    vehicle_box = [100, 280, 250, 380]

    is_viol, conf, details = detector.check_red_light_violation(
        img_no_violation, vehicle_box, "car"
    )
    print(f"  Violation: {is_viol}, Signal: {details['signal_state']}")
    if not is_viol:
        print(f"  {PASS} Correctly no violation with GREEN signal.")
    else:
        print(f"  {FAIL} Should not flag violation with GREEN signal.")
        sys.exit(1)

    # Test 10: Mock Result Override
    print("\n[Test 10] Mock Result Override")
    img_mock = np.zeros((400, 600, 3), dtype=np.uint8)
    is_viol, conf, details = detector.check_red_light_violation(
        img_mock, [100, 200, 300, 350], "car", mock_result=True
    )
    if is_viol and conf >= 0.80:
        print(f"  {PASS} Mock override (True) verified. Conf: {conf:.2f}")
    else:
        print(f"  {FAIL} Mock override failed.")
        sys.exit(1)

    is_viol_f, conf_f, _ = detector.check_red_light_violation(
        img_mock, [100, 200, 300, 350], "car", mock_result=False
    )
    if not is_viol_f:
        print(f"  {PASS} Mock override (False) verified.")
    else:
        print(f"  {FAIL} Mock override (False) failed.")
        sys.exit(1)

    # Test 11: Annotation Rendering
    print("\n[Test 11] Annotation Rendering (no crash)")
    img_annotate = np.zeros((400, 600, 3), dtype=np.uint8)
    annotated = detector.annotate_red_light_violation(
        img_annotate, [100, 280, 250, 380],
        light_box=[290, 40, 310, 80],
        plate_text="KA03MM8812"
    )
    if annotated is not None and annotated.shape == img_annotate.shape:
        print(f"  {PASS} Annotation rendered without crash. Output shape: {annotated.shape}")
    else:
        print(f"  {FAIL} Annotation rendering failed.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ALL RED-LIGHT VIOLATION DETECTION TESTS PASSED!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_tests()
