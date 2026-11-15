from dataclasses import dataclass
from collections.abc import Iterable

from ...contracts.geometry import ObservationGeometryResult
from .footprint_builder import build_observation_geometry
from .geometry_validation import validate_phase_02_output


@dataclass(frozen=True)
class Phase02Result:
    results: tuple[ObservationGeometryResult, ...]

    @property
    def input_count(self) -> int:
        return len(self.results)

    @property
    def ineligible_count(self) -> int:
        return sum(
            item.geometry_status == "ineligible"
            for item in self.results
        )

    @property
    def center_only_count(self) -> int:
        return sum(
            item.geometry_status == "center_only"
            for item in self.results
        )

    @property
    def conservative_envelope_count(self) -> int:
        return sum(
            item.geometry_status == "conservative_envelope"
            for item in self.results
        )


def run_phase_02(qc_results: Iterable) -> Phase02Result:
    source_results = tuple(qc_results)

    geometry_results = tuple(
        build_observation_geometry(item)
        for item in source_results
    )

    validate_phase_02_output(source_results, geometry_results)

    return Phase02Result(results=geometry_results)
