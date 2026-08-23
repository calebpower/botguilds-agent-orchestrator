"""v0.96.0 — THE NUISANCE (operator, for fun): one volunteer shadows rival guild WillMorr
in the vale, helps kill, loots his fallen, cackles home with the spoils, and pouts when
Will hits it. Will is not currently fielded, so these synthetic frames are the only
verification the questline works — every phase and every reclassification is pinned here.

Literals duplicated from the module (the hygiene ratchet forbids sizing fixtures from the
constants under test) and pinned in test_pinned_literals."""
from steemer.bot import GuildBot
from steemer.strategy import explorer as X

WILL = "g_63837f"
TRIGGER = 3
GONE_TTL = 40


def test_pinned_literals():
    assert X.NUISANCE_GUILD == WILL
    assert X.NUISANCE_TRIGGER == TRIGGER
    assert X.NUISANCE_GONE_TTL == GONE_TTL
    assert X.NUISANCE_WORLD == "vale"
    assert X.NUISANCE_LAUGH == "mwahahahaha" and X.NUISANCE_POUT == ":("


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 600
    return b


def _will(eid, pos):
    return {"eid": eid, "kind": "char", "faction": "guild", "guild_id": WILL,
            "name": f"Barbarian_{eid}", "pos": list(pos)}


def _frame(tick, char_pos=(10, 10), will=(), events=(), extra_tiles=(), char_over=None,
           eid=7):
    tiles = [[x, y, "floor", 0, 0] for x in range(24) for y in range(24)]
    tiles += [list(t) for t in extra_tiles]
    ch = {"char_uid": "c1", "eid": eid, "pos": list(char_pos), "hp": 30, "max_hp": 30,
          "stamina": 50, "max_stamina": 56, "level": 3, "stats": {"str": 2},
          "gifts": [], "statuses": [], "spells": [], "carry": {"used": 0, "cap": 20},
          "inventory": [], "equipment": {"hand": {"kind": "club"}}}
    ch.update(char_over or {})
    return {"type": "frame", "world": "vale", "tick": tick, "events": list(events),
            "bounds": [24, 200], "chars": [ch],
            "visible": {"tiles": tiles, "entities": list(will), "items": [], "gold": []}}


def _party(around=(10, 10)):
    x, y = around
    return [_will(101, (x + 1, y)), _will(102, (x, y + 1)), _will(103, (x + 1, y + 1))]


def _acts(bot, frame):
    return bot.on_frame(frame)


def _act_of(acts, uid="c1"):
    return [a for a in acts if a.get("char_uid") == uid]


# match nav.DIRS exactly (this game: N is +y, S is -y) — an inverted copy here was
# the whole reason the movement asserts failed while the behaviour was correct
from steemer.nav import DIRS as _DIR


def _closer(acts, frm, target, uid="c1"):
    """The chosen move steps CLOSER (Manhattan) to target — robust to pathing that
    detours around Will's party, which are blockers, unlike an exact-direction assert."""
    mv = [a for a in _act_of(acts, uid) if a.get("action") == "move"]
    if not mv:
        return False
    dx, dy = _DIR[mv[0]["dir"]]
    nxt = (frm[0] + dx, frm[1] + dy)
    return (abs(nxt[0] - target[0]) + abs(nxt[1] - target[1])
            < abs(frm[0] - target[0]) + abs(frm[1] - target[1]))


# --- designation & reclassification ---------------------------------------------------

def test_a_volunteer_is_designated_when_3_of_wills_chars_share_the_vale():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, char_pos=(10, 10), will=_party((14, 10))))
    assert bot.strategy._nuisance["uid"] == "c1"


def test_TWO_of_wills_chars_do_NOT_trigger():
    bot = _bot()
    two = [_will(101, (14, 10)), _will(102, (14, 11))]
    _acts(bot, _frame(600, will=two))
    assert bot.strategy._nuisance["uid"] is None


def test_the_nuisance_stands_down_when_will_leaves_the_vale():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, will=_party((14, 10))))
    assert bot.strategy._nuisance["uid"] == "c1"
    # Will gone; TTL+1 ticks later the tour ends and the char reverts to its base role
    bot.tick = 600 + GONE_TTL + 1
    _acts(bot, _frame(bot.tick, will=()))
    assert bot.strategy._nuisance["uid"] is None


def test_will_returning_designates_a_fresh_nuisance():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, will=_party((14, 10))))
    bot.tick = 700
    _acts(bot, _frame(700, will=()))              # gone (past TTL) -> stood down
    assert bot.strategy._nuisance["uid"] is None
    bot.tick = 800
    _acts(bot, _frame(800, will=_party((14, 10))))
    assert bot.strategy._nuisance["uid"] == "c1"   # re-designated on return


# --- shadow / follow ------------------------------------------------------------------

def test_the_nuisance_moves_toward_wills_centroid():
    bot = _bot()
    bot.tick = 600
    # Will's party clustered to the EAST; the nuisance steps CLOSER to their centroid
    # (exact dir varies — it paths around Will's chars, which are blockers).
    acts = _acts(bot, _frame(600, char_pos=(10, 18), will=_party((10, 4))))
    assert _closer(acts, (10, 18), (11, 5)), f"did not head for Will's centroid: {acts}"


# --- pout -----------------------------------------------------------------------------

def test_it_says_frown_when_a_will_char_attacks_it():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, will=_party((14, 10))))   # designate + learn Will's eids
    bot.tick = 601
    hit = [{"kind": "attack", "attacker": 101, "target": 7, "dmg": 3}]  # eid 101 is Will's
    acts = _acts(bot, _frame(601, will=_party((14, 10)), events=hit))
    says = [a for a in _act_of(acts) if a.get("action") == "say"]
    assert any(a.get("text") == ":(" for a in says), f"no pout when Will hit us: {acts}"


def test_a_MONSTER_attack_does_not_trigger_the_pout():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, will=_party((14, 10))))
    bot.tick = 601
    hit = [{"kind": "attack", "attacker": 999, "target": 7, "dmg": 3}]  # 999 not Will's
    acts = _acts(bot, _frame(601, will=_party((14, 10)), events=hit))
    says = [a for a in _act_of(acts) if a.get("action") == "say"]
    assert not any(a.get("text") == ":(" for a in says), "pouted at a non-Will attacker"


# --- loot a fallen Will member --------------------------------------------------------

def _pickup(eid=7, items=(555,)):
    return {"kind": "pickup", "eid": eid, "items": list(items)}


def _death(pos, guild=WILL, dropped=(555,)):
    return {"kind": "death", "guild_id": guild, "pos": list(pos), "dropped": list(dropped)}


def test_a_will_death_drop_sends_the_nuisance_to_LOOT_it():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, char_pos=(10, 10), will=_party((10, 3))))
    bot.tick = 601
    # a Will member died at (10,20), due south with a clear lane (party is far north)
    acts = _acts(bot, _frame(601, char_pos=(10, 10), will=_party((10, 3)),
                             events=[_death((10, 20))]))
    assert bot.strategy._nuisance["phase"] == "loot"
    assert _closer(acts, (10, 10), (10, 20)), f"did not beeline to the drop: {acts}"


def test_standing_on_the_drop_picks_it_up_and_flips_to_DELIVER():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, char_pos=(10, 10), will=_party((3, 3))))
    bot.tick = 601
    acts = _acts(bot, _frame(601, char_pos=(10, 10), will=_party((3, 3)),
                             events=[_death((10, 10))]))   # died right under us
    picks = [a for a in _act_of(acts) if a.get("action") == "pickup"]
    assert picks, f"did not loot the drop underfoot: {acts}"
    assert bot.strategy._nuisance["phase"] == "loot"   # not yet — awaits the pickup event
    bot.tick = 602
    _acts(bot, _frame(602, char_pos=(10, 10), will=_party((3, 3)), events=[_pickup()]))
    assert bot.strategy._nuisance["phase"] == "deliver"   # success confirmed


# --- deliver: cackle and run home -----------------------------------------------------

def test_deliver_phase_cackles_and_beelines_home():
    bot = _bot()
    bot.tick = 600
    _acts(bot, _frame(600, char_pos=(10, 10), will=_party((3, 3))))
    bot.tick = 601
    _acts(bot, _frame(601, char_pos=(10, 10), will=_party((3, 3)),
                      events=[_death((10, 10))]))          # on the drop -> offers pickup
    bot.tick = 602
    # success (pickup event) -> flip to deliver; the cackle wins THIS first deliver tick
    acts = _acts(bot, _frame(602, char_pos=(10, 10), will=_party((3, 3)),
                             events=[_pickup()]))
    says = [a for a in _act_of(acts) if a.get("action") == "say"]
    assert any(a.get("text") == "mwahahahaha" for a in says), f"no cackle: {acts}"
    # the NEXT tick he runs home with the loot
    bot.tick = 603
    acts2 = _acts(bot, _frame(603, char_pos=(10, 10), will=_party((3, 3))))
    assert _closer(acts2, (10, 10), (10, 0)), f"did not beeline home: {acts2}"


# --- role overlay ---------------------------------------------------------------------

def test_role_of_shows_nuisance_only_with_the_overlay_uid():
    c = {"char_uid": "c1", "stats": {"str": 2, "dex": 2, "int": 1, "vit": 2, "end": 2,
                                     "agi": 2}, "level": 3, "gifts": []}
    assert X.role_of(c, set(), "c1") == "nuisance"
    assert X.role_of(c, set(), "other") == "forager"   # base role without the overlay
    assert X.role_of(c, set()) == "forager"            # strategy's my_role path unaffected


def test_a_fallen_nuisance_stands_down_immediately_so_a_relief_takes_over():
    """The nuisance tried not to die, but sometimes Will wins. Its death must stand the
    tour down AT ONCE (not wait out the TTL) so a relief is designated while Will's party
    is still here. Two of our chars in the vale; the designated one dies -> the other is
    designated next frame."""
    bot = _bot()
    bot.tick = 600
    # frame with TWO of our chars present so a relief exists
    def _two_frame(tick, dead_uid=None):
        tiles = [[x, y, "floor", 0, 0] for x in range(24) for y in range(24)]
        chars = [{"char_uid": "c1", "eid": 7, "pos": [10, 10], "hp": 30, "max_hp": 30,
                  "stamina": 50, "max_stamina": 56, "level": 3, "stats": {"str": 2},
                  "gifts": [], "statuses": [], "carry": {"used": 0, "cap": 20},
                  "inventory": [], "equipment": {"hand": {"kind": "club"}}},
                 {"char_uid": "c2", "eid": 8, "pos": [12, 12], "hp": 30, "max_hp": 30,
                  "stamina": 50, "max_stamina": 56, "level": 3, "stats": {"str": 2},
                  "gifts": [], "statuses": [], "carry": {"used": 0, "cap": 20},
                  "inventory": [], "equipment": {"hand": {"kind": "club"}}}]
        chars = [c for c in chars if c["char_uid"] != dead_uid]
        evs = ([{"kind": "death", "char_uid": dead_uid, "guild_id": "g_cd0e2a"}]
               if dead_uid else [])
        return {"type": "frame", "world": "vale", "tick": tick, "events": evs,
                "bounds": [24, 200], "chars": chars,
                "visible": {"tiles": tiles, "entities": _party((16, 10)),
                            "items": [], "gold": []}}
    bot.on_frame(_two_frame(600))
    assert bot.strategy._nuisance["uid"] == "c1"
    # c1 dies this frame; the death event stands the tour down
    bot.tick = 601
    bot.on_frame(_two_frame(601, dead_uid="c1"))
    assert bot.strategy._nuisance["uid"] != "c1", "a dead nuisance kept the badge"
    # next frame c2 (still here, Will still present) takes over — WELL within the TTL
    bot.tick = 602
    bot.on_frame(_two_frame(602))
    assert bot.strategy._nuisance["uid"] == "c2", "no relief was designated after the death"


def test_reaching_the_village_with_the_spoils_completes_the_tour():
    """The DELIVER phase ends at home: a nuisance carrying Will's spoils that appears in
    the village stands its tour down (the village economy banks/sells the loot), freeing
    a relief. Drives the village() path, not the field act()."""
    bot = _bot()
    bot.tick = 600
    # designate + reach deliver in the vale
    _acts(bot, _frame(600, char_pos=(10, 10), will=_party((3, 3))))
    bot.tick = 601
    _acts(bot, _frame(601, char_pos=(10, 10), will=_party((3, 3)),
                      events=[_death((10, 10))]))
    bot.tick = 602
    _acts(bot, _frame(602, char_pos=(10, 10), will=_party((3, 3)), events=[_pickup()]))
    assert bot.strategy._nuisance["phase"] == "deliver" and bot.strategy._nuisance["uid"] == "c1"
    # now the nuisance shows up home in the village -> tour complete
    bot.tick = 610
    village = {"world": "village", "tick": 610, "events": [],
               "guild": {"guild_id": "g_us", "gold": 50, "chars_here": ["c1"],
                         "chars_by_world": {}, "market_listings": []},
               "shop": {"stock": []},
               "chars": [{"char_uid": "c1", "eid": 7, "hp": 30, "max_hp": 30, "xp": 0,
                          "level": 3, "stats": {"str": 2}, "gifts": [], "inventory": [],
                          "carry": {"used": 0, "cap": 20}, "equipment": {}}]}
    bot.on_frame(village)
    assert bot.strategy._nuisance["uid"] is None, "tour did not complete at home"
    assert bot.strategy._nuisance["phase"] == "shadow"
