
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config.api_config import FirmsApiConfig, SensorSource
from ingestion.api_manager import APIManager
from ingestion.firms_client import FIRMSResponse
from ingestion.response_handler import SavedRawFile


REQUIRED_VIIRS_COLUMNS = (
    "latitude", "longitude", "bright_ti4", "scan", "track",
    "acq_date", "acq_time", "satellite", "instrument", "confidence",
    "version", "bright_ti5", "frp", "daynight",
)


def make_config(raw_api_dir: Path) -> FirmsApiConfig:
    source = SensorSource(
        key="NOAA20",
        firms_source="VIIRS_NOAA20_NRT",
        instrument="VIIRS",
        resolution_m=375,
        raw_subdir="NOAA20",
        required_columns=REQUIRED_VIIRS_COLUMNS,
    )
    return FirmsApiConfig(
        base_url="https://example.test/api",
        area_endpoint="area/csv",
        map_key="not-a-real-key",
        sources={"NOAA20": source},
        raw_api_dir=raw_api_dir,
    )


def response(body: str) -> FIRMSResponse:
    return FIRMSResponse(
        source_key="NOAA20",
        firms_source="VIIRS_NOAA20_NRT",
        requested_at=datetime.now(timezone.utc),
        status_code=200,
        url_redacted="https://example.test/api/area/csv/***/VIIRS_NOAA20_NRT/world/1",
        body=body,
    )


VALID_CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,"
    "instrument,confidence,version,bright_ti5,frp,daynight\n"
    "30.1,-9.2,330.0,1.0,1.2,2026-11-10,1234,N20,VIIRS,n,2.0,290.0,12.5,D\n"
)


class FakeFIRMSClient:
    def __init__(self, result):
        self.result = result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def fetch_area(self, **kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_api_ingestion_saves_mocked_firms_response(tmp_path):
    config = make_config(tmp_path / "api")
    fake_client = FakeFIRMSClient(response(VALID_CSV))

    def save_csv_fixture(self, dataframe, source_key, partition_id, requested_at):
        output_dir = config.raw_dir(source_key)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "mocked_response.csv"
        dataframe.to_csv(output_path, index=False)
        return SavedRawFile(
            source_key=source_key,
            partition_id=partition_id,
            path=output_path,
            row_count=len(dataframe),
            requested_at=requested_at,
        )

    with (
        patch("ingestion.api_manager.FIRMSClient", return_value=fake_client),
        patch(
            "ingestion.request_manager.get_partitions",
            return_value=[SimpleNamespace(partition_id="test_partition", bbox="world")],
        ),
        patch("ingestion.response_handler.ResponseHandler._save_parquet", new=save_csv_fixture),
    ):
        summary = APIManager(config).run_once(day_range=1, on_date="2026-11-10")

    assert summary.status == "SUCCESS"
    assert summary.total_requests == 1
    assert summary.total_successful_requests == 1
    assert summary.total_rows == 1
    assert len(summary.saved_files) == 1
    assert summary.saved_files[0].path.is_file()
    assert summary.saved_files[0].path.parent == tmp_path / "api" / "NOAA20"
    assert summary.saved_files[0].path.suffix == ".csv"


def test_api_ingestion_records_mocked_http_failure(tmp_path, caplog):
    config = make_config(tmp_path / "api")
    fake_client = FakeFIRMSClient(RuntimeError("mocked upstream failure"))

    caplog.set_level("CRITICAL", logger="ingestion.request_manager")

    with (
        patch("ingestion.api_manager.FIRMSClient", return_value=fake_client),
        patch(
            "ingestion.request_manager.get_partitions",
            return_value=[SimpleNamespace(partition_id="test_partition", bbox="world")],
        ),
    ):
        summary = APIManager(config).run_once(day_range=1)

    assert summary.status == "FAILED"
    assert summary.total_requests == 1
    assert summary.total_successful_requests == 0
    assert summary.total_rows == 0
    assert any("mocked upstream failure" in error for error in summary.errors)
