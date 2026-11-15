# July 2026 harmonization audit

## Scope and source material

The requested work is to use July records from `UNIFIED_DETECTIONS` to calibrate the candidate thresholds, then process the wider dataset through the harmonization workflow. The architecture and pasted delivery plans were treated as design context. Their validation requirements were followed where they align with that request; embedded plan text was not treated as a separate command.

The database was opened read-only throughout. The calibration script queries acquisition time in UTC using the half-open interval `[2026-07-01, 2026-08-01)`. It does not change `UNIFIED_DETECTIONS`.

## July data audit

The selected month contains 4,686,875 rows, across all 31 UTC dates and the four expected platforms:

| Platform | July detections | Product version |
|---|---:|---|
| MODIS Aqua | 305,516 | 61.03 |
| MODIS Terra | 110,673 | 61.03 |
| VIIRS NOAA-20 | 2,170,787 | 2.0 |
| VIIRS NOAA-21 | 2,099,899 | 2.0 |

All July records are marked `C2_SAMPLE`. Coordinates, FRP, scan, track, `brightness_native`, and `bright_t31` are populated for the July rows. `bright_ti4` and `bright_ti5` are NULL for every July row, including VIIRS. The raw VIIRS sample CSVs use the older generic field names `brightness` and `bright_t31`; the sensor-specific mapping for the second VIIRS brightness field must be confirmed before reporting it as I-5. NASA describes VIIRS I-4 and I-5 as distinct brightness-temperature measurements ([FIRMS VIIRS attributes](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html), [VIIRS Collection 2 guide](https://earthdata.nasa.gov/s3fs-public/2024-07/VIIRS_C2_AF-375m_User_Guide_1.0.pdf)).

One NOAA-20 row is at latitude -86.3852°, outside EPSG:6933's area of use. The common-support grid now uses global Equal Earth (EPSG:8857); that actual source row was assigned to a support cell successfully.

## Phase 00 streaming reconciliation

A second Phase 00 audit streamed the complete July interval from the source DuckDB in batches of 100,000 using the read-only connection and the UTC half-open filter `[2026-07-01, 2026-08-01)`. All 4,686,875 rows mapped successfully with zero mapping issues. Per-platform counts exactly matched the population profile above, and all rows were `C2_SAMPLE`. Coordinates, FRP, scan, track, `brightness_native`, and `bright_t31` had zero nulls; `bright_ti4` and `bright_ti5` were null for all rows.

The date filter is now available in both Phase 00 materialized and streaming entry points. The full-month audit used streaming; the materialized entry point remains intended for bounded samples.

## Phase 01 quality-control audit

The production QC rules were applied one record at a time to the complete July interval using 100,000-row input batches. The run assessed 4,686,875 rows in 124 platform-by-UTC-day groups. Every row was eligible for spatial matching and FRP analysis, and every row had at least one finite native brightness value. There were no QC issues. The only warnings were missing `bright_ti4` and `bright_ti5`, each on all 4,686,875 records. Missing these sensor-specific fields did not exclude records from spatial or FRP analysis.

Brightness eligibility here means a finite native-field value is present. It does not certify units, sentinel handling, or physical validity. The old column names have not yet been verified as sensor/band identities, so this does not authorize cross-sensor brightness comparisons. The full-July run report is `data/processed/harmonization/validation/phase01-2026-07-01-to-2026-08-01-20261115T081654.357667Z/`; it contains platform/day counts, QC issue/warning totals, and run metadata. Per-row `harm_observations` publication remains a later output integration task.

## Phase 02 geometry and Phase 03 reproducibility

The full-July SQL profile found positive scan and track dimensions for every row. MODIS Aqua and Terra scan values ranged from 1.0 to 4.8 km and track values from 1.0 to 2.0 km. VIIRS NOAA-20 and NOAA-21 scan values ranged from 0.32 to 0.8 km and track values from 0.36 to 0.78 km. These are source dimensions, not reconstructed footprint measurements.

On the deterministic 37,200-row July sample, Phase 02 produced 37,200 conservative envelopes, with zero ineligible and zero center-only geometries. Provenance labels each envelope as a conservative screening approximation and states that the actual pixel footprint and orientation are unavailable.

The Phase 00-04A sample calibration was repeated at `data/processed/harmonization/calibration/july-20261115T083120.225311Z-s202607/`. It again produced 6,665 candidate rows across the 35-by-6 experiment. Compared with the prior calibration run, the sample manifest, 35-by-6 sensitivity table, candidate-screening rows, reference-label template, and population profile were byte-identical. SHA-256 checksums for this repeat are: manifest `ef29a33cdc7bc4b5ecea873d8f7cfd33ee36d6662f5f77778a3cb186358ba8a9`, sensitivity table `5dec06b485ecd713baca239134f68935cd2744dd7e26aa205c7518dc34986f21`, and candidate rows `635c7d25591d78e966712d900e53d86db1525a45cef94f5efc90cf481c837c00`. The repeated-run metadata now includes brightness eligibility and all Phase 02 geometry-status counts.

## Phase 04A screening-envelope metrics

The repeated July sample run now records projected intersection area, union area, IoU, both containment ratios, minimum boundary distance, and normalized centre distance. Metrics use a pair-centred Lambert azimuthal equal-area projection and are explicitly labelled as screening-envelope evidence. All 6,665 candidate rows had both envelopes available and finite metrics; 4,358 rows intersected across repeated threshold experiments. IoU ranged from 0 to 0.624, and minimum boundary distance ranged from 0 to 1.741 km. The same 1,108 unique detection pairs had identical metric values across their threshold settings, and the new projection-based intersection flags match the previous screen for all 6,665 candidates. The sample output is in `data/processed/harmonization/calibration/july-20261115T083120.225311Z-s202607/july_candidate_screening_sample.csv`.

These metrics still describe approximate envelopes, not actual sensor pixels. Phase 04A leaves every candidate unclassified; no independent correspondence references are available to validate a decision class or measure the performance of the subsequently selected operational threshold.

## Phase 04B, Phase 06, and Phase 07 July sample run

The latest completed end-to-end sample run is `data/processed/harmonization/calibration/july-20261115T093407.243460Z-s202607/`. It profiled the full July population read-only, then processed the same deterministic sample of 37,200 detections through Phases 00-04B, 06, and 07. The source database file remained 677,392,384 bytes.

Phase 04B completed four activity-distance experiments. Its 142,908 clusters contain 148,800 detection memberships across the four settings. Compact result mode retains cluster member IDs and derives the member table at output time instead of holding a duplicate membership object per detection. Cluster extent is the documented linear-time upper bound, twice the maximum geodesic radius from the spherical centroid; the result remains an activity grouping with connected-component chaining, not a confirmed fire boundary.

Phase 06 completed all nine common-support FRP sensitivity settings with 200 date-block bootstrap replicates per uncertainty estimate. It retained native FRP and did not apply a fitted calibration. The output has 42 cross-platform common-support comparison rows. Compact mode discarded per-detection support memberships and one-platform-only aggregates after each experiment; the aggregates needed to validate emitted comparisons were retained.

All seven Phase 07 Parquet tables were written and reopened for row-count verification. The Parquet row counts match `july_calibration_metadata.json`:

| Output table | Rows |
|---|---:|
| `harm_correspondence_edges` | 6,665 |
| `harm_activity_clusters` | 142,908 |
| `harm_cluster_members` | 148,800 |
| `harm_sensor_activity_daily` | 124 |
| `harm_correspondence_summary` | 1,966 |
| `harm_frp_comparisons` | 42 |
| `harm_run_metadata` | 1 |

An earlier attempt at `july-20261115T091839.852717Z-s202607` wrote the CSV evidence but was stopped during Parquet export before the seven-file set was published. Its failure marker identifies the run as incomplete; use the later `july-20261115T093407.243460Z-s202607` run as the completed sample result. The Parquet writer now normalizes and inserts one table at a time in 5,000-row batches and publishes its temporary directory only after all seven files are complete.

## Real-data calibration run

Run command:

```powershell
python scripts/run_july_threshold_calibration.py
```

The script profiles all July rows with DuckDB aggregates, then selects 300 rows from each platform-by-UTC-day stratum. Selection is reproducible from seed `202607` and the lowest MD5 ranks of `seed:detection_id`. This produced 37,200 sample rows across 124 strata. The completed end-to-end run processed the sample through Phases 00-04B, 06, and 07; all 37,200 passed spatial and FRP eligibility checks.

The calibration grid contains seven time limits (5, 10, 15, 30, 60, 180, and 240 minutes) and five centre-distance limits (0.5, 0.85, 1, 1.5, and 2 km), evaluated for six platform pairs. This is a 35-by-6 sensitivity experiment. Across all experiment cells there are 6,665 candidate rows; repeated detections across settings are counted repeatedly. At the broadest setting (240 minutes, 2 km), the sample has 1,108 unique candidate pairs, of which 572 have intersecting screening envelopes.

| Platform pair | Candidates at 240 min / 2 km | Envelope intersections |
|---|---:|---:|
| Aqua–NOAA-20 | 219 | 136 |
| Aqua–NOAA-21 | 198 | 109 |
| Terra–Aqua | 67 | 64 |
| Terra–NOAA-20 | 139 | 91 |
| Terra–NOAA-21 | 138 | 89 |
| NOAA-20–NOAA-21 | 347 | 83 |

These are sample sensitivity counts, not a full-July exact candidate census or confirmed fire matches. The label template has one row per unique sampled candidate pair. It needs independent reference labels; candidate-only labels can support precision estimates but cannot measure recall without a separate set of reference-positive pairs. After reviewing these outputs, the user selected **240 minutes / 1 km** as the fixed operational candidate threshold. This is a project configuration decision; the sample has not independently validated its scientific performance.

Latest completed output directory:

`data/processed/harmonization/calibration/july-20261115T093407.243460Z-s202607/`

It contains the full-month daily/platform profile, reproducible sample manifest, 35-by-6 sensitivity table, candidate-screening rows, annotation template, Phase 04B activity CSVs, seven Parquet outputs under `phase07/`, and run metadata. Earlier user-created CSVs were preserved. Repeated threshold-study runs produced identical manifests, candidate rows, and sensitivity counts.

## Code changes in this work

- The calibration runner evaluates the explicit 35-setting candidate grid, including 2 km; normal V3 runs use the selected 240-minute / 1-km setting.
- The normal Phase 04B daily activity branch uses a single 1-km distance threshold; the calibration runner retains its four historical settings for reproducibility.
- Candidate generation counts broad temporal opportunities without storing the temporal-pair list. A conservative 3D spatial bucket prefilter narrows exact WGS84 distance calculations. The real July sample results matched the prior implementation exactly.
- Phase 06 support uses global EPSG:8857 so valid polar detections are not rejected by EPSG:6933's latitude limit.
- The July calibration runner executes Phase 06 before the larger Phase 04B cluster result and uses compact Phase 04B/06 result modes to avoid duplicate per-detection records.
- The Phase 07 Parquet writer validates the table set, then normalizes, inserts, exports, and releases one table at a time in 5,000-row batches. It atomically renames the temporary run directory only after all seven exports succeed and cleans the temporary directory when interrupted.
- `scripts/run_july_threshold_calibration.py` creates uniquely named outputs and reads the source database read-only.
- The sample output includes a deduplicated reference-label template with blank label/source/reference fields.

The focused Phase 04B/06/07 suite passed 44 tests. The broader V3 suite last passed 249 tests with 12 Shapely deprecation warnings.

## Work still required before full-data processing

The operational threshold is now set to 240 minutes / 1 km by the user's final project decision. The repository has no independent pair/activity reference labels, so its scientific performance, precision, and recall cannot be measured yet.

The July sample now passes Phases 00-04B, 06, and 07, but the full 4,686,875-row month has not been processed through those phases. Phase 08 historical-processing and Phase 09 incremental-processing modules remain empty, and the general V3 runner still needs bounded, partitioned input and output before whole-archive or hourly operation. Phase 04A has no independently validated correspondence classification; the selected threshold is configured but has no independent reference validation. The July sample includes no independent reference labels, and the VIIRS legacy brightness-field mapping remains unresolved.

Before sending all data through V3:

1. Adjudicate candidate pairs using an independent reference source and add reference-positive pairs needed to measure recall.
2. Use independent labels to evaluate Phase 04A screening and the selected operational threshold's performance.
3. Confirm the VIIRS legacy brightness-field mapping from source documentation and correct the sensor-specific output mapping.
4. Implement bounded, partitioned Phase 08 processing and finish Phase 09 incremental processing. Preserve the July-proven one-table-at-a-time output behavior.
5. Run the full-data workflow only after those paths have passed July-scale validation and output review.
