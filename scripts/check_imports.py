import sys
from pathlib import Path
import importlib

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

modules = [
    "ingestion.api_manager",
    "ingestion.firms_client",
    "ingestion.geographic_partitioner",
    "ingestion.incremental_ingestion",
    "ingestion.request_manager",
    "ingestion.response_handler",
    "ingestion.sample_loader",
    "validation.schema_validator",
    "validation.data_quality_validator",
    "storage.metadata_manager",
    "storage.parquet_writer",
    "storage.raw_storage",
    "processing.data_pipeline",
    "processing.sql_runner",
    "utils.id_generator",
]

for module in modules:
    try:
        importlib.import_module(module)
        print(f"OK: {module}")
    except Exception as error:
        print(f"FAILED: {module} | {type(error).__name__}: {error}")
