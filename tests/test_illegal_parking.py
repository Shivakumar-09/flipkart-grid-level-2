"""
test_illegal_parking.py — Standalone Test Suite for TrafficFlow Prohibited Parking Feature
========================================================================================
Validates point-in-polygon logic, vehicle bounding boxes, and camera-specific ROI mappings.
"""

import os
import sys
import numpy as np

# Ensure project root is in the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from models.parking_detector import ParkingDetector

PASS = "[PASS]"
FAIL = "[FAIL]"

def run_tests():
    print("=" * 60)
    print("  TrafficFlow -- Illegal Parking Test Suite")
    print("=" * 60)
    
    detector = ParkingDetector()
    
    # Mock frame representing a 640x480 surveillance camera image
    mock_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # Silk Board (CAM_BLR_001) prohibited zone:
    # Normalized: [[0.4, 0.4], [0.95, 0.4], [0.95, 0.95], [0.4, 0.95]]
    # Pixel coordinates: x from 256 to 608, y from 192 to 456
    
    # Test 1: Vehicle bottom-center inside prohibited zone
    # vehicle_bbox: [300, 250, 400, 350]
    # bottom-center: cx = 350, cy = 350 (inside Silk Board zone)
    print("\n[Test 1] Vehicle inside restricted zone (Silk Board)")
    vehicle_bbox = [300, 250, 400, 350]
    is_parked, conf, zone = detector.check_illegal_parking(
        vehicle_bbox, "CAM_BLR_001", "Silk Board", mock_frame
    )
    if is_parked and conf > 0.8 and zone is not None:
        print(f"  {PASS} Detected inside zone correctly. Zone: {zone}")
    else:
        print(f"  {FAIL} Failed to detect vehicle inside Silk Board zone.")
        sys.exit(1)
        
    # Test 2: Vehicle bottom-center outside prohibited zone
    # vehicle_bbox: [50, 50, 150, 150]
    # bottom-center: cx = 100, cy = 150 (outside Silk Board zone)
    print("\n[Test 2] Vehicle outside restricted zone (Silk Board)")
    vehicle_bbox_outside = [50, 50, 150, 150]
    is_parked_outside, conf_outside, zone_outside = detector.check_illegal_parking(
        vehicle_bbox_outside, "CAM_BLR_001", "Silk Board", mock_frame
    )
    if not is_parked_outside:
        print(f"  {PASS} Correctly classified vehicle as outside the zone.")
    else:
        print(f"  {FAIL} Erroneously flagged outside vehicle as illegally parked.")
        sys.exit(1)
        
    # Test 3: Camera-specific polygon logic (Marathahalli vs Silk Board)
    # Check if a coordinate inside Silk Board's zone is NOT inside Marathahalli's zone
    # Silk Board: x from 256 to 608, y from 192 to 456
    # Marathahalli (CAM_BLR_004) prohibited zone:
    # Normalized: [[0.5, 0.5], [0.95, 0.5], [0.95, 0.95], [0.5, 0.95]]
    # Pixel coordinates: x from 320 to 608, y from 240 to 456
    # A vehicle with bottom-center cx = 280, cy = 200 is inside CAM_BLR_001, but outside CAM_BLR_004!
    print("\n[Test 3] Camera-specific zone routing")
    border_bbox = [240, 150, 320, 200] # cx = 280, cy = 200
    
    is_sb, _, _ = detector.check_illegal_parking(border_bbox, "CAM_BLR_001", "Silk Board", mock_frame)
    is_mh, _, _ = detector.check_illegal_parking(border_bbox, "CAM_BLR_004", "Marathahalli", mock_frame)
    
    if is_sb and not is_mh:
        print(f"  {PASS} Successfully routed camera-specific boundaries.")
    else:
        print(f"  {FAIL} Failed camera-specific boundary check. (SB: {is_sb}, MH: {is_mh})")
        sys.exit(1)
        
    print("\n" + "=" * 60)
    print("  ALL PARKING DETECTOR TESTS PASSED SUCCESSFULLY!")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    run_tests()
