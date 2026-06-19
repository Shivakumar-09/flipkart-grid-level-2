# OCR Debugger & Paths Audit Report
===================================

This audit logs the findings and solutions regarding the blank/missing images in the License Plate OCR Debugger panel.

## 1. Problem Investigation

During initial testing, the OCR Debugger panel failed to show the crops:
* **Vehicle Crop**: Blank / Not Found
* **Plate Crop**: Blank / Not Found
* **Enhanced Plate**: Blank / Not Found
* **Detected Plate**: UNKNOWN (even when clearly visible)

## 2. Root Cause Analysis

We identified three critical bottlenecks causing the failure:
1. **Unset Environment Variables**: The Flask web server was started without explicitly loading the `.env` file first, meaning `TRAFFICFLOW_OCR_DEBUG` was defaulting to `"0"` (disabled) in `OcrEngine`. This completely prevented the model from writing debug crops onto the disk.
2. **Concurrency Overwriting**: The debug crops were written to generic file paths like `outputs/ocr_debug/vehicle_crop.jpg`. When multiple clients uploaded files or multiple detections occurred in a single frame, consecutive plate lookups would overwrite the same file concurrently, leading to file locking errors, corrupt image data, or wrong crop displays.
3. **Missing Copy to Evidence Package**: The crops generated during the detection run were kept in the transient `outputs/ocr_debug/` folder and were never copied over to the permanent violation record folder `outputs/evidence/<violation_id>/`. Hence, when viewing past logs, the images could not be rendered since their temporary directories had been purged or overwritten.

## 3. Implemented Solutions

1. **Explicit Environment Loading**: Added explicit `load_dotenv` at the very beginning of `app.py` and `ocr_engine.py` to ensure `TRAFFICFLOW_OCR_DEBUG=1` is loaded before any modules initialize.
2. **UUID-based Isolation**: Modified `violation_engine.py` to generate a unique `debug_id` (UUID) per vehicle crop and pass it as `debug_name` to the OCR engine. All crops are saved under isolated subfolders: `outputs/ocr_debug/<uuid>/`.
3. **Artifact Retention in Evidence Package**: Updated `evidence_engine.py` to copy `vehicle_crop.jpg`, `plate_crop.jpg`, and `enhanced_plate.jpg` to the permanent violation folder: `outputs/evidence/<violation_id>/`.
4. **Attempts Database Serialization**: Added `ocr_attempts` JSON field inside `EvidencePackage.ocr_results` and updated the `/api/logs` endpoint to return this attempts list along with paths.
5. **Dashboard Detailed Modal Integration**: Embedded a premium OCR debugger panel inside the detailed challan modal in `index.html` and bound its elements inside `app.js` using `openChallanModal`.

## 4. OCR Debugger Paths & URL Specification

For every processed image, the paths and URLs are structured as follows:

* **Vehicle Crop**: 
  - Path: `outputs/evidence/<violation_id>/vehicle_crop.jpg`
  - Served URL: `/outputs/evidence/<violation_id>/vehicle_crop.jpg`
  - Status: Valid (copied from run-time UUID directory or falls back to `original.jpg` vehicle box crop)
* **Plate Crop**: 
  - Path: `outputs/evidence/<violation_id>/plate_crop.jpg`
  - Served URL: `/outputs/evidence/<violation_id>/plate_crop.jpg`
  - Status: Valid (copied from ANPR pipeline or auto-cropped)
* **Enhanced Plate**: 
  - Path: `outputs/evidence/<violation_id>/enhanced_plate.jpg`
  - Served URL: `/outputs/evidence/<violation_id>/enhanced_plate.jpg`
  - Status: Valid (copied from preprocessing pipeline)
* **API Log Endpoint**: 
  - Endpoint URL: `/api/logs`
  - Payload: Contains `ocr_attempts` array and `ocr_debug_paths` mapping:
    ```json
    "ocr_debug_paths": {
      "plate_crop": "outputs/evidence/<violation_id>/plate_crop.jpg",
      "enhanced_plate": "outputs/evidence/<violation_id>/enhanced_plate.jpg",
      "ocr_result": "outputs/evidence/<violation_id>/ocr_result.jpg",
      "vehicle_crop": "outputs/evidence/<violation_id>/vehicle_crop.jpg"
    }
    ```
