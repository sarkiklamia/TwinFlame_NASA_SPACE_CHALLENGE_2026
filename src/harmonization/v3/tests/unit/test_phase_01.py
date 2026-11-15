from dataclasses import replace
from datetime import datetime, timezone

import pytest

from harmonization.v3.phases.phase_00_input_audit.column_mapping import (
    map_input_record,
)
from harmonization.v3.phases.phase_01_quality_control import (
    run_phase_01,
    run_phase_01_streaming,
)
from harmonization.v3.phases.phase_01_quality_control.quality_rules import (
    evaluate_observation,
)


def make_observation(**overrides):
    row = {
        "detection_id": "FIRMS-001",
        "id": 1,
        "source": "FIRMS",
        "platform": "MODIS_TERRA",
        "latitude": 34.1,
        "longitude": -5.3,
        "acq_date": "2026-11-14",
        "acq_time": "0935",
        "confidence_native": "nominal",
        "frp_mw": 12.5,
        "brightness": 330.0,
        "bright_t31": 300.0,
        "bright_ti4": None,
        "bright_ti5": None,
        "scan_km": 1.0,
        "track_km": 1.0,
        "daynight": "D",
    }
    row.update(overrides)
    return map_input_record(row)


def test_valid_observation_is_eligible_for_spatial_and_frp():
    result = evaluate_observation(make_observation())

    assert result.eligible_for_spatial_matching
    assert result.eligible_for_frp_analysis
    assert result.eligible_for_brightness_analysis
    assert result.qc_issues == ()


def test_missing_frp_does_not_prevent_spatial_matching():
    result = evaluate_observation(make_observation(frp_mw=None))

    assert result.eligible_for_spatial_matching
    assert not result.eligible_for_frp_analysis
    assert "missing_frp" in result.qc_warnings


def test_unknown_platform_prevents_spatial_matching_but_retains_record():
    observation = make_observation(platform="SNPP")
    result = evaluate_observation(observation)

    assert result.observation is observation
    assert not result.eligible_for_spatial_matching
    assert not result.eligible_for_frp_analysis
    assert "unsupported_platform" in result.qc_issues


def test_missing_timestamp_prevents_spatial_matching():
    observation = make_observation(acq_time=None)
    result = evaluate_observation(observation)

    assert not result.eligible_for_spatial_matching
    assert "missing_acq_time" in result.qc_issues


def test_invalid_latitude_prevents_spatial_matching():
    result = evaluate_observation(make_observation(latitude=95.0))

    assert not result.eligible_for_spatial_matching
    assert "latitude_out_of_range" in result.qc_issues


def test_invalid_longitude_prevents_spatial_matching():
    result = evaluate_observation(make_observation(longitude=181.0))

    assert not result.eligible_for_spatial_matching
    assert "longitude_out_of_range" in result.qc_issues


def test_missing_detection_id_does_not_discard_observation():
    observation = make_observation(detection_id=None)
    result = evaluate_observation(observation)

    assert result.observation is observation
    assert not result.eligible_for_spatial_matching
    assert "missing_detection_id" in result.qc_issues


def test_negative_frp_only_affects_frp_eligibility():
    result = evaluate_observation(make_observation(frp_mw=-1.0))

    assert result.eligible_for_spatial_matching
    assert not result.eligible_for_frp_analysis
    assert "negative_frp" in result.qc_issues


def test_missing_brightness_does_not_prevent_spatial_or_frp_eligibility():
    result = evaluate_observation(
        make_observation(brightness=None, bright_t31=None)
    )

    assert result.eligible_for_spatial_matching
    assert result.eligible_for_frp_analysis
    assert not result.eligible_for_brightness_analysis
    assert "missing_brightness" in result.qc_warnings
    assert "missing_bright_t31" in result.qc_warnings


def test_missing_pixel_dimensions_do_not_prevent_spatial_eligibility():
    result = evaluate_observation(
        make_observation(scan_km=None, track_km=None)
    )

    assert result.eligible_for_spatial_matching
    assert result.eligible_for_frp_analysis
    assert "missing_scan_km" in result.qc_warnings
    assert "missing_track_km" in result.qc_warnings


def test_non_finite_frp_is_not_frp_eligible():
    result = evaluate_observation(make_observation(frp_mw=float("nan")))

    assert result.eligible_for_spatial_matching
    assert not result.eligible_for_frp_analysis
    assert "non_finite_frp" in result.qc_issues


def test_phase_01_retains_every_input_in_order():
    first = make_observation()
    second = make_observation(
        detection_id="FIRMS-002",
        platform="UNKNOWN",
    )

    result = run_phase_01([first, second])

    assert result.input_count == 2
    assert result.spatial_eligible_count == 1
    assert result.frp_eligible_count == 1
    assert result.results[0].observation is first
    assert result.results[1].observation is second


def test_timezone_naive_timestamp_is_not_spatially_eligible():
    observation = replace(
        make_observation(),
        acquisition_time_utc=datetime(2026, 11, 14, 9, 35),
    )
    result = evaluate_observation(observation)

    assert not result.eligible_for_spatial_matching
    assert "acquisition_timestamp_not_timezone_aware" in result.qc_issues


def test_brightness_analysis_requires_at_least_one_finite_value():
    missing = evaluate_observation(
        make_observation(
            brightness=None,
            bright_t31=None,
            bright_ti4=None,
            bright_ti5=None,
        )
    )
    non_finite = evaluate_observation(
        make_observation(
            brightness=float("nan"),
            bright_t31=None,
            bright_ti4=None,
            bright_ti5=None,
        )
    )
    finite_zero = evaluate_observation(
        make_observation(
            brightness=0,
            bright_t31=None,
            bright_ti4=None,
            bright_ti5=None,
        )
    )

    assert not missing.eligible_for_brightness_analysis
    assert not non_finite.eligible_for_brightness_analysis
    assert finite_zero.eligible_for_brightness_analysis


def test_streaming_summary_groups_all_three_eligibility_flags():
    first = make_observation()
    second = make_observation(
        detection_id="FIRMS-002",
        frp_mw=None,
        brightness=None,
        bright_t31=None,
    )

    summary = run_phase_01_streaming(iter((first, second)))

    assert summary.input_count == 2
    assert summary.spatial_eligible_count == 2
    assert summary.frp_eligible_count == 1
    assert summary.brightness_eligible_count == 1
    assert summary.issue_counts == {}
    assert summary.warning_counts["missing_frp"] == 1
    assert len(summary.groups) == 1
    assert summary.groups[0].platform == "MODIS_TERRA"
    assert summary.groups[0].utc_date == "2026-11-14"
