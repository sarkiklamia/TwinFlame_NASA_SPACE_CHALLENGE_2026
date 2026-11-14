
import pytest
import requests
from unittest.mock import Mock, patch

def fetch_fire_data(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.text
    except requests.Timeout:
        return "TIMEOUT_ERROR"
    except requests.HTTPError:
        return "HTTP_ERROR"
    except requests.RequestException:
        return "NETWORK_ERROR"

@patch("requests.get")
def test_api_timeout(mock_get):
    mock_get.side_effect = requests.Timeout()

    result = fetch_fire_data("https://example.com")

    assert result == "TIMEOUT_ERROR"

@patch("requests.get")
def test_http_error(mock_get):
    response = Mock()
    response.raise_for_status.side_effect = (
        requests.HTTPError("HTTP error")
    )
    mock_get.return_value = response

    result = fetch_fire_data("https://example.com")

    assert result == "HTTP_ERROR"

@patch("requests.get")
def test_network_error(mock_get):
    mock_get.side_effect = requests.ConnectionError()

    result = fetch_fire_data("https://example.com")

    assert result == "NETWORK_ERROR"
