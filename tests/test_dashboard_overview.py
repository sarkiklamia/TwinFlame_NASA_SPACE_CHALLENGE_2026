from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import duckdb
from fastapi.testclient import TestClient

from app.backend import main


def _create_database(path):
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, platform VARCHAR, source VARCHAR,
            latitude DOUBLE, longitude DOUBLE, acq_date DATE,
            acq_time VARCHAR, frp_mw DOUBLE, daynight VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_activity_clusters (
            activity_cluster_id VARCHAR, run_id VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_cluster_members (
            activity_cluster_id VARCHAR, detection_id VARCHAR, run_id VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_correspondence_edges (
            detection_id_a VARCHAR, detection_id_b VARCHAR,
            decision_class VARCHAR, run_id VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_correspondence_summary (
            date_utc DATE, platform_pair VARCHAR, strong_count INTEGER,
            possible_count INTEGER, rejected_count INTEGER, run_id VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_run_metadata (
            run_id VARCHAR, status VARCHAR, started_at_utc TIMESTAMP,
            finished_at_utc TIMESTAMP, duration_seconds DOUBLE,
            input_count BIGINT, activity_cluster_count BIGINT,
            correspondence_edge_count BIGINT
        )
        """
    )
    acquired = datetime.now(timezone.utc).date()
    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d1", "Terra", "MODIS", 1.0, 30.0, acquired, "1200", 20.0, "D"),
            ("d2", "Aqua", "MODIS", 2.0, 31.0, acquired, "1205", 30.0, "D"),
            ("d3", "Terra", "MODIS", 48.0, 10.0, acquired, "1210", 9.0, "D"),
        ],
    )
    connection.execute("INSERT INTO harm_activity_clusters VALUES ('c1', 'r1')")
    connection.execute(
        "INSERT INTO harm_cluster_members VALUES ('c1', 'd1', 'r1'), ('c1', 'd2', 'r1')"
    )
    connection.execute(
        """
        INSERT INTO harm_correspondence_edges VALUES
            ('d1', 'd2', 'STRONG', 'r1'),
            ('d1', 'd3', 'POSSIBLE', 'r1'),
            ('d2', 'd3', 'REJECTED', 'r1')
        """
    )
    connection.execute(
        "INSERT INTO harm_correspondence_summary VALUES (?, 'Terra-Aqua', 1, 1, 1, 'r1')",
        [acquired],
    )
    started = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=5)
    connection.execute(
        "INSERT INTO harm_run_metadata VALUES ('r1', 'completed', ?, ?, 60, 3, 1, 3)",
        [started, datetime.now(timezone.utc).replace(tzinfo=None)],
    )
    connection.close()


def test_overview_filters_all_panels_from_the_same_detection_set(tmp_path, monkeypatch):
    database_path = tmp_path / "dashboard.duckdb"
    _create_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)

    response = client.get(
        "/api/overview",
        params={
            "period": "today",
            "platform": "terra",
            "region": "africa",
            "daynight": "day",
            "frp_min": 10,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["total_detections"] == 1
    assert payload["kpis"]["activity_clusters"] == 1
    assert payload["kpis"]["strong_correspondences"] == 1
    assert payload["kpis"]["possible_correspondences"] == 1
    assert payload["kpis"]["unmatched_or_rejected"] == 0
    assert payload["platform_counts"] == [{"platform": "Terra", "detections": 1}]
    assert len(payload["map"]["points"]) == 1
    assert payload["correspondence_distribution"]["source"] == "filtered_edges"


def test_overview_rejects_reversed_frp_range(tmp_path, monkeypatch):
    database_path = tmp_path / "dashboard.duckdb"
    _create_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/overview",
        params={"frp_min": 20, "frp_max": 10},
    )

    assert response.status_code == 422
    assert "frp_min" in response.json()["detail"]


def test_overview_uses_daily_summary_for_unfiltered_correspondences(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "dashboard.duckdb"
    _create_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get("/api/overview", params={"period": "today"})

    assert response.status_code == 200
    distribution = response.json()["correspondence_distribution"]
    assert distribution == {
        "strong": 1,
        "possible": 1,
        "rejected": 1,
        "source": "daily_summary",
    }


def _create_monitoring_database(path, *, include_optional_columns=True):
    connection = duckdb.connect(str(path))
    optional_columns = (
        ", instrument VARCHAR, confidence VARCHAR, detection_status VARCHAR"
        if include_optional_columns
        else ""
    )
    connection.execute(
        f"""
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, platform VARCHAR, source VARCHAR,
            latitude DOUBLE, longitude DOUBLE, acq_date DATE,
            acq_time VARCHAR, frp_mw DOUBLE, daynight VARCHAR
            {optional_columns}
        )
        """
    )
    acquired = datetime.now(timezone.utc)
    if include_optional_columns:
        connection.executemany(
            "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "d1",
                    "Terra",
                    "MODIS_NRT",
                    1.0,
                    30.0,
                    acquired.date(),
                    acquired.strftime("%H%M"),
                    20.0,
                    "D",
                    "MODIS",
                    "85",
                    "new",
                ),
                (
                    "d2",
                    "NOAA-21",
                    "VIIRS_NOAA21_NRT",
                    2.0,
                    31.0,
                    acquired.date(),
                    acquired.strftime("%H%M"),
                    120.0,
                    "N",
                    "VIIRS",
                    "N",
                    "harmonized",
                ),
            ],
        )
        connection.execute(
            "CREATE TABLE SOURCE_FILES (file_name VARCHAR, retrieved_at_utc TIMESTAMP)"
        )
        connection.execute(
            "INSERT INTO SOURCE_FILES VALUES ('latest.csv', ?)",
            [acquired.replace(tzinfo=None) - timedelta(minutes=3)],
        )
    else:
        connection.execute(
            """
            INSERT INTO UNIFIED_DETECTIONS VALUES
                ('d1', 'Terra', 'MODIS_NRT', 1, 30, ?, '1200', 20, 'D')
            """,
            [acquired.date()],
        )
    connection.close()


def test_monitoring_returns_filtered_hotspots_and_retrieval_time(tmp_path, monkeypatch):
    database_path = tmp_path / "monitoring.duckdb"
    _create_monitoring_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/monitoring",
        params={
            "window": "1h",
            "platform": "terra",
            "sensor": "modis",
            "daynight": "day",
            "frp_min": 10,
            "confidence": "85",
            "status": "new",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_detections"] == 1
    assert payload["detections"][0]["id"] == "d1"
    assert payload["detections"][0]["native_confidence"] == "85"
    assert payload["detections"][0]["status"] == "new"
    assert payload["map_points"][0]["platform"] == "Terra"
    assert payload["retrieval_source"] == "SOURCE_FILES"
    assert payload["latest_retrieval_at"] is not None
    assert payload["frp_distribution"][0]["from_10_to_50"] == 1


def test_monitoring_reports_missing_optional_schema_fields(tmp_path, monkeypatch):
    database_path = tmp_path / "monitoring-minimal.duckdb"
    _create_monitoring_database(database_path, include_optional_columns=False)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get("/api/monitoring")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_detections"] == 1
    assert payload["capabilities"]["confidence_filter"] is False
    assert payload["capabilities"]["status_filter"] is False
    assert payload["latest_retrieval_at"] is None


def test_monitoring_requires_a_complete_custom_window(tmp_path, monkeypatch):
    database_path = tmp_path / "monitoring.duckdb"
    _create_monitoring_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/monitoring",
        params={"window": "custom", "start_at": "2026-11-14T10:00:00Z"},
    )

    assert response.status_code == 422
    assert "start_at and end_at" in response.json()["detail"]
