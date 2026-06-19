import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine, Column, String, Integer, Float, DateTime, ForeignKey, Text, Boolean
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# Setup logging
logger = logging.getLogger("TrafficFlowPostgres")

# Load environment variables
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Database configuration URL
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    logger.warning("DATABASE_URL environment variable is not set. Defaulting to local Singapore-postgres tunnel.")
    DATABASE_URL = "postgresql://vehicles_dp0p_user:ZfLYituZKu0Fr8vAwuuZNK3RryxeUocE@dpg-d8pqqdrtqb8s738f980g-a.singapore-postgres.render.com/vehicles_dp0p"

# Database Engine initialization with pooling and reconnect logic
engine = None
SessionLocal = None
Base = declarative_base()

def initialize_database(max_retries=5, delay=3):
    global engine, SessionLocal
    last_err = None
    
    logger.info(f"Connecting to database at host: {DATABASE_URL.split('@')[-1].split('/')[0]}...")
    
    for attempt in range(1, max_retries + 1):
        try:
            # Setup engine with robust connection pooling
            engine = create_engine(
                DATABASE_URL,
                pool_size=10,
                max_overflow=20,
                pool_timeout=30,
                pool_recycle=1800,
                pool_pre_ping=True
            )
            
            # Simple connection check
            with engine.connect() as conn:
                logger.info("Successfully connected to Render PostgreSQL Cloud Database.")
                
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            return True
        except Exception as e:
            last_err = e
            logger.warning(f"Connection attempt {attempt} failed: {e}. Retrying in {delay}s...")
            time.sleep(delay)
            
    logger.critical("Failed to connect to PostgreSQL Cloud Database after multiple attempts.")
    raise last_err

# --- SQLAlchemy Model Declarations ---

class Vehicle(Base):
    __tablename__ = "vehicles"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    plate_number = Column(String(20), unique=True, index=True, nullable=False)
    owner_name = Column(String(100), default="Vehicle Owner")
    owner_phone = Column(String(20), default="+919876543210")
    
    violations = relationship("Violation", back_populates="vehicle")

class Violation(Base):
    __tablename__ = "violations"
    
    id = Column(String(36), primary_key=True)  # UUID string
    vehicle_id = Column(Integer, ForeignKey("vehicles.id"), nullable=True)
    violation_type = Column(String(50), index=True, nullable=False)
    confidence = Column(Float, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)
    location = Column(String(255), index=True, nullable=False)
    camera_id = Column(String(50), index=True, nullable=False)
    evidence_path = Column(String(255), nullable=False)
    
    vehicle = relationship("Vehicle", back_populates="violations")
    challan = relationship("Challan", back_populates="violation", uselist=False)
    ocr_result = relationship("OCRResult", back_populates="violation", uselist=False)

class Challan(Base):
    __tablename__ = "challans"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    challan_id = Column(String(50), unique=True, index=True, nullable=False)
    violation_id = Column(String(36), ForeignKey("violations.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), default="PENDING", index=True, nullable=False)  # PENDING, PAID
    timestamp = Column(DateTime, nullable=False)
    
    violation = relationship("Violation", back_populates="challan")
    payments = relationship("Payment", back_populates="challan")

class OCRResult(Base):
    __tablename__ = "ocr_results"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    violation_id = Column(String(36), ForeignKey("violations.id"), unique=True, nullable=False)
    ocr_confidence = Column(Float, default=0.0)
    ocr_engine = Column(String(50))
    plate_crop_path = Column(String(255))
    enhanced_plate_path = Column(String(255))
    ocr_result_path = Column(String(255))
    
    violation = relationship("Violation", back_populates="ocr_result")

class RepeatOffender(Base):
    __tablename__ = "repeat_offenders"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    plate_number = Column(String(20), unique=True, index=True, nullable=False)
    violations_count = Column(Integer, default=0)
    last_violation = Column(String(50))
    blacklist_status = Column(String(20), default="WARNING")  # WARNING, BLACKLISTED

class PoliceAlert(Base):
    __tablename__ = "police_alerts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(36), unique=True, nullable=False)
    location = Column(String(255), index=True, nullable=False)
    severity = Column(String(20), nullable=False)  # HIGH, MEDIUM, LOW
    timestamp = Column(DateTime, nullable=False)
    status = Column(String(500), nullable=False)

class PatrolDispatch(Base):
    __tablename__ = "patrol_dispatch"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    dispatch_id = Column(String(36), unique=True, nullable=False)
    location = Column(String(255), nullable=False)
    action = Column(String(255), nullable=False)
    camera_id = Column(String(50), nullable=False)
    timestamp = Column(DateTime, nullable=False)
    status = Column(String(500), nullable=False)

class Payment(Base):
    __tablename__ = "payments"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String(36), unique=True, nullable=False)
    challan_id = Column(String(50), ForeignKey("challans.challan_id"), nullable=False)
    amount = Column(Integer, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    status = Column(String(20), nullable=False)  # e.g., SUCCESS
    
    challan = relationship("Challan", back_populates="payments")

class SMSLog(Base):
    __tablename__ = "sms_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    notification_id = Column(String(36), unique=True, nullable=False)
    type = Column(String(50), nullable=False)  # CUSTOMER_CHALLAN, CONGESTION_ALERT, etc.
    recipient = Column(String(50), nullable=False)
    status = Column(String(20), nullable=False)  # DELIVERED, FAILED, DEMO_SENT
    timestamp = Column(DateTime, nullable=False)
    message = Column(Text)
    plate_number = Column(String(20))
    challan_id = Column(String(50))

class Analytics(Base):
    __tablename__ = "traffic_analytics"
    
    id = Column(String(36), primary_key=True)  # UUID string
    location = Column(String(255), index=True, nullable=False)
    camera_id = Column(String(50), index=True, nullable=False)
    traffic_density = Column(Float, nullable=False)
    timestamp = Column(DateTime, index=True, nullable=False)

class SafetyVideoView(Base):
    __tablename__ = "safety_video_views"
    
    id = Column(String(36), primary_key=True)  # UUID string
    video_id = Column(String(50), nullable=False)
    video_title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    watch_timestamp = Column(DateTime, nullable=False)
    watch_duration = Column(Float, default=0.0, nullable=False)
    completion_percentage = Column(Float, default=0.0, nullable=False)

class CameraNode(Base):
    __tablename__ = "camera_nodes"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    camera_id = Column(String(50), unique=True, index=True, nullable=False)
    location = Column(String(255), nullable=False)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

# Try initialization on module import to expose SessionLocal, but handle exceptions
try:
    initialize_database()
except Exception as ex:
    logger.error(f"PostgreSQL initialization failed at import phase: {ex}")
