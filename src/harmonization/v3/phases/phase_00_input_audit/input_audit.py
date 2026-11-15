
"""Structural audit report for UNIFIED_DETECTIONS."""

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class InputAuditReport:
    row_count: int
    null_counts: dict[str, int]
    platform_counts: dict[str, int]
    source_counts: dict[str, int]
    mapping_issue_counts: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "null_counts": dict(self.null_counts),
            "platform_counts": dict(self.platform_counts),
            "source_counts": dict(self.source_counts),
            "mapping_issue_counts": dict(
                self.mapping_issue_counts or {}
            ),
        }


class InputAuditAccumulator:
    """Incrementally accumulates audit statistics without storing rows."""

    def __init__(self) -> None:
        self.row_count = 0
        self.null_counts: Counter[str] = Counter()
        self.platform_counts: Counter[str] = Counter()
        self.source_counts: Counter[str] = Counter()
        self.mapping_issue_counts: Counter[str] = Counter()

    def update(
        self,
        rows: Iterable[Mapping[str, Any]],
        mapped_records: Iterable[Any] | None = None,
    ) -> None:
        for row in rows:
            self.row_count += 1

            for field, value in row.items():
                if value is None or value == "":
                    self.null_counts[field] += 1

            platform = row.get("platform")
            source = row.get("source")

            self.platform_counts[
                str(platform) if platform is not None else "<NULL>"
            ] += 1

            self.source_counts[
                str(source) if source is not None else "<NULL>"
            ] += 1

        if mapped_records is not None:
            for record in mapped_records:
                for issue in record.mapping_issues:
                    self.mapping_issue_counts[issue] += 1

    def report(self) -> InputAuditReport:
        return InputAuditReport(
            row_count=self.row_count,
            null_counts=dict(self.null_counts),
            platform_counts=dict(self.platform_counts),
            source_counts=dict(self.source_counts),
            mapping_issue_counts=dict(self.mapping_issue_counts),
        )


def audit_records(
    rows: Iterable[Mapping[str, Any]],
) -> InputAuditReport:
    """Preserve the existing one-pass audit interface."""
    accumulator = InputAuditAccumulator()
    accumulator.update(rows)
    return accumulator.report()
