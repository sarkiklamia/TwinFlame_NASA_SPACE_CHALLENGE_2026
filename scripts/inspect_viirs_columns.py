from pathlib import Path
import pandas as pd

sample_dir = Path("data/raw/sample")

for filename in ["J1V-C2_2026_July.csv", "J2V-C2_2026_July.csv"]:
    df = pd.read_csv(sample_dir / filename, nrows=5)
    print(f"\n{filename}")
    print(df.columns.tolist())
