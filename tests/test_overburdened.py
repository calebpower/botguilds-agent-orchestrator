"""v0.62.0 — trusting the server's `overburdened` refusal.

Found by the v0.61.0 expectation detector on its first run over real data: `pickup`
confirmed 90 times against 811 VIOLATIONS across 20,000 frames. All 1,164 `overburdened`
events were the same character in the same state — carry **(19, 21)**, two slots free —
retrying forever.

The gap is a units mismatch. Our fullness test counts SLOTS (`used >= cap - 1`) while the
server spends capacity in BULK. At 19/21 a character cannot take a bulk-3 item, yet it is
not "full" by our rule (which needs 20) and not shedding either (which needs 21). It sits in
between, re-issuing a doomed pickup that nothing learns from — the same shape as the
pre-v0.50.0 learned-block bug.

And the reason no error query ever showed it: **`overburdened` arrives as an EVENT, not an
action_error.** The server refuses through two channels and we had only ever watched one.

The fix trusts the refusal rather than modelling bulk. Ground items do not even expose
`bulk` (only `kind` and `tier`), so a bulk model would have to be inferred from inventories
and would still be a guess; the server's verdict is a fact.
"""
from steemer.bot import GuildBot, OVERBURDENED_TTL


def _frame(tick, events=(), pos=(1, 1), uid="u1", eid=7):
    return {"type": "frame", "world": "vale", "tick": tick, "events": list(events),
            "chars": [{"char_uid": uid, "eid": eid, "pos": list(pos), "hp": 9, "max_hp": 9,
                       "stamina": 9, "inventory": [], "equipment": {},
                       "carry": {"used": 19, "cap": 21}}],
            "visible": {"tiles": [], "entities": [], "items": [], "gold": []}}


OB = {"kind": "overburdened", "eid": 7, "pos": [1, 1]}


def _bot():
    bot = GuildBot("explorer")

    class Spy:
        version = "spy/0"

        def act(self, *_a, **_k):
            pass

        def village(self, *_a, **_k):
            return []

    bot.strategy = Spy()
    return bot


# ---- learning the refusal ----------------------------------------------------

def test_the_overburdened_event_is_learned_for_our_character():
    bot = _bot()
    assert bot.recently_overburdened("u1") is False
    bot.on_frame(_frame(100, events=[OB]))
    assert bot.recently_overburdened("u1") is True


def test_another_guilds_overburdened_event_is_ignored():
    """Events name an `eid`, and eids are a different namespace from our char_uids — a
    rival straining under its own loot must not suppress OUR looting."""
    bot = _bot()
    bot.on_frame(_frame(100, events=[{"kind": "overburdened", "eid": 99999}]))
    assert bot.recently_overburdened("u1") is False


def test_the_refusal_expires():
    """A TTL, not a latch: shedding one item ends the condition, and a permanent flag
    would suppress looting for the rest of the run. The server re-asserts it on the next
    attempt if it is still true — the same reasoning as v0.42.0's STUCK_BLOCK.

    The tick offsets are DELIBERATELY hardcoded rather than derived from
    OVERBURDENED_TTL. A fixture computed from the constant under test moves with it and
    agrees with itself — mutation testing has now caught me doing this three times
    (VEIN_SEEK_RANGE, SCARCE_LONE_KEEP, and here), so: "+5 ticks still refused, +500 long
    forgotten" is the policy claim, independent of the number."""
    bot = _bot()
    bot.on_frame(_frame(100, events=[OB]))
    bot.tick = 105
    assert bot.recently_overburdened("u1") is True, "a refusal 5 ticks old still stands"
    bot.tick = 600
    assert bot.recently_overburdened("u1") is False, "one 500 ticks old is long gone"


def test_the_ttl_stays_in_the_band_that_case_assumes():
    """Pins the constant the test above straddles, so a change that invalidates its
    premise fails loudly here instead of quietly making it vacuous."""
    assert 5 < OVERBURDENED_TTL < 500


def test_a_fresh_refusal_extends_the_window():
    bot = _bot()
    bot.on_frame(_frame(100, events=[OB]))
    bot.on_frame(_frame(100 + OVERBURDENED_TTL - 1, events=[OB]))
    bot.tick = 100 + OVERBURDENED_TTL + 5
    assert bot.recently_overburdened("u1") is True


def test_an_unrelated_event_does_not_set_it():
    bot = _bot()
    bot.on_frame(_frame(100, events=[{"kind": "move_failed", "eid": 7, "to": [2, 2]}]))
    assert bot.recently_overburdened("u1") is False


# ---- what the strategy does with it ------------------------------------------

def _offers(bot, char):
    """Every offer the strategy makes for this character on a field frame.

    Uses the REAL DecisionTrace rather than a stand-in: a hand-rolled spy has to
    re-implement the interface the strategy actually calls, and mine omitted `observe`,
    which the strategy calls first. A test double that drifts from its original tests the
    double."""
    from steemer.strategy.explorer import Explorer
    from steemer.strategy.base import FieldContext
    from steemer.reasoning import DecisionTrace

    trace = DecisionTrace(tick=bot.tick, world="vale", char_uid=char["char_uid"])
    ctx = FieldContext(world="vale", known={(1, 1): "floor", (1, 2): "floor"},
                       loot={(1, 1)})
    Explorer().act(bot, char, {"world": "vale", "tick": bot.tick}, ctx, trace)
    return [(c.action or {}, c.score, c.why) for c in trace.candidates]


def _char(used=19, cap=21, inv=None):
    return {"char_uid": "u1", "eid": 7, "pos": [1, 1], "hp": 30, "max_hp": 30,
            "stamina": 40, "level": 3, "carry": {"used": used, "cap": cap},
            "inventory": inv if inv is not None else
                         [{"kind": "berries", "item_id": "b1", "uses": []}],
            "equipment": {"hand": {"kind": "club"}}, "statuses": []}


def test_a_refused_character_stops_offering_pickup():
    """The defect itself: 811 violated pickups, all re-issued into a refusal."""
    bot = _bot()
    before = _offers(bot, _char())
    assert any(a.get("action") == "pickup" for a, _, _ in before), \
        "premise: standing on loot at 19/21, it normally grabs"
    bot._overburdened["u1"] = bot.tick
    after = _offers(bot, _char())
    assert not any(a.get("action") == "pickup" for a, _, _ in after)


def test_a_refused_character_SHEDS_rather_than_merely_stopping():
    """Suppressing pickup alone would leave it walking home under the load that caused
    the refusal. It must lighten and carry on."""
    bot = _bot()
    bot._overburdened["u1"] = bot.tick
    offers = _offers(bot, _char())
    assert any(a.get("action") == "drop" for a, _, _ in offers)


def test_an_unrefused_character_at_the_same_carry_still_loots():
    """Two oracles for the same claim: the refusal changes behaviour (above) AND the
    identical carry state without a refusal does not (here). Otherwise the tests would
    pass just as well if 19/21 alone suppressed looting."""
    bot = _bot()
    offers = _offers(bot, _char())
    assert any(a.get("action") == "pickup" for a, _, _ in offers)
    assert not any(a.get("action") == "drop" for a, _, _ in offers)
