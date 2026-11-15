from types import SimpleNamespace

from harmonization.v3.phases.phase_06_common_support_frp import runner


def test_phase_06_runs_all_nine_experiments(monkeypatch):
    aggregates = (
        SimpleNamespace(support_unit_id="paired-support"),
        SimpleNamespace(support_unit_id="unpaired-support"),
    )
    comparisons = (
        SimpleNamespace(support_unit_id="paired-support"),
    )
    calls = {
        "spatial": [],
        "temporal": [],
        "common": 0,
        "aggregate": 0,
        "compare": 0,
        "calibrate": 0,
        "uncertainty": 0,
    }

    monkeypatch.setattr(
        runner, "assign_spatial_support",
        lambda source, config: (
            calls["spatial"].append(config.grid_resolution_km)
            or (config.grid_resolution_km,)
        ),
    )

    monkeypatch.setattr(
        runner, "assign_temporal_support",
        lambda source, assignments, config: (
            calls["temporal"].append(config.max_group_span_minutes)
            or (config.max_group_span_minutes,)
        ),
    )

    monkeypatch.setattr(
        runner, "build_common_support_memberships",
        lambda spatial, temporal: (
            calls.__setitem__("common", calls["common"] + 1) or ("common",)
        ),
    )

    monkeypatch.setattr(
        runner, "aggregate_sensor_frp",
        lambda source, memberships: (
            calls.__setitem__("aggregate", calls["aggregate"] + 1)
            or aggregates
        ),
    )

    monkeypatch.setattr(
        runner, "compare_sensor_frp",
        lambda aggregates: (
            calls.__setitem__("compare", calls["compare"] + 1)
            or comparisons
        ),
    )

    monkeypatch.setattr(
        runner, "evaluate_conditional_calibrations",
        lambda aggregates: (
            calls.__setitem__("calibrate", calls["calibrate"] + 1)
            or ("calibration",)
        ),
    )

    monkeypatch.setattr(
        runner, "estimate_phase_06_uncertainty",
        lambda aggregates, **kwargs: (
            calls.__setitem__("uncertainty", calls["uncertainty"] + 1)
            or SimpleNamespace(warnings=())
        ),
    )

    result = runner.run_phase_06(
        object(),
        n_bootstrap=20,
        retain_intermediate_results=False,
    )

    assert result.experiment_count == 9
    assert len({e.experiment_id for e in result.experiments}) == 9
    assert result.intermediate_results_retained is False
    assert all(
        item.spatial_assignments == ()
        and item.temporal_memberships == ()
        and item.common_support_memberships == ()
        and item.sensor_aggregates == (aggregates[0],)
        for item in result.experiments
    )

    assert calls["spatial"] == [0.5, 1.0, 2.0]
    assert calls["temporal"] == [5.0, 15.0, 30.0] * 3

    for stage in ("common", "aggregate", "compare", "calibrate", "uncertainty"):
        assert calls[stage] == 9

    assert len(result.warnings) > 0
