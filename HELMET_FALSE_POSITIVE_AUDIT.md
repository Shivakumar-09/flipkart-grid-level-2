# Helmet False Positive Audit Report

**Date:** 2026-06-19  
**Issue:** Riders wearing full-face helmets were incorrectly flagged as `HELMET_VIOLATION`  
**Status:** Fixed at source in `models/helmet_detector.py`

---

## 1. Root Cause

The helmet pipeline used **inverse bare-head detection** instead of positive helmet detection:

1. Crop rider head region (YOLO pose keypoints or top 20% fallback)
2. Run HSV segmentation for **skin** and **hair**
3. If `bare_head_ratio = (skin + hair) / total_pixels > 0.60` → classify as **NO HELMET**

### Why full-face helmets failed

For a rider wearing a **dark full-face helmet with visor**:

| Signal | Old behavior | Problem |
|--------|--------------|---------|
| Dark visor pixels | Matched `hair_mask` (`S <= 55`, `V <= 80`) | Visor counted as bare hair |
| `bare_head_ratio` | Often **> 0.60** | Triggered false `HELMET_VIOLATION` |
| Default fallback | `return False, 0.75` on empty crop | Assumed violation when uncertain |

**Exact failure path for the reported image:**

```
person_box → head_crop (top 20% or pose crop)
→ HSV hair_mask matches dark visor (~70%+ of head crop)
→ bare_head_ratio > 0.60
→ has_helmet = False
→ violation_engine creates HELMET_VIOLATION
```

The bug was **not** in rider association — it was in treating **helmet visor pixels as bare hair**.

---

## 2. Affected Files

| File | Change |
|------|--------|
| `models/helmet_detector.py` | Core fix: helmet-shell detection, dark visor handling, debug dict API, visual debug panel |
| `engine/violation_engine.py` | Uses new debug API; only flags violation when `helmet_missing_confidence >= 0.80`; adds `REVIEW_REQUIRED`; association metrics |
| `engine/evidence_engine.py` | Skips challan generation for `REVIEW_REQUIRED` items |
| `tests/test_helmet_detection.py` | Regression suite with synthetic helmet test cases |

---

## 3. Code Changes (Summary)

### `helmet_detector.py`

- Added **positive helmet shell detection**:
  - Light helmets (`V >= 130`)
  - Colored helmets (`S >= 35`, not skin)
  - Dark full-face helmets: `dark_coverage >= 40%` AND `skin_ratio <= 25%`
- Stopped counting dark visor pixels as bare hair when they belong to a helmet shell
- Replaced boolean return with structured debug payload:

```json
{
  "rider_id": 0,
  "helmet_detected": true,
  "helmet_confidence": 0.91,
  "helmet_missing_confidence": 0.09,
  "head_bbox": [x1, y1, x2, y2],
  "helmet_bbox": [x1, y1, x2, y2],
  "decision": "HELMET_OK",
  "violation_trigger_reason": null
}
```

- Added visual debug panel: `outputs/debug/helmet/helmet_debug_rider_{id}.jpg`
- Uncertain cases → `REVIEW_REQUIRED` (no automatic challan)

### `violation_engine.py`

```python
if helmet_result["decision"] == "HELMET_VIOLATION":
    # only when helmet_missing_confidence >= 0.80
elif helmet_result["decision"] == "REVIEW_REQUIRED":
    # human review queue, no fine
elif helmet_result["decision"] == "HELMET_OK":
    # green helmet bbox, no violation
```

---

## 4. Before vs After Results

Validation run: `python tests/test_helmet_detection.py`

| Test Case | Legacy Classifier | New Decision | Violation? |
|-----------|-------------------|--------------|------------|
| Full-face dark visor helmet | **NO HELMET** (bare_head_ratio ~0.85) | **HELMET_OK** | No |
| White helmet rider | HELMET OK | **HELMET_OK** | No |
| Bare head rider | NO HELMET | **HELMET_VIOLATION** | Yes (conf >= 0.80) |

### Accuracy improvement (synthetic regression set)

| Metric | Before | After |
|--------|--------|-------|
| Helmeted rider false positive rate | **50%** (1/2 helmet cases) | **0%** |
| Bare-head detection recall | 100% | **100%** |
| Uncertain cases auto-challenged | 0% routed to review | Routed to `REVIEW_REQUIRED` |

---

## 5. Rider-Head Association Verification

Association metrics now logged per rider:

- `iou` — overlap between person and motorcycle box
- `center_inside` — person center inside motorcycle box
- `center_distance_px` / `center_distance_norm`
- `association_score` — must be >= 0.80 to associate

Helmet debug output includes `association` block from `violation_engine.py`.

---

## 6. Debug Artifacts

After processing an image, inspect:

- `outputs/debug/helmet/helmet_debug_rider_0.jpg` — visual panel (Rider / Head / Helmet crops + scores)
- Application logs — structured helmet debug lines
- `process_result["helmet_debug"]` — JSON array in pipeline output

---

## 7. Validation Commands

```bash
cd TrafficFlow
python tests/test_helmet_detection.py
```

Test fixtures are generated at:

- `tests/fixtures/helmet/full_face_dark_visor_helmet.jpg`
- `tests/fixtures/helmet/white_helmet_rider.jpg`
- `tests/fixtures/helmet/bare_head_rider.jpg`

---

## 8. Recommendations (Future)

1. Train a dedicated YOLO helmet/no-helmet classifier for production accuracy
2. Keep HSV logic as a fast fallback only
3. Monitor `REVIEW_REQUIRED` queue volume in the dashboard
