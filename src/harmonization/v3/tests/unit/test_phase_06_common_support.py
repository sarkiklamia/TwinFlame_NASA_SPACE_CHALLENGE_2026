from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from harmonization.v3.contracts.frp import (
    SpatialSupportAssignment,
    TemporalSupportMembership,
)
from harmonization.v3.phases.phase_06_common_support_frp.common_support import (
    build_common_support_memberships,
    run_common_support_experiments,
)


def make_phase02_result():
    timestamp = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)

    observations = [
        ("TERRA-1", "MODIS_TERRA", 0.0, 0.0, timestamp),
        ("AQUA-1", "MODIS_AQUA", 0.0, 0.0, timestamp),
        (
            "NOAA20-1",
            "VIIRS_NOAA20",
            0.0,
            0.0,
            timestamp.replace(minute=10),
        ),
        (
            "NOAA21-1",
            "VIIRS_NOAA21",
            0.0,
            0.0,
            timestamp.replace(minute=20),
        ),
    ]

    results = []
    for detection_id, platform, latitude, longitude, acq_time in observations:
        observation = SimpleNamespace(
            detection_id=detection_id,
            platform=platform,
            latitude=latitude,
            longitude=longitude,
            acquisition_time_utc=acq_time,
        )
        qc_result = SimpleNamespace(
            observation=observation,
            eligible_for_frp_analysis=True,
        )
        results.append(SimpleNamespace(qc_result=qc_result))

    return SimpleNamespace(results=tuple(results))


def test_common_support_runs_all_nine_experiments():
    results = run_common_support_experiments(make_phase02_result())

    assert len(results) == 9
    assert {
        (item.grid_resolution_km, item.max_group_span_minutes)
        for item in results
    } == {
        (grid, span)
        for grid in (0.5, 1.0, 2.0)
        for span in (5.0, 15.0, 30.0)
    }


def test_every_detection_gets_one_membership_per_experiment():
    phase02 = make_phase02_result()
    results = run_common_support_experiments(phase02)

    for experiment in results:
        identities = [
            (item.platform, item.detection_id)
            for item in experiment.memberships
        ]
        assert len(identities) == 4
        assert len(set(identities)) == 4


def test_same_cell_and_temporal_group_share_support_unit():
    results = run_common_support_experiments(make_phase02_result())

    for experiment in results:
        by_identity = {
            (item.platform, item.detection_id): item
            for item in experiment.memberships
        }

        terra = by_identity[("MODIS_TERRA", "TERRA-1")]
        aqua = by_identity[("MODIS_AQUA", "AQUA-1")]

        assert terra.spatial_cell_id == aqua.spatial_cell_id
        assert terra.temporal_group_id == aqua.temporal_group_id
        assert terra.support_unit_id == aqua.support_unit_id


def test_different_temporal_groups_have_different_support_units():
    results = run_common_support_experiments(make_phase02_result())

    five_minute_experiment = next(
        item for item in results
        if item.grid_resolution_km == 1.0
        and item.max_group_span_minutes == 5.0
    )

    by_identity = {
        (item.platform, item.detection_id): item
        for item in five_minute_experiment.memberships
    }

    terra = by_identity[("MODIS_TERRA", "TERRA-1")]
    noaa21 = by_identity[("VIIRS_NOAA21", "NOAA21-1")]

    assert terra.temporal_group_id != noaa21.temporal_group_id
    assert terra.support_unit_id != noaa21.support_unit_id


def test_spatial_temporal_membership_mismatch_is_rejected():
    spatial = (
        SpatialSupportAssignment(
            detection_id="A",
            platform="MODIS_TERRA",
            cell_id="EPSG6933_1000m_0_0",
            grid_resolution_km=1.0,
            cell_x=0,
            cell_y=0,
            projected_x_m=0.0,
            projected_y_m=0.0,
        ),
    )

    temporal = ()

    with pytest.raises(ValueError, match="membership mismatch"):
        build_common_support_memberships(spatial, temporal)


def test_duplicate_temporal_membership_is_rejected():
    temporal = TemporalSupportMembership(
        detection_id="A",
        platform="MODIS_TERRA",
        support_group_id="GROUP-1",
        support_date_utc=datetime(2026, 7, 10, tzinfo=timezone.utc).date(),
        group_start_utc=datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc),
        group_end_utc=datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc),
        max_group_span_minutes=15.0,
    )

    spatial = (
        SpatialSupportAssignment(
            detection_id="A",
            platform="MODIS_TERRA",
            cell_id="EPSG6933_1000m_0_0",
            grid_resolution_km=1.0,
            cell_x=0,
            cell_y=0,
            projected_x_m=0.0,
            projected_y_m=0.0,
        ),
    )

    with pytest.raises(ValueError, match="Duplicate temporal membership"):
        build_common_support_memberships(spatial, (temporal, temporal))
