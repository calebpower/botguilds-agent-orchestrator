"""v0.123.0 danger corridor — death-history tiles cost more to enter but never
wall ("danger as cost, not wall"). The corridor is loaded from recent death
positions (all guilds), smoothed one tile, capped, and applied at explorer's
_step chokepoint plus the retreat/escape routes."""
import json

from steemer import nav
from steemer.bot import GuildBot
from steemer.storage import Storage
from steemer.strategy.base import FieldContext
from steemer.strategy.explorer import Explorer, DANGER_DETOUR_BUDGET


def _grid():
    """Two routes from (0,0) to the goal (4,0): straight along y=0, or a detour
    along y=1. Every tile is floor."""
    known = {}
    for x in range(5):
        known[(x, 0)] = "floor"
        known[(x, 1)] = "floor"
    return known


def test_weighted_step_detours_around_a_kill_tile_and_only_then():
    known = _grid()
    goal = lambda p: p == (4, 0)
    # no danger: the straight corridor wins (bfs-equivalent unit costs)
    straight = nav.weighted_step((0, 0), goal, known, max_cost=20)
    assert straight == (1, 0), f"clean grid must go straight: {straight}"
    # a 5-weight kill tile mid-corridor: the 2-step detour is cheaper than 5
    around = nav.weighted_step((0, 0), goal, known, max_cost=20,
                               danger={(2, 0): 5})
    assert around == (0, 1), f"the corridor did not deform around danger: {around}"
    # cost, not wall: with no alternate route the kill tile is still crossed
    walled = {p: k for p, k in known.items() if p[1] == 0}
    through = nav.weighted_step((0, 0), goal, walled, max_cost=20,
                                danger={(2, 0): 5})
    assert through == (1, 0), f"danger WALLED the only route: {through}"


def test_explorer_step_routes_by_the_context_danger():
    known = _grid()
    goal = lambda p: p == (4, 0)
    ctx = FieldContext(world="vale", known=known, danger={(2, 0): 5})
    assert Explorer._step((0, 0), goal, ctx, set()) == (0, 1), \
        "explorer._step ignored ctx.danger"
    ctx2 = FieldContext(world="vale", known=known)
    assert Explorer._step((0, 0), goal, ctx2, set()) == (1, 0), \
        "danger-less context must be bfs-equivalent"
    assert DANGER_DETOUR_BUDGET == 12


def _seeded_storage(deaths, top_tick=1000):
    st = Storage(":memory:", commit_every=1)
    st.begin_run("sha", "test/danger")
    for tick, world, pos in deaths:
        st.conn.execute(
            "INSERT INTO events(tick, world, kind, payload_json, run_id) "
            "VALUES(?,?,?,?,?)",
            (tick, world, "death", json.dumps({"pos": list(pos)}), st.run_id))
    st.conn.execute(
        "INSERT INTO events(tick, world, kind, payload_json, run_id) "
        "VALUES(?,?,?,?,?)", (top_tick, "vale", "xp", "{}", st.run_id))
    st.flush()
    return st


def test_the_danger_map_smooths_caps_and_windows():
    st = _seeded_storage([
        (900, "vale", (5, 5)),
        (910, "vale", (5, 5)),
        (920, "vale", (5, 5)),
        (930, "vale", (5, 5)),          # 4 deaths: tile would be 8 -> capped 6
        (940, "mines", (2, 2)),
        (-600_000, "vale", (9, 9)),     # far outside the 500k window
    ])
    d = st.load_danger_map()
    assert d["vale"][(5, 5)] == 6, f"cap missing: {d['vale'][(5, 5)]}"
    assert d["vale"][(6, 5)] == 4, f"neighbour smoothing wrong: {d['vale'][(6, 5)]}"
    assert (9, 9) not in d["vale"], "a corpse outside the window still steers"
    assert d["mines"][(2, 2)] == 2 and d["mines"][(1, 2)] == 1


def test_the_bot_hydrates_and_wires_the_corridor_through_a_field_frame(capsys):
    """Through-the-bot: a char between its gold and a remembered kill-alley must
    step around it — proving hydration AND the FieldContext wiring, not just nav."""
    st = _seeded_storage([(990, "vale", (2, 0))])
    bot = GuildBot(strategy="explorer", storage=st)
    assert bot.danger.get("vale", {}).get((2, 0)) == 2, "hydration missing"
    assert "[danger] hydrated" in capsys.readouterr().out
    tiles = [[x, 0, "floor"] for x in range(5)] + [[x, 1, "floor"] for x in range(5)]
    frame = {"type": "frame", "world": "vale", "tick": 1000,
             "bounds": [5, 2], "events": [],
             "visible": {"tiles": tiles, "entities": [],
                         "gold": [{"pos": [4, 0], "amount": 3}], "items": []},
             "chars": [{"char_uid": "c1", "eid": 1, "pos": [0, 0], "hp": 30,
                        "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": 3,
                        "stats": {}, "gifts": [], "statuses": [], "spells": [],
                        "spell_cap": 1, "carry": {"used": 0, "cap": 20},
                        "inventory": [], "equipment": {"hand": {"kind": "club"}}}]}
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                  "maps": [{"id": "vale"}]}
    acts = bot.on_frame(frame)
    mv = [a for a in acts if a.get("action") == "move" and a.get("char_uid") == "c1"]
    assert mv and mv[0]["dir"] == "N", \
        f"the corridor never reached the field decision: {acts}"
