from harmonization.v3.contracts.validation import (
    CorrespondenceValidationResult,
    ReferenceCorrespondence,
)
from harmonization.v3.phases.phase_05_validation.candidate_validation import (
    _reference_key,
)
from harmonization.v3.phases.phase_05_validation.validation_metrics import (
    classification_metrics,
)


def validate_correspondence_decisions(
    predicted_pairs,
    reference_pairs,
):
    """
    Evaluate actual binary correspondence decisions against independent labels.

    predicted_pairs must contain ReferenceCorrespondence objects representing
    pairs explicitly classified as matches by a future decision stage.

    Phase 4A output is deliberately not accepted as predicted matches:
    Phase 4A evaluates candidate evidence but does not classify matches.
    """
    predicted = tuple(predicted_pairs)
    references = tuple(reference_pairs)

    predicted_keys = set()
    for item in predicted:
        if not isinstance(item, ReferenceCorrespondence):
            raise TypeError("predicted_pairs must contain ReferenceCorrespondence objects")
        key = _reference_key(item)
        if key in predicted_keys:
            raise ValueError(f"Duplicate predicted correspondence: {key}")
        predicted_keys.add(key)

    reference_keys = set()
    for item in references:
        if not isinstance(item, ReferenceCorrespondence):
            raise TypeError("reference_pairs must contain ReferenceCorrespondence objects")
        key = _reference_key(item)
        if key in reference_keys:
            raise ValueError(f"Duplicate reference correspondence: {key}")
        reference_keys.add(key)

    true_positive = len(predicted_keys & reference_keys)
    false_positive = len(predicted_keys - reference_keys)
    false_negative = len(reference_keys - predicted_keys)

    # True negatives require a defined universe of possible pairs.
    # We do not invent that universe or report a misleading specificity.
    metrics = classification_metrics(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=None,
    )

    return CorrespondenceValidationResult(
        decision_count=len(predicted_keys),
        reference_pair_count=len(reference_keys),
        metrics=metrics,
    )

