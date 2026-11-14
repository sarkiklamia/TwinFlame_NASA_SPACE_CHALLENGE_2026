
from __future__ import annotations

import numpy as np
import pandas as pd

from validation.schema_validator import SchemaValidator
from validation.data_quality_validator import DataQualityValidator
from utils.id_generator import IDGenerator


class DataPipeline:

    BRIGHTNESS_COLUMNS = [
        "brightness",
        "bright_t31",
        "bright_ti4",
        "bright_ti5",
    ]

    def __init__(self):
        self.schema_validator = SchemaValidator()
        self.quality_validator = DataQualityValidator()

    @staticmethod
    def normalize_columns(
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:

        result = dataframe.copy()

        result.columns = (
            result.columns.astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
        )

        return result

    def process(
        self,
        dataframe: pd.DataFrame,
        profile: str,
    ) -> dict:

        if dataframe is None or dataframe.empty:
            return {
                "source": None,
                "profile": profile,
                "accepted": pd.DataFrame(),
                "rejected": pd.DataFrame(),
                "metrics": {
                    "input_rows": 0,
                    "accepted_rows": 0,
                    "rejected_rows": 0,
                },
            }

        working = self.normalize_columns(dataframe)

        # 1. Validate the original source schema.
        schema = self.schema_validator.validate_or_raise(
            working,
            profile=profile,
        )

        # 2. Validate the original measurements.
        # Missing brightness columns are NOT added yet.
        quality = self.quality_validator.validate(working)

        accepted = quality["valid"].copy()
        rejected = quality["rejected"].copy()

        # 3. Add the four-column unified brightness structure.
        # Non-applicable measurements become NULL/NaN.
        for column in self.BRIGHTNESS_COLUMNS:
            if column not in accepted.columns:
                accepted[column] = np.nan

            if column not in rejected.columns:
                rejected[column] = np.nan

        accepted["schema_profile"] = profile
        rejected["schema_profile"] = profile

        if "source_type" not in accepted.columns:
            accepted["source_type"] = (
                "sample" if profile == "sample_csv" else "api"
            )

        if "source_type" not in rejected.columns:
            rejected["source_type"] = (
                "sample" if profile == "sample_csv" else "api"
            )

        return {
            "source": schema.source,
            "profile": profile,
            "accepted": accepted,
            "rejected": rejected,
            "metrics": {
                "input_rows": len(working),
                "accepted_rows": len(accepted),
                "rejected_rows": len(rejected),
            },
        }

    def store_cleaned_sources(
        self,
        cleaned_frames: list[pd.DataFrame],
        parquet_writer,
        dataset_directory,
    ) -> dict:
        """
        Combine outputs AFTER cleaning and standardization.

        Duplicate detection happens here, immediately before
        writing the unified processed Parquet dataset.
        """

        frames = [
            frame.copy()
            for frame in cleaned_frames
            if frame is not None and not frame.empty
        ]

        if not frames:
            return {
                "dataframe": pd.DataFrame(),
                "path": None,
                "metrics": {
                    "input_rows": 0,
                    "duplicate_rows": 0,
                    "stored_rows": 0,
                },
            }

        normalized_frames = [
            self.normalize_columns(frame)
            for frame in frames
        ]

        # Ensure every cleaned source has the unified schema.
        for frame in normalized_frames:
            for column in self.BRIGHTNESS_COLUMNS:
                if column not in frame.columns:
                    frame[column] = np.nan

        # Concatenate only after the source-specific cleaning
        # and standardization steps have finished.
        combined = pd.concat(
            normalized_frames,
            ignore_index=True,
            sort=False,
        )

        # Generate IDs AFTER standardization so equivalent
        # observations use the same normalized identity values.
        combined = IDGenerator.add_detection_ids(combined)

        before = len(combined)

        combined = combined.drop_duplicates(
            subset=["detection_id"],
            keep="first",
        ).reset_index(drop=True)

        duplicate_rows = before - len(combined)

        # Write the final unified processed dataset.
        output_path = parquet_writer.write_part(
            combined,
            dataset_directory,
        )

        return {
            "dataframe": combined,
            "path": output_path,
            "metrics": {
                "input_rows": before,
                "duplicate_rows": duplicate_rows,
                "stored_rows": len(combined),
            },
        }
