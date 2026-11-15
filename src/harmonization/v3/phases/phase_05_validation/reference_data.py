"""Load independently reviewed Phase 05 labels from the project CSV files."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import date
import hashlib
from pathlib import Path
from typing import Any

from harmonization.v3.contracts.validation import (
    ActivityReferenceLabel,
    ReferenceCorrespondence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[5]
DEFAULT_REFERENCE_PAIR_PATH = (
    PROJECT_ROOT / "data" / "validation" / "candidate_recall_reference_pairs.csv"
)
DEFAULT_ACTIVITY_LABEL_PATH = (
    PROJECT_ROOT / "data" / "validation" / "activity_reference_labels.csv"
)
SUPPORTED_PLATFORMS = {
    "MODIS_TERRA",
    "MODIS_AQUA",
    "VIIRS_NOAA20",
    "VIIRS_NOAA21",
}
PAIR_LABELS = {
    "same_burning_location",
    "different_burning_location",
    "uncertain",
}


@dataclass(frozen=True)
class Phase05ReferenceInputs:
    candidate_recall_pairs_by_date: dict[date, tuple[ReferenceCorrespondence, ...]]
    activity_labels_by_date: dict[date, tuple[ActivityReferenceLabel, ...]]
    manifest: dict[str, Any]


def _snapshot(path: Path, row_count: int) -> dict[str, Any]:
    if not path.is_file():
        return {"path": str(path.resolve()), "exists": False, "row_count": 0}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "path": str(path.resolve()),
        "exists": True,
        "sha256": digest.hexdigest(),
        "row_count": row_count,
    }


def _read_csv(path: Path, required_fields: set[str]) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        missing = required_fields - set(reader.fieldnames or ())
        if missing:
            raise ValueError(
                f"Validation label file {path} is missing columns: "
                f"{sorted(missing)}"
            )
        return [
            {key: (value or "").strip() for key, value in row.items() if key}
            for row in reader
        ]


def _required_review_metadata(row: dict[str, str], path: Path, row_number: int) -> None:
    missing = [
        field for field in ("reviewer_id", "reviewed_at_utc", "evidence_reference")
        if not row.get(field)
    ]
    if missing:
        raise ValueError(
            f"{path}:{row_number} has a label but lacks review metadata: {missing}"
        )


def load_phase05_reference_inputs(
    *,
    candidate_recall_path: str | Path = DEFAULT_REFERENCE_PAIR_PATH,
    activity_labels_path: str | Path = DEFAULT_ACTIVITY_LABEL_PATH,
) -> Phase05ReferenceInputs:
    """Load positive independent pairs and per-detection activity labels.

    Candidate-recall references must be independently found positives. The
    review queue sampled from candidate outputs is intentionally not loaded
    here, since it cannot measure candidate-generation misses.
    """
    pair_path = Path(candidate_recall_path).expanduser().resolve()
    activity_path = Path(activity_labels_path).expanduser().resolve()
    pair_rows = _read_csv(
        pair_path,
        {
            "reference_date_utc", "platform_a", "detection_id_a",
            "platform_b", "detection_id_b", "label", "reviewer_id",
            "reviewed_at_utc", "evidence_reference",
        },
    )
    activity_rows = _read_csv(
        activity_path,
        {
            "activity_date_utc", "platform", "detection_id", "activity_id",
            "reviewer_id", "reviewed_at_utc", "evidence_reference",
        },
    )

    pairs_by_date: dict[date, list[ReferenceCorrespondence]] = {}
    pair_labels_seen: dict[tuple[Any, Any], str] = {}
    label_counts = {label: 0 for label in PAIR_LABELS}
    for row_number, row in enumerate(pair_rows, start=2):
        label = row["label"].casefold()
        if not label:
            continue
        if label not in PAIR_LABELS:
            raise ValueError(
                f"{pair_path}:{row_number} has unsupported label {row['label']!r}"
            )
        _required_review_metadata(row, pair_path, row_number)
        label_counts[label] += 1
        reference_date = date.fromisoformat(row["reference_date_utc"])
        platform_a = row["platform_a"].upper()
        platform_b = row["platform_b"].upper()
        if platform_a not in SUPPORTED_PLATFORMS or platform_b not in SUPPORTED_PLATFORMS:
            raise ValueError(
                f"{pair_path}:{row_number} names an unsupported platform pair"
            )
        if platform_a == platform_b:
            raise ValueError(
                f"{pair_path}:{row_number} must contain two different platforms"
            )
        if not row["detection_id_a"] or not row["detection_id_b"]:
            raise ValueError(f"{pair_path}:{row_number} has a blank detection ID")

        identity = tuple(sorted((
            (platform_a, row["detection_id_a"]),
            (platform_b, row["detection_id_b"]),
        )))
        key = (reference_date, identity)
        previous_label = pair_labels_seen.get(key)
        if previous_label is not None:
            raise ValueError(
                f"{pair_path}:{row_number} duplicates a pair already labeled "
                f"{previous_label!r}"
            )
        pair_labels_seen[key] = label

        # Only positive truth pairs form the candidate-recall denominator.
        if label == "same_burning_location":
            pairs_by_date.setdefault(reference_date, []).append(
                ReferenceCorrespondence(
                    platform_a=platform_a,
                    detection_id_a=row["detection_id_a"],
                    platform_b=platform_b,
                    detection_id_b=row["detection_id_b"],
                )
            )

    activities_by_date: dict[date, list[ActivityReferenceLabel]] = {}
    activity_identities = set()
    for row_number, row in enumerate(activity_rows, start=2):
        activity_id = row["activity_id"]
        if not activity_id:
            continue
        _required_review_metadata(row, activity_path, row_number)
        activity_date = date.fromisoformat(row["activity_date_utc"])
        platform = row["platform"].upper()
        if platform not in SUPPORTED_PLATFORMS:
            raise ValueError(
                f"{activity_path}:{row_number} names an unsupported platform "
                f"{platform!r}"
            )
        if not row["detection_id"]:
            raise ValueError(f"{activity_path}:{row_number} has a blank detection ID")
        identity = (activity_date, platform, row["detection_id"])
        if identity in activity_identities:
            raise ValueError(
                f"{activity_path}:{row_number} duplicates activity label {identity}"
            )
        activity_identities.add(identity)
        activities_by_date.setdefault(activity_date, []).append(
            ActivityReferenceLabel(
                platform=platform,
                detection_id=row["detection_id"],
                activity_date_utc=activity_date,
                activity_id=activity_id,
            )
        )

    frozen_pairs = {
        key: tuple(value) for key, value in pairs_by_date.items()
    }
    frozen_activities = {
        key: tuple(value) for key, value in activities_by_date.items()
    }
    manifest = {
        "candidate_recall_reference_file": _snapshot(pair_path, len(pair_rows)),
        "activity_reference_file": _snapshot(activity_path, len(activity_rows)),
        "reviewed_pair_label_counts": label_counts,
        "positive_candidate_recall_pair_count": sum(
            len(items) for items in frozen_pairs.values()
        ),
        "activity_detection_label_count": sum(
            len(items) for items in frozen_activities.values()
        ),
    }
    return Phase05ReferenceInputs(
        candidate_recall_pairs_by_date=frozen_pairs,
        activity_labels_by_date=frozen_activities,
        manifest=manifest,
    )


def summarize_phase05_results(pipeline_result: Any) -> dict[str, Any]:
    """Serialize Phase 05 metrics for run manifests and dashboard ingestion."""
    return {
        "status": pipeline_result.phase05_status,
        "skipped_validation_types": list(pipeline_result.skipped_validation_types),
        "candidate_recall_results": [
            asdict(result) for result in pipeline_result.candidate_recall_results
        ],
        "activity_pairwise_results": [
            asdict(result) for result in pipeline_result.activity_validation_results
        ],
        "metric_scope": (
            "Independent reviewed references only; candidate recall and "
            "activity pairwise classification are separate metrics."
        ),
    }
