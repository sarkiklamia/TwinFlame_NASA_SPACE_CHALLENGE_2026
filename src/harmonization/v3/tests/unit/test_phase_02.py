from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from shapely.geometry import Point

from harmonization.v3.contracts.observation import ObservationQCResult
from harmonization.v3.phases.phase_02_footprint_construction import (
    build_observation_geometry,
    run_phase_02,
    validate_geometry_result,
)


def make_qc(
    *,
    eligible=True,
    scan_km=1.0,
    track_km=1.0,
    latitude=34.0,
    longitude=-5.0,
):
    observation = SimpleNamespace(
        detection_id="TEST-001",
        platform="MODIS_TERRA",
        latitude=latitude,
        longitude=longitude,
        acquisition_time_utc=datetime(
            2025, 7, 1, 10, 0, tzinfo=timezone.utc
        ),
        scan_km=scan_km,
        track_km=track_km,
    )

    return ObservationQCResult(
        observation=observation,
        eligible_for_spatial_matching=eligible,
        eligible_for_frp_analysis=eligible,
        qc_issues=(),
        qc_warnings=(),
    )


def test_valid_dimensions_create_conservative_envelope():
    result = build_observation_geometry(make_qc())

    assert result.geometry_status == "conservative_envelope"
    assert result.center_point.equals(Point(-5.0, 34.0))
    assert result.spatial_envelope.covers(result.center_point)
    assert result.envelope_radius_km == pytest.approx(2**0.5 / 2)
    assert result.provenance.orientation_known is False
    assert "actual sensor pixel footprint" in " ".join(
        result.provenance.limitations
    )


def test_missing_scan_dimension_returns_center_only():
    result = build_observation_geometry(make_qc(scan_km=None))

    assert result.geometry_status == "center_only"
    assert result.center_point.equals(Point(-5.0, 34.0))
    assert result.spatial_envelope is None
    assert "unavailable_or_invalid:scan_km" in result.geometry_issues


def test_missing_track_dimension_returns_center_only():
    result = build_observation_geometry(make_qc(track_km=None))

    assert result.geometry_status == "center_only"
    assert result.spatial_envelope is None
    assert "unavailable_or_invalid:track_km" in result.geometry_issues


@pytest.mark.parametrize(
    "value",
    [0.0, -1.0, float("nan"), float("inf")],
)
def test_invalid_dimensions_return_center_only(value):
    result = build_observation_geometry(make_qc(scan_km=value))

    assert result.geometry_status == "center_only"
    assert result.spatial_envelope is None


def test_spatially_ineligible_observation_has_no_geometry():
    result = build_observation_geometry(make_qc(eligible=False))

    assert result.geometry_status == "ineligible"
    assert result.center_point is None
    assert result.spatial_envelope is None


def test_phase_02_retains_one_result_per_input_in_order():
    first = make_qc()
    second = make_qc(scan_km=None)

    result = run_phase_02([first, second])

    assert result.input_count == 2
    assert result.conservative_envelope_count == 1
    assert result.center_only_count == 1
    assert result.results[0].qc_result is first
    assert result.results[1].qc_result is second


def test_geometry_validation_accepts_valid_result():
    validate_geometry_result(
        build_observation_geometry(make_qc())
    )


def test_envelope_must_cover_detection_center():
    result = build_observation_geometry(make_qc())

    invalid_envelope = result.spatial_envelope.difference(
        result.center_point.buffer(0.00001)
    )

    broken = result.__class__(
        qc_result=result.qc_result,
        center_point=result.center_point,
        spatial_envelope=invalid_envelope,
        geometry_status=result.geometry_status,
        envelope_radius_km=result.envelope_radius_km,
        provenance=result.provenance,
        geometry_issues=result.geometry_issues,
    )

    with pytest.raises(ValueError, match="cover the detection centre"):
        validate_geometry_result(broken)
