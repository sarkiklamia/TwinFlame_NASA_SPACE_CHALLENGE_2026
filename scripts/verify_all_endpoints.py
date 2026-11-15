import sys
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient

sys.path.insert(0, ".")
from app.backend import main

db_path = Path("database/twinflame.duckdb").resolve()
print(f"Testing against DB: {db_path} (exists: {db_path.exists()})")

main.get_settings = lambda: SimpleNamespace(duckdb_path=db_path, cors_allowed_origins=())
client = TestClient(main.app)

routes = [
    ("/api/overview", {}),
    ("/api/monitoring", {}),
    ("/api/fire-season", {}),
    ("/api/geospatial", {}),
    ("/api/historical-analysis", {}),
    ("/api/historical-analysis/export", {}),
    ("/api/sensor-comparison", {}),
    ("/api/harmonization-evaluation", {}),
    ("/api/quality-methodology", {}),
    ("/api/pipeline-management", {}),
]

success = True
for url, params in routes:
    r = client.get(url, params=params)
    print(f"{url:35} -> HTTP {r.status_code}")
    if r.status_code != 200:
        print("  ERROR:", r.text[:300])
        success = False

# Also test job execution
post_r = client.post("/api/pipeline/run", json={"stage": "harmonization", "dry_run": True})
print(f"{'POST /api/pipeline/run':35} -> HTTP {post_r.status_code}")
if post_r.status_code != 200:
    print("  ERROR:", post_r.text[:300])
    success = False
else:
    run_id = post_r.json()["run_id"]
    get_run = client.get(f"/api/pipeline/runs/{run_id}")
    print(f"{'GET /api/pipeline/runs/{id}':35} -> HTTP {get_run.status_code}")
    if get_run.status_code != 200:
        print("  ERROR:", get_run.text[:300])
        success = False

if success:
    print("ALL 10 DASHBOARD ENDPOINTS & JOB EXECUTION TESTED SUCCESSFULLY WITH HTTP 200 OK!")
else:
    print("SOME ENDPOINTS FAILED!")
    sys.exit(1)
