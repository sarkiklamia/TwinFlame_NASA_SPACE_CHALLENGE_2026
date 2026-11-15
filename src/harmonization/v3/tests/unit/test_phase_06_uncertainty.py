from datetime import date, timedelta

import pytest

from harmonization.v3.contracts.frp import SensorFRPAggregate
from harmonization.v3.phases.phase_06_common_support_frp.uncertainty import (
    estimate_phase_06_uncertainty,
)


PLATFORMS = (
    "MODIS_TERRA",
    "MODIS_AQUA",
    "VIIRS_NOAA20",
    "VIIRS_NOAA21",
)


def make_aggregates():
    rows = []

    for day_index in range(10):
        support_date = date(2025, 1, 1) + timedelta(days=day_index)

        for unit_index in range(3):
            support_id = f"support-{day_index}-{unit_index}"
            base = 10.0 + day_index * 2.0 + unit_index * 3.0

            factors = {
                "MODIS_TERRA": 1.00,
                "MODIS_AQUA": 1.08,
                "VIIRS_NOAA20": 1.15,
                "VIIRS_NOAA21": 1.20,
            }

            for platform in PLATFORMS:
                value = base * factors[platform] + 0.5

                rows.append(
                    SensorFRPAggregate(
                        support_unit_id=support_id,
                        spatial_cell_id=f"cell-{day_index}-{unit_index}",
                        temporal_group_id=f"group-{day_index}-{unit_index}",
                        support_date_utc=support_date,
                        platform=platform,
                        observation_count=1,
                        frp_mean_mw=value,
                        frp_median_mw=value,
                        frp_min_mw=value,
                        frp_max_mw=value,
                    )
                )

    return tuple(rows)


def test_phase_06_uncertainty_returns_all_six_calibration_pairs():
    result = estimate_phase_06_uncertainty(
        make_aggregates(),
        n_bootstrap=40,
        random_seed=7,
        validation_fraction=0.30,
    )

    assert len(result.calibration_uncertainties) == 18
    assert len(result.comparison_uncertainties) == 6


def test_calibration_intervals_are_finite_and_ordered():
    result = estimate_phase_06_uncertainty(
        make_aggregates(),
        n_bootstrap=40,
        random_seed=11,
        validation_fraction=0.30,
    )

    fitted = [
        item
        for item in result.calibration_uncertainties
        if item.method == "multiplicative"
    ]

    assert fitted

    for item in fitted:
        if item.slope is None:
            continue

        assert item.slope.lower <= item.slope.estimate <= item.slope.upper
        assert item.intercept_mw.lower <= item.intercept_mw.estimate
        assert item.intercept_mw.estimate <= item.intercept_mw.upper
        assert item.successful_replicates > 0


def test_comparison_uncertainty_uses_date_blocks():
    result = estimate_phase_06_uncertainty(
        make_aggregates(),
        n_bootstrap=40,
        random_seed=19,
        validation_fraction=0.30,
    )

    comparison = result.comparison_uncertainties[0]

    assert comparison.date_count == 10
    assert comparison.support_unit_count == 30
    assert comparison.resampling_unit == "UTC_date_block"
    assert (
        comparison.mean_difference_mw.lower
        <= comparison.mean_difference_mw.estimate
        <= comparison.mean_difference_mw.upper
    )


def test_bootstrap_is_reproducible_with_same_seed():
    aggregates = make_aggregates()

    first = estimate_phase_06_uncertainty(
        aggregates, n_bootstrap=40, random_seed=123
    )
    second = estimate_phase_06_uncertainty(
        aggregates, n_bootstrap=40, random_seed=123
    )

    assert first == second


@pytest.mark.parametrize(
    "kwargs",
    [
        {"n_bootstrap": 0},
        {"n_bootstrap": 10},
        {"confidence_level": 1.0},
        {"confidence_level": 0.0},
        {"minimum_training_dates": 1},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    options = {
        "n_bootstrap": 40,
        **kwargs,
    }

    with pytest.raises(ValueError):
        estimate_phase_06_uncertainty(
            make_aggregates(),
            **options,
        )


def test_insufficient_training_data_returns_unavailable_intervals():
    result = estimate_phase_06_uncertainty(
        make_aggregates(),
        n_bootstrap=40,
        validation_fraction=0.80,
        minimum_training_pairs=1000,
    )

    assert result.calibration_uncertainties
    assert all(
        item.successful_replicates == 0
        for item in result.calibration_uncertainties
    )
    assert all(
        item.slope is None
        for item in result.calibration_uncertainties
    )

