from dataclasses import dataclass
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import timezone
from typing import Any

from ...contracts.observation import ObservationQCResult
from .eligibility import assess_eligibility
from .quality_rules import evaluate_observation
from .validation import validate_phase_01_output, validate_qc_result


@dataclass(frozen=True)
class Phase01Result:
    results: tuple[ObservationQCResult, ...]

    @property
    def input_count(self) -> int:
        return len(self.results)

    @property
    def spatial_eligible_count(self) -> int:
        return sum(
            item.eligible_for_spatial_matching for item in self.results
        )

    @property
    def frp_eligible_count(self) -> int:
        return sum(
            item.eligible_for_frp_analysis for item in self.results
        )

    @property
    def brightness_eligible_count(self) -> int:
        return sum(
            item.eligible_for_brightness_analysis for item in self.results
        )


@dataclass(frozen=True)
class Phase01GroupSummary:
    platform: str
    utc_date: str
    input_count: int
    spatial_eligible_count: int
    frp_eligible_count: int
    brightness_eligible_count: int


@dataclass(frozen=True)
class Phase01StreamingSummary:
    """Bounded-memory Phase 01 counts grouped by platform and UTC date."""

    input_count: int
    spatial_eligible_count: int
    frp_eligible_count: int
    brightness_eligible_count: int
    issue_counts: dict[str, int]
    warning_counts: dict[str, int]
    groups: tuple[Phase01GroupSummary, ...]


def run_phase_01(observations: Iterable) -> Phase01Result:
    source_observations = tuple(observations)
    results = assess_eligibility(source_observations)

    validate_phase_01_output(source_observations, results)

    return Phase01Result(results=results)


def run_phase_01_streaming(
    observations: Iterable[Any],
) -> Phase01StreamingSummary:
    """Evaluate a one-pass iterable without retaining individual results."""
    totals = Counter()
    issues = Counter()
    warnings = Counter()
    grouped_counts = defaultdict(Counter)

    for observation in observations:
        result = evaluate_observation(observation)
        validate_qc_result(result)
        if result.observation is not observation:
            raise ValueError("Phase 1 must retain the source observation")

        timestamp = observation.acquisition_time_utc
        if (
            timestamp is not None
            and timestamp.tzinfo is not None
            and timestamp.utcoffset() is not None
        ):
            utc_date = timestamp.astimezone(timezone.utc).date().isoformat()
        else:
            utc_date = "UNKNOWN"
        platform = observation.platform or "UNMAPPED"
        group = grouped_counts[(platform, utc_date)]
        group["input_count"] += 1
        totals["input_count"] += 1

        for name, eligible in (
            ("spatial_eligible_count", result.eligible_for_spatial_matching),
            ("frp_eligible_count", result.eligible_for_frp_analysis),
            (
                "brightness_eligible_count",
                result.eligible_for_brightness_analysis,
            ),
        ):
            if eligible:
                group[name] += 1
                totals[name] += 1

        issues.update(result.qc_issues)
        warnings.update(result.qc_warnings)

    groups = tuple(
        Phase01GroupSummary(
            platform=platform,
            utc_date=utc_date,
            input_count=counts["input_count"],
            spatial_eligible_count=counts["spatial_eligible_count"],
            frp_eligible_count=counts["frp_eligible_count"],
            brightness_eligible_count=counts["brightness_eligible_count"],
        )
        for (platform, utc_date), counts in sorted(grouped_counts.items())
    )
    return Phase01StreamingSummary(
        input_count=totals["input_count"],
        spatial_eligible_count=totals["spatial_eligible_count"],
        frp_eligible_count=totals["frp_eligible_count"],
        brightness_eligible_count=totals["brightness_eligible_count"],
        issue_counts=dict(sorted(issues.items())),
        warning_counts=dict(sorted(warnings.items())),
        groups=groups,
    )
