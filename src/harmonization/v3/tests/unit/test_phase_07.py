from datetime import datetime, timezone
from types import SimpleNamespace

from itertools import combinations

import pytest
from pyproj import Geod

from src.harmonization.v3.contracts.candidate import CandidatePair
from src.harmonization.v3.contracts.correspondence import (
    CorrespondenceEvaluation,
    Phase04AResult,
)
from src.harmonization.v3.contracts.observation import ObservationQCResult
from src.harmonization.v3.phases.phase_07_output_generation.correspondence_outputs import (
    build_correspondence_edges,
    build_correspondence_summary,
)


def make_candidate(
    candidate_id="candidate_001",
    experiment_id="exp_001",
    detection_id_a="terra_001",
    detection_id_b="noaa20_001",
    time_difference=5.0,
    distance=0.4,
):
    return CandidatePair(
        candidate_id=candidate_id,
        experiment_id=experiment_id,
        detection_id_a=detection_id_a,
        detection_id_b=detection_id_b,
        platform_a="MODIS_TERRA",
        platform_b="VIIRS_NOAA20",
        platform_pair="MODIS_TERRA__VIIRS_NOAA20",
        time_difference_minutes=time_difference,
        center_distance_km=distance,
        time_threshold_minutes=30.0,
        distance_threshold_km=1.0,
    )


def make_evaluation(candidate, geometry_status="both_screening_envelopes_available"):
    return CorrespondenceEvaluation(
        candidate=candidate,
        evaluation_status="candidate_evaluated",
        geometry_evidence_status=geometry_status,
        geometry_status_a="available",
        geometry_status_b="available",
        geometry_method_a="conservative_envelope",
        geometry_method_b="conservative_envelope",
        screening_envelopes_intersect=True,
        geometry_assumptions_a=(),
        geometry_assumptions_b=(),
        geometry_limitations_a=("Screening envelope only",),
        geometry_limitations_b=("Screening envelope only",),
    )


def make_observation(platform, detection_id, timestamp):
    return SimpleNamespace(
        platform=platform,
        detection_id=detection_id,
        acquisition_time_utc=timestamp,
    )


def test_build_correspondence_edges_preserves_candidate_and_experiment_metadata():
    candidate = make_candidate()
    result = Phase04AResult((make_evaluation(candidate),))

    rows = build_correspondence_edges(result, "run_test_001")

    assert len(rows) == 1

    row = rows[0]
    assert row["correspondence_edge_id"] == "candidate_001"
    assert row["detection_id_a"] == "terra_001"
    assert row["detection_id_b"] == "noaa20_001"
    assert row["experiment_id"] == "exp_001"
    assert row["time_threshold_minutes"] == 30.0
    assert row["distance_threshold_km"] == 1.0
    assert row["time_difference_minutes"] == 5.0
    assert row["centre_distance_km"] == 0.4
    assert row["run_id"] == "run_test_001"


def test_correspondence_edges_do_not_invent_unimplemented_metrics():
    candidate = make_candidate()
    result = Phase04AResult((make_evaluation(candidate),))

    row = build_correspondence_edges(result, "run_test_001")[0]

    assert row["intersection_area_km2"] is None
    assert row["iou"] is None
    assert row["containment_a"] is None
    assert row["containment_b"] is None
    assert row["normalized_centre_distance"] is None
    assert row["decision_class"] == "not_classified"


def test_correspondence_summary_groups_by_experiment_and_earlier_utc_date():
    candidate_a = make_candidate(
        candidate_id="candidate_001",
        experiment_id="exp_001",
        detection_id_a="terra_001",
        detection_id_b="noaa20_001",
        time_difference=5.0,
    )
    candidate_b = make_candidate(
        candidate_id="candidate_002",
        experiment_id="exp_002",
        detection_id_a="terra_002",
        detection_id_b="noaa20_002",
        time_difference=15.0,
    )

    result = Phase04AResult((
        make_evaluation(candidate_a),
        make_evaluation(
            candidate_b,
            geometry_status="one_screening_envelope_available",
        ),
    ))

    observations = [
        make_observation(
            "MODIS_TERRA",
            "terra_001",
            datetime(2024, 7, 1, 23, 58, tzinfo=timezone.utc),
        ),
        make_observation(
            "VIIRS_NOAA20",
            "noaa20_001",
            datetime(2024, 7, 2, 0, 3, tzinfo=timezone.utc),
        ),
        make_observation(
            "MODIS_TERRA",
            "terra_002",
            datetime(2024, 7, 3, 10, 0, tzinfo=timezone.utc),
        ),
        make_observation(
            "VIIRS_NOAA20",
            "noaa20_002",
            datetime(2024, 7, 3, 10, 15, tzinfo=timezone.utc),
        ),
    ]

    rows = build_correspondence_summary(
        result,
        observations,
        "run_test_001",
    )

    assert len(rows) == 2

    first = next(row for row in rows if row["experiment_id"] == "exp_001")
    second = next(row for row in rows if row["experiment_id"] == "exp_002")

    assert first["date_utc"].isoformat() == "2024-07-01"
    assert first["candidate_count"] == 1
    assert first["mean_time_difference_minutes"] == 5.0
    assert first["insufficient_geometry_count"] == 0

    assert second["date_utc"].isoformat() == "2024-07-03"
    assert second["candidate_count"] == 1
    assert second["mean_time_difference_minutes"] == 15.0
    assert second["insufficient_geometry_count"] == 1

    assert first["strong_count"] == 0
    assert first["possible_count"] == 0
    assert first["rejected_count"] == 0
    assert first["mean_iou"] is None


def test_summary_accepts_observation_qc_wrappers():
    candidate = make_candidate()
    result = Phase04AResult((make_evaluation(candidate),))

    timestamp = datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc)

    observations = [
        ObservationQCResult(
            observation=make_observation(
                "MODIS_TERRA", "terra_001", timestamp
            ),
            eligible_for_spatial_matching=True,
            eligible_for_frp_analysis=True,
            qc_issues=(),
            qc_warnings=(),
        ),
        ObservationQCResult(
            observation=make_observation(
                "VIIRS_NOAA20", "noaa20_001", timestamp
            ),
            eligible_for_spatial_matching=True,
            eligible_for_frp_analysis=True,
            qc_issues=(),
            qc_warnings=(),
        ),
    ]

    rows = build_correspondence_summary(
        result,
        observations,
        "run_test_001",
    )

    assert len(rows) == 1
    assert rows[0]["candidate_count"] == 1


def test_summary_rejects_missing_candidate_endpoint():
    candidate = make_candidate()
    result = Phase04AResult((make_evaluation(candidate),))

    observations = [
        make_observation(
            "MODIS_TERRA",
            "terra_001",
            datetime(2024, 7, 1, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    with pytest.raises(ValueError, match="Missing observation"):
        build_correspondence_summary(
            result,
            observations,
            "run_test_001",
        )


def test_empty_phase_04a_result_produces_empty_outputs():
    result = Phase04AResult(())

    assert build_correspondence_edges(result, "run_test_001") == []
    assert build_correspondence_summary(
        result, [], "run_test_001"
    ) == []


def test_builders_reject_empty_run_id():
    result = Phase04AResult(())

    with pytest.raises(ValueError, match="run_id"):
        build_correspondence_edges(result, "")

    with pytest.raises(ValueError, match="run_id"):
        build_correspondence_summary(result, [], "")


# ---------------------------------------------------------------------
# Phase 7: Activity output tests
# ---------------------------------------------------------------------

from datetime import date, datetime, timezone
from types import SimpleNamespace

from src.harmonization.v3.contracts.activity import (
    ActivityThresholdExperiment,
    DailyActivityCluster,
    DailyActivityMembership,
    Phase04BResult,
)
from src.harmonization.v3.phases.phase_07_output_generation.activity_outputs import (
    _extent_upper_bound_km,
    _spherical_centroid,
    build_activity_clusters,
    build_cluster_members,
)


def make_phase02_geometry(platform, detection_id, longitude, latitude):
    observation = SimpleNamespace(
        platform=platform,
        detection_id=detection_id,
    )
    qc_result = SimpleNamespace(
        observation=observation,
        eligible_for_spatial_matching=True,
    )
    return SimpleNamespace(
        qc_result=qc_result,
        center_point=SimpleNamespace(x=longitude, y=latitude),
    )


def make_phase04b_result():
    timestamp_a = datetime(2024, 7, 1, 10, 0, tzinfo=timezone.utc)
    timestamp_b = datetime(2024, 7, 1, 10, 15, tzinfo=timezone.utc)

    experiment = ActivityThresholdExperiment(
        experiment_id="ACT_D0p85km",
        distance_threshold_km=0.85,
    )

    cluster = DailyActivityCluster(
        cluster_id="ACT_D0p85km|2024-07-01|cluster001",
        experiment_id="ACT_D0p85km",
        activity_date_utc=date(2024, 7, 1),
        distance_threshold_km=0.85,
        member_count=2,
        member_keys=(
            ("MODIS_TERRA", "terra_001"),
            ("VIIRS_NOAA20", "noaa20_001"),
        ),
        platform_counts=(
            ("MODIS_TERRA", 1),
            ("VIIRS_NOAA20", 1),
        ),
        min_acquisition_time_utc=timestamp_a,
        max_acquisition_time_utc=timestamp_b,
        maximum_edge_distance_km=0.7,
    )

    memberships = (
        DailyActivityMembership(
            experiment_id="ACT_D0p85km",
            cluster_id=cluster.cluster_id,
            platform="MODIS_TERRA",
            detection_id="terra_001",
            acquisition_time_utc=timestamp_a,
        ),
        DailyActivityMembership(
            experiment_id="ACT_D0p85km",
            cluster_id=cluster.cluster_id,
            platform="VIIRS_NOAA20",
            detection_id="noaa20_001",
            acquisition_time_utc=timestamp_b,
        ),
    )

    return Phase04BResult(
        experiments=(experiment,),
        clusters=(cluster,),
        memberships=memberships,
        summaries=(),
    )


def test_activity_cluster_output_preserves_sensor_counts_and_experiment():
    phase04b = make_phase04b_result()

    phase02 = SimpleNamespace(results=(
        make_phase02_geometry("MODIS_TERRA", "terra_001", 0.0, 0.0),
        make_phase02_geometry("VIIRS_NOAA20", "noaa20_001", 0.01, 0.0),
    ))

    rows = build_activity_clusters(phase04b, phase02, "run_test_001")

    assert len(rows) == 1
    row = rows[0]

    assert row["member_count"] == 2
    assert row["terra_count"] == 1
    assert row["aqua_count"] == 0
    assert row["noaa20_count"] == 1
    assert row["noaa21_count"] == 0
    assert row["sensor_count"] == 2
    assert row["activity_date_utc"] == date(2024, 7, 1)
    assert "ACT_D0p85km" in row["cluster_method"]
    assert "distance_threshold_km=0.85" in row["cluster_method"]
    assert "extent_metric=2x_max_centroid_radius_upper_bound" in row["cluster_method"]
    assert row["run_id"] == "run_test_001"


def test_activity_cluster_output_does_not_invent_area():
    phase04b = make_phase04b_result()

    phase02 = SimpleNamespace(results=(
        make_phase02_geometry("MODIS_TERRA", "terra_001", 0.0, 0.0),
        make_phase02_geometry("VIIRS_NOAA20", "noaa20_001", 0.01, 0.0),
    ))

    row = build_activity_clusters(
        phase04b, phase02, "run_test_001"
    )[0]

    assert row["cluster_extent_km"] > 0
    assert row["cluster_area_km2"] is None
    assert row["centroid_latitude"] == pytest.approx(0.0, abs=1e-6)
    assert row["centroid_longitude"] == pytest.approx(0.005, abs=1e-6)


def test_linear_extent_upper_bound_covers_pairwise_diameter():
    coordinates = [
        (-5.0, 34.0),
        (-4.998, 34.001),
        (-5.003, 34.002),
        (-5.001, 33.998),
    ]
    centroid_lat, centroid_lon = _spherical_centroid(coordinates)
    bound = _extent_upper_bound_km(
        coordinates,
        centroid_lat,
        centroid_lon,
    )
    geod = Geod(ellps="WGS84")
    diameter = max(
        geod.inv(a[0], a[1], b[0], b[1])[2] / 1000.0
        for a, b in combinations(coordinates, 2)
    )

    assert bound >= diameter


def test_cluster_members_preserve_experiment_and_leave_unsupported_metrics_null():
    phase04b = make_phase04b_result()

    rows = build_cluster_members(phase04b, "run_test_001")

    assert len(rows) == 2

    for row in rows:
        assert "ACT_D0p85km" in row["membership_method"]
        assert "distance_threshold_km=0.85" in row["membership_method"]
        assert row["membership_distance_km"] is None
        assert row["membership_quality"] is None
        assert row["run_id"] == "run_test_001"


def test_activity_output_builders_accept_compact_phase04b_results():
    full_result = make_phase04b_result()
    compact_result = Phase04BResult(
        experiments=full_result.experiments,
        clusters=full_result.clusters,
        memberships=(),
        summaries=full_result.summaries,
        memberships_retained=False,
    )
    phase02 = SimpleNamespace(results=(
        make_phase02_geometry("MODIS_TERRA", "terra_001", 0.0, 0.0),
        make_phase02_geometry("VIIRS_NOAA20", "noaa20_001", 0.01, 0.0),
    ))

    cluster_rows = build_activity_clusters(
        compact_result,
        phase02,
        "run_test_001",
    )
    member_rows = build_cluster_members(compact_result, "run_test_001")

    assert len(cluster_rows) == 1
    assert len(member_rows) == 2
    assert {
        (row["platform"], row["detection_id"])
        for row in member_rows
    } == {
        ("MODIS_TERRA", "terra_001"),
        ("VIIRS_NOAA20", "noaa20_001"),
    }


def test_activity_cluster_builder_rejects_missing_member_coordinates():
    phase04b = make_phase04b_result()

    phase02 = SimpleNamespace(results=(
        make_phase02_geometry("MODIS_TERRA", "terra_001", 0.0, 0.0),
    ))

    with pytest.raises(ValueError, match="Missing Phase 2 centre coordinates"):
        build_activity_clusters(
            phase04b, phase02, "run_test_001"
        )


def test_activity_builders_reject_empty_run_id():
    phase04b = make_phase04b_result()

    with pytest.raises(ValueError, match="run_id"):
        build_cluster_members(phase04b, "")

    with pytest.raises(ValueError, match="run_id"):
        build_activity_clusters(phase04b, [], "")
