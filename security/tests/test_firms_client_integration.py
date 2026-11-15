
"""Security and reliability tests for the real FIRMS HTTP client."""

from types import SimpleNamespace
from unittest.mock import MagicMock
import traceback

import pytest
import requests

from ingestion.firms_client import FIRMSClient, FIRMSRequestError


FAKE_KEY = "TEST_SECRET_MAP_KEY_12345"
FAKE_URL = f"https://example.test/api/area/csv/{FAKE_KEY}/NOAA20/world/1"


@pytest.fixture
def client():
    config = SimpleNamespace(
        timeout=2,
        max_retries=1,
        retry_delay=0,
        get_source=lambda key: SimpleNamespace(
            enabled=True,
            firms_source="VIIRS_NOAA20_NRT",
        ),
        area_url=lambda **kwargs: FAKE_URL,
        redact=lambda text: text.replace(FAKE_KEY, "***"),
    )

    session = MagicMock()
    session.headers = {}

    return FIRMSClient(config=config, session=session)


def response_with_status(status, body=""):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response.url = FAKE_URL
    return response


def test_successful_request(client):
    client.session.get.return_value = response_with_status(
        200, "latitude,longitude\n30.0,-9.0"
    )

    result = client.fetch_area("NOAA20")

    assert result.status_code == 200
    assert "latitude" in result.body
    assert FAKE_KEY not in result.url_redacted


def test_http_403_error_redacts_key(client):
    client.session.get.return_value = response_with_status(403)

    with pytest.raises(FIRMSRequestError) as exc:
        client.fetch_area("NOAA20")

    assert FAKE_KEY not in str(exc.value)
    assert "***" in str(exc.value)


def test_retry_after_http_429(client, monkeypatch):
    delays = []
    monkeypatch.setattr(
        "ingestion.firms_client.time.sleep",
        delays.append,
    )

    first = response_with_status(429)
    first.headers["Retry-After"] = "2"

    second = response_with_status(200, "latitude,longitude")

    client.session.get.side_effect = [first, second]

    result = client.fetch_area("NOAA20")

    assert result.status_code == 200
    assert client.session.get.call_count == 2
    assert delays == [2.0]


def test_timeout_then_success(client, monkeypatch):
    monkeypatch.setattr(
        "ingestion.firms_client.time.sleep",
        lambda _: None,
    )

    client.session.get.side_effect = [
        requests.Timeout("Connection timed out"),
        response_with_status(200, "latitude,longitude"),
    ]

    result = client.fetch_area("NOAA20")

    assert result.status_code == 200
    assert client.session.get.call_count == 2


def test_timeout_after_all_retries(client, monkeypatch):
    monkeypatch.setattr(
        "ingestion.firms_client.time.sleep",
        lambda _: None,
    )

    client.session.get.side_effect = requests.Timeout(
        "Connection timed out"
    )

    with pytest.raises(FIRMSRequestError):
        client.fetch_area("NOAA20")

    assert client.session.get.call_count == 2


def test_error_log_does_not_expose_key(client, caplog, monkeypatch):
    monkeypatch.setattr(
        "ingestion.firms_client.time.sleep",
        lambda _: None,
    )

    client.session.get.side_effect = [
        response_with_status(503),
        response_with_status(200),
    ]

    with caplog.at_level("WARNING"):
        client.fetch_area("NOAA20")

    assert FAKE_KEY not in caplog.text


def test_full_traceback_does_not_expose_key(client):
    client.session.get.return_value = response_with_status(403)

    with pytest.raises(FIRMSRequestError) as exc:
        client.fetch_area("NOAA20")

    full_traceback = "".join(
        traceback.format_exception(exc.value)
    )

    assert FAKE_KEY not in full_traceback
