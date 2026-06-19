# Seatbelt Violation Codebase Audit Report

## 1. Existing Violation Architecture

The TrafficFlow violation pipeline is managed by `ViolationEngine` in [violation_engine.py](file:///c:/hackathon/flipkart/TrafficFlow/engine/violation_engine.py). It receives a traffic camera frame path, runs detection modules, extracts OCR plate numbers for non-compliant vehicles, and returns violation details.

```
Traffic Frame File Path
          ↓
[violation_engine.process_image]
          ↓
[1. Image Quality Enhancement] (CLAHE)
          ↓
[2. VehicleDetector.detect()] (YOLOv8 Multi-Class Object Detection)
          ↓
[3. Extraction of motorcycles / cars / persons]
          ├─► Motorcycle Processing (Rider Association, Triple Riding & Overloading check)
          ├─► Helmet compliance checks (Pose keypoints + Skin/Hair color HSV filters)
          └─► Wrong-Side Driving checks (Trajectory angle heuristics)
          ↓
[4. OcrEngine.extract_plate_details()] (YOLOv8 Plate detection + EasyOCR text candidate)
          ↓
[5. Evidence Builder] (PDF layout formatting & crops creation)
          ↓
[6. PostgreSQL Database Sync & Alerts Dispatch]
```

## 2. Helmet Detection Implementation Analysis

* **Class**: `HelmetDetector` in [helmet_detector.py](file:///c:/hackathon/flipkart/TrafficFlow/models/helmet_detector.py)
* **Model**: YOLOv8 Pose (`yolov8n-pose.pt`)
* **Pipeline**:
  1. Crop the associated person bounding box.
  2. Run pose estimation to find the 5 head keypoints (eyes, nose, ears).
  3. Crop the head region based on keypoint min/max boundaries. If pose fails, fallback to cropping the top 20% of the person box.
  4. Perform HSV color analysis on the head crop:
     - Skin tone mask: `H: [0, 25]`, `S: [20, 150]`, `V: [50, 255]`.
     - Hair mask (black/brown): `S <= 55`, `V <= 80`.
     - Bare head ratio = `(skin_pixels + hair_pixels) / total_head_pixels`.
  5. If the bare head ratio is > 60%, classify as **NO HELMET** (`has_helmet = False`).
  6. Scale confidence score into `[0.70, 0.99]`.

## 3. Violation Generation & Storage Flow

* When a violation is flagged:
  1. A metadata dictionary is created containing the violation type (e.g. `HELMET_VIOLATION`, `TRIPLE_RIDING`, `WRONG_SIDE_DRIVING`), coordinates bounding box, confidence, and plate OCR results.
  2. An annotated image is drawn (using OpenCV box overlays with specific coloring).
  3. The Flask app endpoint `/api/upload` invokes `ViolationEngine` and receives the result payload.
  4. The handler writes the details to PostgreSQL:
     - Check/Insert `Vehicle` to get vehicle ID.
     - Insert `Violation` record.
     - Insert `OCRResult` record mapping OCR details.
     - Update `RepeatOffender` counts (handling multi-violation race conditions).
     - Log `PoliceAlert` if severity is high.
     - Trigger SMS alerts.

## 4. Evidence Package Architecture

* **Engine**: `EvidenceEngine` in [evidence_engine.py](file:///c:/hackathon/flipkart/TrafficFlow/engine/evidence_engine.py).
* **Generation**:
  - Automatically cropped frames: vehicle crop, plate crop, and close-up violation crop.
  - Side-by-side visual PDF compilation using ReportLab Flowables.
  - Layout: Left Column (Full scene context showing vehicle and person), Right Column (Zoomed license plate + Close-up violation crop).

---

## 🏁 Audit Conclusion & Integration Plan

The new `SeatbeltDetector` will follow a similar architecture to `HelmetDetector` but adapt for inside-cabin vehicle regions:
1. Identify vehicle objects (`car`, `truck`, `bus`) using the existing `VehicleDetector`.
2. Localize the driver cabin region (upper-left quadrant for standard RHD facing cameras).
3. Analyze the driver crop for diagonal seatbelt strap pixels (using Hough Line angle filters).
4. If diagonal line is missing, raise a `SEATBELT_VIOLATION`.
5. Run the existing plate detection and OCR pipeline to extract the registration number.
6. Build a side-by-side evidence report saving the output crop as `seatbelt_evidence.jpg`.
7. Write the entries to PostgreSQL tables.
