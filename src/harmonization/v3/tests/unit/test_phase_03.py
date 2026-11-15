from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from shapely.geometry import Point

from harmonization.v3.config.experiments import (
    build_threshold_experiments,
)
from harmonization.v3.config.thresholds import (
    CandidateThresholdExperiment,
)
from harmonization.v3.contracts.geometry import (
    GeometryProvenance,
    ObservationGeometryResult,
)
from harmonization.v3.phases.phase_03_candidate_generation import (
    SUPPORTED_PLATFORM_PAIRS,
    run_phase_03,
)


BASE_TIME = datetime(
    2026, 7, 1, 12, 0, tzinfo=timezone.utc
)

PROVENANCE = GeometryProvenance(
    method="test",
    source_dimensions=(),
    orientation_known=False,
    assumptions=(),
    limitations=(),
)


def make_geometry(
    detection_id,
    platform,
    latitude=0.0,
    longitude=0.0,
    minutes_after=0.0,
    eligible=True,
    geometry_status="center_only",
):
    observation = SimpleNamespace(
        detection_id=detection_id,
        platform=platform,
        latitude=latitude,
        longitude=longitude,
        acquisition_time_utc=(
            BASE_TIME + timedelta(minutes=minutes_after)
        ),
    )

    qc_result = SimpleNamespace(
        observation=observation,
        eligible_for_spatial_matching=eligible,
        eligible_for_frp_analysis=False,
        qc_issues=(),
        qc_warnings=(),
    )

    return ObservationGeometryResult(
        qc_result=qc_result,
        center_point=(
            Point(longitude, latitude) if eligible else None
        ),
        spatial_envelope=None,
        geometry_status=(
            geometry_status if eligible else "ineligible"
        ),
        envelope_radius_km=None,
        provenance=PROVENANCE,
        geometry_issues=(),
    )


def experiment(
    time_minutes=10,
    distance_km=1.0,
    experiment_id="test",
):
    return CandidateThresholdExperiment(
        experiment_id=experiment_id,
        time_threshold_minutes=time_minutes,
        distance_threshold_km=distance_km,
    )


def test_default_candidate_experiment_is_the_selected_fixed_threshold():
    experiments = build_threshold_experiments()

    assert len(experiments) == 1
    assert experiments[0].experiment_id == "T240m_D1km"
    assert experiments[0].time_threshold_minutes == 240.0
    assert experiments[0].distance_threshold_km == 1.0


def test_custom_experiment_grid_uses_cartesian_product():
    experiments = build_threshold_experiments(
        time_thresholds_minutes=(5, 10),
        distance_thresholds_km=(0.5, 1.0, 2.0),
    )

    assert len(experiments) == 6


def test_experiment_rejects_non_positive_threshold():
    with pytest.raises(ValueError):
        experiment(time_minutes=0)


def test_candidate_must_pass_both_conditions():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.02,
        minutes_after=2,
    )

    result = run_phase_03(
        [a, b],
        [experiment(distance_km=1.0)],
    )

    assert result.candidate_count == 0


def test_temporal_failure_excludes_spatially_close_pair():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
        minutes_after=20,
    )

    result = run_phase_03(
        [a, b],
        [experiment(time_minutes=10)],
    )

    assert result.candidate_count == 0


def test_pair_inside_both_thresholds_is_candidate():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
        minutes_after=2,
    )

    result = run_phase_03([a, b], [experiment()])

    assert result.candidate_count == 1

    candidate = result.candidates[0]

    assert candidate.detection_id_a == "A"
    assert candidate.detection_id_b == "B"
    assert candidate.time_difference_minutes == pytest.approx(2)
    assert candidate.center_distance_km < 1.0


def test_time_and_distance_thresholds_are_inclusive():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.0089,
        minutes_after=10,
    )

    result = run_phase_03(
        [a, b],
        [experiment(time_minutes=10, distance_km=1.0)],
    )

    assert result.candidate_count == 1


def test_threshold_experiments_are_independent():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.008,
        minutes_after=8,
    )

    experiments = [
        experiment(5, 1.0, "strict_time"),
        experiment(10, 0.5, "strict_distance"),
        experiment(10, 1.0, "both_relaxed"),
    ]

    result = run_phase_03([a, b], experiments)

    assert [
        item.experiment_id for item in result.candidates
    ] == ["both_relaxed"]


def test_center_only_geometry_can_generate_candidates():
    a = make_geometry(
        "A",
        "MODIS_TERRA",
        geometry_status="center_only",
    )

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
        geometry_status="center_only",
    )

    result = run_phase_03([a, b], [experiment()])

    assert result.candidate_count == 1


def test_ineligible_observations_are_excluded():
    a = make_geometry(
        "A",
        "MODIS_TERRA",
        eligible=False,
    )

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
    )

    result = run_phase_03([a, b], [experiment()])

    assert result.candidate_count == 0


def test_all_six_platform_pairs_are_supported():
    assert len(SUPPORTED_PLATFORM_PAIRS) == 6

    geometries = []

    for index, (platform_a, platform_b) in enumerate(
        SUPPORTED_PLATFORM_PAIRS
    ):
        geometries.append(
            make_geometry(
                f"A{index}",
                platform_a,
                minutes_after=index * 100,
            )
        )

        geometries.append(
            make_geometry(
                f"B{index}",
                platform_b,
                longitude=0.001,
                minutes_after=index * 100,
            )
        )

    result = run_phase_03(
        geometries,
        [experiment()],
    )

    assert result.candidate_count == 6

    assert {
        candidate.platform_pair
        for candidate in result.candidates
    } == {
        f"{a}__{b}"
        for a, b in SUPPORTED_PLATFORM_PAIRS
    }


def test_same_platform_pairs_are_not_generated():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_TERRA",
        longitude=0.001,
    )

    result = run_phase_03([a, b], [experiment()])

    assert result.candidate_count == 0


def test_many_to_many_candidates_are_preserved():
    geometries = [
        make_geometry("T1", "MODIS_TERRA"),
        make_geometry(
            "T2", "MODIS_TERRA", longitude=0.0001
        ),
        make_geometry(
            "A1", "MODIS_AQUA", longitude=0.0002
        ),
        make_geometry(
            "A2", "MODIS_AQUA", longitude=0.0003
        ),
    ]

    result = run_phase_03(geometries, [experiment()])

    assert result.candidate_count == 4


def test_candidate_preserves_thresholds_and_measurements():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
        minutes_after=3,
    )

    result = run_phase_03(
        [a, b],
        [experiment(10, 1.0, "experiment_01")],
    )

    candidate = result.candidates[0]

    assert candidate.experiment_id == "experiment_01"
    assert candidate.time_threshold_minutes == 10
    assert candidate.distance_threshold_km == 1
    assert candidate.time_difference_minutes == pytest.approx(3)
    assert candidate.center_distance_km > 0


def test_duplicate_detection_identity_is_rejected():
    a1 = make_geometry("A", "MODIS_TERRA")

    a2 = make_geometry(
        "A",
        "MODIS_TERRA",
        longitude=0.001,
    )

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.002,
    )

    with pytest.raises(
        ValueError,
        match="Duplicate detection identity",
    ):
        run_phase_03([a1, a2, b], [experiment()])


def test_duplicate_experiment_ids_are_rejected():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
    )

    with pytest.raises(
        ValueError,
        match="IDs must be unique",
    ):
        run_phase_03(
            [a, b],
            [
                experiment(experiment_id="same"),
                experiment(experiment_id="same"),
            ],
        )


def test_summary_counts_match_candidate_output():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
    )

    result = run_phase_03([a, b], [experiment()])

    assert result.experiment_count == 1
    assert result.summaries[0].candidate_count == 1
    assert result.summaries[0].temporal_pairs_examined == 1
    assert result.summaries[0].pairs_within_maximum_distance == 1


def test_timezone_offsets_are_normalized_to_utc():
    a = make_geometry("A", "MODIS_TERRA")

    b = make_geometry(
        "B",
        "MODIS_AQUA",
        longitude=0.001,
    )

    b.qc_result.observation.acquisition_time_utc = (
        BASE_TIME.astimezone(
            timezone(timedelta(hours=2))
        )
    )

    result = run_phase_03([a, b], [experiment()])

    assert result.candidate_count == 1

    assert (
        result.candidates[0].time_difference_minutes
        == pytest.approx(0)
    )
