from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from shapely.geometry import Point

from harmonization.v3.config.thresholds import (
    DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM,
)
from harmonization.v3.phases.phase_04_correspondence.phase_04b_daily_activity import (
    run_phase_04b,
)


def make_geometry(
    detection_id,
    longitude,
    latitude=0.0,
    platform="MODIS_TERRA",
    timestamp=None,
    eligible=True,
):
    if timestamp is None:
        timestamp = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)

    observation = SimpleNamespace(
        detection_id=detection_id,
        platform=platform,
        acquisition_time_utc=timestamp,
    )
    qc_result = SimpleNamespace(
        observation=observation,
        eligible_for_spatial_matching=eligible,
    )
    return SimpleNamespace(
        qc_result=qc_result,
        center_point=Point(longitude, latitude),
    )


def test_default_threshold_is_the_selected_one_kilometre_setting():
    assert DEFAULT_ACTIVITY_DISTANCE_THRESHOLDS_KM == (1.0,)

    result = run_phase_04b([
        make_geometry("A", 0.0),
    ])

    assert len(result.experiments) == 1
    assert len(result.summaries) == 1
    assert result.experiments[0].distance_threshold_km == 1.0


def test_nearby_detections_cluster_and_singletons_are_retained():
    geometries = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.002),
        make_geometry("C", 1.0),
    ]

    result = run_phase_04b(geometries, distance_thresholds_km=(0.5,))

    assert len(result.clusters) == 2
    assert sorted(cluster.member_count for cluster in result.clusters) == [1, 2]
    assert result.total_membership_count == 3


def test_thresholds_are_evaluated_independently():
    geometries = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.006),
    ]

    result = run_phase_04b(
        geometries,
        distance_thresholds_km=(0.5, 1.0),
    )

    summary_by_threshold = {
        summary.distance_threshold_km: summary
        for summary in result.summaries
    }

    assert summary_by_threshold[0.5].cluster_count == 2
    assert summary_by_threshold[1.0].cluster_count == 1


def test_different_utc_dates_never_cluster_together():
    geometries = [
        make_geometry(
            "A",
            0.0,
            timestamp=datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc),
        ),
        make_geometry(
            "B",
            0.001,
            timestamp=datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc),
        ),
    ]

    result = run_phase_04b(geometries, distance_thresholds_km=(0.5,))

    assert len(result.clusters) == 2
    assert {
        cluster.activity_date_utc for cluster in result.clusters
    } == {
        datetime(2026, 1, 1).date(),
        datetime(2026, 1, 2).date(),
    }


def test_activity_date_is_derived_after_utc_conversion():
    geometries = [
        make_geometry(
            "A",
            0.0,
            timestamp=datetime(
                2026, 1, 2, 0, 30,
                tzinfo=timezone(timedelta(hours=1)),
            ),
        ),
        make_geometry(
            "B",
            0.001,
            timestamp=datetime(
                2026, 1, 1, 23, 45,
                tzinfo=timezone.utc,
            ),
        ),
    ]

    result = run_phase_04b(geometries, distance_thresholds_km=(0.5,))

    assert len(result.clusters) == 1
    assert result.clusters[0].activity_date_utc.isoformat() == "2026-01-01"


def test_unmatched_and_same_platform_detections_are_included():
    geometries = [
        make_geometry("A", 0.0, platform="MODIS_TERRA"),
        make_geometry("B", 0.001, platform="MODIS_TERRA"),
        make_geometry("C", 1.0, platform="VIIRS_NOAA20"),
    ]

    result = run_phase_04b(geometries, distance_thresholds_km=(0.5,))

    assert result.total_membership_count == 3
    two_member_cluster = next(
        cluster for cluster in result.clusters
        if cluster.member_count == 2
    )
    assert two_member_cluster.platform_counts == (("MODIS_TERRA", 2),)


def test_ineligible_observations_are_excluded():
    geometries = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.001, eligible=False),
    ]

    result = run_phase_04b(geometries, distance_thresholds_km=(0.5,))

    assert result.total_membership_count == 1
    assert result.clusters[0].member_keys == (("MODIS_TERRA", "A"),)


def test_connected_component_chaining_is_explicit():
    # Adjacent detections are within 0.5 km, but A and C are not.
    geometries = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.004),
        make_geometry("C", 0.008),
    ]

    result = run_phase_04b(geometries, distance_thresholds_km=(0.5,))

    assert len(result.clusters) == 1
    cluster = result.clusters[0]
    assert cluster.member_count == 3
    assert cluster.clustering_method == "connected_components"
    assert cluster.chaining_possible is True
    assert cluster.maximum_edge_distance_km <= 0.5 + 1e-9


def test_duplicate_detection_identity_is_rejected():
    geometries = [
        make_geometry("A", 0.0, platform="MODIS_TERRA"),
        make_geometry("A", 0.001, platform="MODIS_TERRA"),
    ]

    with pytest.raises(ValueError, match="Duplicate eligible detection identity"):
        run_phase_04b(geometries, distance_thresholds_km=(0.5,))


def test_missing_centre_for_eligible_detection_is_rejected():
    geometry = make_geometry("A", 0.0)
    geometry.center_point = None

    with pytest.raises(ValueError, match="has no centre point"):
        run_phase_04b([geometry], distance_thresholds_km=(0.5,))


def test_cluster_ids_are_deterministic_and_input_order_independent():
    first = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.001),
        make_geometry("C", 1.0),
    ]
    second = list(reversed(first))

    result_a = run_phase_04b(first, distance_thresholds_km=(0.5,))
    result_b = run_phase_04b(second, distance_thresholds_km=(0.5,))

    ids_a = sorted(cluster.cluster_id for cluster in result_a.clusters)
    ids_b = sorted(cluster.cluster_id for cluster in result_b.clusters)

    assert ids_a == ids_b


def test_each_eligible_detection_has_one_membership_per_experiment():
    geometries = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.001),
        make_geometry("C", 1.0),
    ]

    result = run_phase_04b(
        geometries,
        distance_thresholds_km=(0.5, 0.85, 1.0, 1.5),
    )

    for experiment in result.experiments:
        memberships = [
            item for item in result.memberships
            if item.experiment_id == experiment.experiment_id
        ]
        identities = [(item.platform, item.detection_id) for item in memberships]

        assert len(identities) == 3
        assert len(set(identities)) == 3


def test_compact_mode_keeps_cluster_member_keys_and_releases_memberships():
    geometries = [
        make_geometry("A", 0.0),
        make_geometry("B", 0.001),
        make_geometry("C", 1.0),
    ]

    result = run_phase_04b(
        geometries,
        distance_thresholds_km=(0.5, 1.0),
        retain_intermediate_results=False,
    )

    assert result.memberships == ()
    assert result.memberships_retained is False
    assert result.total_membership_count == 6
    assert all(len(cluster.member_keys) == cluster.member_count for cluster in result.clusters)
    assert all(summary.detection_count == 3 for summary in result.summaries)


def test_naive_timestamp_is_rejected_for_eligible_detection():
    geometries = [
        make_geometry(
            "A",
            0.0,
            timestamp=datetime(2026, 1, 1, 12, 0),
        )
    ]

    with pytest.raises(ValueError, match="timezone-aware"):
        run_phase_04b(geometries, distance_thresholds_km=(0.5,))
