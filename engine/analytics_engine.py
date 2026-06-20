import os
import json
import logging
import time
from datetime import datetime, timedelta, time as time_type
from functools import wraps
from sqlalchemy import func, Date
from database.postgres import (
    SessionLocal, Vehicle, Violation, Challan, OCRResult,
    RepeatOffender, PoliceAlert, SMSLog, Analytics
)

logger = logging.getLogger("AnalyticsEngine")

# Simple caching decorator for analytics methods
def analytics_cache(timeout=30):
    """Cache decorator for analytics methods"""
    def decorator(f):
        cache_store = {}
        cache_timestamps = {}
        
        @wraps(f)
        def decorated_function(self, *args, **kwargs):
            cache_key = f"{f.__name__}"
            now = time.time()
            
            # Check if cache exists and is still valid
            if cache_key in cache_store and cache_key in cache_timestamps:
                if now - cache_timestamps[cache_key] < timeout:
                    return cache_store[cache_key]
            
            # Cache miss - execute function
            result = f(self, *args, **kwargs)
            cache_store[cache_key] = result
            cache_timestamps[cache_key] = now
            return result
        return decorated_function
    return decorator

class AnalyticsEngine:
    def __init__(self, db_path="database/trafficflow.db"):
        self.db_path = db_path
        self.camera_locations = {}
        try:
            current_dir = os.path.dirname(os.path.abspath(__file__))
            proj_root = os.path.dirname(current_dir)
            with open(os.path.join(proj_root, "camera_locations.json"), "r") as f:
                self.camera_locations = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load camera_locations.json in AnalyticsEngine: {e}")

    @analytics_cache(timeout=20)
    def get_summary_metrics(self):
        """
        Aggregate overview metrics: total violations today, most congested area,
        peak traffic hour, active alerts, pending challans, and high risk zones count.
        """
        session = SessionLocal()
        try:
            # 1. Total Violations Today
            today_start = datetime.combine(datetime.now().date(), time_type.min)
            today_end = datetime.combine(datetime.now().date(), time_type.max)
            violations_today = session.query(Violation).filter(
                Violation.timestamp >= today_start,
                Violation.timestamp <= today_end
            ).count()
            
            # 2. Most Congested Area
            row_congested = session.query(
                Analytics.location,
                func.avg(Analytics.traffic_density).label('avg_d')
            ).group_by(Analytics.location).order_by(func.avg(Analytics.traffic_density).desc()).first()
            most_congested = row_congested[0].split(",")[0] if row_congested else "None"
            
            # 3. Peak Traffic Hour
            hour_counts = session.query(
                func.extract('hour', Violation.timestamp).label('hr'),
                func.count(Violation.id)
            ).group_by(func.extract('hour', Violation.timestamp)).all()
            
            hourly_counts = {}
            for row in hour_counts:
                if row.hr is not None:
                    hourly_counts[int(row.hr)] = row[1]
            
            peak_hour = "17:00 - 18:00"
            if hourly_counts:
                best_hour = max(hourly_counts, key=hourly_counts.get)
                peak_hour = f"{best_hour:02d}:00 - {(best_hour+1):02d}:00"
                
            # 4. Active Alerts
            active_alerts = session.query(PoliceAlert).count()
            
            # 5. Pending Challans
            pending_challans = session.query(Challan).filter_by(status='PENDING').count()
            
            # 6. High Risk Zones count
            hotspots = self.get_violation_hotspots()
            high_risk_zones = sum(1 for h in hotspots if h["hotspot_score"] > 30)
            
            return {
                "total_violations_today": violations_today,
                "most_congested": most_congested,
                "peak_hour": peak_hour,
                "active_alerts": active_alerts,
                "pending_challans": pending_challans,
                "high_risk_zones": high_risk_zones
            }
        except Exception as e:
            logger.error(f"Error in get_summary_metrics: {e}")
            return {
                "total_violations_today": 0,
                "most_congested": "None",
                "peak_hour": "17:00 - 18:00",
                "active_alerts": 0,
                "pending_challans": 0,
                "high_risk_zones": 0
            }
        finally:
            session.close()

    @analytics_cache(timeout=30)
    def get_violation_breakdown(self):
        """
        Get count of violations grouped by type.
        """
        session = SessionLocal()
        try:
            v_types = session.query(Violation.violation_type, func.count(Violation.id)).group_by(Violation.violation_type).all()
            breakdown = {
                "HELMET_VIOLATION": 0,
                "TRIPLE_RIDING": 0,
                "WRONG_SIDE_DRIVING": 0,
                "ILLEGAL_PARKING": 0,
                "SEATBELT_VIOLATION": 0,
                "RED_LIGHT_VIOLATION": 0,
                "STOP_LINE_VIOLATION": 0
            }
            for vtype, count in v_types:
                breakdown[vtype] = count
            return breakdown
        except Exception as e:
            logger.error(f"Error in get_violation_breakdown: {e}")
            return {}
        finally:
            session.close()

    @analytics_cache(timeout=30)
    def get_repeat_offenders(self):
        """
        Identify vehicles with multiple violations.
        """
        session = SessionLocal()
        try:
            offenders = session.query(RepeatOffender).order_by(RepeatOffender.violations_count.desc()).limit(5).all()
            return [{
                "plate_number": o.plate_number,
                "violations_count": o.violations_count,
                "last_violation": o.last_violation
            } for o in offenders]
        except Exception as e:
            logger.error(f"Error in get_repeat_offenders: {e}")
            return []
        finally:
            session.close()

    @analytics_cache(timeout=45)
    def get_violation_hotspots(self):
        """
        Aggregate hotspots (locations with calculated hotspot scores and rank).
        Formula: Hotspot Score = (Violation Count * 0.5) + (Traffic Density * 0.3) + (Repeat Offender Count * 0.2)
        """
        session = SessionLocal()
        try:
            # Violation counts per camera
            v_counts = session.query(Violation.camera_id, func.count(Violation.id)).group_by(Violation.camera_id).all()
            violation_counts = {camera_id: count for camera_id, count in v_counts}
            
            # Average density per camera
            densities = session.query(Analytics.camera_id, func.avg(Analytics.traffic_density)).group_by(Analytics.camera_id).all()
            density_averages = {camera_id: float(avg_val or 0.0) for camera_id, avg_val in densities}
            
            # Repeat offenders per camera
            subq = session.query(Vehicle.plate_number).join(Violation).group_by(Vehicle.plate_number).having(func.count(Violation.id) > 1).subquery()
            rep_counts = session.query(
                Violation.camera_id,
                func.count(func.distinct(Vehicle.plate_number))
            ).join(Vehicle).filter(Vehicle.plate_number.in_(session.query(subq.c.plate_number))).group_by(Violation.camera_id).all()
            repeat_offenders_counts = {camera_id: count for camera_id, count in rep_counts}
            
            hotspots = []
            for cam_id, loc_name in self.camera_locations.items():
                v_count = violation_counts.get(cam_id, 0)
                avg_d = round(density_averages.get(cam_id, 0.0), 1)
                rep_count = repeat_offenders_counts.get(cam_id, 0)
                
                # Hotspot Score calculation
                score = round((v_count * 0.5) + (avg_d * 0.3) + (rep_count * 0.2), 1)
                
                # Determine police action
                if avg_d > 7.0:
                    action = "Deploy 2 Traffic Officers to manage gridlock"
                elif v_count > 80:
                    action = "Deploy Mobile Patrol Unit to enforce rules"
                else:
                    action = "Increase Surveillance Coverage"
                    
                # Compute risk level
                if score > 50:
                    risk_level = "CRITICAL"
                elif score > 30:
                    risk_level = "HIGH"
                elif score > 15:
                    risk_level = "MEDIUM"
                else:
                    risk_level = "LOW"
                    
                hotspots.append({
                    "camera_id": cam_id,
                    "location": loc_name,
                    "violation_count": v_count,
                    "avg_density": avg_d,
                    "repeat_offenders": rep_count,
                    "hotspot_score": score,
                    "risk_level": risk_level,
                    "action": action
                })
                
            # Sort by hotspot score descending
            hotspots = sorted(hotspots, key=lambda x: x['hotspot_score'], reverse=True)
            return hotspots
        except Exception as e:
            logger.error(f"Error in get_violation_hotspots: {e}")
            return []
        finally:
            session.close()

    @analytics_cache(timeout=30)
    def get_peak_hours(self):
        """
        Calculate hourly violation counts for 0-23 hours.
        """
        session = SessionLocal()
        try:
            rows = session.query(
                func.extract('hour', Violation.timestamp).label('hr'),
                func.count(Violation.id)
            ).group_by(func.extract('hour', Violation.timestamp)).all()
            
            hourly = {f"{h:02d}:00": 0 for h in range(24)}
            for row in rows:
                if row.hr is not None:
                    hour_label = f"{int(row.hr):02d}:00"
                    hourly[hour_label] = row[1]
            return [{"hour": k, "count": v} for k, v in hourly.items()]
        except Exception as e:
            logger.error(f"Error in get_peak_hours: {e}")
            return []
        finally:
            session.close()

    def get_ward_stats(self):
        """
        Returns violation statistics mapped by Bengaluru BBMP Wards.
        """
        hotspots = self.get_violation_hotspots()
        wards = []
        for h in hotspots[:5]:
            wards.append({
                "ward": f"{h['location']} Area",
                "violations": h["violation_count"],
                "enforcement_efficiency": f"{int(95 - (h['hotspot_score'] * 0.1))}%"
            })
        return wards

    @analytics_cache(timeout=60)
    def get_daily_trends(self):
        """
        Returns daily trends for the last 7 days.
        """
        session = SessionLocal()
        try:
            today = datetime.now()
            # Initialize the last 7 days with 0 counts
            last_7_days = [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
            daily_counts = {day: 0 for day in last_7_days}

            # Query the database for those days
            rows = session.query(
                func.to_char(Violation.timestamp, 'YYYY-MM-DD').label('dt'),
                func.count(Violation.id)
            ).filter(
                func.to_char(Violation.timestamp, 'YYYY-MM-DD').in_(last_7_days)
            ).group_by(func.to_char(Violation.timestamp, 'YYYY-MM-DD')).all()
            
            for r in rows:
                if r[0] in daily_counts:
                    daily_counts[r[0]] = r[1]
            
            labels = []
            counts = []
            for day in last_7_days:
                dt_obj = datetime.strptime(day, "%Y-%m-%d")
                labels.append(dt_obj.strftime("%b %d"))
                counts.append(daily_counts[day])
                
            return {
                "labels": labels,
                "counts": counts
            }
        except Exception as e:
            logger.error(f"Error in get_daily_trends: {e}")
            today = datetime.now()
            labels = [(today - timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]
            return {"labels": labels, "counts": [0]*7}
        finally:
            session.close()

    def get_traffic_density_logs(self):
        """
        Retrieves the last 10 traffic density logs from the analytics table.
        """
        session = SessionLocal()
        try:
            logs = session.query(Analytics).order_by(Analytics.timestamp.desc()).limit(10).all()
            return [{
                "location": log.location,
                "camera_id": log.camera_id,
                "traffic_density": log.traffic_density,
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            } for log in logs]
        except Exception as e:
            logger.error(f"Error in get_traffic_density_logs: {e}")
            return []
        finally:
            session.close()

    @analytics_cache(timeout=60)
    def get_weekend_vs_weekday_trends(self):
        """
        Aggregates violations/density into weekday vs weekend count.
        """
        session = SessionLocal()
        try:
            weekday_count = session.query(Violation).filter(func.extract('dow', Violation.timestamp).between(1, 5)).count()
            weekend_count = session.query(Violation).filter(func.extract('dow', Violation.timestamp).in_([0, 6])).count()
            return {
                "weekday": weekday_count,
                "weekend": weekend_count
            }
        except Exception as e:
            logger.error(f"Error in get_weekend_vs_weekday_trends: {e}")
            return {"weekday": 0, "weekend": 0}
        finally:
            session.close()

    @analytics_cache(timeout=60)
    def get_monthly_trends(self):
        """
        Returns monthly aggregate violation counts for the current year.
        """
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        session = SessionLocal()
        try:
            rows = session.query(
                func.extract('month', Violation.timestamp).label('month_num'),
                func.count(Violation.id)
            ).group_by(func.extract('month', Violation.timestamp)).all()
            
            monthly_data = {m: 0 for m in months}
            for row in rows:
                if row.month_num is not None:
                    m_idx = int(row.month_num) - 1
                    if 0 <= m_idx < 12:
                        monthly_data[months[m_idx]] = row[1]
                        
            return {
                "labels": months,
                "counts": [monthly_data[m] for m in months]
            }
        except Exception as e:
            logger.error(f"Error in get_monthly_trends: {e}")
            return {"labels": months, "counts": [0]*12}
        finally:
            session.close()

    @analytics_cache(timeout=45)
    def get_top_congested_areas(self):
        """
        Aggregate top congested areas from analytics logs.
        """
        session = SessionLocal()
        try:
            rows = session.query(
                Analytics.location,
                func.avg(Analytics.traffic_density).label('avg_d')
            ).group_by(Analytics.location).order_by(func.avg(Analytics.traffic_density).desc()).limit(5).all()
            return [{"location": row[0].split(",")[0], "avg_density": round(row[1], 1)} for row in rows]
        except Exception as e:
            logger.error(f"Error in get_top_congested_areas: {e}")
            return []
        finally:
            session.close()

    def get_camera_heatmap(self):
        """
        Returns latest status for all 10 cameras.
        """
        session = SessionLocal()
        try:
            subq = session.query(
                Analytics.camera_id,
                func.max(Analytics.timestamp).label('max_ts')
            ).group_by(Analytics.camera_id).subquery()
            
            rows = session.query(
                Analytics.camera_id,
                Analytics.location,
                Analytics.traffic_density
            ).join(
                subq,
                (Analytics.camera_id == subq.c.camera_id) & (Analytics.timestamp == subq.c.max_ts)
            ).all()
            
            heatmap = []
            for camera_id, location, density in rows:
                short_loc = location.split(",")[0]
                status = "NORMAL"
                if density > 8.0:
                    status = "CRITICAL"
                elif density > 5.0:
                    status = "HEAVY"
                elif density > 3.0:
                    status = "MODERATE"
                    
                heatmap.append({
                    "camera_id": camera_id,
                    "location": short_loc,
                    "status": status,
                    "density": float(density)
                })
                
            return heatmap
        except Exception as e:
            logger.error(f"Error in get_camera_heatmap: {e}")
            return []
        finally:
            session.close()

    @analytics_cache(timeout=30)
    def get_live_alerts(self):
        """
        Retrieves the 10 most recent police patrol alerts.
        """
        session = SessionLocal()
        try:
            alerts = session.query(PoliceAlert).order_by(PoliceAlert.timestamp.desc()).limit(10).all()
            return [{
                "alert_id": a.alert_id,
                "location": a.location,
                "severity": a.severity,
                "timestamp": a.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "status": a.status
            } for a in alerts]
        except Exception as e:
            logger.error(f"Error in get_live_alerts: {e}")
            return []
        finally:
            session.close()

    @analytics_cache(timeout=20)
    def get_sms_logs(self):
        """
        Retrieves the 10 most recent SMS notifications.
        """
        session = SessionLocal()
        try:
            logs = session.query(SMSLog).order_by(SMSLog.timestamp.desc()).limit(10).all()
            return [{
                "notification_id": log.notification_id,
                "type": log.type,
                "recipient": log.recipient,
                "status": log.status,
                "timestamp": log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "message": log.message,
                "plate_number": log.plate_number,
                "challan_id": log.challan_id
            } for log in logs]
        except Exception as e:
            logger.error(f"Error in get_sms_logs: {e}")
            return []
        finally:
            session.close()

    def get_weekday_trends(self):
        """
        Returns violations count grouped by day of the week (Monday, Tuesday, Wednesday, Thursday, Friday).
        """
        session = SessionLocal()
        try:
            rows = session.query(
                func.extract('dow', Violation.timestamp).label('day_num'),
                func.count(Violation.id)
            ).filter(func.extract('dow', Violation.timestamp).between(1, 5)).group_by(func.extract('dow', Violation.timestamp)).all()
            
            weekday_map = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday"}
            result = {v: 0 for v in weekday_map.values()}
            for row in rows:
                if row.day_num is not None:
                    day_name = weekday_map.get(int(row.day_num))
                    if day_name:
                        result[day_name] = row[1]
            return [{"day": k, "count": v} for k, v in result.items()]
        except Exception as e:
            logger.error(f"Error in get_weekday_trends: {e}")
            return []
        finally:
            session.close()

    def get_weekend_trends(self):
        """
        Returns violations count grouped by day of the week (Saturday, Sunday).
        """
        session = SessionLocal()
        try:
            rows = session.query(
                func.extract('dow', Violation.timestamp).label('day_num'),
                func.count(Violation.id)
            ).filter(func.extract('dow', Violation.timestamp).in_([0, 6])).group_by(func.extract('dow', Violation.timestamp)).all()
            
            weekend_map = {6: "Saturday", 0: "Sunday"}
            result = {v: 0 for v in weekend_map.values()}
            for row in rows:
                if row.day_num is not None:
                    day_name = weekend_map.get(int(row.day_num))
                    if day_name:
                        result[day_name] = row[1]
            return [{"day": k, "count": v} for k, v in result.items()]
        except Exception as e:
            logger.error(f"Error in get_weekend_trends: {e}")
            return []
        finally:
            session.close()

    def get_location_wise_violations(self):
        """
        Returns violations count per camera location.
        """
        session = SessionLocal()
        try:
            rows = session.query(
                Violation.location,
                func.count(Violation.id).label('cnt')
            ).group_by(Violation.location).order_by(func.count(Violation.id).desc()).all()
            return [{"location": row[0].split(",")[0], "count": row[1]} for row in rows]
        except Exception as e:
            logger.error(f"Error in get_location_wise_violations: {e}")
            return []
        finally:
            session.close()
