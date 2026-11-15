"""Run a reproducible, July-only threshold sensitivity study on real data.

The source DuckDB database is opened read-only. The study audits the full
month with SQL aggregates, then runs Phases 00-04B, 06, and 07 on a
deterministic platform-by-UTC-day sample. Correspondence candidates,
activity clusters, and common-support FRP results are exploratory products;
the user-selected operational candidate threshold is recorded separately,
but independent reference evidence is still required to validate it.
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from datetime import date, datetime, time, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from harmonization.v3.config.experiments import build_threshold_experiments
from harmonization.v3.config.thresholds import (
    CALIBRATION_ACTIVITY_DISTANCE_THRESHOLDS_KM,
    CALIBRATION_DISTANCE_THRESHOLDS_KM,
    CALIBRATION_TIME_THRESHOLDS_MINUTES,
    OPERATIONAL_DISTANCE_THRESHOLD_KM,
    OPERATIONAL_TIME_THRESHOLD_MINUTES,
)
from harmonization.v3.contracts.candidate import CandidatePair
from harmonization.v3.phases.phase_00_input_audit.column_mapping import (
    map_input_record,
)
from harmonization.v3.phases.phase_00_input_audit.input_audit import (
    InputAuditAccumulator,
)
from harmonization.v3.phases.phase_00_input_audit.schema_validation import (
    validate_schema,
)
from harmonization.v3.phases.phase_01_quality_control.runner import (
    run_phase_01,
)
from harmonization.v3.phases.phase_02_footprint_construction.runner import (
    run_phase_02,
)
from harmonization.v3.phases.phase_03_candidate_generation.candidate_generator import (
    SUPPORTED_PLATFORM_PAIRS,
    run_phase_03,
)
from harmonization.v3.phases.phase_04_correspondence.phase_04a_pair_evaluation import (
    run_phase_04a,
)
from harmonization.v3.phases.phase_04_correspondence.phase_04b_daily_activity import (
    run_phase_04b,
)
from harmonization.v3.phases.phase_00_input_audit.runner import Phase00Result
from harmonization.v3.phases.phase_07_output_generation.orchestrator import (
    build_phase_07_outputs,
)
from harmonization.v3.phases.phase_06_common_support_frp.runner import (
    run_phase_06,
)
from harmonization.v3.storage.parquet_writer import write_phase_07_parquet


SUPPORTED_PLATFORMS = (
    "MODIS_TERRA",
    "MODIS_AQUA",
    "VIIRS_NOAA20",
    "VIIRS_NOAA21",
)
DEFAULT_DATABASE = PROJECT_ROOT / "database" / "twinflame.duckdb"
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT / "data" / "processed" / "harmonization" / "calibration"
)


def _table_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Invalid table name: {value!r}")
    return f'"{value}"'


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from exc


def _utc_midnight(value: date) -> datetime:
    return datetime.combine(value, time.min)


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _rows_as_dicts(result) -> list[dict[str, Any]]:
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def _profile_full_month(
    connection,
    *,
    table_sql: str,
    start: datetime,
    end_exclusive: datetime,
) -> list[dict[str, Any]]:
    return _rows_as_dicts(connection.execute(
        f"""
        SELECT
            CAST(acquisition_time_utc AS DATE) AS utc_date,
            platform,
            COUNT(*) AS detection_count,
            COUNT(*) FILTER (WHERE latitude IS NULL OR longitude IS NULL)
                AS missing_coordinate_count,
            COUNT(*) FILTER (WHERE frp_mw IS NULL) AS missing_frp_count,
            COUNT(*) FILTER (
                WHERE scan IS NULL OR track IS NULL
            ) AS missing_scan_or_track_count,
            COUNT(*) FILTER (
                WHERE brightness_native IS NULL
                  AND bright_t31 IS NULL
                  AND bright_ti4 IS NULL
                  AND bright_ti5 IS NULL
            ) AS missing_all_brightness_count
        FROM {table_sql}
        WHERE acquisition_time_utc >= ?
          AND acquisition_time_utc < ?
        GROUP BY 1, 2
        ORDER BY 1, 2
        """,
        [start, end_exclusive],
    ))


def _select_stratified_sample(
    connection,
    *,
    table_sql: str,
    start: datetime,
    end_exclusive: datetime,
    sample_per_stratum: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    seed_text = str(seed)
    result = connection.execute(
        f"""
        WITH eligible AS (
            SELECT
                *,
                CAST(acquisition_time_utc AS DATE) AS july_utc_date,
                md5(? || ':' || CAST(detection_id AS VARCHAR)) AS selection_hash
            FROM {table_sql}
            WHERE acquisition_time_utc >= ?
              AND acquisition_time_utc < ?
              AND platform IN ({', '.join('?' for _ in SUPPORTED_PLATFORMS)})
        ), ranked AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY july_utc_date, platform
                ) AS stratum_population_count,
                ROW_NUMBER() OVER (
                    PARTITION BY july_utc_date, platform
                    ORDER BY selection_hash, detection_id
                ) AS sample_rank
            FROM eligible
        )
        SELECT * FROM ranked
        WHERE sample_rank <= ?
        ORDER BY july_utc_date, platform, sample_rank
        """,
        [seed_text, start, end_exclusive, *SUPPORTED_PLATFORMS, sample_per_stratum],
    )

    sampled_rows = _rows_as_dicts(result)
    manifest = []
    source_rows = []
    helper_columns = {
        "july_utc_date",
        "selection_hash",
        "stratum_population_count",
        "sample_rank",
    }

    for row in sampled_rows:
        manifest.append({
            "detection_id": row["detection_id"],
            "platform": row["platform"],
            "utc_date": row["july_utc_date"],
            "acquisition_time_utc": row["acquisition_time_utc"],
            "sample_rank": row["sample_rank"],
            "stratum_population_count": row["stratum_population_count"],
            "selection_hash": row["selection_hash"],
            "sampling_seed": seed,
            "sampling_method": "lowest_md5(seed:detection_id)_per_platform_utc_day",
        })
        source_rows.append({
            key: value for key, value in row.items()
            if key not in helper_columns
        })

    return source_rows, manifest


def _candidate_row(candidate: CandidatePair, evaluation) -> dict[str, Any]:
    return {
        "candidate_id": candidate.candidate_id,
        "experiment_id": candidate.experiment_id,
        "detection_id_a": candidate.detection_id_a,
        "detection_id_b": candidate.detection_id_b,
        "platform_a": candidate.platform_a,
        "platform_b": candidate.platform_b,
        "platform_pair": candidate.platform_pair,
        "time_difference_minutes": candidate.time_difference_minutes,
        "center_distance_km": candidate.center_distance_km,
        "time_threshold_minutes": candidate.time_threshold_minutes,
        "distance_threshold_km": candidate.distance_threshold_km,
        "evaluation_status": evaluation.evaluation_status,
        "geometry_evidence_status": evaluation.geometry_evidence_status,
        "screening_envelopes_intersect": evaluation.screening_envelopes_intersect,
        "intersection_area_km2": evaluation.intersection_area_km2,
        "union_area_km2": evaluation.union_area_km2,
        "iou": evaluation.iou,
        "containment_a": evaluation.containment_a,
        "containment_b": evaluation.containment_b,
        "minimum_boundary_distance_km": evaluation.minimum_boundary_distance_km,
        "normalized_center_distance": evaluation.normalized_center_distance,
        "metric_method": evaluation.metric_method,
        "geometry_status_a": evaluation.geometry_status_a,
        "geometry_status_b": evaluation.geometry_status_b,
    }


def run_calibration(
    *,
    database: Path,
    output_root: Path,
    table: str,
    start_date: date,
    end_date_exclusive: date,
    sample_per_stratum: int,
    seed: int,
) -> Path:
    if start_date >= end_date_exclusive:
        raise ValueError("End date must be later than start date")
    if sample_per_stratum <= 0:
        raise ValueError("Sample size per platform-day must be positive")
    if not database.is_file():
        raise FileNotFoundError(f"DuckDB database not found: {database}")

    table_sql = _table_identifier(table)
    start = _utc_midnight(start_date)
    end_exclusive = _utc_midnight(end_date_exclusive)
    print("Profiling the full requested month from the read-only database...", flush=True)
    connection = duckdb.connect(str(database), read_only=True)

    try:
        description = connection.execute(f"DESCRIBE {table_sql}").fetchall()
        columns = [row[0] for row in description]
        types = {row[0]: row[1] for row in description}
        schema_result = validate_schema(columns, types)
        if not schema_result.valid:
            raise ValueError(schema_result.summary())

        profile = _profile_full_month(
            connection,
            table_sql=table_sql,
            start=start,
            end_exclusive=end_exclusive,
        )
        sampled_rows, manifest = _select_stratified_sample(
            connection,
            table_sql=table_sql,
            start=start,
            end_exclusive=end_exclusive,
            sample_per_stratum=sample_per_stratum,
            seed=seed,
        )
        print(f"Selected {len(sampled_rows):,} stratified rows; mapping sample records...", flush=True)
        source_inventory = _rows_as_dicts(connection.execute(
            f"""
            SELECT platform, source, product_version, COUNT(*) AS row_count
            FROM {table_sql}
            WHERE acquisition_time_utc >= ?
              AND acquisition_time_utc < ?
            GROUP BY 1, 2, 3
            ORDER BY 1, 2, 3
            """,
            [start, end_exclusive],
        ))
    finally:
        connection.close()

    if not profile:
        raise ValueError("No detections found in the requested UTC date range")

    calendar_days = [
        date.fromordinal(start_date.toordinal() + offset)
        for offset in range((end_date_exclusive - start_date).days)
    ]
    expected_strata = {
        (calendar_day, platform)
        for calendar_day in calendar_days
        for platform in SUPPORTED_PLATFORMS
    }
    observed_strata = {(row["utc_date"], row["platform"]) for row in profile}
    missing_strata = sorted(expected_strata - observed_strata)
    unexpected_platforms = sorted(
        {row["platform"] for row in profile} - set(SUPPORTED_PLATFORMS)
    )
    if missing_strata:
        raise ValueError(f"July coverage has empty platform-day strata: {missing_strata[:8]}")
    if unexpected_platforms:
        raise ValueError(f"Unsupported platform(s) in selected month: {unexpected_platforms}")

    expected_sample_count = sum(
        min(sample_per_stratum, int(row["detection_count"]))
        for row in profile
    )
    if len(sampled_rows) != expected_sample_count:
        raise RuntimeError(
            f"Sample selection returned {len(sampled_rows):,} rows; "
            f"expected {expected_sample_count:,}"
        )

    mapped_records = tuple(map_input_record(row) for row in sampled_rows)
    audit_accumulator = InputAuditAccumulator()
    audit_accumulator.update(sampled_rows, mapped_records)
    phase00 = Phase00Result(
        audit=audit_accumulator.report(),
        observations=mapped_records,
    )
    print("Running Phases 01 and 02 on the sample...", flush=True)
    phase01 = run_phase_01(phase00.observations)
    phase02 = run_phase_02(phase01.results)
    run_started_at_utc = datetime.now(timezone.utc)
    run_id = run_started_at_utc.strftime("july-%Y%m%dT%H%M%S.%fZ") + f"-s{seed}"
    experiments = build_threshold_experiments(
        time_thresholds_minutes=CALIBRATION_TIME_THRESHOLDS_MINUTES,
        distance_thresholds_km=CALIBRATION_DISTANCE_THRESHOLDS_KM,
    )
    if len(experiments) != 35:
        raise RuntimeError(f"Expected 35 candidate experiments, got {len(experiments)}")
    print("Running the 35-setting x 6-pair candidate study...", flush=True)
    phase03 = run_phase_03(
        phase02,
        experiments=experiments,
        platform_pairs=SUPPORTED_PLATFORM_PAIRS,
    )
    print("Screening candidate envelopes in Phase 04A...", flush=True)
    phase04a = run_phase_04a(phase03, phase02)
    print("Running the nine common-support FRP sensitivity experiments...", flush=True)
    phase06 = run_phase_06(
        phase02,
        n_bootstrap=200,
        random_seed=seed,
        retain_intermediate_results=False,
    )
    print("Clustering daily activity in the separate Phase 04B branch...", flush=True)
    phase04b = run_phase_04b(
        phase02,
        distance_thresholds_km=CALIBRATION_ACTIVITY_DISTANCE_THRESHOLDS_KM,
        retain_intermediate_results=False,
    )
    activity_sensitivity_rows = [
        {
            "experiment_id": summary.experiment_id,
            "distance_threshold_km": summary.distance_threshold_km,
            "detection_count": summary.detection_count,
            "cluster_count": summary.cluster_count,
            "singleton_count": summary.singleton_count,
            "largest_cluster_size": summary.largest_cluster_size,
        }
        for summary in phase04b.summaries
    ]
    evidence_counts: Counter[tuple[str, str, str]] = Counter()
    for evaluation in phase04a.evaluations:
        pair = evaluation.candidate.platform_pair
        experiment_id = evaluation.candidate.experiment_id
        if evaluation.screening_envelopes_intersect is True:
            evidence_counts[(experiment_id, pair, "envelope_intersection_count")] += 1
        if evaluation.screening_envelopes_intersect is not None:
            evidence_counts[(experiment_id, pair, "envelope_comparable_count")] += 1
        evidence_counts[(experiment_id, pair, evaluation.geometry_evidence_status)] += 1

    sensitivity_rows = []
    for summary in phase03.summaries:
        candidate_counts = dict(summary.candidate_counts_by_platform_pair)
        for platform_a, platform_b in SUPPORTED_PLATFORM_PAIRS:
            pair = f"{platform_a}__{platform_b}"
            sensitivity_rows.append({
                "experiment_id": summary.experiment_id,
                "time_threshold_minutes": summary.time_threshold_minutes,
                "distance_threshold_km": summary.distance_threshold_km,
                "platform_pair": pair,
                "candidate_count_in_stratified_sample": candidate_counts.get(pair, 0),
                "candidate_pairs_screened": candidate_counts.get(pair, 0),
                "screening_envelopes_intersect_count": evidence_counts[
                    (summary.experiment_id, pair, "envelope_intersection_count")
                ],
                "envelope_comparable_count": evidence_counts[
                    (summary.experiment_id, pair, "envelope_comparable_count")
                ],
                "both_envelopes_available_count": evidence_counts[
                    (summary.experiment_id, pair, "both_screening_envelopes_available")
                ],
                "one_envelope_available_count": evidence_counts[
                    (summary.experiment_id, pair, "one_screening_envelope_available")
                ],
                "no_envelopes_available_count": evidence_counts[
                    (summary.experiment_id, pair, "no_screening_envelopes_available")
                ],
                "sample_temporal_pairs_examined": summary.temporal_pairs_examined,
                "sample_pairs_within_maximum_distance": summary.pairs_within_maximum_distance,
                "full_month_candidate_count": None,
                "precision_recall": None,
            })

    evaluations_by_id = {
        evaluation.candidate.candidate_id: evaluation
        for evaluation in phase04a.evaluations
    }
    candidate_rows = [
        _candidate_row(candidate, evaluations_by_id[candidate.candidate_id])
        for candidate in phase03.candidates
    ]

    observations_by_key = {
        (observation.platform, observation.detection_id): observation
        for observation in phase00.observations
    }
    annotation_by_pair = {}
    for candidate in phase03.candidates:
        pair_key = (
            candidate.platform_a,
            candidate.detection_id_a,
            candidate.platform_b,
            candidate.detection_id_b,
        )
        evaluation = evaluations_by_id[candidate.candidate_id]
        annotation = annotation_by_pair.get(pair_key)
        if annotation is None:
            observation_a = observations_by_key[(candidate.platform_a, candidate.detection_id_a)]
            observation_b = observations_by_key[(candidate.platform_b, candidate.detection_id_b)]
            pair_digest = hashlib.sha256(
                "|".join(str(value) for value in pair_key).encode("utf-8")
            ).hexdigest()[:20]
            annotation = {
                "reference_pair_id": pair_digest,
                "detection_id_a": candidate.detection_id_a,
                "detection_id_b": candidate.detection_id_b,
                "platform_a": candidate.platform_a,
                "platform_b": candidate.platform_b,
                "platform_pair": candidate.platform_pair,
                "acquisition_time_utc_a": observation_a.acquisition_time_utc,
                "acquisition_time_utc_b": observation_b.acquisition_time_utc,
                "latitude_a": observation_a.latitude,
                "longitude_a": observation_a.longitude,
                "latitude_b": observation_b.latitude,
                "longitude_b": observation_b.longitude,
                "frp_mw_a": observation_a.frp_mw,
                "frp_mw_b": observation_b.frp_mw,
                "confidence_native_a": observation_a.confidence_native,
                "confidence_native_b": observation_b.confidence_native,
                "center_distance_km": candidate.center_distance_km,
                "time_difference_minutes": candidate.time_difference_minutes,
                "screening_envelopes_intersect": evaluation.screening_envelopes_intersect,
                "geometry_evidence_status": evaluation.geometry_evidence_status,
                "experiment_ids": [],
                "reference_match_label": "",
                "reference_catalog_or_source": "",
                "reference_id": "",
                "reviewer_notes": "",
            }
            annotation_by_pair[pair_key] = annotation
        annotation["experiment_ids"].append(candidate.experiment_id)

    annotation_rows = []
    experiment_order = {
        experiment.experiment_id: index
        for index, experiment in enumerate(experiments)
    }
    for annotation in annotation_by_pair.values():
        annotation["experiment_ids"] = ";".join(sorted(
            set(annotation["experiment_ids"]),
            key=experiment_order.__getitem__,
        ))
        annotation["candidate_threshold_count"] = len(
            annotation["experiment_ids"].split(";")
        )
        annotation_rows.append(annotation)
    annotation_rows.sort(key=lambda row: row["reference_pair_id"])

    phase07_result = build_phase_07_outputs(
        observations=phase00.observations,
        phase02_result=phase02,
        phase04a_result=phase04a,
        phase04b_result=phase04b,
        phase06_result=phase06,
        run_id=run_id,
        algorithm_version="twinflame-harmonization-v3",
        config_id=f"july-sensitivity-s{seed}",
        started_at_utc=run_started_at_utc,
        finished_at_utc=datetime.now(timezone.utc),
        status="success",
    )
    output_directory = output_root / run_id
    output_directory.mkdir(parents=True, exist_ok=False)

    _write_csv(
        output_directory / "july_population_profile.csv",
        [
            "utc_date", "platform", "detection_count",
            "missing_coordinate_count", "missing_frp_count",
            "missing_scan_or_track_count", "missing_all_brightness_count",
        ],
        profile,
    )
    _write_csv(
        output_directory / "july_sample_manifest.csv",
        [
            "detection_id", "platform", "utc_date", "acquisition_time_utc",
            "sample_rank", "stratum_population_count", "selection_hash",
            "sampling_seed", "sampling_method",
        ],
        manifest,
    )
    _write_csv(
        output_directory / "july_threshold_sensitivity_35x6.csv",
        [
            "experiment_id", "time_threshold_minutes", "distance_threshold_km",
            "platform_pair", "candidate_count_in_stratified_sample",
            "candidate_pairs_screened", "screening_envelopes_intersect_count",
            "envelope_comparable_count", "both_envelopes_available_count",
            "one_envelope_available_count", "no_envelopes_available_count",
            "sample_temporal_pairs_examined", "sample_pairs_within_maximum_distance",
            "full_month_candidate_count", "precision_recall",
        ],
        sensitivity_rows,
    )
    _write_csv(
        output_directory / "july_candidate_screening_sample.csv",
        [
            "candidate_id", "experiment_id", "detection_id_a", "detection_id_b",
            "platform_a", "platform_b", "platform_pair", "time_difference_minutes",
            "center_distance_km", "time_threshold_minutes", "distance_threshold_km",
            "evaluation_status", "geometry_evidence_status",
            "screening_envelopes_intersect", "intersection_area_km2",
            "union_area_km2", "iou", "containment_a", "containment_b",
            "minimum_boundary_distance_km", "normalized_center_distance",
            "metric_method", "geometry_status_a", "geometry_status_b",
        ],
        candidate_rows,
    )
    _write_csv(
        output_directory / "july_candidate_reference_label_template.csv",
        [
            "reference_pair_id", "detection_id_a", "detection_id_b",
            "platform_a", "platform_b", "platform_pair",
            "acquisition_time_utc_a", "acquisition_time_utc_b",
            "latitude_a", "longitude_a", "latitude_b", "longitude_b",
            "frp_mw_a", "frp_mw_b", "confidence_native_a", "confidence_native_b",
            "center_distance_km", "time_difference_minutes",
            "screening_envelopes_intersect", "geometry_evidence_status",
            "experiment_ids", "candidate_threshold_count",
            "reference_match_label", "reference_catalog_or_source",
            "reference_id", "reviewer_notes",
        ],
        annotation_rows,
    )
    _write_csv(
        output_directory / "july_activity_threshold_sensitivity.csv",
        [
            "experiment_id", "distance_threshold_km", "detection_count",
            "cluster_count", "singleton_count", "largest_cluster_size",
        ],
        activity_sensitivity_rows,
    )
    _write_csv(
        output_directory / "july_activity_clusters_sample.csv",
        list(phase07_result.tables["harm_activity_clusters"][0])
        if phase07_result.tables["harm_activity_clusters"]
        else [
            "activity_cluster_id", "activity_date_utc", "centroid_latitude",
            "centroid_longitude", "member_count", "terra_count", "aqua_count",
            "noaa20_count", "noaa21_count", "sensor_count", "start_time_utc",
            "end_time_utc", "cluster_extent_km", "cluster_area_km2",
            "cluster_method", "run_id",
        ],
        phase07_result.tables["harm_activity_clusters"],
    )
    _write_csv(
        output_directory / "july_activity_memberships_sample.csv",
        list(phase07_result.tables["harm_cluster_members"][0])
        if phase07_result.tables["harm_cluster_members"]
        else [
            "activity_cluster_id", "detection_id", "platform",
            "membership_method", "membership_distance_km",
            "membership_quality", "run_id",
        ],
        phase07_result.tables["harm_cluster_members"],
    )

    phase07_output_root = output_directory / "phase07"
    phase07_parquet_paths = write_phase_07_parquet(
        phase07_result,
        output_root=phase07_output_root,
        run_id=run_id,
    )

    monthly_rows = sum(int(row["detection_count"]) for row in profile)
    metadata = {
        "run_id": run_id,
        "created_at_utc": datetime.now(timezone.utc),
        "source_database": database.resolve(),
        "source_database_read_only": True,
        "table": table,
        "acquisition_start_utc_inclusive": start,
        "acquisition_end_utc_exclusive": end_exclusive,
        "full_month_row_count": monthly_rows,
        "full_month_platform_day_strata": len(profile),
        "source_inventory": source_inventory,
        "sampling": {
            "method": "lowest md5(seed:detection_id) rank within each platform and UTC day",
            "seed": seed,
            "target_per_platform_day": sample_per_stratum,
            "sampled_rows": len(sampled_rows),
            "sample_manifest_file": "july_sample_manifest.csv",
        },
        "phases_run": [
            "00 sample audit",
            "01 quality control",
            "02 footprint construction",
            "03 candidate generation",
            "04A envelope screening",
            "04B daily activity clustering (separate branch)",
            "06 common-support FRP sensitivity experiments",
            "07 sample scientific products (Parquet)",
        ],
        "phase_counts": {
            "sample_input": len(phase00.observations),
            "sample_spatially_eligible": phase01.spatial_eligible_count,
            "sample_frp_eligible": phase01.frp_eligible_count,
            "sample_brightness_eligible": phase01.brightness_eligible_count,
            "phase02_geometry_rows": phase02.input_count,
            "phase02_ineligible": phase02.ineligible_count,
            "phase02_center_only": phase02.center_only_count,
            "phase02_conservative_envelopes": phase02.conservative_envelope_count,
            "candidate_rows_across_experiments": phase03.candidate_count,
            "phase04a_evaluated_rows": phase04a.candidate_count,
            "phase04b_clusters_across_experiments": len(phase04b.clusters),
            "phase04b_memberships_across_experiments": phase04b.total_membership_count,
            "phase06_experiments": phase06.experiment_count,
            "phase07_tables": phase07_result.table_count,
        },
        "activity_distance_thresholds_km": list(
            CALIBRATION_ACTIVITY_DISTANCE_THRESHOLDS_KM
        ),
        "phase06_n_bootstrap": 200,
        "phase06_intermediate_results_retained": (
            phase06.intermediate_results_retained
        ),
        "phase06_warnings": list(phase06.warnings),
        "phase07_table_row_counts": {
            name: len(rows)
            for name, rows in phase07_result.tables.items()
        },
        "phase07_parquet_directory": str(
            phase07_output_root / run_id
        ),
        "phase07_parquet_files": sorted(
            path.name for path in phase07_parquet_paths.values()
        ),
        "candidate_experiments": [
            {
                "experiment_id": item.experiment_id,
                "time_threshold_minutes": item.time_threshold_minutes,
                "distance_threshold_km": item.distance_threshold_km,
            }
            for item in experiments
        ],
        "platform_pairs": [list(pair) for pair in SUPPORTED_PLATFORM_PAIRS],
        "independent_reference_validation": "not_run_no_reference_labels_supplied",
        "candidate_annotation_template": {
            "file": "july_candidate_reference_label_template.csv",
            "unique_candidate_pairs": len(annotation_rows),
            "warning": "Labels must come from an independent reference source; this candidate-only sheet cannot measure recall by itself.",
        },
        "operational_candidate_threshold": {
            "time_threshold_minutes": OPERATIONAL_TIME_THRESHOLD_MINUTES,
            "distance_threshold_km": OPERATIONAL_DISTANCE_THRESHOLD_KM,
            "selection_status": "user_selected_not_independently_validated",
        },
        "threshold_status": "sensitivity_study_with_user_selected_operational_setting",
        "interpretation": [
            "Threshold counts are from a reproducible stratified sample, not a full-July exact candidate census.",
            "A candidate is a spatiotemporal screening relationship, not a confirmed same-fire match.",
            "Envelope intersection is screening evidence only; it is not a correspondence decision.",
            "Phase 04B clusters are daily connected components; chaining may join distant members and clusters are not confirmed fire incidents.",
            "Phase 06 is a nine-setting common-support FRP sensitivity analysis; no calibration model is selected or applied.",
            "Independent reference labels are still required to estimate precision and recall and scientifically validate the user-selected operational threshold.",
        ],
    }
    (output_directory / "july_calibration_metadata.json").write_text(
        json.dumps(_json_value(metadata), indent=2),
        encoding="utf-8",
    )

    print(f"Full-month input rows profiled: {monthly_rows:,}")
    print(f"Stratified sample rows processed: {len(sampled_rows):,}")
    print(f"Candidate experiments: {len(experiments)} x {len(SUPPORTED_PLATFORM_PAIRS)} platform pairs")
    print(f"Candidate rows screened: {phase04a.candidate_count:,}")
    print(
        f"Phase 04B sample clusters/memberships: "
        f"{len(phase04b.clusters):,}/{phase04b.total_membership_count:,}"
    )
    print(f"Phase 06 support experiments: {phase06.experiment_count}")
    print(f"Phase 07 Parquet tables written: {len(phase07_parquet_paths)}")
    print(
        "Operational candidate threshold: 240 minutes / 1 km "
        "(user-selected; not independently validated)."
    )
    print(f"Outputs: {output_directory}")
    return output_directory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--table", default="UNIFIED_DETECTIONS")
    parser.add_argument("--start-date", type=_parse_date, default=date(2026, 7, 1))
    parser.add_argument("--end-date-exclusive", type=_parse_date, default=date(2026, 8, 1))
    parser.add_argument("--sample-per-platform-day", type=int, default=300)
    parser.add_argument("--seed", type=int, default=202607)
    args = parser.parse_args()

    run_calibration(
        database=args.database,
        output_root=args.output_root,
        table=args.table,
        start_date=args.start_date,
        end_date_exclusive=args.end_date_exclusive,
        sample_per_stratum=args.sample_per_platform_day,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
