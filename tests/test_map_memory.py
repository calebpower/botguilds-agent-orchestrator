"""v0.55.0 — PERSISTENT MAP MEMORY: hydrate `known` from `tiles_seen` at startup.

`tiles_seen` was written on every frame and never once read back. The bot therefore
started every run map-blind and re-learned ground it already knew, and we redeploy
several times a day.

v0.54.0 is what made the cost measurable rather than theoretical. Vein-seek was validated
against the DATABASE's accumulated 7,532-tile mines map — 85 vein tiles — and then fired
exactly ZERO times in 7,714 live frames, because a freshly deployed bot has seen almost
none of them. (Run #130 saw 2 unique vein positions across 32,000 frames.) I had validated
against an input the running system did not have: the same failure shape as the 0.51.0
segfault, where the untested input was a caller rather than a data source.

What these tests do NOT prove: that a remembered tile is still accurate. It may not be —
the map is a HINT. A live frame overwrites it on sight, and a stale tile costs at most one
bounced move, which v0.50.0's server-driven learned-block absorbs.
"""
import steemer.db as _db
from steemer.bot import GuildBot
from steemer.storage import Storage


def _storage_with(tiles, tick=5):
    st = Storage(":memory:")
    st.begin_run("sha", "test/0")
    st.record_frame({"world": "mines", "tick": tick,
                     "visible": {"tiles": tiles}, "chars": []})
    st.flush()
    return st


# ---- the round trip ----------------------------------------------------------

def test_tiles_written_by_a_frame_can_be_read_back():
    st = _storage_with([[3, 4, "vein", 0, 0], [3, 5, "floor", 0, 0]])
    assert st.load_known_tiles() == {"mines": {(3, 4): "vein", (3, 5): "floor"}}


def test_a_bot_starts_with_the_remembered_map_already_loaded():
    """The defect itself: this map used to start empty on every single run."""
    st = _storage_with([[3, 4, "vein", 0, 0]])
    bot = GuildBot("explorer", storage=st)
    assert bot.known == {"mines": {(3, 4): "vein"}}


def test_the_remembered_map_survives_a_restart():
    """Two oracles for the claim that matters — the tiles come back (above), AND a
    SECOND bot built on the same storage sees what the first one recorded."""
    st = _storage_with([[1, 1, "vein", 0, 0]])
    first = GuildBot("explorer", storage=st)
    frame = {"type": "frame", "tick": 6, "world": "mines", "chars": [],
             "visible": {"tiles": [[9, 9, "floor", 0, 0]], "entities": [],
                         "items": [], "gold": []}, "events": []}
    # The live loop does BOTH of these per frame (see client.run): the bot learns the
    # tile into `known`, and storage records the frame. They are separate paths, so the
    # test drives both rather than assuming one implies the other.
    first.on_frame(frame)
    st.record_frame(frame)
    st.flush()
    assert (9, 9) in first.known["mines"], "run 1 learned it in memory"
    second = GuildBot("explorer", storage=st)
    assert (9, 9) in second.known.get("mines", {}), "run 2 must inherit run 1's map"


def test_worlds_are_kept_apart():
    st = Storage(":memory:")
    st.begin_run("sha", "test/0")
    st.record_frame({"world": "mines", "tick": 1, "chars": [],
                     "visible": {"tiles": [[0, 0, "vein", 0, 0]]}})
    st.record_frame({"world": "vale", "tick": 2, "chars": [],
                     "visible": {"tiles": [[0, 0, "tree", 0, 0]]}})
    st.flush()
    known = st.load_known_tiles()
    assert known["mines"][(0, 0)] == "vein"
    assert known["vale"][(0, 0)] == "tree"


def test_the_newest_sighting_of_a_tile_wins():
    """A tile that CHANGED must come back as what we saw last, not what we saw first —
    otherwise the memory would actively contradict the world. Note this is enforced by
    the tiles_seen UPSERT, not by the loader: the table holds one row per position, so
    the loader never sees a choice to get wrong."""
    st = Storage(":memory:")
    st.begin_run("sha", "test/0")
    st.record_frame({"world": "mines", "tick": 1, "chars": [],
                     "visible": {"tiles": [[2, 2, "vein", 0, 0]]}})
    st.record_frame({"world": "mines", "tick": 9, "chars": [],
                     "visible": {"tiles": [[2, 2, "floor", 0, 0]]}})
    st.flush()
    assert st.load_known_tiles()["mines"][(2, 2)] == "floor"


# ---- it must never stop the bot starting -------------------------------------

def test_a_bot_with_no_storage_still_starts(capsys):
    """Two claims, and the second is why the `is not None` guard exists at all: with no
    storage the bot must start map-blind AND SILENTLY. Reaching the loader with None and
    letting the except clause catch the AttributeError would also "work", while printing
    a hydration failure on every ordinary offline start."""
    bot = GuildBot("explorer")
    assert bot.known == {}
    assert "could not hydrate" not in capsys.readouterr().out


def test_a_storage_that_cannot_answer_does_not_stop_the_bot():
    """Best-effort by design: a read-only replay or a schema predating the table must
    still start, just map-blind as it always was."""
    class Broken:
        def load_known_tiles(self):
            raise RuntimeError("no such table: tiles_seen")

    bot = GuildBot("explorer", storage=Broken())
    assert bot.known == {}


# ---- what the hydrated map is FOR --------------------------------------------

def test_a_hydrated_map_lets_vein_seek_fire_where_a_blind_one_cannot():
    """The end-to-end point of the change, asserted against the two states directly:
    the same character, on the same ground, seeks ore only when it remembers the map."""
    from steemer.strategy.base import FieldContext
    from steemer.strategy.explorer import Explorer

    tiles = [[x, 0, "floor", 0, 0] for x in range(12)] + [[12, 0, "vein", 0, 0]]
    st = _storage_with(tiles)

    blind = GuildBot("explorer")
    assert Explorer._ore_step(
        (0, 0), FieldContext(world="mines", known=blind.known.get("mines", {})),
        set()) is None, "map-blind: nothing to walk to (this was run #131)"

    remembering = GuildBot("explorer", storage=st)
    assert Explorer._ore_step(
        (0, 0), FieldContext(world="mines", known=remembering.known["mines"]),
        set()) == (1, 0)


# ---- v0.56.0: terrain is durable, CONTENTS are not ---------------------------

def _frame(tiles, world="mines", tick=1):
    return {"type": "frame", "tick": tick, "world": world, "events": [],
            "chars": [{"char_uid": "u1", "eid": 1, "pos": [0, 0], "hp": 9, "max_hp": 9,
                       "stamina": 9, "inventory": [], "equipment": {}}],
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def _containers_seen_by(bot, frame):
    """The container set the strategy is actually handed for this frame — asserted at
    the boundary the strategy sees, not on a bot attribute, so the test cannot pass by
    agreeing with an internal that never reaches a decision."""
    seen = {}

    class Spy:
        version = "spy/0"

        def act(self, _bot, _char, _frame, ctx, _trace):
            seen["c"] = set(ctx.containers)

        def village(self, _bot, _frame):
            return []

    bot.strategy = Spy()
    bot.on_frame(frame)
    return seen["c"]


def test_a_chest_remembered_from_an_earlier_run_is_not_a_target():
    """The v0.55.0 regression itself. `containers` was derived from `known`, so hydrating
    the map promoted chest-beelining from a local errand to a map-wide one — characters
    set off across the whole remembered map toward chests recorded in earlier runs, most
    of them already opened. Move failures went 5.2% -> 21.6% of moves on run #132."""
    st = _storage_with([[40, 40, "chest", 0, 0], [0, 0, "floor", 0, 0]])
    bot = GuildBot("explorer", storage=st)
    assert bot.known["mines"][(40, 40)] == "chest", "the map still REMEMBERS it"
    assert _containers_seen_by(bot, _frame([[0, 0, "floor", 0, 0]])) == set(), \
        "but it is not a target until seen this run"


def test_a_chest_seen_this_run_IS_a_target():
    """The other side of the boundary — without it, the fix above would pass just as
    well if chests stopped being targets altogether."""
    bot = GuildBot("explorer")
    assert _containers_seen_by(bot, _frame([[3, 3, "chest", 0, 0]])) == {(3, 3)}


def test_a_chest_stays_a_target_after_it_leaves_sight():
    """Within a run the set must still ACCUMULATE, exactly as it did before v0.55.0 —
    a character walking to a chest loses sight of it on the way."""
    bot = GuildBot("explorer")
    _containers_seen_by(bot, _frame([[3, 3, "chest", 0, 0]]))
    assert _containers_seen_by(bot, _frame([[9, 9, "floor", 0, 0]], tick=2)) == {(3, 3)}


def test_terrain_from_an_earlier_run_is_STILL_used_for_routing():
    """The distinction the fix rests on: contents are scoped to the run, terrain is not.
    If this fails, the fix has thrown away what v0.55.0 was for."""
    from steemer.strategy.base import FieldContext
    from steemer.strategy.explorer import Explorer

    tiles = [[x, 0, "floor", 0, 0] for x in range(12)] + [[12, 0, "vein", 0, 0]]
    bot = GuildBot("explorer", storage=_storage_with(tiles))
    ctx = FieldContext(world="mines", known=bot.known["mines"])
    assert Explorer._ore_step((0, 0), ctx, set()) == (1, 0)


def test_worlds_do_not_share_their_this_run_sightings():
    """The worlds must be kept apart at the SAME coordinates, or the test proves nothing:
    a shared sighting set is harmless while (3,3) means nothing in the other world. Here
    vale also remembers a chest at (3,3) from an earlier run, so a shared set would let a
    sighting in the MINES resurrect vale's stale chest as a live target."""
    st = Storage(":memory:")
    st.begin_run("sha", "test/0")
    st.record_frame({"world": "vale", "tick": 1, "chars": [],
                     "visible": {"tiles": [[3, 3, "chest", 0, 0]]}})
    st.flush()
    bot = GuildBot("explorer", storage=st)
    assert bot.known["vale"][(3, 3)] == "chest", "vale REMEMBERS a chest there"
    seen_in_mines = _containers_seen_by(bot, _frame([[3, 3, "chest", 0, 0]], world="mines"))
    assert seen_in_mines == {(3, 3)}, "seeing one in the mines is fine"
    assert _containers_seen_by(bot, _frame([[8, 8, "floor", 0, 0]], world="vale")) == set()
