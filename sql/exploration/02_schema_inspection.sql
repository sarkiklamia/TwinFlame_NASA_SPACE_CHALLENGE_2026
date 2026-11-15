-- Inspect the original CSV schema.
DESCRIBE
SELECT *
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true
);

-- Inspect the combined API schema.
-- union_by_name preserves source-specific columns.
DESCRIBE
SELECT *
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true
);