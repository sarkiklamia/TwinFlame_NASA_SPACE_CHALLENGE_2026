import sys
from pathlib import Path
from io import StringIO
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ingestion.firms_client import FIRMSClient

with FIRMSClient() as client:
    response = client.fetch_area(
        source_key="MODIS",
        bbox="-13,27,-1,36",
        day_range=1,
    )

    print("HTTP status:", response.status_code)
    print("FIRMS source:", response.firms_source)

    if response.body.strip():
        df = pd.read_csv(StringIO(response.body), nrows=5)
        print("MODIS API columns:", df.columns.tolist())
        print(df.head(3).to_string(index=False))
    else:
        print("Empty response.")
