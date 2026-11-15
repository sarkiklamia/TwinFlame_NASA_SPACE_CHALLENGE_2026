import math
from collections import defaultdict
from statistics import fmean, median

from ...contracts.frp import SensorFRPAggregate


def _extract_geometry_results(source):
    if hasattr(source, "results"):
        return tuple(source.results)
    try:
        return tuple(source)
    except TypeError as exc:
        raise TypeError(
            "Expected Phase02Result or iterable of geometry results"
        ) from exc


def aggregate_sensor_frp(
    phase02_result,
    common_support_memberships,
) -> tuple[SensorFRPAggregate, ...]:
    """
    Aggregate native FRP independently by support unit and platform.

    FRP remains in MW. This function does not sum FRP over time,
    calibrate measurements, or require Phase 3 correspondence matches.
    """
    geometry_results = _extract_geometry_results(phase02_result)
    memberships = tuple(common_support_memberships)

    observations = {}

    for result in geometry_results:
        qc_result = result.qc_result
        observation = qc_result.observation
        identity = (observation.platform, observation.detection_id)

        if identity in observations:
            raise ValueError(f"Duplicate observation identity: {identity}")

        observations[identity] = (observation, qc_result)

    membership_index = {}
    for membership in memberships:
        identity = (membership.platform, membership.detection_id)

        if identity in membership_index:
            raise ValueError(f"Duplicate common-support membership: {identity}")

        membership_index[identity] = membership

    # Every FRP-eligible observation must have exactly one membership.
    eligible_identities = {
        identity
        for identity, (_, qc_result) in observations.items()
        if qc_result.eligible_for_frp_analysis
    }

    membership_identities = set(membership_index)

    missing_memberships = eligible_identities - membership_identities

    if missing_memberships:
        raise ValueError(
            "Missing common-support membership for FRP-eligible "
            f"observations: {sorted(missing_memberships)}"
        )

    grouped = defaultdict(list)
    unit_metadata = {}

    for identity, membership in membership_index.items():
        if identity not in observations:
            raise ValueError(
                f"Membership refers to unknown observation: {identity}"
            )

        observation, qc_result = observations[identity]

        if not qc_result.eligible_for_frp_analysis:
            raise ValueError(
                f"Common-support membership references FRP-ineligible "
                f"observation: {identity}"
            )

        frp = observation.frp_mw

        if frp is None or not math.isfinite(frp) or frp < 0:
            raise ValueError(
                f"Invalid native FRP for common-support observation: {identity}"
            )

        unit_id = membership.support_unit_id
        platform = membership.platform

        metadata = (
            membership.spatial_cell_id,
            membership.temporal_group_id,
            membership.support_date_utc,
        )

        previous_metadata = unit_metadata.setdefault(unit_id, metadata)
        if previous_metadata != metadata:
            raise ValueError(
                f"Inconsistent metadata within support unit: {unit_id}"
            )

        grouped[(unit_id, platform)].append(float(frp))

    aggregates = []

    for (unit_id, platform), values in sorted(grouped.items()):
        spatial_cell_id, temporal_group_id, support_date = (
            unit_metadata[unit_id]
        )

        aggregates.append(
            SensorFRPAggregate(
                support_unit_id=unit_id,
                spatial_cell_id=spatial_cell_id,
                temporal_group_id=temporal_group_id,
                support_date_utc=support_date,
                platform=platform,
                observation_count=len(values),
                frp_mean_mw=fmean(values),
                frp_median_mw=median(values),
                frp_min_mw=min(values),
                frp_max_mw=max(values),
            )
        )

    return tuple(aggregates)
