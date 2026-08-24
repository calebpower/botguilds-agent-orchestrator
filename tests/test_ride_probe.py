"""v0.93.0 — the ride probe: one guarded `ride` experiment per run.

`ride` has never been issued by anyone on this server; slice 1 buys the semantics
(clean slide vs error taxonomy vs the operator's minecart hypothesis) for one tick.
Guards under test: on-rail only, armed only (green doctrine), healthy+calm only, ONCE
per run, and the direction must follow the rail. HP/stamina literals are pinned."""
from steemer.bot import GuildBot

HP_FRAC = 0.7
MIN_STA = 15


def test_pinned_literals():
    from steemer.strategy import explorer
    assert explorer.RIDE_PROBE_HP_FRAC == HP_FRAC
    assert explorer.RIDE_PROBE_MIN_STA == MIN_STA


def _bot():
    b = GuildBot("explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "mines"}]}
    b.tick = 600
    return b


def _frame(char_over=None, entities=(), tiles_extra=()):
    tiles = [[x, y, "floor", 0, 0] for x in range(8) for y in range(8)]
    tiles += [list(t) for t in tiles_extra]
    ch = {"char_uid": "c1", "eid": 7, "pos": [3, 3], "hp": 30, "max_hp": 30,
          "stamina": 40, "max_stamina": 56, "level": 3, "stats": {"str": 2},
          "gifts": [], "statuses": [], "spells": [], "carry": {"used": 0, "cap": 20},
          "inventory": [], "equipment": {"hand": {"kind": "club"}}}
    ch.update(char_over or {})
    return {"type": "frame", "world": "mines", "tick": 600, "events": [],
            "bounds": [8, 200], "chars": [ch],
            "visible": {"tiles": tiles,
                        "entities": [{"eid": e, "kind": k, "pos": list(p),
                                      "faction": "monster"} for e, k, p in entities],
                        "items": [], "gold": []}}


RAIL = ((3, 3, "track", 0, 0), (3, 4, "track", 0, 0), (3, 5, "track", 0, 0))


def _rides(acts):
    return [a for a in acts if a.get("action") == "ride"]


def test_the_probe_fires_on_a_rail_and_follows_it():
    acts = _bot().on_frame(_frame(tiles_extra=RAIL))
    r = _rides(acts)
    assert r and r[0]["dir"] == "S", f"expected a ride S along the rail, got {acts}"


def test_the_probe_fires_ONCE_per_run():
    bot = _bot()
    first = _rides(bot.on_frame(_frame(tiles_extra=RAIL)))
    bot.tick = 601
    f2 = _frame(tiles_extra=RAIL); f2["tick"] = 601
    second = _rides(bot.on_frame(f2))
    assert first and not second, f"probe fired twice: {second}"


def test_a_bare_handed_char_never_probes():
    """The green doctrine extends to experiments: an unarmed char cannot afford the
    ram, or the destination."""
    acts = _bot().on_frame(_frame({"equipment": {}}, tiles_extra=RAIL))
    assert not _rides(acts), "a bare-handed char rode the rail"


def test_no_probe_with_a_predator_in_flee_radius():
    acts = _bot().on_frame(_frame(entities=[(90, "wolf", (5, 3))], tiles_extra=RAIL))
    assert not _rides(acts), "probed with a wolf two tiles away"


def test_no_probe_off_the_rail_or_on_a_dead_end():
    # standing on FLOOR with a rail RIGHT THERE at (3,4): still no ride — you must be
    # ON the track (this is the fixture that kills the is-not-None standing-check
    # mutant, which the plain-floor and lone-track cases both let live)
    beside = ((3, 4, "track", 0, 0), (3, 5, "track", 0, 0))
    assert not _rides(_bot().on_frame(_frame(tiles_extra=beside)))
    # standing on an ISOLATED track tile (no adjacent rail): no direction, no ride
    lone = ((3, 3, "track", 0, 0),)
    assert not _rides(_bot().on_frame(_frame(tiles_extra=lone)))


def test_a_hurt_char_never_probes():
    acts = _bot().on_frame(_frame({"hp": 20}, tiles_extra=RAIL))   # 20/30 < 0.7
    assert not _rides(acts), "a hurt char rode the rail"


# ---- v0.93.1: the seek makes the probe REACHABLE ------------------------------------
# Slice 1 sat unreachable (run #184: 0 sends — armed chars never crossed a rail). A
# qualified prober now walks to the nearest known rideable rail.

def _field_frame(char_over=None, tiles_extra=(), entities=()):
    """A NON-village field frame so the safe non-homing gather branch (where the seek
    lives) is reached — the probe/seek only run in the field."""
    tiles = [[x, y, "floor", 0, 0] for x in range(12) for y in range(12)]
    tiles += [list(t) for t in tiles_extra]
    ch = {"char_uid": "c1", "eid": 7, "pos": [1, 1], "hp": 30, "max_hp": 30,
          "stamina": 40, "max_stamina": 56, "level": 3, "stats": {"str": 2},
          "gifts": [], "statuses": [], "spells": [], "carry": {"used": 0, "cap": 20},
          "inventory": [], "equipment": {"hand": {"kind": "club"}}}
    ch.update(char_over or {})
    return {"type": "frame", "world": "mines", "tick": 600, "events": [],
            "bounds": [12, 200], "chars": [ch],
            "visible": {"tiles": tiles,
                        "entities": [{"eid": e, "kind": k, "pos": list(p),
                                      "faction": "monster"} for e, k, p in entities],
                        "items": [], "gold": []}}


# a rideable rail (two adjacent track tiles) four tiles east of the char at (1,1)
FAR_RAIL = ((5, 1, "track", 0, 0), (6, 1, "track", 0, 0))


def _moves_toward_rail(acts, uid="c1"):
    m = [a for a in acts if a.get("char_uid") == uid and a.get("action") == "move"]
    return m and m[0].get("dir") == "E"      # rail is due east


def test_a_qualified_prober_walks_toward_a_known_rail():
    acts = _bot().on_frame(_field_frame(tiles_extra=FAR_RAIL))
    assert _moves_toward_rail(acts), f"prober did not head for the rail: {acts}"


def test_a_bare_handed_char_does_not_seek_the_rail():
    acts = _bot().on_frame(_field_frame({"equipment": {}}, tiles_extra=FAR_RAIL))
    assert not _moves_toward_rail(acts), "a bare-handed char sought the rail"


def test_a_lone_rail_tile_is_not_sought():
    """A single track with no track neighbour is a dead ride — the probe needs a
    direction, so the seek must ignore it (kills a 'seek any track' mutant)."""
    lone = ((5, 1, "track", 0, 0),)
    acts = _bot().on_frame(_field_frame(tiles_extra=lone))
    assert not _moves_toward_rail(acts), "sought a lone (un-rideable) track tile"


def test_the_seek_stops_once_ON_the_rail_and_the_probe_fires():
    """Standing on a rideable rail: the fire offer takes over and a ride is issued."""
    on_rail = ((1, 1, "track", 0, 0), (1, 2, "track", 0, 0))
    acts = _bot().on_frame(_field_frame(tiles_extra=on_rail))
    assert _rides(acts), f"on the rail but did not fire the probe: {acts}"


def test_a_char_on_a_LONE_track_seeks_a_real_rail_instead_of_stranding():
    """Regression for the first-draft guard (pos != 'track'), which stranded a prober
    parked on a lone track: it must still walk to a rideable rail elsewhere. Char on a
    lone track at (1,1); rideable pair four east — expect a move E, and NO ride (the
    lone tile is not rideable)."""
    lone_here_rail_east = ((1, 1, "track", 0, 0),
                           (5, 1, "track", 0, 0), (6, 1, "track", 0, 0))
    acts = _bot().on_frame(_field_frame(tiles_extra=lone_here_rail_east))
    assert _moves_toward_rail(acts), f"stranded on the lone track: {acts}"
    assert not _rides(acts), "fired a ride from a lone (un-rideable) track"


def test_an_unhealed_prober_feels_no_pull_from_a_rail_past_the_poison_cap():
    """v0.105.1 — run #198's chorus line: the ride probe was the seek 0.105.0 shipped
    step-gated only (and named as the gap). An un-healed anchor marched to y11 chasing
    a rail at y>=13 it could never reach, stalled against the cap, and its two escorts
    held formation on the stall — three chars parked in a row at y11. The rail GOAL is
    now filtered: no pull at any distance, the char heads home instead. Bounded world
    (no frontier) so the rail pull is the only candidate the mutant could win with."""
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    assert POISON_SAFE_DEPTH == 12, "cap moved — update this test's literal geometry"
    bot = _bot()
    tiles = [[x, y, "floor", 0, 0] for x in range(8) for y in range(17)]
    tiles += [[3, 13, "track", 0, 0], [3, 14, "track", 0, 0], [3, 15, "track", 0, 0]]
    frame = {"type": "frame", "world": "mines", "tick": 600, "events": [],
             "bounds": [8, 17],
             "chars": [{"char_uid": "c1", "eid": 7, "pos": [3, 10], "hp": 30,
                        "max_hp": 30, "stamina": 40, "max_stamina": 56, "level": 3,
                        "stats": {"str": 2}, "gifts": [], "statuses": [], "spells": [],
                        "carry": {"used": 0, "cap": 20}, "inventory": [],
                        "equipment": {"hand": {"kind": "club"}}}],
             "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}
    acts = bot.on_frame(frame)
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts), acts
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts, \
        f"should commit home (looted-out), got {acts}"
