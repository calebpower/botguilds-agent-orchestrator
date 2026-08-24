"""v0.106.0 — the CAUSAL re-embark condition for looted-out returners.

v0.105.0 benched a looted-out returner for a fixed 150 ticks; #199 measured that
merely PACING the commute (419 embarks/2797 ticks — chars rotated mines->vale->spire
through worlds that were all still empty for them). The nap is gone. The condition is
now the actual cause ending: a stamped char re-embarks only into a world that has
REPLENISHED since its stamp — an observed band refresh (bot.refreshed_at), or the
clock passing the last-known refresh ETA (bot.refresh_eta, the fallback for worlds we
lost eyes on) — or the moment the char holds a heal, which explodes its reachable set
and moots the stamp. A char never stamped (e.g. a full-carry sell-homer) embarks
freely. The stamp itself is proven end-to-end in test_decision_engine.py.
"""
from steemer.bot import GuildBot


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 6,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    return b


def _char(uid, pos=(3, 3), level=3, hp=30, inventory=None):
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos), "hp": hp,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": level,
            "stats": {}, "gifts": ["vit"], "statuses": [], "spells": [], "spell_cap": 1,
            "carry": {"used": 0, "cap": 20}, "inventory": list(inventory or []),
            "equipment": {"hand": {"kind": "club"}}}


def _village(here_chars, by_world_uids, tick=500):
    return {"world": "village", "tick": tick, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50,
                      "chars_here": [c["char_uid"] for c in here_chars],
                      "chars_by_world": by_world_uids, "market_listings": []},
            "shop": {"stock": []}, "chars": here_chars}


def _pad():
    # 5 fielded + the returner = 6 = roster_cap (no recruit preempt); BOTH worlds stay
    # under party_cap (vale 1, mines 4), so routing assertions have a real choice.
    return {"vale": ["g1"], "mines": [f"v{i}" for i in range(4)]}


def _embarks(acts):
    return [a for a in acts if a.get("action") == "embark"]


def test_a_looted_out_returner_WAITS_while_nothing_has_replenished():
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}   # refreshes far in the future
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=700))
    assert not _embarks(acts), f"re-fielded into worlds it just proved empty: {acts}"


def test_the_returner_goes_back_INTO_the_world_that_refreshed():
    # MINES refreshed after the stamp, vale did not. Mines is deliberately the world
    # plain routing would AVOID (4 fielded vs vale's 1), so a skip-only mutant that
    # lets the char through but routes by (threat, headcount) picks vale and is
    # caught — the assertion demands the replenishment filter reach the TARGET.
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.refreshed_at = {"mines": 650}
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=700))
    emb = _embarks(acts)
    assert emb and "r1" in (emb[0].get("char_uids") or []), f"never re-embarked: {acts}"
    assert emb[0]["map"] == "mines", f"routed into an unreplenished world: {emb[0]}"


def test_the_ETA_fallback_frees_the_returner_when_we_lost_eyes_on_the_world():
    # no observed refresh anywhere (nobody in the field to see one), but the clock has
    # passed vale's last-known ETA: the refresh is due, so the char may go check.
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.refresh_eta = {"vale": 650, "mines": 10 ** 9}
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=700))
    emb = _embarks(acts)
    assert emb and emb[0]["map"] == "vale", \
        f"ETA fallback dead — the returner is benched forever: {acts}"


def test_a_HEALED_returner_embarks_at_once_the_stamp_is_moot():
    # a potion lifts the depth cap: the world it proved empty at y<12 is not the world
    # it can reach now. The stamp must clear and the char ship out immediately.
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    ch = _char("r1", inventory=[{"kind": "potion_red", "item_id": "p1"}])
    acts = bot.on_frame(_village([ch], _pad(), tick=700))
    emb = _embarks(acts)
    assert emb and "r1" in (emb[0].get("char_uids") or []), \
        f"a healed returner stayed benched: {acts}"
    assert "r1" not in bot.strategy._returned_empty, "the moot stamp was not cleared"


def test_an_unstamped_char_embarks_freely():
    bot = _bot()
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=600))
    emb = _embarks(acts)
    assert emb and "r1" in (emb[0].get("char_uids") or []), \
        f"an unstamped char was withheld from the field: {acts}"


def test_the_replenishment_clocks_are_stamped_END_TO_END_by_field_frames():
    # The wizard-recall lesson: a gate whose stamp is only ever set by hand in tests
    # masks the missing stamp. Drive real field frames: the countdown falling is no
    # refresh; the countdown JUMPING UP is one (the bot's own two-tell rule), and
    # every frame re-arms the ETA as tick + in_ticks.
    bot = _bot()
    tiles = [[x, y, "floor"] for x in range(4) for y in range(4)]
    def frame(tick, in_ticks):
        return {"type": "frame", "world": "vale", "tick": tick, "events": [],
                "bounds": [4, 200], "chars": [_char("r1", pos=(1, 1))],
                "next_refresh": {"band": 1, "in_ticks": in_ticks},
                "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}
    bot.on_frame(frame(500, 40))
    bot.on_frame(frame(501, 39))                  # countdown falling: not a refresh
    assert "vale" not in bot.refreshed_at
    assert bot.refresh_eta.get("vale") == 501 + 39
    bot.on_frame(frame(502, 200))                 # countdown JUMPED: a refresh
    assert bot.refreshed_at.get("vale") == 502, \
        f"refresh not stamped: {bot.refreshed_at}"
    assert bot.refresh_eta.get("vale") == 502 + 200
