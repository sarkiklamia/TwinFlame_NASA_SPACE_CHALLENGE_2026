
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass
class LoadedSample:
    file_path: Path
    source_name: str
    checksum: str
    dataframe: pd.DataFrame


class SampleLoader:

    def __init__(self, raw_storage):
        self.raw_storage = raw_storage

    def load_file(self, file_path: Path) -> LoadedSample:

        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(file_path)

        if file_path.suffix.lower() != ".csv":
            raise ValueError(
                f"Unsupported sample file: {file_path}"
            )

        dataframe = pd.read_csv(
            file_path,
            low_memory=False,
        )

        if dataframe.empty:
            raise ValueError(
                f"Sample file is empty: {file_path}"
            )

        dataframe.columns = (
            dataframe.columns.astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_", regex=False)
        )

        dataframe["source_type"] = "sample"
        dataframe["schema_profile"] = "sample_csv"
        dataframe["source_name"] = file_path.stem
        dataframe["source_file"] = file_path.name

        return LoadedSample(
            file_path=file_path,
            source_name=file_path.stem,
            checksum=self.raw_storage.checksum(file_path),
            dataframe=dataframe,
        )

    def load_all(self) -> list[LoadedSample]:

        files = self.raw_storage.get_local_csv_files()
        loaded = []

        for file_path in files:
            loaded.append(self.load_file(file_path))

        return loaded
