from collections import defaultdict
from collections.abc import Iterable
from datetime import timezone
from hashlib import sha256

from ...config.frp_support import (
    TemporalSupportConfig,
    build_temporal_support_experiments,
)
from ...contracts.frp import TemporalSupportMembership


def _extract_geometry_results(source) -> tuple:
    if hasattr(source, "results"):
        return tuple(source.results)
    if isinstance(source, Iterable):
        return tuple(source)
    raise TypeError("Expected Phase02Result or iterable of geometry results")


def _stable_group_id(
    cell_id,
    support_date,
    config,
    group_start,
    members,
):
    identity_text = "|".join(
        (
            cell_id,
            support_date.isoformat(),
            str(config.max_group_span_minutes),
            group_start.isoformat(),
            *sorted(
                f"{platform}:{detection_id}"
                for platform, detection_id in members
            ),
        )
    )
    digest = sha256(identity_text.encode("utf-8")).hexdigest()[:20]
    return f"FRPT-{digest}"


def assign_temporal_support(
    phase02_result,
    spatial_assignments,
    config: TemporalSupportConfig,
) -> tuple[TemporalSupportMembership, ...]:
    geometry_results = _extract_geometry_results(phase02_result)
    assignments = tuple(spatial_assignments)

    assignment_index = {}
    for assignment in assignments:
        identity = (assignment.platform, assignment.detection_id)
        if identity in assignment_index:
            raise ValueError(f"Duplicate spatial assignment: {identity}")
        assignment_index[identity] = assignment

    observations = {}

    for geometry_result in geometry_results:
        qc_result = geometry_result.qc_result

        if not qc_result.eligible_for_frp_analysis:
            continue

        observation = qc_result.observation
        identity = (observation.platform, observation.detection_id)

        if identity not in assignment_index:
            continue

        if identity in observations:
            raise ValueError(f"Duplicate observation identity: {identity}")

        timestamp = observation.acquisition_time_utc

        if timestamp is None or timestamp.tzinfo is None:
            raise ValueError(
                f"FRP-eligible observation has missing or naive timestamp: {identity}"
            )

        timestamp_utc = timestamp.astimezone(timezone.utc)

        observations[identity] = (
            timestamp_utc,
            assignment_index[identity],
        )

    # A group is built independently for each spatial cell and UTC date.
    buckets = defaultdict(list)

    for identity, (timestamp, assignment) in observations.items():
        buckets[
            (assignment.cell_id, timestamp.date())
        ].append((timestamp, identity))

    memberships = []

    for (cell_id, support_date), entries in sorted(
        buckets.items(),
        key=lambda item: (item[0][1], item[0][0]),
    ):
        entries.sort(
            key=lambda item: (
                item[0],
                item[1][0],
                item[1][1],
            )
        )

        current_group = []
        group_start = None

        def emit_group(group_entries):
            if not group_entries:
                return

            start = group_entries[0][0]
            end = group_entries[-1][0]
            group_members = [identity for _, identity in group_entries]

            group_id = _stable_group_id(
                cell_id,
                support_date,
                config,
                start,
                group_members,
            )

            for timestamp, (platform, detection_id) in group_entries:
                memberships.append(
                    TemporalSupportMembership(
                        detection_id=detection_id,
                        platform=platform,
                        support_group_id=group_id,
                        support_date_utc=support_date,
                        group_start_utc=start,
                        group_end_utc=end,
                        max_group_span_minutes=config.max_group_span_minutes,
                    )
                )

        for timestamp, identity in entries:
            if group_start is None:
                group_start = timestamp
                current_group = [(timestamp, identity)]
                continue

            elapsed_minutes = (
                timestamp - group_start
            ).total_seconds() / 60.0

            if elapsed_minutes <= config.max_group_span_minutes:
                current_group.append((timestamp, identity))
            else:
                emit_group(current_group)
                group_start = timestamp
                current_group = [(timestamp, identity)]

        emit_group(current_group)

    memberships.sort(
        key=lambda item: (
            item.support_date_utc,
            item.support_group_id,
            item.platform,
            item.detection_id,
        )
    )

    if len(memberships) != len(observations):
        raise RuntimeError(
            "Temporal support did not assign exactly one membership "
            "to every spatially assigned FRP-eligible observation"
        )

    return tuple(memberships)


def run_temporal_support_experiments(
    phase02_result,
    spatial_assignments,
):
    results = []

    for config in build_temporal_support_experiments():
        memberships = assign_temporal_support(
            phase02_result,
            spatial_assignments,
            config,
        )
        results.append((config, memberships))

    return tuple(results)
