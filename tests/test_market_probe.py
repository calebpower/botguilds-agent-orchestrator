"""v0.82.0 — the player-market probe: one listing per run, into a market nobody uses.

`guild.market_listings` has been `[]` in every frame this project has recorded — no guild
on the server, the dev's included, has ever listed an item — while the shop pays 20% of
list and the docs say "sell to players when you can". The probe posts ONE surplus lumber
at 3g (shop pays ~1) and watches whether any rival bot buys.

Every listing/sale event shape is UNOBSERVED. These tests pin the guards, not the market:
once per run, never stacking a live listing, fail closed on rejection, and the stale
probe reclaimed at the next run. What they cannot prove: that anyone buys.
"""
from steemer.bot import GuildBot


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    return b


def _frame(tick, lumber=2, listings=(), gold=50):
    inv = [{"kind": "lumber", "item_id": f"L{i}", "uses": []} for i in range(lumber)]
    return {"world": "village", "tick": tick, "events": [],
            "guild": {"guild_id": "g_us", "gold": gold, "chars_here": ["c1"],
                      "chars_by_world": {}, "market_listings": list(listings)},
            "chars": [{"char_uid": "c1", "eid": 7, "hp": 30, "max_hp": 30,
                       "inventory": inv, "stats": {"vit": 8, "end": 8, "str": 8},
                       "equipment": {"hand": {"kind": "club"}, "offhand": None,
                                     "outfit": None, "trinket": None, "boots": None},
                       "gifts": [], "xp": 0}]}


def _acts_of(acts, kind):
    return [a for a in acts if a.get("action") == kind]


def test_a_surplus_lumber_is_LISTED_before_the_shop_gets_it():
    acts = _bot().on_frame(_frame(3))
    lists = _acts_of(acts, "list")
    assert lists and lists[0]["price"] == 3 and lists[0]["item_id"].startswith("L"), \
        f"no probe listing: {acts}"


def test_ONE_probe_per_run_then_the_shop_sells_as_before():
    bot = _bot()
    assert _acts_of(bot.on_frame(_frame(3)), "list")
    acts = bot.on_frame(_frame(30))
    assert not _acts_of(acts, "list"), f"stacked a second probe: {acts}"
    assert _acts_of(acts, "sell"), f"the shop fallback stopped selling: {acts}"


def test_a_LIVE_listing_of_ours_blocks_a_second():
    """Belt and braces with the once-per-run flag: even a fresh process (flag reset) must
    not stack listings when the frame already shows ours."""
    bot = _bot()
    mine = {"guild_id": "g_us", "listing_id": 77, "item": "lumber", "price": 3}
    bot.strategy._market_reclaimed = True          # isolate the stacking guard
    acts = bot.on_frame(_frame(3, listings=[mine]))
    assert not _acts_of(acts, "list"), f"stacked on a live listing: {acts}"


def test_a_STALE_probe_is_reclaimed_at_the_next_run():
    """A listing of ours present BEFORE we list anything this run survived a prior run
    unsold — nobody buys at that price. It is unlisted, and the fresh probe follows on a
    later tick once the listing is gone."""
    bot = _bot()
    mine = {"guild_id": "g_us", "listing_id": 77, "item": "lumber", "price": 3}
    acts = bot.on_frame(_frame(3, listings=[mine]))
    uls = _acts_of(acts, "unlist")
    assert uls and uls[0]["listing_id"] == 77, f"stale probe not reclaimed: {acts}"
    acts2 = bot.on_frame(_frame(30, listings=[]))
    assert _acts_of(acts2, "list"), f"no fresh probe after the reclaim: {acts2}"


def test_a_RIVALS_listing_is_left_alone():
    bot = _bot()
    theirs = {"guild_id": "g_them", "listing_id": 5, "item": "bow", "price": 40}
    acts = bot.on_frame(_frame(3, listings=[theirs]))
    assert not _acts_of(acts, "unlist"), f"touched a rival's listing: {acts}"


def test_even_a_REFUSED_list_is_not_retried():
    """The probe flag is set when the OFFER fires, not when it succeeds — so a refusal
    needs no handler (one was written and deleted as unobservable dead code), and a
    rejected probe still never retries within the run."""
    bot = _bot()
    assert _acts_of(bot.on_frame(_frame(3)), "list")
    bot.on_action_error({"action": "list", "char_uid": "c1", "reason": "whatever"})
    acts = bot.on_frame(_frame(30))
    assert not _acts_of(acts, "list"), f"retried a refused list: {acts}"
