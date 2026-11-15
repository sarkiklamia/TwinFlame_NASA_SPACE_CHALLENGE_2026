"""Create a blind, human-review queue from successful Phase 08 outputs."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import sys

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "validation" / "correspondence_review_queue.csv"
QUEUE_FIELDS = (
    "review_id",
    "reference_date_utc",
    "platform_a",
    "detection_id_a",
    "platform_b",
    "detection_id_b",
    "experiment_id",
    "reference_label",
    "reviewer_id",
    "reviewed_at_utc",
    "evidence_reference",
    "notes",
)


def _quote_sql_string(value: str | Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _review_id(activity_date: str, pair: tuple[str, str, str, str, str]) -> str:
    payload = "|".join((activity_date, *pair))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _sample_manifest(path: Path) -> dict:
    content = json.loads(path.read_text(encoding="utf-8"))
    if content.get("phase") != "08_full_historical_processing":
        raise ValueError("Manifest is not a Phase 08 manifest.")
    if content.get("status") != "success":
        raise ValueError("Review queues can only be built from a successful run.")
    return content


def create_review_queue(
    manifest_path: Path,
    output_path: Path,
    *,
    sample_per_platform_pair: int = 60,
    seed: int = 42,
) -> dict:
    if sample_per_platform_pair < 1:
        raise ValueError("sample_per_platform_pair must be positive")

    manifest_path = manifest_path.expanduser().resolve()
    manifest = _sample_manifest(manifest_path)
    output_path = output_path.expanduser().resolve()
    rng = random.Random(seed)
    reservoirs: dict[tuple[str, str], list[dict[str, str]]] = {}
    population_counts: dict[tuple[str, str], int] = {}

    connection = duckdb.connect(database=":memory:")
    try:
        for partition in manifest.get("partitions", []):
            if partition.get("status") != "succeeded":
                continue
            output_directory = Path(partition["output_directory"])
            parquet_path = output_directory / "harm_correspondence_edges.parquet"
            if not parquet_path.is_file():
                raise FileNotFoundError(f"Missing Phase 08 edge output: {parquet_path}")

            activity_date = str(partition["date_utc"])
            cursor = connection.execute(
                "SELECT platform_a, detection_id_a, platform_b, detection_id_b, "
                "experiment_id FROM read_parquet(" + _quote_sql_string(parquet_path) + ")"
            )
            while True:
                rows = cursor.fetchmany(20_000)
                if not rows:
                    break
                for row in rows:
                    platform_a, detection_a, platform_b, detection_b, experiment_id = row
                    platform_key = tuple(sorted((str(platform_a), str(platform_b))))
                    population_counts[platform_key] = population_counts.get(platform_key, 0) + 1
                    sample = reservoirs.setdefault(platform_key, [])
                    candidate = {
                        "reference_date_utc": activity_date,
                        "platform_a": str(platform_a),
                        "detection_id_a": str(detection_a),
                        "platform_b": str(platform_b),
                        "detection_id_b": str(detection_b),
                        "experiment_id": str(experiment_id),
                    }
                    sample_limit = sample_per_platform_pair
                    if len(sample) < sample_limit:
                        sample.append(candidate)
                    else:
                        replacement = rng.randrange(population_counts[platform_key])
                        if replacement < sample_limit:
                            sample[replacement] = candidate
    finally:
        connection.close()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    selected_counts = {}
    with output_path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=QUEUE_FIELDS)
        writer.writeheader()
        for platform_key in sorted(reservoirs):
            for item in sorted(
                reservoirs[platform_key],
                key=lambda value: (
                    value["reference_date_utc"],
                    value["detection_id_a"],
                    value["detection_id_b"],
                ),
            ):
                pair = (
                    item["platform_a"],
                    item["detection_id_a"],
                    item["platform_b"],
                    item["detection_id_b"],
                    item["experiment_id"],
                )
                writer.writerow({
                    "review_id": _review_id(item["reference_date_utc"], pair),
                    **item,
                    "reference_label": "",
                    "reviewer_id": "",
                    "reviewed_at_utc": "",
                    "evidence_reference": "",
                    "notes": "",
                })
            selected_counts["|".join(platform_key)] = len(reservoirs[platform_key])

    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase08_run_id": manifest.get("run_id"),
        "phase08_manifest": str(manifest_path),
        "selection": "uniform reservoir sample within each platform pair",
        "sample_per_platform_pair": sample_per_platform_pair,
        "random_seed": seed,
        "population_candidate_rows_by_platform_pair": {
            "|".join(key): value for key, value in sorted(population_counts.items())
        },
        "selected_rows_by_platform_pair": selected_counts,
        "review_queue": str(output_path),
        "labeling_status": "UNLABELED_REVIEW_QUEUE",
    }
    summary_path = output_path.with_name(output_path.stem + "_manifest.json")
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Sample a blinded human-review queue from successful Phase 08 "
            "correspondence outputs. This does not create ground-truth labels."
        ),
    )
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-per-platform-pair", type=int, default=60)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        summary = create_review_queue(
            args.manifest,
            args.output,
            sample_per_platform_pair=args.sample_per_platform_pair,
            seed=args.seed,
        )
    except Exception as exc:
        parser.exit(2, f"Could not create review queue: {type(exc).__name__}: {exc}\n")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
