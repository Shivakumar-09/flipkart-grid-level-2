import os
import logging
from database.postgres import (
    SessionLocal, Violation, Challan, OCRResult,
    RepeatOffender, PoliceAlert, PatrolDispatch, Payment, SMSLog, Analytics,
    EvidencePackage, Vehicle, SafetyVideoView, CameraNode
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ClearLogs")

def clear_logs():
    # 1. Delete SQLite database if it exists
    sqlite_path = os.path.join("database", "trafficflow.db")
    if os.path.exists(sqlite_path):
        try:
            os.remove(sqlite_path)
            logger.info(f"Successfully deleted local SQLite database: {sqlite_path}")
        except Exception as e:
            logger.error(f"Failed to delete SQLite database: {e}")
    else:
        logger.info("No local SQLite database found to delete.")

    # 2. Clear PostgreSQL enforcement tables
    session = SessionLocal()
    try:
        logger.info("Clearing PostgreSQL enforcement tables...")
        
        # Order of deletion is important due to foreign key constraints
        logger.info("Deleting Payment records...")
        session.query(Payment).delete()
        
        logger.info("Deleting Challan records...")
        session.query(Challan).delete()
        
        logger.info("Deleting OCRResult records...")
        session.query(OCRResult).delete()
        
        logger.info("Deleting EvidencePackage records...")
        session.query(EvidencePackage).delete()
        
        logger.info("Deleting Violation records...")
        session.query(Violation).delete()

        logger.info("Deleting Vehicle records...")
        session.query(Vehicle).delete()
        
        logger.info("Deleting RepeatOffender records...")
        session.query(RepeatOffender).delete()
        
        logger.info("Deleting PoliceAlert records...")
        session.query(PoliceAlert).delete()
        
        logger.info("Deleting PatrolDispatch records...")
        session.query(PatrolDispatch).delete()
        
        logger.info("Deleting SMSLog records...")
        session.query(SMSLog).delete()
        
        logger.info("Deleting Analytics records...")
        session.query(Analytics).delete()
        
        logger.info("Deleting SafetyVideoView records...")
        session.query(SafetyVideoView).delete()

        logger.info("Deleting CameraNode records...")
        session.query(CameraNode).delete()
        
        session.commit()
        logger.info("PostgreSQL enforcement logs cleared successfully.")
    except Exception as e:
        session.rollback()
        logger.error(f"Error clearing PostgreSQL tables: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    clear_logs()
