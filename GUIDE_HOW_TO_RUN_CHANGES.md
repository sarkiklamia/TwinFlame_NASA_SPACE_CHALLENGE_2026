# TwinFlame / PyroSync — How to Run Your Friend's New Changes & Fix the Pipeline

This guide explains **why the errors occur**, **what you actually need to run** to see all of your friend's new features (the 10-page dashboard and backend APIs), and **how to resolve database schema collisions**.

---

## Quick Summary: Why Are These Two Different Errors Happening?

You have encountered two different errors when running `python scripts/run_pipeline.py`:

| Run | Error | Root Cause |
|---|---|---|
| **Run 1** | `RuntimeError: 10162 detections could not be linked...` | Line 33 of `sql/cleaning/01_clean_sources.sql` was edited to read Parquet instead of CSV, mislabeling API records as `ARCHIVE`. |
| **Run 2** | `Binder Error: Referenced column "source_type" not found in FROM clause!` | Running `seed_demo_database.py` created a mock `database/twinflame.duckdb` where `SOURCE_FILES` lacks the `source_type` column. The pipeline's `CREATE TABLE IF NOT EXISTS` did not recreate or alter it. |

---

## Section 1: How to Run the New Dashboard & APIs (Recommended)

Your friend implemented a full 10-page satellite visualization platform with FastAPI and React. If you just want to run and test everything right now:

### Step 1: Seed the DuckDB Database (Instant)
In your repository root terminal:
```powershell
python scripts/seed_demo_database.py
```
*Output: Creates `database/twinflame.duckdb` with all required tables (`UNIFIED_DETECTIONS`, `INGESTION_RUNS`, `SOURCE_FILES`, `PROCESSING_RUNS`, `harm_activity_clusters`, etc.).*

### Step 2: (Optional) Verify All 10 Backend Endpoints
```powershell
python scripts/verify_all_endpoints.py
```
*You will see `HTTP 200 OK` for all 10 endpoints.*

### Step 3: Start the FastAPI Backend
In your first PowerShell terminal:
```powershell
python -m uvicorn app.backend.main:app --reload --host 127.0.0.1 --port 8000
```
*Backend runs at: [http://127.0.0.1:8000](http://127.0.0.1:8000)*  
*Interactive Swagger docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)*

### Step 4: Start the Frontend Application
In a **second PowerShell terminal**:
```powershell
cd app/frontend
npm run dev
```
*Open your browser at: [http://localhost:5173](http://localhost:5173)*

You can now explore all 10 pages:
* **Page 01**: Overview (`/`)
* **Page 02**: Live Near-Real-Time (NRT) Monitoring
* **Page 03**: Fire Season & Climatology
* **Page 04**: Geospatial Exploration
* **Page 05**: Advanced Clusters & Complexes
* **Page 06**: Historical Analysis & Export
* **Page 07**: Sensor & Platform Comparison (MODIS vs. VIIRS)
* **Page 08**: Harmonization Evaluation & Matching
* **Page 09**: Data Quality Audit & Methodology
* **Page 10**: Pipeline Management & Asynchronous Job Execution

---

## Section 2: Investigation — Why `source_type not found in FROM clause` Happened

### The Exact Error
```
2026-11-15 08:13:36,430 | INFO     | Initializing database schema.
2026-11-15 08:13:37,289 | ERROR    | Pipeline failed.
Traceback (most recent call last):
  File "scripts\run_pipeline.py", line 1134, in run_pipeline
    file_ids = register_source_files(
  File "scripts\run_pipeline.py", line 387, in register_source_files
    existing = conn.execute(
_duckdb.BinderException: Binder Error: Referenced column "source_type" not found in FROM clause!
Candidate bindings: "product_version", "retrieval_time"

LINE 5:               AND source_type = ?
                          ^
```

### Detailed Investigation: What Triggered This?

There are two completely separate ways `database/twinflame.duckdb` is created in this project:

1. **The Demo Seeder (`scripts/seed_demo_database.py`)**:
   Creates a mock database for the UI. It defines `SOURCE_FILES` as:
   ```sql
   CREATE TABLE SOURCE_FILES (
       file_id BIGINT PRIMARY KEY,
       filename VARCHAR,
       platform VARCHAR,
       product_version VARCHAR,
       retrieval_time TIMESTAMP,
       checksum VARCHAR,
       ingestion_id BIGINT
   );
   ```
   Notice: **`source_type` is completely missing** in the demo seeder schema!

2. **The Production Pipeline Initialization (`sql/database/01_initialize_database.sql`)**:
   Defines the production schema as:
   ```sql
   CREATE TABLE IF NOT EXISTS SOURCE_FILES (
       file_id BIGINT PRIMARY KEY,
       filename VARCHAR NOT NULL,
       source_type VARCHAR NOT NULL CHECK (source_type IN ('API', 'ARCHIVE')),
       platform VARCHAR,
       product_version VARCHAR,
       retrieval_time TIMESTAMP,
       checksum VARCHAR,
       ingestion_id BIGINT,
       FOREIGN KEY (ingestion_id) REFERENCES INGESTION_RUNS(ingestion_id)
   );
   ```

### The Collision Mechanism
1. When you ran `python scripts/seed_demo_database.py`, it created `database/twinflame.duckdb` with the **demo schema** (without `source_type`).
2. When you next ran `python scripts/run_pipeline.py`, line 1124 ran `01_initialize_database.sql`.
3. Because the SQL says **`CREATE TABLE IF NOT EXISTS SOURCE_FILES`**, DuckDB detected that table `SOURCE_FILES` already existed from the seed step, and skipped creating it!
4. At line 1134, `run_pipeline.py` called `register_source_files()`, executing:
   ```sql
   SELECT file_id, checksum
   FROM SOURCE_FILES
   WHERE lower(filename) = lower(?)
     AND source_type = ?;
   ```
5. DuckDB inspected the existing table, found no `source_type` column (only `product_version`, `retrieval_time`), and raised `Binder Error: Referenced column "source_type" not found in FROM clause!`.

---

### How to Fix Both Errors to Run `scripts/run_pipeline.py` Successfully

To run the production data pipeline cleanly from scratch:

#### Step 1: Remove the Existing Demo Database
Because the pipeline creates and validates its own full schema, delete the demo database file:
```powershell
Remove-Item database\twinflame.duckdb
```
*(When `database/twinflame.duckdb` is absent, the pipeline initializes a fresh database directly with `source_type` present).*

#### Step 2: Ensure `sql/cleaning/01_clean_sources.sql` is Restored
If `01_clean_sources.sql` still has line 33 pointing to `.parquet` instead of `.csv`, revert it:
```powershell
git restore sql/cleaning/01_clean_sources.sql
```
*(This prevents the second error: `10162 detections could not be linked`).*

#### Step 3: Run the Pipeline
```powershell
python scripts/run_pipeline.py --check-only   # Verify preflight passes
python scripts/run_pipeline.py                # Run pipeline
```

---

## Section 3: Live NASA FIRMS API Ingestion (Optional)

If your friend added the live ingestion scripts and you want to fetch the latest worldwide satellite fires from NASA FIRMS:

1. Ensure your `.env` contains your NASA FIRMS map key:
   ```env
   FIRMS_MAP_KEY=your_firms_map_key_here
   ```
2. Run the continuous ingestion worker:
   ```powershell
   python scripts/run_api_ingestion.py
   ```
   *This automatically pulls active fires from MODIS, NOAA-20, and NOAA-21 and saves them into `data/raw/api/` as Parquet files.*

---

## Summary of Commands Cheatsheet

| Goal | Exact Commands to Run |
|---|---|
| **Run Dashboard (Frontend + Backend)** | `python scripts/seed_demo_database.py`<br>`python -m uvicorn app.backend.main:app --reload`<br>`cd app/frontend; npm run dev` |
| **Fix and Run Data Pipeline** | `Remove-Item database\twinflame.duckdb`<br>`git restore sql/cleaning/01_clean_sources.sql`<br>`python scripts/run_pipeline.py` |
| **Verify Backend Endpoints** | `python scripts/verify_all_endpoints.py` |
| **Run Automated Backend Tests** | `python -m pytest -q tests/test_dashboard_overview.py` |
