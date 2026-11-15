from datetime import date
from types import SimpleNamespace

import pytest

from harmonization.v3.contracts.validation import (
    ActivityReferenceLabel,
    ReferenceCorrespondence,
)
from harmonization.v3.contracts.candidate import CandidatePair, Phase03Result
from harmonization.v3.contracts.activity import (
    ActivityThresholdExperiment,
    DailyActivityCluster,
    DailyActivityMembership,
    Phase04BResult,
)
from harmonization.v3.phases.phase_05_validation.validation_metrics import (
    classification_metrics,
)
from harmonization.v3.phases.phase_05_validation.candidate_validation import (
    validate_candidate_recall,
)
from harmonization.v3.phases.phase_05_validation.correspondence_validation import (
    validate_correspondence_decisions,
)
from harmonization.v3.phases.phase_05_validation.activity_validation import (
    validate_daily_activity,
)
from harmonization.v3.phases.phase_05_validation.threshold_evaluation import (
    compare_threshold_experiments,
)


def reference_pair(a="A", b="B"):
    return ReferenceCorrespondence(
        platform_a="MODIS_TERRA",
        detection_id_a=a,
        platform_b="VIIRS_NOAA20",
        detection_id_b=b,
    )


def reversed_reference_pair():
    """Same physical pair as reference_pair(), with endpoints reversed."""
    return ReferenceCorrespondence(
        platform_a="VIIRS_NOAA20",
        detection_id_a="B",
        platform_b="MODIS_TERRA",
        detection_id_b="A",
    )

def candidate(experiment_id, a="A", b="B"):
    return CandidatePair(
        candidate_id=f"{experiment_id}-{a}-{b}",
        experiment_id=experiment_id,
        detection_id_a=a,
        detection_id_b=b,
        platform_a="MODIS_TERRA",
        platform_b="VIIRS_NOAA20",
        platform_pair="MODIS_TERRA__VIIRS_NOAA20",
        time_difference_minutes=10.0,
        center_distance_km=0.4,
        time_threshold_minutes=15.0,
        distance_threshold_km=0.5,
    )


def test_classification_metrics_calculation():
    metrics = classification_metrics(8, 2, 2, 8)

    assert metrics.precision == pytest.approx(0.8)
    assert metrics.recall == pytest.approx(0.8)
    assert metrics.f1 == pytest.approx(0.8)
    assert metrics.specificity == pytest.approx(0.8)
    assert metrics.accuracy == pytest.approx(0.8)


def test_undefined_metric_denominators_return_none():
    metrics = classification_metrics(0, 0, 0, 0)

    assert metrics.precision is None
    assert metrics.recall is None
    assert metrics.f1 is None
    assert metrics.specificity is None
    assert metrics.accuracy is None


def test_negative_confusion_count_is_rejected():
    with pytest.raises(ValueError):
        classification_metrics(-1, 0, 0, 0)


def test_candidate_recall_is_calculated_per_experiment():
    experiments = (
        SimpleNamespace(
            experiment_id="E1",
            time_threshold_minutes=15.0,
            distance_threshold_km=0.5,
        ),
        SimpleNamespace(
            experiment_id="E2",
            time_threshold_minutes=30.0,
            distance_threshold_km=1.0,
        ),
    )
    phase03 = Phase03Result(
        experiments=experiments,
        candidates=(candidate("E1"), candidate("E2")),
        summaries=(),
    )

    references = (reference_pair(), reference_pair("C", "D"))

    results = validate_candidate_recall(phase03, references)
    by_id = {item.experiment_id: item for item in results}

    assert by_id["E1"].candidate_recall == pytest.approx(0.5)
    assert by_id["E2"].candidate_recall == pytest.approx(0.5)
    assert len(by_id["E1"].missed_reference_pairs) == 1


def test_candidate_recall_is_none_without_reference_pairs():
    phase03 = Phase03Result(
        experiments=(
            SimpleNamespace(
                experiment_id="E1",
                time_threshold_minutes=15.0,
                distance_threshold_km=0.5,
            ),
        ),
        candidates=(),
        summaries=(),
    )

    result = validate_candidate_recall(phase03, ())

    assert result[0].candidate_recall is None


def test_candidate_validation_rejects_duplicate_reference_pairs():
    phase03 = Phase03Result(experiments=(), candidates=(), summaries=())

    with pytest.raises(ValueError, match="Duplicate reference"):
        validate_candidate_recall(
            phase03,
            (reference_pair(), reversed_reference_pair()),
        )


def test_correspondence_decisions_are_compared_with_reference_labels():
    result = validate_correspondence_decisions(
        predicted_pairs=(reference_pair(), reference_pair("C", "D")),
        reference_pairs=(reference_pair(), reference_pair("E", "F")),
    )

    assert result.metrics.true_positive == 1
    assert result.metrics.false_positive == 1
    assert result.metrics.false_negative == 1
    assert result.metrics.precision == pytest.approx(0.5)
    assert result.metrics.recall == pytest.approx(0.5)
    # Specificity is deliberately undefined without a pair universe.
    assert result.metrics.specificity is None
    assert result.metrics.accuracy is None


def test_correspondence_validation_rejects_duplicate_predictions():
    with pytest.raises(ValueError, match="Duplicate predicted"):
        validate_correspondence_decisions(
            (reference_pair(), reversed_reference_pair()),
            (),
        )


def make_activity_result():
    experiment = ActivityThresholdExperiment("ACT_D0p5km", 0.5)

    clusters = (
        DailyActivityCluster(
            cluster_id="C1",
            experiment_id="ACT_D0p5km",
            activity_date_utc=date(2026, 1, 1),
            distance_threshold_km=0.5,
            member_count=2,
            member_keys=(("MODIS_TERRA", "A"), ("MODIS_TERRA", "B")),
            platform_counts=(("MODIS_TERRA", 2),),
            min_acquisition_time_utc=__import__("datetime").datetime(
                2026, 1, 1, 10, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            max_acquisition_time_utc=__import__("datetime").datetime(
                2026, 1, 1, 10, 5, tzinfo=__import__("datetime").timezone.utc
            ),
            maximum_edge_distance_km=0.2,
        ),
        DailyActivityCluster(
            cluster_id="C2",
            experiment_id="ACT_D0p5km",
            activity_date_utc=date(2026, 1, 1),
            distance_threshold_km=0.5,
            member_count=1,
            member_keys=(("MODIS_TERRA", "C"),),
            platform_counts=(("MODIS_TERRA", 1),),
            min_acquisition_time_utc=__import__("datetime").datetime(
                2026, 1, 1, 11, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            max_acquisition_time_utc=__import__("datetime").datetime(
                2026, 1, 1, 11, 0, tzinfo=__import__("datetime").timezone.utc
            ),
            maximum_edge_distance_km=0.0,
        ),
    )

    memberships = (
        DailyActivityMembership("ACT_D0p5km", "C1", "MODIS_TERRA", "A",
            clusters[0].min_acquisition_time_utc),
        DailyActivityMembership("ACT_D0p5km", "C1", "MODIS_TERRA", "B",
            clusters[0].max_acquisition_time_utc),
        DailyActivityMembership("ACT_D0p5km", "C2", "MODIS_TERRA", "C",
            clusters[1].min_acquisition_time_utc),
    )

    return Phase04BResult(
        experiments=(experiment,),
        clusters=clusters,
        memberships=memberships,
        summaries=(),
    )


def test_activity_validation_pairwise_grouping_metrics():
    result = make_activity_result()
    labels = (
        ActivityReferenceLabel("MODIS_TERRA", "A", date(2026, 1, 1), "FIRE_1"),
        ActivityReferenceLabel("MODIS_TERRA", "B", date(2026, 1, 1), "FIRE_1"),
        ActivityReferenceLabel("MODIS_TERRA", "C", date(2026, 1, 1), "FIRE_2"),
    )

    validation = validate_daily_activity(result, labels)[0]

    assert validation.labelled_detection_count == 3
    assert validation.metrics.true_positive == 1
    assert validation.metrics.false_positive == 0
    assert validation.metrics.false_negative == 0
    assert validation.metrics.true_negative == 2
    assert validation.metrics.f1 == 1.0


def test_activity_validation_detects_over_merging():
    result = make_activity_result()
    labels = (
        ActivityReferenceLabel("MODIS_TERRA", "A", date(2026, 1, 1), "FIRE_1"),
        ActivityReferenceLabel("MODIS_TERRA", "B", date(2026, 1, 1), "FIRE_2"),
        ActivityReferenceLabel("MODIS_TERRA", "C", date(2026, 1, 1), "FIRE_3"),
    )

    validation = validate_daily_activity(result, labels)[0]

    assert validation.metrics.false_positive == 1
    assert validation.metrics.precision == 0.0


def test_activity_validation_rejects_duplicate_labels():
    result = make_activity_result()
    label = ActivityReferenceLabel(
        "MODIS_TERRA", "A", date(2026, 1, 1), "FIRE_1"
    )

    with pytest.raises(ValueError, match="Duplicate activity reference"):
        validate_daily_activity(result, (label, label))


def test_activity_validation_ignores_unlabelled_detections_and_reports_count():
    result = make_activity_result()
    labels = (
        ActivityReferenceLabel("MODIS_TERRA", "A", date(2026, 1, 1), "FIRE_1"),
        ActivityReferenceLabel("MODIS_TERRA", "B", date(2026, 1, 1), "FIRE_1"),
    )

    validation = validate_daily_activity(result, labels)[0]

    assert validation.labelled_detection_count == 2
    assert validation.unlabelled_detection_count == 1


def test_threshold_comparison_does_not_select_a_winner():
    candidate_result = SimpleNamespace(
        experiment_id="T15_D0p5",
        time_threshold_minutes=15.0,
        distance_threshold_km=0.5,
        candidate_recall=0.9,
    )
    activity_result = SimpleNamespace(
        experiment_id="ACT_D0p5km",
        distance_threshold_km=0.5,
        metrics=SimpleNamespace(f1=0.8),
    )

    comparisons = compare_threshold_experiments(
        candidate_results=(candidate_result,),
        activity_results=(activity_result,),
    )

    assert len(comparisons) == 2
    assert all(item.selected is False for item in comparisons)
    assert {item.validation_type for item in comparisons} == {
        "candidate_recall",
        "daily_activity_pairwise_f1",
    }

