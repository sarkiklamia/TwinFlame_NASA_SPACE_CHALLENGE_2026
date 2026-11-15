# TwinFlame handoff: ingestion, cleaning, harmonization, and validation

This is the Windows PowerShell runbook for rebuilding the data products from
the beginning and keeping them current. Run commands from the repository root.

## 1. Know which database each pipeline writes

| Step | Reads | Writes |
|---|---|---|
| Archive/sample + API cleaning and standardization | CSVs in `data/raw/sample` and `data/raw/archive`; API Parquet in `data/raw/api` | `database/twinflame.duckdb`, canonical cleaned Parquet, quarantine Parquet, cleaning report |
| Phase 08 historical harmonization | `UNIFIED_DETECTIONS` in `database/twinflame.duckdb` (read-only) | `data/processed/harmonization/phase_08/<run-id>/harmonization.duckdb` and partitioned Parquet |
| API ingestion + incremental import | NASA FIRMS; saved raw API Parquet | Raw API Parquet and appended/deduplicated `UNIFIED_DETECTIONS` in `database/twinflame.duckdb` |
| Phase 09 incremental harmonization | New API detections in `UNIFIED_DETECTIONS` and the Phase 08 baseline | Updated affected dates in that Phase 08 run's `harmonization.duckdb`, plus Phase 09 manifests/partitions |

The raw archives, databases, generated Parquet/CSV products, and completed
validation labels stay local and are excluded from Git. The repository includes
only the validation instructions and empty label templates. The teammate needs
the raw archive files and a FIRMS API key supplied separately; cloning this
repository alone cannot recreate the historical archive. Live FIRMS ingestion
supplies recent data, not missing historical months.

**Dashboard handoff:** the current FastAPI setting `DUCKDB_PATH` points to one
database. The ingestion database contains `UNIFIED_DETECTIONS`; the separate
Phase 08 database contains the `harm_*` outputs. The dashboard backend must be
updated to read both databases (or a deliberate combined read-only snapshot)
before all dashboard pages can query live ingestion and harmonization together.
Do not point the current single path at the Phase 08 database and expect it to
also contain `UNIFIED_DETECTIONS`.

## 2. One-time setup on the dashboard teammate's computer

Open PowerShell in the cloned project directory. The commands below assume
the current directory is the repository root:

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks virtual-environment activation, run this for the current
terminal only and activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Create the private environment file and add the teammate's own FIRMS key:

```powershell
Copy-Item .env.example .env
notepad .env
```

Set `FIRMS_MAP_KEY=...` in `.env`. Never commit or share `.env`.

Copy the approved source C2/sample and archive CSV files into:

```text
data/raw/sample/
data/raw/archive/
```

The project discovers every CSV under those folders recursively. A CSV placed
there is treated as input data, so do not place reports, review sheets, or
unrelated CSVs there. Preserve the raw files unchanged after ingestion; source
checksums are tracked in DuckDB. API response Parquet belongs under
`data/raw/api/` and is created by the API fetcher. Neither archive files nor
generated outputs are included in Git.

## 3. Build the cleaned and unified detection database

First stop any already-running API fetcher and close DuckDB CLI windows using
`database/twinflame.duckdb`. The full pipeline rebuilds `UNIFIED_DETECTIONS`
from all discovered raw files; it is not the hourly ingestion command.

Check that input files and SQL stages are present:

```powershell
python scripts/run_pipeline.py --check-only
```

Expected: discovered file count, archive/API counts, and `Preflight passed`.
Check that the counts match the data the teammate intended to process.

Run the full ingestion cleaning/standardization pipeline:

```powershell
python scripts/run_pipeline.py
```

The SQL stages applied by the runner are:

1. `sql/cleaning/01_clean_sources.sql` reads the CSV/Parquet inputs, removes
   duplicate copies within each source, quarantines records that fail the
   required validity checks, and flags measurements needing review.
2. `sql/standardization/01_standardize_cleaned.sql` standardizes platform and
   sensor names, parses UTC acquisition time, classifies native confidence,
   and preserves sensor-specific brightness fields.
3. `sql/preprocessing/01_generate_detection_ids.sql` creates deterministic
   detection IDs from canonical attributes.
4. `scripts/run_pipeline.py` registers source-file checksums and run metadata,
   attaches `file_id`/`processing_id`, validates the result, then rebuilds
   `UNIFIED_DETECTIONS` from the final cleaned Parquet.

Expected success marker: `PYROSYNC PIPELINE COMPLETED SUCCESSFULLY`, with a
canonical Parquet path, DuckDB path, and total row count. The runner validates
nonempty output, matching Parquet/database row counts, required columns,
metadata references, and unique detection IDs. If it fails, keep the terminal
error and log at `logs/pipeline.log`; do not start harmonization from a failed
run.

The pipeline uses a default DuckDB memory limit of 4 GB and two threads. It can
spill temporary work to `database/tmp_spill`. If memory is constrained, close
other heavy programs and set `DUCKDB_MEMORY_LIMIT`/`DUCKDB_THREADS` in the
terminal before running; do not run multiple database writers at once.

## 4. Verify cleaning and `UNIFIED_DETECTIONS`

If the DuckDB CLI is installed and on `PATH`, open the ingestion database:

```powershell
duckdb .\database\twinflame.duckdb
```

In the DuckDB prompt, run these queries one at a time:

```sql
SHOW TABLES;
DESCRIBE UNIFIED_DETECTIONS;

SELECT COUNT(*) AS total_rows,
       MIN(acquisition_time_utc) AS first_detection_utc,
       MAX(acquisition_time_utc) AS last_detection_utc
FROM UNIFIED_DETECTIONS;

SELECT source, platform, processing_level, COUNT(*) AS detections
FROM UNIFIED_DETECTIONS
GROUP BY source, platform, processing_level
ORDER BY detections DESC;

SELECT ingestion_id, source_type, start_time, end_time, status
FROM INGESTION_RUNS
ORDER BY ingestion_id DESC;

SELECT processing_id, input_file_id, processing_version, start_time, status
FROM PROCESSING_RUNS
ORDER BY processing_id DESC
LIMIT 30;

SELECT COUNT(*) AS rows,
       COUNT(DISTINCT detection_id) AS unique_detection_ids,
       COUNT(*) - COUNT(DISTINCT detection_id) AS duplicate_ids
FROM UNIFIED_DETECTIONS;
```

Exit the CLI before a script writes to that database:

```text
.quit
```

The cleaning report can be inspected in a DuckDB CLI session with:

```sql
SELECT *
FROM read_csv_auto('data/processed/reports/cleaning_report.csv')
ORDER BY metric;

SELECT * FROM read_parquet('data/processed/quarantine/quarantined_detections.parquet') LIMIT 20;
```

Quarantine rows and quality flags are outputs to review, not automatic proof
that the source is wrong. `CLEANING_THRESHOLD_BASELINES` stores the data-driven
cleaning baselines used for review flags.

## 5. Run Phase 08 once for the historical baseline

Phase 08 runs Phases 00–07 for each supported UTC date in `UNIFIED_DETECTIONS`,
using the selected **240-minute temporal / 1-km spatial threshold** and all six
cross-platform pairs. It does not download missing dates or modify the source
database.

If Phase 05 reference metrics are required, create the two local label files
described in the next section before starting Phase 08. The manifest records
their hashes and row counts.

Before the long run, stop `run_api_ingestion.py` and close DuckDB CLI windows
for both databases. The Phase 08 runner checks that its input database is not
being changed during the backfill.

Audit the available dates and platform coverage first:

```powershell
python scripts/run_phase_08_historical.py --audit-only
```

Expected: JSON with first/last available dates, active-date count, supported
platform totals/coverage, unsupported platform totals, coverage gaps, and API
processing watermark. The run uses the dates that exist; gaps remain gaps.

Run the full historical harmonization with no date filters:

```powershell
python scripts/run_phase_08_historical.py
```

The script prints a stable `run_id`. Save it. Outputs are written under:

```text
data/processed/harmonization/phase_08/<run-id>/
```

That directory contains `phase08_manifest.json`, per-date Parquet partitions,
and `harmonization.duckdb` with the seven harmonization tables. A successful
full-coverage run must end with status `success`; inspect the manifest for
failed dates and coverage gaps. For a stopped run, reuse its printed ID:

```powershell
python scripts/run_phase_08_historical.py --run-id YOUR_RUN_ID
python scripts/run_phase_08_historical.py --run-id YOUR_RUN_ID --retry-failed
```

Replace `YOUR_RUN_ID` with the exact ID printed by the earlier run. Successful
partitions are retained. Do not change the source database or validation-label
files in the middle of a resumable run.

## 6. Phase 05 validation and reference labels

Phase 05 is reference-based scientific validation, distinct from the pipeline's
schema/count checks. It reads these optional local files:

```text
data/validation/candidate_recall_reference_pairs.csv
data/validation/activity_reference_labels.csv
```

The repository includes their empty header templates and an instructions file;
the templates contain no reference labels. Add independently reviewed labels
before the run. Without them, the manifest correctly reports
`skipped_no_reference_data`; that means the harmonization ran, but accuracy
metrics were not measured.

Required header for `candidate_recall_reference_pairs.csv`:

```csv
reference_date_utc,platform_a,detection_id_a,platform_b,detection_id_b,label,reviewer_id,reviewed_at_utc,evidence_reference
```

Allowed pair labels are `same_burning_location`,
`different_burning_location`, and `uncertain`. Candidate recall uses only
independently identified `same_burning_location` positives as its denominator.
Find positives independently of the candidate generator; otherwise missed
pairs cannot be counted and recall is biased.

Required header for `activity_reference_labels.csv`:

```csv
activity_date_utc,platform,detection_id,activity_id,reviewer_id,reviewed_at_utc,evidence_reference
```

`activity_id` must come from a consistent, independent human/reference
interpretation for detections on the same date. Every labeled row must include
reviewer ID, review timestamp, and evidence reference. Do not invent labels to
make a run appear validated.

An optional blind queue of predicted correspondence candidates can be created
after a successful Phase 08 run:

```powershell
python scripts/create_phase05_review_queue.py --manifest .\data\processed\harmonization\phase_08\YOUR_RUN_ID\phase08_manifest.json
```

This creates `data/validation/correspondence_review_queue.csv` and a manifest.
It is an unlabeled sample of generated candidate edges, **not ground truth**;
it cannot measure candidate-generation recall because it cannot include pairs
the generator missed. The implemented Phase 05 metrics are candidate recall
against independent positive pairs and pairwise activity-clustering
classification metrics where activity labels overlap processed detections.
Cross-sensor decision precision/F1 is not currently produced by the orchestration
stage; do not report it from candidate counts alone. Activity pairwise
validation can report TP/FP/FN/TN, precision, recall, F1, specificity, and
accuracy over the labeled comparison universe. Candidate recall reports
retrieved known positives / all known positives.

## 7. Start API ingestion and Phase 09 hourly updates

Only after the Phase 08 full historical baseline succeeds, start the ongoing
API process:

```powershell
python scripts/run_api_ingestion.py
```

The current settings poll worldwide FIRMS data every 10 minutes for MODIS,
NOAA-20, and NOAA-21, requesting a two-day overlap. Each successful nonempty
API response is saved as raw Parquet and then imported into
`UNIFIED_DETECTIONS` with checksum/file tracking and deterministic-ID
deduplication. Phase 09 is attempted after the first completed import pass,
then every 60 minutes by default (`ingestion.harmonization_interval_minutes` in
`config/sources.yaml`). It uses the completed API processing IDs as its
watermark, reprocesses affected dates, and advances the watermark only after
the affected batch succeeds.

Expected log summaries include `CYCLE ... SUMMARY`, `CYCLE ... PROCESSING`,
and `PHASE 09 | status=...`. `not_ready` means there is no successful full
Phase 08 baseline; `no_data` means there are no new API records after the last
watermark. These are different from a failed processing status. Keep this
terminal open while streaming. Press `Ctrl+C` to stop gracefully.

To import pending API Parquet files manually while the fetcher is stopped:

```powershell
python scripts/process_pending_api_files.py
```

To retry files whose last import failed:

```powershell
python scripts/process_pending_api_files.py --retry-failed
```

Then run one Phase 09 catch-up batch:

```powershell
python scripts/run_phase_09_incremental.py
```

The normal `run_api_ingestion.py` loop already calls the importer and Phase 09;
do not run separate writers against the same DuckDB at the same time. Do not
rerun `run_pipeline.py` hourly: it is a full rebuild from all raw files and
replaces `UNIFIED_DETECTIONS`.

## 8. Inspect the harmonization tables

Open the Phase 08 output database using the run ID. Close the ingestion DB
session first if it is open:

```powershell
duckdb .\data\processed\harmonization\phase_08\YOUR_RUN_ID\harmonization.duckdb
```

Phase 09 updates this database in place for affected dates. In the DuckDB
prompt:

```sql
SHOW TABLES;

SELECT *
FROM harm_run_metadata
ORDER BY started_at_utc DESC
LIMIT 20;

SELECT date_utc, platform_pair, candidate_count, strong_count,
       possible_count, rejected_count, insufficient_geometry_count
FROM harm_correspondence_summary
ORDER BY date_utc DESC, platform_pair;

SELECT COUNT(*) AS correspondence_edges
FROM harm_correspondence_edges;

SELECT COUNT(*) AS activity_clusters
FROM harm_activity_clusters;

SELECT COUNT(*) AS cluster_memberships
FROM harm_cluster_members;

SELECT COUNT(*) AS daily_sensor_rows
FROM harm_sensor_activity_daily;

SELECT COUNT(*) AS frp_comparisons
FROM harm_frp_comparisons;
```

The seven output tables are `harm_correspondence_edges`,
`harm_activity_clusters`, `harm_cluster_members`,
`harm_sensor_activity_daily`, `harm_correspondence_summary`,
`harm_frp_comparisons`, and `harm_run_metadata`. Use `DESCRIBE table_name;`
to inspect each schema. The Phase 09 watermark and batch manifests are under
`data/processed/harmonization/phase_09/<phase08-run-id>/`.

To query both source and harmonization databases in one DuckDB CLI session,
open either one and attach the other read-only (substitute the actual run ID):

```sql
ATTACH 'database/twinflame.duckdb' AS source_db (READ_ONLY);
ATTACH 'data/processed/harmonization/phase_08/YOUR_RUN_ID/harmonization.duckdb' AS harm_db (READ_ONLY);

SELECT COUNT(*) FROM source_db.main.UNIFIED_DETECTIONS;
SELECT COUNT(*) FROM harm_db.main.harm_correspondence_edges;
```

Close CLI/read-only dashboard connections before a writer starts if DuckDB
reports that the database is locked. For a dashboard that must stay live while
ingestion writes, use a single controlled query service or a refreshed
read-only dashboard snapshot rather than competing processes opening the same
DuckDB file.

## 9. Run the dashboard after its database wiring is complete

The backend is FastAPI and the frontend is React/Vite. After the dashboard
teammate configures the backend to read both databases described above, open
one terminal from the repository root:

```powershell
python -m uvicorn app.backend.main:app --reload
```

Open another terminal:

```powershell
Set-Location .\app\frontend
npm install # first setup only
npm run dev
```

Use the local URL printed by Vite. The current app configuration exposes only
one `DUCKDB_PATH`, so the dual-database backend change is a required dashboard
integration item, not a pipeline command.

## 10. Optional API preflight and software tests

`python scripts/preflight_firms.py` makes live requests and writes test-area
Parquet files into the raw API tree. It consumes FIRMS quota and those files
can be discovered by the regular pipeline. Run it only when specifically
checking the API key/schema, then review and remove or exclude its test-area
files before building production outputs.

The repository's Python tests can be run from the project root with:

```powershell
python -m pytest src/harmonization/v3/tests
```

Test execution is separate from the operational data pipeline and may create
temporary local artifacts.
