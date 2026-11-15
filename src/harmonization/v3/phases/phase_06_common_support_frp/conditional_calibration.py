import math
from datetime import date
from statistics import median

from ...contracts.frp import CalibrationResult
from .frp_comparison import CROSS_PLATFORM_PAIRS


DEFAULT_VALIDATION_FRACTION = 0.20
DEFAULT_MIN_TRAINING_PAIRS = 20
DEFAULT_MIN_VALIDATION_PAIRS = 5
DEFAULT_MIN_TRAINING_DATES = 3
DEFAULT_MIN_RMSE_IMPROVEMENT = 0.02
DEFAULT_MAX_MAE_DEGRADATION = 0.02


def _validate_configuration(
    validation_fraction,
    minimum_training_pairs,
    minimum_validation_pairs,
    minimum_training_dates,
    minimum_rmse_improvement,
    maximum_mae_degradation,
):
    if not math.isfinite(validation_fraction) or not 0 < validation_fraction < 1:
        raise ValueError("validation_fraction must be between 0 and 1")

    for name, value in (
        ("minimum_training_pairs", minimum_training_pairs),
        ("minimum_validation_pairs", minimum_validation_pairs),
        ("minimum_training_dates", minimum_training_dates),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    if not math.isfinite(minimum_rmse_improvement) or not 0 <= minimum_rmse_improvement < 1:
        raise ValueError("minimum_rmse_improvement must be in [0, 1)")

    if not math.isfinite(maximum_mae_degradation) or maximum_mae_degradation < 0:
        raise ValueError("maximum_mae_degradation must be finite and non-negative")


def _collect_pair_samples(sensor_aggregates, platform_reference, platform_target):
    aggregates = tuple(sensor_aggregates)
    index = {}
    support_dates = {}

    supported_platforms = {
        platform
        for pair in CROSS_PLATFORM_PAIRS
        for platform in pair
    }

    for aggregate in aggregates:
        platform = aggregate.platform
        support_id = aggregate.support_unit_id
        identity = (support_id, platform)

        if platform not in supported_platforms:
            raise ValueError(f"Unsupported platform: {platform}")

        if identity in index:
            raise ValueError(f"Duplicate aggregate identity: {identity}")

        value = aggregate.frp_mean_mw
        try:
            valid = math.isfinite(value) and value >= 0
        except (TypeError, ValueError):
            valid = False

        if not valid:
            raise ValueError(f"Invalid mean FRP for {identity}")

        if not isinstance(aggregate.support_date_utc, date):
            raise ValueError(f"Invalid UTC support date for {identity}")

        index[identity] = float(value)
        support_dates[identity] = aggregate.support_date_utc

    samples = []

    for support_id in sorted({key[0] for key in index}):
        key_a = (support_id, platform_reference)
        key_b = (support_id, platform_target)

        if key_a not in index or key_b not in index:
            continue

        date_a = support_dates[key_a]
        date_b = support_dates[key_b]

        if date_a != date_b:
            raise ValueError(
                f"Support unit {support_id} has inconsistent UTC dates"
            )

        # x = reference sensor; y = target sensor.
        samples.append((date_a, support_id, index[key_a], index[key_b]))

    return tuple(sorted(samples, key=lambda item: (item[0], item[1])))


def _split_by_date(samples, validation_fraction):
    dates = sorted({sample[0] for sample in samples})

    if len(dates) < 2:
        return (), samples

    validation_date_count = max(1, math.ceil(len(dates) * validation_fraction))
    validation_date_set = set(dates[-validation_date_count:])

    training = tuple(sample for sample in samples if sample[0] not in validation_date_set)
    validation = tuple(sample for sample in samples if sample[0] in validation_date_set)

    return training, validation


def _weighted_affine_fit(x_values, y_values, weights):
    total_weight = sum(weights)

    if total_weight <= 0:
        raise ValueError("Regression weights must have a positive sum")

    mean_x = sum(w * x for x, w in zip(x_values, weights)) / total_weight
    mean_y = sum(w * y for y, w in zip(y_values, weights)) / total_weight

    denominator = sum(
        w * (x - mean_x) ** 2
        for x, w in zip(x_values, weights)
    )

    if denominator <= 1e-12:
        raise ValueError("Insufficient variation in reference FRP")

    numerator = sum(
        w * (x - mean_x) * (y - mean_y)
        for x, y, w in zip(x_values, y_values, weights)
    )

    slope = numerator / denominator
    intercept = mean_y - slope * mean_x

    if not math.isfinite(slope) or not math.isfinite(intercept):
        raise ValueError("Regression produced non-finite coefficients")

    return intercept, slope


def _fit_model(method, x_values, y_values):
    if not x_values or len(x_values) != len(y_values):
        raise ValueError("Training data is empty or inconsistent")

    if method == "multiplicative":
        denominator = sum(x * x for x in x_values)

        if denominator <= 1e-12:
            raise ValueError("Multiplicative fit requires non-zero reference FRP")

        slope = sum(x * y for x, y in zip(x_values, y_values)) / denominator

        if not math.isfinite(slope):
            raise ValueError("Multiplicative fit produced a non-finite slope")

        return 0.0, slope

    if method == "affine":
        return _weighted_affine_fit(
            x_values,
            y_values,
            [1.0] * len(x_values),
        )

    if method == "robust_affine":
        weights = [1.0] * len(x_values)
        intercept, slope = _weighted_affine_fit(x_values, y_values, weights)

        # Huber IRLS: iteratively reduce the influence of large residuals.
        for _ in range(50):
            residuals = [
                y - (intercept + slope * x)
                for x, y in zip(x_values, y_values)
            ]

            residual_center = median(residuals)
            mad = median([abs(r - residual_center) for r in residuals])
            scale = 1.4826 * mad

            if scale <= 1e-12:
                break

            cutoff = 1.345 * scale
            new_weights = []

            for residual in residuals:
                absolute_residual = abs(residual - residual_center)
                weight = (
                    1.0
                    if absolute_residual <= cutoff
                    else cutoff / absolute_residual
                )
                new_weights.append(weight)

            new_intercept, new_slope = _weighted_affine_fit(
                x_values,
                y_values,
                new_weights,
            )

            change = max(
                abs(new_intercept - intercept),
                abs(new_slope - slope),
            )

            intercept, slope = new_intercept, new_slope
            weights = new_weights

            if change <= 1e-10:
                break

        return intercept, slope

    raise ValueError(f"Unknown calibration method: {method}")


def _calculate_metrics(observed, predicted):
    errors = [prediction - actual for actual, prediction in zip(observed, predicted)]

    return (
        ("bias_mw", sum(errors) / len(errors)),
        ("mae_mw", sum(abs(error) for error in errors) / len(errors)),
        ("rmse_mw", math.sqrt(sum(error * error for error in errors) / len(errors))),
    )


def _make_result(
    platform_reference,
    platform_target,
    method,
    intercept,
    slope,
    training_count,
    validation_count,
    metrics,
    accepted,
    rejection_reasons,
):
    return CalibrationResult(
        platform_reference=platform_reference,
        platform_target=platform_target,
        method=method,
        intercept_mw=float(intercept),
        slope=float(slope),
        training_count=training_count,
        validation_count=validation_count,
        validation_metrics=tuple(metrics),
        accepted=accepted,
        rejection_reasons=tuple(rejection_reasons),
    )


def _evaluate_pair(
    samples,
    platform_reference,
    platform_target,
    validation_fraction,
    minimum_training_pairs,
    minimum_validation_pairs,
    minimum_training_dates,
    minimum_rmse_improvement,
    maximum_mae_degradation,
):
    training, validation = _split_by_date(samples, validation_fraction)

    training_dates = {sample[0] for sample in training}
    validation_dates = {sample[0] for sample in validation}

    x_validation = [sample[2] for sample in validation]
    y_validation = [sample[3] for sample in validation]

    baseline_predictions = list(x_validation)
    baseline_metrics = (
        _calculate_metrics(y_validation, baseline_predictions)
        if validation
        else ()
    )

    # Identity is the no-adjustment baseline, never a fitted model.
    results = [
        _make_result(
            platform_reference,
            platform_target,
            "identity",
            0.0,
            1.0,
            len(training),
            len(validation),
            baseline_metrics,
            True,
            (),
        )
    ]

    insufficient_reasons = []

    if len(training) < minimum_training_pairs:
        insufficient_reasons.append("insufficient_training_pairs")

    if len(validation) < minimum_validation_pairs:
        insufficient_reasons.append("insufficient_validation_pairs")

    if len(training_dates) < minimum_training_dates:
        insufficient_reasons.append("insufficient_distinct_training_dates")

    if not validation_dates:
        insufficient_reasons.append("no_independent_validation_dates")

    x_training = [sample[2] for sample in training]
    y_training = [sample[3] for sample in training]

    for method in ("multiplicative", "affine", "robust_affine"):
        if insufficient_reasons:
            results.append(
                _make_result(
                    platform_reference,
                    platform_target,
                    method,
                    0.0,
                    1.0,
                    len(training),
                    len(validation),
                    (),
                    False,
                    insufficient_reasons,
                )
            )
            continue

        try:
            intercept, slope = _fit_model(method, x_training, y_training)

            if slope <= 0:
                raise ValueError("non_positive_calibration_slope")

            predictions = [
                intercept + slope * value
                for value in x_validation
            ]

            if any(not math.isfinite(value) for value in predictions):
                raise ValueError("non_finite_validation_prediction")

            if any(value < 0 for value in predictions):
                raise ValueError("negative_validation_prediction")

            metrics = _calculate_metrics(y_validation, predictions)
            metric_values = dict(metrics)
            baseline_values = dict(baseline_metrics)

            baseline_rmse = baseline_values["rmse_mw"]
            model_rmse = metric_values["rmse_mw"]
            baseline_mae = baseline_values["mae_mw"]
            model_mae = metric_values["mae_mw"]

            reasons = []

            if baseline_rmse <= 1e-12:
                reasons.append("identity_baseline_has_zero_rmse")
            elif model_rmse > baseline_rmse * (1 - minimum_rmse_improvement):
                reasons.append("insufficient_held_out_rmse_improvement")

            if model_mae > baseline_mae * (1 + maximum_mae_degradation) + 1e-12:
                reasons.append("held_out_mae_degradation_exceeds_limit")

            results.append(
                _make_result(
                    platform_reference,
                    platform_target,
                    method,
                    intercept,
                    slope,
                    len(training),
                    len(validation),
                    metrics,
                    not reasons,
                    reasons,
                )
            )

        except (ValueError, ArithmeticError, OverflowError) as exc:
            results.append(
                _make_result(
                    platform_reference,
                    platform_target,
                    method,
                    0.0,
                    1.0,
                    len(training),
                    len(validation),
                    (),
                    False,
                    (str(exc),),
                )
            )

    return tuple(results)


def evaluate_conditional_calibrations(
    sensor_aggregates,
    validation_fraction=DEFAULT_VALIDATION_FRACTION,
    minimum_training_pairs=DEFAULT_MIN_TRAINING_PAIRS,
    minimum_validation_pairs=DEFAULT_MIN_VALIDATION_PAIRS,
    minimum_training_dates=DEFAULT_MIN_TRAINING_DATES,
    minimum_rmse_improvement=DEFAULT_MIN_RMSE_IMPROVEMENT,
    maximum_mae_degradation=DEFAULT_MAX_MAE_DEGRADATION,
):
    """
    Evaluate directional FRP calibration models for all six configured pairs.

    The first platform in each pair is the reference (x); the second is
    the target (y). Samples are paired only by identical common-support ID.

    Dates are split chronologically. The latest dates are held out.
    Calibration coefficients are fitted using training dates only.

    The identity result represents no adjustment and is retained as the
    baseline. Fitted models are accepted only when they meet sample
    requirements and improve held-out metrics according to the configured
    criteria.

    This function evaluates models; it does not select a single winner
    or alter the original sensor FRP aggregates.
    """
    _validate_configuration(
        validation_fraction,
        minimum_training_pairs,
        minimum_validation_pairs,
        minimum_training_dates,
        minimum_rmse_improvement,
        maximum_mae_degradation,
    )

    aggregates = tuple(sensor_aggregates)
    results = []

    for platform_reference, platform_target in CROSS_PLATFORM_PAIRS:
        samples = _collect_pair_samples(
            aggregates,
            platform_reference,
            platform_target,
        )

        results.extend(
            _evaluate_pair(
                samples,
                platform_reference,
                platform_target,
                validation_fraction,
                minimum_training_pairs,
                minimum_validation_pairs,
                minimum_training_dates,
                minimum_rmse_improvement,
                maximum_mae_degradation,
            )
        )

    return tuple(results)

