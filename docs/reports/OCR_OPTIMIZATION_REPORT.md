# OCR Accuracy Improvements Report

## YOLOv8 Plate Detection Verification
We verify that a dedicated YOLOv8 License Plate detection model is successfully loaded from `license_plate_detector.pt` (Muhammad-Zeerak-Khan/Automatic-License-Plate-Recognition-using-YOLOv8: license_plate_detector.pt) and acts as the primary locator for license plates within vehicle bounding boxes. If this model fails to load, `yolov8n_license_plate.pt` is used as a local candidate.

## OCR Pipeline Preprocessing Improvements
The OCR pipeline in [ocr_engine.py](file:///c:/hackathon/flipkart/TrafficFlow/models/ocr_engine.py) applies a multi-stage image enhancement pipeline:
1. **Perspective Correction**: Detects contours in the plate crop and uses a 4-point transform to straighten the plate bounding box, correcting for high angle or side angles.
2. **CLAHE (Contrast Limited Adaptive Histogram Equalization)**: Evens out lighting and reduces the impact of headlights/sunlight glare.
3. **Bilateral Filter Denoising**: Smooths the plate body while preserving sharp character boundaries.
4. **Sharpening & Contrast Enhancement**: Multiplies image contrast and applies a 2D sharpening kernel to clarify character outlines.
5. **Adaptive Thresholding / Otsu Binarization**: Converts character crops into clean, binary black-and-white lines.

## Multi-Engine Comparison & Candidate Extraction
1. **EasyOCR & PaddleOCR**: Both engines run on the preprocessed variants (if available).
2. **Variants Sweep**: The engine evaluates multiple preprocessed variants (original crop, upscaled crop, contrast-enhanced, adaptive threshold, Otsu, and focal sub-crops).
3. **Rank Selection**: A scoring mechanism selects the candidate with the highest combined confidence and format score.

## Indian Registration Validation
The validation regex inside `_is_valid_plate()` has been refined to:
`r"^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{1,4})$"`
This matches standard Indian plate patterns:
- State prefix: 2 letters (e.g. `TS`, `KA`, `AP`, verified against `STATE_CODES` set)
- District code: 1 or 2 digits
- Series characters: 0 to 3 letters (optional for older or government vehicles)
- Serial sequence: 1 to 4 digits (e.g. matches `AP28DF996` with 3 digits and `KA03AB1234` with 4 digits)
- Accepts total alphanumeric length between 7 and 11.

## Diagnostics Panel
The web interface successfully binds:
- **Original Vehicle**: Cropped vehicle scene box.
- **Plate Crop**: Localized raw plate box.
- **Enhanced Plate**: Binarized/contrast-adjusted binarization crop.
- **OCR Output**: Final validated string.
- **OCR Confidence**: Final candidate confidence.
- **OCR Engine**: Displaying `easyocr` or `paddleocr`.
