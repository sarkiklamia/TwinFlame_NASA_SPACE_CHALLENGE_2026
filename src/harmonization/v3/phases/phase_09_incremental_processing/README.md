# Phase 09: incremental API processing

Phase 09 runs after API Parquet files have been processed into
`UNIFIED_DETECTIONS`. It requires a **successful, full-coverage Phase 08 run**
with the same 240-minute / 1-km settings. A date-scoped Phase 08 pilot is not a
baseline.

The runner uses completed API `PROCESSING_RUNS` IDs as its watermark. It finds
new API detections after the last successful batch, relying on the existing
FIRMS fetch overlap and the API processor's detection-ID deduplication. It
reprocesses each affected UTC day and its previous day, with all platforms
loaded together and the same four-hour match halo used by Phase 08. The input
`UNIFIED_DETECTIONS` database stays read-only.

## Run once

```powershell
python scripts/run_phase_09_incremental.py
```

The runner writes a per-batch manifest and replacement Parquet partitions
under `data/processed/harmonization/phase_09/<phase08-run-id>/`. After each
date succeeds, it transactionally replaces that date's seven harmonization
tables in the Phase 08 output `harmonization.duckdb`. The Phase 08 Parquet files
remain immutable; Phase 09 manifests identify the newer replacement
partitions. The watermark advances only when every affected date in the batch
succeeds.

## Hourly operation

`scripts/run_api_ingestion.py` invokes Phase 09 after API file processing, on a
60-minute interval by default. Set `ingestion.harmonization_interval_minutes`
in `config/sources.yaml` to change the interval. Until a full Phase 08 run is
available, the hourly call reports `not_ready` and leaves the watermark
uninitialized.

Failed batches retain their watermark and successful date outputs. The next
Phase 09 call resumes those dates without duplicating completed output rows.
The checkpoint is `watermark.json` beside the Phase 09 batch manifests.

Phase 05 labels are read from `data/validation/` when present. Their file
hashes are recorded in the batch manifest, and the resulting candidate-recall
and activity pairwise metrics are stored per affected date. A pending batch
cannot resume with changed label files; restore the recorded files or finish
the batch before changing them.
