# Lamia's Notes: Run the TwinFlame Overview

## What you need

- Python 3.10 or newer
- Node.js and npm
- The harmonized TwinFlame DuckDB database

The dashboard API is read-only. It does not create or populate the database.
At the time this note was written, the configured DuckDB file was not present
in the workspace, so the UI will show a database error until the path and
pipeline outputs are ready.

## 1. Prepare the database

From the repository root, set `DUCKDB_PATH` in `.env` to the database created
by the pipeline. The default is `database/twinflame.duckdb`; a relative path is
resolved from the repository root. Keep `.env` local and do not commit it.

The Overview expects these tables:

- `UNIFIED_DETECTIONS`
- `harm_activity_clusters`
- `harm_cluster_members`
- `harm_correspondence_edges`
- `harm_correspondence_summary`
- `harm_run_metadata`

Run the standardization and harmonization pipeline first if these tables are
not yet available.

## 2. Install dependencies

Open PowerShell in the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

If PowerShell does not allow activating the virtual environment, you can skip
activation and use the Python installation that already has the project
dependencies.

## 3. Start the API

In the first PowerShell terminal, from the repository root:

```powershell
python -m uvicorn app.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Leave this terminal running. Check the API in a browser:

- Health check: <http://127.0.0.1:8000/api/health> (expected: `{"status":"ok"}`)
- API documentation: <http://127.0.0.1:8000/docs>

## 4. Start and open the dashboard

Open a second PowerShell terminal:

```powershell
Set-Location .\app\frontend
npm install
npm run dev
```

`npm install` is needed once. Open the Vite URL printed in the terminal; the
default is <http://127.0.0.1:5173>. Keep both terminals running while using the
dashboard.

## 5. Check the Overview

Try the date range buttons, then change platform, region, day/night, and FRP.
The KPI cards, map, detection trend, platform chart, and correspondence chart
should refresh together. The latest pipeline executions appear below the
charts. The map uses OpenStreetMap tiles, so an internet connection is needed
for its basemap.

To check the API and filtering tests from the repository root:

```powershell
python -m pytest -q tests\test_dashboard_overview.py
```

To check the frontend production build, from `app\frontend`:

```powershell
npm run build
```

## If something does not work

- **Dashboard says the database is missing:** check `DUCKDB_PATH` in `.env`,
  then confirm the database file exists and the pipeline has run.
- **Dashboard reports missing tables:** complete the pipeline steps that
  create the tables listed above.
- **The page cannot reach the API:** make sure the first terminal is still
  running on port `8000`.
- **`npm` is not recognized:** install Node.js (which includes npm), reopen
  PowerShell, and retry the frontend commands.
- **The map has no background:** check the internet connection; detections
  and the other dashboard panels can still load independently.
