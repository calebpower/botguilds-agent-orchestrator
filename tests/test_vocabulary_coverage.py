"""Property tests over the OBSERVED input vocabularies, not hand-picked examples.

Written after diagnosing why regressions kept shipping past a green gate (2026-08-21).
Every one lived in an input the tests never enumerated:

* v0.46.0 reserved lumber unconditionally — the untested input was "lumber with NO metal".
* v0.49.0 freed an in-flight intent on any rejection — the untested input was the
  `not_in_village` reason, one of SEVENTEEN the server actually emits.

Both suites were green and fully mutation-killed at the time. That is the point: mutation
testing proves a test is SENSITIVE to code changes; it cannot prove the tests COVER the
input space. Only enumeration does that, and the enumeration has to come from somewhere
independent of the code — here, our own recorded history, frozen into
`tests/fixtures/vocabulary.json` by `python -m steemer.vocabulary`.
"""
import json
import os

import pytest

from steemer.strategy.explorer import Explorer, INTENT_RETRY_DIFFERS, INTENT_TTL
from steemer.bot import GuildBot

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "vocabulary.json")
with open(FIXTURE) as fh:
    VOC = json.load(fh)


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 30,
                "maps": [{"id": "vale"}], "shop": {}}
    return b


def _char():
    return {"char_uid": "c1", "pos": [0, 0], "hp": 30, "max_hp": 30, "stamina": 40,
            "carry": {"used": 0, "cap": 20}, "inventory": [], "stats": {"str": 4},
            "equipment": {"hand": None}}


def _vframe(char, tick, gold=500):
    return {"world": "village", "tick": tick,
            "guild": {"gold": gold, "chars_here": ["c1"], "chars_by_world": {}},
            "shop": {"stock": [{"kind": "club", "buy_price": 15, "sell_price": 3}]},
            "chars": [char]}


def test_the_fixture_is_not_empty_or_stale_shaped():
    """Guards the guard: an empty fixture would make every property test below vacuous."""
    assert len(VOC["reasons"]) >= 10, VOC["reasons"]
    assert "not_in_village" in VOC["reasons"] and "wrong_slot" in VOC["reasons"]
    assert len(VOC["tiles"]) >= 10


@pytest.mark.parametrize("reason", sorted(VOC["reasons"]))
def test_every_observed_rejection_reason_leaves_the_latch_in_a_sane_state(reason):
    """THE test that would have caught v0.49.0 on its first run.

    For every reason the server has EVER sent us, the in-flight latch must end up in one of
    exactly two states, and the choice must match the retry-differs classification — not
    whichever couple of reasons happened to occur to me while writing the feature.
    """
    bot = _bot()
    bot.on_frame(_vframe(_char(), tick=3))
    assert "c1" in bot.strategy._village_intent, "no intent was latched to begin with"
    bot.strategy.on_action_error(bot, {"action": "buy", "char_uid": "c1", "reason": reason})
    freed = "c1" not in bot.strategy._village_intent
    assert freed == (reason in INTENT_RETRY_DIFFERS), (
        f"reason {reason!r}: latch freed={freed} but retry-differs="
        f"{reason in INTENT_RETRY_DIFFERS}. A rejection may only free the latch when the "
        f"next attempt would DIFFER; otherwise we re-issue the same doomed action.")


@pytest.mark.parametrize("reason", sorted(VOC["reasons"]))
def test_no_observed_rejection_reason_crashes_the_error_handler(reason):
    """Cheap blanket property: the handler must survive every reason, including ones it
    has no opinion about."""
    bot = _bot()
    bot.on_frame(_vframe(_char(), tick=3))
    bot.on_action_error({"action": "equip", "char_uid": "c1", "reason": reason})
    bot.on_action_error({"action": "move", "char_uid": "c1", "reason": reason})


@pytest.mark.parametrize("kind", sorted(VOC["tiles"]))
def test_every_observed_tile_kind_has_a_walkability_answer(kind):
    """`nav.is_walkable` must not be undefined for any terrain the game has shown us — a
    new tile kind appearing (the game is an evolving target) must fail closed, not raise."""
    from steemer import nav
    known = {(0, 0): kind}
    assert isinstance(nav.is_walkable((0, 0), known, ()), bool)


@pytest.mark.parametrize("kind", sorted(VOC["items"]))
def test_every_observed_item_kind_gets_a_sell_decision_without_raising(kind):
    """v0.46.0's bug was a sell-policy branch that mishandled a kind. Every item kind we
    have ever seen must produce a boolean, whatever its `uses`."""
    exp = Explorer()
    uses = VOC["uses_by_kind"].get(kind, [])
    item = {"kind": kind, "item_id": f"{kind}-1", "tier": 1, "uses": uses}
    keep = Explorer._feedstock_keep_ids([item])
    assert isinstance(exp._should_sell(item, {}, set(), set(), keep), bool)


# --------------------------------------------------------------------------- #
# The other half: enumeration catches "the code ignores the rule". It cannot catch
# "the rule is WRONG", because the assertion above is derived from the very constant it
# is checking — a mutant that added `not_enough_gold` to INTENT_RETRY_DIFFERS survived it.
# So the classification is duplicated here DELIBERATELY, reasoned one reason at a time,
# and the duplication IS the check.
#
# The question for each: after this rejection, would re-issuing the IDENTICAL action do
# anything different? Only then may it free the in-flight latch.
# --------------------------------------------------------------------------- #

RETRY_DIFFERS_BY_HAND = {
    # the two where the next attempt genuinely changes
    "wrong_slot":          True,   # we learn the slot and try a DIFFERENT one
    "stat_requirement":    True,   # we mark the kind wont_fit and stop trying it
    # everything else re-issues the same doomed action
    "crafting":            False,  # busy crafting; the craft must finish first
    "no_cauldron_nearby":  False,  # position-dependent; unchanged next tick
    "no_forge_nearby":     False,  # same
    "no_such_character":   False,  # the character is gone
    "no_such_item":        False,  # the item is gone
    "not_enough_gold":     False,  # gold does not appear between two ticks
    "not_enough_stamina":  False,  # regenerates, and MOVE_STAMINA_SAFETY already gates it
    "not_in_village":      False,  # THE v0.49.0 bug: persistent until the char returns
    "not_enough_xp":       False,  # persistent
    "nothing_to_open":     False,  # there is nothing there
    "out_of_range":        False,  # position-dependent
    "party_cap":           False,  # capacity, persistent
    "roster_cap":          False,  # capacity, persistent
    "world_cap":           False,  # capacity, persistent
    "unknown_character":   False,  # the character is not known to the server
}


def test_the_hand_reasoned_classification_covers_every_observed_reason():
    """If the game emits a reason nobody has classified, this fails rather than letting it
    default silently — which is how `not_in_village` slipped through in the first place."""
    missing = set(VOC["reasons"]) - set(RETRY_DIFFERS_BY_HAND)
    assert not missing, f"unclassified rejection reasons: {sorted(missing)}"


@pytest.mark.parametrize("reason", sorted(RETRY_DIFFERS_BY_HAND))
def test_the_shipped_classification_matches_the_hand_reasoned_one(reason):
    """Catches a WRONG rule, which the enumeration above structurally cannot."""
    assert (reason in INTENT_RETRY_DIFFERS) is RETRY_DIFFERS_BY_HAND[reason], (
        f"{reason!r}: shipped says retry-differs="
        f"{reason in INTENT_RETRY_DIFFERS}, hand-reasoning says "
        f"{RETRY_DIFFERS_BY_HAND[reason]}")


# --------------------------------------------------------------------------- #
# The HARVESTER itself. The tests above read the frozen fixture, so they guard the fixture
# and say nothing about the code that produces it — a mutant gutting `harvest()` survived
# them all. If the harvester silently stops finding reasons, the next re-harvest quietly
# empties the fixture and every property test above goes vacuous while staying green.
# --------------------------------------------------------------------------- #

class _FakeConn:
    """Answers the harvester's queries with a small known world."""
    def __init__(self):
        import json as _j
        import zlib as _z
        frame = {"chars": [{"inventory": [{"kind": "lumber", "uses": ["forge"]},
                                          {"kind": "club", "uses": ["equip", "attack"]}],
                            "equipment": {"hand": {"kind": "spear"}}}],
                 "visible": {"entities": [{"faction": "monster", "kind": "wolf"}]},
                 "shop": {"stock": [{"kind": "shield_wood"}]}}
        self._frame = _z.compress(_j.dumps(frame).encode())

    def execute(self, sql, params=()):
        class _R:
            def __init__(self, rows): self._r = rows
            def fetchall(inner): return inner._r
        if "action_errors" in sql:
            return _R([("wrong_slot",), ("not_in_village",)])
        if "DISTINCT action FROM actions_sent" in sql:
            return _R([("move",), ("buy",)])
        if "DISTINCT kind FROM events" in sql:
            return _R([("death",), ("forged",)])
        if "tiles_seen" in sql:
            return _R([("tree",), ("portal",)])
        if "FROM frames" in sql:
            return _R([(self._frame,)])
        return _R([])


def test_the_harvester_extracts_each_vocabulary_from_history():
    from steemer.vocabulary import harvest
    v = harvest(_FakeConn())
    assert v["reasons"] == ["not_in_village", "wrong_slot"]
    assert v["verbs_sent"] == ["buy", "move"]
    assert "tree" in v["tiles"] and "portal" in v["tiles"]
    assert "lumber" in v["items"] and "shield_wood" in v["items"]
    assert "wolf" in v["mobs"]
    assert v["uses_by_kind"]["lumber"] == ["forge"]
    assert "club" in v["equippable"] and "spear" in v["equippable"]


def test_the_harvester_reports_verbs_we_have_NEVER_sent():
    """The frontier's headline number comes from this, so it must be the protocol list
    MINUS what we sent, not merely what we sent."""
    from steemer.vocabulary import harvest, PROTOCOL_VERBS
    v = harvest(_FakeConn())
    assert set(v["verbs_never_sent"]) == set(PROTOCOL_VERBS) - {"move", "buy"}
    assert "say" in v["verbs_never_sent"] and "forge" in v["verbs_never_sent"]
