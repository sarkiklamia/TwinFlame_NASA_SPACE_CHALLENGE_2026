from collections import Counter, defaultdict
from math import comb

from harmonization.v3.contracts.validation import (
    ActivityReferenceLabel,
    ActivityValidationResult,
)
from harmonization.v3.phases.phase_05_validation.validation_metrics import (
    classification_metrics,
)


def validate_daily_activity(phase04b_result, reference_labels):
    """
    Compare daily cluster co-membership with independent activity labels.

    Pairwise metrics are calculated only among detections with reference labels.
    Comparisons are restricted to the same UTC date.

    This is a pairwise grouping assessment, not proof that a cluster is a
    physically distinct fire event.
    """
    labels = tuple(reference_labels)
    label_by_identity = {}

    for label in labels:
        if not isinstance(label, ActivityReferenceLabel):
            raise TypeError("reference_labels must contain ActivityReferenceLabel objects")
        if not label.activity_id:
            raise ValueError("Reference activity_id must not be empty")

        identity = (str(label.platform), str(label.detection_id))
        if identity in label_by_identity:
            raise ValueError(f"Duplicate activity reference label: {identity}")

        label_by_identity[identity] = label

    results = []

    for experiment in phase04b_result.experiments:
        clusters = {
            cluster.cluster_id: cluster
            for cluster in phase04b_result.clusters
            if cluster.experiment_id == experiment.experiment_id
        }

        membership_by_identity = {}
        for membership in phase04b_result.memberships:
            if membership.experiment_id != experiment.experiment_id:
                continue

            identity = (membership.platform, membership.detection_id)
            if identity in membership_by_identity:
                raise ValueError(
                    f"Duplicate activity membership in experiment "
                    f"{experiment.experiment_id}: {identity}"
                )

            membership_by_identity[identity] = membership

        # Only compare reference-labelled detections actually present
        # in this experiment's cluster output.
        common = []
        for identity, label in label_by_identity.items():
            membership = membership_by_identity.get(identity)
            if membership is None:
                continue

            cluster = clusters.get(membership.cluster_id)
            if cluster is None:
                raise ValueError(
                    f"Membership references unknown cluster: {membership.cluster_id}"
                )

            if cluster.activity_date_utc != label.activity_date_utc:
                raise ValueError(
                    f"Reference date disagrees with UTC cluster date for {identity}"
                )

            common.append((
                label.activity_date_utc,
                label.activity_id,
                membership.cluster_id,
            ))

        # Contingency counts per date:
        # actual group = (date, activity_id)
        # predicted group = (date, cluster_id)
        actual_counts = Counter()
        predicted_counts = Counter()
        intersection_counts = Counter()
        date_counts = Counter()

        for activity_date, activity_id, cluster_id in common:
            actual_counts[(activity_date, activity_id)] += 1
            predicted_counts[(activity_date, cluster_id)] += 1
            intersection_counts[(activity_date, activity_id, cluster_id)] += 1
            date_counts[activity_date] += 1

        tp = sum(
            comb(count, 2)
            for count in intersection_counts.values()
            if count >= 2
        )
        predicted_positive = sum(
            comb(count, 2)
            for count in predicted_counts.values()
            if count >= 2
        )
        actual_positive = sum(
            comb(count, 2)
            for count in actual_counts.values()
            if count >= 2
        )
        total_pairs = sum(
            comb(count, 2)
            for count in date_counts.values()
            if count >= 2
        )

        fp = predicted_positive - tp
        fn = actual_positive - tp
        tn = total_pairs - tp - fp - fn

        metrics = classification_metrics(tp, fp, fn, tn)

        results.append(
            ActivityValidationResult(
                experiment_id=experiment.experiment_id,
                distance_threshold_km=experiment.distance_threshold_km,
                labelled_detection_count=len(common),
                unlabelled_detection_count=(
                    len(membership_by_identity) - len(common)
                ),
                metrics=metrics,
            )
        )

    return tuple(results)
