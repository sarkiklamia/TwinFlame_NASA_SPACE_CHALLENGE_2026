# TwinFlame_NASA_SPACE_CHALLENGE_2026
Harmonization of MODIS and VIIRS Hot Spots

## Dashboard

See [guide.md](guide.md) for the complete Windows runbook covering raw sample
and archive data, cleaning, API ingestion, Phase 08/09, validation, and DuckDB
inspection.

The frontend is React + Vite and the API is read-only FastAPI. The ingestion
pipeline writes `UNIFIED_DETECTIONS` to `database/twinflame.duckdb`; Phase 08/09
write the `harm_*` tables to a separate run-specific DuckDB under
`data/processed/harmonization/phase_08/<run-id>/harmonization.duckdb`. The
backend currently has one `DUCKDB_PATH` setting, so it needs dual-database
reading (or an explicit combined read-only snapshot) before all live ingestion
and harmonization views can work together. The setup commands are in the guide;
start the dashboard after that database wiring is in place.

The Overview supports date range, satellite/platform, geographic region,
day/night, and fire radiative power filters. A missing database or an
incomplete pipeline schema is reported in the dashboard rather than replaced
with sample values.

The Live Monitoring page polls the read-only `/api/monitoring` endpoint every
60 seconds and supports rolling or custom acquisition-time windows, platform,
sensor, region, day/night, FRP, and available native-confidence/status filters.
It reads detections from `UNIFIED_DETECTIONS`; `SOURCE_FILES` and
`INGESTION_RUNS` provide the latest retrieval timestamp when they expose an
explicit retrieval-time column. Acquisition time is the satellite observation
time, while retrieval time is when TwinFlame collected the source data. If a
database does not include confidence, status, or retrieval metadata, those
fields are identified as unavailable rather than inferred.

The Geospatial Exploration page joins `UNIFIED_DETECTIONS` to
`harm_activity_clusters` and `harm_cluster_members` to show detections,
activity-cluster extents, member observations, and a 0.5-degree density grid.
Cluster extent and area are calculated from member coordinates as a bounding
envelope when the database has no stored cluster geometry. Saved areas and map
annotations are stored in browser local storage and remain available in that
browser for later research sessions.

The Alerts Center currently presents a clearly labeled illustrative sample,
not live alerts. Acknowledge and resolve actions are saved in that browser's
local storage; they are not written to the read-only DuckDB database or sent
through email/SMS. Sample map locations and historical counts are not real fire
notifications. MODIS/VIIRS correspondence alone is not an alert condition, and
satellite-observation alerts are not emergency warnings or predictions of
danger to people.
