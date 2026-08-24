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
    from support import seat_bench
    return seat_bench(b)          # v0.88.0: seats need a pool; int>=3 fixtures claim one


def _char(uid, gifts, pos=(3, 3), level=5, hp=30):
    # v0.88.0: wizardhood is a SEAT (top-6 by INT over the ledger); an int-GIFTED fixture
    # char gets int 5 so it outranks the seat bench, an ungifted one stays int 1 below it.
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos), "hp": hp,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": level,
            "stats": {"int": 5 if "int" in gifts else 1}, "gifts": list(gifts),
            "statuses": [], "spells": [],
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
    # v0.105.0: the wizard carries a heal. This fixture's only work is the frontier at
    # y23 — past POISON_SAFE_DEPTH — and an UN-healed char must not feel that pull (the
    # goal filter; before it, this fixture "worked" by marching to the cap and line-
    # dancing there, which this test never looked far enough to see). The claim under
    # test is escort-vs-fallback, not the poison economy, so equip the wizard the way
    # the village heal-first step does and let it range.
    bot = _bot()
    wiz = _char("wiz", ["int"], pos=(3, 9))
    wiz["inventory"] = [{"kind": "potion_red", "item_id": "p1"}]
    acts = bot.on_frame(_field([wiz, _char("guard", ["vit"], pos=(4, 9), level=5)]))
    mine = _act_for(acts, "wiz")
    assert not (mine and mine[0].get("dir") == "S"), \
        f"escorted wizard still ran home: {mine}"


# ---- the escort ---------------------------------------------------------------

def test_a_guardian_closes_on_a_drifting_wizard():
    """Two frames: the PARTY forms on the wizard's turn (frame 1), the guardian holds
    formation on the party square from frame 2 — pairing is state, not a per-tick
    inference, which is the whole point of v0.86.0."""
    bot = _bot()
    bot.on_frame(_field([_char("guard", ["vit"], pos=(3, 3), level=5),
                         _char("wiz", ["int"], pos=(11, 3))]))
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
    bot.on_frame(f)                       # frame 1 pairs the party
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


# ---- v0.86.0: the party is the unit -------------------------------------------

def test_every_member_computes_the_SAME_rally_square():
    """The jitter diagnosis (operator, verbatim: individualized targets 'evaluating the
    position of the other members... causing a lot of jitter'). Cohesion's centroid
    excluded self, so two members of the same group rallied to two DIFFERENT squares.
    With self included, both compute the identical point."""
    from steemer.strategy.explorer import Explorer
    from steemer.strategy.base import FieldContext
    exp = Explorer()
    known = {(x, y): "floor" for x in range(8) for y in range(8)}
    ctx = FieldContext(world="mines", known=known)
    # A member standing AT the shared centroid must not move. With the two-ally geometry
    # of the first draft the first STEP quantized identically under both centroids and
    # the self-excluded mutant survived — the discriminating observable is the STOPPING
    # rule. pts {(5,0),(0,0),(5,1),(5,2)} -> centroid (3,0), distance 2 = within HOLD;
    # excluding self -> (3,1), distance 3 -> the mutant marches a settled member off.
    step = exp._cohesion_step((5, 0), [(0, 0), (5, 1), (5, 2)], ctx, blocked=set())
    assert step is None, \
        f"a member at the shared rally square moved ({step}) — centroid must include self"


def test_partied_characters_SKIP_cohesion():
    """The party IS their formation: a partied guardian in a dangerous world must not
    also rally to the group centroid — that second, different target is the jitter."""
    bot = _bot()
    from steemer.strategy.explorer import COHESION_PRED_DENSE
    bot.strategy._world_danger["vale"] = (0.0, COHESION_PRED_DENSE, 500)
    # geometry chosen so the group centroid is INSIDE cohesion's rally range (gap 4);
    # with the centroid out of range the skip-mutant had nothing to offer and survived
    frame = _field([_char("guard", ["vit"], pos=(3, 3), level=5),
                    _char("wiz", ["int"], pos=(9, 3)),
                    _char("forg", ["str"], pos=(6, 8), level=1)])
    bot.on_frame(frame)                     # pair the party
    from steemer.reasoning import DecisionTrace
    from steemer.strategy.base import FieldContext
    known = {(x, y): "floor" for x in range(24) for y in range(24)}
    ctx = FieldContext(world="vale", known=known, bounds=(24, 200))
    guard = _char("guard", ["vit"], pos=(3, 3), level=5)
    tr = DecisionTrace(tick=501, world="vale", char_uid="guard")
    bot.strategy.act(bot, guard, {"world": "vale", "tick": 501,
                                  "chars": [guard, _char("wiz", ["int"], pos=(9, 3)),
                                            _char("forg", ["str"], pos=(6, 8), level=1)]},
                     ctx, tr)
    whys = [c.why for c in tr.candidates]
    assert any("party square" in w for w in whys), f"no formation move at gap 8: {whys}"
    assert not any("rallying to the group centre" in w for w in whys), \
        f"a partied guardian also rallied to the centroid — two targets, jitter: {whys}"


def test_wizards_CLUSTER_into_one_detail_around_the_arch_wizard():
    """v0.87.0 INVERTED the morning's contract, on operator direction: "It's okay for
    wizards to cluster into a single party. In that case the wizard with the most int
    needs to be protected by the other wizards too." The second wizard no longer falls
    back — it joins the detail and holds formation on the arch-wizard's square. w1 has
    INT 3 (the arch); w2 (INT 1) shields it; both stay fielded with one guardian.

    NB the mutant that sends the ARCH through the lesser-wizard branch is EQUIVALENT
    (anchor == its own tile -> gap 0 -> no move, in_party still set), so it survives
    mutation by construction; the arch's stillness is asserted implicitly by w2's motion
    toward a stationary target."""
    bot = _bot()
    w1 = _char("w1", ["int"], pos=(4, 3))
    w1["stats"]["int"] = 6
    frame = _field([_char("guard", ["vit"], pos=(3, 3), level=5),
                    w1,
                    _char("w2", ["int"], pos=(12, 3))])
    bot.on_frame(frame)
    acts = bot.on_frame(frame)
    w2 = _act_for(acts, "w2")
    assert w2 and w2[0]["action"] == "move" and w2[0]["dir"] == "W", \
        f"the lesser wizard should close on the arch-wizard, not flee home: {w2}"


# ---- v0.87.0: the party forms at the village gate ------------------------------

def test_PAIR_EMBARK_ships_the_guardian_with_the_wizard():
    """One embark, two char_uids, guardian first: the party exists from tick one instead
    of forming by sighting-luck in the field."""
    bot = _bot()
    bot.config["roster_cap"] = 9        # roster at cap, else recruit-to-cap (0.87.0)
    acts = bot.on_frame(_village([_char("wiz", ["int"]), _char("guard", ["vit"], level=5)],
                                 {"mines": [f"v{i}" for i in range(7)]}))
    emb = [a for a in acts if a.get("action") == "embark"]
    assert emb and sorted(emb[0]["char_uids"]) == ["guard", "wiz"], \
        f"no pair-embark: {acts}"


def test_a_guardian_reinforces_the_thin_world():
    """Operator: at least two guardians per world. vale holds two sighted guardians,
    mines none — the next guardian must ship to mines despite vale being no worse."""
    bot = _bot()
    bot.config["roster_cap"] = 7        # roster at cap, else recruit-to-cap (0.87.0)
    bot.on_frame(_field([_char("g1", ["vit"], level=5), _char("g2", ["vit"], pos=(5, 5), level=5)]))
    acts = bot.on_frame(_village([_char("g3", ["vit"], level=5)],
                                 {"vale": ["g1", "g2"], "mines": [f"v{i}" for i in range(4)]}))
    emb = [a for a in acts if a.get("action") == "embark"]
    assert emb and emb[0]["map"] == "mines", \
        f"guardian did not reinforce the guardian-less world: {acts}"


# ---- v0.87.1: wizards sit out dangerous bands ----------------------------------

def test_a_wizard_does_not_embark_into_a_DANGEROUS_world_even_with_guardians():
    """#175's undead cycle killed 9 wizards near home with escorts present: an escort is
    not an answer to a hostile band. The wizard waits; guardians and fodder work it."""
    from steemer.strategy.explorer import COHESION_PRED_DENSE
    bot = _bot()
    bot.config["roster_cap"] = 9
    bot.strategy._world_danger["vale"] = (0.0, COHESION_PRED_DENSE, 500)
    bot.on_frame(_field([_char("guard", ["vit"], level=5)]))       # guardian sighted in vale
    acts = bot.on_frame(_village([_char("wiz", ["int"])],
                                 {"vale": ["guard"], "mines": [f"v{i}" for i in range(7)]}))
    emb = [a for a in acts if a.get("action") == "embark"]
    assert not any("wiz" in (a.get("char_uids") or []) for a in emb), \
        f"wizard shipped into a dangerous band: {acts}"


def test_a_fielded_wizard_LEAVES_when_the_band_turns_dangerous():
    """A refresh brings undead mid-stint: the wizard heads home even with its guardian
    right there — the pipeline waits out the cycle."""
    from steemer.strategy.explorer import COHESION_PRED_DENSE
    bot = _bot()
    frame = _field([_char("wiz", ["int"], pos=(3, 9)),
                    _char("guard", ["vit"], pos=(4, 9), level=5)])
    bot.on_frame(frame)
    bot.strategy._world_danger["vale"] = (0.0, COHESION_PRED_DENSE, 500)
    acts = bot.on_frame(frame)
    mine = _act_for(acts, "wiz")
    assert mine and mine[0]["action"] == "move" and mine[0]["dir"] == "S", \
        f"wizard stayed out in a dangerous band: {mine}"
