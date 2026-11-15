# TwinFlame_NASA_SPACE_CHALLENGE_2026
Harmonization of MODIS and VIIRS Hot Spots

## Dashboard

The Overview dashboard is a React + Vite frontend backed by a read-only FastAPI
API. It summarizes unified detections, harmonized activity clusters,
correspondences, and processing runs from the configured DuckDB database.

1. Install the Python dependencies with `pip install -r requirements.txt`.
2. Set `DUCKDB_PATH` to the harmonized DuckDB database in `.env`.
3. Start the API from the repository root with
   `uvicorn app.backend.main:app --reload`.
4. With Node.js and npm installed, in `app/frontend` run `npm install` once
   and `npm run dev`.
5. Open the Vite URL shown in the terminal (by default
   `http://127.0.0.1:5173`).

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

The Fire Season Monitor reads acquisition dates and FRP metrics from
`UNIFIED_DETECTIONS`, and adds activity-cluster counts when
`harm_activity_clusters` and `harm_cluster_members` are available. It supports
year-over-year comparisons, month-by-year activity, sensor/platform and
day/night filters, sensor-specific monthly comparisons, and researcher-defined
month or season windows. Regional
comparisons use the dashboard's approximate bounding boxes, not precise
administrative or ecological boundaries; the dashboard does not impose a
universal fire-season calendar.

The Historical Fire Analysis page (`/api/historical-analysis` and `/api/historical-analysis/export`)
provides multi-year exploratory analysis of long-term fire regime changes:
- Long-term detection trend across platforms and sensors from `UNIFIED_DETECTIONS`.
- Fire Radiative Power (FRP) evolution from `harm_sensor_activity_daily` (with automatic aggregation fallback to `UNIFIED_DETECTIONS`).
- Historical cluster counts and cluster size evolution (small, medium, large, mega-clusters) from `harm_activity_clusters` and `harm_cluster_members`.
- Historical spatial distribution map supporting individual detections, 2-degree spatial density grid cells, and activity clusters.
- Continental historical comparisons across Africa, Asia, Europe, North America, Oceania, and South America.
- Downloadable datasets with direct export to CSV, GeoJSON (for GIS workflows in QGIS and ArcGIS), and JSON.

The Sensor Comparison page (`/api/sensor-comparison`) provides head-to-head empirical evaluation across satellite platforms:
- Supported platforms: Terra (MODIS), Aqua (MODIS), NOAA-20 (VIIRS), and NOAA-21 (VIIRS).
- Enforces selection of two distinct platforms (A and B) with automatic conflict prevention.
- Prominently surfaces the scientific caution on detection count disparities vs. spatial resolution (375m VIIRS vs 1000m MODIS), overpass timing, and sensitivity thresholds.
- Comparative visualizations: detection counts and relative share, FRP bracket distribution curves, synchronized daily trends, mean/median/peak FRP indicators, 4µm MWIR brightness temperature distributions, and 24-hour diurnal observation curves.
- Coincident hotspot matching evaluating observation time offsets (Δt) and inter-centroid spatial proximity within researcher-configured temporal and spatial windows.
- Database sources: `UNIFIED_DETECTIONS`, `harm_sensor_activity_daily`, and `harm_frp_comparisons`.

The Harmonization Evaluation page (`/api/harmonization-evaluation`) evaluates the matching algorithm establishing correspondences between MODIS and VIIRS observations:
- Answers the core methodology question: *How well does our harmonization methodology establish correspondences between MODIS and VIIRS observations?*
- Summary KPIs: Total candidate pairs, Strong matches & rate, Possible matches & rate, Rejected candidates & rate, Insufficient geometry cases, Acceptance rate, Mean/Median spatial distance (km), Mean/Median time difference (minutes), Mean Intersection over Union (IoU), and Mean containment ratio.
- Visualizations:
  1. Decision distribution donut chart and breakdown table (Strong, Possible, Rejected, Insufficient Geometry) from `harm_correspondence_summary`.
  2. Multi-series correspondence trend over time with superimposed Harmonization Acceptance Rate (%) curve.
  3. Spatial distance distribution across distance brackets (<0.5km, 0.5-1km, 1-2km, 2-3km, 3-5km, ≥5km).
  4. Temporal difference distribution across overpass coincidence brackets (0-15m, 15-30m, 30-60m, 60-120m, ≥120m).
  5. Intersection over Union (IoU) distribution highlighting the critical ≥0.20 threshold.
  6. Correspondence quality by platform pair stacked bars (Terra–NOAA-20, Aqua–NOAA-20, etc.) from `harm_correspondence_edges`.
  7. Cluster membership composition analyzing cross-sensor synergy (MODIS + VIIRS) from `harm_activity_clusters` and `harm_cluster_members`.
- Interactive Candidate Edge Inspector:
  - Explores individual candidate correspondence edges with explainable AI rationale.
  - Side-by-side detection inspection for Detection A and Detection B (satellite platform, sensor, acquisition timestamp, coordinates, FRP, confidence, day/night).
  - Spatial and temporal alignment metrics: Euclidean separation distance (km), overpass time offset Δt (minutes), bounding box IoU, and centroid containment.
  - Interactive Leaflet mini-map displaying paired detections as color-coded satellite markers connected by a dashed correspondence polyline.
  - Direct CSV and JSON export for offline correspondence verification.
- Specialized algorithm filters: Date range with presets, Platform pair selector, Decision class, Geometry quality, Time difference min/max, Centre distance min/max, IoU range min/max, Containment range min/max, Harmonization run ID, and Algorithm version.

The Quality & Methodology page (`/api/quality-methodology`) provides comprehensive data quality auditing and full scientific methodology documentation:
- **Part A: Data Quality & Ingestion Audit**:
  - Top KPI hero cards: Overall Completeness Rating (%), Audited Detections, Invalid/Missing Coordinates, Invalid/Missing FRP, Duplicate Records, and Insufficient Geometry flags.
  - Quality Defect Distribution: Horizontal bar visualization auditing 6 core anomaly vectors (missing values, invalid coordinates, duplicate detections, invalid FRP, invalid timestamps, insufficient geometry).
  - Platform-Specific Completeness: Progress meters tracking ingestion integrity across Terra, Aqua, NOAA-20, and NOAA-21.
  - Ingestion Catalogs: Audited records from `SOURCE_FILES` (with file IDs, hashes, retrieval times) and `PROCESSING_RUNS` (processing IDs, software versions, start times, execution statuses).
  - Historical Validation Snapshots: Preserved audit reports from `DATA_QUALITY_REPORTS` (report ID, run ID, total records, defect counts, completeness score, and summary logs).
  - Audit Export: Downloadable comprehensive CSV quality audit report.
- **Part B: Scientific Methodology**:
  - Sensor & Product Specifications: Deep dive comparison between MODIS (Terra/Aqua, 1km, 3.96µm/11.03µm, 2330km swath) and VIIRS (NOAA-20/21, 375m, 3.74µm/11.45µm, 3040km swath).
  - Standardization Pipeline: 4-stage ingestion and transformation architecture (Raw Ingestion & Verification, Attribute & Schema Normalization, Spatial & Geometric Transformation, Radiometric Unit Alignment).
  - Mathematical Equations: Geometric definitions rendered in KaTeX for Intersection over Union ($\text{IoU} = \frac{|A \cap B|}{|A \cup B|}$), Great-circle / Euclidean centroid distance ($d_c$), and Off-nadir scan expansion ($S(\theta)$).
  - Correspondence Decision Matrix: Strict rule specifications for Strong ($\text{IoU} \ge 0.20$), Possible ($\le 3.0\text{ km}$ proximity), Rejected ($>3.0\text{ km}$ or $>120\text{ min}$), and Insufficient Geometry ($>55^\circ$ scan angle deformation).
  - Clustering Algorithm: Multi-sensor spatio-temporal DBSCAN specification ($\epsilon_{\text{space}} = 2.5\text{ km}$, $\epsilon_{\text{time}} = 6\text{ hours}$, $\text{MinPts} = 1$).
  - Assumptions & Sensor Limitations: Transparent accounting of parallax distortions, cloud/smoke obscuration, and fire temporal dynamics.
  - Version History: Evolution changelog from v1.0 baseline through v2.5 harmonized polygon IoU.
- Specialized Quality Filters: Date range, Satellite/Platform, Source file, Product version, Processing version, Quality status (EXCELLENT, NOMINAL, DEGRADED, ACTION_REQUIRED), Quality issue, and Processing run ID.
- Database sources: `UNIFIED_DETECTIONS`, `SOURCE_FILES`, `PROCESSING_RUNS`, `harm_correspondence_edges`, `harm_run_metadata`, and `DATA_QUALITY_REPORTS`.

The Pipeline Management page (`/api/pipeline-management`, `/api/pipeline/run`, and `/api/pipeline/runs/{run_id}`) provides complete technical operations and execution telemetry for platform administrators and researchers:
- Answers the core technical question: *Is the data pipeline working correctly, and what happened during each execution?*
- Top KPI Hero Cards: Total Pipeline Runs, Completed Executions, Failed Executions, Average Processing Duration (seconds), Input Records Audited, and Harmonized Clusters Generated.
- Stage Reliability Cards: Progress meters and execution metrics broken down across Ingestion, Standardization, and Harmonization stages.
- Visualizations:
  1. *Execution Duration Trend*: Multi-series area chart tracking runtime duration across historical executions from `harm_run_metadata`.
  2. *Data Transformation Funnel*: Multi-tier bar chart tracking the reduction ratio from Raw Input Detections $\rightarrow$ Coincident Candidates $\rightarrow$ Correspondence Edges $\rightarrow$ Activity Clusters.
  3. *Stage Success/Failure Rates*: Health rates across pipeline stages.
- Multi-Stage Telemetry Tabs:
  1. *Harmonization Runs (`harm_run_metadata`)*: Run ID, algorithm version, configuration profile, duration, status, inputs, candidates, edges, clusters, and detailed inspection modal with failed stage and error summaries.
  2. *Ingestion History (`INGESTION_RUNS`)*: Ingestion ID, source type (FIRMS API, Historical Archive, Sample), timestamps, durations, statuses, and linked source files count.
  3. *Source Files Overview (`SOURCE_FILES`)*: File ID, filename, platform, product version, retrieval timestamp, and SHA-256 checksums.
  4. *Processing Executions (`PROCESSING_RUNS`)*: Processing ID, input file ID, filename, platform, software version, start time, and status.
- Secure Job Execution Engine:
  - Interactive modal dialog to dispatch new harmonization runs with custom observation date ranges, configuration profiles (`cfg_spatiotemporal_iou_v25`, `cfg_strict_spatial_threshold`, `cfg_rapid_revisit_noaa`), algorithm versions, and a dry-run simulation toggle.
  - Safeguarded by server-side mutex lock (`PIPELINE_MUTEX`), input validation, and asynchronous FastAPI `BackgroundTasks`.
  - Real-time job polling via `/api/pipeline/runs/{run_id}`.
- Specialized Operations Filters: Date range with presets, Ingestion type, Pipeline stage, Execution status, Satellite/Platform, Source file, Processing version, and Run ID search.
- Database sources: `INGESTION_RUNS`, `SOURCE_FILES`, `PROCESSING_RUNS`, and `harm_run_metadata`.
