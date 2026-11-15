from collections.abc import Iterable, Mapping
from datetime import date, datetime
import math
from typing import Any

from .schemas import OUTPUT_SCHEMAS, get_output_schema


_TYPE_CHECKS = {
    "VARCHAR": lambda value: isinstance(value, str),
    "INTEGER": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "BIGINT": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "DOUBLE": lambda value: (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    ),
    "DATE": lambda value: isinstance(value, date) and not isinstance(value, datetime),
    "TIMESTAMP": lambda value: isinstance(value, datetime),
}


def validate_output_rows(
    table_name: str,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    """
    Validate output records against their registered schema.

    Returns the number of validated rows.
    Raises ValueError with details if validation fails.
    """
    schema = get_output_schema(table_name)
    expected_columns = {column.name for column in schema}
    errors: list[str] = []
    row_count = 0

    for index, row in enumerate(rows):
        row_count += 1

        if not isinstance(row, Mapping):
            errors.append(f"Row {index}: expected a mapping")
            continue

        actual_columns = set(row)
        missing = expected_columns - actual_columns
        unexpected = actual_columns - expected_columns

        for name in sorted(missing):
            errors.append(f"Row {index}: missing column '{name}'")

        for name in sorted(unexpected):
            errors.append(f"Row {index}: unexpected column '{name}'")

        for column in schema:
            if column.name not in row:
                continue

            value = row[column.name]

            if value is None:
                if not column.nullable:
                    errors.append(
                        f"Row {index}: '{column.name}' cannot be NULL"
                    )
                continue

            checker = _TYPE_CHECKS[column.data_type]

            if not checker(value):
                errors.append(
                    f"Row {index}: '{column.name}' must be "
                    f"{column.data_type}, got {type(value).__name__}"
                )

    if errors:
        details = "\n".join(errors[:50])
        remaining = len(errors) - 50
        if remaining > 0:
            details += f"\n... and {remaining} more errors"

        raise ValueError(
            f"Validation failed for '{table_name}':\n{details}"
        )

    return row_count


def validate_all_output_schemas() -> None:
    """Check that every registered schema has valid, unique definitions."""
    for table_name, columns in OUTPUT_SCHEMAS.items():
        names = [column.name for column in columns]

        if len(names) != len(set(names)):
            raise ValueError(
                f"Duplicate column names in schema '{table_name}'"
            )

        for column in columns:
            if column.data_type not in _TYPE_CHECKS:
                raise ValueError(
                    f"Unsupported type '{column.data_type}' "
                    f"in '{table_name}.{column.name}'"
                )
