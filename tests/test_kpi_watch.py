"""Tests for the cross-run KPI regression alarm (steemer.kpi_watch)."""
from steemer.kpi_watch import flag_regressions, KPI_SPECS


def test_flags_a_death_spike_and_an_income_drop_worst_first():
    prev = {"deaths_per_1k": 0.5, "income_total": 600.0, "gold_mean": 100.0}
    curr = {"deaths_per_1k": 2.0, "income_total": 300.0, "gold_mean": 101.0}
    flagged = flag_regressions(prev, curr)
    kinds = [f["kpi"] for f in flagged]
    # deaths quadrupled (severity huge) and income halved are both flagged;
    # gold_mean barely moved (+1) so it is NOT flagged.
    assert "deaths_per_1k" in kinds and "income_total" in kinds
    assert "gold_mean" not in kinds
    # worst-first: the death spike (300% over a 25% threshold) outranks the income
    # drop (50% over a 25% threshold).
    assert kinds[0] == "deaths_per_1k"


def test_improvements_are_never_flagged():
    # every KPI moved in the GOOD direction -> no regressions at all.
    prev = {"deaths_per_1k": 2.0, "move_failed_per_1k": 20.0, "income_total": 200.0,
            "gold_mean": 90.0, "chest_opens": 3.0}
    curr = {"deaths_per_1k": 0.3, "move_failed_per_1k": 4.0, "income_total": 450.0,
            "gold_mean": 130.0, "chest_opens": 12.0}
    assert flag_regressions(prev, curr) == []


def test_small_absolute_change_is_below_the_floor():
    # income dropped 30/600 = 5% and only 30 absolute (< the 50 floor AND < 25% rel):
    # noise, not a regression.
    prev = {"income_total": 600.0}
    curr = {"income_total": 570.0}
    assert flag_regressions(prev, curr) == []


def test_relative_threshold_guards_a_big_absolute_but_small_relative_move():
    # income fell 60 (over the 50 floor) but on a 6000 baseline that's 1% (< 25% rel).
    prev = {"income_total": 6000.0}
    curr = {"income_total": 5940.0}
    assert flag_regressions(prev, curr) == []


def test_missing_kpi_is_skipped_not_crashed():
    # a KPI present in one snapshot but not the other is simply not compared.
    assert flag_regressions({"deaths_per_1k": 0.2}, {"income_total": 100.0}) == []


def test_context_kpis_are_never_specced():
    # undead_frac / frames are context only — they must not be in the flagging spec,
    # or a swing in the world's poison level would raise a false code-regression alarm.
    assert "undead_frac" not in KPI_SPECS
    assert "frames" not in KPI_SPECS
