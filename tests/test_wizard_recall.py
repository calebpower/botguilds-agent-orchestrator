"""v0.102.0 — wizard recall hysteresis: a wizard pulled from a dangerous band WAITS out
the band at home instead of re-embarking straight back into it.

#194: the arch-wizard oscillated home 222x. Cause is observation staleness — a wizard
only knows a world is dangerous WHILE in it; back home that knowledge expires (THREAT_TTL),
so the embark check reads the world "safe" and re-dispatches it into the danger it fled.
A re-embark cooldown after a band-danger fallback breaks the loop.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import WIZARD_RECALL_COOLDOWN

COOLDOWN = 200   # literal, pinned below


def test_pinned_literal():
    assert WIZARD_RECALL_COOLDOWN == COOLDOWN


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    from support import seat_bench
    return seat_bench(b)


def _char(uid, gifts, pos=(3, 3), level=5, hp=30):
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos), "hp": hp,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": level,
            "stats": {"int": 5 if "int" in gifts else 1}, "gifts": list(gifts),
            "statuses": [], "spells": [], "spell_cap": 1, "carry": {"used": 0, "cap": 20},
            "inventory": [], "equipment": {"hand": {"kind": "club"}}}


def _field(chars, world="vale", w=24, h=24):
    tiles = [[x, y, "floor", 0, 0] for x in range(w) for y in range(h)]
    return {"type": "frame", "world": world, "tick": 500, "events": [],
            "bounds": [w, 200], "chars": chars,
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def _village(here_chars, by_world_uids, tick=500):
    return {"world": "village", "tick": tick, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50,
                      "chars_here": [c["char_uid"] for c in here_chars],
                      "chars_by_world": by_world_uids, "market_listings": []},
            "shop": {"stock": []}, "chars": here_chars}


def _embarks(acts):
    return [a for a in acts if a.get("action") == "embark"]


def _pad():
    # 9 fielded (g1 in vale + 8 in mines) + the wizard in the village = 10 = roster_cap,
    # so the recruit branch (which returns before embarks) never preempts; and 9 < the
    # world_cap of 10, so an embark is still possible.
    return {"vale": ["g1"], "mines": [f"v{i}" for i in range(8)]}


def test_a_recalled_wizard_WAITS_instead_of_re_embarking():
    bot = _bot()
    bot.on_frame(_field([_char("g1", ["vit"], level=5)]))   # guardian sighting in vale
    bot.strategy._wizard_recall["wiz"] = 600                # a fresh band-danger recall
    # the village frame's tick is the clock (on_frame sets bot.tick from it); still within
    # the cooldown, so the wizard must WAIT despite an escort being available.
    acts = bot.on_frame(_village([_char("wiz", ["int"])], _pad(), tick=600 + COOLDOWN - 1))
    assert not _embarks(acts), f"a just-recalled wizard re-embarked into the band: {acts}"


def test_the_wizard_re_embarks_after_the_cooldown_expires():
    bot = _bot()
    bot.on_frame(_field([_char("g1", ["vit"], level=5)]))
    bot.strategy._wizard_recall["wiz"] = 600
    # past the cooldown (band cycled): the wizard re-embarks
    acts = bot.on_frame(_village([_char("wiz", ["int"])], _pad(), tick=600 + COOLDOWN + 1))
    emb = _embarks(acts)
    assert emb and "wiz" in (emb[0].get("char_uids") or []), \
        f"wizard never re-embarked after the cooldown: {acts}"


def test_a_wizard_with_no_recall_embarks_normally():
    """Control: no recall stamped -> the cooldown never fires, the wizard embarks."""
    bot = _bot()
    bot.on_frame(_field([_char("g1", ["vit"], level=5)]))
    acts = bot.on_frame(_village([_char("wiz", ["int"])], _pad()))
    emb = _embarks(acts)
    assert emb and "wiz" in (emb[0].get("char_uids") or []), \
        f"a never-recalled wizard failed to embark: {acts}"


def test_the_field_fallback_STAMPS_the_recall_end_to_end():
    """Drive the real path, not a hand-set stamp: a wizard in a band-dangerous world falls
    back home AND records the recall — so the next village frame holds it out. This is
    what a 'recall never stamped' regression breaks."""
    bot = _bot()
    # a wizard fielded in vale, with vale flagged dangerous (as a hot band would)
    bot.strategy._world_danger["vale"] = (0.0, 3.0, 500)   # dense melee preds, fresh
    wiz = _char("wiz", ["int"])
    bot.on_frame(_field([wiz], world="vale"))
    assert "wiz" in bot.strategy._wizard_recall, "the band-danger fallback did not stamp the recall"
    # and the recall then holds it home this same window
    stamp = bot.strategy._wizard_recall["wiz"]
    bot.on_frame(_field([_char("g1", ["vit"], level=5)]))   # a guardian sighting elsewhere
    acts = bot.on_frame(_village([wiz], _pad(), tick=stamp + COOLDOWN - 1))
    assert not _embarks(acts), f"stamped but did not hold the wizard home: {acts}"
