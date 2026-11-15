from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GeometryProvenance:
    method: str
    source_dimensions: tuple[str, ...]
    orientation_known: bool
    assumptions: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class ObservationGeometryResult:
    qc_result: Any
    center_point: Any | None
    spatial_envelope: Any | None
    geometry_status: str
    envelope_radius_km: float | None
    provenance: GeometryProvenance
    geometry_issues: tuple[str, ...]
