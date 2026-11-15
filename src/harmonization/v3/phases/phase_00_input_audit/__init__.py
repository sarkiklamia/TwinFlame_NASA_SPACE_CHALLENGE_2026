"""Phase 0: structural input audit and canonical column mapping."""
from .column_mapping import CanonicalInputRecord, map_input_record
from .input_audit import InputAuditReport, audit_records
from .schema_validation import (
    EXPECTED_SCHEMA,
    SchemaValidationResult,
    validate_schema,
)

__all__ = [
    "CanonicalInputRecord",
    "EXPECTED_SCHEMA",
    "InputAuditReport",
    "SchemaValidationResult",
    "audit_records",
    "map_input_record",
    "validate_schema",
]
