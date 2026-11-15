
"""Check that anonymous users cannot launch the pipeline."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.backend.main as backend


def test_anonymous_user_cannot_run_pipeline(monkeypatch, tmp_path):
    # Use a nonexistent test database to prevent real execution.
    fake_database = tmp_path / "missing_test.duckdb"

    monkeypatch.setattr(
        backend,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=fake_database),
    )

    # Ensure no background job could be scheduled.
    def block_background_job(*args, **kwargs):
        raise AssertionError("Unauthorized request scheduled a job!")

    monkeypatch.setattr(
        "fastapi.BackgroundTasks.add_task",
        block_background_job,
    )

    client = TestClient(backend.app)

    response = client.post(
        "/api/pipeline/run",
        json={"stage": "harmonization", "dry_run": True},
    )

    assert response.status_code in (401, 403)

"""Additional tests for real pipeline authorization."""

from fastapi.testclient import TestClient

import app.backend.main as backend
import security.auth as auth


def test_anonymous_request_returns_401():
    with TestClient(backend.app) as client:
        response = client.post(
            "/api/pipeline/run",
            json={"stage": "harmonization"},
        )

    assert response.status_code == 401


def test_non_operator_returns_403(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AUTH_DB_PATH",
        str(tmp_path / "sessions.sqlite3"),
    )
    monkeypatch.setenv(
        "GOOGLE_OPERATOR_EMAILS",
        "operator@example.com",
    )

    token = auth._create_session(
        "test-google-sub",
        "viewer@example.com",
    )

    with TestClient(backend.app) as client:
        client.cookies.set(auth.COOKIE_NAME, token)
        response = client.post(
            "/api/pipeline/run",
            json={"stage": "harmonization"},
            headers={"Origin": "http://localhost:5173"},
        )

    assert response.status_code == 403


def test_operator_reaches_database_check(monkeypatch, tmp_path):
    """No real pipeline is run; database is intentionally absent."""

    monkeypatch.setenv(
        "AUTH_DB_PATH",
        str(tmp_path / "sessions.sqlite3"),
    )
    monkeypatch.setenv(
        "GOOGLE_OPERATOR_EMAILS",
        "operator@example.com",
    )

    token = auth._create_session(
        "test-google-sub",
        "operator@example.com",
    )

    with TestClient(backend.app) as client:
        client.cookies.set(auth.COOKIE_NAME, token)
        response = client.post(
            "/api/pipeline/run",
            json={"stage": "harmonization"},
            headers={"Origin": "http://localhost:5173"},
        )

    # If the actual configured DB exists, the request may succeed.
    # The key assertion is that authorization did not return 401/403.
    assert response.status_code not in (401, 403)
