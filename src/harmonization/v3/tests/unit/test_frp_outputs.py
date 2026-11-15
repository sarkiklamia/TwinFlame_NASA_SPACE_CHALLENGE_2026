from datetime import date
from types import SimpleNamespace

import pytest

from src.harmonization.v3.phases.phase_07_output_generation.frp_outputs import (
    build_frp_comparisons,
)


def make_experiment():
    support_date = date(2025, 7, 12)

    aggregate_a = SimpleNamespace(
        support_unit_id="FRPS-test",
        spatial_cell_id="CELL-test",
        temporal_group_id="GROUP-test",
        support_date_utc=support_date,
        platform="MODIS_TERRA",
        observation_count=3,
        frp_mean_mw=12.5,
        frp_median_mw=11.0,
        frp_min_mw=8.0,
        frp_max_mw=18.0,
    )

    aggregate_b = SimpleNamespace(
        support_unit_id="FRPS-test",
        spatial_cell_id="CELL-test",
        temporal_group_id="GROUP-test",
        support_date_utc=support_date,
        platform="VIIRS_NOAA20",
        observation_count=2,
        frp_mean_mw=15.0,
        frp_median_mw=14.0,
        frp_min_mw=13.0,
        frp_max_mw=17.0,
    )

    comparison = SimpleNamespace(
        support_unit_id="FRPS-test",
        platform_a="MODIS_TERRA",
        platform_b="VIIRS_NOAA20",
        frp_a_mw=12.5,
        frp_b_mw=15.0,
        difference_mw=2.5,
        relative_difference=0.1818,
    )

    return SimpleNamespace(
        experiment_id="FRP-TEST-001",
        grid_resolution_km=1.0,
        max_group_span_minutes=15.0,
        sensor_aggregates=(aggregate_a, aggregate_b),
        comparisons=(comparison,),
    )


def make_workflow(experiment):
    return SimpleNamespace(
        experiments=(experiment,),
        warnings=(),
    )


def test_frp_output_maps_comparison_and_sensor_counts():
    rows = build_frp_comparisons(
        make_workflow(make_experiment()),
        "run-test",
    )

    assert len(rows) == 1

    row = rows[0]

    assert row["support_id"] == "FRPS-test"
    assert row["date_utc"] == date(2025, 7, 12)
    assert row["spatial_scale_km"] == 1.0
    assert row["temporal_window_minutes"] == 15.0
    assert row["platform_a"] == "MODIS_TERRA"
    assert row["platform_b"] == "VIIRS_NOAA20"
    assert row["frp_a_mw"] == 12.5
    assert row["frp_b_mw"] == 15.0
    assert row["count_a"] == 3
    assert row["count_b"] == 2
    assert row["run_id"] == "run-test"


def test_frp_output_leaves_unavailable_metrics_null():
    rows = build_frp_comparisons(
        make_workflow(make_experiment()),
        "run-test",
    )

    row = rows[0]

    assert row["time_gap_minutes"] is None
    assert row["brightness_summary_a"] is None
    assert row["brightness_summary_b"] is None
    assert row["comparison_eligibility"] == "eligible_common_support"


def test_frp_output_returns_empty_list_without_comparisons():
    experiment = make_experiment()
    experiment = SimpleNamespace(
        **{
            **vars(experiment),
            "comparisons": (),
        }
    )

    rows = build_frp_comparisons(
        make_workflow(experiment),
        "run-test",
    )

    assert rows == []


def test_frp_output_rejects_missing_sensor_aggregate():
    experiment = make_experiment()

    experiment = SimpleNamespace(
        **{
            **vars(experiment),
            "sensor_aggregates": experiment.sensor_aggregates[:1],
        }
    )

    with pytest.raises(ValueError, match="no corresponding sensor aggregate"):
        build_frp_comparisons(make_workflow(experiment), "run-test")


def test_frp_output_rejects_duplicate_sensor_aggregates():
    experiment = make_experiment()

    experiment = SimpleNamespace(
        **{
            **vars(experiment),
            "sensor_aggregates": (
                *experiment.sensor_aggregates,
                experiment.sensor_aggregates[0],
            ),
        }
    )

    with pytest.raises(ValueError, match="Duplicate FRP aggregate"):
        build_frp_comparisons(make_workflow(experiment), "run-test")


def test_frp_output_rejects_empty_run_id():
    with pytest.raises(ValueError, match="run_id"):
        build_frp_comparisons(
            make_workflow(make_experiment()),
            "",
        )


def test_frp_output_rejects_comparison_value_inconsistent_with_aggregate():
    experiment = make_experiment()
    comparison = SimpleNamespace(
        **{
            **vars(experiment.comparisons[0]),
            "frp_a_mw": 999.0,
        }
    )

    experiment = SimpleNamespace(
        **{
            **vars(experiment),
            "comparisons": (comparison,),
        }
    )

    with pytest.raises(ValueError, match="Platform A FRP"):
        build_frp_comparisons(make_workflow(experiment), "run-test")
