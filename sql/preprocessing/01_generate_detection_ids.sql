
-- ============================================================
-- PyroSync — Deterministic Detection ID Generation
--
-- Input:
--   {{STANDARDIZED_INPUT}}
--
-- Output:
--   {{IDENTIFIED_OUTPUT}}
--
-- ID:
--   Deterministic, positive BIGINT
--   Generated from canonical detection attributes
-- ============================================================

COPY (
    WITH source_data AS (
        SELECT *
        FROM read_parquet(
            '{{STANDARDIZED_INPUT}}'
        )
    ),

    identified AS (
        SELECT
            CAST(
                (
                    md5_number_lower(
                        to_json(
                            struct_pack(
                                source := d.source,
                                satellite := d.satellite,
                                instrument := d.instrument,
                                platform := d.platform,

                                acquisition_time_utc :=
                                    d.acquisition_time_utc,

                                latitude := d.latitude,
                                longitude := d.longitude,

                                brightness := d.brightness,
                                bright_t31 := d.bright_t31,
                                bright_ti4 := d.bright_ti4,
                                bright_ti5 := d.bright_ti5,

                                frp_mw := d.frp_mw,
                                scan_km := d.scan_km,
                                track_km := d.track_km,

                                confidence_native :=
                                    d.confidence_native,

                                daynight := d.daynight,
                                product_version := d.product_version
                            )
                        )
                    )
                    & 9223372036854775807
                ) AS BIGINT
            ) AS detection_id,
            d.source_file,
            d.source_type,
            d.source,
            d.satellite,
            d.instrument,
            d.platform,
            d.sensor,
            d.latitude,
            d.longitude,
            d.acq_date,
            d.acq_time,
            d.acquisition_time_utc,
            d.confidence_native,
            d.confidence_class,
            d.brightness,
            d.bright_t31,
            d.bright_ti4,
            d.bright_ti5,
            d.frp_mw,
            d.scan_km,
            d.track_km,
            d.daynight,
            d.product_version,
            d.quality_flags

        FROM source_data AS d
    )

    SELECT *
    FROM identified

) TO '{{IDENTIFIED_OUTPUT}}'
(FORMAT PARQUET, COMPRESSION ZSTD);


-- ============================================================
-- Verification 1: row count and ID validity
-- ============================================================

SELECT
    COUNT(*) AS total_rows,
    COUNT(detection_id) AS non_null_ids,
    COUNT(*) FILTER (
        WHERE detection_id IS NULL
    ) AS null_ids,
    MIN(detection_id) AS minimum_id,
    MAX(detection_id) AS maximum_id

FROM read_parquet(
    '{{IDENTIFIED_OUTPUT}}'
);


-- ============================================================
-- Verification 2: ID uniqueness
-- ============================================================

SELECT
    COUNT(*) AS total_rows,
    COUNT(DISTINCT detection_id) AS unique_ids,
    COUNT(*) - COUNT(DISTINCT detection_id)
        AS duplicate_id_count

FROM read_parquet(
    '{{IDENTIFIED_OUTPUT}}'
);


-- ============================================================
-- Verification 3: row count comparison
-- ============================================================

SELECT
    (
        SELECT COUNT(*)
        FROM read_parquet(
            '{{STANDARDIZED_INPUT}}'
        )
    ) AS original_rows,

    (
        SELECT COUNT(*)
        FROM read_parquet(
            '{{IDENTIFIED_OUTPUT}}'
        )
    ) AS output_rows;


-- ============================================================
-- Verification 4: schema
-- ============================================================

DESCRIBE
SELECT *
FROM read_parquet(
    '{{IDENTIFIED_OUTPUT}}'
);


-- ============================================================
-- Verification 5: sample
-- ============================================================

SELECT
    detection_id,
    source,
    platform,
    acquisition_time_utc,
    latitude,
    longitude,
    frp_mw

FROM read_parquet(
    '{{IDENTIFIED_OUTPUT}}'
)

LIMIT 10;
