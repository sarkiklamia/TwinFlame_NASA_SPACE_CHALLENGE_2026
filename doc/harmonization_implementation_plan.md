# TwinFlame harmonization rebuild and validation plan

## Goal

Keep one canonical implementation under `src/harmonization/v3`. Rebuild or repair it phase by phase against the architecture, validate each gate on the real July 2026 `UNIFIED_DETECTIONS` data, and prepare two later operating modes:

1. Partitioned processing of the historical archive after it is added.
2. Incremental processing after each hourly API ingestion completes.

The source DuckDB database and raw inputs stay read-only to harmonization. Every run writes to a new, provenance-stamped output directory. Existing root-level CSVs and previous run directories remain available until their replacement has passed the relevant gate.

## Current inventory

The repository already has the intended package areas: `config`, `contracts`, `pipeline`, `storage`, `utils`, `tests`, and phase directories 00–09. The phase 00–07 implementations and unit tests have useful synthetic-data foundations. Phase 08 and Phase 09 source modules are empty. Some test support files and bytecode caches are also present; they will be cleaned only after we know they are generated artifacts and a validated replacement exists.

The latest end-to-end July sample run is in `data/processed/harmonization/calibration/july-20261115T093407.243460Z-s202607/`. It profiled all 4,686,875 July rows, selected a reproducible 37,200-row sample (300 per platform per UTC day), and ran Phases 00–04B, 06, and 07. It wrote all seven Parquet tables with row counts reconciled to the run metadata. The focused Phase 04B/06/07 suite passed 44 tests. This is sample validation; the production historical and incremental runners still need bounded processing.

## Phase gates

| Phase | Current state | Work and acceptance gate |
|---|---|---|
| 00 - Input audit and mapping | PASS for the read-only July input audit. UTC half-open filters are available in materialized and streaming readers; streaming mapped all 4,686,875 July rows with zero mapping issues and counts matching the existing profile. | The date-filtered Phase 00 API and July reconciliation passed. Keep full materialization limited to small samples; use streaming for production-sized ranges. |
| 01 - Quality control | PASS for QC behavior and the July streaming audit. All 4,686,875 July rows were assessed: all spatial/FRP/native-brightness usable, zero QC issues, and expected missing bright_ti4/bright_ti5 warnings. | Separate flags and a bounded-memory per-platform/day audit are implemented. Brightness usability only means a finite native source value; sensor band identity and cross-sensor interpretation remain unresolved. Per-row product publication remains to be integrated. |
| 02 - Footprint construction | PASS for the July sample: all 37,200 selected records produced conservative envelopes; zero were ineligible or center-only. Full-month dimensions are positive and complete. | The output explicitly marks the envelopes as approximations, not sensor pixel footprints. Full-month scan/track profiling and reproducible sample geometry checks are recorded. |
| 03 - Candidate generation | PASS for reproducibility on the July sample. Two runs produced byte-identical manifests, all 210 sensitivity cells, candidate screening rows, label templates, and population profiles; 6,665 candidate rows across the grid. The production default is now the user-selected 240-minute / 1-km setting. | The setting is fixed for operational runs. Independent labels are still needed to measure performance; candidates are not confirmed matches. |
| 04A - Pair evidence | PARTIAL. Local equal-area screening-envelope metrics pass edge-case tests and the 6,665-row July sample; 4,358 candidate rows intersect across repeated threshold settings. | Metrics describe the conservative envelopes only. No correspondence classes or threshold decisions are validated without independent reference labels. |
| 04B — Daily activity | PASS on the 37,200-row sample at four calibration distance settings: 142,908 clusters and 148,800 output memberships across all settings. The production default now uses 1 km. Compact mode avoids retaining duplicate membership objects; output rows are derived from each cluster's member IDs. | The sample passes all July dates. Cluster extent is a linear-time conservative upper bound; connected-component chaining remains explicit. These are activity clusters, not confirmed fires. |
| 05 — Independent validation | Validation modules exist; no reference labels have been supplied. A candidate-pair annotation template is available. | Load independently sourced positive and negative pair/activity labels. Measure candidate recall, precision where the sample design supports it, and activity metrics. The user-selected operational threshold remains unvalidated until this evidence is available. |
| 06 — Common-support FRP | PASS on the July sample: all nine spatial/temporal settings completed and 42 paired support comparisons were emitted. Native FRP is retained; fitted calibrations are evaluation-only. | Sample support counts and output rows reconcile. VIIRS legacy brightness mapping still needs confirmation; no brightness comparison or calibration correction is applied. |
| 07 — Outputs | PASS on the July sample. All seven Parquet outputs were written atomically to a unique run folder; counts reconcile with the metadata and the source database remained read-only. The writer normalizes and inserts one table at a time in 5,000-row batches. | Review the sample products, then add row-level QC output and validate bounded historical processing. |
| 08 — Historical processing | All source files are empty. | Implement restartable, date-partitioned processing with overlap for the configured maximum candidate time window, deterministic edge ownership/deduplication, and resumable manifests. Validate on July before the later archive. |
| 09 — Incremental processing | All source files are empty. | Process only newly ingested API partitions after ingestion succeeds. Add an idempotent watermark, late-arrival/backfill handling, retry records, and partition reprocessing. Schedule hourly only after Phases 00–08 pass. |

## Validation order

1. **Phase 00:** PASS for the read-only July audit. The filtered streaming path reconciles exact row/platform/source totals and null counts against the established profile.
2. **Phase 01:** PASS for the full-July QC audit; inspect the saved platform/day counts and warning profile. **Phase 02:** validate footprint behavior on the reproducible July sample and review the full-month scan/track profile.
3. **Phase 03:** PASS for reproducible July sample sensitivity. Use the selected 240-minute / 1-km setting as the production default; keep its scientific performance unvalidated pending independent reference evidence.
4. **Phase 04A:** PASS for metric calculation on the July sample; review screening evidence and geometry limitations. Keep classification blocked until independent references support it.
5. **Phase 04B:** PASS on the 37,200-row July sample across four historical calibration settings. The production default is now 1 km. Keep activity clustering separate from correspondence decisions.
6. **Phase 05:** use independent references to evaluate the selected threshold. Candidate-pair labels alone cannot measure recall; reference-positive pairs outside the generated candidate set are needed too.
7. **Phases 06–07:** PASS on the July sample. Nine native-FRP support settings completed; all seven Parquet tables and their row counts were verified.
8. **Phase 08:** run the complete July month partition by partition and reconcile all output manifests.
9. **Phase 09:** only after archive outputs are accepted, connect hourly API ingestion to idempotent incremental processing.

## Housekeeping rules

- Keep `src/harmonization/v3` as the single active code tree; avoid a parallel “clean” or “v4” package.
- Make replacement files within a phase, then run that phase's acceptance checks before retiring duplicates or backups.
- Keep user-created CSVs at the repository root unchanged. Treat the latest calibration folder as the current run; earlier generated runs are provenance records.
- Do not run the existing whole-table V3 orchestrator on all July rows until bounded processing is implemented.
- Do not schedule the API-to-harmonization chain until Phase 09 is complete and an end-to-end hourly dry run succeeds.
