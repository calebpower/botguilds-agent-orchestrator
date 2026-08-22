"""Attribution-safe metrics — the guardrail for a measured failure rate.

Across one 24-hour stretch this loop produced SIX attribution errors, every one from a
hand-written query that interpreted a number before establishing what it counted. The worst
reached the operator as a reported result and had to be retracted: a forge success rate of
"35% -> 68%" that counted RIVAL forges. On run #141 the real figures are 4 ours against 13
world-wide — and 13 is exactly the number that was reported.

A "Metric attribution" section existed in orchestrator/loop.md through all six, and memory
already warned that death queries count rivals. A directive that cannot fail does not change
behaviour. These tests pin the properties that make the failure hard to repeat:

  * `ours_only` defaults TRUE, so the safe answer is the one you get by not thinking
  * run-scoped questions raise `TooEarly` below a maturity threshold
  * `compare()` cannot yield a delta without the band confounder beside it
  * `distinct_entities()` answers "how many", never "how often"
"""
import json

import pytest

import steemer.attribution as m
from steemer.storage import Storage


def _db(tmp_path, frames=40_000, ours=(7, 8), rivals=(999,)):
    """A DB with our characters, some rival events, and a settable frame count."""
    st = Storage(str(tmp_path / "m.db"))
    st.begin_run("sha", "test/0")
    st.conn.execute(
        "INSERT INTO decisions(tick, world, char_uid, action, chosen_json, "
        "alternatives_json, reasoning, strategy_version, run_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (1, "vale", "g_us_c1", "move", "{}", "[]", "why", "test/0", st.run_id))
    chars = [{"char_uid": f"g_us_c{e}", "eid": e, "pos": [0, 0]} for e in ours]
    for i in range(frames):
        st.conn.execute(
            "INSERT INTO frames(seq, tick, world, received_at, run_id, json) "
            "VALUES(?,?,?,?,?,?)",
            (i, i, "vale", 0.0, st.run_id,
             json.dumps({"world": "vale", "chars": chars if i % 100 == 0 else [],
                         "visible": {"items": [{"pos": [1, 1]}] if i % 2 == 0 else []}})))
    def ev(kind, payload):
        st.conn.execute(
            "INSERT INTO events(tick, world, kind, payload_json, run_id) VALUES(?,?,?,?,?)",
            (1, "vale", kind, json.dumps(payload), st.run_id))
    for e in ours:
        ev("forged", {"kind": "forged", "eid": e, "item": "spear"})
    for e in rivals:
        ev("forged", {"kind": "forged", "eid": e, "item": "pickaxe"})
        ev("forged", {"kind": "forged", "eid": e, "item": "sickle"})
    ev("sale", {"kind": "sale", "guild_id": "g_us", "item": "lumber", "gold": 3})
    ev("sale", {"kind": "sale", "guild_id": "g_them", "item": "bow", "gold": 9})
    st.conn.commit()
    m._EID_CACHE.clear()
    return st.conn, st.run_id


# ---- the default is the safe answer -------------------------------------------

def test_events_are_OURS_by_default(tmp_path):
    """The retraction in one assertion: two of ours, three world-wide."""
    conn, rid = _db(tmp_path)
    assert len(m.events(conn, rid, "forged")) == 2
    assert len(m.events(conn, rid, "forged", ours_only=False)) == 4


def test_counting_rivals_requires_saying_so_out_loud(tmp_path):
    """You can still ask the world-wide question — but never by accident."""
    conn, rid = _db(tmp_path)
    import inspect
    assert inspect.signature(m.events).parameters["ours_only"].default is True
    assert inspect.signature(m.rate_per).parameters["ours_only"].default is True
    assert inspect.signature(m.distinct_entities).parameters["ours_only"].default is True


def test_guild_events_are_attributed_by_guild_id_not_eid(tmp_path):
    """The server uses TWO ownership channels: `eid` on character events and `guild_id` on
    guild events like `sale`. Filtering on eid alone would silently drop every sale."""
    conn, rid = _db(tmp_path)
    assert len(m.events(conn, rid, "sale")) == 1
    assert len(m.events(conn, rid, "sale", ours_only=False)) == 2


def test_our_guild_is_derived_from_the_data(tmp_path):
    conn, rid = _db(tmp_path)
    assert m.our_guild_id(conn) == "g_us"


def test_a_run_with_no_characters_of_ours_refuses_to_attribute(tmp_path):
    """Better an exception than a confident zero."""
    conn, rid = _db(tmp_path, ours=())
    with pytest.raises(m.Unattributed):
        m.events(conn, rid, "forged")


# ---- too young to have an answer ----------------------------------------------

def test_a_young_run_raises_rather_than_answering(tmp_path):
    """Both "it has stopped entirely" alarms came from minutes-old samples. This is
    shadow.MIN_DECISIONS' lesson applied to every ad-hoc question."""
    conn, rid = _db(tmp_path, frames=500)
    with pytest.raises(m.TooEarly):
        m.rate_per(conn, rid, "forged")


def test_a_mature_run_answers_normally(tmp_path):
    conn, rid = _db(tmp_path, frames=40_000)
    assert m.rate_per(conn, rid, "forged", per=10_000) == pytest.approx(0.5)


def test_the_maturity_bar_can_be_lowered_but_only_deliberately(tmp_path):
    conn, rid = _db(tmp_path, frames=500)
    assert m.require_mature(conn, rid, min_frames=100) == 500


# ---- how many, not how often ---------------------------------------------------

def test_distinct_entities_collapses_repeat_sightings(tmp_path):
    """A blind spot was once sized from 2,500-4,600 SIGHTINGS of the same 22 tiles."""
    conn, rid = _db(tmp_path)
    for _ in range(50):
        conn.execute(
            "INSERT INTO events(tick, world, kind, payload_json, run_id) VALUES(?,?,?,?,?)",
            (2, "vale", "forged", json.dumps({"eid": 7, "item": "spear"}), rid))
    conn.commit()
    assert len(m.events(conn, rid, "forged")) == 52       # how often
    assert m.distinct_entities(conn, rid, "forged") == 2  # how many


# ---- the confounder travels with the delta -------------------------------------

def test_compare_reports_the_band_alongside_the_delta(tmp_path):
    conn, rid = _db(tmp_path)
    r = m.compare(conn, rid, rid, "forged")
    assert "items_per_frame" in r["a"] and "items_per_frame" in r["b"]
    assert "verdict" in r
    # The delta must be the actual difference, not merely present: a stub that always
    # returned 0.0 would satisfy "the key exists" and report every change as no change.
    assert r["delta"] == pytest.approx(r["b"]["rate"] - r["a"]["rate"])
    assert r["delta"] == pytest.approx(0.0), "a run against itself has moved nowhere"


def test_compare_flags_two_runs_the_band_makes_incomparable(tmp_path):
    """A good change was nearly reverted on runs whose loot density differed 2.7x."""
    conn, a = _db(tmp_path)
    b = a + 1
    # A second run in the SAME database with a QUARTER of the loot density — the shape that
    # caused the near-revert (0.444 vs 0.162 items/frame between two real runs).
    conn.executemany(
        "INSERT INTO frames(seq, tick, world, received_at, run_id, json) VALUES(?,?,?,?,?,?)",
        [(100_000 + i, i, "vale", 0.0, b,
          json.dumps({"world": "vale",
                      "chars": [{"char_uid": "g_us_c7", "eid": 7, "pos": [0, 0]}],
                      "visible": {"items": [{"pos": [1, 1]}] if i % 8 == 0 else []}}))
         for i in range(40_000)])
    conn.execute("INSERT INTO events(tick, world, kind, payload_json, run_id) "
                 "VALUES(?,?,?,?,?)",
                 (1, "vale", "forged", json.dumps({"eid": 7}), b))
    conn.commit()
    m._EID_CACHE.clear()
    r = m.compare(conn, a, b, "forged")
    # Two DIFFERENT runs, so a stubbed-zero delta is distinguishable here where a
    # run-against-itself comparison could never show it.
    assert r["a"]["rate"] != r["b"]["rate"]
    assert r["delta"] == pytest.approx(r["b"]["rate"] - r["a"]["rate"])
    assert r["delta"] != 0
    assert r["comparable"] is False
    assert "NOT COMPARABLE" in r["verdict"]
    assert r["band_ratio"] > m.BAND_COMPARABLE_RATIO


def test_compare_accepts_runs_of_similar_density(tmp_path):
    """The other side of the boundary — otherwise the guard could pass by calling
    everything incomparable, which is just a different way of saying nothing."""
    conn, rid = _db(tmp_path)
    r = m.compare(conn, rid, rid, "forged")
    assert r["comparable"] is True
    assert r["band_ratio"] == pytest.approx(1.0)
