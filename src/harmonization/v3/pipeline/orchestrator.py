
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
import json

from ..config.experiments import build_threshold_experiments
from ..config.thresholds import DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM
from ..phases.phase_00_input_audit.runner import run_phase_00
from ..phases.phase_01_quality_control.runner import run_phase_01
from ..phases.phase_02_footprint_construction.runner import run_phase_02
from ..phases.phase_03_candidate_generation.candidate_generator import (
    SUPPORTED_PLATFORM_PAIRS,
    run_phase_03,
)
from ..phases.phase_04_correspondence.phase_04a_pair_evaluation import (
    run_phase_04a,
)
from ..phases.phase_04_correspondence.phase_04b_daily_activity import (
    run_phase_04b,
)
from ..phases.phase_05_validation.candidate_validation import (
    validate_candidate_recall,
)
from ..phases.phase_05_validation.activity_validation import (
    validate_daily_activity,
)
from ..phases.phase_06_common_support_frp.runner import (
    SPATIAL_RESOLUTIONS_KM,
    TEMPORAL_WINDOWS_MINUTES,
    run_phase_06,
)
from ..phases.phase_07_output_generation.orchestrator import (
    build_phase_07_outputs,
)
from ..phases.phase_07_output_generation.run_metadata import (
    build_run_metadata,
)
from ..storage.failure_writer import write_failed_run_metadata
from ..storage.parquet_writer import write_phase_07_parquet
from .run_context import PipelineRunContext, create_run_context


@dataclass(frozen=True)
class PipelineResult:
    run_context: PipelineRunContext
    phase00: Any
    phase01: Any
    phase02: Any
    phase03: Any
    phase04a: Any
    phase04b: Any
    phase05_status: str
    candidate_recall_results: tuple
    activity_validation_results: tuple
    skipped_validation_types: tuple[str, ...]
    phase06: Any
    phase07: Any
    parquet_paths: dict[str, Path]


class PipelineExecutionError(RuntimeError):
    def __init__(self, run_id: str, failed_stage: str):
        self.run_id = run_id
        self.failed_stage = failed_stage
        super().__init__(
            f"Pipeline run {run_id} failed during stage: {failed_stage}"
        )


def _build_config_id(
    experiments,
    platform_pairs,
    n_bootstrap,
    confidence_level,
    random_seed,
    platforms,
):
    platform_filter = platforms
    if isinstance(platform_filter, str):
        platform_filter = [platform_filter]
    elif platform_filter is not None:
        platform_filter = sorted(platform_filter)

    configuration = {
        "candidate_experiments": [
            {
                "experiment_id": item.experiment_id,
                "time_threshold_minutes": item.time_threshold_minutes,
                "distance_threshold_km": item.distance_threshold_km,
            }
            for item in experiments
        ],
        "platform_pairs": [list(pair) for pair in platform_pairs],
        "activity_distance_thresholds_km": list(
            DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM
        ),
        "frp_spatial_resolutions_km": list(SPATIAL_RESOLUTIONS_KM),
        "frp_temporal_windows_minutes": list(TEMPORAL_WINDOWS_MINUTES),
        "n_bootstrap": n_bootstrap,
        "confidence_level": confidence_level,
        "random_seed": random_seed,
        "platform_filter": platform_filter,
    }

    serialized = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
    )

    digest = sha256(serialized.encode("utf-8")).hexdigest()[:12]
    return f"v3-{digest}"


def run_pipeline(
    *,
    database: str,
    output_root: str | Path,
    table: str = "UNIFIED_DETECTIONS",
    platforms: str | list[str] | None = None,
    reference_pairs: Iterable | None = None,
    activity_reference_labels: Iterable | None = None,
    experiments=None,
    platform_pairs=None,
    n_bootstrap: int = 1000,
    confidence_level: float = 0.95,
    random_seed: int = 42,
    algorithm_version: str = "v3",
    config_id: str | None = None,
    run_id: str | None = None,
    write_outputs: bool = True,
    retain_phase06_intermediates: bool = True,
    acquisition_start_utc: datetime | None = None,
    acquisition_end_utc_exclusive: datetime | None = None,
) -> PipelineResult:
    """
    Execute the complete V3 harmonization workflow.

    Phase 5 validation is performed only when independent reference
    data is supplied. Correspondence-decision validation is deliberately
    excluded because Phase 4A does not classify correspondence decisions.
    """

    if experiments is None:
        experiments = build_threshold_experiments()
    else:
        experiments = tuple(experiments)

    if platform_pairs is None:
        platform_pairs = SUPPORTED_PLATFORM_PAIRS
    else:
        platform_pairs = tuple(tuple(pair) for pair in platform_pairs)

    if config_id is None:
        config_id = _build_config_id(
            experiments,
            platform_pairs,
            n_bootstrap,
            confidence_level,
            random_seed,
            platforms,
        )

    context = create_run_context(
        algorithm_version=algorithm_version,
        config_id=config_id,
        run_id=run_id,
    )

    # Materialize optional reference inputs once.
    reference_pairs = (
        tuple(reference_pairs)
        if reference_pairs is not None
        else None
    )
    activity_reference_labels = (
        tuple(activity_reference_labels)
        if activity_reference_labels is not None
        else None
    )

    # Counts reflect only phases that completed successfully.
    input_count = 0
    candidate_count = 0
    correspondence_edge_count = 0
    activity_cluster_count = 0

    stage = "phase_00_input_audit"

    try:
        phase00 = run_phase_00(
            database=database,
            table=table,
            platforms=platforms,
            acquisition_start_utc=acquisition_start_utc,
            acquisition_end_utc_exclusive=acquisition_end_utc_exclusive,
        )
        input_count = len(phase00.observations)

        stage = "phase_01_quality_control"
        phase01 = run_phase_01(phase00.observations)

        stage = "phase_02_footprint_construction"
        phase02 = run_phase_02(phase01.results)

        stage = "phase_03_candidate_generation"
        phase03 = run_phase_03(
            phase02,
            experiments=experiments,
            platform_pairs=platform_pairs,
        )
        candidate_count = len(phase03.candidates)

        stage = "phase_04a_pair_evaluation"
        phase04a = run_phase_04a(phase03, phase02)
        correspondence_edge_count = len(phase04a.evaluations)

        stage = "phase_04b_daily_activity"
        phase04b = run_phase_04b(phase02)
        activity_cluster_count = len(phase04b.clusters)

        # Phase 5: independent-reference validation only.
        stage = "phase_05_validation"

        candidate_recall_results = ()
        activity_validation_results = ()
        skipped_validation_types = []

        if reference_pairs:
            candidate_recall_results = validate_candidate_recall(
                phase03,
                reference_pairs,
            )
        else:
            skipped_validation_types.append("candidate_recall")

        if activity_reference_labels:
            activity_validation_results = validate_daily_activity(
                phase04b,
                activity_reference_labels,
            )
        else:
            skipped_validation_types.append("daily_activity")

        phase05_status = (
            "completed"
            if candidate_recall_results or activity_validation_results
            else "skipped_no_reference_data"
        )

        stage = "phase_06_common_support_frp"
        phase06 = run_phase_06(
            phase02,
            n_bootstrap=n_bootstrap,
            confidence_level=confidence_level,
            random_seed=random_seed,
            retain_intermediate_results=retain_phase06_intermediates,
        )

        stage = "phase_07_output_generation"

        phase07 = build_phase_07_outputs(
            observations=phase00.observations,
            phase02_result=phase02,
            phase04a_result=phase04a,
            phase04b_result=phase04b,
            phase06_result=phase06,
            run_id=context.run_id,
            algorithm_version=context.algorithm_version,
            config_id=context.config_id,
            started_at_utc=context.started_at_utc,
            status="running",
        )

        parquet_paths = {}
        if write_outputs:
            stage = "phase_07_parquet_export"
            parquet_paths = write_phase_07_parquet(
                phase07_result=phase07,
                output_root=output_root,
                run_id=context.run_id,
            )

    except Exception as exc:
        try:
            finished_at_utc = datetime.now(timezone.utc)

            error_summary = (
                f"{type(exc).__name__}: {exc}"
            )[:2000]

            failure_metadata = build_run_metadata(
                run_id=context.run_id,
                algorithm_version=context.algorithm_version,
                config_id=context.config_id,
                started_at_utc=context.started_at_utc,
                finished_at_utc=finished_at_utc,
                status="failed",
                input_count=input_count,
                candidate_count=candidate_count,
                correspondence_edge_count=correspondence_edge_count,
                activity_cluster_count=activity_cluster_count,
                failed_stage=stage,
                error_summary=error_summary,
            )

            write_failed_run_metadata(
                metadata=failure_metadata,
                output_root=output_root,
            )

        except Exception as metadata_exc:
            exc.add_note(
                "Additionally, failure metadata could not be saved: "
                f"{type(metadata_exc).__name__}: {metadata_exc}"
            )

        raise PipelineExecutionError(
            run_id=context.run_id,
            failed_stage=stage,
        ) from exc

    return PipelineResult(
        run_context=context,
        phase00=phase00,
        phase01=phase01,
        phase02=phase02,
        phase03=phase03,
        phase04a=phase04a,
        phase04b=phase04b,
        phase05_status=phase05_status,
        candidate_recall_results=tuple(candidate_recall_results),
        activity_validation_results=tuple(activity_validation_results),
        skipped_validation_types=tuple(skipped_validation_types),
        phase06=phase06,
        phase07=phase07,
        parquet_paths=parquet_paths,
    )
