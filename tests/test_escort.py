"""v0.85.0 — the escort pact (operator directive): guardians protect wizards; wizards
without guardians fall back to the village and only venture out with one.

Three gates: the EMBARK gate (a wizard leaves the village only into a world holding one
of our guardians), the FALLBACK (a fielded wizard with no guardian within ESCORT_NEAR
walks home), and the ESCORT (a guardian closes on a drifting wizard, above income and
below survival). Accepted cost, stated when the operator chose this: no fielded guardian
anywhere means wizards wait and the INT grind pauses.
"""
from steemer.bot import GuildBot


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    return b


def _char(uid, gifts, pos=(3, 3), level=5, hp=30):
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos), "hp": hp,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": level,
            "stats": {"int": 1}, "gifts": list(gifts), "statuses": [], "spells": [],
            "spell_cap": 1, "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}}}


def _field(chars, w=24, h=24):
    tiles = [[x, y, "floor", 0, 0] for x in range(w) for y in range(h)]
    return {"type": "frame", "world": "vale", "tick": 500, "events": [],
            "bounds": [w, 200], "chars": chars,
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def _village(here_chars, by_world_uids):
    return {"world": "village", "tick": 500, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50,
                      "chars_here": [c["char_uid"] for c in here_chars],
                      "chars_by_world": by_world_uids, "market_listings": []},
            "shop": {"stock": []}, "chars": here_chars}


def _act_for(acts, uid):
    return [a for a in acts if a.get("char_uid") == uid or uid in (a.get("char_uids") or [])]


# ---- the embark gate ----------------------------------------------------------

def test_a_wizard_stays_home_when_no_guardian_is_fielded():
    bot = _bot()
    # 8 padding, not 9: at 9 the field is at world_cap and NO embark can fire, which
    # made this test pass with the escort gate deleted (a vacuous oracle, caught by its
    # own mutant). At 8 an embark is possible and only the gate holds the wizard back.
    acts = bot.on_frame(_village([_char("wiz", ["int"])],
                                 {"vale": ["someone_unknown"],
                                  "mines": [f"v{i}" for i in range(8)]}))
    assert not any(a.get("action") == "embark" for a in acts), \
        f"wizard embarked with no known guardian fielded: {acts}"


def test_a_wizard_embarks_INTO_the_guardian_world():
    """The strategy learns roles by sighting: a field frame shows the guardian in vale,
    then the village fields the wizard — to vale, not to the empty mines."""
    bot = _bot()
    bot.on_frame(_field([_char("guard", ["vit"], level=5)]))          # sighting: guardian in vale
    # mines padded to keep the roster at cap (else the recruit branch preempts embarks)
    acts = bot.on_frame(_village([_char("wiz", ["int"])],
                                 {"vale": ["guard"], "mines": [f"v{i}" for i in range(8)]}))
    emb = [a for a in acts if a.get("action") == "embark"]
    assert emb and emb[0]["map"] == "vale" and emb[0]["char_uids"] == ["wiz"], \
        f"wizard did not follow the guardian: {acts}"


def test_the_held_wizard_never_blocks_the_rest_of_the_queue():
    """A wizard with no escort and a forager behind it: the forager embarks."""
    bot = _bot()
    acts = bot.on_frame(_village([_char("wiz", ["int"]), _char("forg", ["str"], level=1)],
                                 {"mines": [f"v{i}" for i in range(9)]}))
    emb = [a for a in acts if a.get("action") == "embark"]
    assert emb and emb[0]["char_uids"] == ["forg"], \
        f"the waiting wizard blocked the embark queue: {acts}"


# ---- the field fallback -------------------------------------------------------

def test_a_fielded_wizard_with_no_guardian_walks_home():
    bot = _bot()
    acts = bot.on_frame(_field([_char("wiz", ["int"], pos=(3, 9))]))
    mine = _act_for(acts, "wiz")
    assert mine and mine[0]["action"] == "move" and mine[0]["dir"] == "S", \
        f"unescorted wizard did not fall back: {mine}"


def test_a_wizard_WITH_its_guardian_stays_and_works():
    bot = _bot()
    acts = bot.on_frame(_field([_char("wiz", ["int"], pos=(3, 9)),
                                _char("guard", ["vit"], pos=(4, 9), level=5)]))
    mine = _act_for(acts, "wiz")
    assert not (mine and mine[0].get("dir") == "S"), \
        f"escorted wizard still ran home: {mine}"


# ---- the escort ---------------------------------------------------------------

def test_a_guardian_closes_on_a_drifting_wizard():
    bot = _bot()
    acts = bot.on_frame(_field([_char("guard", ["vit"], pos=(3, 3), level=5),
                                _char("wiz", ["int"], pos=(11, 3))]))
    mine = _act_for(acts, "guard")
    assert mine and mine[0]["action"] == "move" and mine[0]["dir"] == "E", \
        f"guardian did not close on the wizard: {mine}"


def test_a_guardian_beside_its_wizard_does_not_orbit():
    bot = _bot()
    acts = bot.on_frame(_field([_char("guard", ["vit"], pos=(3, 3), level=5),
                                _char("wiz", ["int"], pos=(4, 3))]))
    mine = _act_for(acts, "guard")
    assert not any("escorting" in str(a) for a in mine), f"orbiting at gap 1: {mine}"


def test_escort_duty_BEATS_one_more_coin():
    """Loot beside the guardian, wizard drifting: the escort (4.2) must outrank gathering
    (4.0). The starvation lesson of this whole arc — score a duty under an offer that
    always exists and the duty never happens — asserted here with the competing offer
    actually present, because without loot in the frame the score mutant survived."""
    bot = _bot()
    f = _field([_char("guard", ["vit"], pos=(3, 3), level=5),
                _char("wiz", ["int"], pos=(11, 3))])
    f["visible"]["items"] = [{"pos": [2, 3], "kind": "meat"}]
    acts = bot.on_frame(f)
    mine = _act_for(acts, "guard")
    assert mine and mine[0]["action"] == "move" and mine[0]["dir"] == "E", \
        f"the guardian chose a coin over its wizard: {mine}"


def test_a_guardian_does_NOT_cross_the_map_to_escort():
    """First live trace of 0.85.0: 'escorting the wizard (130 away)'. An unbounded escort
    is a cross-map errand — the exact stint-sizing trap of the cohesion and vein arcs —
    and re-pairing at distance belongs to the village (fallback + embark gate), not to a
    guardian's legs.

    Asserted on the DECISION TRACE, not the action: the first draft checked the action
    dict for the word 'escorting', which actions never carry, so it passed under the
    unbounded mutant while the guardian marched east — an oracle that could not fail.
    """
    from steemer.reasoning import DecisionTrace
    from steemer.strategy.base import FieldContext
    bot = _bot()
    guard = _char("guard", ["vit"], pos=(1, 3), level=5)
    wiz = _char("wiz", ["int"], pos=(60, 3))
    known = {(x, y): "floor" for x in range(64) for y in range(24)}
    ctx = FieldContext(world="vale", known=known, bounds=(64, 200))
    tr = DecisionTrace(tick=500, world="vale", char_uid="guard")
    bot.strategy.act(bot, guard, {"world": "vale", "tick": 500,
                                  "chars": [guard, wiz]}, ctx, tr)
    escort = [c.why for c in tr.candidates if "escorting" in c.why]
    assert not escort, f"guardian set off on a 59-tile escort: {escort}"
