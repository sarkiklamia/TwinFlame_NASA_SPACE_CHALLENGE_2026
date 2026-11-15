from datetime import date
from types import SimpleNamespace

import pytest

from harmonization.v3.contracts.frp import CommonSupportMembership
from harmonization.v3.phases.phase_06_common_support_frp.sensor_aggregation import (
    aggregate_sensor_frp,
)


def make_phase02(rows):
    results = []

    for detection_id, platform, frp, eligible in rows:
        observation = SimpleNamespace(
            detection_id=detection_id,
            platform=platform,
            frp_mw=frp,
        )
        qc_result = SimpleNamespace(
            observation=observation,
            eligible_for_frp_analysis=eligible,
        )
        results.append(SimpleNamespace(qc_result=qc_result))

    return SimpleNamespace(results=tuple(results))


def make_membership(detection_id, platform, unit="UNIT-1"):
    return CommonSupportMembership(
        detection_id=detection_id,
        platform=platform,
        support_unit_id=unit,
        spatial_cell_id="CELL-1",
        temporal_group_id="GROUP-1",
        support_date_utc=date(2026, 7, 10),
    )


def test_aggregates_native_frp_statistics_per_sensor():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, True),
        ("T2", "MODIS_TERRA", 20.0, True),
        ("T3", "MODIS_TERRA", 30.0, True),
    ])
    memberships = (
        make_membership("T1", "MODIS_TERRA"),
        make_membership("T2", "MODIS_TERRA"),
        make_membership("T3", "MODIS_TERRA"),
    )

    result = aggregate_sensor_frp(phase02, memberships)

    assert len(result) == 1
    aggregate = result[0]
    assert aggregate.observation_count == 3
    assert aggregate.frp_mean_mw == pytest.approx(20.0)
    assert aggregate.frp_median_mw == pytest.approx(20.0)
    assert aggregate.frp_min_mw == pytest.approx(10.0)
    assert aggregate.frp_max_mw == pytest.approx(30.0)


def test_platforms_are_aggregated_independently():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, True),
        ("A1", "MODIS_AQUA", 100.0, True),
    ])
    memberships = (
        make_membership("T1", "MODIS_TERRA"),
        make_membership("A1", "MODIS_AQUA"),
    )

    result = aggregate_sensor_frp(phase02, memberships)

    assert len(result) == 2
    by_platform = {item.platform: item for item in result}
    assert by_platform["MODIS_TERRA"].frp_mean_mw == 10.0
    assert by_platform["MODIS_AQUA"].frp_mean_mw == 100.0


def test_zero_frp_is_retained():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 0.0, True),
    ])
    result = aggregate_sensor_frp(
        phase02,
        (make_membership("T1", "MODIS_TERRA"),),
    )

    assert len(result) == 1
    assert result[0].frp_mean_mw == 0.0
    assert result[0].frp_min_mw == 0.0


def test_different_support_units_are_aggregated_separately():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, True),
        ("T2", "MODIS_TERRA", 20.0, True),
    ])
    memberships = (
        make_membership("T1", "MODIS_TERRA", "UNIT-1"),
        make_membership("T2", "MODIS_TERRA", "UNIT-2"),
    )

    result = aggregate_sensor_frp(phase02, memberships)

    assert len(result) == 2
    assert {item.support_unit_id for item in result} == {
        "UNIT-1",
        "UNIT-2",
    }


def test_duplicate_membership_is_rejected():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, True),
    ])
    membership = make_membership("T1", "MODIS_TERRA")

    with pytest.raises(ValueError, match="Duplicate common-support membership"):
        aggregate_sensor_frp(phase02, (membership, membership))


def test_unknown_observation_membership_is_rejected():
    phase02 = make_phase02([])
    membership = make_membership("UNKNOWN", "MODIS_TERRA")

    with pytest.raises(ValueError, match="unknown observation"):
        aggregate_sensor_frp(phase02, (membership,))


def test_frp_ineligible_observation_is_rejected():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, False),
    ])

    with pytest.raises(ValueError, match="FRP-ineligible"):
        aggregate_sensor_frp(
            phase02,
            (make_membership("T1", "MODIS_TERRA"),),
        )


@pytest.mark.parametrize("frp", [None, -1.0, float("nan"), float("inf")])
def test_invalid_frp_is_rejected(frp):
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", frp, True),
    ])

    with pytest.raises(ValueError, match="Invalid native FRP"):
        aggregate_sensor_frp(
            phase02,
            (make_membership("T1", "MODIS_TERRA"),),
        )


def test_inconsistent_support_unit_metadata_is_rejected():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, True),
        ("T2", "MODIS_AQUA", 20.0, True),
    ])
    first = make_membership("T1", "MODIS_TERRA")
    second = CommonSupportMembership(
        detection_id="T2",
        platform="MODIS_AQUA",
        support_unit_id="UNIT-1",
        spatial_cell_id="CELL-OTHER",
        temporal_group_id="GROUP-1",
        support_date_utc=date(2026, 7, 10),
    )

    with pytest.raises(ValueError, match="Inconsistent metadata"):
        aggregate_sensor_frp(phase02, (first, second))

def test_missing_membership_for_frp_eligible_observation_is_rejected():
    phase02 = make_phase02([
        ("T1", "MODIS_TERRA", 10.0, True),
        ("T2", "MODIS_TERRA", 20.0, True),
    ])

    memberships = (
        make_membership("T1", "MODIS_TERRA"),
    )

    with pytest.raises(
        ValueError,
        match="Missing common-support membership",
    ):
        aggregate_sensor_frp(phase02, memberships)
