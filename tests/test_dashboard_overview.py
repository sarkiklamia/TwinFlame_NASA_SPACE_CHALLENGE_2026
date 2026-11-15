from datetime import datetime, timedelta, timezone
from pathlib import Path
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


def _create_canonical_detection_database(path):
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE unified_detections (
            detection_id BIGINT, acquisition_time_utc TIMESTAMP,
            platform VARCHAR, source VARCHAR, latitude DOUBLE,
            longitude DOUBLE, frp_mw DOUBLE, daynight VARCHAR
        )
        """
    )
    connection.execute(
        """
        INSERT INTO unified_detections VALUES
            (1, ?, 'Terra', 'MODIS', 34.1, -6.8, 12.5, 'D'),
            (2, ?, 'NOAA-21', 'VIIRS', 34.2, -6.9, 24.0, 'N')
        """,
        [datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
         datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)],
    )
    connection.close()


def test_canonical_timestamp_works_without_harmonization_tables(tmp_path, monkeypatch):
    database_path = tmp_path / "canonical.duckdb"
    _create_canonical_detection_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)

    overview_response = client.get("/api/overview", params={"period": "7d"})
    geospatial_response = client.get("/api/geospatial")

    assert overview_response.status_code == 200
    overview_payload = overview_response.json()
    assert overview_payload["kpis"]["total_detections"] == 2
    assert overview_payload["kpis"]["activity_clusters"] is None
    assert overview_payload["kpis"]["strong_correspondences"] is None
    assert overview_payload["harmonization_available"] is False

    assert geospatial_response.status_code == 200
    geospatial_payload = geospatial_response.json()
    assert len(geospatial_payload["detections"]) == 2
    assert geospatial_payload["clusters"] == []
    assert geospatial_payload["cluster_data_available"] is False


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
                ('d1', 'Terra', 'MODIS_NRT', 1, 30, ?, ?, 20, 'D')
            """,
            [acquired.date(), acquired.strftime('%H%M')],
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


def _create_geospatial_database(path):
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, platform VARCHAR, source VARCHAR,
            instrument VARCHAR, latitude DOUBLE, longitude DOUBLE,
            acq_date DATE, acq_time VARCHAR, frp_mw DOUBLE, daynight VARCHAR,
            country VARCHAR
        )
        """
    )
    connection.execute(
        "CREATE TABLE harm_activity_clusters (activity_cluster_id VARCHAR, run_id VARCHAR)"
    )
    connection.execute(
        """
        CREATE TABLE harm_cluster_members (
            activity_cluster_id VARCHAR, detection_id VARCHAR,
            run_id VARCHAR, membership_quality VARCHAR
        )
        """
    )
    acquired = datetime.now(timezone.utc)
    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d1", "Terra", "MODIS_NRT", "MODIS", 1.0, 30.0, acquired.date(), "1200", 20.0, "D", "Kenya"),
            ("d2", "Aqua", "MODIS_NRT", "MODIS", 1.2, 30.2, acquired.date(), "1210", 35.0, "D", "Kenya"),
            ("d3", "NOAA-21", "VIIRS_NOAA21_NRT", "VIIRS", 20.0, 40.0, acquired.date(), "1220", 90.0, "N", "Ethiopia"),
        ],
    )
    connection.execute(
        "INSERT INTO harm_activity_clusters VALUES ('c1', 'r1'), ('c2', 'r1')"
    )
    connection.execute(
        """
        INSERT INTO harm_cluster_members VALUES
            ('c1', 'd1', 'r1', 'strong'),
            ('c1', 'd2', 'r1', 'possible'),
            ('c2', 'd3', 'r1', 'strong')
        """
    )
    connection.close()


def test_geospatial_filters_aoi_and_builds_cluster_summaries(tmp_path, monkeypatch):
    database_path = tmp_path / "geospatial.duckdb"
    _create_geospatial_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/geospatial",
        params={
            "aoi": '{"type":"rectangle","south":0,"west":29,"north":3,"east":32}',
            "min_cluster_size": 2,
            "membership_quality": "all",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_detections"] == 2
    assert {item["id"] for item in payload["detections"]} == {"d1", "d2"}
    assert len(payload["clusters"]) == 1
    cluster = payload["clusters"][0]
    assert cluster["id"] == "c1"
    assert cluster["member_count"] == 2
    assert cluster["platforms"] == ["Aqua", "Terra"]
    assert cluster["extent_km"] > 0
    assert payload["density_cells"][0]["count"] == 2
    assert payload["size_distribution"][0] == {"bucket": "1-5", "count": 1}


def test_geospatial_filters_by_country_platform_and_membership_quality(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "geospatial.duckdb"
    _create_geospatial_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/geospatial",
        params={
            "platform": "terra",
            "country": "Kenya",
            "membership_quality": "strong",
            "min_cluster_size": 1,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["id"] for item in payload["detections"]] == ["d1"]
    assert payload["clusters"][0]["member_count"] == 1
    assert payload["capabilities"]["country_filter"] is True
    assert payload["capabilities"]["membership_quality_filter"] is True


def test_geospatial_cluster_inspection_returns_member_detections(tmp_path, monkeypatch):
    database_path = tmp_path / "geospatial.duckdb"
    _create_geospatial_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/geospatial/clusters/c1/members",
        params={"run_id": "r1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_members"] == 2
    assert {member["id"] for member in payload["members"]} == {"d1", "d2"}


def _create_fire_season_database(path):
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, platform VARCHAR, source VARCHAR,
            instrument VARCHAR, latitude DOUBLE, longitude DOUBLE,
            acq_date DATE, frp_mw DOUBLE, daynight VARCHAR
        )
        """
    )
    connection.execute(
        "CREATE TABLE harm_activity_clusters (activity_cluster_id VARCHAR, run_id VARCHAR)"
    )
    connection.execute(
        """
        CREATE TABLE harm_cluster_members (
            activity_cluster_id VARCHAR, detection_id VARCHAR, run_id VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d1", "Terra", "MODIS_NRT", "MODIS", 1, 30, "2024-01-15", 10, "D"),
            ("d2", "Terra", "MODIS_NRT", "MODIS", 2, 32, "2024-01-20", 30, "D"),
            ("d3", "NOAA-21", "VIIRS_NOAA21_NRT", "VIIRS", 20, 40, "2024-07-10", 100, "N"),
            ("d4", "Aqua", "MODIS_NRT", "MODIS", -20, -60, "2025-01-05", 50, "D"),
            ("d5", "NOAA-21", "VIIRS_NOAA21_NRT", "VIIRS", 35, -100, "2025-08-03", 60, "D"),
        ],
    )
    connection.execute(
        """
        INSERT INTO harm_activity_clusters VALUES
            ('c1', 'r1'), ('c2', 'r1'), ('c3', 'r1'), ('c4', 'r1')
        """
    )
    connection.execute(
        """
        INSERT INTO harm_cluster_members VALUES
            ('c1', 'd1', 'r1'), ('c1', 'd2', 'r1'),
            ('c2', 'd3', 'r1'), ('c3', 'd4', 'r1'), ('c4', 'd5', 'r1')
        """
    )
    connection.close()


def test_fire_season_returns_monthly_annual_and_regional_metrics(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "fire-season.duckdb"
    _create_fire_season_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get(
        "/api/fire-season",
        params={"platform": "terra", "region": "africa", "daynight": "day"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["available_years"] == [2024]
    assert payload["monthly"] == [
        {
            "year": 2024,
            "month": 1,
            "detections": 2,
            "frp_observations": 2,
            "mean_frp": 20.0,
            "median_frp": 20.0,
            "total_frp": 40.0,
            "activity_clusters": 1,
        }
    ]
    assert payload["annual"][0]["detections"] == 2
    assert payload["annual"][0]["activity_clusters"] == 1
    assert payload["climatology"][0]["month"] == 1
    assert payload["climatology"][0]["detections"] == 2
    assert payload["sensor_climatology"] == [
        {"sensor": "MODIS", "month": 1, "detections": 2}
    ]
    assert payload["capabilities"]["activity_clusters"] is True
    assert payload["sources"]["detection_metrics"] == "UNIFIED_DETECTIONS"
    assert any(
        row["region"] == "africa" and row["month"] == 1
        for row in payload["regional_activity"]
    )


def test_fire_season_supports_detection_only_schemas(tmp_path, monkeypatch):
    database_path = tmp_path / "fire-season-minimal.duckdb"
    _create_monitoring_database(database_path, include_optional_columns=False)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    response = TestClient(main.app).get("/api/fire-season")

    assert response.status_code == 200
    payload = response.json()
    assert payload["monthly"][0]["detections"] == 1
    assert payload["monthly"][0]["mean_frp"] == 20
    assert payload["capabilities"]["activity_clusters"] is False
    assert payload["capabilities"]["daynight"] is True


def _create_historical_database(path):
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, platform VARCHAR, source VARCHAR,
            instrument VARCHAR, latitude DOUBLE, longitude DOUBLE,
            acq_date DATE, acq_time VARCHAR, frp_mw DOUBLE,
            confidence VARCHAR, daynight VARCHAR
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
        CREATE TABLE harm_sensor_activity_daily (
            date_utc DATE, sensor VARCHAR, observation_count BIGINT,
            mean_frp DOUBLE, median_frp DOUBLE, p90_frp DOUBLE, total_frp DOUBLE
        )
        """
    )
    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d1", "Terra", "MODIS_NRT", "MODIS", 1.0, 30.0, "2023-05-10", "1100", 25.0, "95", "D"),
            ("d2", "Aqua", "MODIS_NRT", "MODIS", 2.0, 32.0, "2023-05-15", "1330", 50.0, "85", "D"),
            ("d3", "NOAA-20", "VIIRS_NOAA20_NRT", "VIIRS", 38.0, -100.0, "2023-08-20", "2200", 110.0, "h", "N"),
            ("d4", "NOAA-21", "VIIRS_NOAA21_NRT", "VIIRS", -15.0, -50.0, "2024-02-12", "1400", 65.0, "n", "D"),
            ("d5", "Terra", "MODIS_NRT", "MODIS", 45.0, 10.0, "2024-07-04", "1045", 30.0, "70", "D"),
        ],
    )
    connection.execute(
        """
        INSERT INTO harm_activity_clusters VALUES
            ('c1', 'r1'), ('c2', 'r1'), ('c3', 'r2')
        """
    )
    connection.execute(
        """
        INSERT INTO harm_cluster_members VALUES
            ('c1', 'd1', 'r1'), ('c1', 'd2', 'r1'),
            ('c2', 'd3', 'r1'),
            ('c3', 'd4', 'r2')
        """
    )
    connection.execute(
        """
        INSERT INTO harm_sensor_activity_daily VALUES
            ('2023-05-10', 'MODIS', 1, 25.0, 25.0, 25.0, 25.0),
            ('2023-05-15', 'MODIS', 1, 50.0, 50.0, 50.0, 50.0),
            ('2023-08-20', 'VIIRS', 1, 110.0, 110.0, 110.0, 110.0),
            ('2024-02-12', 'VIIRS', 1, 65.0, 65.0, 65.0, 65.0),
            ('2024-07-04', 'MODIS', 1, 30.0, 30.0, 30.0, 30.0)
        """
    )
    connection.close()


def test_historical_analysis_full_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "historical_full.duckdb"
    _create_historical_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    client = TestClient(main.app)
    response = client.get(
        "/api/historical-analysis",
        params={
            "start_date": "2023-01-01",
            "end_date": "2024-12-31",
            "temporal_aggregation": "yearly",
            "spatial_aggregation": "grid",
            "grid_resolution": 5.0,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_kpis"]["total_detections"] == 5
    assert payload["summary_kpis"]["total_clusters"] == 3
    assert payload["summary_kpis"]["mean_frp"] == 56.0
    assert payload["summary_kpis"]["peak_frp"] == 110.0
    assert len(payload["detection_trend"]) == 2  # 2023 and 2024
    assert payload["sources"]["historical_detection_trend"] == "UNIFIED_DETECTIONS"
    assert payload["sources"]["frp_evolution"] == "harm_sensor_activity_daily"
    assert payload["capabilities"]["activity_clusters"] is True
    assert payload["spatial_distribution"]["mode"] == "grid"
    assert len(payload["spatial_distribution"]["grid_cells"]) > 0
    assert len(payload["regional_comparison"]) >= 3


def test_historical_analysis_detection_only_schema(tmp_path, monkeypatch):
    database_path = tmp_path / "historical_minimal.duckdb"
    _create_monitoring_database(database_path, include_optional_columns=False)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    client = TestClient(main.app)
    response = client.get("/api/historical-analysis")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary_kpis"]["total_detections"] == 1
    assert payload["summary_kpis"]["total_clusters"] is None
    assert payload["sources"]["frp_evolution"] == "UNIFIED_DETECTIONS"
    assert payload["capabilities"]["activity_clusters"] is False


def test_historical_analysis_export_csv_and_geojson(tmp_path, monkeypatch):
    database_path = tmp_path / "historical_export.duckdb"
    _create_historical_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )

    client = TestClient(main.app)

    # 1. Observations CSV
    csv_resp = client.get("/api/historical-analysis/export", params={"export_type": "observations", "format": "csv"})
    assert csv_resp.status_code == 200
    assert "text/csv" in csv_resp.headers["content-type"]
    assert "detection_id,acq_date,acq_time" in csv_resp.text
    assert "Terra" in csv_resp.text

    # 2. Observations GeoJSON
    geojson_resp = client.get("/api/historical-analysis/export", params={"export_type": "observations", "format": "geojson"})
    assert geojson_resp.status_code == 200
    assert "application/geo+json" in geojson_resp.headers["content-type"]
    geo_data = geojson_resp.json()
    assert geo_data["type"] == "FeatureCollection"
    assert len(geo_data["features"]) == 5

    # 3. Aggregated CSV
    agg_resp = client.get("/api/historical-analysis/export", params={"export_type": "aggregated", "format": "csv", "temporal_aggregation": "yearly"})
    assert agg_resp.status_code == 200
    assert "period,detections,mean_frp" in agg_resp.text


def test_sensor_comparison_rejects_same_platform(tmp_path, monkeypatch):
    database_path = tmp_path / "sensor_comp.duckdb"
    _create_historical_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)
    response = client.get(
        "/api/sensor-comparison",
        params={"platform_a": "terra", "platform_b": "terra"},
    )
    assert response.status_code == 422
    assert "Platform A and Platform B must be different platforms" in response.json()["detail"]


def test_sensor_comparison_returns_metrics_and_specs(tmp_path, monkeypatch):
    database_path = tmp_path / "sensor_comp_metrics.duckdb"
    _create_historical_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)
    response = client.get(
        "/api/sensor-comparison",
        params={
            "platform_a": "terra",
            "platform_b": "noaa20",
            "region": "global",
            "daynight": "all",
            "temporal_window_minutes": 120,
            "spatial_threshold_meters": 5000,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["platform_a"]["id"] == "terra"
    assert payload["platform_b"]["id"] == "noaa20"
    assert payload["platform_a"]["specs"]["instrument"] == "MODIS"
    assert payload["platform_b"]["specs"]["instrument"] == "VIIRS"
    assert payload["detection_counts"]["platform_a"] == 2  # d1 & d5 in _create_historical_database
    assert payload["detection_counts"]["platform_b"] == 1  # d3 in _create_historical_database
    assert len(payload["frp_distribution"]) == 6
    assert len(payload["diurnal_distribution"]) == 24
    assert "scientific_caution" in payload
    assert "Differences in detection counts do not necessarily mean one sensor is better" in payload["scientific_caution"]


def _create_harmonization_database(database_path: Path) -> None:
    connection = duckdb.connect(str(database_path))
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, platform VARCHAR, product VARCHAR, instrument VARCHAR,
            latitude DOUBLE, longitude DOUBLE, acq_date DATE, acq_time VARCHAR,
            frp_mw DOUBLE, native_confidence VARCHAR, daynight VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_correspondence_edges (
            detection_id_a VARCHAR,
            detection_id_b VARCHAR,
            decision_class VARCHAR,
            spatial_distance_m DOUBLE,
            time_difference_minutes DOUBLE,
            iou DOUBLE,
            containment DOUBLE,
            geometry_quality VARCHAR,
            decision_reason VARCHAR,
            platform_pair VARCHAR,
            run_id VARCHAR
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
        CREATE TABLE harm_run_metadata (
            run_id VARCHAR, status VARCHAR, started_at_utc TIMESTAMP,
            finished_at_utc TIMESTAMP, duration_seconds DOUBLE,
            input_count BIGINT, activity_cluster_count BIGINT,
            correspondence_edge_count BIGINT
        )
        """
    )
    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("det_t1", "Terra", "MODIS_NRT", "MODIS", 34.05, -118.25, "2024-06-15", "1100", 45.0, "90", "D"),
            ("det_v1", "NOAA-20", "VIIRS_NOAA20_NRT", "VIIRS", 34.052, -118.248, "2024-06-15", "1115", 52.0, "h", "D"),
            ("det_a1", "Aqua", "MODIS_NRT", "MODIS", 37.77, -122.41, "2024-06-16", "1330", 110.0, "85", "D"),
            ("det_v2", "NOAA-21", "VIIRS_NOAA21_NRT", "VIIRS", 37.78, -122.39, "2024-06-16", "1410", 95.0, "h", "D"),
            ("det_t2", "Terra", "MODIS_NRT", "MODIS", 40.71, -74.00, "2024-06-17", "1045", 25.0, "60", "D"),
            ("det_v3", "NOAA-20", "VIIRS_NOAA20_NRT", "VIIRS", 40.79, -73.85, "2024-06-17", "1300", 15.0, "l", "D"),
        ],
    )
    connection.executemany(
        "INSERT INTO harm_correspondence_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "det_t1", "det_v1", "STRONG", 320.0, 15.0, 0.58, 0.88,
                "High", "Spatio-temporal intersection (IoU >= 0.20) within orbital coincidence window",
                "Terra – NOAA-20", "run_2024_06"
            ),
            (
                "det_a1", "det_v2", "POSSIBLE", 1850.0, 40.0, 0.22, 0.45,
                "Nominal", "Active fire cluster proximity with partial boundary overlap",
                "Aqua – NOAA-21", "run_2024_06"
            ),
            (
                "det_t2", "det_v3", "REJECTED", 14500.0, 135.0, 0.02, 0.05,
                "Degraded", "Centroid distance exceeds maximum spatial threshold (>3.0 km)",
                "Terra – NOAA-20", "run_2024_06"
            ),
        ],
    )
    connection.execute("INSERT INTO harm_activity_clusters VALUES ('c1', 'run_2024_06'), ('c2', 'run_2024_06')")
    connection.execute(
        """
        INSERT INTO harm_cluster_members VALUES
            ('c1', 'det_t1', 'run_2024_06'),
            ('c1', 'det_v1', 'run_2024_06'),
            ('c2', 'det_a1', 'run_2024_06')
        """
    )
    connection.execute(
        """
        INSERT INTO harm_run_metadata VALUES
            ('run_2024_06', 'SUCCESS', '2024-06-18 00:00:00', '2024-06-18 00:05:00', 300.0, 6, 2, 3)
        """
    )
    connection.close()


def test_harmonization_evaluation_endpoint(tmp_path, monkeypatch):
    database_path = tmp_path / "harmonization_eval.duckdb"
    _create_harmonization_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)
    response = client.get("/api/harmonization-evaluation")
    assert response.status_code == 200
    payload = response.json()

    # 1. Summary KPIs
    kpis = payload["summary_kpis"]
    assert kpis["total_candidates"] == 3
    assert kpis["strong_count"] == 1
    assert kpis["possible_count"] == 1
    assert kpis["rejected_count"] == 1
    assert kpis["insufficient_geometry_count"] == 0
    assert kpis["acceptance_rate_pct"] == 66.7  # (1 + 1) / 3 * 100
    assert kpis["strong_rate_pct"] == 33.3
    assert kpis["rejection_rate_pct"] == 33.3
    assert kpis["mean_distance_km"] > 0
    assert kpis["mean_iou"] > 0

    # 2. Decision Distribution
    assert len(payload["decision_distribution"]) == 4
    dec_dict = {d["decision"]: d["count"] for d in payload["decision_distribution"]}
    assert dec_dict["STRONG"] == 1
    assert dec_dict["POSSIBLE"] == 1
    assert dec_dict["REJECTED"] == 1

    # 3. Distributions
    assert len(payload["spatial_distance_distribution"]) == 6
    assert len(payload["temporal_difference_distribution"]) == 5
    assert len(payload["iou_distribution"]) == 6
    assert len(payload["platform_pair_quality"]) >= 2

    # 4. Cluster Composition
    cluster_comp = payload["cluster_composition"]
    assert cluster_comp["total_clusters"] == 2
    assert cluster_comp["cross_sensor_clusters"] == 1  # c1 has Terra (MODIS) + NOAA-20 (VIIRS)
    assert cluster_comp["cross_sensor_pct"] == 50.0

    # 5. Inspection Candidates
    candidates = payload["inspection_candidates"]
    assert len(candidates) == 3
    cand0 = candidates[0]
    assert "edge_id" in cand0
    assert "decision_class" in cand0
    assert "decision_reason" in cand0
    assert "geometry_quality" in cand0
    assert "distance_km" in cand0
    assert "time_difference_minutes" in cand0
    assert "iou" in cand0
    assert "containment" in cand0
    assert "detection_a" in cand0
    assert "detection_b" in cand0
    assert cand0["detection_a"]["id"] in ("det_t1", "det_a1", "det_t2")
    assert cand0["detection_a"]["latitude"] != 0.0

    # 6. Runs & Versions
    assert "run_2024_06" in payload["available_runs"]
    assert len(payload["available_versions"]) >= 1


def test_harmonization_evaluation_filters(tmp_path, monkeypatch):
    database_path = tmp_path / "harmonization_eval_filtered.duckdb"
    _create_harmonization_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)

    # Filter by platform pair: terra_noaa20
    resp_pair = client.get("/api/harmonization-evaluation", params={"platform_pair": "terra_noaa20"})
    assert resp_pair.status_code == 200
    data_pair = resp_pair.json()
    assert data_pair["summary_kpis"]["total_candidates"] == 2
    for cand in data_pair["inspection_candidates"]:
        assert "Terra" in cand["platform_pair"] and "NOAA-20" in cand["platform_pair"]

    # Filter by decision class: strong
    resp_strong = client.get("/api/harmonization-evaluation", params={"decision_class": "strong"})
    assert resp_strong.status_code == 200
    data_strong = resp_strong.json()
    assert data_strong["summary_kpis"]["total_candidates"] == 1
    assert data_strong["inspection_candidates"][0]["decision_class"] == "STRONG"

    # Filter by min_iou: 0.50
    resp_iou = client.get("/api/harmonization-evaluation", params={"min_iou": 0.50})
    assert resp_iou.status_code == 200
    data_iou = resp_iou.json()
    assert data_iou["summary_kpis"]["total_candidates"] == 1
    assert data_iou["inspection_candidates"][0]["iou"] >= 0.50






def _create_quality_database(database_path: Path) -> None:
    connection = duckdb.connect(str(database_path))
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, id BIGINT, source VARCHAR, platform VARCHAR,
            latitude FLOAT, longitude FLOAT, acq_date DATE, acq_time VARCHAR,
            confidence_native VARCHAR, frp_mw FLOAT, brightness FLOAT,
            bright_t31 FLOAT, bright_ti4 FLOAT, bright_ti5 FLOAT,
            scan_km FLOAT, track_km FLOAT, daynight VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE SOURCE_FILES (
            file_id BIGINT, filename VARCHAR, platform VARCHAR,
            product_version VARCHAR, retrieval_time TIMESTAMP,
            checksum VARCHAR, ingestion_id BIGINT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE PROCESSING_RUNS (
            processing_id BIGINT, input_file_id BIGINT,
            processing_version VARCHAR, start_time TIMESTAMP, status VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_correspondence_edges (
            correspondence_edge_id VARCHAR, detection_id_a VARCHAR, detection_id_b VARCHAR,
            platform_a VARCHAR, platform_b VARCHAR, time_difference_minutes DOUBLE,
            centre_distance_km DOUBLE, intersection_area_km2 DOUBLE, iou DOUBLE,
            containment_a DOUBLE, containment_b DOUBLE, normalized_centre_distance DOUBLE,
            decision_class VARCHAR, decision_reason VARCHAR, geometry_quality VARCHAR,
            run_id VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_run_metadata (
            run_id VARCHAR, algorithm_version VARCHAR, config_id VARCHAR,
            started_at_utc TIMESTAMP, finished_at_utc TIMESTAMP, duration_seconds DOUBLE,
            status VARCHAR, input_count BIGINT, candidate_count BIGINT,
            correspondence_edge_count BIGINT, activity_cluster_count BIGINT,
            failed_stage VARCHAR, error_summary VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE DATA_QUALITY_REPORTS (
            report_id VARCHAR, run_id VARCHAR, generated_at TIMESTAMP,
            total_records BIGINT, valid_records BIGINT, invalid_coordinates BIGINT,
            missing_frp BIGINT, invalid_frp BIGINT, missing_timestamps BIGINT,
            duplicate_detections BIGINT, insufficient_geometry BIGINT,
            completeness_pct DOUBLE, quality_status VARCHAR, summary_notes VARCHAR
        )
        """
    )

    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d1", 1, "MODIS_NRT", "Terra", 34.05, -118.25, "2024-06-15", "1100", "90", 45.0, 330.0, 305.0, 330.0, 305.0, 1.0, 1.0, "D"),
            ("d2", 2, "VIIRS_NRT", "NOAA-20", 34.052, -118.248, "2024-06-15", "1115", "h", 52.0, 335.0, 310.0, 335.0, 310.0, 0.4, 0.4, "D"),
            ("d3", 3, "MODIS_NRT", "Aqua", 37.77, -122.41, "2024-06-16", "1330", "85", 110.0, 350.0, 315.0, 350.0, 315.0, 1.2, 1.1, "D"),
            ("d4", 4, "VIIRS_NRT", "NOAA-21", 37.78, -122.39, "2024-06-16", "1410", "h", 95.0, 345.0, 312.0, 345.0, 312.0, 0.4, 0.4, "D"),
            ("d_bad_frp", 5, "MODIS_NRT", "Terra", 40.71, -74.00, "2024-06-17", "1045", "60", None, 300.0, 290.0, 300.0, 290.0, 1.0, 1.0, "D"),
            ("d_bad_coord", 6, "VIIRS_NRT", "NOAA-20", 0.0, 0.0, "2024-06-17", "1300", "l", 15.0, 310.0, 295.0, 310.0, 295.0, 0.4, 0.4, "D"),
            ("d_dup_1", 7, "MODIS_NRT", "Terra", 42.0, -71.0, "2024-06-18", "1100", "80", 30.0, 320.0, 300.0, 320.0, 300.0, 1.0, 1.0, "D"),
            ("d_dup_2", 8, "MODIS_NRT", "Terra", 42.0, -71.0, "2024-06-18", "1100", "80", 30.0, 320.0, 300.0, 320.0, 300.0, 1.0, 1.0, "D"),
        ],
    )
    connection.execute(
        """
        INSERT INTO SOURCE_FILES VALUES
            (2001, 'MODIS_C61_Global_7d.csv', 'Terra', 'MODIS_C61', TIMESTAMP '2024-06-18 10:00:00', 'hash123', 1001),
            (2002, 'VIIRS_J1_NRT_USA.csv', 'NOAA-20', 'VIIRS_VNP14IMG', TIMESTAMP '2024-06-18 10:30:00', 'hash456', 1002)
        """
    )
    connection.execute(
        """
        INSERT INTO PROCESSING_RUNS VALUES
            (3001, 2001, 'v2.5', TIMESTAMP '2024-06-18 10:05:00', 'SUCCESS'),
            (3002, 2002, 'v2.5', TIMESTAMP '2024-06-18 10:35:00', 'SUCCESS')
        """
    )
    connection.execute(
        """
        INSERT INTO harm_correspondence_edges VALUES
            ('e1', 'd1', 'd2', 'Terra', 'NOAA-20', 15.0, 0.32, 0.15, 0.58, 0.88, 0.92, 0.25, 'STRONG', 'IoU >= 0.20', 'High', 'run_test'),
            ('e2', 'd3', 'd4', 'Aqua', 'NOAA-21', 40.0, 1.85, 0.05, 0.22, 0.45, 0.50, 0.65, 'POSSIBLE', 'Cluster proximity', 'Nominal', 'run_test'),
            ('e3', 'd_bad_frp', 'd_bad_coord', 'Terra', 'NOAA-20', 135.0, 14.5, 0.0, 0.02, 0.05, 0.05, 4.5, 'INSUFFICIENT_GEOMETRY', 'Scan angle > 55 deg', 'Insufficient', 'run_test')
        """
    )
    connection.execute(
        """
        INSERT INTO DATA_QUALITY_REPORTS VALUES
            ('rep_01', 'run_test', TIMESTAMP '2024-06-18 11:00:00', 8, 5, 1, 1, 0, 0, 1, 1, 62.5, 'DEGRADED', 'Test validation report')
        """
    )
    connection.close()


def test_quality_methodology_endpoint(tmp_path, monkeypatch):
    database_path = tmp_path / "quality_methodology.duckdb"
    _create_quality_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)
    response = client.get("/api/quality-methodology")
    assert response.status_code == 200
    payload = response.json()

    # 1. Summary KPIs
    kpis = payload["summary_kpis"]
    assert kpis["total_detections_audited"] == 8
    assert kpis["missing_values_count"] >= 1
    assert kpis["invalid_coordinates_count"] >= 1
    assert kpis["duplicate_detections_count"] >= 1
    assert kpis["insufficient_geometry_count"] >= 1
    assert kpis["quality_status"] in ("EXCELLENT", "NOMINAL", "DEGRADED", "ACTION_REQUIRED")

    # 2. Issues Breakdown
    issues = payload["quality_issues_breakdown"]
    assert len(issues) == 6
    issue_keys = {i["issue_key"] for i in issues}
    assert "missing_values" in issue_keys
    assert "invalid_coordinates" in issue_keys
    assert "duplicate_detections" in issue_keys
    assert "invalid_frp" in issue_keys
    assert "invalid_timestamps" in issue_keys
    assert "insufficient_geometry" in issue_keys

    # 3. Platform Completeness
    platforms = payload["platform_completeness"]
    assert len(platforms) >= 3

    # 4. Source Files & Processing Runs Audits
    assert len(payload["source_files_audit"]) == 2
    assert payload["source_files_audit"][0]["filename"] in ("MODIS_C61_Global_7d.csv", "VIIRS_J1_NRT_USA.csv")
    assert len(payload["processing_runs_audit"]) == 2

    # 5. Scientific Methodology Documentation Structure
    meth = payload["scientific_methodology"]
    assert len(meth["data_sources"]) == 2
    assert len(meth["standardization_pipeline"]) == 4
    assert meth["matching_criteria"]["spatial_threshold_km"] == 3.0
    assert meth["matching_criteria"]["temporal_window_minutes"] == 120.0
    assert len(meth["decision_classes"]) == 4
    assert "DBSCAN" in meth["clustering_algorithm"]["algorithm"]
    assert len(meth["version_history"]) >= 4

    # 6. Preserved Reports
    assert len(payload["data_quality_reports"]) == 1
    assert payload["data_quality_reports"][0]["report_id"] == "rep_01"


def test_quality_methodology_filters(tmp_path, monkeypatch):
    database_path = tmp_path / "quality_methodology_filtered.duckdb"
    _create_quality_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)

    # Filter by platform: terra
    resp_plat = client.get("/api/quality-methodology", params={"platform": "terra"})
    assert resp_plat.status_code == 200
    data_plat = resp_plat.json()
    assert data_plat["summary_kpis"]["total_detections_audited"] == 4

    # Filter by quality issue: invalid_coordinates
    resp_issue = client.get("/api/quality-methodology", params={"quality_issue": "invalid_coordinates"})
    assert resp_issue.status_code == 200
    data_issue = resp_issue.json()
    assert data_issue["summary_kpis"]["total_detections_audited"] == 1

    # Filter by quality issue: invalid_frp
    resp_frp = client.get("/api/quality-methodology", params={"quality_issue": "invalid_frp"})
    assert resp_frp.status_code == 200
    data_frp = resp_frp.json()
    assert data_frp["summary_kpis"]["total_detections_audited"] == 1


def _create_pipeline_database(database_path: Path) -> None:
    connection = duckdb.connect(str(database_path))
    connection.execute(
        """
        CREATE TABLE INGESTION_RUNS (
            ingestion_id BIGINT PRIMARY KEY,
            source_type VARCHAR,
            start_time TIMESTAMP,
            end_time TIMESTAMP,
            status VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE SOURCE_FILES (
            file_id BIGINT PRIMARY KEY,
            filename VARCHAR,
            platform VARCHAR,
            product_version VARCHAR,
            retrieval_time TIMESTAMP,
            checksum VARCHAR,
            ingestion_id BIGINT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE PROCESSING_RUNS (
            processing_id BIGINT PRIMARY KEY,
            input_file_id BIGINT,
            processing_version VARCHAR,
            start_time TIMESTAMP,
            status VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR, id BIGINT, source VARCHAR, platform VARCHAR,
            latitude FLOAT, longitude FLOAT, acq_date DATE, acq_time VARCHAR,
            confidence_native VARCHAR, frp_mw FLOAT, brightness FLOAT,
            bright_t31 FLOAT, bright_ti4 FLOAT, bright_ti5 FLOAT,
            scan_km FLOAT, track_km FLOAT, daynight VARCHAR
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE harm_run_metadata (
            run_id VARCHAR PRIMARY KEY,
            algorithm_version VARCHAR,
            config_id VARCHAR,
            started_at_utc TIMESTAMP,
            finished_at_utc TIMESTAMP,
            duration_seconds DOUBLE,
            status VARCHAR,
            input_count BIGINT,
            candidate_count BIGINT,
            correspondence_edge_count BIGINT,
            activity_cluster_count BIGINT,
            failed_stage VARCHAR,
            error_summary VARCHAR
        )
        """
    )

    connection.execute(
        """
        INSERT INTO INGESTION_RUNS VALUES
            (1001, 'FIRMS API', TIMESTAMP '2024-06-15 10:00:00', TIMESTAMP '2024-06-15 10:08:00', 'COMPLETED'),
            (1002, 'Historical Archive', TIMESTAMP '2024-06-16 10:00:00', TIMESTAMP '2024-06-16 10:15:00', 'COMPLETED'),
            (1003, 'Sample', TIMESTAMP '2024-06-17 10:00:00', NULL, 'RUNNING')
        """
    )
    connection.execute(
        """
        INSERT INTO SOURCE_FILES VALUES
            (2001, 'MODIS_Terra_Global.csv', 'Terra', 'MODIS_C61', TIMESTAMP '2024-06-15 10:05:00', 'hash111', 1001),
            (2002, 'VIIRS_NOAA20_Global.csv', 'NOAA-20', 'VIIRS_VNP14IMG', TIMESTAMP '2024-06-16 10:10:00', 'hash222', 1002)
        """
    )
    connection.execute(
        """
        INSERT INTO PROCESSING_RUNS VALUES
            (3001, 2001, 'v2.5', TIMESTAMP '2024-06-15 10:10:00', 'COMPLETED'),
            (3002, 2002, 'v2.5', TIMESTAMP '2024-06-16 10:20:00', 'COMPLETED'),
            (3003, 2002, 'v2.4', TIMESTAMP '2024-06-17 10:20:00', 'FAILED')
        """
    )
    connection.executemany(
        "INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("d1", 1, "MODIS_NRT", "Terra", 34.05, -118.25, "2024-06-15", "1100", "90", 45.0, 330.0, 305.0, 330.0, 305.0, 1.0, 1.0, "D"),
            ("d2", 2, "VIIRS_NRT", "NOAA-20", 34.052, -118.248, "2024-06-15", "1115", "h", 52.0, 335.0, 310.0, 335.0, 310.0, 0.4, 0.4, "D"),
            ("d3", 3, "MODIS_NRT", "Aqua", 37.77, -122.41, "2024-06-16", "1330", "85", 110.0, 350.0, 315.0, 350.0, 315.0, 1.2, 1.1, "D"),
        ],
    )
    connection.execute(
        """
        INSERT INTO harm_run_metadata VALUES
            ('run_2024_06_test_success', 'v2.5', 'cfg_default', TIMESTAMP '2024-06-16 11:00:00', TIMESTAMP '2024-06-16 11:05:00', 300.0, 'COMPLETED', 100, 30, 10, 2, NULL, NULL),
            ('run_2024_06_test_failed', 'v2.5', 'cfg_default', TIMESTAMP '2024-06-17 11:00:00', TIMESTAMP '2024-06-17 11:02:00', 120.0, 'FAILED', 80, 20, 0, 0, 'Geometric Intersection Over Union', 'Scan angle deformation > 60 deg')
        """
    )
    connection.close()


def test_pipeline_management_endpoint(tmp_path, monkeypatch):
    database_path = tmp_path / "pipeline_mgmt.duckdb"
    _create_pipeline_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)
    response = client.get("/api/pipeline-management")
    assert response.status_code == 200
    payload = response.json()

    # 1. Summary KPIs
    kpis = payload["summary_kpis"]
    assert kpis["total_runs"] >= 8
    assert kpis["completed_runs"] >= 5
    assert kpis["failed_runs"] >= 2
    assert kpis["success_rate_pct"] > 60.0
    assert kpis["avg_duration_seconds"] > 0
    assert kpis["total_input_records"] >= 180

    # 2. Stage success rates
    stages = payload["stage_success_rates"]
    assert len(stages) == 3
    stage_names = {s["stage"] for s in stages}
    assert "Ingestion" in stage_names
    assert "Standardization" in stage_names
    assert "Harmonization" in stage_names

    # 3. Telemetry datasets
    assert len(payload["harmonization_runs"]) >= 2
    assert len(payload["ingestion_runs"]) == 3
    assert len(payload["source_files_overview"]) == 2
    assert len(payload["processing_runs"]) == 3
    assert len(payload["duration_trend"]) >= 2
    assert payload["records_funnel"]["input_records"] >= 180


def test_pipeline_management_filters(tmp_path, monkeypatch):
    database_path = tmp_path / "pipeline_mgmt_filters.duckdb"
    _create_pipeline_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)

    # Filter by status: failed
    resp_failed = client.get("/api/pipeline-management", params={"status": "failed"})
    assert resp_failed.status_code == 200
    data_failed = resp_failed.json()
    assert len(data_failed["harmonization_runs"]) == 1
    assert data_failed["harmonization_runs"][0]["status"] == "FAILED"
    assert data_failed["harmonization_runs"][0]["failed_stage"] == "Geometric Intersection Over Union"

    # Filter by run_id
    resp_run = client.get("/api/pipeline-management", params={"run_id": "test_success"})
    assert resp_run.status_code == 200
    data_run = resp_run.json()
    assert len(data_run["harmonization_runs"]) == 1
    assert data_run["harmonization_runs"][0]["run_id"] == "run_2024_06_test_success"


def test_pipeline_run_execution(tmp_path, monkeypatch):
    database_path = tmp_path / "pipeline_mgmt_exec.duckdb"
    _create_pipeline_database(database_path)
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: SimpleNamespace(duckdb_path=database_path, cors_allowed_origins=()),
    )
    client = TestClient(main.app)

    # Clear active jobs for test isolation
    main.ACTIVE_PIPELINE_JOBS.clear()

    # Trigger job
    post_resp = client.post(
        "/api/pipeline/run",
        json={
            "stage": "harmonization",
            "start_date": "2024-06-15",
            "end_date": "2024-06-16",
            "config_id": "cfg_spatiotemporal_iou_v25",
            "algorithm_version": "v2.5",
            "dry_run": True,
        },
    )
    assert post_resp.status_code == 200
    post_data = post_resp.json()
    run_id = post_data["run_id"]
    assert post_data["status"] == "RUNNING"

    # Check status of the job
    status_resp = client.get(f"/api/pipeline/runs/{run_id}")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["run_id"] == run_id
    assert status_data["status"] in ("RUNNING", "COMPLETED (DRY RUN)", "COMPLETED")
