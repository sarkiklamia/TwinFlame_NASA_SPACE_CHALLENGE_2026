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
