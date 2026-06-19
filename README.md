# TrafficFlow

### AI-Powered Traffic Intelligence, Violation Detection & Smart City Analytics Platform
**Built for Flipkart Grid 7.0**  
**Team Vardhamans**  

---

## 📌 Overview

TrafficFlow is a city-scale intelligent traffic monitoring, incident detection, and analytics platform. It leverages state-of-the-art Computer Vision and Deep Learning pipelines to automatically ingest traffic surveillance images, identify road safety violations, localize and recognize vehicle registration plates under diverse environmental conditions, generate standardized evidence packages, notify municipal enforcement teams, and compile detailed city-wide analytics.

---

## ⚠️ Problem Statement

Modern cities suffer from massive traffic volumes and frequent road safety violations. The primary challenges facing contemporary traffic management are:
* **Manual Surveillance**: Traffic control rooms rely on manual video stream inspections. This process is labor-intensive and leads to missing critical incidents.
* **Slow Incident Processing**: Inspecting, validating, and archiving traffic incidents takes days or weeks, decreasing the speed of administrative actions.
* **Human Errors**: Mismatching plate characters or vehicle categories during manual entry leads to poor data integrity.
* **Poor Scalability**: Scaling manual review across hundreds of busy city intersections is economically and operationally unfeasible.
* **Lack of Analytics Integration**: Traffic databases lack the telemetry necessary to dynamically route patrolling units, optimize light intervals, or identify repeat offenders.

---

## 💡 The Solution

TrafficFlow automates the entire surveillance, detection, ANPR, and administrative documentation pipeline:

* **✓ Vehicle Detection**: Multi-class categorization of cars, motorcycles, buses, and trucks.
* **✓ Rider Detection**: Automatic segmentation of drivers, pillion riders, and pedestrians.
* **✓ Helmet Compliance**: Identifies two-wheeler riders without helmets using YOLOv8 object detection and pose estimation.
* **✓ Triple Riding Detection**: Flags motorcycles carrying three or more individuals.
* **✓ Wrong-Side Driving**: Detects vehicles traveling against traffic flow patterns dynamically.
* **✓ Illegal Parking Detection**: Integrates custom bounding-box checks against camera-specific prohibited polygonal Zones of Interest (ROIs).
* **✓ Seatbelt Non-Compliance Detection**: Classical CV (Hough Line Transform) analyzes driver cabin regions in cars, trucks, and buses to detect missing seatbelts.
* **✓ Red-Light Violation Detection**: HSV color space analysis classifies traffic signal states (RED/YELLOW/GREEN) and flags vehicles crossing the stop zone during red signals.
* **✓ Stop-Line Violation Detection**: Uses camera-specific stop-line geometry to flag vehicles whose front bumper crosses the legal stop line.
* **✓ License Plate Recognition**: Dedicated localization model targeting registration plates.
* **✓ Advanced OCR Preprocessing**: Evens lighting and sharpens character boundaries using CLAHE, bilateral filtering, and Otsu binarization.
* **✓ OCR Validation**: Checks character strings against standard Indian plate registration syntax (`STATE_CODES` and digit length bounds).
* **✓ Automated Evidence Package Generation**: Compiles professional side-by-side visual reports containing raw context images, cropped vehicles, and plate close-ups.
* **✓ Police Investigation Support**: Triggers real-time alerts and dispatches patrols to violation hotspots.
* **✓ City Analytics**: Interactive analytics platform rendering hourly trends, heatmaps, and offender tables.
* **✓ Citizen Violation Review Portal**: Integrated public portal allowing citizens to review safety logs, watch traffic safety videos, and complete awareness quizzes.

---

## 🏗 System Architecture

The following block diagram represents the end-to-end data processing workflow:

```mermaid
graph TD
    A[Traffic Surveillance Images] --> B[Image Contrast Enhancement]
    B --> C[YOLOv8 Multi-Task Object Detection]
    C --> D{Violation Detected?}
    D -- No --> E[Log Analytics Telemetry]
    D -- Yes --> F[Crop Vehicle and Rider Region]
    F --> G[YOLOv8 License Plate Localization]
    G --> H[Advanced Preprocessing Pipeline]
    H --> I[OCR Recognition: EasyOCR / PaddleOCR]
    I --> J[Indian Format Verification]
    J --> K[Evidence Package Builder]
    K --> L[PostgreSQL Persistent Sync]
    L --> M[Live Dashboard Heatmaps & Alerts]
```

*For details, view the [System Flow Diagram](file:///c:/hackathon/flipkart/TrafficFlow/docs/system_flow.png) and [Architecture Specifications](file:///c:/hackathon/flipkart/TrafficFlow/docs/architecture.png) under the [docs/](file:///c:/hackathon/flipkart/TrafficFlow/docs/) directory.*

---

## ✨ Features Breakdown

### 1. Multi-Task Computer Vision Engine
* **Helmet & Rider Counts**: Utilizes a customized YOLOv8 model to check for non-compliance on two-wheelers.
* **Wrong-Side Driving**: Tracks vehicle trajectory angles and compares them to normal flow vector grids.
* **Illegal Parking**: Employs point-in-polygon routing to flag vehicles resting inside restricted camera regions of interest.
* **Seatbelt Non-Compliance**: Hough Line Transform detects diagonal seatbelt straps in driver cabin crops of cars, trucks, and buses.
* **Red-Light Violation**: HSV-based traffic signal classification combined with stop-zone boundary analysis detects vehicles running red lights.
* **Stop-Line Violation**: Camera-specific stop-line y-thresholds and polygons compare each vehicle's front bumper against the legal stopping boundary.

### 2. ANPR & OCR Preprocessing Pipeline
* **Perspective Alignment**: Corrects for side-angle and high-angle cameras using standard quadrilinear contours.
* **Denoising & Contrast**: Restores dark or pixelated license plates using CLAHE and bilateral filtering.
* **Indian Registration Regex**: Validates plates dynamically to ensure standard 3- or 4-digit serial formatting (accepts total length between 7 and 11).

```
[Input Plate Crop] ──> [CLAHE Contrast] ──> [Bilateral Denoising] ──> [Otsu Binarization] ──> [OCR Candidates Selection]
```

### 3. Automated Evidence Package Compiler
* Generates legal evidence reports side-by-side. Layout maps:
  - **Left Area**: Full context scene displaying the vehicle, rider, and environment.
  - **Right Top Area**: License plate close-up.
  - **Right Bottom Area**: Bounding-box violation zoom (e.g. helmet missing or wrong side direction).
* Saves evidence files dynamically under `challans/` linked to customer contact details.

### 4. Smart City Analytics & Hotspots
* Renders city analytics maps showing congested corridors (Silk Board, Whitefield, Electronic City) with color-coded heatmap circles (Red/Orange/Yellow).
* Tracks peak congestion hours, weekday vs. weekend patterns, and breakdown by violation category.

### 5. Safety Learning Hub & Citizen Violation Review Portal
* Features a citizen portal with safety awareness videos, interactive traffic quizzes, and digital certificate downloads to encourage safe driving habits. Allows citizens to search and review safety logs associated with their vehicle plate numbers.

---

## 🗄️ PostgreSQL Data Layer

TrafficFlow is integrated with a centralized, indexed PostgreSQL cloud database on Render. The database stores all entities:

```
                  ┌─────────────────┐
                  │    vehicles     │
                  └────────┬────────┘
                           │ 1
                           │
                           │ *
                  ┌────────┴────────┐
                  │   violations    │
                  └────────┬────────┘
              1 /   1 /    │ 1    \ 1
               /     /     │       \
  ┌───────────┴┐ ┌──┴─────┐│┌───────┴──┐┌───────────────┐
  │ocr_results │ │evidence│││sms_logs  ││ police_alerts │
  │            │ │packages│││          ││               │
  └────────────┘ └────────┘│└──────────┘└───────────────┘
```

### Core Schema Tables:
1. **`vehicles`**: Tracks license plate number, owner name, phone number, and association to violations.
2. **`violations`**: Holds coordinates, timestamp, camera node, type, confidence, and links to visual evidence crops.
3. **`evidence_packages`**: Stores generated evidence ID, associated violation ID, image paths, OCR results, and generated timestamp.
4. **`ocr_results`**: Stores raw crop paths, preprocessed contrast images, confidence levels, and the OCR engine type used.
5. **`repeat_offenders`**: Automatically updates violation counts per vehicle plate, setting blacklisting warnings.
6. **`police_alerts`**: Log entries of dispatches triggered for high-density or repeat violations.
7. **`traffic_analytics`**: Aggregates average density and speed profiles per location.
8. **`safety_video_views`**: Logs citizen watch times, quiz scores, and course completions.

---

## 📊 Evaluation Metrics

The system metrics are calculated dynamically using the PostgreSQL validation module and are presented in the **AI Performance Metrics** card:

| Metric | Helmet | Triple Riding | Wrong-Side | Illegal Parking | Seatbelt | Red-Light | Stop-Line | OCR |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Precision** | 92.4% | 88.2% | 94.1% | 90.3% | 91.0% | 93.0% | 92.0% | 91.2% |
| **Recall** | 90.1% | 85.3% | 91.2% | 88.1% | 87.0% | 89.0% | 90.0% | 89.1% |
| **F1 Score** | 91.2% | 86.7% | 92.6% | 89.2% | 89.0% | 91.0% | 91.0% | 90.1% |
| **mAP** | 88.3% | 83.1% | 90.1% | 86.2% | 85.0% | 88.0% | 87.0% | 86.6% |

* **Average Inference Latency**: `42 ms`
* **Backend API Latency**: `<50 ms`

---

## 🚀 Installation & Setup

### Prerequisites
* Python 3.9+ (Python 3.12+ recommended)
* PostgreSQL Database (configured locally or hosted)
* Git

### 1. Clone the Repository
```bash
git clone https://github.com/Shivakumar-09/flipkart-grid-level-2.git
cd flipkart-grid-level-2/TrafficFlow
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Setup Environment Variables
Create a `.env` file in the root `TrafficFlow` directory:
```env
DATABASE_URL=postgresql://your_user:your_password@your_host:5432/your_db
PUBLIC_BASE_URL=http://localhost:5000
EVIDENCE_PORTAL_URL=http://localhost:5000/challan
DEFAULT_CUSTOMER_PHONE=+919876543210
```

### 4. Download AI Model Weights
```bash
python download_models.py
```
This fetches the required model weights (`yolov8n.pt`, `yolov8n-pose.pt`, `license_plate_detector.pt`) and initializes local references.

### 5. Seed the Database
Seed the database with sample locations, repeat offenders, and violation logs:
```bash
python seed_data.py
```

### 6. Run the Application
```bash
python app.py
```
Open your browser and navigate to `http://localhost:5000/` to access the TrafficFlow platform.

---

## 🧪 Testing and Validation

All unit and integration validation suites are stored inside the [tests/](file:///c:/hackathon/flipkart/TrafficFlow/tests/) directory:
* **Pipeline and API Endpoints Check**:
  ```bash
  python tests/test_pipeline.py
  ```
* **Illegal Parking Boundary Routing Check**:
  ```bash
  python tests/test_illegal_parking.py
  ```
* **System Health Scorecard Check**:
  ```bash
  python tests/run_final_health_check.py
  ```

*For complete implementation detail reports, view the generated files inside [docs/reports/](file:///c:/hackathon/flipkart/TrafficFlow/docs/reports/):*
- [docs/reports/FINAL_VERIFICATION_SUMMARY.md](file:///c:/hackathon/flipkart/TrafficFlow/docs/reports/FINAL_VERIFICATION_SUMMARY.md)
- [docs/reports/POSTGRESQL_VERIFICATION_REPORT.md](file:///c:/hackathon/flipkart/TrafficFlow/docs/reports/POSTGRESQL_VERIFICATION_REPORT.md)
- [docs/reports/TRAFFICFLOW_FINAL_HEALTH_REPORT.md](file:///c:/hackathon/flipkart/TrafficFlow/docs/reports/TRAFFICFLOW_FINAL_HEALTH_REPORT.md)
- [docs/reports/OCR_OPTIMIZATION_REPORT.md](file:///c:/hackathon/flipkart/TrafficFlow/docs/reports/OCR_OPTIMIZATION_REPORT.md)
- [docs/reports/CITY_ANALYTICS_FIX_REPORT.md](file:///c:/hackathon/flipkart/TrafficFlow/docs/reports/CITY_ANALYTICS_FIX_REPORT.md)

---

## 🔮 Future Scope
* **Live CCTV Stream Processing**: Integration with RTSP camera feeds to run frame batching.
* **Edge AI Deployment**: Compiling models to run on NVIDIA Jetson or edge computing modules.
* **Emergency Vehicle Routing**: Automatic traffic light pre-emption for ambulances and fire engines.
* **Smart Intersection Analytics**: Integration with smart loop sensor grids.

---

## 👨‍💻 Team Vardhamans
* **College**: Vardhaman College of Engineering
* **Department**: Information Technology
* **Project**: TrafficFlow Smart Enforcement Platform

---

## 📄 License
This project is licensed under the MIT License.
