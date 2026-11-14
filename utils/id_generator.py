
from __future__ import annotations

import hashlib
import json
import math

import pandas as pd


class IDGenerator:

    IDENTITY_FIELDS = [
        "satellite",
        "instrument",
        "latitude",
        "longitude",
        "acq_date",
        "acq_time",
        "scan",
        "track",
    ]

    NUMERIC_FIELDS = {
        "latitude", "longitude", "scan", "track",
    }

    @classmethod
    def _normalize(cls, field, value):

        if pd.isna(value):
            return None

        if field in cls.NUMERIC_FIELDS:
            try:
                number = float(value)

                if not math.isfinite(number):
                    return None

                return format(number, ".8f")

            except (ValueError, TypeError):
                return str(value).strip()

        text = str(value).strip()

        if field in {"satellite", "instrument"}:
            return text.upper()

        if field == "acq_time":
            if text.endswith(".0"):
                text = text[:-2]
            if text.isdigit():
                return text.zfill(4)

        return text

    @classmethod
    def generate_detection_id(cls, row: dict) -> str:

        identity = {
            field: cls._normalize(field, row.get(field))
            for field in cls.IDENTITY_FIELDS
        }

        payload = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
        )

        return hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest()

    @classmethod
    def add_detection_ids(
        cls,
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:

        result = dataframe.copy()

        result["detection_id"] = [
            cls.generate_detection_id(row)
            for row in result.to_dict(orient="records")
        ]

        return result
