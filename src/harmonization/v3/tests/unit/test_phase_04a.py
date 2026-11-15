from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from harmonization.v3.contracts.candidate import CandidatePair
from harmonization.v3.contracts.geometry import (
    GeometryProvenance,
    ObservationGeometryResult,
)
from harmonization.v3.phases.phase_04_correspondence import run_phase_04a
from harmonization.v3.phases.phase_04_correspondence.spatial_metrics import (
    evaluate_screening_envelope_metrics,
)
from harmonization.v3.phases.phase_07_output_generation.correspondence_outputs import (
    build_correspondence_edges,
)


PROVENANCE = GeometryProvenance(
    method="test_conservative_envelope",
    source_dimensions=("scan_km", "track_km"),
    orientation_known=False,
    assumptions=("synthetic test geometry",),
    limitations=("not an actual sensor pixel footprint",),
)


def make_geometry(detection_id, platform, envelope=None, status=None):
    observation = SimpleNamespace(
        detection_id=detection_id,
        platform=platform,
        acquisition_time_utc=datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    qc = SimpleNamespace(observation=observation)

    return ObservationGeometryResult(
        qc_result=qc,
        center_point=None,
        spatial_envelope=envelope,
        geometry_status=status or (
            "conservative_envelope" if envelope is not None
            else "center_only"
        ),
        envelope_radius_km=1.0 if envelope is not None else None,
        provenance=PROVENANCE,
        geometry_issues=(),
    )


def make_candidate(
    candidate_id="c1",
    experiment_id="T10_D1",
    id_a="A1",
    id_b="B1",
):
    return CandidatePair(
        candidate_id=candidate_id,
        experiment_id=experiment_id,
        detection_id_a=id_a,
        detection_id_b=id_b,
        platform_a="MODIS_TERRA",
        platform_b="MODIS_AQUA",
        platform_pair="MODIS_TERRA__MODIS_AQUA",
        time_difference_minutes=4.0,
        center_distance_km=0.4,
        time_threshold_minutes=10.0,
        distance_threshold_km=1.0,
    )


def test_evaluates_candidate_and_preserves_experiment_measurements():
    candidate = make_candidate()
    geometries = [
        make_geometry("A1", "MODIS_TERRA", box(0, 0, 1, 1)),
        make_geometry("B1", "MODIS_AQUA", box(0.5, 0.5, 2, 2)),
    ]

    result = run_phase_04a([candidate], geometries)

    assert result.candidate_count == 1
    evaluation = result.evaluations[0]
    assert evaluation.candidate is candidate
    assert evaluation.candidate.experiment_id == "T10_D1"
    assert evaluation.candidate.time_difference_minutes == 4.0
    assert evaluation.candidate.center_distance_km == 0.4
    assert evaluation.evaluation_status == "candidate_evaluated"
    assert evaluation.screening_envelopes_intersect is True
    assert evaluation.intersection_area_km2 > 0
    assert evaluation.union_area_km2 > evaluation.intersection_area_km2
    assert 0 < evaluation.iou < 1
    assert evaluation.minimum_boundary_distance_km == pytest.approx(0.0)
    assert evaluation.metric_method == (
        "pair_centered_lambert_azimuthal_equal_area"
    )


def test_non_intersecting_screening_envelopes_are_recorded():
    result = run_phase_04a(
        [make_candidate()],
        [
            make_geometry("A1", "MODIS_TERRA", box(0, 0, 1, 1)),
            make_geometry("B1", "MODIS_AQUA", box(2, 2, 3, 3)),
        ],
    )

    assert result.evaluations[0].screening_envelopes_intersect is False


def test_missing_envelope_does_not_discard_candidate():
    result = run_phase_04a(
        [make_candidate()],
        [
            make_geometry("A1", "MODIS_TERRA", box(0, 0, 1, 1)),
            make_geometry("B1", "MODIS_AQUA"),
        ],
    )

    evaluation = result.evaluations[0]
    assert result.candidate_count == 1
    assert evaluation.screening_envelopes_intersect is None
    assert evaluation.intersection_area_km2 is None
    assert evaluation.union_area_km2 is None
    assert evaluation.iou is None
    assert evaluation.normalized_center_distance is None
    assert (
        evaluation.geometry_evidence_status
        == "one_screening_envelope_available"
    )


def test_two_center_only_records_are_retained_without_overlap_claim():
    result = run_phase_04a(
        [make_candidate()],
        [
            make_geometry("A1", "MODIS_TERRA"),
            make_geometry("B1", "MODIS_AQUA"),
        ],
    )

    evaluation = result.evaluations[0]
    assert evaluation.screening_envelopes_intersect is None
    assert (
        evaluation.geometry_evidence_status
        == "no_screening_envelopes_available"
    )


def test_many_to_many_candidates_are_all_preserved():
    candidates = [
        make_candidate("c1", id_a="A1", id_b="B1"),
        make_candidate("c2", id_a="A1", id_b="B2"),
        make_candidate("c3", id_a="A2", id_b="B1"),
        make_candidate("c4", id_a="A2", id_b="B2"),
    ]
    geometries = [
        make_geometry("A1", "MODIS_TERRA"),
        make_geometry("A2", "MODIS_TERRA"),
        make_geometry("B1", "MODIS_AQUA"),
        make_geometry("B2", "MODIS_AQUA"),
    ]

    result = run_phase_04a(candidates, geometries)

    assert result.candidate_count == 4
    assert len({
        item.candidate.candidate_id for item in result.evaluations
    }) == 4


def test_candidates_from_different_experiments_remain_separate():
    candidates = [
        make_candidate("c1", experiment_id="T5_D05"),
        make_candidate("c2", experiment_id="T10_D1"),
    ]
    geometries = [
        make_geometry("A1", "MODIS_TERRA"),
        make_geometry("B1", "MODIS_AQUA"),
    ]

    result = run_phase_04a(candidates, geometries)

    assert result.counts_by_experiment == (
        ("T10_D1", 1),
        ("T5_D05", 1),
    )


def test_missing_geometry_for_candidate_endpoint_is_an_error():
    with pytest.raises(ValueError, match="Missing Phase 2 geometry"):
        run_phase_04a(
            [make_candidate()],
            [make_geometry("A1", "MODIS_TERRA")],
        )


def test_duplicate_geometry_identity_is_rejected():
    with pytest.raises(ValueError, match="Duplicate geometry identity"):
        run_phase_04a(
            [make_candidate()],
            [
                make_geometry("A1", "MODIS_TERRA"),
                make_geometry("A1", "MODIS_TERRA"),
                make_geometry("B1", "MODIS_AQUA"),
            ],
        )


def test_duplicate_candidate_ids_are_rejected():
    with pytest.raises(ValueError, match="Candidate IDs must be unique"):
        run_phase_04a(
            [
                make_candidate("duplicate"),
                make_candidate("duplicate"),
            ],
            [
                make_geometry("A1", "MODIS_TERRA"),
                make_geometry("B1", "MODIS_AQUA"),
            ],
        )


def test_geometry_provenance_is_preserved():
    result = run_phase_04a(
        [make_candidate()],
        [
            make_geometry("A1", "MODIS_TERRA", box(0, 0, 1, 1)),
            make_geometry("B1", "MODIS_AQUA", box(0, 0, 1, 1)),
        ],
    )

    evaluation = result.evaluations[0]
    assert evaluation.geometry_method_a == "test_conservative_envelope"
    assert (
        "not an actual sensor pixel footprint"
        in evaluation.geometry_limitations_a
    )


def test_phase_does_not_assign_confirmed_match_labels():
    result = run_phase_04a(
        [make_candidate()],
        [
            make_geometry("A1", "MODIS_TERRA"),
            make_geometry("B1", "MODIS_AQUA"),
        ],
    )

    assert result.evaluations[0].evaluation_status == "candidate_evaluated"
    assert not hasattr(result.evaluations[0], "match_class")


def test_containment_and_boundary_distance_use_projected_envelopes():
    result = evaluate_screening_envelope_metrics(
        make_geometry("A1", "MODIS_TERRA", box(0, 0, 0.02, 0.02)),
        make_geometry("B1", "MODIS_AQUA", box(0.005, 0.005, 0.01, 0.01)),
        center_distance_km=0.4,
    )

    assert result.intersects is True
    assert result.containment_a < 1
    assert result.containment_b == pytest.approx(1.0)
    assert result.minimum_boundary_distance_km > 0
    assert result.normalized_center_distance > 0


@pytest.mark.parametrize(
    "envelope_a,envelope_b",
    [
        (box(179.99, -0.01, 180.0, 0.01), box(-180.0, -0.01, -179.99, 0.01)),
        (box(-0.01, -86.4, 0.01, -86.39), box(0.005, -86.4, 0.02, -86.39)),
    ],
)
def test_metrics_are_finite_near_antimeridian_and_polar_latitudes(
    envelope_a,
    envelope_b,
):
    result = evaluate_screening_envelope_metrics(
        make_geometry("A1", "MODIS_TERRA", envelope_a),
        make_geometry("B1", "MODIS_AQUA", envelope_b),
        center_distance_km=0.4,
    )

    assert result.intersection_area_km2 is not None
    assert result.union_area_km2 is not None
    assert 0 <= result.iou <= 1


def test_phase_07_edge_output_preserves_phase_04a_metrics():
    result = run_phase_04a(
        [make_candidate()],
        [
            make_geometry("A1", "MODIS_TERRA", box(0, 0, 0.02, 0.02)),
            make_geometry("B1", "MODIS_AQUA", box(0.005, 0.005, 0.01, 0.01)),
        ],
    )

    row = build_correspondence_edges(result, "run-test-04a")[0]

    assert row["intersection_area_km2"] > 0
    assert row["union_area_km2"] > row["intersection_area_km2"]
    assert row["iou"] > 0
    assert row["minimum_boundary_distance_km"] > 0
    assert row["metric_method"] == (
        "pair_centered_lambert_azimuthal_equal_area"
    )
