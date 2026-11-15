from datetime import date

import pytest

from harmonization.v3.contracts.frp import SensorFRPAggregate
from harmonization.v3.phases.phase_06_common_support_frp.frp_comparison import (
    CROSS_PLATFORM_PAIRS,
    compare_sensor_frp,
)


def make_aggregate(platform, frp, support_unit="unit-1"):
    return SensorFRPAggregate(
        support_unit_id=support_unit,
        spatial_cell_id="cell-1",
        temporal_group_id="time-1",
        support_date_utc=date(2025, 7, 1),
        platform=platform,
        observation_count=1,
        frp_mean_mw=frp,
        frp_median_mw=frp,
        frp_min_mw=frp,
        frp_max_mw=frp,
    )


def test_all_six_platform_pairs_are_configured():
    assert len(CROSS_PLATFORM_PAIRS) == 6


def test_comparison_uses_same_support_unit_and_b_minus_a():
    aggregates = [
        make_aggregate("MODIS_TERRA", 100.0),
        make_aggregate("MODIS_AQUA", 120.0),
    ]

    result = compare_sensor_frp(aggregates)

    assert len(result) == 1
    comparison = result[0]

    assert comparison.platform_a == "MODIS_TERRA"
    assert comparison.platform_b == "MODIS_AQUA"
    assert comparison.frp_a_mw == 100.0
    assert comparison.frp_b_mw == 120.0
    assert comparison.difference_mw == 20.0
    assert comparison.relative_difference == pytest.approx(2 * 20 / 220)


def test_comparison_is_not_created_across_different_support_units():
    aggregates = [
        make_aggregate("MODIS_TERRA", 100.0, "unit-1"),
        make_aggregate("MODIS_AQUA", 120.0, "unit-2"),
    ]

    assert compare_sensor_frp(aggregates) == ()


def test_missing_platform_aggregate_is_skipped():
    aggregates = [
        make_aggregate("MODIS_TERRA", 100.0),
    ]

    assert compare_sensor_frp(aggregates) == ()


def test_both_zero_frp_values_have_undefined_relative_difference():
    aggregates = [
        make_aggregate("MODIS_TERRA", 0.0),
        make_aggregate("MODIS_AQUA", 0.0),
    ]

    result = compare_sensor_frp(aggregates)

    assert len(result) == 1
    assert result[0].difference_mw == 0.0
    assert result[0].relative_difference is None


def test_relative_difference_is_symmetric_and_bounded():
    aggregates = [
        make_aggregate("MODIS_TERRA", 50.0),
        make_aggregate("MODIS_AQUA", 150.0),
    ]

    result = compare_sensor_frp(aggregates)

    assert result[0].relative_difference == pytest.approx(1.0)


def test_duplicate_aggregate_identity_is_rejected():
    aggregates = [
        make_aggregate("MODIS_TERRA", 100.0),
        make_aggregate("MODIS_TERRA", 110.0),
    ]

    with pytest.raises(ValueError, match="Duplicate sensor aggregate"):
        compare_sensor_frp(aggregates)


@pytest.mark.parametrize("invalid_frp", [-1.0, float("nan"), float("inf")])
def test_invalid_mean_frp_is_rejected(invalid_frp):
    aggregates = [
        make_aggregate("MODIS_TERRA", invalid_frp),
    ]

    with pytest.raises(ValueError, match="Invalid mean native FRP"):
        compare_sensor_frp(aggregates)


def test_comparisons_are_deterministic():
    aggregates = [
        make_aggregate("MODIS_AQUA", 120.0, "unit-2"),
        make_aggregate("MODIS_TERRA", 100.0, "unit-2"),
        make_aggregate("MODIS_TERRA", 80.0, "unit-1"),
        make_aggregate("MODIS_AQUA", 90.0, "unit-1"),
    ]

    first = compare_sensor_frp(aggregates)
    second = compare_sensor_frp(reversed(aggregates))

    assert first == second
    assert [item.support_unit_id for item in first] == ["unit-1", "unit-2"]
