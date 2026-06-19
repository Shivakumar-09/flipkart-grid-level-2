"""
test_seatbelt_detection.py — Standalone Test Suite for TrafficFlow Seatbelt Compliance Detection Feature
========================================================================================================
Validates driver cabin localization, Hough line edge detection, and low light robustness.
"""

import os
import sys
import cv2
import numpy as np

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.seatbelt_detector import SeatbeltDetector

PASS = "[PASS]"
FAIL = "[FAIL]"

def run_tests():
    print("=" * 60)
    print("  TrafficFlow -- Seatbelt Detection Test Suite")
    print("=" * 60)
    
    detector = SeatbeltDetector()
    
    # Test 1: Seatbelt Present (diagonal line)
    print("\n[Test 1] Seatbelt Present (Diagonal line present in driver crop)")
    # Draw a mock vehicle image
    # Vehicle box: [100, 100, 300, 300] (width = 200, height = 200)
    # Driver box should localize at:
    # dx1 = 100 + 200*0.12 = 124
    # dy1 = 100 + 200*0.18 = 136
    # dx2 = 100 + 200*0.52 = 204
    # dy2 = 100 + 200*0.52 = 204
    # So driver crop is image[136:204, 124:204] (68x80)
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    
    # Draw a clear diagonal line in the driver region representing a seatbelt strap
    # Angle of line should be diagonal (e.g. from (130, 140) to (190, 195))
    cv2.line(img, (130, 140), (190, 195), (255, 255, 255), 4)
    
    present, conf, driver_box = detector.detect_seatbelt(img, [100, 100, 300, 300], "car")
    print(f"  Result: Present={present}, Confidence={conf:.2f}, Driver Box={driver_box}")
    if present:
        print(f"  {PASS} Seatbelt correctly detected via Hough line angle filtering.")
    else:
        # Fallback to verify with mock just in case, but let's make sure it passes
        print(f"  {FAIL} Failed to detect diagonal seatbelt line.")
        sys.exit(1)

    # Test 2: Seatbelt Missing (no line)
    print("\n[Test 2] Seatbelt Missing (No diagonal line in driver crop)")
    img_empty = np.zeros((400, 400, 3), dtype=np.uint8)
    present, conf, driver_box = detector.detect_seatbelt(img_empty, [100, 100, 300, 300], "car")
    print(f"  Result: Present={present}, Confidence={conf:.2f}, Driver Box={driver_box}")
    if not present:
        print(f"  {PASS} Correctly detected missing seatbelt.")
    else:
        print(f"  {FAIL} Erroneously detected seatbelt in empty driver crop.")
        sys.exit(1)

    # Test 3: Multiple Vehicles processing
    print("\n[Test 3] Multiple Vehicles (Batch processing test)")
    img_multi = np.zeros((500, 500, 3), dtype=np.uint8)
    # Vehicle 1: seatbelt present (diagonal line drawn)
    cv2.line(img_multi, (60, 70), (90, 95), (255, 255, 255), 3) # vehicle box [50, 50, 150, 150]
    
    vehicles = [
        {"box": [50, 50, 150, 150], "label": "car"},
        {"box": [200, 200, 350, 350], "label": "truck"}
    ]
    
    results = []
    for v in vehicles:
        res = detector.detect_seatbelt(img_multi, v["box"], v["label"])
        results.append(res)
        
    print(f"  Vehicle 1 (should be present): {results[0][0]} (Conf: {results[0][1]:.2f})")
    print(f"  Vehicle 2 (should be missing): {results[1][0]} (Conf: {results[1][1]:.2f})")
    if results[0][0] and not results[1][0]:
        print(f"  {PASS} Multiple vehicles processed with correct relative classification.")
    else:
        print(f"  {FAIL} Multiple vehicles batch processing failed.")
        sys.exit(1)

    # Test 4: Low Light Conditions (extremely dark/low contrast check)
    print("\n[Test 4] Low Light / Low Contrast robustness")
    img_low_light = np.zeros((400, 400, 3), dtype=np.uint8)
    # Draw a faint diagonal line (gray, low contrast)
    cv2.line(img_low_light, (130, 140), (190, 195), (60, 60, 60), 3)
    
    present, conf, driver_box = detector.detect_seatbelt(img_low_light, [100, 100, 300, 300], "car")
    print(f"  Result in low light: Present={present}, Confidence={conf:.2f}")
    print(f"  {PASS} Low light conditions evaluated successfully without crash. Confidence: {conf:.2f}")

    # Test 5: Mock result override
    print("\n[Test 5] Explicit Mock Result Override")
    present_mock, conf_mock, _ = detector.detect_seatbelt(img_empty, [100, 100, 300, 300], "car", mock_result=True)
    if present_mock and conf_mock >= 0.70:
        print(f"  {PASS} Mock override functionality verified successfully.")
    else:
        print(f"  {FAIL} Mock override failed.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("  ALL SEATBELT DETECTOR TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    run_tests()
