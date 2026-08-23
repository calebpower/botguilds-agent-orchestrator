"""v0.84.0 — the planned escape: danger is a price, not a wall.

Reconstruction of Recruit-17384's death on run #170 (tick 2020238): hurt at (23,6) with a
rat_brown at (22,5) and a wolf at (22,7), east wall at (24,6). Their strike ranges cover
every neighbour, so the retreat found nothing, the desperation step found nothing, and the
character chose `rest` six consecutive ticks at full stamina until dead at 2 hp. The
second wizard corpse (c17392) is the same shape with a bounce instead of a rest.

The escape router prices a strike-range tile at nav.AVOID_COST (~one eaten hit) instead
of banning it: crossing once, on purpose, beats resting to death. What these tests do not
prove: that the crossing survives the hit — that is the live falsification (wizard/boxed
deaths per 10k on the next mature run).
"""
from steemer.bot import GuildBot


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    return b


def _boxed_char(hp=9):
    return {"char_uid": "c1", "eid": 7, "pos": [23, 6], "hp": hp, "max_hp": 30,
            "stamina": 48, "max_stamina": 56, "level": 2, "stats": {}, "gifts": [],
            "statuses": [], "spells": [], "spell_cap": 1, "carry": {"used": 4, "cap": 24},
            "inventory": [], "equipment": {"hand": {"kind": "club"}}}


def _box_frame(char, rat=(22, 5), wolf=(22, 7)):
    """The death geometry: open floor except a wall at (24,6); predators west."""
    tiles = []
    for x in range(20, 27):
        for y in range(0, 10):
            kind = "wall" if (x, y) == (24, 6) else "floor"
            tiles.append([x, y, kind, 0, 0])
    ents = [{"eid": 50, "kind": "rat_brown", "pos": list(rat), "faction": "monster"},
            {"eid": 51, "kind": "wolf", "pos": list(wolf), "faction": "monster"}]
    return {"type": "frame", "world": "vale", "tick": 500, "events": [],
            "bounds": [64, 200], "chars": [char],
            "visible": {"tiles": tiles, "entities": ents, "items": [], "gold": []}}


def test_the_boxed_wizard_geometry_now_ESCAPES_instead_of_resting():
    """The exact box that killed c17384: every neighbour is strike-range or wall. The old
    ladder's best offer was rest; the planned escape must offer a MOVE, southward through
    strike range toward home."""
    bot = _bot()
    acts = bot.on_frame(_box_frame(_boxed_char()))
    assert acts and acts[0]["action"] == "move", \
        f"still resting in the death box: {acts}"
    assert acts[0]["dir"] == "S", f"escape should head home through the gap: {acts}"


def test_a_CLEAN_retreat_still_outranks_the_priced_crossing():
    """Predators far enough that a strike-free homeward step exists: the 8.5 retreat must
    win over the 8.2 planned escape — never cross strike range when a safe route exists."""
    bot = _bot()
    acts = bot.on_frame(_box_frame(_boxed_char(), rat=(20, 9), wolf=(26, 9)))
    assert acts and acts[0]["action"] == "move" and acts[0]["dir"] == "S"
    # the winning reason must be the clean retreat, not the crossing
    row = [a for a in acts if a.get("action") == "move"][0]
    # decision reasoning is not in the action; assert via the strategy trace instead
    from steemer.reasoning import DecisionTrace
    from steemer.strategy.base import FieldContext
    import steemer.nav as nav
    char = _boxed_char()
    known = {(x, y): "floor" for x in range(20, 27) for y in range(0, 10)}
    ctx = FieldContext(world="vale", known=known,
                       enemies={(20, 9): {"kind": "rat_brown"}, (26, 9): {"kind": "wolf"}},
                       bounds=(64, 200))
    tr = DecisionTrace(tick=500, world="vale", char_uid="c1")
    bot.strategy.act(bot, char, {"world": "vale", "tick": 500, "chars": [char]}, ctx, tr)
    top = max(c.score for c in tr.candidates)
    won = [c.why for c in tr.candidates if c.score == top]
    assert any("walking home to heal" in w for w in won), f"clean retreat lost: {won}"


def test_a_HEALTHY_char_never_uses_the_priced_crossing():
    """Full hp in the same box: the escape is a survival behaviour, not a shortcut —
    a healthy character keeps treating strike range as a wall."""
    bot = _bot()
    acts = bot.on_frame(_box_frame(_boxed_char(hp=30)))
    assert not any("boxed in" in str(a) for a in acts)


def test_the_router_crosses_as_LITTLE_strike_range_as_possible():
    """Nav-level, two exits from a box, and the DANGEROUS one is the raw-shortest —
    deliberately, because the first version of this test had the safe corridor shorter
    too, so it passed with the cost deleted (the mutant survived twice). Direct south is
    4 steps through TWO strike tiles (cost 2*9+2=20); the eastern detour is 6 steps
    through ONE (cost 9+5=14). With AVOID_COST the detour wins; without it the raw count
    (4 < 6) sends the router through both strikes."""
    import steemer.nav as nav
    known = {}
    for x in range(0, 8):
        for y in range(0, 6):
            known[(x, y)] = "wall"
    for p in [(4, 4), (4, 3), (4, 2), (4, 1), (4, 0),                 # direct south
              (5, 4), (6, 4), (6, 3), (6, 2), (6, 1), (6, 0)]:        # eastern detour
        known[p] = "floor"
    strike = {(4, 3), (4, 2), (6, 3)}
    step = nav.weighted_step((4, 4), lambda p: p[1] == 0, known, blocked=(), avoid=strike)
    assert step == (5, 4), f"crossed two strike tiles when one would do: {step}"
