from datetime import date, timedelta

import pytest

from harmonization.v3.contracts.frp import SensorFRPAggregate
from harmonization.v3.phases.phase_06_common_support_frp.conditional_calibration import (
    evaluate_conditional_calibrations,
)


def make_aggregate(platform, frp, day, support_id):
    return SensorFRPAggregate(
        support_unit_id=support_id,
        spatial_cell_id="cell-" + support_id,
        temporal_group_id="time-" + support_id,
        support_date_utc=day,
        platform=platform,
        observation_count=1,
        frp_mean_mw=frp,
        frp_median_mw=frp,
        frp_min_mw=frp,
        frp_max_mw=frp,
    )


def make_linear_dataset(number_of_days=30):
    aggregates = []
    start = date(2025, 1, 1)

    for index in range(number_of_days):
        day = start + timedelta(days=index)
        support_id = f"unit-{index:03d}"
        reference_frp = 20.0 + index * 5.0
        target_frp = 1.2 * reference_frp + 5.0

        aggregates.extend([
            make_aggregate("MODIS_TERRA", reference_frp, day, support_id),
            make_aggregate("MODIS_AQUA", target_frp, day, support_id),
        ])

    return aggregates


def pair_results(results):
    return {
        result.method: result
        for result in results
        if result.platform_reference == "MODIS_TERRA"
        and result.platform_target == "MODIS_AQUA"
    }


def test_returns_identity_and_three_fitted_models_for_each_pair():
    results = evaluate_conditional_calibrations(make_linear_dataset())

    assert len(results) == 6 * 4

    methods = {
        result.method for result in results
    }

    assert methods == {"identity", "multiplicative", "affine", "robust_affine"}


def test_chronological_split_holds_out_later_dates():
    results = pair_results(evaluate_conditional_calibrations(make_linear_dataset()))

    identity = results["identity"]

    assert identity.training_count == 24
    assert identity.validation_count == 6


def test_affine_model_recovers_synthetic_relationship():
    results = pair_results(evaluate_conditional_calibrations(make_linear_dataset()))
    affine = results["affine"]

    assert affine.slope == pytest.approx(1.2)
    assert affine.intercept_mw == pytest.approx(5.0)
    assert affine.accepted is True


def test_identity_baseline_is_always_retained():
    results = pair_results(evaluate_conditional_calibrations(make_linear_dataset()))
    identity = results["identity"]

    assert identity.slope == 1.0
    assert identity.intercept_mw == 0.0
    assert identity.accepted is True


def test_fitted_models_are_rejected_when_sample_requirements_fail():
    aggregates = make_linear_dataset(number_of_days=4)

    results = pair_results(
        evaluate_conditional_calibrations(
            aggregates,
            minimum_training_pairs=20,
            minimum_validation_pairs=5,
        )
    )

    for method in ("multiplicative", "affine", "robust_affine"):
        assert results[method].accepted is False
        assert results[method].rejection_reasons


def test_pairs_are_created_only_for_identical_support_units():
    day = date(2025, 1, 1)
    aggregates = [
        make_aggregate("MODIS_TERRA", 100.0, day, "unit-a"),
        make_aggregate("MODIS_AQUA", 120.0, day, "unit-b"),
    ]

    results = pair_results(
        evaluate_conditional_calibrations(
            aggregates,
            minimum_training_pairs=1,
            minimum_validation_pairs=1,
            minimum_training_dates=1,
        )
    )

    assert results["identity"].training_count == 0
    assert results["identity"].validation_count == 0


def test_duplicate_sensor_aggregate_is_rejected():
    day = date(2025, 1, 1)
    aggregates = [
        make_aggregate("MODIS_TERRA", 100.0, day, "unit-a"),
        make_aggregate("MODIS_TERRA", 110.0, day, "unit-a"),
    ]

    with pytest.raises(ValueError, match="Duplicate aggregate identity"):
        evaluate_conditional_calibrations(aggregates)


def test_invalid_frp_is_rejected():
    day = date(2025, 1, 1)
    aggregates = [
        make_aggregate("MODIS_TERRA", float("nan"), day, "unit-a"),
    ]

    with pytest.raises(ValueError, match="Invalid mean FRP"):
        evaluate_conditional_calibrations(aggregates)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"validation_fraction": 0},
        {"validation_fraction": 1},
        {"minimum_training_pairs": 0},
        {"minimum_validation_pairs": 0},
        {"minimum_training_dates": 0},
        {"minimum_rmse_improvement": 1},
        {"maximum_mae_degradation": -0.1},
    ],
)
def test_invalid_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        evaluate_conditional_calibrations([], **kwargs)


def test_no_calibration_model_is_selected_automatically():
    results = pair_results(evaluate_conditional_calibrations(make_linear_dataset()))

    assert "accepted" in results["affine"].__dataclass_fields__
    assert all(
        result.method in {"identity", "multiplicative", "affine", "robust_affine"}
        for result in results.values()
    )
