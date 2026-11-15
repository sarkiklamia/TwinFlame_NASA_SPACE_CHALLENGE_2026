from datetime import datetime, timezone, timedelta

import pytest

from src.harmonization.v3.contracts.observation import ObservationQCResult
from src.harmonization.v3.phases.phase_00_input_audit.column_mapping import (
    CanonicalInputRecord,
)
from src.harmonization.v3.phases.phase_07_output_generation.daily_metrics import (
    build_sensor_activity_daily,
)


def make_observation(
    detection_id="D1",
    platform="MODIS_TERRA",
    timestamp=None,
    frp=10.0,
    brightness=300.0,
    bright_t31=280.0,
    bright_ti4=None,
    bright_ti5=None,
):
    return CanonicalInputRecord(
        detection_id=detection_id,
        source_record_id=None,
        source="archive",
        platform=platform,
        raw_platform=platform,
        latitude=35.0,
        longitude=-5.0,
        acquisition_time_utc=timestamp or datetime(
            2026, 1, 1, 12, 0, tzinfo=timezone.utc
        ),
        confidence_native="nominal",
        frp_mw=frp,
        brightness_native=brightness,
        bright_t31=bright_t31,
        bright_ti4=bright_ti4,
        bright_ti5=bright_ti5,
        scan_km=1.0,
        track_km=1.0,
        daynight="D",
        raw_record={},
        mapping_issues=(),
    )


def make_qc(observation, spatial=True, frp=True):
    return ObservationQCResult(
        observation=observation,
        eligible_for_spatial_matching=spatial,
        eligible_for_frp_analysis=frp,
        qc_issues=(),
        qc_warnings=(),
    )


def test_daily_metrics_groups_by_utc_date():
    timestamp = datetime(
        2026, 1, 2, 0, 30,
        tzinfo=timezone(timedelta(hours=2)),
    )
    observation = make_observation(timestamp=timestamp)

    rows = build_sensor_activity_daily(
        [make_qc(observation)],
        run_id="test-run",
    )

    assert len(rows) == 1
    assert rows[0]["date_utc"].isoformat() == "2026-01-01"


def test_daily_metrics_counts_all_detections_and_eligibility_separately():
    first = make_observation("D1", frp=10.0)
    second = make_observation("D2", frp=20.0)

    rows = build_sensor_activity_daily(
        [
            make_qc(first, spatial=True, frp=True),
            make_qc(second, spatial=False, frp=False),
        ],
        run_id="test-run",
    )

    row = rows[0]
    assert row["detection_count"] == 2
    assert row["matching_eligible_count"] == 1
    assert row["frp_eligible_count"] == 1
    assert row["frp_sum_mw"] == 10.0
    assert row["frp_mean_mw"] == 10.0
    assert row["frp_median_mw"] == 10.0


def test_daily_metrics_includes_zero_frp():
    first = make_observation("D1", frp=0.0)
    second = make_observation("D2", frp=10.0)

    rows = build_sensor_activity_daily(
        [make_qc(first), make_qc(second)],
        run_id="test-run",
    )

    assert rows[0]["frp_eligible_count"] == 2
    assert rows[0]["frp_sum_mw"] == 10.0
    assert rows[0]["frp_mean_mw"] == 5.0
    assert rows[0]["frp_median_mw"] == 5.0


def test_modis_brightness_uses_native_brightness_and_t31():
    observation = make_observation(
        brightness=310.0,
        bright_t31=290.0,
    )

    row = build_sensor_activity_daily(
        [make_qc(observation)],
        run_id="test-run",
    )[0]

    assert row["brightness_band_1_mean_k"] == 310.0
    assert row["brightness_band_1_median_k"] == 310.0
    assert row["brightness_band_2_mean_k"] == 290.0
    assert row["brightness_band_2_median_k"] == 290.0


def test_viirs_brightness_uses_ti4_and_ti5():
    observation = make_observation(
        platform="VIIRS_NOAA20",
        brightness=999.0,
        bright_t31=888.0,
        bright_ti4=320.0,
        bright_ti5=300.0,
    )

    row = build_sensor_activity_daily(
        [make_qc(observation)],
        run_id="test-run",
    )[0]

    assert row["brightness_band_1_mean_k"] == 320.0
    assert row["brightness_band_2_mean_k"] == 300.0


def test_missing_viirs_brightness_remains_null():
    observation = make_observation(
        platform="VIIRS_NOAA21",
        bright_ti4=None,
        bright_ti5=None,
    )

    row = build_sensor_activity_daily(
        [make_qc(observation)],
        run_id="test-run",
    )[0]

    assert row["brightness_band_1_mean_k"] is None
    assert row["brightness_band_1_median_k"] is None
    assert row["brightness_band_2_mean_k"] is None
    assert row["brightness_band_2_median_k"] is None


def test_brightness_is_independent_of_frp_eligibility():
    first = make_observation("D1", frp=10.0, brightness=300.0)
    second = make_observation("D2", frp=None, brightness=320.0)

    rows = build_sensor_activity_daily(
        [
            make_qc(first, spatial=True, frp=True),
            make_qc(second, spatial=True, frp=False),
        ],
        run_id="test-run",
    )

    row = rows[0]
    assert row["frp_eligible_count"] == 1
    assert row["brightness_band_1_mean_k"] == 310.0
    assert row["brightness_band_1_median_k"] == 310.0


def test_empty_input_returns_empty_list():
    assert build_sensor_activity_daily([], "test-run") == []


def test_empty_run_id_is_rejected():
    with pytest.raises(ValueError, match="run_id"):
        build_sensor_activity_daily([], "")


def test_naive_timestamp_is_rejected():
    observation = make_observation(
        timestamp=datetime(2026, 1, 1, 12, 0)
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        build_sensor_activity_daily(
            [make_qc(observation)],
            run_id="test-run",
        )
