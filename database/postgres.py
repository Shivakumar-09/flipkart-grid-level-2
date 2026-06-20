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
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.warning("DATABASE_URL environment variable is not set. Database integration is disabled.")

class DummySessionMaker:
    def __call__(self):
        class DummySession:
            def query(self, *args, **kwargs):
                class DummyQuery:
                    def join(self, *args, **kwargs): return self
                    def order_by(self, *args, **kwargs): return self
                    def limit(self, *args, **kwargs): return self
                    def all(self): return []
                    def count(self): return 0
                    def first(self): return None
                return DummyQuery()
            def add(self, *args, **kwargs): pass
            def commit(self, *args, **kwargs): pass
            def rollback(self, *args, **kwargs): pass
            def close(self, *args, **kwargs): pass
        return DummySession()

# Database Engine initialization with pooling and reconnect logic
engine = None
SessionLocal = None
Base = declarative_base()

def initialize_database(max_retries=1, delay=1):
    global engine, SessionLocal
    if not DATABASE_URL:
        logger.warning("No DATABASE_URL set. Using DummySessionMaker for fallback.")
        SessionLocal = DummySessionMaker()
        return False
        
    logger.info("Connecting to database...")
    
    try:
        engine = create_engine(
            DATABASE_URL,
            pool_size=2,
            max_overflow=4,
            pool_timeout=30,
            pool_recycle=1800,
            pool_pre_ping=True
        )
        
        # Check connection once, do not block startup with multiple retries if unavailable
        try:
            with engine.connect() as conn:
                logger.info("Successfully connected to PostgreSQL Database.")
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            return True
        except Exception as e:
            logger.error(f"Failed to connect to PostgreSQL Database on startup: {e}. Falling back to DummySessionMaker.")
            SessionLocal = DummySessionMaker()
            return False
    except Exception as e:
        logger.error(f"Error initializing PostgreSQL engine: {e}. Falling back to DummySessionMaker.")
        SessionLocal = DummySessionMaker()
        return False

def database_health_check():
    """
    Check if the database is connected.
    Returns: "CONNECTED" or "DISCONNECTED"
    """
    if not DATABASE_URL or engine is None:
        return "DISCONNECTED"
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            conn.execute(text("SELECT 1"))
            return "CONNECTED"
    except Exception:
        return "DISCONNECTED"

def database_health():
    """
    Check if the database is connected.
    Returns: {"connected": True/False}
    """
    return {
        "connected": database_health_check() == "CONNECTED"
    }

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
    evidence_package = relationship("EvidencePackage", back_populates="violation", uselist=False)

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

class EvidencePackage(Base):
    __tablename__ = "evidence_packages"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    evidence_id = Column(String(36), unique=True, index=True, nullable=False)
    violation_id = Column(String(36), ForeignKey("violations.id"), nullable=False)
    image_paths = Column(Text, nullable=False)
    ocr_results = Column(Text, nullable=False)
    generated_timestamp = Column(DateTime, nullable=False)
    
    violation = relationship("Violation", back_populates="evidence_package")

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
