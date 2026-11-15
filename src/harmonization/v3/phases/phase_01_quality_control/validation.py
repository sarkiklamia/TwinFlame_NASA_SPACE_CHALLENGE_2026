from collections.abc import Sequence

from ...contracts.observation import ObservationQCResult


def validate_qc_result(result: ObservationQCResult) -> None:
    """Raise ValueError if an individual QC result violates the contract."""
    for field in (
        "eligible_for_spatial_matching",
        "eligible_for_frp_analysis",
        "eligible_for_brightness_analysis",
    ):
        if not isinstance(getattr(result, field), bool):
            raise ValueError(f"{field} must be a boolean")

    if result.eligible_for_frp_analysis and not result.eligible_for_spatial_matching:
        raise ValueError(
            "FRP-eligible observations must also be spatially eligible"
        )

    if result.observation is None:
        raise ValueError("QC result must retain its source observation")



def validate_phase_01_output(
    input_observations: Sequence,
    results: Sequence[ObservationQCResult],
) -> None:
    """Validate count, order, retention, and eligibility invariants."""
    if len(input_observations) != len(results):
        raise ValueError("Phase 1 must return exactly one result per input")

    for original, result in zip(input_observations, results):
        validate_qc_result(result)

        if result.observation is not original:
            raise ValueError(
                "Phase 1 must retain the exact original observation object"
            )
