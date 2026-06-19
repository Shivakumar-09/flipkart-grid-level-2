# PostgreSQL Verification Report

Generated at: 2026-06-19 10:57:57

## Connection Health
- **Status**: CONNECTED
- **Host**: `dpg-d8pqqdrtqb8s738f980g-a.singapore-postgres.render.com`
- **Port**: `None`
- **Database**: `vehicles_dp0p`
- **Connection Latency**: `5370.51 ms`

## Record Counts
| Table Name | Record Count |
|---|---|
| `vehicles` | 653 |
| `violations` | 711 |
| `challans` | 711 |
| `ocr_results` | 711 |
| `repeat_offenders` | 8 |
| `police_alerts` | 12 |
| `traffic_analytics` | 1680 |
| `sms_logs` | 20 |
| `safety_video_views` | 35 |
| `camera_nodes` | 10 |
| `payments` | 0 |

## CRUD Operations Latency
| Operation | Target Table | Latency | Status |
|---|---|---|---|
| INSERT | `vehicles` | `593.19 ms` | SUCCESS |
| UPDATE | `vehicles` | `1524.74 ms` | SUCCESS |
| SEARCH | `vehicles` | `981.43 ms` | SUCCESS |

## Dashboard Queries Latency
| Query Type | Description | Latency |
|---|---|---|
| Hotspots Aggregation | Group violations by camera | `1073.30 ms` |
| Repeat Offenders List | Fetch top 5 repeat offenders | `302.44 ms` |
| Hourly Trends | Group violations by hour | `291.76 ms` |
| Daily Trends | Group violations by day (last 7 days) | `311.44 ms` |

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