from collections.abc import Iterable

from ...contracts.observation import ObservationQCResult
from .quality_rules import evaluate_observation


def assess_eligibility(observations: Iterable) -> tuple[ObservationQCResult, ...]:
    """Return one QC result for every input observation, preserving order."""
    return tuple(evaluate_observation(item) for item in observations)
