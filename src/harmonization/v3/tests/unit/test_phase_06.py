import pytest

from harmonization.v3.config.frp_support import (
    DEFAULT_SPATIAL_GRID_RESOLUTIONS_KM,
    DEFAULT_TEMPORAL_GROUP_SPANS_MINUTES,
    REFERENCE_SPATIAL_SUPPORT,
    REFERENCE_TEMPORAL_SUPPORT,
    SpatialSupportConfig,
    TemporalSupportConfig,
    build_spatial_support_experiments,
    build_temporal_support_experiments,
)
from harmonization.v3.contracts.frp import (
    SpatialSupportAssignment,
    TemporalSupportMembership,
    CommonSupportMembership,
    SensorFRPAggregate,
    FRPComparison,
    CalibrationResult,
    Phase06Result,
)


def test_default_spatial_experiments():
    assert DEFAULT_SPATIAL_GRID_RESOLUTIONS_KM == (0.5, 1.0, 2.0)
    assert len(build_spatial_support_experiments()) == 3
    assert REFERENCE_SPATIAL_SUPPORT.grid_resolution_km == 1.0


def test_default_temporal_experiments():
    assert DEFAULT_TEMPORAL_GROUP_SPANS_MINUTES == (5.0, 15.0, 30.0)
    assert len(build_temporal_support_experiments()) == 3
    assert REFERENCE_TEMPORAL_SUPPORT.max_group_span_minutes == 15.0


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_spatial_resolution_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        SpatialSupportConfig(value)


@pytest.mark.parametrize("value", [0, -1, float("inf"), float("nan")])
def test_temporal_span_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        TemporalSupportConfig(value)


def test_spatial_projection_is_explicit():
    assert REFERENCE_SPATIAL_SUPPORT.projection_crs == "EPSG:8857"


def test_contracts_are_importable():
    assert SpatialSupportAssignment is not None
    assert TemporalSupportMembership is not None
    assert CommonSupportMembership is not None
    assert SensorFRPAggregate is not None
    assert FRPComparison is not None
    assert CalibrationResult is not None
    assert Phase06Result is not None

from types import SimpleNamespace

from harmonization.v3.phases.phase_06_common_support_frp.spatial_support import (
    assign_spatial_support,
    grid_cell_indices,
    run_spatial_support_experiments,
)


def make_geometry(
    detection_id="D1",
    platform="MODIS_TERRA",
    latitude=0.0,
    longitude=0.0,
    frp_eligible=True,
):
    observation = SimpleNamespace(
        detection_id=detection_id,
        platform=platform,
        latitude=latitude,
        longitude=longitude,
    )
    qc_result = SimpleNamespace(
        observation=observation,
        eligible_for_frp_analysis=frp_eligible,
    )
    return SimpleNamespace(qc_result=qc_result)


def test_grid_cell_indices_use_floor_for_negative_coordinates():
    assert grid_cell_indices(-1.0, -1001.0, 1.0) == (-1, -2)


def test_grid_cell_indices_assign_exact_boundary_consistently():
    assert grid_cell_indices(1000.0, 2000.0, 1.0) == (1, 2)


def test_spatial_assignment_uses_projected_coordinates():
    from harmonization.v3.config.frp_support import SpatialSupportConfig

    result = assign_spatial_support(
        [make_geometry(latitude=0.0, longitude=0.0)],
        SpatialSupportConfig(1.0),
    )

    assert len(result) == 1
    assert result[0].detection_id == "D1"
    assert result[0].platform == "MODIS_TERRA"
    assert result[0].grid_resolution_km == 1.0
    assert result[0].projected_x_m == pytest.approx(0.0, abs=1e-6)
    assert result[0].projected_y_m == pytest.approx(0.0, abs=1e-6)


def test_ineligible_frp_observations_are_excluded():
    from harmonization.v3.config.frp_support import SpatialSupportConfig

    result = assign_spatial_support(
        [make_geometry(frp_eligible=False)],
        SpatialSupportConfig(1.0),
    )

    assert result == ()


def test_same_centre_and_resolution_receive_same_cell():
    from harmonization.v3.config.frp_support import SpatialSupportConfig

    geometries = [
        make_geometry("D1", "MODIS_TERRA", 10.0, 20.0),
        make_geometry("D2", "MODIS_AQUA", 10.0, 20.0),
    ]

    result = assign_spatial_support(
        geometries,
        SpatialSupportConfig(1.0),
    )

    assert result[0].cell_id == result[1].cell_id


def test_duplicate_platform_detection_identity_is_rejected():
    from harmonization.v3.config.frp_support import SpatialSupportConfig

    geometries = [
        make_geometry("D1", "MODIS_TERRA"),
        make_geometry("D1", "MODIS_TERRA"),
    ]

    with pytest.raises(ValueError, match="Duplicate observation identity"):
        assign_spatial_support(geometries, SpatialSupportConfig(1.0))


def test_equal_earth_support_includes_polar_latitudes():
    from harmonization.v3.config.frp_support import SpatialSupportConfig

    result = assign_spatial_support(
        [make_geometry(latitude=87.0)],
        SpatialSupportConfig(1.0),
    )
    assert len(result) == 1


def test_spatial_experiments_run_independently():
    geometries = [make_geometry()]

    results = run_spatial_support_experiments(geometries)

    assert tuple(item.grid_resolution_km for item in results) == (
        0.5, 1.0, 2.0
    )
    assert all(len(item.assignments) == 1 for item in results)


def test_cell_ids_include_resolution_and_indices():
    from harmonization.v3.config.frp_support import SpatialSupportConfig

    result = assign_spatial_support(
        [make_geometry()],
        SpatialSupportConfig(1.0),
    )

    assert result[0].cell_id.startswith("EPSG8857_1000m_")

from datetime import datetime, timezone, timedelta

from harmonization.v3.config.frp_support import TemporalSupportConfig
from harmonization.v3.phases.phase_06_common_support_frp.temporal_support import (
    assign_temporal_support,
    run_temporal_support_experiments,
)
from harmonization.v3.contracts.frp import SpatialSupportAssignment


def make_timed_geometry(
    detection_id,
    platform,
    minute,
    day=14,
    hour=10,
    offset=timezone.utc,
):
    timestamp = datetime(
        2026, 11, day, hour, minute, tzinfo=offset
    )
    observation = SimpleNamespace(
        detection_id=detection_id,
        platform=platform,
        latitude=0.0,
        longitude=0.0,
        acquisition_time_utc=timestamp,
    )
    qc_result = SimpleNamespace(
        observation=observation,
        eligible_for_frp_analysis=True,
    )
    return SimpleNamespace(qc_result=qc_result)


def make_spatial_assignment(detection_id, platform, cell_id="CELL_A"):
    return SpatialSupportAssignment(
        detection_id=detection_id,
        platform=platform,
        cell_id=cell_id,
        grid_resolution_km=1.0,
        cell_x=0,
        cell_y=0,
        projected_x_m=0.0,
        projected_y_m=0.0,
    )


def test_temporal_group_uses_bounded_span_from_first_observation():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 0),
        make_timed_geometry("D2", "MODIS_AQUA", 8),
        make_timed_geometry("D3", "VIIRS_NOAA20", 14),
        make_timed_geometry("D4", "VIIRS_NOAA21", 16),
        make_timed_geometry("D5", "MODIS_TERRA", 25),
    ]
    assignments = [
        make_spatial_assignment(item.qc_result.observation.detection_id,
                                item.qc_result.observation.platform)
        for item in geometries
    ]

    result = assign_temporal_support(
        geometries,
        assignments,
        TemporalSupportConfig(15.0),
    )

    group_by_id = {item.detection_id: item.support_group_id for item in result}

    assert group_by_id["D1"] == group_by_id["D2"] == group_by_id["D3"]
    assert group_by_id["D4"] == group_by_id["D5"]
    assert group_by_id["D1"] != group_by_id["D4"]


def test_temporal_groups_never_cross_spatial_cells():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 0),
        make_timed_geometry("D2", "MODIS_AQUA", 1),
    ]
    assignments = [
        make_spatial_assignment("D1", "MODIS_TERRA", "CELL_A"),
        make_spatial_assignment("D2", "MODIS_AQUA", "CELL_B"),
    ]

    result = assign_temporal_support(
        geometries,
        assignments,
        TemporalSupportConfig(15.0),
    )

    assert result[0].support_group_id != result[1].support_group_id


def test_temporal_groups_never_cross_utc_dates():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 59, day=14, hour=23),
        make_timed_geometry("D2", "MODIS_AQUA", 0, day=15, hour=0),
    ]
    assignments = [
        make_spatial_assignment("D1", "MODIS_TERRA"),
        make_spatial_assignment("D2", "MODIS_AQUA"),
    ]

    result = assign_temporal_support(
        geometries,
        assignments,
        TemporalSupportConfig(15.0),
    )

    assert result[0].support_date_utc != result[1].support_date_utc
    assert result[0].support_group_id != result[1].support_group_id


def test_temporal_group_span_is_inclusive():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 0),
        make_timed_geometry("D2", "MODIS_AQUA", 15),
    ]
    assignments = [
        make_spatial_assignment("D1", "MODIS_TERRA"),
        make_spatial_assignment("D2", "MODIS_AQUA"),
    ]

    result = assign_temporal_support(
        geometries,
        assignments,
        TemporalSupportConfig(15.0),
    )

    assert result[0].support_group_id == result[1].support_group_id


def test_temporal_grouping_normalizes_offsets_to_utc():
    geometries = [
        make_timed_geometry(
            "D1", "MODIS_TERRA", 0, hour=10, offset=timezone.utc
        ),
        make_timed_geometry(
            "D2", "MODIS_AQUA", 0, hour=11,
            offset=timezone(timedelta(hours=1))
        ),
    ]
    assignments = [
        make_spatial_assignment("D1", "MODIS_TERRA"),
        make_spatial_assignment("D2", "MODIS_AQUA"),
    ]

    result = assign_temporal_support(
        geometries,
        assignments,
        TemporalSupportConfig(5.0),
    )

    assert result[0].support_group_id == result[1].support_group_id
    assert result[0].group_start_utc.tzinfo == timezone.utc


def test_temporal_grouping_excludes_non_frp_eligible_observations():
    geometry = make_timed_geometry("D1", "MODIS_TERRA", 0)
    geometry.qc_result.eligible_for_frp_analysis = False

    result = assign_temporal_support(
        [geometry],
        [make_spatial_assignment("D1", "MODIS_TERRA")],
        TemporalSupportConfig(15.0),
    )

    assert result == ()


def test_temporal_grouping_rejects_naive_timestamp():
    geometry = make_timed_geometry("D1", "MODIS_TERRA", 0)
    geometry.qc_result.observation.acquisition_time_utc = datetime(
        2026, 11, 14, 10, 0
    )

    with pytest.raises(ValueError, match="naive timestamp"):
        assign_temporal_support(
            [geometry],
            [make_spatial_assignment("D1", "MODIS_TERRA")],
            TemporalSupportConfig(15.0),
        )


def test_every_assigned_observation_gets_exactly_one_membership():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 0),
        make_timed_geometry("D2", "MODIS_AQUA", 5),
        make_timed_geometry("D3", "VIIRS_NOAA20", 40),
    ]
    assignments = [
        make_spatial_assignment(item.qc_result.observation.detection_id,
                                item.qc_result.observation.platform)
        for item in geometries
    ]

    result = assign_temporal_support(
        geometries,
        assignments,
        TemporalSupportConfig(15.0),
    )

    assert len(result) == 3
    assert len({(item.platform, item.detection_id) for item in result}) == 3


def test_temporal_group_ids_are_deterministic():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 0),
        make_timed_geometry("D2", "MODIS_AQUA", 5),
    ]
    assignments = [
        make_spatial_assignment("D1", "MODIS_TERRA"),
        make_spatial_assignment("D2", "MODIS_AQUA"),
    ]

    first = assign_temporal_support(
        geometries, assignments, TemporalSupportConfig(15.0)
    )
    second = assign_temporal_support(
        list(reversed(geometries)),
        list(reversed(assignments)),
        TemporalSupportConfig(15.0),
    )

    assert {
        item.detection_id: item.support_group_id for item in first
    } == {
        item.detection_id: item.support_group_id for item in second
    }


def test_temporal_experiments_are_independent():
    geometries = [
        make_timed_geometry("D1", "MODIS_TERRA", 0),
        make_timed_geometry("D2", "MODIS_AQUA", 10),
    ]
    assignments = [
        make_spatial_assignment("D1", "MODIS_TERRA"),
        make_spatial_assignment("D2", "MODIS_AQUA"),
    ]

    results = run_temporal_support_experiments(geometries, assignments)

    assert tuple(config.max_group_span_minutes for config, _ in results) == (
        5.0, 15.0, 30.0
    )
    assert results[0][1][0].support_group_id != results[0][1][1].support_group_id
    assert results[1][1][0].support_group_id == results[1][1][1].support_group_id
