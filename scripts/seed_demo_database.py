"""
Seed Demo Database for TwinFlame NASA Space Apps Challenge 2026.
Creates database/twinflame.duckdb populated with realistic multi-sensor observations,
activity clusters, and harmonization correspondences matching the exact
Standardization & Harmonization Schema Specification.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import duckdb

def seed_database(db_path: Path | str = "database/twinflame.duckdb") -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()

    print(f"Creating demo database matching exact schema spec at {path.resolve()}...")
    con = duckdb.connect(str(path))

    # 1. INGESTION_RUNS
    con.execute(
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

    # 2. SOURCE_FILES
    con.execute(
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

    # 3. PROCESSING_RUNS
    con.execute(
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

    # 4. UNIFIED_DETECTIONS
    con.execute(
        """
        CREATE TABLE UNIFIED_DETECTIONS (
            detection_id VARCHAR PRIMARY KEY,
            id BIGINT,
            source VARCHAR,
            platform VARCHAR,
            latitude FLOAT,
            longitude FLOAT,
            acq_date DATE,
            acq_time VARCHAR,
            confidence_native VARCHAR,
            frp_mw FLOAT,
            brightness FLOAT,
            bright_t31 FLOAT,
            bright_ti4 FLOAT,
            bright_ti5 FLOAT,
            scan_km FLOAT,
            track_km FLOAT,
            daynight VARCHAR
        )
        """
    )

    # 5. harm_correspondence_edges
    con.execute(
        """
        CREATE TABLE harm_correspondence_edges (
            correspondence_edge_id VARCHAR PRIMARY KEY,
            detection_id_a VARCHAR,
            detection_id_b VARCHAR,
            platform_a VARCHAR,
            platform_b VARCHAR,
            time_difference_minutes DOUBLE,
            centre_distance_km DOUBLE,
            intersection_area_km2 DOUBLE,
            iou DOUBLE,
            containment_a DOUBLE,
            containment_b DOUBLE,
            normalized_centre_distance DOUBLE,
            decision_class VARCHAR,
            decision_reason VARCHAR,
            geometry_quality VARCHAR,
            run_id VARCHAR
        )
        """
    )

    # 6. harm_activity_clusters
    con.execute(
        """
        CREATE TABLE harm_activity_clusters (
            activity_cluster_id VARCHAR PRIMARY KEY,
            activity_date_utc DATE,
            centroid_latitude DOUBLE,
            centroid_longitude DOUBLE,
            member_count INTEGER,
            terra_count INTEGER,
            aqua_count INTEGER,
            noaa20_count INTEGER,
            noaa21_count INTEGER,
            sensor_count INTEGER,
            start_time_utc TIMESTAMP,
            end_time_utc TIMESTAMP,
            cluster_extent_km DOUBLE,
            cluster_area_km2 DOUBLE,
            cluster_method VARCHAR,
            run_id VARCHAR
        )
        """
    )

    # 7. harm_cluster_members
    con.execute(
        """
        CREATE TABLE harm_cluster_members (
            activity_cluster_id VARCHAR,
            detection_id VARCHAR,
            platform VARCHAR,
            membership_method VARCHAR,
            membership_distance_km DOUBLE,
            membership_quality VARCHAR,
            run_id VARCHAR
        )
        """
    )

    # 8. harm_sensor_activity_daily
    con.execute(
        """
        CREATE TABLE harm_sensor_activity_daily (
            date_utc DATE,
            platform VARCHAR,
            detection_count INTEGER,
            matching_eligible_count INTEGER,
            frp_eligible_count INTEGER,
            frp_sum_mw DOUBLE,
            frp_mean_mw DOUBLE,
            frp_median_mw DOUBLE,
            brightness_band_1_mean_k DOUBLE,
            brightness_band_1_median_k DOUBLE,
            brightness_band_2_mean_k DOUBLE,
            brightness_band_2_median_k DOUBLE,
            run_id VARCHAR
        )
        """
    )

    # 9. harm_correspondence_summary
    con.execute(
        """
        CREATE TABLE harm_correspondence_summary (
            date_utc DATE,
            platform_pair VARCHAR,
            candidate_count INTEGER,
            strong_count INTEGER,
            possible_count INTEGER,
            rejected_count INTEGER,
            insufficient_geometry_count INTEGER,
            mean_time_difference_minutes DOUBLE,
            median_time_difference_minutes DOUBLE,
            mean_iou DOUBLE,
            run_id VARCHAR
        )
        """
    )

    # 10. harm_frp_comparisons
    con.execute(
        """
        CREATE TABLE harm_frp_comparisons (
            support_id VARCHAR PRIMARY KEY,
            date_utc DATE,
            spatial_scale_km DOUBLE,
            temporal_window_minutes DOUBLE,
            platform_a VARCHAR,
            platform_b VARCHAR,
            frp_a_mw DOUBLE,
            frp_b_mw DOUBLE,
            count_a INTEGER,
            count_b INTEGER,
            time_gap_minutes DOUBLE,
            brightness_summary_a DOUBLE,
            brightness_summary_b DOUBLE,
            comparison_eligibility VARCHAR,
            run_id VARCHAR
        )
        """
    )

    # 11. harm_run_metadata
    con.execute(
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

    # 12. DATA_QUALITY_REPORTS (Recommended to preserve validation results across runs)
    con.execute(
        """
        CREATE TABLE DATA_QUALITY_REPORTS (
            report_id VARCHAR PRIMARY KEY,
            run_id VARCHAR,
            generated_at TIMESTAMP,
            total_records BIGINT,
            valid_records BIGINT,
            invalid_coordinates BIGINT,
            missing_frp BIGINT,
            invalid_frp BIGINT,
            missing_timestamps BIGINT,
            duplicate_detections BIGINT,
            insufficient_geometry BIGINT,
            completeness_pct DOUBLE,
            quality_status VARCHAR,
            summary_notes VARCHAR
        )
        """
    )

    now = datetime.now(timezone.utc)
    today = now.date()

    # Ingestion & Source Files records
    con.execute(
        f"""
        INSERT INTO INGESTION_RUNS VALUES
            (1001, 'FIRMS API', TIMESTAMP '{(now - timedelta(days=2, hours=2)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(days=2, hours=1, minutes=50)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (1002, 'Historical Archive', TIMESTAMP '{(now - timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(days=1, minutes=45)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (1003, 'Sample', TIMESTAMP '{(now - timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(hours=13, minutes=55)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (1004, 'FIRMS API', TIMESTAMP '{(now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(hours=1, minutes=50)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (1005, 'FIRMS API', TIMESTAMP '{(now - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")}', NULL, 'RUNNING')
        """
    )

    con.execute(
        f"""
        INSERT INTO SOURCE_FILES VALUES
            (2001, 'MODIS_C61_Global_7d.csv', 'Terra', 'MODIS_C61', TIMESTAMP '{(now - timedelta(days=2, hours=2)).strftime("%Y-%m-%d %H:%M:%S")}', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 1001),
            (2002, 'MODIS_C61_Global_Aqua_7d.csv', 'Aqua', 'MODIS_C61', TIMESTAMP '{(now - timedelta(days=2, hours=2)).strftime("%Y-%m-%d %H:%M:%S")}', 'ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb', 1001),
            (2003, 'VIIRS_J1_NRT_USA_Contiguous.csv', 'NOAA-20', 'VIIRS_VNP14IMG', TIMESTAMP '{(now - timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S")}', '4e1243bd22c66e76c2ba9eddc1f91394e57f9f83', 1002),
            (2004, 'VIIRS_J2_NRT_Global.csv', 'NOAA-21', 'VIIRS_VJ114IMG', TIMESTAMP '{(now - timedelta(days=1, hours=1)).strftime("%Y-%m-%d %H:%M:%S")}', '831243bd22c66e76c2ba9eddc1f91394e57f9abc', 1002),
            (2005, 'MODIS_Aqua_Sample_NRT.csv', 'Aqua', 'MODIS_C61', TIMESTAMP '{(now - timedelta(hours=14)).strftime("%Y-%m-%d %H:%M:%S")}', '3a978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee1122', 1003),
            (2006, 'VIIRS_NOAA20_NRT_Daily.csv', 'NOAA-20', 'VIIRS_VNP14IMG', TIMESTAMP '{(now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")}', '771243bd22c66e76c2ba9eddc1f91394e57f9555', 1004)
        """
    )

    con.execute(
        f"""
        INSERT INTO PROCESSING_RUNS VALUES
            (3001, 2001, 'v2.5', TIMESTAMP '{(now - timedelta(days=2, hours=1, minutes=45)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (3002, 2002, 'v2.5', TIMESTAMP '{(now - timedelta(days=2, hours=1, minutes=40)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (3003, 2003, 'v2.5', TIMESTAMP '{(now - timedelta(days=1, minutes=40)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (3004, 2004, 'v2.5', TIMESTAMP '{(now - timedelta(days=1, minutes=35)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (3005, 2005, 'v2.4', TIMESTAMP '{(now - timedelta(hours=13, minutes=50)).strftime("%Y-%m-%d %H:%M:%S")}', 'FAILED'),
            (3006, 2006, 'v2.5', TIMESTAMP '{(now - timedelta(hours=1, minutes=45)).strftime("%Y-%m-%d %H:%M:%S")}', 'COMPLETED'),
            (3007, 2006, 'v2.5', TIMESTAMP '{(now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")}', 'RUNNING')
        """
    )

    # UNIFIED_DETECTIONS
    detections = []
    # California wildfire complex
    detections.extend([
        ("det_ca_t1", 1, "MODIS_NRT", "Terra", 39.75, -121.62, today, "1115", "95", 85.4, 345.2, 310.1, 345.2, 310.1, 1.2, 1.1, "D"),
        ("det_ca_v1", 2, "VIIRS_NOAA20_NRT", "NOAA-20", 39.752, -121.618, today, "1128", "high", 92.1, 355.0, 315.0, 355.0, 315.0, 0.4, 0.4, "D"),
        ("det_ca_t2", 3, "MODIS_NRT", "Terra", 39.76, -121.60, today, "1115", "88", 64.0, 335.0, 305.0, 335.0, 305.0, 1.2, 1.1, "D"),
        ("det_ca_v2", 4, "VIIRS_NOAA20_NRT", "NOAA-20", 39.761, -121.597, today, "1128", "high", 78.5, 348.0, 310.0, 348.0, 310.0, 0.4, 0.4, "D"),
    ])
    # Amazon basin fire
    detections.extend([
        ("det_amz_a1", 5, "MODIS_NRT", "Aqua", -9.45, -54.80, today, "1340", "90", 145.0, 360.5, 318.0, 360.5, 318.0, 1.4, 1.2, "D"),
        ("det_amz_v1", 6, "VIIRS_NOAA21_NRT", "NOAA-21", -9.462, -54.785, today, "1410", "high", 160.2, 370.0, 320.0, 370.0, 320.0, 0.45, 0.4, "D"),
        ("det_amz_a2", 7, "MODIS_NRT", "Aqua", -9.42, -54.82, today, "1340", "80", 110.0, 348.0, 312.0, 348.0, 312.0, 1.4, 1.2, "D"),
        ("det_amz_v2", 8, "VIIRS_NOAA21_NRT", "NOAA-21", -9.435, -54.810, today, "1410", "nominal", 98.4, 340.0, 308.0, 340.0, 308.0, 0.45, 0.4, "D"),
    ])
    # Mediterranean (Southern Europe)
    detections.extend([
        ("det_med_t1", 9, "MODIS_NRT", "Terra", 38.12, 13.35, today, "1030", "82", 55.0, 330.0, 304.0, 330.0, 304.0, 1.1, 1.0, "D"),
        ("det_med_v1", 10, "VIIRS_NOAA20_NRT", "NOAA-20", 38.25, 13.55, today, "1245", "low", 22.0, 315.0, 298.0, 315.0, 298.0, 0.5, 0.5, "D"),
    ])
    # Australian bushfire (Oceania night overpasses)
    detections.extend([
        ("det_aus_v1", 11, "VIIRS_NOAA20_NRT", "NOAA-20", -33.85, 150.20, today, "0210", "high", 210.0, 380.0, 325.0, 380.0, 325.0, 0.4, 0.4, "N"),
        ("det_aus_v2", 12, "VIIRS_NOAA21_NRT", "NOAA-21", -33.87, 150.22, today, "0255", "high", 195.0, 375.0, 322.0, 375.0, 322.0, 0.4, 0.4, "N"),
    ])

    # Multi-year historical records (2021 - 2024) across continents
    regions_coords = [
        ("north-america", 45.0, -115.0),
        ("south-america", -12.0, -55.0),
        ("africa", -2.0, 25.0),
        ("asia", 52.0, 105.0),
        ("europe", 40.0, 20.0),
        ("oceania", -25.0, 135.0),
    ]
    platforms = ["Terra", "Aqua", "NOAA-20", "NOAA-21"]
    hist_idx = 100
    for year in range(2021, 2025):
        for month in [2, 5, 8, 11]:
            d_date = datetime(year, month, 15).date()
            for r_name, lat, lon in regions_coords:
                for plat in platforms:
                    hist_idx += 1
                    det_id = f"det_hist_{hist_idx}"
                    frp = 30.0 + (hist_idx % 80)
                    detections.append((
                        det_id, hist_idx, f"{plat}_PROCESSED", plat,
                        lat + ((hist_idx % 5) * 0.1), lon + ((hist_idx % 7) * 0.1),
                        d_date, "1200", "85", frp,
                        330.0 + frp * 0.2, 305.0, 330.0 + frp * 0.2, 305.0, 1.0, 1.0, "D"
                    ))

    # Add a few edge cases to evaluate data quality auditing (e.g. missing FRP, zero coord, duplicate)
    detections.extend([
        ("det_audit_null_frp", 901, "MODIS_NRT", "Terra", 34.0, -118.0, today, "1115", "50", None, 300.0, 290.0, 300.0, 290.0, 1.0, 1.0, "D"),
        ("det_audit_zero_coord", 902, "VIIRS_NOAA20_NRT", "NOAA-20", 0.0, 0.0, today, "1128", "low", 15.0, 310.0, 295.0, 310.0, 295.0, 0.4, 0.4, "D"),
        ("det_audit_dup_1", 903, "MODIS_NRT", "Aqua", 45.1, 10.2, today, "1340", "85", 40.0, 320.0, 300.0, 320.0, 300.0, 1.0, 1.0, "D"),
        ("det_audit_dup_2", 904, "MODIS_NRT", "Aqua", 45.1, 10.2, today, "1340", "85", 40.0, 320.0, 300.0, 320.0, 300.0, 1.0, 1.0, "D"),
    ])

    con.executemany("INSERT INTO UNIFIED_DETECTIONS VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", detections)

    # 5. harm_correspondence_edges
    edges = [
        ("edge_01", "det_ca_t1", "det_ca_v1", "Terra", "NOAA-20", 13.0, 0.28, 0.15, 0.65, 0.90, 0.95, 0.25, "STRONG", "Spatio-temporal intersection (IoU >= 0.20) within orbital coincidence window", "High", "run_2024_06"),
        ("edge_02", "det_ca_t2", "det_ca_v2", "Terra", "NOAA-20", 13.0, 0.31, 0.12, 0.58, 0.85, 0.92, 0.28, "STRONG", "Spatio-temporal intersection (IoU >= 0.20) within orbital coincidence window", "High", "run_2024_06"),
        ("edge_03", "det_amz_a1", "det_amz_v1", "Aqua", "NOAA-21", 30.0, 1.85, 0.08, 0.42, 0.75, 0.80, 0.65, "STRONG", "Orbital coincidence overlap within adaptive clustering window", "Nominal", "run_2024_06"),
        ("edge_04", "det_amz_a2", "det_amz_v2", "Aqua", "NOAA-21", 30.0, 2.15, 0.03, 0.18, 0.40, 0.45, 0.78, "POSSIBLE", "Active fire cluster proximity with partial boundary overlap", "Nominal", "run_2024_06"),
        ("edge_05", "det_med_t1", "det_med_v1", "Terra", "NOAA-20", 135.0, 22.4, 0.00, 0.00, 0.00, 0.00, 5.20, "REJECTED", "Centroid distance exceeds maximum spatial threshold (>3.0 km)", "Degraded", "run_2024_06"),
        ("edge_06", "det_aus_v1", "det_aus_v2", "NOAA-20", "NOAA-21", 45.0, 2.20, 0.11, 0.52, 0.82, 0.85, 0.70, "STRONG", "Spatio-temporal intersection (IoU >= 0.20) within orbital coincidence window", "High", "run_2024_06"),
    ]
    con.executemany("INSERT INTO harm_correspondence_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", edges)

    # 6. harm_activity_clusters
    clusters = [
        ("cl_california", today, 39.755, -121.609, 4, 2, 0, 2, 0, 2, f"{today} 11:15:00", f"{today} 11:28:00", 3.2, 5.8, "DBSCAN_SPATIO_TEMPORAL", "run_2024_06"),
        ("cl_amazon", today, -9.442, -54.804, 4, 0, 2, 0, 2, 2, f"{today} 13:40:00", f"{today} 14:10:00", 4.5, 9.2, "DBSCAN_SPATIO_TEMPORAL", "run_2024_06"),
        ("cl_mediterranean", today, 38.185, 13.450, 2, 1, 0, 1, 0, 2, f"{today} 10:30:00", f"{today} 12:45:00", 24.0, 45.0, "DBSCAN_SPATIO_TEMPORAL", "run_2024_06"),
        ("cl_australia", today, -33.860, 150.210, 2, 0, 0, 1, 1, 2, f"{today} 02:10:00", f"{today} 02:55:00", 2.8, 4.1, "DBSCAN_SPATIO_TEMPORAL", "run_2024_06"),
    ]
    con.executemany("INSERT INTO harm_activity_clusters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", clusters)

    # 7. harm_cluster_members
    members = [
        ("cl_california", "det_ca_t1", "Terra", "CentroidProximity", 0.45, "High", "run_2024_06"),
        ("cl_california", "det_ca_v1", "NOAA-20", "CentroidProximity", 0.38, "High", "run_2024_06"),
        ("cl_california", "det_ca_t2", "Terra", "CentroidProximity", 0.52, "High", "run_2024_06"),
        ("cl_california", "det_ca_v2", "NOAA-20", "CentroidProximity", 0.41, "High", "run_2024_06"),
        ("cl_amazon", "det_amz_a1", "Aqua", "CentroidProximity", 0.85, "Nominal", "run_2024_06"),
        ("cl_amazon", "det_amz_v1", "NOAA-21", "CentroidProximity", 0.78, "Nominal", "run_2024_06"),
        ("cl_amazon", "det_amz_a2", "Aqua", "CentroidProximity", 1.10, "Nominal", "run_2024_06"),
        ("cl_amazon", "det_amz_v2", "NOAA-21", "CentroidProximity", 0.95, "Nominal", "run_2024_06"),
        ("cl_mediterranean", "det_med_t1", "Terra", "CentroidProximity", 11.5, "Degraded", "run_2024_06"),
        ("cl_mediterranean", "det_med_v1", "NOAA-20", "CentroidProximity", 12.0, "Degraded", "run_2024_06"),
        ("cl_australia", "det_aus_v1", "NOAA-20", "CentroidProximity", 0.65, "High", "run_2024_06"),
        ("cl_australia", "det_aus_v2", "NOAA-21", "CentroidProximity", 0.58, "High", "run_2024_06"),
    ]
    con.executemany("INSERT INTO harm_cluster_members VALUES (?, ?, ?, ?, ?, ?, ?)", members)

    # 8. harm_sensor_activity_daily
    daily_records = []
    for d_offset in range(30):
        dt = (now - timedelta(days=d_offset)).date()
        daily_records.append((dt, "Terra", 45 + d_offset, 40 + d_offset, 42 + d_offset, 2450.0, 54.4, 48.0, 325.0, 320.0, 298.0, 295.0, "run_2024_06"))
        daily_records.append((dt, "Aqua", 52 + d_offset, 48 + d_offset, 50 + d_offset, 3200.0, 61.5, 52.0, 330.0, 322.0, 302.0, 298.0, "run_2024_06"))
        daily_records.append((dt, "NOAA-20", 68 + d_offset * 2, 62 + d_offset * 2, 65 + d_offset * 2, 4500.0, 66.2, 55.0, 335.0, 325.0, 305.0, 300.0, "run_2024_06"))
        daily_records.append((dt, "NOAA-21", 64 + d_offset * 2, 59 + d_offset * 2, 61 + d_offset * 2, 4200.0, 65.6, 54.0, 334.0, 324.0, 304.0, 299.0, "run_2024_06"))
    con.executemany("INSERT INTO harm_sensor_activity_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", daily_records)

    # 9. harm_correspondence_summary
    con.execute(
        """
        INSERT INTO harm_correspondence_summary VALUES
            (DATE '2024-06-15', 'Terra – NOAA-20', 25, 14, 6, 3, 2, 14.5, 13.0, 0.54, 'run_2024_06'),
            (DATE '2024-06-16', 'Aqua – NOAA-21', 28, 18, 5, 2, 3, 28.0, 26.0, 0.48, 'run_2024_06'),
            (DATE '2024-06-17', 'Terra – NOAA-20', 18, 8, 4, 5, 1, 16.0, 15.0, 0.45, 'run_2024_06'),
            (DATE '2024-06-18', 'NOAA-20 – NOAA-21', 19, 12, 3, 1, 3, 42.0, 40.0, 0.51, 'run_2024_06'),
            (CURRENT_DATE, 'Terra – NOAA-20', 5, 2, 1, 1, 1, 13.0, 13.0, 0.61, 'run_2024_06'),
            (CURRENT_DATE, 'Aqua – NOAA-21', 4, 1, 1, 1, 1, 30.0, 30.0, 0.35, 'run_2024_06'),
            (CURRENT_DATE, 'NOAA-20 – NOAA-21', 2, 1, 0, 0, 1, 45.0, 45.0, 0.52, 'run_2024_06')
        """
    )

    # 10. harm_frp_comparisons
    con.execute(
        """
        INSERT INTO harm_frp_comparisons VALUES
            ('frp_cmp_01', CURRENT_DATE, 3.0, 120.0, 'Terra', 'NOAA-20', 85.4, 92.1, 2, 2, 13.0, 345.2, 355.0, 'ELIGIBLE_COINCIDENT', 'run_2024_06'),
            ('frp_cmp_02', CURRENT_DATE, 3.0, 120.0, 'Aqua', 'NOAA-21', 145.0, 160.2, 2, 2, 30.0, 360.5, 370.0, 'ELIGIBLE_COINCIDENT', 'run_2024_06')
        """
    )

    # 11. harm_run_metadata
    con.execute(
        f"""
        INSERT INTO harm_run_metadata VALUES
            ('run_2024_06_baseline', 'v2.1', 'cfg_euclidean_distance_v21', TIMESTAMP '{(now - timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(days=5, minutes=-7)).strftime("%Y-%m-%d %H:%M:%S")}', 420.5, 'COMPLETED', 1250, 840, 260, 48, NULL, NULL),
            ('run_2024_06_strict', 'v2.4', 'cfg_strict_spatial_threshold', TIMESTAMP '{(now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(days=3, minutes=-6)).strftime("%Y-%m-%d %H:%M:%S")}', 365.2, 'COMPLETED', 1100, 720, 195, 38, NULL, NULL),
            ('run_2024_06_edge_test', 'v2.5', 'cfg_experimental_polygon_iou', TIMESTAMP '{(now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(days=2, minutes=-2)).strftime("%Y-%m-%d %H:%M:%S")}', 128.0, 'FAILED', 850, 410, 0, 0, 'Geometric Intersection Over Union', 'Scan angle deformation > 60° caused polygon projection singularity in polar overpass.'),
            ('run_2024_06_rapid', 'v2.5', 'cfg_rapid_revisit_noaa', TIMESTAMP '{(now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(days=1, minutes=-5)).strftime("%Y-%m-%d %H:%M:%S")}', 295.4, 'COMPLETED', 950, 610, 180, 34, NULL, NULL),
            ('run_2024_06', 'v2.5', 'cfg_spatiotemporal_iou_v25', TIMESTAMP '{(now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")}', TIMESTAMP '{(now - timedelta(minutes=55)).strftime("%Y-%m-%d %H:%M:%S")}', 312.4, 'COMPLETED', {len(detections)}, 32, {len(edges)}, {len(clusters)}, NULL, NULL)
        """
    )

    # 12. DATA_QUALITY_REPORTS
    con.execute(
        f"""
        INSERT INTO DATA_QUALITY_REPORTS VALUES
            ('dqr_run_2024_06', 'run_2024_06', TIMESTAMP '{now.strftime("%Y-%m-%d %H:%M:%S")}', {len(detections)}, {len(detections) - 4}, 1, 1, 0, 0, 2, 1, 98.9, 'EXCELLENT', 'Validation passed: 98.9% data completeness across MODIS and VIIRS unified streams.')
        """
    )

    con.close()
    print(f"Successfully populated {path.resolve()} with:")
    print(f"  - 4 Standardization Tables (INGESTION_RUNS, SOURCE_FILES, PROCESSING_RUNS, UNIFIED_DETECTIONS: {len(detections)} rows)")
    print(f"  - 7 Harmonization Tables (clusters, members, edges, daily, summary, frp_comp, metadata)")
    print(f"  - 1 Validation Preservation Table (DATA_QUALITY_REPORTS)")

if __name__ == "__main__":
    seed_database()
