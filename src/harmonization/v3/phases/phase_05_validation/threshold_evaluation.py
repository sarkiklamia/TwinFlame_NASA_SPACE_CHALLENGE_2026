from harmonization.v3.contracts.validation import ThresholdComparison


def compare_threshold_experiments(
    candidate_results=(),
    activity_results=(),
):
    """
    Produce transparent metric rows for threshold comparison.

    Candidate recall and activity clustering metrics are different objectives.
    They are not combined into one score, and this function never selects
    a winning threshold automatically.
    """
    comparisons = []

    for result in candidate_results:
        comparisons.append(
            ThresholdComparison(
                validation_type="candidate_recall",
                experiment_id=result.experiment_id,
                time_threshold_minutes=result.time_threshold_minutes,
                distance_threshold_km=result.distance_threshold_km,
                metric_name="candidate_recall",
                metric_value=result.candidate_recall,
                selected=False,
            )
        )

    for result in activity_results:
        comparisons.append(
            ThresholdComparison(
                validation_type="daily_activity_pairwise_f1",
                experiment_id=result.experiment_id,
                time_threshold_minutes=None,
                distance_threshold_km=result.distance_threshold_km,
                metric_name="f1",
                metric_value=result.metrics.f1,
                selected=False,
            )
        )

    return tuple(
        sorted(
            comparisons,
            key=lambda item: (
                item.validation_type,
                item.distance_threshold_km,
                item.time_threshold_minutes or 0.0,
                item.experiment_id,
            ),
        )
    )
