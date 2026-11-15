# Lamia's Guide: Running & Verifying the TwinFlame Dashboard

Welcome to the **TwinFlame NASA Space Apps Challenge 2026** platform guide! This document provides everything you need to start the backend, launch the frontend, and systematically verify that all **10 dashboard pages** and their underlying APIs are functioning properly.

---

## 1. Prerequisites

Before running the dashboard, ensure you have:

- **Python 3.10+** installed
- **Node.js (v18+)** and **npm** installed
- The project cloned and opened in PowerShell or terminal

---

## 2. Quickstart in 4 Steps

### Step 1: Install Python Dependencies & Activate Environment
Open a PowerShell terminal in the repository root:

```powershell
# Create and activate virtual environment (optional if using system Python)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install backend dependencies
python -m pip install -r requirements.txt
```

### Step 2: Prepare the DuckDB Database
The FastAPI backend reads directly from DuckDB (configured via `DUCKDB_PATH` in `.env`, default: `database/twinflame.duckdb`).

- **For instant testing and full dashboard verification**, run our built-in seed generator:
  ```powershell
  python scripts/seed_demo_database.py
  ```
  *This populates `database/twinflame.duckdb` with realistic multi-sensor observations across Terra, Aqua, NOAA-20, and NOAA-21, activity clusters, correspondence edges, daily sensor metrics, and ingestion logs.*

- **If you already have production pipeline outputs**, simply set `DUCKDB_PATH` in your `.env` file:
  ```env
  DUCKDB_PATH=database/twinflame.duckdb
  ```

### Step 3: Start the Backend API (FastAPI)
In the first PowerShell terminal (repository root):

```powershell
python -m uvicorn app.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Verify the API is live:
- **Health Check**: Open <http://127.0.0.1:8000/api/health> (Expected: `{"status":"ok"}`)
- **Interactive Swagger Docs**: Open <http://127.0.0.1:8000/docs>

### Step 4: Start the Frontend (React + Vite)
Open a second PowerShell terminal:

```powershell
Set-Location .\app\frontend
npm install    # only needed the first time
npm run dev
```

Open your browser to the local Vite URL:
👉 **<http://127.0.0.1:5173>**

---

## 3. How to Verify Everything on the Dashboard

Once the dashboard opens, use the left sidebar to navigate and verify each of the **8 pages**:

---

### Page 01 · Overview (`/`)
- [ ] **Database Connection Pill**: The bottom-left status card shows a green pulsing indicator and says `CONNECTED` to the read-only database.
- [ ] **KPI Hero Cards**: Check that **Total detections**, **Activity clusters**, **Strong matches**, **Possible matches**, and **Unmatched / rejected** display valid numbers.
- [ ] **Global Fire Map**: An interactive Leaflet map renders fire hotspots color-coded by satellite (Terra in amber, Aqua in red-orange, NOAA-20 in copper, NOAA-21 in gold). Click any marker to view its acquisition time and FRP.
- [ ] **Daily Trend & Platform Breakdown**: The area chart displays daily detection volume, while the platform breakdown bar chart compares sensor contributions.
- [ ] **Correspondence Distribution**: A donut chart illustrates the ratio of Strong vs. Possible vs. Rejected candidate correspondences.
- [ ] **Pipeline Activity**: The bottom panel lists recent harmonization runs with run IDs, timestamps, and execution statuses.
- [ ] **Filter Controls**: Switch the date range presets (Today, 24h, 7 days, 30 days) and platform filters. Verify that all cards and charts update synchronously.

---

### Page 02 · Live Monitoring (`activePage === "monitoring"`)
- [ ] **Auto-Refresh Indicator**: Notice the 60-second polling pulse in the top right.
- [ ] **Acquisition vs. Retrieval Timestamps**: Verify that the top bar clearly distinguishes satellite observation time (UTC) from TwinFlame pipeline retrieval time.
- [ ] **Rolling Windows**: Toggle between `1h`, `6h`, `12h`, `24h`, `48h`, or `Custom UTC` windows.
- [ ] **Hotspot Table & Map**: Filter detections by native confidence (`high`, `nominal`, `low`) and adjust the minimum FRP slider.

---

### Page 03 · Geospatial Exploration (`activePage === "geospatial"`)
- [ ] **Activity Clusters & Envelopes**: Inspect multi-observation fire complexes rendered as bounding envelopes derived from member coordinates.
- [ ] **0.5° Density Grid**: Toggle the density grid overlay to see regional hotspot concentrations.
- [ ] **Cluster Inspection Pane**: Click on any cluster to view its member observations, dominant platform, total FRP, and geographic spread.
- [ ] **Spatial Annotations**: Use the polygon and marker drawing tools to annotate areas of interest. Refresh the page to confirm that your annotations persist in browser `localStorage`.

---

### Page 04 · Alerts Center (`activePage === "alerts"`)
- [ ] **Active Incident Feed**: Browse prioritized high-intensity fire incidents with confidence ratings and regional tags.
- [ ] **Acknowledge & Resolve Workflow**: Click **Acknowledge** or **Resolve** on an alert. Confirm that the status badge updates immediately and is remembered in browser storage.
- [ ] **Severity Filtering**: Filter alerts by severity levels (Critical, Warning, Informational).

---

### Page 05 · Fire Season Monitor (`activePage === "fire-season"`)
- [ ] **Multi-Year Comparisons**: Review annual fire activity curves comparing historical fire years.
- [ ] **Month-by-Month Activity Matrix**: Observe seasonal peaks (e.g., summer fire surges in North America/Europe vs. dry-season spikes in the Amazon and Australia).
- [ ] **Peak Month Identification**: Check the highlighted peak fire month badge and seasonal duration metrics.

---

### Page 06 · Historical Fire Analysis (`activePage === "historical"`)
- [ ] **Long-Term Detection Trends**: Explore multi-year time series from `UNIFIED_DETECTIONS`.
- [ ] **FRP Evolution**: Verify daily and monthly Fire Radiative Power trends from `harm_sensor_activity_daily`.
- [ ] **Cluster Size Evolution**: Inspect the stacked area visualization categorizing fires into small (&lt;5), medium (5–20), large (20–100), and mega-clusters (&gt;100 detections).
- [ ] **Continental Comparisons**: Toggle between Africa, Asia, Europe, North America, Oceania, and South America.
- [ ] **Data Export**: Click **Export** to download the currently filtered historical dataset in **CSV**, **GeoJSON** (ready for QGIS/ArcGIS), or **JSON**.

---

### Page 07 · Sensor Comparison (`activePage === "sensor-comparison"`)
- [ ] **Head-to-Head Platform Duel**: Select **Platform A** (e.g., *Terra*) and **Platform B** (e.g., *NOAA-20*). Confirm that selecting the same platform on both sides is automatically prevented.
- [ ] **Scientific Caution Notice**: A dedicated banner explains that raw detection count disparities reflect spatial resolution (375m VIIRS vs. 1000m MODIS) and overpass timing differences rather than sensor superiority.
- [ ] **FRP & 4µm Brightness Curves**: Compare Fire Radiative Power distributions and MWIR brightness temperatures between instruments.
- [ ] **Diurnal 24-Hour Cycle**: View the diurnal observation distribution curve showing morning (Terra) vs. afternoon (Aqua / NOAA) overpass peaks.
- [ ] **Coincident Matching**: Check the temporal offset (&Delta;t) and spatial centroid separation between coincident overpasses within your chosen threshold window.

---

### Page 08 · Harmonization Evaluation (`activePage === "harmonization"`)
- [ ] **Explainable AI Banner**: Review the methodology description explaining orbital coincidence, bounding box Intersection over Union (IoU), and scan-angle distortion safeguards.
- [ ] **6 Evaluation Hero Cards**:
  - Total candidate pairs evaluated
  - Strong correspondences &amp; strong rate (%)
  - Possible correspondences &amp; possible rate (%)
  - Rejected candidate pairs &amp; rejection rate (%)
  - Insufficient geometry count (&gt;55&deg; scan angle distortion)
  - Overall acceptance rate (%) with mean IoU (&mu;<sub>IoU</sub>) and mean separation distance (&mu;<sub>d</sub>)
- [ ] **7 Analytical Visualizations**:
  1. *Correspondence Decision Distribution* (donut chart + tabular counts)
  2. *Correspondence Trend Over Time* (stacked area chart with acceptance rate line)
  3. *Spatial Distance Distribution* (bar chart across &lt;0.5km to &ge;5km brackets)
  4. *Temporal Difference Distribution* (bar chart across 0–15m to &ge;120m brackets)
  5. *IoU Overlap Distribution* (bar chart highlighting the &ge;0.20 cutoff)
  6. *Platform Pair Quality Matrix* (stacked bars for Terra–NOAA-20, Aqua–NOAA-21, etc.)
  7. *Cluster Membership Composition* (multi-sensor MODIS + VIIRS synergy card)
- [ ] **Interactive Candidate Edge Inspector**:
  - Click any edge in the candidate list.
  - Inspect **Detection A** and **Detection B** side-by-side (satellite, instrument, coordinates, FRP, time UTC).
  - Review the **Explainable Decision Rationale Banner** detailing the automated classification reason.
  - View the **Geospatial Mini-Map** showing both detections connected by a color-coded correspondence polyline.
- [ ] **Export Correspondences**: Click **Export CSV** to download the evaluated correspondence table.

---

### Page 09 · Quality & Methodology (`activePage === "quality-methodology"`)
- [ ] **Dual Responsibility Tab Switcher**:
  - Click **A. Data Quality Audit** to inspect data integrity, missing values, coordinate anomalies, and ingestion logs.
  - Click **B. Scientific Methodology** to inspect product descriptions, mathematical equations, harmonization matching criteria, and algorithm changelogs.
- [ ] **Quality KPI Hero Cards**:
  - **Overall Completeness**: Displays the percentage of observations meeting all schema validity checks with a dynamic status pill (`EXCELLENT`, `NOMINAL`, `DEGRADED`, or `ACTION_REQUIRED`).
  - **Audited Detections**: Total count of active fire observations evaluated.
  - **Invalid Coordinates**: Count of records with out-of-bounds or null latitudes/longitudes.
  - **Invalid / Missing FRP**: Detections with null or non-positive Fire Radiative Power.
  - **Duplicate Detections**: Count of duplicate observations flagged by matching coordinates, timestamps, and platforms.
  - **Insufficient Geometry**: Observations flagged with excessive scan angles (>55°) where bounding box calculations are degraded.
- [ ] **Quality Defect Distribution Bar Chart**:
  - Horizontal bar chart breaking down anomalies across 6 vectors: Missing values, Invalid coordinates, Duplicate detections, Invalid FRP, Invalid timestamps, and Insufficient geometry.
- [ ] **Platform Completeness Progress Panels**:
  - Progress meters showing independent completeness scores for Terra, Aqua, NOAA-20, and NOAA-21.
- [ ] **SOURCE_FILES & PROCESSING_RUNS Ingestion Catalogs**:
  - Tabular view of raw NASA FIRMS files ingested, checksums, platforms, product versions, and ingestion run IDs.
  - Execution logs from `PROCESSING_RUNS` showing processing version, run timestamp, and pipeline status.
- [ ] **DATA_QUALITY_REPORTS Historical Preservation**:
  - Table of preserved quality reports across pipeline executions with completeness scores and quality status tags.
- [ ] **Methodology Documentation Visuals**:
  - Side-by-side **MODIS vs. VIIRS Instrument Specifications** (equator crossing, swath width, resolution, saturation temperatures).
  - **4-Stage Standardization Pipeline** diagram (Raw Ingestion, Attribute Normalization, Geometric Projection, Radiometric Unit Alignment).
  - **Mathematical Formulations** rendered in KaTeX for Intersection over Union ($\text{IoU}$), Centroid Separation ($d_c$), and Scan Expansion ($S(\theta)$).
  - **Correspondence Decision Matrix** table detailing classification logic for Strong, Possible, Rejected, and Insufficient Geometry.
  - **Spatio-Temporal DBSCAN Clustering** parameters ($\epsilon_{\text{space}} = 2.5\text{ km}$, $\epsilon_{\text{time}} = 6\text{ hours}$, $\text{MinPts} = 1$).
  - **Algorithm Version History** timeline from v1.0 through v2.5.
- [ ] **Specialized Quality Filters**:
  - Filter by Date Range, Satellite/Platform, Source File, Product Version, Processing Version, Quality Status, Quality Issue, or Processing Run ID.
- [ ] **Export Audit Report**: Click **Export Audit Report** to download the complete quality metrics and file audit catalog as CSV.

---

### Page 10 · Pipeline Management (`activePage === "pipeline-management"`)
- [ ] **Top Operations KPI Hero Cards**:
  - **Total Pipeline Runs**: Total operational executions across stages with overall success rate badge.
  - **Completed Runs**: Count of successful pipeline runs.
  - **Failed Runs**: Isolated failure count with error tracking.
  - **Avg Processing Duration**: Mean harmonization execution duration in seconds.
  - **Input Records Audited**: Total detections processed from unified streams.
  - **Clusters Generated**: Total activity clusters formed across runs.
- [ ] **Stage Reliability Progress Panels**:
  - 3 progress cards for **Ingestion Stage** (`INGESTION_RUNS`), **Standardization Stage** (`PROCESSING_RUNS`), and **Harmonization Stage** (`harm_run_metadata`), detailing total runs, successful, failed, and running jobs.
- [ ] **Execution Duration Trend Chart**:
  - Area chart displaying execution durations in seconds across pipeline runs.
- [ ] **Data Transformation Funnel Chart**:
  - Horizontal bar chart tracking record reduction from Raw Inputs &rarr; Coincident Candidates &rarr; Correspondence Edges &rarr; Harmonized Clusters.
- [ ] **Multi-Stage Telemetry Tabs**:
  - **Tab 1: Harmonization Runs (`harm_run_metadata`)**: Table listing run ID, algorithm version, configuration profile, duration, status, inputs, candidates, edges, clusters, and an **Inspect Details** button.
  - **Tab 2: Ingestion History (`INGESTION_RUNS`)**: Table listing ingestion batches, source types (FIRMS API, Historical Archive, Sample), duration, status, and linked source files.
  - **Tab 3: Source Files Overview (`SOURCE_FILES`)**: Table listing file ID, filename, platform, product version, retrieval timestamp, and SHA-256 checksums.
  - **Tab 4: Processing Executions (`PROCESSING_RUNS`)**: Table listing processing ID, input file ID, filename, platform, version, execution time, and status.
- [ ] **Selected Run Detail Modal**:
  - Click any row in the Harmonization Runs table or the **Inspect Details &rarr;** button.
  - Review detailed run metadata, error alert banner (if failed) showing failed stage and error traceback, telemetry funnel boxes, and timestamp audit.
- [ ] **Secure Job Execution Trigger**:
  - Click the green **Execute Pipeline Run** button in the header to open the execution dialog.
  - Choose stage (`Harmonization`, `Standardization`, `Ingestion`, or `Full Pipeline`).
  - Set custom observation date range, configuration profile (`cfg_spatiotemporal_iou_v25`, etc.), algorithm version, and toggle **Dry Run** mode.
  - Click **Launch Pipeline Execution**. Verify that the button switches to "Initiating Job..." and dispatches asynchronously via the FastAPI worker with DuckDB concurrency locking.
  - Confirm that the new run appears at the top of the Harmonization Runs table.
- [ ] **Specialized Operations Filters**:
  - Filter by Date Range, Ingestion Type, Stage, Status, Satellite / Platform, Source File, Processing Version, or Run ID search.
- [ ] **Export Run Log**: Click **Export CSV** to download the complete pipeline execution history.

---

## 4. Automated Verification & Testing

To run the complete automated test suite and ensure all backend endpoints and schemas comply with requirements:

```powershell
# From the repository root:
python -m pytest -q tests\test_dashboard_overview.py
```
*Expected output: `23 passed in ~9s`.*

To run the end-to-end endpoint verification script covering all 10 frontend routes and asynchronous job execution:

```powershell
python scripts\verify_all_endpoints.py
```
*Expected output: `ALL 10 DASHBOARD ENDPOINTS & JOB EXECUTION TESTED SUCCESSFULLY WITH HTTP 200 OK!`.*

To run the comprehensive parameter combination test (verifying case-insensitive platforms, date ranges, and specialized filters across all 10 pages):

```powershell
python scripts\test_parameter_combinations.py
```
*Expected output: `ALL 26 TEST CASES PASSED WITH HTTP 200!`.*

To verify the frontend TypeScript types and production build:

```powershell
# From app\frontend:
npm run build
```
*Expected output: `tsc -b && vite build` completes with zero errors (`built in ~11s`).*
# From app\frontend:
npm run build
```
*Expected output: `tsc -b && vite build` completes with zero errors (`built in ~8s`).*

---

## 5. Database Schema Specification Reference

The TwinFlame platform reads from the 11 standardized tables (plus the `DATA_QUALITY_REPORTS` preservation table):

| Table Name | Core Columns & Types | Description |
|---|---|---|
| `INGESTION_RUNS` | `ingestion_id` (BIGINT), `source_type` (VARCHAR), `start_time` (TIMESTAMP), `end_time` (TIMESTAMP), `status` (VARCHAR) | Ingestion pipeline batches |
| `SOURCE_FILES` | `file_id` (BIGINT), `filename` (VARCHAR), `platform` (VARCHAR), `product_version` (VARCHAR), `retrieval_time` (TIMESTAMP), `checksum` (VARCHAR), `ingestion_id` (BIGINT) | Raw NASA FIRMS source files |
| `PROCESSING_RUNS` | `processing_id` (BIGINT), `input_file_id` (BIGINT), `processing_version` (VARCHAR), `start_time` (TIMESTAMP), `status` (VARCHAR) | Standardization execution logs |
| `UNIFIED_DETECTIONS` | `detection_id` (VARCHAR), `id` (BIGINT), `source` (VARCHAR), `platform` (VARCHAR), `latitude` (FLOAT), `longitude` (FLOAT), `acq_date` (DATE), `acq_time` (VARCHAR), `confidence_native` (VARCHAR), `frp_mw` (FLOAT), `brightness` (FLOAT), `bright_t31` (FLOAT), `bright_ti4` (FLOAT), `bright_ti5` (FLOAT), `scan_km` (FLOAT), `track_km` (FLOAT), `daynight` (VARCHAR) | Standardized hotspot observations |
| `harm_correspondence_edges` | `correspondence_edge_id` (VARCHAR), `detection_id_a` (VARCHAR), `detection_id_b` (VARCHAR), `platform_a` (VARCHAR), `platform_b` (VARCHAR), `time_difference_minutes` (DOUBLE), `centre_distance_km` (DOUBLE), `intersection_area_km2` (DOUBLE), `iou` (DOUBLE), `containment_a` (DOUBLE), `containment_b` (DOUBLE), `normalized_centre_distance` (DOUBLE), `decision_class` (VARCHAR), `decision_reason` (VARCHAR), `geometry_quality` (VARCHAR), `run_id` (VARCHAR) | Pairwise candidate matches |
| `harm_activity_clusters` | `activity_cluster_id` (VARCHAR), `activity_date_utc` (DATE), `centroid_latitude` (DOUBLE), `centroid_longitude` (DOUBLE), `member_count` (INTEGER), `terra_count` (INTEGER), `aqua_count` (INTEGER), `noaa20_count` (INTEGER), `noaa21_count` (INTEGER), `sensor_count` (INTEGER), `start_time_utc` (TIMESTAMP), `end_time_utc` (TIMESTAMP), `cluster_extent_km` (DOUBLE), `cluster_area_km2` (DOUBLE), `cluster_method` (VARCHAR), `run_id` (VARCHAR) | Multi-observation fire complexes |
| `harm_cluster_members` | `activity_cluster_id` (VARCHAR), `detection_id` (VARCHAR), `platform` (VARCHAR), `membership_method` (VARCHAR), `membership_distance_km` (DOUBLE), `membership_quality` (VARCHAR), `run_id` (VARCHAR) | Cluster membership mapping |
| `harm_sensor_activity_daily`| `date_utc` (DATE), `platform` (VARCHAR), `detection_count` (INTEGER), `matching_eligible_count` (INTEGER), `frp_eligible_count` (INTEGER), `frp_sum_mw` (DOUBLE), `frp_mean_mw` (DOUBLE), `frp_median_mw` (DOUBLE), `brightness_band_1_mean_k` (DOUBLE), `brightness_band_1_median_k` (DOUBLE), `brightness_band_2_mean_k` (DOUBLE), `brightness_band_2_median_k` (DOUBLE), `run_id` (VARCHAR) | Aggregated daily sensor metrics |
| `harm_correspondence_summary`| `date_utc` (DATE), `platform_pair` (VARCHAR), `candidate_count` (INTEGER), `strong_count` (INTEGER), `possible_count` (INTEGER), `rejected_count` (INTEGER), `insufficient_geometry_count` (INTEGER), `mean_time_difference_minutes` (DOUBLE), `median_time_difference_minutes` (DOUBLE), `mean_iou` (DOUBLE), `run_id` (VARCHAR) | Daily correspondence summaries |
| `harm_frp_comparisons` | `support_id` (VARCHAR), `date_utc` (DATE), `spatial_scale_km` (DOUBLE), `temporal_window_minutes` (DOUBLE), `platform_a` (VARCHAR), `platform_b` (VARCHAR), `frp_a_mw` (DOUBLE), `frp_b_mw` (DOUBLE), `count_a` (INTEGER), `count_b` (INTEGER), `time_gap_minutes` (DOUBLE), `brightness_summary_a` (DOUBLE), `brightness_summary_b` (DOUBLE), `comparison_eligibility` (VARCHAR), `run_id` (VARCHAR) | Cross-platform FRP comparisons |
| `harm_run_metadata` | `run_id` (VARCHAR), `algorithm_version` (VARCHAR), `config_id` (VARCHAR), `started_at_utc` (TIMESTAMP), `finished_at_utc` (TIMESTAMP), `duration_seconds` (DOUBLE), `status` (VARCHAR), `input_count` (BIGINT), `candidate_count` (BIGINT), `correspondence_edge_count` (BIGINT), `activity_cluster_count` (BIGINT), `failed_stage` (VARCHAR), `error_summary` (VARCHAR) | Harmonization execution metadata |
| `DATA_QUALITY_REPORTS` | `report_id` (VARCHAR), `run_id` (VARCHAR), `generated_at` (TIMESTAMP), `total_records` (BIGINT), `valid_records` (BIGINT), `invalid_coordinates` (BIGINT), `missing_frp` (BIGINT), `invalid_frp` (BIGINT), `missing_timestamps` (BIGINT), `duplicate_detections` (BIGINT), `insufficient_geometry` (BIGINT), `completeness_pct` (DOUBLE), `quality_status` (VARCHAR), `summary_notes` (VARCHAR) | Ingestion validation audit log |

---

## 6. Troubleshooting & FAQs

### Q: The dashboard says "The dashboard database was not found"
**A:** Run `python scripts/seed_demo_database.py` from the root directory to generate `database/twinflame.duckdb`, or check that `DUCKDB_PATH` in `.env` points to your valid DuckDB file.

### Q: Frontend shows "Failed to fetch" or network error
**A:** Ensure your backend terminal is running at <http://127.0.0.1:8000>. Check that `CORS_ALLOWED_ORIGINS` in `.env` includes `http://localhost:5173` and `http://127.0.0.1:5173`.

### Q: The map has dark gray tiles or no background
**A:** The Leaflet map loads OpenStreetMap/CARTO dark basemap tiles, which require internet access. Hotspot markers, cluster polygons, and correspondence lines will still render accurately even if tile servers are offline.

### Q: `npm` or `python` is not recognized
**A:** Make sure Python 3.10+ and Node.js are added to your system `PATH`. Reopen PowerShell after installing.
