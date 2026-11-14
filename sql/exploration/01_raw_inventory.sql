-- Inventory: count records in every raw file.
-- Read-only exploration.

SELECT
    'sample_csv' AS source,
    filename,
    COUNT(*) AS row_count
FROM read_csv_auto(
    'data/raw/sample/*.csv',
    union_by_name = true,
    filename = true
)
GROUP BY filename

UNION ALL

SELECT
    'firms_api' AS source,
    filename,
    COUNT(*) AS row_count
FROM read_parquet(
    'data/raw/api/**/*.parquet',
    union_by_name = true,
    filename = true
)
GROUP BY filename

ORDER BY source, filename;