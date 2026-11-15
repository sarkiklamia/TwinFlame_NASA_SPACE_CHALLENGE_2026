import math
import random
from collections import defaultdict
from datetime import date

from ...contracts.uncertainty import (
    BootstrapInterval,
    CalibrationUncertainty,
    FRPComparisonUncertainty,
    Phase06UncertaintyResult,
)
from .conditional_calibration import (
    DEFAULT_VALIDATION_FRACTION,
    _calculate_metrics,
    _collect_pair_samples,
    _fit_model,
    _split_by_date,
)
from .frp_comparison import CROSS_PLATFORM_PAIRS


CALIBRATION_METHODS = ("multiplicative", "affine", "robust_affine")


def _validate_options(n_bootstrap, confidence_level, random_seed):
    if (
        not isinstance(n_bootstrap, int)
        or isinstance(n_bootstrap, bool)
        or n_bootstrap < 20
    ):
        raise ValueError("n_bootstrap must be an integer >= 20")

    if (
        not math.isfinite(confidence_level)
        or not 0 < confidence_level < 1
    ):
        raise ValueError("confidence_level must be between 0 and 1")

    if not isinstance(random_seed, int) or isinstance(random_seed, bool):
        raise ValueError("random_seed must be an integer")


def _percentile(values, probability):
    ordered = sorted(values)

    if not ordered:
        raise ValueError("Cannot calculate percentile from empty values")

    position = (len(ordered) - 1) * probability
    lower_index = math.floor(position)
    upper_index = math.ceil(position)

    if lower_index == upper_index:
        return float(ordered[lower_index])

    fraction = position - lower_index
    return float(
        ordered[lower_index] * (1.0 - fraction)
        + ordered[upper_index] * fraction
    )


def _make_interval(estimate, values, confidence_level):
    if not values:
        return None

    tail = (1.0 - confidence_level) / 2.0

    return BootstrapInterval(
        estimate=float(estimate),
        lower=_percentile(values, tail),
        upper=_percentile(values, 1.0 - tail),
        confidence_level=float(confidence_level),
        successful_replicates=len(values),
    )


def _group_by_date(samples):
    grouped = defaultdict(list)

    for sample in samples:
        grouped[sample[0]].append(sample)

    return dict(grouped)


def _resample_date_blocks(grouped, rng):
    dates = sorted(grouped)

    if not dates:
        return ()

    sampled_dates = [
        rng.choice(dates)
        for _ in range(len(dates))
    ]

    return tuple(
        sample
        for sampled_date in sampled_dates
        for sample in grouped[sampled_date]
    )


def _metric_values(observed, predicted):
    return dict(_calculate_metrics(observed, predicted))


def _calibration_uncertainty(
    samples,
    platform_reference,
    platform_target,
    method,
    validation_fraction,
    n_bootstrap,
    confidence_level,
    rng,
    minimum_training_pairs,
    minimum_training_dates,
):
    training, validation = _split_by_date(samples, validation_fraction)

    training_dates = {sample[0] for sample in training}
    validation_dates = {sample[0] for sample in validation}

    if (
        len(training) < minimum_training_pairs
        or len(training_dates) < minimum_training_dates
        or not validation
        or not validation_dates
    ):
        return CalibrationUncertainty(
            platform_reference=platform_reference,
            platform_target=platform_target,
            method=method,
            intercept_mw=None,
            slope=None,
            validation_bias_mw=None,
            validation_mae_mw=None,
            validation_rmse_mw=None,
            successful_replicates=0,
            rejected_replicates=n_bootstrap,
            training_date_count=len(training_dates),
            validation_date_count=len(validation_dates),
        )

    x_train = [sample[2] for sample in training]
    y_train = [sample[3] for sample in training]
    x_valid = [sample[2] for sample in validation]
    y_valid = [sample[3] for sample in validation]

    try:
        point_intercept, point_slope = _fit_model(
            method, x_train, y_train
        )
        point_predictions = [
            point_intercept + point_slope * value
            for value in x_valid
        ]
        if (
            point_slope <= 0
            or any(not math.isfinite(v) or v < 0 for v in point_predictions)
        ):
            raise ValueError("Invalid full-sample calibration model")
        point_metrics = _metric_values(y_valid, point_predictions)
    except (ValueError, ArithmeticError, OverflowError):
        return CalibrationUncertainty(
            platform_reference=platform_reference,
            platform_target=platform_target,
            method=method,
            intercept_mw=None,
            slope=None,
            validation_bias_mw=None,
            validation_mae_mw=None,
            validation_rmse_mw=None,
            successful_replicates=0,
            rejected_replicates=n_bootstrap,
            training_date_count=len(training_dates),
            validation_date_count=len(validation_dates),
        )

    train_blocks = _group_by_date(training)
    valid_blocks = _group_by_date(validation)

    intercepts = []
    slopes = []
    biases = []
    maes = []
    rmses = []
    rejected = 0

    for _ in range(n_bootstrap):
        sampled_training = _resample_date_blocks(train_blocks, rng)
        sampled_validation = _resample_date_blocks(valid_blocks, rng)

        try:
            x_boot = [sample[2] for sample in sampled_training]
            y_boot = [sample[3] for sample in sampled_training]
            intercept, slope = _fit_model(method, x_boot, y_boot)

            if slope <= 0:
                raise ValueError("Non-positive bootstrap slope")

            x_test = [sample[2] for sample in sampled_validation]
            y_test = [sample[3] for sample in sampled_validation]
            predictions = [
                intercept + slope * value for value in x_test
            ]

            if any(
                not math.isfinite(value) or value < 0
                for value in predictions
            ):
                raise ValueError("Invalid bootstrap prediction")

            metrics = _metric_values(y_test, predictions)

            intercepts.append(float(intercept))
            slopes.append(float(slope))
            biases.append(metrics["bias_mw"])
            maes.append(metrics["mae_mw"])
            rmses.append(metrics["rmse_mw"])

        except (ValueError, ArithmeticError, OverflowError):
            rejected += 1

    return CalibrationUncertainty(
        platform_reference=platform_reference,
        platform_target=platform_target,
        method=method,
        intercept_mw=_make_interval(
            point_intercept, intercepts, confidence_level
        ),
        slope=_make_interval(point_slope, slopes, confidence_level),
        validation_bias_mw=_make_interval(
            point_metrics["bias_mw"], biases, confidence_level
        ),
        validation_mae_mw=_make_interval(
            point_metrics["mae_mw"], maes, confidence_level
        ),
        validation_rmse_mw=_make_interval(
            point_metrics["rmse_mw"], rmses, confidence_level
        ),
        successful_replicates=len(intercepts),
        rejected_replicates=rejected,
        training_date_count=len(training_dates),
        validation_date_count=len(validation_dates),
    )


def _comparison_uncertainty(
    sensor_aggregates,
    platform_a,
    platform_b,
    n_bootstrap,
    confidence_level,
    rng,
):
    index = {}
    dates_by_support = {}

    for aggregate in sensor_aggregates:
        key = (aggregate.support_unit_id, aggregate.platform)
        if key in index:
            raise ValueError(f"Duplicate sensor aggregate: {key}")

        value = aggregate.frp_mean_mw
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"Invalid FRP aggregate: {key}")

        if not isinstance(aggregate.support_date_utc, date):
            raise ValueError(f"Invalid support date: {key}")

        index[key] = float(value)
        dates_by_support[key] = aggregate.support_date_utc

    paired = []

    support_ids = sorted({
        support_id for support_id, _ in index
    })

    for support_id in support_ids:
        key_a = (support_id, platform_a)
        key_b = (support_id, platform_b)

        if key_a not in index or key_b not in index:
            continue

        date_a = dates_by_support[key_a]
        date_b = dates_by_support[key_b]

        if date_a != date_b:
            raise ValueError(
                f"Support unit {support_id} has inconsistent dates"
            )

        frp_a = index[key_a]
        frp_b = index[key_b]
        difference = frp_b - frp_a
        denominator = abs(frp_a) + abs(frp_b)
        relative = (
            2.0 * difference / denominator
            if denominator > 0
            else None
        )

        paired.append((date_a, difference, relative))

    if not paired:
        return None

    grouped = defaultdict(list)
    for sample in paired:
        grouped[sample[0]].append(sample)

    point_differences = [sample[1] for sample in paired]
    point_relatives = [
        sample[2] for sample in paired if sample[2] is not None
    ]

    difference_estimate = sum(point_differences) / len(point_differences)
    relative_estimate = (
        sum(point_relatives) / len(point_relatives)
        if point_relatives
        else None
    )

    bootstrap_differences = []
    bootstrap_relatives = []

    for _ in range(n_bootstrap):
        sampled = _resample_date_blocks(grouped, rng)
        differences = [sample[1] for sample in sampled]
        relatives = [
            sample[2] for sample in sampled if sample[2] is not None
        ]

        if differences:
            bootstrap_differences.append(
                sum(differences) / len(differences)
            )

        if relatives:
            bootstrap_relatives.append(
                sum(relatives) / len(relatives)
            )

    return FRPComparisonUncertainty(
        platform_a=platform_a,
        platform_b=platform_b,
        mean_difference_mw=_make_interval(
            difference_estimate,
            bootstrap_differences,
            confidence_level,
        ),
        mean_relative_difference=(
            _make_interval(
                relative_estimate,
                bootstrap_relatives,
                confidence_level,
            )
            if relative_estimate is not None
            else None
        ),
        support_unit_count=len(paired),
        date_count=len(grouped),
    )


def estimate_phase_06_uncertainty(
    sensor_aggregates,
    n_bootstrap=1000,
    confidence_level=0.95,
    random_seed=42,
    validation_fraction=DEFAULT_VALIDATION_FRACTION,
    minimum_training_pairs=20,
    minimum_training_dates=3,
):
    """
    Estimate Phase 6 uncertainty using UTC-date block bootstrap.

    Calibration coefficients are refitted on bootstrap samples of training
    dates. Validation dates are independently block-resampled for held-out
    metric intervals. FRP comparison intervals resample complete date blocks.

    This estimates sampling variability across observed dates. It does not
    account for systematic geolocation, footprint, retrieval, or reference
    data errors, and it does not make dates independent fire episodes.
    """
    _validate_options(n_bootstrap, confidence_level, random_seed)

    if not math.isfinite(validation_fraction) or not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")

    if (
        not isinstance(minimum_training_pairs, int)
        or isinstance(minimum_training_pairs, bool)
        or minimum_training_pairs < 1
    ):
        raise ValueError("minimum_training_pairs must be positive")

    if (
        not isinstance(minimum_training_dates, int)
        or isinstance(minimum_training_dates, bool)
        or minimum_training_dates < 2
    ):
        raise ValueError("minimum_training_dates must be >= 2")

    aggregates = tuple(sensor_aggregates)
    rng = random.Random(random_seed)

    calibration_results = []

    for platform_reference, platform_target in CROSS_PLATFORM_PAIRS:
        samples = _collect_pair_samples(
            aggregates, platform_reference, platform_target
        )

        for method in CALIBRATION_METHODS:
            calibration_results.append(
                _calibration_uncertainty(
                    samples,
                    platform_reference,
                    platform_target,
                    method,
                    validation_fraction,
                    n_bootstrap,
                    confidence_level,
                    rng,
                    minimum_training_pairs,
                    minimum_training_dates,
                )
            )

    comparison_results = []

    for platform_a, platform_b in CROSS_PLATFORM_PAIRS:
        result = _comparison_uncertainty(
            aggregates,
            platform_a,
            platform_b,
            n_bootstrap,
            confidence_level,
            rng,
        )
        if result is not None:
            comparison_results.append(result)

    warnings = (
        "Intervals quantify date-block sampling variability, not systematic sensor uncertainty.",
        "Date blocks may not be independent when the same fire episode spans multiple dates.",
        "Calibration intervals are directional and do not establish either sensor as ground truth.",
        "Bootstrap intervals do not automatically approve or select a calibration model.",
    )

    return Phase06UncertaintyResult(
        calibration_uncertainties=tuple(calibration_results),
        comparison_uncertainties=tuple(comparison_results),
        warnings=warnings,
    )
