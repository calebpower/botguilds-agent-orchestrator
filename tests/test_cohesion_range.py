"""v0.73.0 — a rally is only worth starting if it can FINISH.

0.72.0 fixed cohesion's mutual pursuit by rallying to the group's centre, a fixed point,
and proved convergence in `test_cohesion_convergence.py`. It converges there because the
simulation gives every character an uninterrupted run of ticks. Play does not:

    run 150: group spread median 43 tiles, tight (<=6) on 1.7% of frames
    run 151: group spread median 39 tiles, tight (<=6) on 1.3% of frames   <- after 0.72.0

while cohesion's share of CHOSEN decisions went UP, 11.6% -> 17.6%. The rally was being
started constantly and finished essentially never, because a field stint is median 10-12
ticks (`tools/field_stints.py`) and the distance to the centre is median 13, p75 22.

That is the same defect as an over-long errand, and it has a general form worth naming:
a behaviour that needs N uninterrupted ticks must be gated on N, not on how good the
destination is. These tests pin the gate.

They do NOT prove the group converges in play — only that we stop spending movement on
rallies that cannot land. Convergence is `test_cohesion_convergence.py`, and whether it
holds in play is a MEASUREMENT, recorded against run #152.
"""
from steemer.bot import GuildBot
from steemer.reasoning import DecisionTrace
from steemer.strategy.base import FieldContext
from steemer.strategy.explorer import Explorer, COHESION_PRED_DENSE


def _dangerous(exp, tick=500, world="mines"):
    exp._world_danger[world] = (0.0, COHESION_PRED_DENSE, tick)
    return exp


def _char(pos, uid="u1"):
    return {"char_uid": uid, "eid": 7, "pos": list(pos), "hp": 30, "max_hp": 30,
            "stamina": 40, "level": 3, "stats": {}, "gifts": [], "statuses": [],
            "spells": [], "spell_cap": 1, "carry": {"used": 1, "cap": 21},
            "inventory": [], "equipment": {"hand": {"kind": "club"}}}


def _rally_reasons(pos, ally_positions):
    """Every cohesion candidate offered to a character at `pos`, in a dangerous world.

    Drives the REAL `GuildBot` rather than a hand-rolled stand-in. The first draft of this
    file used a four-attribute double and it broke immediately on `bot.config` — which is
    the cheap version of the failure that matters: a double that keeps working while
    drifting from the object it imitates tests a bot we do not ship.
    """
    bot = GuildBot("explorer")
    bot.tick = 500
    exp = _dangerous(bot.strategy)
    known = {(x, y): "floor" for x in range(60) for y in range(60)}
    ctx = FieldContext(world="mines", known=known)
    chars = [_char(pos)] + [_char(p, f"a{i}") for i, p in enumerate(ally_positions)]
    trace = DecisionTrace(tick=500, world="mines", char_uid="u1")
    exp.act(bot, chars[0], {"world": "mines", "tick": 500, "chars": chars}, ctx, trace)
    return [c.why for c in trace.candidates if "rallying" in c.why]


def test_a_rally_from_WITHIN_reach_is_offered():
    """Allies centred on (10,10); we stand 6 tiles off — closable inside a median stint."""
    assert _rally_reasons((16, 10), [(10, 8), (10, 12)]), \
        "a rally we could actually finish was not offered"


def test_a_rally_from_BEYOND_reach_is_NOT_offered():
    """Same formation, 20 tiles off. On #151 this was the common case — median distance to
    the centre was 13 and p75 was 22 — and every one of those rallies was movement spent
    on an errand the stint would cut short."""
    assert _rally_reasons((30, 10), [(10, 8), (10, 12)]) == [], \
        "offered a rally that cannot finish inside a field stint"


def test_the_gate_measures_the_CENTRE_not_the_NEAREST_ALLY():
    """The 0.72.0 inconsistency, pinned.

    0.72.0 changed the STEP to target the centre and left the GATE measuring the nearest
    ally. So a character could be 10 tiles from an ally — comfortably past COHESION_PULL,
    so the gate said "form up" — and 30 tiles from the centre the step actually walks
    toward. It would set off and never arrive, every tick, for the whole run.

    Allies at (20,2) and (20,10): centre (20,6). We stand at (10,10): 10 from the nearest
    ally, 14 from the centre. The old gate rallies. The new one must not.

    Every position here stays ABOVE `POISON_SAFE_DEPTH`. The first draft of this test put
    the character at y=40, where a character carrying no heal takes the poison-retreat
    branch and never reaches the cohesion block — so it asserted "no rally offered" and was
    right for a reason that had nothing to do with the gate. Mutation testing caught it:
    the mutant that restores the old gate SURVIVED.
    """
    assert _rally_reasons((10, 10), [(20, 2), (20, 10)]) == [], \
        "gated on the nearest ally again — the step and the gate must measure the same thing"


def test_the_reason_reports_the_distance_it_actually_WALKS():
    """The decision trace is our primary evidence, and a trace that names the wrong
    quantity is how a bad measurement gets believed: 0.72.0's said "closing on the nearest
    ally (N away)" while walking to the centre, so the logged distance was not the distance
    being closed. Allies (10,4) and (10,12) -> centre (10,8); from (14,8) that is 4, while
    the nearest ally is 8 away."""
    reasons = _rally_reasons((14, 8), [(10, 4), (10, 12)])
    assert reasons, "no rally offered, so the reason cannot be checked"
    assert "(4 away" in reasons[0], f"reported the wrong distance: {reasons[0]!r}"


def test_the_bounded_rally_is_reachable_THROUGH_THE_BOT():
    """Drives `GuildBot.on_frame` — the entry point the live loop calls. Four behaviours
    have shipped correct and unreachable because their tests started downstream of the
    routing."""
    bot = GuildBot("explorer")
    bot.tick = 500
    _dangerous(bot.strategy)
    tiles = [[x, y, "floor", 0, 0] for x in range(20) for y in range(6, 15)]
    chars = [_char((16, 10)), _char((10, 8), "a0"), _char((10, 12), "a1")]
    actions = bot.on_frame({"type": "frame", "world": "mines", "tick": 500, "events": [],
                            "bounds": [64, 176], "chars": chars,
                            "visible": {"tiles": tiles, "entities": [], "items": [],
                                        "gold": []}})
    mine = [a for a in actions if a.get("char_uid") == "u1"]
    assert mine, "the bot produced no action for the out-of-position character"
    assert mine[0].get("action") == "move" and mine[0].get("dir") == "W", \
        f"should step toward the group centre at (10,10): {mine[0]}"
