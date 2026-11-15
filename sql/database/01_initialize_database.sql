-- ============================================================
-- PyroSync / TwinFlame - Database initialization
-- ============================================================

BEGIN TRANSACTION;

CREATE TABLE IF NOT EXISTS INGESTION_RUNS (
    ingestion_id BIGINT PRIMARY KEY,
    source_type VARCHAR NOT NULL
        CHECK (source_type IN ('API', 'ARCHIVE')),
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    status VARCHAR
);

CREATE TABLE IF NOT EXISTS SOURCE_FILES (
    file_id BIGINT PRIMARY KEY,
    filename VARCHAR NOT NULL,
    source_type VARCHAR NOT NULL
        CHECK (source_type IN ('API', 'ARCHIVE')),
    platform VARCHAR,
    product_version VARCHAR,
    retrieval_time TIMESTAMP,
    checksum VARCHAR,
    ingestion_id BIGINT,
    FOREIGN KEY (ingestion_id)
        REFERENCES INGESTION_RUNS(ingestion_id)
);

CREATE TABLE IF NOT EXISTS PROCESSING_RUNS (
    processing_id BIGINT PRIMARY KEY,
    input_file_id BIGINT,
    processing_version VARCHAR,
    start_time TIMESTAMP,
    status VARCHAR,
    FOREIGN KEY (input_file_id)
        REFERENCES SOURCE_FILES(file_id)
);

CREATE TABLE IF NOT EXISTS CLEANING_THRESHOLD_BASELINES (
    source VARCHAR NOT NULL,
    satellite VARCHAR NOT NULL,
    metric VARCHAR NOT NULL,
    observation_count BIGINT,
    lower_percentile DOUBLE,
    q1 DOUBLE,
    q3 DOUBLE,
    updated_at TIMESTAMP,
    PRIMARY KEY (source, satellite, metric)
);

CREATE TABLE IF NOT EXISTS UNIFIED_DETECTIONS (
    detection_id BIGINT PRIMARY KEY,
    file_id BIGINT,
    processing_id BIGINT,

    ingested_at TIMESTAMP NOT NULL,
    processing_level VARCHAR NOT NULL
        CHECK (
            processing_level IN (
                'CLEANED', 'STANDARDIZED', 'HARMONIZED'
            )
        ),

    source VARCHAR,
    platform VARCHAR,
    sensor VARCHAR,

    latitude FLOAT,
    longitude FLOAT,
    acquisition_time_utc TIMESTAMP,

    confidence_native VARCHAR,
    confidence_class VARCHAR,

    frp_mw FLOAT,
    brightness_native FLOAT,
    bright_t31 FLOAT,
    bright_ti4 FLOAT,
    bright_ti5 FLOAT,

    scan FLOAT,
    track FLOAT,

    daynight VARCHAR,
    product_version VARCHAR,
    quality_flags VARCHAR,

    FOREIGN KEY (file_id) REFERENCES SOURCE_FILES(file_id),
    FOREIGN KEY (processing_id) REFERENCES PROCESSING_RUNS(processing_id)
);

COMMIT;
