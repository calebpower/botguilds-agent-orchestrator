"""v0.75.0 wiring: flavour text is a FIELD action, and it only ever costs an idle rest.

0.74.x issued `say` from the village and the server refused all three attempts with
`not_in_village`. docs/03-actions.md gives the action's scope as "map" — I read that as
"map-visible" rather than as where it is legal. The scope column had the answer before the
feature was written, and the fail-closed path (three rejections and stop) is the only
reason it cost three actions rather than one every cooldown for the rest of the run.

`test_chatter.py` tests the module. This tests what only the wiring can answer:

  * a `say` comes out of `GuildBot.on_frame` at all;
  * it never beats anything except a rest, and never a rest that would RECOVER something;
  * an offer that loses does not spend the line.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import (FRONTIER_NORTH_SCORE, FRONTIER_SCORE,
                                       REST_SCORE, SAY_SCORE, SCOUT_SCORE)

SILENT_FOR = 300        # steemer.chatter.COOLDOWN (duplicated: see test_chatter.py)
GIVE_UP_AFTER = 3       # steemer.chatter.FAIL_LIMIT


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    return b


def _char(hp=30, stamina=60, max_stamina=60, pos=(1, 1)):
    return {"char_uid": "c1", "eid": 7, "pos": list(pos), "hp": hp, "max_hp": 30,
            "stamina": stamina, "max_stamina": max_stamina, "level": 3, "stats": {},
            "gifts": [], "statuses": [], "spells": [], "spell_cap": 1,
            "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}}}


def _frame(tick, char=None, items=(), events=()):
    """A small explored room, so `frontier` has nothing to chase and the ladder is quiet."""
    tiles = [[x, y, "floor", 0, 0] for x in range(4) for y in range(4)]
    return {"type": "frame", "world": "vale", "tick": tick, "events": list(events),
            "bounds": [4, 4], "chars": [char or _char()],
            "visible": {"tiles": tiles, "entities": [], "items": list(items), "gold": []}}


def _says(actions):
    return [a for a in actions if a.get("action") == "say"]


def test_a_say_reaches_the_world_THROUGH_THE_BOT():
    bot = _bot()
    said = []
    for tick in range(1, 3 * SILENT_FOR, 7):
        said += _says(bot.on_frame(_frame(tick)))
    assert said, "chatter never produced a say through GuildBot.on_frame"
    assert said[0]["char_uid"] == "c1" and len(said[0]["text"]) <= 40


def test_it_talks_about_an_event_THE_SERVER_actually_sent():
    """Events reach chatter through `_learn_from_events`, which runs for every frame and
    resolves eid -> char_uid. 0.64.0 put an event parser somewhere it never saw its own
    events and shipped inert for two versions."""
    bot = _bot()
    said = []
    for tick in range(1, 3 * SILENT_FOR, 5):
        evs = [{"kind": "forged", "eid": 7, "item": "spear"}] if tick == 1 else []
        said += _says(bot.on_frame(_frame(tick, events=evs)))
    assert any("spear" in a["text"] for a in said), \
        f"the forge we were told about never reached the world: {[a['text'] for a in said]}"


# ---- it only costs an idle rest ----------------------------------------------

def test_a_TIRED_character_recovers_instead_of_talking():
    """The claim "it only displaces an idle rest" was false in the first draft: rest is
    also the RECOVERY action, and it wins precisely when a character has something to
    recover. Three decision-engine tests caught a character chatting at low stamina.

    30/60 is chosen so the test can only pass for the RIGHT reason. At 5/60 it passed with
    the gate deleted — a `say` costs 10 stamina, so the affordability check in `offer` was
    quietly doing the work and the gate was never exercised. Here the action is affordable
    and resting still has something to give."""
    bot = _bot()
    for tick in range(1, 3 * SILENT_FOR, 7):
        acts = bot.on_frame(_frame(tick, char=_char(stamina=30, max_stamina=60)))
        assert not _says(acts), f"talked at 30/60 stamina instead of resting: {acts}"


def test_a_character_short_of_FULL_HP_does_not_stop_to_talk():
    """25/30, not 4/30. At 4 hp the character takes the retreat branch and returns long
    before the say is offered, so that fixture proved nothing about this gate — it survived
    the mutant that removes it. 25/30 is above every hurt threshold in the ladder, so the
    only thing standing between this character and a chat is the gate itself."""
    bot = _bot()
    for tick in range(1, 3 * SILENT_FOR, 7):
        acts = bot.on_frame(_frame(tick, char=_char(hp=25)))
        assert not _says(acts), f"talked at 25/30 hp instead of topping up: {acts}"


def test_a_character_with_missing_max_stamina_stays_QUIET():
    """Missing data reads as "not ready", never as "ready". The opposite default would
    make a protocol change silently spend rest ticks."""
    bot = _bot()
    char = _char()
    del char["max_stamina"]
    for tick in range(1, 2 * SILENT_FOR, 7):
        assert not _says(bot.on_frame(_frame(tick, char=char)))


def test_the_say_outbids_only_the_idle_FILLERS():
    """Not a re-export of the constants: it pins the ORDER, which is the whole safety
    argument. It must beat scout — the ladder's always-available filler, and the reason a
    say scored just above REST fired zero times — and lose to the frontier push and
    everything productive above it."""
    assert SAY_SCORE > FRONTIER_SCORE > SCOUT_SCORE > REST_SCORE
    assert SAY_SCORE < FRONTIER_NORTH_SCORE, \
        "the north push, every retreat, spacing and gathering must still win"


def test_loot_on_the_floor_beats_flavour_text():
    bot = _bot()
    for tick in range(1, 2 * SILENT_FOR, 7):
        acts = bot.on_frame(_frame(tick, items=[{"pos": [3, 3]}]))
        assert not _says(acts), f"talked while there was loot to fetch: {acts}"


def test_an_offer_that_LOSES_does_not_spend_the_line():
    """peek/commit, and the reason for it. If the offer consumed the line on the way past,
    a tick where the say lost would still burn the 300-tick cooldown — and the one event we
    had to talk about — on a broadcast that never happened.

    Loot every tick for a while (the say loses), then loot removed: the guild must still
    have something to say, and it must still be the FORGE it was told about.
    """
    bot = _bot()
    bot.on_frame(_frame(1, events=[{"kind": "forged", "eid": 7, "item": "spear"}],
                        items=[{"pos": [3, 3]}]))
    for tick in range(2, 60):
        assert not _says(bot.on_frame(_frame(tick, items=[{"pos": [3, 3]}])))
    said = []
    for tick in range(60, 120):
        said += _says(bot.on_frame(_frame(tick)))
    assert said, "the line was consumed by an offer that never went out"
    assert "spear" in said[0]["text"], \
        f"the event was spent while losing; got {said[0]['text']!r}"
