from datetime import datetime, timezone

import pytest

from harmonization.v3.phases.phase_00_input_audit import (
    EXPECTED_SCHEMA,
    audit_records,
    map_input_record,
    validate_schema,
)


def valid_row(**overrides):
    row = {
        "detection_id": "FIRMS-0001",
        "id": 1,
        "source": "FIRMS",
        "platform": "MODIS_TERRA",
        "latitude": 34.1,
        "longitude": -5.3,
        "acq_date": "2026-11-14",
        "acq_time": "0935",
        "confidence_native": "nominal",
        "frp_mw": 12.5,
        "brightness": 330.0,
        "bright_t31": 300.0,
        "bright_ti4": None,
        "bright_ti5": None,
        "scan_km": 1.0,
        "track_km": 1.0,
        "daynight": "D",
    }
    row.update(overrides)
    return row


def test_expected_schema_has_all_documented_input_columns():
    assert len(EXPECTED_SCHEMA) == 17
    assert "acq_date" in EXPECTED_SCHEMA
    assert "acq_time" in EXPECTED_SCHEMA


def test_schema_validation_accepts_documented_schema_and_types():
    result = validate_schema(
        list(EXPECTED_SCHEMA),
        EXPECTED_SCHEMA,
    )
    assert result.valid


def test_schema_validation_reports_missing_columns():
    columns = [name for name in EXPECTED_SCHEMA if name != "frp_mw"]
    result = validate_schema(columns)
    assert not result.valid
    assert result.missing_columns == ("frp_mw",)


def test_schema_validation_reports_type_mismatch():
    types = dict(EXPECTED_SCHEMA)
    types["latitude"] = "VARCHAR"
    result = validate_schema(list(EXPECTED_SCHEMA), types)
    assert not result.valid
    assert result.type_mismatches == (("latitude", "float", "string"),)


def test_schema_validation_allows_extra_columns_by_default():
    result = validate_schema([*EXPECTED_SCHEMA, "extra_metadata"])
    assert result.valid
    assert result.unexpected_columns == ("extra_metadata",)


def test_map_record_combines_date_and_time_as_utc():
    mapped = map_input_record(valid_row())
    assert mapped.acquisition_time_utc == datetime(
        2026, 11, 14, 9, 35, tzinfo=timezone.utc
    )
    assert mapped.mapping_issues == ()


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("MODIS_TERRA", "MODIS_TERRA"),
        ("terra", "MODIS_TERRA"),
        ("MODIS_AQUA", "MODIS_AQUA"),
        ("NOAA20", "VIIRS_NOAA20"),
        ("NOAA-20", "VIIRS_NOAA20"),
        ("VIIRS_NOAA21", "VIIRS_NOAA21"),
        ("NOAA 21", "VIIRS_NOAA21"),
    ],
)
def test_platform_mapping(platform, expected):
    assert map_input_record(
        valid_row(platform=platform)
    ).platform == expected


def test_map_record_preserves_missing_frp_as_none():
    mapped = map_input_record(valid_row(frp_mw=None))
    assert mapped.frp_mw is None
    assert mapped.mapping_issues == ()


def test_unknown_platform_is_preserved_and_flagged():
    row = valid_row(platform="SNPP")
    mapped = map_input_record(row)

    assert mapped.platform is None
    assert mapped.raw_platform == "SNPP"
    assert mapped.raw_record["platform"] == "SNPP"
    assert "unsupported_platform" in mapped.mapping_issues


def test_missing_detection_id_does_not_discard_record():
    row = valid_row(detection_id=None)
    mapped = map_input_record(row)

    assert mapped.detection_id is None
    assert mapped.raw_record["detection_id"] is None
    assert "missing_detection_id" in mapped.mapping_issues


def test_invalid_timestamp_does_not_discard_record():
    row = valid_row(acq_time="invalid")
    mapped = map_input_record(row)

    assert mapped.acquisition_time_utc is None
    assert "invalid_acquisition_timestamp" in mapped.mapping_issues
    assert mapped.raw_record["acq_time"] == "invalid"


def test_missing_timestamp_is_flagged():
    mapped = map_input_record(valid_row(acq_time=None))

    assert mapped.acquisition_time_utc is None
    assert "missing_acq_time" in mapped.mapping_issues


def test_invalid_numeric_value_is_preserved_and_flagged():
    row = valid_row(latitude="not-a-number")
    mapped = map_input_record(row)

    assert mapped.latitude is None
    assert mapped.raw_record["latitude"] == "not-a-number"
    assert "invalid_numeric:latitude" in mapped.mapping_issues


def test_audit_records_reports_counts_and_nulls():
    rows = [
        valid_row(),
        valid_row(
            detection_id="FIRMS-0002",
            platform="MODIS_AQUA",
            frp_mw=None,
        ),
    ]
    report = audit_records(rows)

    assert report.row_count == 2
    assert report.platform_counts == {
        "MODIS_TERRA": 1,
        "MODIS_AQUA": 1,
    }
    assert report.null_counts["frp_mw"] == 1
