import sys
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient

sys.path.insert(0, ".")
from app.backend import main

db_path = Path("database/twinflame.duckdb").resolve()
main.get_settings = lambda: SimpleNamespace(duckdb_path=db_path, cors_allowed_origins=())
client = TestClient(main.app)

test_cases = [
    # Page 1: Overview
    ("/api/overview", {"region": "global", "date_range": "7d", "satellite": "all", "day_night": "all"}),
    ("/api/overview", {"region": "north-america", "satellite": "MODIS", "day_night": "day", "min_frp": 10.0, "confidence": "high"}),
    
    # Page 2: Monitoring
    ("/api/monitoring", {"region": "global", "satellite": "all"}),
    ("/api/monitoring", {"region": "global", "satellite": "VIIRS", "day_night": "night"}),

    # Page 3: Fire Season
    ("/api/fire-season", {"region": "global", "satellite": "all"}),
    ("/api/fire-season", {"region": "north-america", "satellite": "MODIS"}),

    # Page 4 & 5: Geospatial
    ("/api/geospatial", {"region": "global", "satellite": "all"}),
    ("/api/geospatial", {"region": "north-america", "platform": "Terra", "day_night": "day"}),

    # Page 6: Historical Analysis
    ("/api/historical-analysis", {"region": "global", "temporal_aggregation": "daily", "spatial_aggregation": "detections"}),
    ("/api/historical-analysis", {"region": "north-america", "temporal_aggregation": "monthly", "spatial_aggregation": "clusters"}),
    ("/api/historical-analysis/export", {"region": "global"}),

    # Page 7: Sensor Comparison
    ("/api/sensor-comparison", {"platform_a": "Terra", "platform_b": "NOAA-20"}),
    ("/api/sensor-comparison", {"platform_a": "Aqua", "platform_b": "NOAA-21", "metric": "frp"}),
    ("/api/sensor-comparison", {"platform_a": "Terra", "platform_b": "NOAA-21", "comparison_eligibility": "eligible"}),

    # Page 8: Harmonization Evaluation
    ("/api/harmonization-evaluation", {"platform_pair": "Terra – NOAA-20"}),
    ("/api/harmonization-evaluation", {"decision_class": "STRONG"}),
    ("/api/harmonization-evaluation", {"min_iou": 0.1, "max_iou": 1.0}),

    # Page 9: Quality & Methodology
    ("/api/quality-methodology", {"platform": "Terra"}),
    ("/api/quality-methodology", {"quality_issue": "missing_values"}),
    ("/api/quality-methodology", {"quality_status": "NOMINAL"}),
    ("/api/quality-methodology", {"source_file": "MODIS_C61_Global_7d.csv"}),

    # Page 10: Pipeline Management
    ("/api/pipeline-management", {"stage": "Harmonization", "status": "Completed"}),
    ("/api/pipeline-management", {"ingestion_type": "FIRMS API"}),
    ("/api/pipeline-management", {"platform": "NOAA-20"}),
    ("/api/pipeline-management", {"source_file": "MODIS_C61_Global_7d.csv"}),
    ("/api/pipeline-management", {"run_id": "run_2024_06"}),
]

errors = 0
for url, params in test_cases:
    res = client.get(url, params=params)
    param_str = ", ".join(f"{k}={v}" for k, v in params.items())
    if res.status_code == 200:
        print(f"[OK 200] {url} ({param_str})")
    else:
        print(f"[FAIL {res.status_code}] {url} ({param_str})")
        print("  Error:", res.text[:300])
        errors += 1

if errors == 0:
    print(f"\nALL {len(test_cases)} TEST CASES PASSED WITH HTTP 200!")
else:
    print(f"\n{errors} TEST CASES FAILED!")
    sys.exit(1)
