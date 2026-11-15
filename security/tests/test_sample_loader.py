
import csv

from ingestion.sample_loader import SampleLoader
from storage.raw_storage import RawStorage


def make_sample_csv(tmp_path):
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    path = sample_dir / "demo_fire.csv"
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["Latitude", "Longitude", "Acq Date"])
        writer.writerow(["30.0", "-9.0", "2026-11-10"])
    return path


def test_sample_file_exists(tmp_path):
    assert make_sample_csv(tmp_path).is_file()


def test_sample_csv_readable_and_normalized(tmp_path):
    loaded = SampleLoader(RawStorage(tmp_path)).load_file(make_sample_csv(tmp_path))

    assert loaded.source_name == "demo_fire"
    assert loaded.dataframe.columns.tolist() == [
        "latitude", "longitude", "acq_date", "source_type",
        "schema_profile", "source_name", "source_file",
    ]
    assert loaded.dataframe.loc[0, "source_type"] == "sample"
    assert loaded.dataframe.loc[0, "schema_profile"] == "sample_csv"


def test_sample_csv_has_coordinates_and_checksum(tmp_path):
    loaded = SampleLoader(RawStorage(tmp_path)).load_file(make_sample_csv(tmp_path))

    assert {"latitude", "longitude"}.issubset(loaded.dataframe.columns)
    assert len(loaded.checksum) == 64

