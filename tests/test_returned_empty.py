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


def test_an_ALL_BENCHED_roster_still_scouts_an_empty_world():
    """v0.106.1 — run #200's live failure: every char stamped, ETAs far out, and with
    NOBODY fielded no frames arrive, so no refresh can ever be observed — the gate had
    benched the roster AND removed its own eyes. A world with none of our chars may
    always be scouted by a stamped char: a fielded char is a sensor."""
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    # vale is EMPTY of our chars (the pad puts nobody there) -> scout release
    acts = bot.on_frame(_village([_char("r1")], {"mines": [f"v{i}" for i in range(4)],
                                                 "spare": ["g1"]}, tick=700))
    emb = _embarks(acts)
    assert emb and emb[0]["map"] == "vale", \
        f"the roster starves with the field empty: {acts}"


def test_the_scout_release_holds_OFF_while_the_world_is_watched():
    """The release is for EYES, not a bypass: a world that already holds our chars and
    has not replenished stays gated — the bench is only overridden when it would leave
    a world unobserved."""
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    # both open worlds hold our chars (vale 1, mines 4): no release, r1 waits
    acts = bot.on_frame(_village([_char("r1")], _pad(), tick=700))
    assert not _embarks(acts), f"scout release fired at a watched world: {acts}"


def test_the_scout_resend_guard_covers_the_by_world_lag():
    """chars_by_world lags an embark by a few frames (the 0.43.0 lagging-count lesson):
    a second stamped char must not chase the first scout out while the count still
    reads zero — but the guard expires, so a scout that died en route is replaced."""
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.strategy._scout_sent["vale"] = 690                  # scout released 10 ticks ago
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    pad = {"mines": [f"v{i}" for i in range(4)], "spare": ["g1"]}
    acts = bot.on_frame(_village([_char("r1")], pad, tick=700))
    assert not _embarks(acts), "double-released into the lag window"
    acts = bot.on_frame(_village([_char("r1")], pad, tick=690 + 40))
    assert _embarks(acts), "the resend guard never expires — a dead scout is never replaced"


def test_the_scout_stamp_is_set_BY_THE_EMBARK_end_to_end():
    """The wizard-recall lesson, third occurrence: a guard whose stamp is only set by
    hand in tests masks the missing stamp. Release a scout through a REAL embark, then
    replay the lag window (chars_by_world still empty, the scout still listed here):
    a second release must not fire — only the embark-time stamp can prevent it."""
    bot = _bot()
    bot.strategy._returned_empty["r1"] = 600
    bot.strategy._returned_empty["r2"] = 600
    bot.refresh_eta = {"vale": 10 ** 9, "mines": 10 ** 9}
    pad = {"mines": [f"v{i}" for i in range(4)]}
    both = [_char("r1"), _char("r2")]
    first = _embarks(bot.on_frame(_village(both, pad, tick=700)))
    assert first and first[0]["map"] == "vale", f"no scout released at all: {first}"
    # the lag window: the server still shows vale empty and both chars "here"
    second = _embarks(bot.on_frame(_village(both, pad, tick=705)))
    assert not second, f"double-released during the lag window: {second}"
