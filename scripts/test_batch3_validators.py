
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from validation.schema_validator import SchemaValidator
from validation.data_quality_validator import DataQualityValidator

SAMPLE_DIR = PROJECT_ROOT / "data" / "raw" / "sample"

FILES = [
    "J1V-C2_2026_July.csv",
    "J2V-C2_2026_July.csv",
    "M-C61_2026_July.csv",
]

schema_validator = SchemaValidator()
quality_validator = DataQualityValidator()

for filename in FILES:
    print(f"\n{'=' * 60}")
    print(f"TESTING: {filename}")
    print("=" * 60)

    df = pd.read_csv(
        SAMPLE_DIR / filename,
        nrows=10_000,
        low_memory=False,
    )

    df.columns = (
        df.columns.astype(str)
        .str.strip()
        .str.lower()
        .str.replace(" ", "_", regex=False)
    )

    schema = schema_validator.validate(df)

    print("Detected source:", schema.source)
    print("Schema valid:", schema.valid)
    print("Missing columns:", schema.missing_columns)
    print("Schema errors:", schema.errors)

    if not schema.valid:
        print("QUALITY TEST SKIPPED")
        continue

    quality = quality_validator.validate(df)

    print("Quality metrics:", quality["metrics"])

    if not quality["rejected"].empty:
        print("\nRejection reasons:")
        print(
            quality["rejected"]["quality_reasons"]
            .explode()
            .value_counts()
        )
