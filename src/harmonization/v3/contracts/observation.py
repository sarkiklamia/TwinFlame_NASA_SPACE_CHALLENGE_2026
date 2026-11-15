from dataclasses import dataclass
from typing import Any

from . import __name__ as _contracts_package


@dataclass(frozen=True)
class ObservationQCResult:
    """QC assessment of one observation; the original observation is retained."""

    observation: Any
    eligible_for_spatial_matching: bool
    eligible_for_frp_analysis: bool
    qc_issues: tuple[str, ...]
    qc_warnings: tuple[str, ...]
    eligible_for_brightness_analysis: bool = False
