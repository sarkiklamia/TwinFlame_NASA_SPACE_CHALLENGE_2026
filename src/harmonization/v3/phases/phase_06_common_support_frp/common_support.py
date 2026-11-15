from dataclasses import dataclass
from hashlib import sha256

from ...config.frp_support import (
    build_spatial_support_experiments,
    build_temporal_support_experiments,
)
from ...contracts.frp import (
    CommonSupportMembership,
)
from .spatial_support import assign_spatial_support
from .temporal_support import assign_temporal_support


@dataclass(frozen=True)
class CommonSupportExperimentResult:
    grid_resolution_km: float
    max_group_span_minutes: float
    memberships: tuple[CommonSupportMembership, ...]


def build_common_support_memberships(
    spatial_assignments,
    temporal_memberships,
) -> tuple[CommonSupportMembership, ...]:
    spatial_index = {}
    for assignment in spatial_assignments:
        identity = (assignment.platform, assignment.detection_id)
        if identity in spatial_index:
            raise ValueError(f"Duplicate spatial assignment: {identity}")
        spatial_index[identity] = assignment

    temporal_index = {}
    for membership in temporal_memberships:
        identity = (membership.platform, membership.detection_id)
        if identity in temporal_index:
            raise ValueError(f"Duplicate temporal membership: {identity}")
        temporal_index[identity] = membership

    if set(spatial_index) != set(temporal_index):
        missing_temporal = sorted(set(spatial_index) - set(temporal_index))
        missing_spatial = sorted(set(temporal_index) - set(spatial_index))
        raise ValueError(
            "Spatial/temporal membership mismatch. "
            f"Missing temporal={missing_temporal[:5]}; "
            f"missing spatial={missing_spatial[:5]}"
        )

    memberships = []

    for identity in sorted(spatial_index):
        assignment = spatial_index[identity]
        temporal = temporal_index[identity]

        if assignment.cell_id == "":
            raise ValueError(f"Empty spatial cell ID: {identity}")

        if temporal.support_date_utc is None:
            raise ValueError(f"Missing UTC support date: {identity}")

        support_key = (
            f"{assignment.cell_id}|"
            f"{temporal.support_group_id}"
        )
        digest = sha256(support_key.encode("utf-8")).hexdigest()[:20]

        memberships.append(
            CommonSupportMembership(
                detection_id=assignment.detection_id,
                platform=assignment.platform,
                support_unit_id=f"FRPS-{digest}",
                spatial_cell_id=assignment.cell_id,
                temporal_group_id=temporal.support_group_id,
                support_date_utc=temporal.support_date_utc,
            )
        )

    return tuple(memberships)


def run_common_support_experiments(phase02_result):
    results = []

    temporal_configs = build_temporal_support_experiments()

    for spatial_config in build_spatial_support_experiments():
        spatial_assignments = assign_spatial_support(
            phase02_result,
            spatial_config,
        )

        for temporal_config in temporal_configs:
            temporal_memberships = assign_temporal_support(
                phase02_result,
                spatial_assignments,
                temporal_config,
            )

            common_memberships = build_common_support_memberships(
                spatial_assignments,
                temporal_memberships,
            )

            results.append(
                CommonSupportExperimentResult(
                    grid_resolution_km=spatial_config.grid_resolution_km,
                    max_group_span_minutes=(
                        temporal_config.max_group_span_minutes
                    ),
                    memberships=common_memberships,
                )
            )

    return tuple(results)
