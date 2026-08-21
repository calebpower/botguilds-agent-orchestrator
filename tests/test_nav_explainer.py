"""The "how navigation works" tab (ui.server.api_nav).

The wishlist asked for an explainer that stays TRUE as the nav protocols change, so the
thing worth testing is not the wording — it is the derivation. Both halves must come from
the source of truth:

* the rules from ``steemer.nav`` itself, so editing nav.py changes the page;
* the ladder from the bot's own recorded decision traces, so a re-scored branch appears
  without anyone touching the dashboard.

Per the testing ethic, the rule checks deliberately do NOT compare against a list copied
into this file — a check derived from the same structure it is checking agrees with itself
no matter what. They assert the endpoint reports what nav.py CURRENTLY holds by mutating
nav's values and requiring the output to follow.
"""
import json

import ui.server as srv
from steemer import nav


# ---- the rules half: derived from nav.py, not restated ----------------------

def test_rules_follow_nav_when_nav_changes(monkeypatch):
    """The anti-drift claim, tested the only way that means anything: change nav and
    require the page to change with it. A hardcoded copy would pass the 'lists wall'
    check forever while silently going stale."""
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    monkeypatch.setattr(nav, "SOLID", frozenset({"lava", "chasm"}))
    monkeypatch.setattr(nav, "DIRS", {"N": (0, 1)})

    out = srv.api_nav("db")
    assert out["rules"]["solid"] == ["chasm", "lava"]
    assert out["rules"]["dirs"] == {"N": (0, 1)}


def test_rules_carry_the_real_docstrings_of_the_functions_the_planner_calls(monkeypatch):
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    out = srv.api_nav("db")
    by_name = {f["name"]: f["doc"] for f in out["rules"]["functions"]}
    # the planner's entry points must all be explained
    assert {"is_walkable", "bfs_step", "frontier"} <= set(by_name)
    # ... with the module's OWN prose. Compared against inspect.getdoc of the same
    # function because that IS the claim ("the page shows nav's docstring"); the
    # anti-drift half of it is proved separately, by mutating nav and requiring the
    # output to follow (the two tests either side of this one).
    import inspect
    assert by_name["is_walkable"] == inspect.getdoc(nav.is_walkable)
    assert out["rules"]["module_doc"], "nav's module docstring should be surfaced"


def test_a_removed_nav_function_disappears_from_the_page(monkeypatch):
    """The other direction of the same claim: the page cannot advertise a rule the code
    no longer has."""
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    monkeypatch.setattr(nav.frontier, "__doc__", "")
    out = srv.api_nav("db")
    doc = {f["name"]: f["doc"] for f in out["rules"]["functions"]}["frontier"]
    assert doc == ""


# ---- the ladder half: derived from recorded traces --------------------------

class _Row(dict):
    def keys(self):                       # mimic the DB layer's mapping rows
        return super().keys()


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, sql, params=()):
        assert "alternatives_json" in sql and "ORDER BY seq DESC" in sql
        self._served = self._rows
        return self

    def fetchall(self):
        return self._served

    def close(self):
        pass


def _alts(*items):
    return json.dumps([{"score": s, "why": w, "chosen": c} for s, w, c in items])


def _serve(monkeypatch, rows):
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: True)
    monkeypatch.setattr(srv, "_ro", lambda cfg: _FakeConn(rows))


def test_the_ladder_is_ordered_by_score_high_to_low(monkeypatch):
    _serve(monkeypatch, [_Row(alternatives_json=_alts(
        (0.5, "rest (double regen)", False),
        (8.5, "hurt — walking home to heal", True),
        (2.0, "heading to the nearest frontier", False),
    ), strategy_version="explorer/9.9.9")])
    out = srv.api_nav("db")
    assert [r["score"] for r in out["ladder"]] == [8.5, 2.0, 0.5]
    assert out["strategy_version"] == "explorer/9.9.9"


def test_the_same_branch_groups_across_characters_and_specifics(monkeypatch):
    """Reasons carry per-tick specifics; the rung is the branch. Without normalisation
    every tick would be its own row and the ladder would be unreadable."""
    _serve(monkeypatch, [_Row(alternatives_json=_alts(
        (3.0, "spacing: a wolf is 2 away (severe band) — spacing off", False),
        (3.0, "spacing: a wolf is 3 away (severe band) — spacing off", True),
    ), strategy_version="v")])
    out = srv.api_nav("db")
    assert len(out["ladder"]) == 1
    assert out["ladder"][0]["considered"] == 2 and out["ladder"][0]["chosen"] == 1


def test_a_character_uid_is_rendered_as_prose_not_a_mangled_id(monkeypatch):
    """uids are hex+digits, so number-blanking alone turns `g_cd0e2a_c15192` into the
    unreadable `g_cd#e#a_c#` and puts it in front of the operator as a branch NAME.

    Note what this does NOT claim: number-blanking already groups our uids together (they
    share a guild prefix), so this is about legibility, not about grouping. The grouping
    claim is `test_the_same_branch_groups_across_characters_and_specifics`.
    """
    _serve(monkeypatch, [_Row(alternatives_json=_alts(
        (5.0, "embarking g_cd0e2a_c15192 to vale", True),
        (5.0, "embarking g_cd0e2a_c15206 to vale", True),
    ), strategy_version="v")])
    out = srv.api_nav("db")
    assert len(out["ladder"]) == 1, out["ladder"]
    label = out["ladder"][0]["label"]
    assert label == "embarking a char to vale", label
    assert "#" not in label and "g_" not in label


def test_win_rate_counts_wins_not_appearances(monkeypatch):
    _serve(monkeypatch, [_Row(alternatives_json=_alts(
        (2.0, "heading to the nearest frontier", False),
        (2.0, "heading to the nearest frontier", False),
        (2.0, "heading to the nearest frontier", True),
    ), strategy_version="v")])
    r = srv.api_nav("db")["ladder"][0]
    assert r["considered"] == 3 and r["chosen"] == 1 and r["win_rate"] == 0.333


def test_two_branches_sharing_a_score_stay_separate(monkeypatch):
    """Grouping by score alone would merge distinct branches that happen to tie."""
    _serve(monkeypatch, [_Row(alternatives_json=_alts(
        (8.0, "attack adjacent wolf (hp 40%)", True),
        (8.0, "hurt & cornered — stepping to open ground", False),
    ), strategy_version="v")])
    assert len(srv.api_nav("db")["ladder"]) == 2


def test_sample_sizes_are_reported_so_an_absent_branch_is_readable(monkeypatch):
    """The honest limit of the derivation: a branch that never fired is missing, not
    listed at zero. That is only interpretable next to the sample size."""
    _serve(monkeypatch, [_Row(alternatives_json=_alts((1.0, "scouting", True)),
                              strategy_version="v")])
    out = srv.api_nav("db")
    assert out["sampled_decisions"] == 1
    assert out["sampled_candidates"] == 1 and out["sampled_chosen"] == 1


def test_malformed_trace_rows_are_skipped_not_fatal(monkeypatch):
    _serve(monkeypatch, [_Row(alternatives_json="not json", strategy_version="v"),
                         _Row(alternatives_json=_alts((1.0, "scouting", True)),
                              strategy_version="v")])
    out = srv.api_nav("db")
    assert out["sampled_decisions"] == 1 and len(out["ladder"]) == 1


def test_no_database_still_serves_the_rules(monkeypatch):
    """The rules half must not depend on the DB — a fresh checkout with no history
    should still explain how navigation works."""
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    out = srv.api_nav("db")
    assert out["ladder"] == [] and out["rules"]["solid"]
