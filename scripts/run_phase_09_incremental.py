"""Run or resume one Phase 09 incremental API harmonization batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
for source_root in (PROJECT_ROOT, SRC_ROOT):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from harmonization.v3.phases.phase_09_incremental_processing.incremental_runner import (
    DEFAULT_DATABASE,
    DEFAULT_OUTPUT_ROOT,
    DEFAULT_PHASE08_ROOT,
    run_phase_09,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Harmonize newly completed FIRMS API files after a successful "
            "full Phase 08 run. UNIFIED_DETECTIONS is read-only."
        ),
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--phase08-output-root", type=Path, default=DEFAULT_PHASE08_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--phase08-run-id")
    parser.add_argument("--table", default="UNIFIED_DETECTIONS")
    args = parser.parse_args()

    try:
        result = run_phase_09(
            database=args.database,
            phase08_output_root=args.phase08_output_root,
            output_root=args.output_root,
            phase08_run_id=args.phase08_run_id,
            table=args.table,
        )
    except Exception as exc:
        parser.exit(2, f"Phase 09 failed: {type(exc).__name__}: {exc}\n")

    print(json.dumps(result, indent=2, default=str))
    return 0 if result["status"] in {"success", "no_data", "not_ready"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
