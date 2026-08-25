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


# --- v0.97.0: HINTS from the feed-watcher (map-wide, no local vision) -----------------

def _winning_why(bot, frame):
    """The reasoning string of the highest-scored offer — the action the bot will take.
    Lets a test assert WHICH behaviour won, not just a coincidental direction."""
    import steemer.reasoning as R
    seen = []
    orig = R.DecisionTrace.consider
    def spy(self, action, score, why):
        seen.append((score, why))
        return orig(self, action, score, why)
    R.DecisionTrace.consider = spy
    try:
        bot.on_frame(frame)
    finally:
        R.DecisionTrace.consider = orig
    return max(seen, key=lambda t: t[0])[1] if seen else ""


def _hint_bot(vale_hints):
    """A bot whose rival_hints already carry Will's vale positions (as the sidecar would
    supply), with NO Will chars in local frame vision."""
    b = _bot()
    b.rival_hints = {"vale": vale_hints}
    return b


def _will_hints(positions):
    return [{"guild_id": WILL, "pos": list(p), "name": "Barbarian"} for p in positions]


def test_hints_alone_designate_a_nuisance_with_NO_local_vision():
    """The exact failure the operator hit: Will is in the vale (the sidecar sees him) but
    our chars can't see him locally. Hints must be enough to designate."""
    bot = _hint_bot(_will_hints([(60, 40), (61, 40), (60, 41)]))
    bot.tick = 600
    # frame has our char but ZERO Will entities in visible
    _acts(bot, _frame(600, char_pos=(10, 10), will=()))
    assert bot.strategy._nuisance["uid"] == "c1", "hints did not designate a nuisance"


def test_TWO_hint_chars_do_NOT_trigger():
    bot = _hint_bot(_will_hints([(60, 40), (61, 40)]))
    bot.tick = 600
    _acts(bot, _frame(600, char_pos=(10, 10), will=()))
    assert bot.strategy._nuisance["uid"] is None


def test_the_nuisance_routes_toward_the_HINT_centroid_when_will_is_unseen():
    """Designated but Will unseen locally: the nuisance crosses the vale toward his hint
    positions. Will's hints are toward LOW y (home side) while the scout/frontier pull is
    toward HIGH y (unexplored) — so a move that closes on the low-y hint centroid can only
    be the nuisance follow, not a coincidental scout step (which would go the other way)."""
    bot = _hint_bot(_will_hints([(30, 5), (31, 5), (30, 6)]))   # centroid ~ (30,5)
    bot.tick = 600
    # a HEALTHY, shallow char (no home/heal pull); the WINNING action must be the nuisance
    # follow — a direction assert alone can be satisfied by a coincidental scout step.
    why = _winning_why(bot, _frame(600, char_pos=(10, 5), will=()))
    assert "nuisance" in why and "shadowing" in why, f"nuisance follow did not win: {why!r}"


def test_local_vision_OVERRIDES_hints_when_will_is_actually_in_sight():
    """Once our char can see Will, exact local positions win over the coarser hints. Local
    Will is toward LOW y; the hints point HIGH y (where the scout pull also is). A move
    that closes on the low-y LOCAL centroid proves local won — a scout step or a hint
    follow would both go high y."""
    bot = _hint_bot(_will_hints([(10, 22), (11, 22), (10, 21)]))   # hints HIGH y
    bot.tick = 600
    acts = _acts(bot, _frame(600, char_pos=(10, 12), will=_party((10, 2))))  # local LOW y
    assert _closer(acts, (10, 12), (10, 3)), f"ignored local vision for hints: {acts}"


def test_the_tour_PAUSES_off_stage_the_mines_are_not_the_vale():
    """v0.110.2 — run #213: the vale-designated nuisance followed WillMorr's party
    into the MINES (local visibility carried the offers cross-world) and flickered
    follow-vs-poison-retreat at y=28, un-healed. The operator's spec is vale-only;
    off the stage, the ordinary ladder governs — here the depth-cap retreat, which
    must be the winning move with Will's party visibly adjacent."""
    bot = _bot()
    bot.config["maps"] = [{"id": "vale"}, {"id": "mines"}]
    # designate in the vale (Will's trio present)
    bot.on_frame(_frame(600, will=_party((12, 10))))
    assert bot.strategy._nuisance["uid"] == "c1"
    # same char now deep in the MINES with Will's party right there
    f = _frame(610, char_pos=(10, 15), will=_party((12, 15)))
    f["world"] = "mines"
    acts = bot.on_frame(f)
    moves = [a for a in acts if a.get("char_uid") == "c1" and a.get("action") == "move"]
    assert moves and moves[0]["dir"] == "S", \
        f"the tour did not pause off-stage (expected the depth retreat): {acts}"


def test_on_station_the_depth_retreat_yields_no_hang_boundary_dance():
    """v0.111.3 — run #218, c19657: within hang radius the follow goes quiet and the
    un-healed depth retreat pulled one step home, exiting the radius, re-triggering
    the follow — a y22/23 dance ON the proper stage. Holding station is a deliberate
    choice: within the radius, deep, un-healed, the char RESTS (no S move); one step
    outside, the follow (not the retreat) is the winning pull (N, back to station)."""
    bot = _bot()
    bot.on_frame(_frame(600, char_pos=(10, 14), will=_party((10, 15))))  # designate deep
    assert bot.strategy._nuisance["uid"] == "c1"
    # ON station (centroid ~(11,16), char at (10,14): d=3... use adjacent) — re-frame:
    f = _frame(610, char_pos=(10, 15), will=_party((10, 15)))
    acts = bot.on_frame(f)
    mine = [a for a in acts if a.get("char_uid") == "c1" and a.get("action") == "move"]
    assert all(a.get("dir") != "S" for a in mine), \
        f"the depth retreat broke station: {mine}"
