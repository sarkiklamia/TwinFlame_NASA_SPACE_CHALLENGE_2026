
from unittest.mock import Mock


def check_authentication(token):
    expected_token = "test-token"

    if token != expected_token:
        return 401

    return 200


def check_rate_limit(request_count, limit=10):
    if request_count > limit:
        return 429

    return 200


def test_valid_token():
    assert check_authentication("test-token") == 200


def test_invalid_token():
    assert check_authentication("wrong-token") == 401


def test_missing_token():
    assert check_authentication(None) == 401


def test_requests_within_limit():
    assert check_rate_limit(5) == 200


def test_requests_at_limit():
    assert check_rate_limit(10) == 200


def test_requests_above_limit():
    assert check_rate_limit(11) == 429
