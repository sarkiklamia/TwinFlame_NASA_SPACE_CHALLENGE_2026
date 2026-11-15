from dataclasses import dataclass
from datetime import datetime, timezone
import re
import uuid


@dataclass(frozen=True)
class PipelineRunContext:
    run_id: str
    algorithm_version: str
    config_id: str
    started_at_utc: datetime


def create_run_context(
    *,
    algorithm_version: str = "v3",
    config_id: str = "default",
    run_id: str | None = None,
) -> PipelineRunContext:
    """Create a validated pipeline run identity and UTC start timestamp."""

    if not isinstance(algorithm_version, str) or not algorithm_version.strip():
        raise ValueError("algorithm_version must be a non-empty string")

    if not isinstance(config_id, str) or not config_id.strip():
        raise ValueError("config_id must be a non-empty string")

    if run_id is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_id = f"{timestamp}_{uuid.uuid4().hex[:8]}"

    if not isinstance(run_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*", run_id
    ):
        raise ValueError("Invalid run_id")

    return PipelineRunContext(
        run_id=run_id,
        algorithm_version=algorithm_version.strip(),
        config_id=config_id.strip(),
        started_at_utc=datetime.now(timezone.utc),
    )
