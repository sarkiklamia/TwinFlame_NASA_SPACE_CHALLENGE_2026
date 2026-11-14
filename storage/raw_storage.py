
from pathlib import Path
import hashlib


class RawStorage:

    def __init__(self, root="data/raw"):
        self.root = Path(root)

    def get_local_csv_files(self):

        directory = self.root / "sample"

        if not directory.exists():
            return []

        return sorted(directory.rglob("*.csv"))

    def get_api_parquet_files(self):

        directory = self.root / "api"

        if not directory.exists():
            return []

        return sorted(directory.rglob("*.parquet"))

    @staticmethod
    def checksum(filepath):

        digest = hashlib.sha256()

        with open(filepath, "rb") as file:

            for chunk in iter(
                lambda: file.read(1024 * 1024),
                b""
            ):
                digest.update(chunk)

        return digest.hexdigest()
