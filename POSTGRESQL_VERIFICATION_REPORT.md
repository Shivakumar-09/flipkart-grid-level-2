# PostgreSQL Verification Report

Generated at: 2026-06-20 14:58:40

## Connection Health
- **Status**: CONNECTED
- **Host**: `dpg-d8pqqdrtqb8s738f980g-a.singapore-postgres.render.com`
- **Port**: `None`
- **Database**: `vehicles_dp0p`
- **Connection Latency**: `4842.58 ms`

## Record Counts
| Table Name | Record Count |
|---|---|
| `vehicles` | 1 |
| `violations` | 3 |
| `challans` | 3 |
| `ocr_results` | 3 |
| `repeat_offenders` | 1 |
| `police_alerts` | 2 |
| `traffic_analytics` | 7 |
| `sms_logs` | 5 |
| `safety_video_views` | 0 |
| `camera_nodes` | 0 |
| `payments` | 0 |

## CRUD Operations Latency
| Operation | Target Table | Latency | Status |
|---|---|---|---|
| INSERT | `vehicles` | `534.16 ms` | SUCCESS |
| UPDATE | `vehicles` | `1310.54 ms` | SUCCESS |
| SEARCH | `vehicles` | `784.69 ms` | SUCCESS |

## Dashboard Queries Latency
| Query Type | Description | Latency |
|---|---|---|
| Hotspots Aggregation | Group violations by camera | `790.74 ms` |
| Repeat Offenders List | Fetch top 5 repeat offenders | `268.20 ms` |
| Hourly Trends | Group violations by hour | `263.48 ms` |
| Daily Trends | Group violations by day (last 7 days) | `264.94 ms` |

## Index Usage Verification
The database utilizes the following indices mapped in SQLAlchemy:
- **Table** `vehicles`: Index on column `plate_number` configured successfully.
- **Table** `violations`: Index on column `vehicle_id` configured successfully.
- **Table** `violations`: Index on column `violation_type` configured successfully.
- **Table** `violations`: Index on column `timestamp` configured successfully.
- **Table** `violations`: Index on column `location` configured successfully.
- **Table** `violations`: Index on column `camera_id` configured successfully.
- **Table** `challans`: Index on column `challan_id` configured successfully.
- **Table** `challans`: Index on column `status` configured successfully.
- **Table** `repeat_offenders`: Index on column `plate_number` configured successfully.
- **Table** `police_alerts`: Index on column `location` configured successfully.
- **Table** `traffic_analytics`: Index on column `location` configured successfully.
- **Table** `traffic_analytics`: Index on column `camera_id` configured successfully.
- **Table** `traffic_analytics`: Index on column `timestamp` configured successfully.
- **Table** `camera_nodes`: Index on column `camera_id` configured successfully.