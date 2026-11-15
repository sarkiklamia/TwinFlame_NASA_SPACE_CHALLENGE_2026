from harmonization.v3.contracts.validation import BinaryClassificationMetrics


def _ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


def classification_metrics(
    true_positive,
    false_positive,
    false_negative,
    true_negative,
):
    required_counts = (
        true_positive,
        false_positive,
        false_negative,
    )

    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in required_counts
    ):
        raise ValueError("Confusion-matrix counts must be non-negative integers")

    if true_negative is not None and (
        not isinstance(true_negative, int)
        or isinstance(true_negative, bool)
        or true_negative < 0
    ):
        raise ValueError("true_negative must be a non-negative integer or None")

    precision = _ratio(
        true_positive,
        true_positive + false_positive,
    )
    recall = _ratio(
        true_positive,
        true_positive + false_negative,
    )

    specificity = (
        _ratio(true_negative, true_negative + false_positive)
        if true_negative is not None
        else None
    )

    accuracy = (
        _ratio(
            true_positive + true_negative,
            true_positive + false_positive + false_negative + true_negative,
        )
        if true_negative is not None
        else None
    )

    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return BinaryClassificationMetrics(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        precision=precision,
        recall=recall,
        f1=f1,
        specificity=specificity,
        accuracy=accuracy,
    )
