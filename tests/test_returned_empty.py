"""v0.105.0 — the revolving door: a char that came home LOOTED-OUT waits out a band
refresh before re-embarking.

Run #197: 1051 embarks in ~4300 ticks, chars doing vale->village->vale in 1-4 ticks.
The field half correctly concluded "world looted-out — home to re-embark" (an un-healed
char is depth-capped and the shallow strip was farmed), but the village re-fielded it
the tick it arrived ("safest: threat 0.0"), so it commuted forever. The cooldown keys
on WHY the char came home: the looted-out retreat stamps `_returned_empty`, and only
that stamp gates re-embark — a full-carry sell-homer is never stamped and re-embarks
freely (asserted below). Mirrors the 0.102.0 wizard-recall guard, and the stamp itself
is proven end-to-end in test_decision_engine.py.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import RETURNED_EMPTY_COOLDOWN

COOLDOWN = 150   # literal, pinned below


def test_pinned_literal():
    assert RETURNED_EMPTY_COOLDOWN == COOLDOWN


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    return b


def _char(uid, pos=(3, 3), level=3, hp=30):
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos), "hp": hp,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": level,
            "stats": {}, "gifts": ["vit"], "statuses": [], "spells": [], "spell_cap": 1,
            "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}}}


def _village(here_chars, by_world_uids, tick=500):
    return {"world": "village", "tick": tick, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50,
                      "chars_here": [c["char_uid"] for c in here_chars],
                      "chars_by_world": by_world_uids, "market_listings": []},
            "shop": {"stock": []}, "chars": here_chars}


def _pad():
    # 9 fielded + the returner in the village = 10 = roster_cap, so the recruit branch
    # (which returns before embarks) never preempts; 9 < world_cap 10 so an embark fits.
    return {"vale": ["g1"], "mines": [f"v{i}" for i in range(8)]}


def _embarks(acts):
    return [a for a in acts if a.get("action") == "embark"]


def test_a_looted_out_returner_WAITS_instead_of_re_embarking():
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600            # walked home looted-out
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=600 + COOLDOWN - 1))
    assert not _embarks(acts), f"a looted-out returner was re-fielded at once: {acts}"


def test_the_returner_re_embarks_after_the_cooldown_expires():
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=600 + COOLDOWN + 1))
    emb = _embarks(acts)
    assert emb and "r1" in (emb[0].get("char_uids") or []), \
        f"never re-embarked after the refresh window: {acts}"


def test_an_unstamped_char_embarks_freely():
    # The other side of "keys on WHY it came home": a char with no looted-out stamp
    # (e.g. a full-carry sell-homer) is fielded immediately — the cooldown must not
    # become a blanket embark throttle.
    bot = _bot()
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=600))
    emb = _embarks(acts)
    assert emb and "r1" in (emb[0].get("char_uids") or []), \
        f"an unstamped char was withheld from the field: {acts}"
