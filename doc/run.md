# TwinFlame / PyroSync: demonstration runbook

This runbook explains how to demonstrate the dashboard using the database in
this checkout, and how to run the data pipeline from raw inputs through
harmonization and optional live updates.

## Before the demonstration: know what is available

The checked-in application code does not include the local DuckDB database or
the original raw archive. In the current working copy, the database is about
500 MB and contains about 4.8 million standardized detections. There are raw
API files, but no raw sample or archive files, and there are no validated
Phase 08 harmonization outputs yet. Therefore:

- You can demonstrate source-detection analysis now if the local database file
  is present.
- You cannot reproduce the full 4.8-million-record database from the currently
  present raw files alone. Obtain the original approved archive inputs first.
- Do not run the full rebuild against the only copy of
  `database/twinflame.duckdb`. `scripts/run_pipeline.py` rebuilds the unified
  detections from discovered raw inputs, so its output will reflect only the
  inputs available in that run.
- No harmonization matches, clusters, evaluation scores, or alerts are
  fabricated. The dashboard should report those capabilities unavailable until
  valid outputs and an alerting pipeline actually exist.

Run all commands below from the repository root in Windows PowerShell unless a
step says otherwise.

## A. Fast dashboard demonstration with the current database

### 1. Check the local inputs

```powershell
Test-Path .\database\twinflame.duckdb
Get-Item .\database\twinflame.duckdb | Select-Object FullName,Length
Get-ChildItem .\data\raw\api -Recurse -File | Measure-Object
Get-ChildItem .\data\raw\sample,.\data\raw\archive -Recurse -File -ErrorAction SilentlyContinue | Measure-Object
```

The first command must return `True`. If the database is missing, obtain the
authorized database file from your project data owner and place it at
`database/twinflame.duckdb`. Do not replace it with the demo seeder or an empty
database and then present the result as real observations.

### 2. Configure and start Docker Compose

Docker Desktop must be running. Create `.env` only if it does not already
exist; preserve any existing settings and credentials.

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose config --quiet
docker compose up --build -d
docker compose ps
```

Open `http://127.0.0.1:8080`. Compose serves the frontend through Nginx and
routes its `/api/` requests to FastAPI. It also publishes the backend health
endpoint on port 8000 for local development. If either port is already in use,
set `FRONTEND_PORT` or `BACKEND_PORT` in `.env` and rerun `docker compose up -d`.

### 3. Confirm that the app and database are connected

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/api/health
Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8080/api/overview?period=7d'
```

The health response should report `database: ok`, detections available, and
harmonization unavailable if no valid Phase 08 output exists. The overview
should return a nonzero detection total. In the current data snapshot, the
independently checked seven-day total is 112,599; expect it to change as the
data changes or filters change.

### 4. Walk through the dashboard

1. **Overview:** show source-detection totals, date/platform/region/day-night
   filters, the filtered detection map, and UTC acquisition times. Harmonization
   KPIs should be unavailable (`—`), not zero, while those outputs are missing.
2. **Near Real-Time Monitoring and Geospatial Exploration:** show the filtered
   observation views and explain that the detections are satellite observations,
   not confirmed fire incidents.
3. **Historical Fire Analysis, Sensor Comparison, Fire Season, and Quality &
   Methodology:** demonstrate database-derived detection trends and data-quality
   metrics. Explain each page's source and method when presenting its numbers.
4. **Harmonization Evaluation:** show the explicit unavailable message until
   valid Phase 08 output tables exist. Do not quote match rates or claim
   harmonization success without that evidence.
5. **Alerts Center:** show that alert records, alert map, and alert actions are
   unavailable. TwinFlame does not currently provide live wildfire warnings.
6. **Pipeline Management:** review the recorded ingestion and standardization
   runs. A completed ingestion or processing record is not proof that Phase 08
   harmonization completed.

To inspect service logs while presenting, open another PowerShell window:

```powershell
docker compose logs -f backend frontend
```

## B. Full data pipeline demonstration

Run this section only in a **separate working copy** with the complete approved
raw archive and a backup of the source database. The pipeline is a data-writing
workflow; the dashboard's Docker database mount is read-only, but that does not
make the host-side pipeline scripts read-only.

### 1. Prepare Python and the data inputs

Install a supported Python version, then from the separate working copy:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, allow it for this terminal and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Place approved source CSVs under `data/raw/sample/` and
`data/raw/archive/`. The pipeline recursively discovers CSVs there. API
response Parquet belongs under `data/raw/api/`. Keep raw input files unchanged;
do not place reports, review labels, or unrelated files in the input folders.
If live NASA FIRMS ingestion is part of the demo, put your own key in the
private `.env` as `FIRMS_MAP_KEY=...`; never commit or display the key.

Before continuing, check the inputs and available disk space. If the full
historical archive is unavailable, stop here rather than rebuilding the main
database from only the current API files.

### 2. Run the ingestion, cleaning, and standardization pipeline

Stop any API ingestion process and close DuckDB CLI sessions first. Run the
preflight:

```powershell
python scripts/run_pipeline.py --check-only
```

Confirm the discovered input count and file types are the intended complete
dataset. A successful preflight checks for files and SQL stages; it does not
prove the input data is complete or scientifically valid.

Then run the rebuild in the separate working copy:

```powershell
python scripts/run_pipeline.py
```

The script cleans and validates discovered CSV/Parquet data, standardizes
platforms and UTC acquisition timestamps, generates deterministic detection
IDs, records input/processing metadata, and rebuilds
`UNIFIED_DETECTIONS`. Wait for `PYROSYNC PIPELINE COMPLETED SUCCESSFULLY` and
record the reported row count and output paths. If it fails, preserve the error
and `logs/pipeline.log`; do not proceed to Phase 08 with a failed rebuild.

### 3. Verify the rebuilt detection database

If the DuckDB CLI is installed, run read-only checks:

```powershell
duckdb -readonly .\database\twinflame.duckdb
```

Then at the DuckDB prompt:

```sql
SHOW TABLES;
DESCRIBE UNIFIED_DETECTIONS;
SELECT COUNT(*) AS detections,
       COUNT(DISTINCT detection_id) AS unique_ids,
       MIN(acquisition_time_utc) AS first_time_utc,
       MAX(acquisition_time_utc) AS last_time_utc
FROM UNIFIED_DETECTIONS;
SELECT platform, COUNT(*) AS detections
FROM UNIFIED_DETECTIONS
GROUP BY platform
ORDER BY platform;
.quit
```

Check that row count equals unique ID count, and compare dates/platform totals
to the input coverage and pipeline report. Review cleaning and quarantine
reports; quarantined records are not silently treated as valid detections.

### 4. Audit source coverage before historical harmonization

```powershell
python scripts/run_phase_08_historical.py --audit-only
```

Review available dates, supported/unsupported platform counts, and coverage
gaps. Phase 08 processes dates present in the database; it does not fill missing
historical months. The configured method uses a 240-minute temporal window,
1-km spatial threshold, and supported cross-platform pairs. Treat these as the
implemented method, not proof that a match is a confirmed wildfire event.

For a short rehearsal, you may run one available UTC date by adding
`--start-date YYYY-MM-DD --end-date YYYY-MM-DD`. Clearly label this as a subset
run; it is not full historical coverage.

### 5. Run Phase 08 and inspect its outputs

Stop API ingestion and close DuckDB sessions using either database. Then run:

```powershell
python scripts/run_phase_08_historical.py
```

Save the printed `run_id`. The outputs go under
`data/processed/harmonization/phase_08/<run-id>/`, including the manifest,
partitioned Parquet, and a separate `harmonization.duckdb`. Open the manifest
and confirm its final status, failed-date count, and coverage gaps. A completed
process with failed partitions or coverage gaps is not full successful
coverage. Resume an interrupted run using its exact run ID:

```powershell
python scripts/run_phase_08_historical.py --run-id YOUR_RUN_ID
python scripts/run_phase_08_historical.py --run-id YOUR_RUN_ID --retry-failed
```

Only present harmonization metrics when the output manifest and required
harmonization tables have been validated.

### 6. Optional scientific validation with independent references

Phase 05 reference metrics require independently reviewed labels in
`data/validation/candidate_recall_reference_pairs.csv` and/or
`data/validation/activity_reference_labels.csv`. Add real review outcomes with
reviewer, UTC timestamp, and evidence reference. Do not make labels from the
algorithm's own candidate list and call them ground truth. Without valid
reference data, report validation as skipped/unavailable; do not infer accuracy
from the number of generated candidates.

An optional review queue can be generated from a Phase 08 manifest:

```powershell
python scripts/create_phase05_review_queue.py --manifest .\data\processed\harmonization\phase_08\YOUR_RUN_ID\phase08_manifest.json
```

That queue contains candidates for human review; it is not ground truth by
itself and cannot measure missed candidate pairs.

### 7. Optional NASA FIRMS ingestion and Phase 09 updates

Only after a successful Phase 08 baseline exists and a valid private
`FIRMS_MAP_KEY` is configured, start the continuous ingestion process:

```powershell
python scripts/run_api_ingestion.py
```

Keep the terminal open to show request/import summaries and Phase 09 status.
The process polls according to `config/sources.yaml`, stores API responses as
raw Parquet, imports/deduplicates them into `UNIFIED_DETECTIONS`, then attempts
incremental harmonization. `no_data` means no new eligible observations;
`not_ready` means no suitable successful Phase 08 baseline; neither is a
successful new harmonization batch. Press `Ctrl+C` to stop gracefully.

If API files have already been downloaded and you want a one-off catch-up
instead:

```powershell
python scripts/process_pending_api_files.py
python scripts/run_phase_09_incremental.py --phase08-run-id YOUR_RUN_ID
```

Inspect the Phase 09 status/manifest and confirm the affected dates were
successfully updated. Do not run Phase 09 concurrently with Phase 08 or while
the dashboard is reading the same output database if DuckDB reports a lock.

### 8. Start or refresh the dashboard against the results

The current Compose setup mounts the detection database and Phase 08 output
directory read-only into the backend. Make sure `.env` points
`DUCKDB_HOST_PATH` at the rebuilt detection database and
`HARMONIZATION_PHASE08_HOST_PATH` at the directory containing the validated
Phase 08 run folders. Then:

```powershell
docker compose config --quiet
docker compose up -d --build
docker compose ps
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8080/api/health
```

Open `http://127.0.0.1:8080` and refresh the page. Verify that the health
response and UI distinguish detections from harmonization outputs. If the
Phase 08 run is valid, evaluation metrics should come from its real tables; if
not, the dashboard must continue to show an unavailable state. Alerts remain
unavailable until a real alert source and generation workflow are separately
implemented and validated.

## Stop the demonstration

Stop continuous ingestion with `Ctrl+C`. Stop the dashboard containers while
retaining the host data with:

```powershell
docker compose down
```

Do not use `docker compose down -v` as a routine cleanup command. Keep the
database, raw inputs, Phase 08 run directory, manifests, and logs needed for
review.
