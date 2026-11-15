
import importlib.util

import pytest


def require_ingestion_module():
    if importlib.util.find_spec("ingestion") is None:
        pytest.skip("Ingestion package not available yet")

    if importlib.util.find_spec(
        "ingestion.firms_client"
    ) is None:
        pytest.skip("FIRMS client not available yet")


def test_firms_client_available():
    require_ingestion_module()


def test_api_ingestion():
    require_ingestion_module()

    pytest.skip(
        "Pending integration with real FIRMS client "
        "function and its request/response contract"
    )


def test_api_error_handling():
    require_ingestion_module()

    pytest.skip(
        "Pending real FIRMS client error-handling tests"
    )
