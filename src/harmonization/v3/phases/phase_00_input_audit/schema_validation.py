
"""Structural validation of legacy and database UNIFIED_DETECTIONS schemas.

This module validates table structure and declared data types only.
Scientific record-quality checks belong to Phase 1.
"""
from dataclasses import dataclass
from typing import Mapping, Sequence


# Legacy input schema. Retained for existing tests and older input files.
EXPECTED_SCHEMA: dict[str, str] = {
    "detection_id": "string",
    "id": "integer",
    "source": "string",
    "platform": "string",
    "latitude": "float",
    "longitude": "float",
    "acq_date": "date",
    "acq_time": "string",
    "confidence_native": "string",
    "frp_mw": "float",
    "brightness": "float",
    "bright_t31": "float",
    "bright_ti4": "float",
    "bright_ti5": "float",
    "scan_km": "float",
    "track_km": "float",
    "daynight": "string",
}


# Actual DuckDB UNIFIED_DETECTIONS schema.
UNIFIED_DETECTIONS_SCHEMA: dict[str, str] = {
    "detection_id": "integer",
    "file_id": "integer",
    "processing_id": "integer",
    "ingested_at": "timestamp",
    "processing_level": "string",
    "source": "string",
    "platform": "string",
    "sensor": "string",
    "latitude": "float",
    "longitude": "float",
    "acquisition_time_utc": "timestamp",
    "confidence_native": "string",
    "confidence_class": "string",
    "frp_mw": "float",
    "brightness_native": "float",
    "bright_t31": "float",
    "bright_ti4": "float",
    "bright_ti5": "float",
    "scan": "float",
    "track": "float",
    "daynight": "string",
    "product_version": "string",
    "quality_flags": "string",
}


_TYPE_ALIASES = {
    "varchar": "string",
    "char": "string",
    "text": "string",
    "string": "string",
    "utf8": "string",
    "large_string": "string",
    "int": "integer",
    "int8": "integer",
    "int16": "integer",
    "int32": "integer",
    "int64": "integer",
    "bigint": "integer",
    "long": "integer",
    "integer": "integer",
    "float": "float",
    "float32": "float",
    "float64": "float",
    "double": "float",
    "real": "float",
    "date": "date",
    "date32": "date",
    "date64": "date",
    "timestamp": "timestamp",
    "datetime": "timestamp",
}


def normalize_type(type_name: str) -> str:
    """Normalize common DuckDB, SQL and Arrow type names."""
    value = str(type_name).strip().lower()

    value = value.replace("nullable(", "").rstrip(")")

    if value.startswith("decimal") or value.startswith("numeric"):
        return "float"

    if value.startswith("timestamp") or value.startswith("datetime"):
        return "timestamp"

    return _TYPE_ALIASES.get(value, value)


@dataclass(frozen=True)
class SchemaValidationResult:
    valid: bool
    missing_columns: tuple[str, ...]
    unexpected_columns: tuple[str, ...]
    type_mismatches: tuple[tuple[str, str, str], ...]
    missing_type_declarations: tuple[str, ...]

    def summary(self) -> str:
        if self.valid:
            return "UNIFIED_DETECTIONS schema is valid."

        problems = []

        if self.missing_columns:
            problems.append(
                f"missing columns: {', '.join(self.missing_columns)}"
            )

        if self.unexpected_columns:
            problems.append(
                f"unexpected columns: {', '.join(self.unexpected_columns)}"
            )

        if self.type_mismatches:
            details = ", ".join(
                f"{name} (expected {expected}, got {actual})"
                for name, expected, actual in self.type_mismatches
            )
            problems.append(f"type mismatches: {details}")

        if self.missing_type_declarations:
            problems.append(
                "type declarations missing for: "
                + ", ".join(self.missing_type_declarations)
            )

        return "UNIFIED_DETECTIONS schema is invalid: " + "; ".join(problems)


def validate_schema(
    columns: Sequence[str],
    column_types: Mapping[str, str] | None = None,
    *,
    allow_extra_columns: bool = True,
    expected_schema: Mapping[str, str] | None = None,
) -> SchemaValidationResult:
    """
    Validate a legacy or actual UNIFIED_DETECTIONS schema.

    Schema selection is automatic unless expected_schema is supplied.
    """
    actual_columns = tuple(str(column) for column in columns)
    actual_set = set(actual_columns)

    if expected_schema is None:
        if "acquisition_time_utc" in actual_set:
            expected_schema = UNIFIED_DETECTIONS_SCHEMA
        else:
            expected_schema = EXPECTED_SCHEMA

    expected_set = set(expected_schema)

    missing = tuple(
        name for name in expected_schema if name not in actual_set
    )

    unexpected = tuple(
        name for name in actual_columns if name not in expected_set
    )

    mismatches: list[tuple[str, str, str]] = []
    missing_types: list[str] = []

    if column_types is not None:
        for name, expected_type in expected_schema.items():
            if name not in actual_set:
                continue

            actual_type = column_types.get(name)

            if actual_type is None:
                missing_types.append(name)
                continue

            normalized = normalize_type(actual_type)

            if normalized != expected_type:
                mismatches.append(
                    (name, expected_type, normalized)
                )

    valid = (
        not missing
        and not mismatches
        and not missing_types
        and (allow_extra_columns or not unexpected)
    )

    return SchemaValidationResult(
        valid=valid,
        missing_columns=missing,
        unexpected_columns=unexpected,
        type_mismatches=tuple(mismatches),
        missing_type_declarations=tuple(missing_types),
    )
