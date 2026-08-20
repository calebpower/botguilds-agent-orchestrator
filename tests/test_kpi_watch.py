"""Tests for the cross-run KPI regression alarm (steemer.kpi_watch)."""
from steemer.kpi_watch import flag_regressions, KPI_SPECS, CONTEXT_KPIS


def test_flags_a_death_spike_and_an_income_drop_worst_first():
    prev = {"deaths_per_1k": 0.5, "income_per_1k": 7.0, "gold_mean": 100.0}
    curr = {"deaths_per_1k": 2.0, "income_per_1k": 3.0, "gold_mean": 101.0}
    flagged = flag_regressions(prev, curr)
    kinds = [f["kpi"] for f in flagged]
    # deaths quadrupled (severity huge) and income-rate more than halved are both
    # flagged; gold_mean barely moved (+1) so it is NOT flagged.
    assert "deaths_per_1k" in kinds and "income_per_1k" in kinds
    assert "gold_mean" not in kinds
    # worst-first: the death spike (300% over a 25% threshold) outranks the income
    # drop (~57% over a 25% threshold).
    assert kinds[0] == "deaths_per_1k"


def test_improvements_are_never_flagged():
    # every KPI moved in the GOOD direction -> no regressions at all.
    prev = {"deaths_per_1k": 2.0, "move_failed_per_1k": 20.0, "income_per_1k": 4.0,
            "gold_mean": 90.0, "chest_opens_per_1k": 0.1}
    curr = {"deaths_per_1k": 0.3, "move_failed_per_1k": 4.0, "income_per_1k": 8.0,
            "gold_mean": 130.0, "chest_opens_per_1k": 0.3}
    assert flag_regressions(prev, curr) == []


def test_partial_run_does_not_confound_the_income_flag():
    # THE fix (iter 28): the alarm once compared a 30k mid-run to a 64k full run and
    # flagged income -65% when the per-frame RATE was flat — run length confounded it.
    # income_total differs hugely here but income_per_1k is equal -> no regression, and
    # income_total is context (not flagged) so it can never raise a length artifact.
    prev = {"income_per_1k": 7.0, "income_total": 469.0}
    curr = {"income_per_1k": 7.0, "income_total": 163.0}
    assert flag_regressions(prev, curr) == []


def test_small_absolute_change_is_below_the_floor():
    # income rate dropped 0.5/7.0 = 7% and only 0.5 absolute (< the 1.0 floor): noise.
    prev = {"income_per_1k": 7.0}
    curr = {"income_per_1k": 6.5}
    assert flag_regressions(prev, curr) == []


def test_relative_threshold_guards_a_big_absolute_but_small_relative_move():
    # a 2.0 absolute drop (over the 1.0 floor) on a 100 baseline is 2% (< 25% rel).
    prev = {"income_per_1k": 100.0}
    curr = {"income_per_1k": 98.0}
    assert flag_regressions(prev, curr) == []


def test_missing_kpi_is_skipped_not_crashed():
    # a KPI present in one snapshot but not the other is simply not compared.
    assert flag_regressions({"deaths_per_1k": 0.2}, {"income_per_1k": 5.0}) == []


def test_cumulative_totals_and_context_are_never_specced():
    # cumulative totals + world context must NOT be in the flagging spec, or run-length
    # / world-poison swings would raise false code-regression alarms. Only rates flagged.
    for k in ("undead_frac", "frames", "income_total", "chest_opens"):
        assert k not in KPI_SPECS
        assert k in CONTEXT_KPIS
    # and the specced KPIs are all rates / stable means
    assert set(KPI_SPECS) == {"deaths_per_1k", "move_failed_per_1k",
                              "income_per_1k", "gold_mean", "chest_opens_per_1k"}
