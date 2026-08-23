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
