
from pathlib import Path
import os
import uuid

import pandas as pd


class ParquetWriter:

    def __init__(self, compression="snappy"):
        self.compression = compression

    def write_part(self, dataframe, dataset_directory):

        if dataframe.empty:
            return None

        directory = Path(dataset_directory)
        directory.mkdir(parents=True, exist_ok=True)

        destination = directory / (
            f"part-{uuid.uuid4().hex}.parquet"
        )

        temporary = directory / (
            f".{destination.stem}.tmp.parquet"
        )

        try:
            dataframe.to_parquet(
                temporary,
                index=False,
                compression=self.compression
            )

            os.replace(temporary, destination)

        except Exception:
            temporary.unlink(missing_ok=True)
            raise

        return destination

    @staticmethod
    def read_file(filepath):
        return pd.read_parquet(filepath)

    @staticmethod
    def read_dataset(directory):

        directory = Path(directory)

        files = sorted(directory.glob("*.parquet"))

        if not files:
            return pd.DataFrame()

        return pd.concat(
            [pd.read_parquet(file) for file in files],
            ignore_index=True,
            sort=False
        )
