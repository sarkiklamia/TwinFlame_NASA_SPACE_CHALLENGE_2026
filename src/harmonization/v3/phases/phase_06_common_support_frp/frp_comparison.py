import math

from ...contracts.frp import FRPComparison


CROSS_PLATFORM_PAIRS = (
    ("MODIS_TERRA", "MODIS_AQUA"),
    ("VIIRS_NOAA20", "VIIRS_NOAA21"),
    ("MODIS_TERRA", "VIIRS_NOAA20"),
    ("MODIS_TERRA", "VIIRS_NOAA21"),
    ("MODIS_AQUA", "VIIRS_NOAA20"),
    ("MODIS_AQUA", "VIIRS_NOAA21"),
)


def compare_sensor_frp(sensor_aggregates):
    """
    Compare sensor mean native FRP within identical common-support units.

    Difference is defined as FRP_B - FRP_A.

    Relative difference is symmetric:
        2 * (FRP_B - FRP_A) / (abs(FRP_A) + abs(FRP_B))

    It is None when both values are zero.

    Only the six configured cross-platform pairs are compared.
    Missing sensor aggregates do not create comparisons.
    """
    aggregates = tuple(sensor_aggregates)

    aggregate_index = {}

    supported_platforms = {
        platform
        for pair in CROSS_PLATFORM_PAIRS
        for platform in pair
    }

    for aggregate in aggregates:
        platform = aggregate.platform
        support_unit_id = aggregate.support_unit_id
        identity = (support_unit_id, platform)

        if platform not in supported_platforms:
            raise ValueError(f"Unsupported platform in FRP aggregate: {platform}")

        if identity in aggregate_index:
            raise ValueError(
                f"Duplicate sensor aggregate for support unit/platform: {identity}"
            )

        frp = aggregate.frp_mean_mw

        try:
            valid_frp = math.isfinite(frp) and frp >= 0
        except (TypeError, ValueError):
            valid_frp = False

        if not valid_frp:
            raise ValueError(
                f"Invalid mean native FRP for support unit/platform: {identity}"
            )

        aggregate_index[identity] = aggregate

    support_unit_ids = sorted({
        aggregate.support_unit_id for aggregate in aggregates
    })

    comparisons = []

    for support_unit_id in support_unit_ids:
        for platform_a, platform_b in CROSS_PLATFORM_PAIRS:
            aggregate_a = aggregate_index.get((support_unit_id, platform_a))
            aggregate_b = aggregate_index.get((support_unit_id, platform_b))

            # A comparison requires both sensors in the same support unit.
            if aggregate_a is None or aggregate_b is None:
                continue

            frp_a = float(aggregate_a.frp_mean_mw)
            frp_b = float(aggregate_b.frp_mean_mw)

            difference = frp_b - frp_a
            denominator = abs(frp_a) + abs(frp_b)

            relative_difference = (
                2.0 * difference / denominator
                if denominator > 0
                else None
            )

            comparisons.append(
                FRPComparison(
                    support_unit_id=support_unit_id,
                    platform_a=platform_a,
                    platform_b=platform_b,
                    frp_a_mw=frp_a,
                    frp_b_mw=frp_b,
                    difference_mw=difference,
                    relative_difference=relative_difference,
                )
            )

    return tuple(comparisons)
