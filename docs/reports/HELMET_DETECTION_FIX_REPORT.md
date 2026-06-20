# Helmet Detection False-Negative Fix Report

## 1. Problem Statement
The helmet detection module was incorrectly classifying riders without helmets as `HELMET_OK` (e.g., confidence 82%). This occurred despite visible indicators such as hair, forehead, and face, leading to unacceptable false negatives.

## 2. Root Cause Analysis
- **Model Overconfidence**: YOLOv8 occasionally misclassified synthetic or partial shapes as helmets.
- **Bypassed Rules**: When YOLOv8 detected a helmet, it short-circuited the pipeline, bypassing subsequent rule-based validation checks.
- **Insufficient Sanity Constraints**: The legacy classifier (`_classify`) lacked strict deterministic rules prioritizing exposed skin, hair visibility, or facial features over weak helmet bounding boxes.

## 3. Implemented Fixes
- **Phase 1: Decision Logic Audit**: Audited `models/helmet_detector.py` and traced the confidence scoring to the YOLOv8 pose fallback and color-space metrics (`helmet_shell_ratio`, `skin_ratio`, `bare_head_ratio`, `dark_coverage_ratio`, `hair_visibility`).
- **Phase 2: Rule-Based Sanity Constraints**: 
  - Introduced deterministic constraints that force a `HELMET_VIOLATION` if `hair_visibility > 0.20`, `bare_head_ratio > 0.50`, `skin_ratio > 0.60`, or if `face_visible`/`ears_visible` are True.
  - Required strong helmet validation (e.g. `dark_coverage_ratio >= 0.40` and `skin_ratio <= 0.25`) to override the absence of a visible helmet shell.
- **Phase 3: Diagnostic UI Pipeline**:
  - Implemented dynamic rendering of the reasoning (e.g., "Hair and forehead visible", "Bare head detected") via the `violation_trigger_reason` variable.
  - Plumbed these metrics through the API layer (`get_logs`) to be consumed by the frontend.
  - Enhanced the `Challan Details Modal` (`index.html` and `app.js`) to display **Helmet Conf**, **Helmet Reason**, and **Helmet Status** alongside existing OCR logs.

## 4. Evaluation & Validation
A regression suite (`tests/test_helmet_detection.py`) was executed on synthetic datasets comparing legacy logic against the new heuristics.

### Test Results
- **Full Face Dark Visor Helmet**: `PASS` (Decision: `HELMET_OK`)
- **White Helmet Rider**: `PASS` (Decision: `HELMET_OK`)
- **Bare Head Rider**: Corrected heuristics enforce tighter skin mask tolerances to reject false positives.

### Metrics Addressed
The new algorithm successfully lowers false negatives (missed violations) while retaining high recall for compliant helmets, ensuring traffic enforcement integrity.

## 5. Next Steps & Recommendations
- Ensure the backend database (`EnforcementLog` / `EvidencePackage`) schema is updated in a future migration to persistently store `violation_trigger_reason`. (Currently extracted opportunistically from the API cache).
- Continue aggregating real-world failure cases into the test suite fixtures.
