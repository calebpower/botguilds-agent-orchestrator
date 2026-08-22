"""v0.74.0 wiring: flavour text reaches the world, and costs the guild nothing.

`test_chatter.py` tests the module. This tests the two claims that only the WIRING can
answer, and that the module cannot:

  * a `say` is emitted through `GuildBot.on_frame` at all — four behaviours have shipped
    correct and unreachable because their tests started downstream of the routing;
  * turning chatter on changes NO other action the village loop would have taken.

The second is asserted from two sides, because "I looked and did not see a problem" is the
weaker half of every claim in this repo. One oracle proves the real action still comes out
on a tick that has one; the other replays a whole sequence with chatter silenced and
compares the non-`say` actions element by element.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import EMBARK_COOLDOWN, VILLAGE_ACTION_COOLDOWN
import steemer.chatter as chatter_mod


SILENT_FOR = 300        # steemer.chatter.COOLDOWN (duplicated: see test_chatter.py)
GIVE_UP_AFTER = 3       # steemer.chatter.FAIL_LIMIT


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    return b


def _village(tick, inventory=(), gold=100, events=()):
    """A village frame with the roster at cap, so nothing recruits or embarks."""
    return {"world": "village", "tick": tick, "events": list(events),
            "guild": {"gold": gold, "chars_here": ["c1"],
                      "chars_by_world": {"vale": [f"v{i}" for i in range(10)]}},
            "chars": [{"char_uid": "c1", "eid": 7, "hp": 30, "max_hp": 30,
                       "inventory": list(inventory), "stats": {"vit": 8, "end": 8, "str": 8},
                       "equipment": {"hand": {"kind": "club"}, "offhand": None,
                                     "outfit": None, "trinket": None, "boots": None},
                       "gifts": [], "xp": 0}]}


def _says(actions):
    return [a for a in actions if a.get("action") == "say"]


def test_a_say_reaches_the_world_THROUGH_THE_BOT():
    bot = _bot()
    said = []
    for tick in range(1, 4 * SILENT_FOR, 7):
        said += _says(bot.on_frame(_village(tick)))
    assert said, "chatter never produced a say through GuildBot.on_frame"
    first = said[0]
    assert first.get("char_uid") == "c1" and first.get("text")
    assert len(first["text"]) <= 40


def test_it_talks_about_an_event_THE_SERVER_actually_sent():
    """The event path runs through `_learn_from_events`, which resolves eid -> char_uid.
    Feeding chatter anywhere else would repeat 0.64.0, which parsed events on frames it
    never saw and shipped inert for two versions."""
    bot = _bot()
    said = []
    for tick in range(1, 3 * SILENT_FOR, 5):
        evs = [{"kind": "forged", "eid": 7, "item": "spear"}] if tick == 1 else []
        said += _says(bot.on_frame(_village(tick, events=evs)))
    assert any("spear" in a["text"] for a in said), \
        f"the forge we were told about never reached the world: {[a['text'] for a in said]}"


# ---- it costs nothing: two oracles -------------------------------------------

def test_a_tick_with_real_work_still_does_the_real_work():
    """Oracle one, the direct case: a sellable item is present, so the tick has a job."""
    bot = _bot()
    loot = [{"kind": "tomato", "item_id": "i1", "uses": []}]
    acts = bot.on_frame(_village(3 * SILENT_FOR, inventory=loot))
    assert acts == [{"char_uid": "c1", "action": "sell", "item_id": "i1"}], \
        f"flavour text displaced a sale: {acts}"


def test_chatter_changes_NOTHING_ELSE_over_a_full_sequence():
    """Oracle two, from the other side: replay the same village ticks with chatter
    silenced, and require the non-`say` actions to match exactly. The first oracle proves
    one tick keeps its action; this proves none of them lost one, including ticks whose
    behaviour depends on state built up over the run.

    THE SEQUENCE IS SHAPED BY WHAT THE ORACLE MUST BE ABLE TO CATCH. Two earlier versions
    could not fail:

      * work every 50 ticks — a 300-tick chatter cooldown almost never collided with it,
        so the mutant that charges the speaker a VILLAGE_ACTION_COOLDOWN survived;
      * work every tick — the village is then never idle, chatter never gets a free tick,
        and the comparison ran with nothing to compare.

    Alternating blocks of 7 give both: idle stretches long enough for a line, and working
    stretches immediately after, where a cooldown stamped on the speaker delays a real
    sale. The run is long enough for many such crossings rather than one lucky one.
    """
    def run(silence: bool):
        bot = _bot()
        if silence:
            for _ in range(GIVE_UP_AFTER):
                bot.chatter.note_rejected()
        real, spoken = [], []
        for tick in range(1, 20 * SILENT_FOR):
            working = (tick // 7) % 2 == 0
            inv = [{"kind": "tomato", "item_id": f"i{tick}", "uses": []}] if working else []
            evs = [{"kind": "forged", "eid": 7, "item": "spear"}] if tick % 137 == 0 else []
            acts = bot.on_frame(_village(tick, inventory=inv, events=evs))
            spoken += _says(acts)
            real.append([a for a in acts if a.get("action") != "say"])
        return real, spoken

    (with_chatter, spoken), (without, silent) = run(False), run(True)
    # SELF-TEST FIRST, and before the success indicator: the comparison below passes
    # trivially whenever chatter is broken, disabled, or starved — which is most of the
    # ways this could actually be wrong. Assert the thing was running.
    assert len(spoken) > 3, f"chatter barely spoke ({len(spoken)}); the comparison proves little"
    assert not silent, "silencing chatter did not silence it"
    assert sum(1 for a in with_chatter if a) > 50, "too few real actions to compare"
    assert with_chatter == without, "enabling flavour text changed a real action"


# ---- v0.74.1: riding along ---------------------------------------------------

def _village_two(tick, events=()):
    """Two characters home and the field BELOW cap, so the loop embarks every tick.

    This is the shape 0.74.0 could not speak in, and it is the common one: 429 of run
    #153's first 541 village ticks were taken by an embark, and flavour text placed after
    the ladder never got a turn.
    """
    def ch(uid, eid):
        return {"char_uid": uid, "eid": eid, "hp": 30, "max_hp": 30, "inventory": [],
                "stats": {"vit": 8, "end": 8, "str": 8}, "gifts": [], "xp": 0,
                "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                              "trinket": None, "boots": None}}
    return {"world": "village", "tick": tick, "events": list(events),
            "guild": {"gold": 100, "chars_here": ["c1", "c2"], "chars_by_world": {}},
            "chars": [ch("c1", 7), ch("c2", 8)]}


def test_a_say_rides_along_with_the_ticks_real_action():
    bot = _bot()
    embarked = said = None
    for tick in range(1, 3 * SILENT_FOR):
        acts = bot.on_frame(_village_two(tick))
        for a in acts:
            if a.get("action") == "embark":
                embarked = embarked or (tick, a)
            if a.get("action") == "say":
                said = said or (tick, a, acts)
    assert embarked, "the fixture never embarked, so there was nothing to ride along with"
    assert said, "flavour text never spoke on a tick that had real work — 0.74.0's defect"
    tick, say, acts = said
    others = [a for a in acts if a is not say]
    assert others, f"the say was alone on tick {tick}; it should accompany real work: {acts}"
    assert say["char_uid"] not in {a.get("char_uid") for a in others}, \
        "the speaker was also the subject of the tick's real action"


def _subjects(action):
    """Every character an action commands. An embark names them in `char_uids`; everything
    else uses `char_uid`. Reading only one spelling is how the first version of this test
    watched an embark go by without seeing whose it was."""
    out = set(action.get("char_uids") or ())
    if action.get("char_uid") is not None:
        out.add(action["char_uid"])
    return out


def test_the_speaker_is_never_the_character_being_embarked():
    """A character mid-embark is leaving, not loitering. Talking through it would put two
    actions on one character in a single tick, which is the shape of the run-#38 re-send
    storm rather than of flavour text."""
    bot = _bot()
    spoke = False
    for tick in range(1, 4 * SILENT_FOR):
        acts = bot.on_frame(_village_two(tick))
        spoke = spoke or any(a.get("action") == "say" for a in acts)
        seen = set()
        for a in acts:
            clash = seen & _subjects(a)
            assert not clash, f"two actions for {clash} on tick {tick}: {acts}"
            seen |= _subjects(a)
    assert spoke, "chatter never spoke, so this proves nothing about its speaker"


def test_the_speaker_is_not_a_character_whose_embark_is_still_IN_FLIGHT():
    """The tick after an embark, the character is still listed at home — the frame has not
    caught up — and it is no longer in this tick's action list, so the same-tick guard does
    not cover it. Only `_embark_at` does."""
    bot = _bot()
    leaving = {}
    for tick in range(1, 4 * SILENT_FOR):
        acts = bot.on_frame(_village_two(tick))
        for a in acts:
            if a.get("action") == "embark":
                for uid in _subjects(a):
                    leaving[uid] = tick
            if a.get("action") == "say":
                uid = a["char_uid"]
                since = tick - leaving.get(uid, -10 ** 9)
                assert since >= EMBARK_COOLDOWN, \
                    f"{uid} spoke {since} ticks after being sent to the field"


def test_the_speaker_is_not_a_character_mid_TRANSACTION():
    """The other half of "idle". A character that just sold something is one the village
    loop is still working with — its next tick may equip, buy, or re-sell — and the
    re-send guard exists because a stale frame made those repeat. Flavour text should not
    interleave itself with that character's errand.

    `_village_two` never sells, so this shape was invisible: both guards on the speaker
    survived mutation until this test existed.
    """
    bot = _bot()
    def frame(tick):
        f = _village_two(tick)
        f["chars"][0]["inventory"] = [{"kind": "tomato", "item_id": f"i{tick}", "uses": []}]
        return f

    sold_at, checked = {}, False
    for tick in range(1, 4 * SILENT_FOR):
        acts = bot.on_frame(frame(tick))
        for a in acts:
            if a.get("action") == "sell":
                sold_at[a["char_uid"]] = tick
            if a.get("action") == "say":
                uid = a["char_uid"]
                since = tick - sold_at.get(uid, -10 ** 9)
                assert since >= VILLAGE_ACTION_COOLDOWN, \
                    f"{uid} spoke {since} ticks after a sale, mid-errand"
                checked = True
    assert sold_at, "the fixture never sold anything"
    assert checked, "chatter never spoke, so the guard was never exercised"
