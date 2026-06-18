# Deployment Strategy — TrafficFlow Platform

This document describes the scale-out plan, infrastructure configuration, containerization, and data policies for implementing TrafficFlow across Bengaluru's smart city surveillance grid.

---

## 1. Scale-Out Architecture

To process 50 million images/day from 1000+ CCTV cameras, a distributed microservices model is implemented:

```
                            [ CCTV CAMERAS ]
                                   │ (RTSP Stream)
                                   ▼
                         [ Load Balancer (NGINX) ]
                                   │
             ┌─────────────────────┼─────────────────────┐
             ▼                     ▼                     ▼
     [ API Node 1 ]         [ API Node 2 ]         [ API Node 3 ]
     (FastAPI/YOLO)         (FastAPI/YOLO)         (FastAPI/YOLO)
             │                     │                     │
             └─────────────────────┼─────────────────────┘
                                   ▼
                       [ Message Queue (RabbitMQ) ]
                                   │
                                   ▼
                       [ OCR & Database Worker ]
                        (EasyOCR GPU Cluster)
                                   │
             ┌─────────────────────┴─────────────────────┐
             ▼                                           ▼
      [ PostgreSQL DB ]                          [ AWS S3 Storage ]
   (Violations/Metadata)                         (Evidence Images)
```

### Stream Pipeline Details
*   **API Node Layer**: FastAPI applications deployed on NVIDIA Jetson / edge nodes or cloud instances. They run the vehicle tracker and flag suspected violations.
*   **Queueing Layer**: Suspected violation frames (including cropped vehicle boxes) are pushed to a RabbitMQ queue to prevent drops.
*   **OCR Worker Cluster**: Dedicated high-VRAM GPU instances pull messages from RabbitMQ, execute plate text extraction (EasyOCR/PaddleOCR), and load the parsed results to a central database.

---

## 2. Docker Containerization

Below is the Docker configuration structure to containerize the application for orchestration (e.g. Kubernetes).

### `Dockerfile`
```dockerfile
FROM pytorch/pytorch:2.2.1-cuda12.1-cudnn8-runtime

# System dependencies
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgomp1 \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download base models to prevent download at container startup
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt'); YOLO('yolov8n-pose.pt')"

COPY . .

EXPOSE 5000

ENV FLASK_APP=app.py
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]
```

---

## 3. Database Schema

The system uses a highly structured relational schema. For local testing, SQLite is used; for production, this maps to PostgreSQL.

```sql
CREATE TABLE IF NOT EXISTS violations (
    violation_id VARCHAR(36) PRIMARY KEY,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    camera_id VARCHAR(50) NOT NULL,
    location VARCHAR(100) NOT NULL,
    vehicle_type VARCHAR(20) NOT NULL,
    violation_type VARCHAR(50) NOT NULL,
    plate_number VARCHAR(15),
    confidence DOUBLE PRECISION NOT NULL,
    evidence_image_path TEXT NOT NULL,
    status VARCHAR(20) DEFAULT 'PENDING_REVIEW'
);

CREATE TABLE IF NOT EXISTS analytics_summary (
    id SERIAL PRIMARY KEY,
    date DATE UNIQUE,
    total_violations INT,
    helmet_count INT,
    seatbelt_count INT,
    triple_riding_count INT,
    wrong_side_count INT,
    parking_count INT
);
```

---

## 4. Evidence Storage Policy

*   **Hot Storage (First 30 Days)**: All annotated violation JPEG/PNG files are stored on high-speed block storage (or AWS S3 Standard) for rapid querying and officer validation on the dashboard.
*   **Warm Storage (Day 31–180)**: Compressed images and detailed SQLite/JSON audit trails are moved to Infrequent Access storage (AWS S3-IA).
*   **Cold Storage (Day 181+)**: Legal evidence is archived on tape/AWS Glacier. Metadata records remain in the PostgreSQL database index indefinitely to track repeat offenders.
*   **Security & Compliance**: All stored evidence is signed with SHA-256 hashes and timestamped to maintain strict chain-of-custody validity in traffic courts.
