"""v0.63.1 — the RIVAL RECON endpoint.

The `spectate` and `track` intel feeds have been written for many runs and only ever read
back as raw rows. This is the comparison they were collected for, and the first look already
paid for itself twice:

  * We field the highest median level (7) and the ONLY fully-armed roster (10/10), while the
    guild with three times our headcount runs a median of 3 and arms 9 of 30.
  * Rivals work at depth median 29-43 (max 57) while our characters sit at median 2 — the
    same depth cap the ore chain has been stuck behind since iter 70, seen from the outside.

Read-only by construction: it issues no actions and cannot affect play.
"""
import json

import pytest

from ui.server import api_recon


def _spectate(guilds):
    return json.dumps({"guilds": guilds})


def _guild(gid, name, roster, worlds=None):
    return {"guild_id": gid, "name": name, "characters": len(roster),
            "roster": roster, "worlds": worlds or {}}


def _char(level=1, hand=None, outfit=None):
    return {"level": level, "equipment": {"hand": hand, "outfit": outfit}}


@pytest.fixture()
def seeded(tmp_path):
    """A DB with one spectate snapshot, one track row, and one decision naming us."""
    import steemer.db as _db
    from steemer.storage import Storage

    path = str(tmp_path / "t.db")
    st = Storage(path)
    st.begin_run("sha", "test/0")
    st.conn.execute(
        "INSERT INTO decisions(tick, world, char_uid, action, chosen_json, "
        "alternatives_json, reasoning, strategy_version, run_id) VALUES(?,?,?,?,?,?,?,?,?)",
        (1, "vale", "g_us_c1", "move", "{}", "[]", "why", "test/0", st.run_id))
    st.conn.execute(
        "INSERT INTO intel(observed_at, tick, kind, payload_json) VALUES(?,?,?,?)",
        (1.0, 5, "spectate", _spectate([
            _guild("g_us", "Us", [_char(9, "club"), _char(5, "dagger")], {"vale": 2}),
            # NOTE the rival also carries a `club`, which we field too. Without an
            # overlapping kind the gap filter cannot be observed at all: nothing we own
            # would ever be a candidate, and the test would pass with the filter deleted.
            _guild("g_them", "Them", [_char(2, "club"), _char(30, "bow", "smith_apron")],
                   {"mines": 2}),
        ])))
    st.conn.execute(
        "INSERT INTO intel(observed_at, tick, kind, payload_json) VALUES(?,?,?,?)",
        (2.0, 6, "track", json.dumps({"map": "mines", "tick": 6, "rivals": [
            {"eid": 1, "pos": [3, 40]}, {"eid": 2, "pos": [4, 20]}]})))
    st.conn.commit()
    st.close() if hasattr(st, "close") else None
    return path


# ---- identifying ourselves ---------------------------------------------------

def test_our_guild_is_derived_from_the_data_not_hardcoded(seeded):
    """A char_uid is "<guild_id>_c<n>", so the newest decision names our guild. Derived
    rather than hardcoded so a rename or re-creation cannot silently make the whole panel
    compare us against ourselves — and so it needs no access to the git-ignored token."""
    d = api_recon(seeded)
    assert d["us"] is not None
    assert d["us"]["name"] == "Us"
    assert [g["us"] for g in d["guilds"]] == [True, False], "we sort first"


def test_a_database_with_no_decisions_still_renders(tmp_path):
    """No history means we cannot tell which guild is ours — the panel must still show the
    standings rather than throwing."""
    import steemer.db as _db
    from steemer.storage import Storage
    path = str(tmp_path / "u.db")
    st = Storage(path)
    st.begin_run("sha", "test/0")
    st.conn.execute(
        "INSERT INTO intel(observed_at, tick, kind, payload_json) VALUES(?,?,?,?)",
        (1.0, 5, "spectate", _spectate([_guild("g_x", "X", [_char(3, "club")])])))
    st.conn.commit()
    d = api_recon(path)
    assert len(d["guilds"]) == 1
    assert d["us"] is None


def test_an_absent_database_returns_empty_rather_than_raising():
    d = api_recon("/nonexistent/nope.db")
    assert d == {"guilds": [], "us": None, "gear_gap": [], "sightings": [], "tick": None}


# ---- the comparison ----------------------------------------------------------

def test_it_reports_level_spread_and_armament_per_guild(seeded):
    d = api_recon(seeded)
    us = d["us"]
    # levels [9, 5] sort to [5, 9]; the median index is len//2 == 1, so both are 9.
    # Spelled out rather than written as `A and B or C`, which operator precedence makes
    # nearly unfalsifiable — the exact weak-assertion shape mutation testing keeps finding.
    assert us["levels"] == [5, 9]
    assert us["level_median"] == 9
    assert us["level_max"] == 9
    assert us["armed"] == 2 and us["roster"] == 2
    them = next(g for g in d["guilds"] if not g["us"])
    assert them["armed"] == 2 and them["roster"] == 2   # both carry a hand item
    assert them["level_max"] == 30


def test_the_gear_gap_lists_only_what_a_rival_fields_and_we_do_not(seeded):
    """The concrete "what do they know that we don't" list — the point of recon. On the
    live data this found `smith_apron`, an outfit no character of ours has ever worn."""
    d = api_recon(seeded)
    kinds = {g["kind"] for g in d["gear_gap"]}
    assert "smith_apron" in kinds and "bow" in kinds
    assert "club" not in kinds, "we field clubs, so a club is not a gap"


def test_rival_positions_are_summarised_by_world_and_depth(seeded):
    d = api_recon(seeded)
    mines = next(s for s in d["sightings"] if s["world"] == "mines")
    assert mines["seen"] == 2
    assert mines["depth_max"] == 40


def test_each_rival_is_counted_once_and_at_its_NEWEST_position(seeded):
    """The track feed samples every tick, so counting ROWS would weight whoever loitered
    longest and make a stationary character look like a crowd.

    The position matters as much as the count: rows are read newest-first, so the first
    sighting of an eid is its CURRENT one. Reporting a stale position would put a rival
    somewhere it has already left — worse than not reporting it, because it looks precise.
    """
    import steemer.db as _db
    conn = _db.connect(seeded)
    for tick in range(7, 31):                      # eid 1 walks steadily deeper
        conn.execute(
            "INSERT INTO intel(observed_at, tick, kind, payload_json) VALUES(?,?,?,?)",
            (float(tick), tick, "track", json.dumps(
                {"map": "mines", "tick": tick, "rivals": [{"eid": 1, "pos": [3, tick]}]})))
    conn.commit()
    d = api_recon(seeded)
    mines = next(s for s in d["sightings"] if s["world"] == "mines")
    assert mines["seen"] == 2, "still two distinct rivals, not fifteen sightings"
    # eid 1 ends at depth 30, deeper than eid 2's fixed 20, so the max is unambiguous:
    # a stale reading would report eid 1 back at depth 7 and the max would fall to 20.
    assert mines["depth_max"] == 30, "eid 1 is reported where it is NOW, not where it was"
