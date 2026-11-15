# Phase 08: historical processing

Phase 08 reads `UNIFIED_DETECTIONS` from the supplied DuckDB in read-only mode.
It runs the existing Phases 00–07 on each UTC date that has supported records,
using all six cross-platform pairs, the configured 240-minute / 1-km matching
threshold, and a four-hour input halo on each side of the date. Outputs are
owned by their UTC date, so halo rows do not create duplicate daily products.

## Run

From the project root in PowerShell:

```powershell
python scripts/run_phase_08_historical.py --audit-only
python scripts/run_phase_08_historical.py
```

The audit reports platform coverage and date gaps. The run creates one
directory under `data/processed/harmonization/phase_08/<run-id>/` containing:

- `harmonization.duckdb` with the seven Phase 07 tables.
- `partitions/<partition-run-id>/` with those seven tables as Parquet.
- `phase08_manifest.json` with the source snapshot, coverage, thresholds,
  per-date status, quality counts, output counts, and failures.

Only dates present in `UNIFIED_DETECTIONS` are processed. Missing date ranges
are reported in the manifest and remain absent; the runner does not download or
invent archive records. Phase 05 records when reference-based validation was
skipped because no independent labels were supplied.

## Resume

The runner prints its `run_id` before processing. Reuse that exact value after
an interruption:

```powershell
python scripts/run_phase_08_historical.py --run-id YOUR_PRINTED_RUN_ID
python scripts/run_phase_08_historical.py --run-id YOUR_PRINTED_RUN_ID --retry-failed
```

Replace `YOUR_PRINTED_RUN_ID` with the exact ID printed when the run begins.

Successful partitions are retained. Failed partitions are retried only with
`--retry-failed`; published Parquet partitions can be recovered without
rerunning the scientific phases. A changed source database requires a new run
ID so outputs from different source snapshots are not mixed.

Close DuckDB CLI and stop API ingestion while Phase 08 runs. The pipeline checks
that the source DuckDB and its WAL stay unchanged; it stops if another writer
changes the input. Restart API ingestion after the backfill is complete. Phase
09 incremental harmonization is a separate step and is not started by Phase 08.
