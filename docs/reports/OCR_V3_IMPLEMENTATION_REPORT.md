# OCR V3 Engine Implementation Report
======================================

This document outlines the architecture, pipeline stages, and voting algorithms implemented in the upgraded OCR V3 engine.

## 1. Engine Architecture

OCR V3 uses a hybrid, multi-engine approach designed to achieve high accuracy and robustness under challenging environmental conditions (night, glare, rain, motion blur):
* **YOLOv8 ALPR**: Detects and localizes the boundary of the license plate within the cropped vehicle frame.
* **EasyOCR (Deep Learning)**: CNN + LSTM based character recognition, running on GPU when available.
* **Tesseract OCR (LSTM Alphanumeric mode)**: Runs PyTesseract configured for strict alphanumeric recognition (`tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789`).
* **Multi-Engine Voting System**: Selects the best plate text from a pool of 8 preprocessing variants processed by both engines.

## 2. Key Pipeline Stages

### A. Adaptive Padding
* Applied **15% adaptive padding** around the raw localized plate bounding box.
* Prevents character clipping at the borders, which is crucial for edge characters (e.g. state code prefix or sequential number suffix).

### B. Preprocessing Variants (8-Fold Generation)
Each localized plate crop undergoes 8 pre-processing filters to construct the candidate pool:
1. **Original Color (Padded)**: Unfiltered cropped region with a border.
2. **CLAHE (Contrast Limited Adaptive Histogram Equalization)**: Equalizes luminance and corrects local glare or shadows.
3. **Bilateral Filter**: Reduces high-frequency noise while preserving clean character boundaries.
4. **Adaptive Threshold**: Generates binarized black-and-white character masks dynamically suited for local lighting.
5. **OTSU Threshold**: Binarizes global histogram peaks to segment clear plates.
6. **Sharpened**: Enhances character edges using an unsharp kernel mask.
7. **Perspective Correction**: Detects the plate boundary quadrilateral contour and performs a 4-point perspective warp.
8. **Super Resolution (2x Lanczos upscaling)**: Multiplies resolution of small plate crops to feed larger inputs to the OCR engines.

### C. Alphanumeric Correction Dictionary
Standard Indian license plate patterns are used to auto-correct character confusions based on character indices:
* **Position 0-1 (State Code)**: Confusions corrected to letters (e.g. `0` -> `O`, `1` -> `I`, `5` -> `S`, `8` -> `B`).
* **Position 2-3 (District Code)**: Confusions corrected to digits (e.g. `O` -> `0`, `I` -> `1`, `S` -> `5`, `B` -> `8`).
* **Position 4-5 (Series letters)**: Confusions corrected to letters.
* **Position 6-9 (Sequential digits)**: Confusions corrected to digits.

### D. Multi-Engine Voting Pool
All OCR outputs from the 8 variants run through a voting classifier:
* **Indian Plate Format Score**: Candidates matching `^([A-Z]{2})([0-9]{1,2})([A-Z]{0,3})([0-9]{1,4})$` receive a **+5.0 weight boost**.
* **Engine Consensus**: Agreement between EasyOCR and Tesseract on a string adds **+3.0 weight**. Agreement between different variants of the same engine adds **+1.5 weight**.
* **Confidence Tuning**: Confidence scores are averaged across agreeing attempts. The string with the highest cumulative weighted score wins.

### E. Early-Exit Optimization
* To minimize latency, if the top YOLO candidate crop processed with the top-tier preprocessing variants (Original, Adaptive, Super Resolution) yields a valid Indian plate with confidence `> 82%`, the engine exits early and returns the text, bypassing remaining processing combinations.
