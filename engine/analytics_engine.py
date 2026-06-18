import sqlite3
import pandas as pd
import logging
import json
import os
from datetime import datetime, timedelta

logger = logging.getLogger("AnalyticsEngine")

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

    def get_summary_metrics(self):
        """
        Aggregate overview metrics: total violations today, most congested area,
        peak traffic hour, active alerts, pending challans, and high risk zones count.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. Total Violations Today
        today_str = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT COUNT(*) FROM violations WHERE timestamp LIKE ?", (today_str + "%",))
        violations_today = cursor.fetchone()[0]
        
        # 2. Most Congested Area
        cursor.execute("SELECT location, AVG(traffic_density) as avg_d FROM analytics GROUP BY location ORDER BY avg_d DESC LIMIT 1")
        row_congested = cursor.fetchone()
        most_congested = row_congested[0].split(",")[0] if row_congested else "None"
        
        # 3. Peak Traffic Hour
        cursor.execute("SELECT timestamp FROM violations")
        rows_v = cursor.fetchall()
        hourly_counts = {}
        for row in rows_v:
            try:
                dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                hr = dt.hour
                hourly_counts[hr] = hourly_counts.get(hr, 0) + 1
            except Exception:
                pass
        
        peak_hour = "17:00 - 18:00"
        if hourly_counts:
            best_hour = max(hourly_counts, key=hourly_counts.get)
            peak_hour = f"{best_hour:02d}:00 - {(best_hour+1):02d}:00"
            
        # 4. Active Alerts
        cursor.execute("SELECT COUNT(*) FROM alerts")
        active_alerts = cursor.fetchone()[0]
        
        # 5. Pending Challans
        cursor.execute("SELECT COUNT(*) FROM violations WHERE status = 'PENDING'")
        pending_challans = cursor.fetchone()[0]
        
        conn.close()
        
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

    def get_violation_breakdown(self):
        """
        Get count of violations grouped by type.
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("SELECT violation_type FROM violations", conn)
        conn.close()
        
        breakdown = {
            "HELMET_VIOLATION": 0,
            "TRIPLE_RIDING": 0,
            "WRONG_SIDE_DRIVING": 0,
            "ILLEGAL_PARKING": 0,
            "SEATBELT_VIOLATION": 0
        }
        
        for vtype in df['violation_type']:
            if vtype in breakdown:
                breakdown[vtype] += 1
            else:
                breakdown[vtype] = 1
                
        return breakdown

    def get_repeat_offenders(self):
        """
        Identify vehicles with multiple violations.
        """
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query("""
            SELECT plate_number, COUNT(*) as violations_count, MAX(violation_type) as last_violation 
            FROM violations 
            WHERE plate_number != 'UNKNOWN' 
            GROUP BY plate_number 
            HAVING violations_count > 1 
            ORDER BY violations_count DESC 
            LIMIT 5
        """, conn)
        conn.close()
        return df.to_dict(orient="records")

    def get_violation_hotspots(self):
        """
        Aggregate hotspots (locations with calculated hotspot scores and rank).
        Formula: Hotspot Score = (Violation Count * 0.5) + (Traffic Density * 0.3) + (Repeat Offender Count * 0.2)
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Get all violations count per camera_id
        cursor.execute("SELECT camera_id, COUNT(*) FROM violations GROUP BY camera_id")
        violation_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        # Get average traffic density per camera_id
        cursor.execute("SELECT camera_id, AVG(traffic_density) FROM analytics GROUP BY camera_id")
        density_averages = {row[0]: float(row[1]) for row in cursor.fetchall()}
        
        # Get number of repeat offenders per camera_id
        cursor.execute("""
            SELECT camera_id, COUNT(DISTINCT plate_number) 
            FROM violations 
            WHERE plate_number IN (
                SELECT plate_number FROM violations 
                WHERE plate_number != 'UNKNOWN' 
                GROUP BY plate_number HAVING COUNT(*) > 1
            )
            GROUP BY camera_id
        """)
        repeat_offenders_counts = {row[0]: row[1] for row in cursor.fetchall()}
        
        conn.close()
        
        hotspots = []
        for cam_id, loc_name in self.camera_locations.items():
            v_count = violation_counts.get(cam_id, 0)
            avg_d = round(density_averages.get(cam_id, 0.0), 1)
            rep_count = repeat_offenders_counts.get(cam_id, 0)
            
            # Hotspot Score calculation
            score = round((v_count * 0.5) + (avg_d * 0.3) + (rep_count * 0.2), 1)
            
            # Determine police action (Phase 4)
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

    def get_peak_hours(self):
        """
        Calculate hourly violation counts for 0-23 hours.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT strftime('%H', timestamp) as hr, COUNT(*) FROM violations GROUP BY hr")
        rows = cursor.fetchall()
        conn.close()
        
        hourly = {f"{h:02d}:00": 0 for h in range(24)}
        for row in rows:
            hour_label = f"{int(row[0]):02d}:00"
            hourly[hour_label] = row[1]
        return [{"hour": k, "count": v} for k, v in hourly.items()]

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

    def get_daily_trends(self):
        """
        Returns daily trends for the last 7 days.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # Query violations count grouped by date for the last 7 days
        cursor.execute("""
            SELECT substr(timestamp, 1, 10) as dt, COUNT(*) 
            FROM violations 
            GROUP BY dt 
            ORDER BY dt DESC 
            LIMIT 7
        """)
        rows = cursor.fetchall()
        conn.close()
        
        rows = list(reversed(rows))
        
        if not rows:
            # Fallback mock trend
            today = datetime.now()
            labels = [(today - timedelta(days=i)).strftime("%b %d") for i in range(6, -1, -1)]
            counts = [42, 51, 48, 59, 61, 58, 64]
            return {"labels": labels, "counts": counts}
            
        labels = []
        counts = []
        for r in rows:
            try:
                dt_obj = datetime.strptime(r[0], "%Y-%m-%d")
                labels.append(dt_obj.strftime("%b %d"))
            except Exception:
                labels.append(r[0])
            counts.append(r[1])
            
        return {
            "labels": labels,
            "counts": counts
        }

    def get_traffic_density_logs(self):
        """
        Retrieves the last 10 traffic density logs from the analytics table.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT location, camera_id, traffic_density, timestamp FROM analytics ORDER BY timestamp DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_weekend_vs_weekday_trends(self):
        """
        Aggregates violations/density into weekday vs weekend count.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT timestamp FROM violations")
        rows = cursor.fetchall()
        conn.close()
        
        weekday_count = 0
        weekend_count = 0
        
        for row in rows:
            try:
                dt = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
                if dt.weekday() < 5:
                    weekday_count += 1
                else:
                    weekend_count += 1
            except Exception:
                pass
                
        return {
            "weekday": weekday_count,
            "weekend": weekend_count
        }

    def get_monthly_trends(self):
        """
        Returns monthly aggregate violation counts for the current year.
        """
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT strftime('%m', timestamp) as month_num, COUNT(*) FROM violations GROUP BY month_num")
        rows = cursor.fetchall()
        conn.close()
        
        monthly_data = {m: 0 for m in months}
        for row in rows:
            m_idx = int(row[0]) - 1
            if 0 <= m_idx < 12:
                monthly_data[months[m_idx]] = row[1]
                
        return {
            "labels": months,
            "counts": [monthly_data[m] for m in months]
        }

    def get_top_congested_areas(self):
        """
        Aggregate top congested areas from analytics logs.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT location, AVG(traffic_density) as avg_d FROM analytics GROUP BY location ORDER BY avg_d DESC LIMIT 5")
        rows = cursor.fetchall()
        conn.close()
        return [{"location": row[0].split(",")[0], "avg_density": round(row[1], 1)} for row in rows]

    def get_camera_heatmap(self):
        """
        Returns latest status for all 10 cameras.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT camera_id, location, traffic_density 
            FROM analytics a
            WHERE timestamp = (SELECT MAX(timestamp) FROM analytics WHERE camera_id = a.camera_id)
        """)
        rows = cursor.fetchall()
        conn.close()
        
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

    def get_live_alerts(self):
        """
        Retrieves the 10 most recent police patrol alerts.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT alert_id, location, severity, timestamp, status FROM alerts ORDER BY timestamp DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_sms_logs(self):
        """
        Retrieves the 10 most recent SMS notifications.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(notifications)")
        columns = {row[1] for row in cursor.fetchall()}
        selected_columns = ["notification_id", "type", "recipient", "status", "timestamp"]
        for optional_column in ["message", "plate_number", "challan_id"]:
            if optional_column in columns:
                selected_columns.append(optional_column)
        cursor.execute(f"SELECT {', '.join(selected_columns)} FROM notifications ORDER BY timestamp DESC LIMIT 10")
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_weekday_trends(self):
        """
        Returns violations count grouped by day of the week (Monday, Tuesday, Wednesday, Thursday, Friday).
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        # SQLite strftime('%w') returns 0=Sunday, 1=Monday, ..., 5=Friday, 6=Saturday
        cursor.execute("""
            SELECT strftime('%w', timestamp) as day_num, COUNT(*) 
            FROM violations 
            WHERE strftime('%w', timestamp) BETWEEN '1' AND '5'
            GROUP BY day_num
        """)
        rows = cursor.fetchall()
        conn.close()
        
        weekday_map = {"1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday"}
        result = {v: 0 for v in weekday_map.values()}
        for row in rows:
            day_name = weekday_map.get(row[0])
            if day_name:
                result[day_name] = row[1]
        return [{"day": k, "count": v} for k, v in result.items()]

    def get_weekend_trends(self):
        """
        Returns violations count grouped by day of the week (Saturday, Sunday).
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT strftime('%w', timestamp) as day_num, COUNT(*) 
            FROM violations 
            WHERE strftime('%w', timestamp) IN ('0', '6')
            GROUP BY day_num
        """)
        rows = cursor.fetchall()
        conn.close()
        
        weekend_map = {"6": "Saturday", "0": "Sunday"}
        result = {v: 0 for v in weekend_map.values()}
        for row in rows:
            day_name = weekend_map.get(row[0])
            if day_name:
                result[day_name] = row[1]
        return [{"day": k, "count": v} for k, v in result.items()]

    def get_location_wise_violations(self):
        """
        Returns violations count per camera location.
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT location, COUNT(*) as cnt FROM violations GROUP BY location ORDER BY cnt DESC")
        rows = cursor.fetchall()
        conn.close()
        return [{"location": row[0].split(",")[0], "count": row[1]} for row in rows]
