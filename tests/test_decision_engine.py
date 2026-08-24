"""The decision engine end to end: synthetic frames -> chosen actions.

These exercise GuildBot + the explorer strategy without any network, which is
the frame-replay tier — the same shape :mod:`steemer.replay` uses on recorded
history.
"""

from steemer.bot import GuildBot
from steemer.storage import Storage


def _bot(storage=None):
    b = GuildBot(strategy="explorer", storage=storage)
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    return b


def _field_char(**over):
    char = {"char_uid": "c1", "pos": [0, 0], "hp": 30, "max_hp": 30,
            "stamina": 40, "carry": {"used": 0, "cap": 20},
            "inventory": [], "stats": {}, "equipment": {}}
    char.update(over)
    return char


def _field_frame(char, tiles, entities=(), items=(), gold=()):
    return {"world": "vale", "tick": 10, "chars": [char],
            "visible": {"tiles": list(tiles), "entities": list(entities),
                        "items": list(items), "gold": list(gold)}}


FLOOR3 = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]


def test_attacks_the_adjacent_enemy():
    bot = _bot()
    frame = _field_frame(
        _field_char(),
        FLOOR3,
        entities=[{"pos": [1, 0], "faction": "monster", "kind": "rat_grey", "hp_frac": 0.5}],
    )
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [1, 0]} in actions


def test_drinks_a_potion_when_hurt():
    bot = _bot()
    char = _field_char(hp=5, inventory=[{"kind": "potion_red", "item_id": "p1"}])
    actions = bot.on_frame(_field_frame(char, FLOOR3))
    assert {"char_uid": "c1", "action": "use", "item_id": "p1"} in actions


def test_rests_when_stamina_too_low_to_act():
    bot = _bot()
    char = _field_char(stamina=5)     # below MIN_AFFORD -> rest (send nothing)
    actions = bot.on_frame(_field_frame(char, FLOOR3,
                           entities=[{"pos": [1, 0], "faction": "monster",
                                      "kind": "rat_grey", "hp_frac": 0.1}]))
    assert actions == []              # no action emitted for a resting char


def test_picks_up_loot_underfoot():
    bot = _bot()
    actions = bot.on_frame(_field_frame(_field_char(), FLOOR3,
                                        items=[{"pos": [0, 0], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "pickup"} in actions


def _vert_corridor(top):
    # a 1-wide floor corridor x=0, y=0..top; the topmost tile borders the unknown
    # so it (and every tile) is a north frontier to push toward.
    return [[0, y, "floor"] for y in range(0, top + 1)]


def test_unhealed_char_past_safe_depth_heads_home_not_deeper():
    # v0.23.0: an un-healed char (no potion) deep in the field stops pushing north
    # and heads HOME instead — poison kills chars on long retreats from deep ground.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    tiles = _vert_corridor(POISON_SAFE_DEPTH + 4)
    char = _field_char(pos=[0, POISON_SAFE_DEPTH + 2], stamina=40, inventory=[])
    acts = bot.on_frame(_field_frame(char, tiles))
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts        # heading home
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts)


def test_healed_char_may_range_deep():
    # a char carrying a potion can still push north from deep ground (it can drink
    # the poison off en route home).
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    tiles = _vert_corridor(POISON_SAFE_DEPTH + 4)
    char = _field_char(pos=[0, POISON_SAFE_DEPTH + 2], stamina=40,
                       inventory=[{"kind": "potion_red", "item_id": "p1"}])
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in bot.on_frame(
        _field_frame(char, tiles))


def test_unhealed_char_still_explores_when_shallow():
    # shallow enough that a poison-retreat is survivable -> still explores north.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    tiles = _vert_corridor(POISON_SAFE_DEPTH + 4)
    char = _field_char(pos=[0, max(1, POISON_SAFE_DEPTH - 4)], stamina=40, inventory=[])
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in bot.on_frame(
        _field_frame(char, tiles))


def test_unhealed_char_at_the_cap_wont_chase_loot_deeper_the_line_dance():
    # v0.103.0 THE LINE DANCE (run #195, c19457 at y12/13): an un-healed char AT the
    # depth cap is pulled NORTH (deeper) by loot one tile past the cap at 4.0, which
    # out-scored the safe-depth home-retreat (2.5). It stepped past the cap, the
    # retreat turned it back, and the two alternated forever at the boundary. Gating
    # the gather step on the same POISON_SAFE_DEPTH the retreat uses kills the deeper
    # pull: the char commits to home instead of oscillating.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    tiles = _vert_corridor(POISON_SAFE_DEPTH + 4)
    char = _field_char(pos=[0, POISON_SAFE_DEPTH], stamina=40, inventory=[])
    acts = bot.on_frame(_field_frame(
        char, tiles, items=[{"pos": [0, POISON_SAFE_DEPTH + 1], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts        # heads home
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts)


def test_unhealed_char_ONE_BELOW_the_cap_wont_step_onto_it_for_loot():
    # v0.104.0 — the off-by-one 0.103.0 missed (run #196, c19457/c19468 still dancing):
    # the guard's `<=` allowed a gather step ONTO exactly y == POISON_SAFE_DEPTH, the
    # very tile the retreat fires from (`>=`), so the dance survived one tile shallower:
    # pulled y11 -> y12 for loot, retreated y12 -> y11, forever. The guard must be
    # STRICT: no outward step may land on ground the retreat immediately vacates.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    tiles = _vert_corridor(POISON_SAFE_DEPTH + 4)
    char = _field_char(pos=[0, POISON_SAFE_DEPTH - 1], stamina=40, inventory=[])
    acts = bot.on_frame(_field_frame(
        char, tiles, items=[{"pos": [0, POISON_SAFE_DEPTH], "kind": "egg"}]))
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts), acts


def test_unhealed_char_ONE_BELOW_the_cap_wont_scout_or_frontier_onto_it():
    # The second live dance flavour (run #196, c19455 in spire): with NO loot at all,
    # the un-gated scout/frontier steps walked the char onto the cap tile and the
    # retreat threw it back — N,N,S,S forever. Every idle pull (frontier, scout,
    # rally, seeks) now respects the same strict cap.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    tiles = _vert_corridor(POISON_SAFE_DEPTH + 4)
    char = _field_char(pos=[0, POISON_SAFE_DEPTH - 1], stamina=40, inventory=[])
    acts = bot.on_frame(_field_frame(char, tiles))
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts), acts


def test_unhealed_char_ONE_BELOW_the_cap_wont_SCOUT_onto_it():
    # Aimed specifically at the scout step (the frontier tests above never reach it —
    # a frontier offer preempts). Fully-explored bounded corridor -> no frontier;
    # imminent refresh -> no looted-out retreat (1.5, would out-score scout and mask
    # the gate). Scout's first candidate dir is N (nav.DIRS order) onto the cap tile:
    # the strict depth gate must refuse it, leaving rest — never a step onto ground
    # the poison retreat immediately vacates.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    top = POISON_SAFE_DEPTH + 4
    char = _field_char(pos=[0, POISON_SAFE_DEPTH - 1], stamina=40, inventory=[])
    frame = {"world": "vale", "tick": 10, "chars": [char],
             "bounds": [1, top + 1],                      # corridor IS the world: no frontier
             "next_refresh": {"in_ticks": 1},             # suppress the looted-out retreat
             "visible": {"tiles": _vert_corridor(top), "entities": [],
                         "items": [], "gold": []}}
    acts = bot.on_frame(frame)
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts), acts


def test_unhealed_char_TWO_below_the_cap_feels_no_pull_from_past_cap_loot():
    # v0.105.0 — the goal filter (run #197, c19465 thrashing y10<->y11 while the village
    # re-embarked it 1051 times). Step-gating alone relocated the dance: at cap-2 the
    # first step toward a past-cap chest is LEGAL, at cap-1 it is not, so the offer
    # flickered with position. A goal an un-healed char may not reach must generate no
    # pull at ANY distance — then the world honestly reads looted-out and the char
    # commits home. Bounded world (no frontier) so the gather pull is the only
    # candidate the mutant could win with.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    top = POISON_SAFE_DEPTH + 4
    char = _field_char(pos=[0, POISON_SAFE_DEPTH - 2], stamina=40, inventory=[])
    frame = {"world": "vale", "tick": 10, "chars": [char],
             "bounds": [1, top + 1],
             "visible": {"tiles": _vert_corridor(top), "entities": [],
                         "items": [{"pos": [0, POISON_SAFE_DEPTH + 1], "kind": "egg"}],
                         "gold": []}}
    acts = bot.on_frame(frame)
    assert all(not (a.get("action") == "move" and a.get("dir") == "N") for a in acts), acts
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts, \
        f"should commit home (looted-out), got {acts}"


def test_the_looted_out_retreat_STAMPS_returned_empty_end_to_end():
    # v0.105.0 — the village half keys off this stamp; the wizard-recall lesson
    # (a manually-stamped unit test masked the missing stamp) says drive it through
    # on_frame and read the stamp back.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    top = POISON_SAFE_DEPTH + 4
    char = _field_char(pos=[0, POISON_SAFE_DEPTH - 2], stamina=40, inventory=[])
    frame = {"world": "vale", "tick": 10, "chars": [char],
             "bounds": [1, top + 1],
             "visible": {"tiles": _vert_corridor(top), "entities": [],
                         "items": [], "gold": []}}
    bot.on_frame(frame)
    assert bot.strategy._returned_empty.get("c1") == 10, \
        f"looted-out retreat did not stamp: {bot.strategy._returned_empty}"


def test_unhealed_char_still_gathers_loot_within_the_safe_depth():
    # The guard must bite only PAST the cap. Loot the char can reach without crossing
    # POISON_SAFE_DEPTH is still pursued — otherwise we would starve shallow gathering
    # to kill an edge oscillation. Loot lies EAST at a safe depth; the frontier would
    # pull elsewhere, so an EAST step proves the guard left the in-cap step alone.
    from steemer.strategy.explorer import POISON_SAFE_DEPTH
    bot = _bot()
    y = POISON_SAFE_DEPTH - 2
    tiles = [[x, yy, "floor"] for x in range(6) for yy in range(0, POISON_SAFE_DEPTH + 4)]
    char = _field_char(pos=[1, y], stamina=40, inventory=[])
    acts = bot.on_frame(_field_frame(char, tiles, items=[{"pos": [4, y], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "move", "dir": "E"} in acts        # toward the loot


# --- v0.37.0 predator spacing, v0.38.0 mode-gated by band severity ---
# Geometry: char at (0,2), mob(s) NORTH. (0,3) borders the unknown -> a north frontier
# (score 2.5). Spacing scores 3.0 in a SEVERE band (beats the frontier -> char steps
# SOUTH away) but only 1.5 in a CALM band (loses to the frontier -> char pushes NORTH
# and keeps working). So the chosen direction reveals the band the char thinks it's in.
_SPACE_TILES = [[0, 1, "floor"], [0, 2, "floor"], [0, 3, "floor"], [1, 2, "floor"]]


def test_severe_band_spaces_off_from_the_predators():
    # a predator SWARM is a severe band -> spacing (3.0) beats the frontier, so the char
    # disengages SOUTH (away from the ONE near predator). The default char has no level, so
    # it's a FORAGER (MELEE_DENSE_FORAGER == 4); the extra predators are far NORTH (count only,
    # they don't block the east frontier the calm case would take), giving a clean S-vs-not-S.
    bot = _bot()
    char = _field_char(pos=[0, 2], stamina=40)
    acts = bot.on_frame(_field_frame(char, _SPACE_TILES, entities=[
        {"pos": [0, 4], "faction": "monster", "kind": "wolf"},     # near (dist 2)
        {"pos": [0, 8], "faction": "monster", "kind": "boar"},     # far -> count only
        {"pos": [0, 10], "faction": "monster", "kind": "wolf"},    # far -> count only
        {"pos": [0, 14], "faction": "monster", "kind": "boar"}]))  # 4th -> trips forager's 4
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts     # away from the swarm


def test_calm_band_yields_spacing_to_exploration():
    # v0.38.0 the income fix: a LONE wolf (no undead, not a swarm) is a calm band, so spacing
    # drops to 1.5 and LOSES to the north frontier (2.5) — the char keeps working (pushes N)
    # instead of fleeing, recovering the gold-gathering 0.37's flat spacing cost.
    bot = _bot()
    char = _field_char(pos=[0, 2], stamina=40)
    acts = bot.on_frame(_field_frame(char, _SPACE_TILES,
                        entities=[{"pos": [0, 4], "faction": "monster", "kind": "wolf"}]))
    # it keeps working (explores toward a frontier) rather than fleeing SOUTH away from the
    # lone wolf — the discriminator vs the severe case, robust to which frontier BFS picks.
    assert any(a.get("action") == "move" for a in acts)                # not idling
    assert all(not (a.get("action") == "move" and a.get("dir") == "S") for a in acts)  # not fleeing


def test_severe_band_from_a_high_undead_fraction():
    # severity also trips on undead FRACTION (poison-DoT bands are the lethal ones): a lone
    # melee predator at dist 2 plus undead in view (>= UNDEAD_SEVERE_FRAC of mobs) -> severe,
    # so the char spaces off (S) even though it's only one predator. The undead here sits
    # OUTSIDE FLEE_RADIUS (dist>4) so it raises the fraction without triggering the undead-flee.
    bot = _bot()
    char = _field_char(pos=[0, 2], stamina=40)
    acts = bot.on_frame(_field_frame(char, _SPACE_TILES, entities=[
        {"pos": [0, 4], "faction": "monster", "kind": "wolf"},
        {"pos": [0, 12], "faction": "monster", "kind": "cultist"}]))   # undead, far
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts     # severe -> disengage


def test_gathering_still_beats_spacing_so_income_is_safe():
    # a grab underfoot (banked, death-proof) is worth one tick in any band — pickup (6.0)
    # outscores spacing (<=3.0), then spacing fires next tick.
    bot = _bot()
    char = _field_char(pos=[0, 2], stamina=40)
    acts = bot.on_frame(_field_frame(char, _SPACE_TILES,
                        entities=[{"pos": [0, 4], "faction": "monster", "kind": "wolf"}],
                        gold=[{"pos": [0, 2]}]))
    assert {"char_uid": "c1", "action": "pickup"} in acts


def test_benign_wildlife_does_not_trigger_spacing():
    # a chicken (WILDLIFE_SAFE) at dist 2 is NOT a predator -> no spacing; the char is
    # free to push the north frontier toward it. Guards that spacing is predator-scoped.
    bot = _bot()
    char = _field_char(pos=[0, 2], stamina=40)
    acts = bot.on_frame(_field_frame(char, _SPACE_TILES,
                        entities=[{"pos": [0, 4], "faction": "monster", "kind": "chicken"}]))
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in acts     # not spaced away


def test_role_of_is_derived_from_level():
    # v0.39.0: a leveled veteran is a Guardian, a fresh recruit a Forager. Missing level
    # (a not-yet-seen char) defaults to Forager, the low-risk assumption.
    from steemer.strategy.explorer import role_of, GUARDIAN_LEVEL
    assert role_of({"level": GUARDIAN_LEVEL}) == "guardian"
    assert role_of({"level": GUARDIAN_LEVEL + 3}) == "guardian"
    assert role_of({"level": GUARDIAN_LEVEL - 1}) == "forager"
    assert role_of({"level": 1}) == "forager"
    assert role_of({}) == "forager"


def test_barren_forager_disengages_like_a_guardian():
    # v0.39.1: a forager only earns its BOLD thresholds when there's value to gather. With
    # NOTHING in view (a coin-dry band) it reverts to the cautious (Guardian) thresholds, so
    # a lone recruit spaces off from a 2-predator band exactly like a veteran does — no
    # taking predator risk for zero income (the 0.39 flaw that re-fed the death->recruit drain).
    from steemer.strategy.explorer import GUARDIAN_LEVEL
    ents = [{"pos": [0, 4], "faction": "monster", "kind": "wolf"},    # near (dist 2)
            {"pos": [0, 8], "faction": "monster", "kind": "boar"}]    # far -> 2 preds total
    for level in (2, GUARDIAN_LEVEL + 1):        # barren forager AND guardian both disengage
        acts = _bot().on_frame(_field_frame(       # fresh bot per char: no cross-char state bleed
            _field_char(pos=[0, 2], stamina=40, level=level), _SPACE_TILES, entities=ents))
        assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts   # spaced off (cautious)


def test_forager_works_toward_value_instead_of_fleeing():
    # v0.39.1: WITH value in view (a gold coin), a forager does not flee the 2-predator band —
    # it works toward the coin (gather beats spacing). The income upside earns the risk.
    ents = [{"pos": [0, 4], "faction": "monster", "kind": "wolf"},
            {"pos": [0, 8], "faction": "monster", "kind": "boar"}]
    acts = _bot().on_frame(_field_frame(
        _field_char(pos=[0, 2], stamina=40, level=2), _SPACE_TILES,
        entities=ents, gold=[{"pos": [1, 2]}]))         # a coin one tile east
    assert any(a.get("action") == "move" for a in acts)
    assert all(not (a.get("action") == "move" and a.get("dir") == "S") for a in acts)  # not fleeing


def test_full_char_does_not_pick_up_more_loot():
    # A pack-full char (used >= cap-1) standing on loot, with just enough stamina
    # to afford a pickup (cost ~10) but NOT the stamina-gated walk-home move
    # (~30): without the v0.15.0 `not full` gate it would grab the loot and cross
    # into overburden. With the gate it grabs nothing and rests (no action).
    bot = _bot()
    char = _field_char(stamina=15, carry={"used": 19, "cap": 20})
    actions = bot.on_frame(_field_frame(char, FLOOR3,
                                        items=[{"pos": [0, 0], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "pickup"} not in actions
    assert actions == []              # nothing affordable but rest


def test_overburdened_char_drops_loot_to_shed_weight():
    # Overburdened (used >= cap): the walk home is stamina-unaffordable, so
    # without the v0.15.0 shed escape the char sits stranded until it dies.
    # It should drop its least-useful carried item to regain mobility.
    bot = _bot()
    char = _field_char(stamina=15, carry={"used": 21, "cap": 20},
                       inventory=[{"kind": "lumber", "item_id": "L1"}])
    actions = bot.on_frame(_field_frame(char, FLOOR3))
    assert {"char_uid": "c1", "action": "drop", "item_id": "L1"} in actions


def test_homing_latch_suppresses_repickup_after_shed():
    # v0.16.0 thrash fix: a char that filled up latches into "heading home"; even
    # after it sheds weight back below `full`, it must NOT re-grab loot underfoot
    # (that item is the one it just dropped) — it keeps walking home.
    bot = _bot()
    # frame 1: overburdened -> latches homing (and sheds)
    bot.on_frame(_field_frame(
        _field_char(carry={"used": 21, "cap": 20},
                    inventory=[{"kind": "lumber", "item_id": "L1"}]), FLOOR3))
    # frame 2: now below `full` (19) but still above half-cap (10) -> latch holds
    acts = bot.on_frame(_field_frame(
        _field_char(carry={"used": 15, "cap": 20}), FLOOR3,
        items=[{"pos": [0, 0], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "pickup"} not in acts
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts  # still homing


def test_homing_latch_clears_when_light_and_loots_again():
    # The latch releases once the village has sold the haul down to <= half cap,
    # so the char resumes looting on its next trip out.
    bot = _bot()
    bot.on_frame(_field_frame(
        _field_char(carry={"used": 21, "cap": 20},
                    inventory=[{"kind": "lumber", "item_id": "L1"}]), FLOOR3))  # latch
    acts = bot.on_frame(_field_frame(
        _field_char(carry={"used": 5, "cap": 20}), FLOOR3,   # light -> latch clears
        items=[{"pos": [0, 0], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "pickup"} in acts


def test_village_sells_before_embarking():
    bot = _bot()
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [{"char_uid": "c1",
                        # `tomato` is pure loot. It used to be `bone`, which v0.59.0
                        # made a KEPT vigor herb -- this test is about the ORDER of
                        # sell-before-embark, so it needs a genuinely disposable item.
                        "inventory": [{"kind": "tomato", "item_id": "i1", "tier": 1}],
                        "equipment": {"hand": None}, "stats": {"str": 2},
                        "hp": 10, "max_hp": 10}]}
    actions = bot.on_frame(frame)
    assert actions == [{"char_uid": "c1", "action": "sell", "item_id": "i1"}]


def test_village_recruits_toward_the_cap_when_empty_handed():
    bot = _bot()
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 0, "chars_here": [], "chars_by_world": {}},
             "chars": []}
    assert bot.on_frame(frame) == [{"action": "recruit"}]


def test_affordability_rests_rather_than_attempting_unaffordable(tmp_path):
    # stamina 15 cannot afford an attack (~20) or a move (~20): the character
    # rests (sends nothing) instead of a doomed action that would only earn a
    # not_enough_stamina error and forfeit the idle regen. (0.1.0 would attack.)
    bot = _bot()
    char = _field_char(stamina=15)
    frame = _field_frame(char, FLOOR3,
                         entities=[{"pos": [1, 0], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.5}])
    assert bot.on_frame(frame) == []


def test_acts_once_stamina_is_affordable():
    bot = _bot()
    char = _field_char(stamina=25)     # >= attack cost (~20)
    frame = _field_frame(char, FLOOR3,
                         entities=[{"pos": [1, 0], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.5}])
    assert {"char_uid": "c1", "action": "attack", "target": [1, 0]} in bot.on_frame(frame)


def test_move_requires_staleness_headroom_above_raw_cost():
    # v0.9.0: field `move` is 98% of not_enough_stamina — the bot issued steps it
    # "afforded" (sta >= raw cost 20) that the server rejected because the acted-on
    # frame was ~1 tick stale (true stamina lower). The move gate now needs headroom
    # (1.5x raw cost = 30) so a stale-high reading still affords the step; below that
    # the char rests and regens instead of spamming a doomed move. A pure-exploration
    # frame (no enemy/loot/container, only scout moves) isolates the move gate.
    bot = _bot()
    # sta 25: >= raw cost (20) but < headroom (30) -> rests rather than a doomed step.
    assert bot.on_frame(_field_frame(_field_char(stamina=25, pos=[0, 0]), FLOOR3)) == []
    # sta 30: clears the headroom -> it moves. (Break the margin and the sta-25 case
    # above wrongly emits a move, so that assertion fails — the mutation check.)
    acts = bot.on_frame(_field_frame(_field_char(stamina=30, pos=[0, 0]), FLOOR3))
    assert any(a.get("action") == "move" for a in acts)


def test_attack_is_not_subject_to_the_move_headroom():
    # the headroom is move-only: an attack still fires at the raw cost (20), so a
    # sta-25 char with an adjacent enemy attacks rather than resting. (Guards against
    # the margin being applied to every action and throttling combat.)
    bot = _bot()
    char = _field_char(stamina=25)
    acts = bot.on_frame(_field_frame(char, FLOOR3,
                        entities=[{"pos": [1, 0], "faction": "monster",
                                   "kind": "rat_grey", "hp_frac": 0.5}]))
    assert {"char_uid": "c1", "action": "attack", "target": [1, 0]} in acts


def test_adjacent_monster_is_attacked_never_walked_onto():
    bot = _bot()
    frame = _field_frame(_field_char(), FLOOR3,
                         entities=[{"pos": [0, 1], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.9}])
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [0, 1]} in actions
    # no emitted move steps onto the monster tile (0,1)
    from steemer import nav
    for a in actions:
        if a.get("action") == "move":
            dx, dy = nav.DIRS[a["dir"]]
            assert (0 + dx, 0 + dy) != (0, 1)


def test_two_characters_do_not_move_onto_the_same_tile():
    # a 1-wide corridor with a single open middle tile; both ends would pick it.
    # Reservation must stop the second from colliding. (0.1.0 collides.)
    bot = _bot()
    W = "wall"
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [0, 2, "floor"],
             [1, 0, W], [1, 1, W], [1, 2, W], [-1, 0, W], [-1, 1, W], [-1, 2, W],
             [0, -1, W], [0, 3, W]]
    a = _field_char(char_uid="a", pos=[0, 0])
    b = _field_char(char_uid="b", pos=[0, 2])
    frame = {"world": "vale", "tick": 10, "chars": [a, b],
             "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}
    actions = bot.on_frame(frame)
    dests = []
    for act in actions:
        if act.get("action") == "move":
            base = a["pos"] if act["char_uid"] == "a" else b["pos"]
            from steemer import nav
            dx, dy = nav.DIRS[act["dir"]]
            dests.append((base[0] + dx, base[1] + dy))
    assert len(dests) == len(set(dests)), f"two chars collided on a tile: {dests}"


def _south_corridor():
    # a north-south corridor: (0,0)=exit row, (0,1), (0,2); an enemy sits east.
    return [[0, 0, "floor"], [0, 1, "floor"], [0, 2, "floor"]]


def test_retreats_at_60pct_even_when_it_would_have_fought_before(tmp_path):
    # 50% HP: below 0.3.0's 0.6 threshold but above 0.2.0's 0.4 — so 0.2.0 would
    # attack the adjacent monster and 0.3.0 flees toward the exit.
    bot = _bot()
    char = _field_char(pos=[0, 1], hp=15, max_hp=30, stamina=40)
    frame = _field_frame(char, _south_corridor(),
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.9}])
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in actions   # fleeing
    assert all(a.get("action") != "attack" for a in actions)             # not fighting


def test_poison_triggers_retreat_even_at_full_hp(tmp_path):
    bot = _bot()
    char = _field_char(pos=[0, 1], hp=30, max_hp=30, stamina=40,
                       statuses=[{"kind": "poison", "ticks_left": 5, "power": 1}])
    frame = _field_frame(char, _south_corridor(),
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.9}])
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in actions
    assert all(a.get("action") != "attack" for a in actions)


def test_hurt_suppresses_offense_when_it_cannot_flee(tmp_path):
    # boxed in (no walkable exit) and hurt, adjacent to a monster it could afford
    # to hit: 0.2.0 would attack; 0.3.0 offers only heal/flee -> rests (empty).
    W = "wall"
    bot = _bot()
    char = _field_char(pos=[0, 1], hp=10, max_hp=30, stamina=40)
    tiles = [[0, 1, "floor"], [1, 1, "floor"],
             [0, 0, W], [0, 2, W], [-1, 1, W]]
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.5}])
    assert bot.on_frame(frame) == []          # heal/flee only, both impossible -> rest


def test_village_does_not_buy_potions_in_gold_rush_hoard():
    # v0.24.0 gold-rush HOARD: potion-buying is frozen (every coin is stockpiled),
    # even for an armed, potion-less char sitting on 100 gold.
    bot = _bot()
    char = {"char_uid": "c1", "inventory": [], "equipment": {"hand": {"kind": "club"}},
            "stats": {"str": 2}, "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert all(not (a.get("action") == "buy" and a.get("kind") == "potion_red")
               for a in bot.on_frame(frame))


def test_village_does_not_buy_a_second_potion():
    bot = _bot()
    char = {"char_uid": "c1",
            "inventory": [{"kind": "potion_red", "item_id": "p1", "tier": 1}],
            "equipment": {"hand": {"kind": "club"}}, "stats": {"str": 2},
            "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    actions = bot.on_frame(frame)
    assert all(not (a.get("action") == "buy" and a.get("kind") == "potion_red")
               for a in actions)


_SHOP_CLUB = {"stock": [{"kind": "club", "buy_price": 15, "sell_price": 3}]}


def _bare_village_char():
    return {"char_uid": "c1", "inventory": [], "equipment": {}, "stats": {"str": 2},
            "hp": 30, "max_hp": 30}


def _village_shop_frame(gold):
    return {"world": "village", "tick": 3,
            "guild": {"gold": gold, "chars_here": ["c1"], "chars_by_world": {"vale": ["e1"]}},
            "chars": [_bare_village_char()], "shop": _SHOP_CLUB}


def test_village_arms_a_bare_char_when_gold_is_above_the_floor():
    # v0.40.0 DIRECTION CHANGE: gold is now a floor, not the objective — the goal is to level
    # and master the game, and the rival scan showed us bare-handed vs armed rivals. So a bare
    # char buys the cheapest weapon whenever the treasury is above WEAPON_BUY_FLOOR.
    from steemer.strategy.explorer import WEAPON_BUY_FLOOR
    acts = _bot().on_frame(_village_shop_frame(WEAPON_BUY_FLOOR + 200))
    assert {"char_uid": "c1", "action": "buy", "kind": "club"} in acts


def test_village_does_not_arm_below_the_gold_floor():
    # below the floor we protect the working reserve and harvest instead — the "gather when
    # low on funds" half of the operator's direction.
    from steemer.strategy.explorer import WEAPON_BUY_FLOOR
    acts = _bot().on_frame(_village_shop_frame(WEAPON_BUY_FLOOR - 50))
    assert all(a.get("action") != "buy" for a in acts)


def _world_field_frame(world, tiles, entities=()):
    return {"world": world, "tick": 10, "chars": [_field_char(pos=[0, 3])],
            "visible": {"tiles": list(tiles), "entities": list(entities),
                        "items": [], "gold": []}}


def test_recruiting_fills_the_ROSTER_CAP():
    """v0.87.0 REPLACED the v0.27.0 contract, on operator direction ("we should probably
    fill the roster"). The old rule stopped at the fieldable count (17) to avoid arming
    an undeployable bench — but recruits are free, the gift lottery is the only wizard
    source (~1 in 3 rolls int-gifted), FODDER absorbs the bad rolls at zero coin, and
    the gold-drain fear died when arming moved behind its floors. Recruiting now stops
    only at roster_cap."""
    bot = _bot()
    bot.config = {"party_cap": 5, "world_cap": 30, "roster_cap": 30,
                  "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    here17 = [f"h{i}" for i in range(17)]
    at_17 = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": here17, "chars_by_world": {}},
             "chars": [_idle_village_char("h0")]}
    assert any(a.get("action") == "recruit" for a in bot.on_frame(at_17)), \
        "17 of 30 must keep recruiting — the bench is wizard candidates now"
    at_30 = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": [f"h{i}" for i in range(30)],
                       "chars_by_world": {}},
             "chars": [_idle_village_char("h0")]}
    assert all(a.get("action") != "recruit" for a in bot.on_frame(at_30))   # cap is cap


def test_embark_routes_to_the_safest_world():
    # v0.26.0: after seeing vale full of undead and mines as wildlife, a char embarks
    # into the SAFE world (mines), not the undead one.
    bot = _bot()
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 1,
                  "maps": [{"id": "vale"}, {"id": "mines"}]}
    corridor = [[0, y, "floor"] for y in range(0, 6)] + [[3, 3, "floor"]]
    bot.on_frame(_world_field_frame("vale", corridor,
                 [{"pos": [3, 3], "faction": "monster", "kind": "zombie", "hp_frac": 0.9}]))
    bot.on_frame(_world_field_frame("mines", corridor,
                 [{"pos": [3, 3], "faction": "monster", "kind": "skunk", "hp_frac": 0.9}]))
    village = {"world": "village", "tick": 20,
               "guild": {"gold": 5, "chars_here": ["c1"],
                         "chars_by_world": {"vale": ["a"], "mines": ["b"]}},
               "chars": [_idle_village_char("c1")]}
    acts = bot.on_frame(village)
    assert acts and acts[0]["action"] == "embark" and acts[0]["map"] == "mines"


def test_flee_still_grabs_a_coin_in_the_safe_direction():
    # v0.26.0: while evading an undead to the EAST, the char still fetches a coin to
    # the WEST (farther from the threat) rather than only fleeing south.
    bot = _bot()
    tiles = ([[0, y, "floor"] for y in range(0, 4)]
             + [[-1, 3, "floor"], [-2, 3, "floor"], [3, 3, "floor"]])
    frame = _world_field_frame("vale", tiles,
                               [{"pos": [3, 3], "faction": "monster",
                                 "kind": "zombie", "hp_frac": 0.9}])
    frame["visible"]["gold"] = [{"pos": [-2, 3]}]
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "W"} in acts   # toward the safe coin


def _threat_frame(mob_kind, gold=()):
    # char at (0,3) in a north-south corridor; a mob 3 tiles east at (3,3).
    tiles = [[0, y, "floor"] for y in range(0, 6)] + [[1, 3, "floor"], [2, 3, "floor"], [3, 3, "floor"]]
    return _field_frame(_field_char(pos=[0, 3], stamina=40), tiles, gold=gold,
                        entities=[{"pos": [3, 3], "faction": "monster",
                                   "kind": mob_kind, "hp_frac": 0.9}])


def test_flees_from_a_nearby_undead_threat():
    # v0.25.0: a THREAT mob (zombie) within FLEE_RADIUS -> flee to the village, do
    # not loot or explore.
    bot = _bot()
    acts = bot.on_frame(_threat_frame("zombie"))
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts        # fleeing home
    assert {"char_uid": "c1", "action": "move", "dir": "N"} not in acts    # not exploring


def test_does_not_flee_benign_wildlife():
    # a benign mob (skunk) at the same distance is NOT a threat -> the char keeps
    # gold-rushing (explores north here), it does not flee.
    bot = _bot()
    acts = bot.on_frame(_threat_frame("skunk"))
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in acts        # normal exploration


def test_snatches_underfoot_coin_before_fleeing_undead():
    # instant banked gold underfoot is worth one grab even while fleeing.
    bot = _bot()
    acts = bot.on_frame(_threat_frame("ghoul", gold=[{"pos": [0, 3]}]))
    assert {"char_uid": "c1", "action": "pickup"} in acts


def test_routes_around_a_melee_predator_not_into_it():
    # v0.30.0: run #85's real death cause — a full-HP char stepped ADJACENT to a
    # golem_stone (a melee predator absent from the undead THREAT set) and took -15,
    # then died. Now the tiles next to such a mob are blocked, so the char won't step
    # onto a coin sitting adjacent to the golem. (Mutation: drop golem_stone from
    # MELEE_THREAT_KINDS and it walks E onto the coin -> into strike range.)
    bot = _bot()
    tiles = [[x, 3, "floor"] for x in range(4)] + [[0, 2, "floor"], [0, 4, "floor"]]
    char = _field_char(pos=[0, 3], stamina=40)
    frame = _field_frame(char, tiles, gold=[{"pos": [1, 3]}],
                         entities=[{"pos": [2, 3], "faction": "monster",
                                    "kind": "golem_stone", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "E"} not in acts


def test_a_distant_melee_predator_does_not_trigger_the_undead_flee():
    # v0.30.0: golem_stone is melee-AVOIDED (block its neighbours), NOT flee-at-radius-4
    # like the ranged/chasing undead — so a char 3 tiles from a golem keeps working
    # (explores north here) instead of running home, preserving wildlife-world looting.
    bot = _bot()
    acts = bot.on_frame(_threat_frame("golem_stone"))
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in acts   # still exploring


def test_dodges_an_adjacent_melee_predator_instead_of_fighting_it():
    # v0.31.0: run #86 showed delver/boar still hit because the MOB drifts adjacent to a
    # stationary char (0.30.0 blocks US approaching, not the mob). An adjacent predator
    # must be DODGED (step to a farther tile), never attacked — fighting a delver is a
    # fast death. The delver is at [1,2] (north of the char), so the dodge is NOT north.
    bot = _bot()
    tiles = [[x, y, "floor"] for x in range(3) for y in range(3)]
    char = _field_char(pos=[1, 1], stamina=40)
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 2], "faction": "monster", "kind": "delver", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [1, 2]} not in acts   # never fight it
    moves = [a for a in acts if a.get("action") == "move"]
    assert moves, "should step away from the predator"
    assert all(a.get("dir") != "N" for a in moves)   # N (+y) steps toward the delver


def test_low_stamina_char_still_dodges_a_predator_instead_of_resting():
    # v0.34.0: the operator watched a low-stamina char sit and take wolf hits without
    # fleeing or fighting — the 1.5x move-stamina margin (raw 20 -> needs 30) was
    # starving its only escape. A survival move (dodge/flee/retreat) is now URGENT and
    # gated on the RAW cost, so at stamina 25 (>= raw 20, < margin 30) the char dodges
    # the adjacent wolf rather than resting. (Mutation: drop urgent -> it rests, [].)
    bot = _bot()
    tiles = [[x, y, "floor"] for x in range(3) for y in range(3)]
    char = _field_char(pos=[1, 1], stamina=25)
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 2], "faction": "monster",
                                    "kind": "wolf", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert any(a.get("action") == "move" for a in acts), "should dodge the wolf, not rest"


def test_still_attacks_a_confirmed_benign_adjacent_mob():
    # regression guard: the dodge is ONLY for predators — a CONFIRMED-benign mob
    # (chicken, in WILDLIFE_SAFE) adjacent is still attacked, so the dodge/allowlist
    # does not neuter normal combat/loot-for-drops on harmless wildlife.
    bot = _bot()
    tiles = [[x, y, "floor"] for x in range(3) for y in range(3)]
    char = _field_char(pos=[1, 1], stamina=40)
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 2], "faction": "monster", "kind": "chicken", "hp_frac": 0.5}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [1, 2]} in acts


def test_an_unknown_new_mob_is_avoided_by_default():
    # v0.32.0 INVERSION: a mob never seen before (a fresh band's lava_ant) is NOT in
    # WILDLIFE_SAFE, so it is a predator by DEFAULT — dodged when adjacent, never
    # attacked. This is the whole point: new killers are avoided on sight, not after
    # the first corpse. (Mutation: add "lava_ant" to WILDLIFE_SAFE and it gets attacked.)
    bot = _bot()
    tiles = [[x, y, "floor"] for x in range(3) for y in range(3)]
    char = _field_char(pos=[1, 1], stamina=40)
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 2], "faction": "monster", "kind": "lava_ant", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [1, 2]} not in acts   # never fight it
    assert [a for a in acts if a.get("action") == "move"], "should dodge the unknown mob"


def test_cracks_a_chest_beside_a_predator_before_dodging():
    # v0.33.0: a chest (1-21g + loot, tomes 24-44g) beside a predator is worth one hit —
    # crack it, THEN dodge next tick. 0.32.0 would have just dodged and left it. (This is
    # the income-recovery half of the survival/income tradeoff the KPI alarm flagged.)
    bot = _bot()
    tiles = [[x, y, "floor"] for x in range(3) for y in range(3)
             if (x, y) != (0, 1)] + [[0, 1, "chest"]]
    char = _field_char(pos=[1, 1], stamina=40)
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 2], "faction": "monster",
                                    "kind": "golem_stone", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "open", "target": [0, 1]} in acts


def test_reaches_a_chest_whose_access_is_beside_a_predator():
    # v0.33.0: a chest boxed in so its only walkable access tile sits beside a predator
    # is now REACHABLE — 0.32.0 hard-blocked every predator-adjacent tile and cratered
    # chest-opens (-69%). golem [1,1]; chest [0,0]; the access tile [0,1] is golem-
    # adjacent (blocked in 0.32.0) but chest-access is now exempt, so the char steps to
    # it. (Mutation: drop the chest_access exemption and it can't approach.)
    bot = _bot()
    tiles = [[0, 0, "chest"], [0, 1, "floor"], [0, 2, "floor"],
             [1, 1, "floor"], [1, 2, "floor"]]
    char = _field_char(pos=[0, 2], stamina=40)
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "golem_stone", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts   # stepping to [0,1]


def test_still_will_not_beeline_a_coin_that_sits_beside_a_predator():
    # v0.33.0 guard: only CHESTS (high value) justify stepping into strike range; a
    # single ~2g coin is NOT worth a -15 hit, so a predator-adjacent COIN stays blocked
    # (this is the pre-existing routes-around behaviour, re-asserted after the chest
    # exemption to prove coins were not also loosened).
    bot = _bot()
    tiles = [[x, 3, "floor"] for x in range(4)] + [[0, 2, "floor"], [0, 4, "floor"]]
    char = _field_char(pos=[0, 3], stamina=40)
    frame = _field_frame(char, tiles, gold=[{"pos": [1, 3]}],
                         entities=[{"pos": [2, 3], "faction": "monster",
                                    "kind": "golem_stone", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "E"} not in acts


def _walled_box_frame(char, gold=(), items=(), next_refresh=None):
    # a 3x3 floor box fully ringed by KNOWN walls: every floor tile's neighbours are
    # seen, so nav.frontier finds nothing unexplored -> the world is 'fully explored'.
    tiles = [[x, y, "floor"] for x in range(3) for y in range(3)]
    for x in range(-1, 4):
        for y in range(-1, 4):
            if not (0 <= x <= 2 and 0 <= y <= 2):
                tiles.append([x, y, "wall"])
    f = {"world": "vale", "tick": 10, "chars": [char],
         "visible": {"tiles": tiles, "entities": [], "items": list(items), "gold": list(gold)}}
    if next_refresh is not None:
        f["next_refresh"] = next_refresh
    return f


def test_depleted_char_heads_home_when_no_refresh_is_imminent(tmp_path):
    # v0.36.0: nothing to grab, nowhere to explore, and no next_refresh -> the world is
    # looted-out, so head HOME to re-embark somewhere fresher instead of scout-wandering.
    s = Storage(str(tmp_path / "d.db"), commit_every=1)
    bot = _bot(storage=s)
    bot.on_frame(_walled_box_frame(_field_char(pos=[1, 1], stamina=40)))
    row = s.conn.execute("SELECT action, reasoning FROM decisions").fetchone()
    s.close()
    assert row[0] == "move"
    assert "looted-out" in row[1]      # the depletion-retreat won, not the 1.0 scout


def test_depleted_char_stays_put_when_a_refresh_is_imminent(tmp_path):
    # v0.36.0 refresh guard: same looted-out world, but this world refreshes in 50 ticks
    # (< REFRESH_STAY_TICKS) -> DON'T pay a home round-trip; wait for the fresh coins.
    s = Storage(str(tmp_path / "d.db"), commit_every=1)
    bot = _bot(storage=s)
    bot.on_frame(_walled_box_frame(_field_char(pos=[1, 1], stamina=40),
                                   next_refresh={"band": 1, "in_ticks": 50}))
    row = s.conn.execute("SELECT reasoning FROM decisions").fetchone()
    s.close()
    assert "looted-out" not in (row[0] or "")   # stayed (scouts/waits), did not retreat


def test_gold_rush_beelines_to_a_gold_coin_over_loot():
    # v0.24.0: a gold coin outranks ordinary loot — chars go for banked gold first.
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [0, 2, "floor"], [1, 0, "floor"], [2, 0, "floor"]]
    frame = _field_frame(_field_char(pos=[0, 0], stamina=40), tiles,
                         items=[{"pos": [2, 0], "kind": "egg"}], gold=[{"pos": [0, 2]}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in acts   # toward the coin
    assert {"char_uid": "c1", "action": "move", "dir": "E"} not in acts  # not the egg


def test_gold_rush_cracks_an_adjacent_chest():
    # v0.24.0: opening an adjacent chest (direct gold + loot) is a top priority.
    bot = _bot()
    tiles = [[0, 0, "floor"], [1, 0, "chest"]]
    acts = bot.on_frame(_field_frame(_field_char(pos=[0, 0], stamina=40), tiles))
    assert {"char_uid": "c1", "action": "open", "target": [1, 0]} in acts


def test_gold_rush_does_not_chase_a_distant_monster():
    # v0.24.0: no chasing — combat isn't the gold source. With a non-adjacent monster
    # east and a frontier north, the char explores north, it does NOT close on the mob.
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [0, 2, "floor"], [1, 0, "floor"], [2, 0, "floor"]]
    frame = _field_frame(_field_char(pos=[0, 0], stamina=40), tiles,
                         entities=[{"pos": [2, 0], "faction": "monster",
                                    "kind": "zombie", "hp_frac": 0.9}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "E"} not in acts  # no chase east


def test_village_sells_food_instead_of_hoarding_it():
    # v0.19.0: a char carrying food (drink loot) must SELL it in the village, not
    # hoard it. Before the fix, food was unsellable so a full-of-food char had no
    # village action and got re-embarked off the boundary forever (the stuck-gold
    # thrash). Armed + no potion + food + gold: it should sell the food.
    bot = _bot()
    char = {"char_uid": "c1",
            "inventory": [{"kind": "meat", "item_id": "m1", "uses": ["drink"]}],
            "equipment": {"hand": {"kind": "club"}}, "stats": {"str": 2},
            "hp": 30, "max_hp": 30, "carry": {"used": 1, "cap": 24}}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert {"char_uid": "c1", "action": "sell", "item_id": "m1"} in bot.on_frame(frame)


def test_pick_xp_stat_prefers_an_affordable_stat_over_an_unaffordable_top_priority():
    # v0.22.0: VIT is top priority but its cost grows with value; at vit=5 it costs
    # 40, so a char banking 17 XP can't afford it and must fall to a cheaper stat it
    # CAN afford (END at 1 costs 8) — that is what finally makes spend_xp fire.
    from steemer.strategy.explorer import Explorer
    char = {"stats": {"vit": 5, "end": 1, "str": 2}, "gifts": [], "xp": 17}
    assert Explorer._pick_xp_stat(char) == "end"
    # nothing affordable -> None (bank it), even though stats are below the cap.
    broke = {"stats": {"vit": 1, "end": 1, "str": 1}, "gifts": [], "xp": 0}
    assert Explorer._pick_xp_stat(broke) is None


def test_village_spends_banked_xp_on_an_affordable_stat():
    # v0.22.0 end-to-end: an idle armed char with banked XP now issues spend_xp on
    # the affordable END rather than stalling on an unaffordable VIT (was: 0 spends).
    bot = _bot()
    char = {"char_uid": "c1", "hp": 30, "max_hp": 30,
            "inventory": [{"kind": "potion_red", "item_id": "p1", "tier": 1}],
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None},
            "stats": {"vit": 5, "end": 1, "str": 2}, "gifts": [], "xp": 17,
            "carry": {"used": 0, "cap": 24}}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 50, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == [{"char_uid": "c1", "action": "spend_xp", "stat": "end"}]


def test_village_hoard_does_not_arm_even_at_exactly_the_club_price():
    # v0.28.0 freeze at the boundary: gold == the club's exact price (15) is the
    # tightest case where the old logic would have armed. The pure hoard buys
    # nothing even here — proving the freeze isn't merely a raised reserve floor.
    bot = _bot()
    char = {"char_uid": "c1", "inventory": [], "equipment": {}, "stats": {"str": 2},
            "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 15, "chars_here": ["c1"], "chars_by_world": {"vale": ["e1"]}},
             "chars": [char], "shop": _SHOP_CLUB}
    assert all(a.get("action") != "buy" for a in bot.on_frame(frame))


def _village_char(**over):
    # armed + carrying a potion so the sell/weapon/potion steps all no-op and we
    # reach the spend_xp step.
    char = {"char_uid": "c1", "hp": 30, "max_hp": 30,
            "inventory": [{"kind": "potion_red", "item_id": "p1", "tier": 1}],
            "equipment": {"hand": {"kind": "club"}},
            "stats": {"vit": 1, "end": 1, "str": 1}, "gifts": [], "xp": 0}
    char.update(over)
    return char


def _village_frame1(char, gold=100):
    return {"world": "village", "tick": 3,
            "guild": {"gold": gold, "chars_here": ["c1"], "chars_by_world": {}},
            "chars": [char]}


def test_village_spends_xp_on_vit_first():
    bot = _bot()
    char = _village_char(stats={"vit": 1, "end": 1, "str": 1}, xp=10)
    assert bot.on_frame(_village_frame1(char)) == \
        [{"char_uid": "c1", "action": "spend_xp", "stat": "vit"}]


def test_village_spends_end_after_vit_capped():
    bot = _bot()
    char = _village_char(stats={"vit": 8, "end": 1, "str": 1}, xp=10)
    assert bot.on_frame(_village_frame1(char)) == \
        [{"char_uid": "c1", "action": "spend_xp", "stat": "end"}]


def test_village_gift_halves_xp_cost():
    # vit=2 costs 16 XP normally, 8 as a gift. With exactly 8 XP, only the gifted
    # character can afford the point.
    bot = _bot()
    gift = _village_char(stats={"vit": 2, "end": 8, "str": 8}, xp=8, gifts=["vit"])
    assert {"char_uid": "c1", "action": "spend_xp", "stat": "vit"} in bot.on_frame(_village_frame1(gift))
    nongift = _village_char(stats={"vit": 2, "end": 8, "str": 8}, xp=8, gifts=[])
    assert all(a.get("action") != "spend_xp" for a in bot.on_frame(_village_frame1(nongift)))


def test_village_no_xp_spend_when_stats_capped():
    bot = _bot()
    char = _village_char(stats={"vit": 8, "end": 8, "str": 8}, xp=9999)
    assert all(a.get("action") != "spend_xp" for a in bot.on_frame(_village_frame1(char)))


def _equip_char(inv, equipment=None, uid="c1"):
    return {"char_uid": uid, "hp": 30, "max_hp": 30, "inventory": inv,
            "equipment": equipment or {"hand": None, "offhand": None,
                                       "outfit": None, "trinket": None, "boots": None},
            "stats": {"vit": 1, "end": 1, "str": 1}, "gifts": [], "xp": 0}


def _vframe(char, gold=100, tick=3):
    return {"world": "village", "tick": tick,
            "guild": {"gold": gold, "chars_here": [char["char_uid"]], "chars_by_world": {}},
            "chars": [char]}


def test_village_equips_carried_gear_before_selling():
    bot = _bot()
    char = _equip_char([{"kind": "ore_copper", "item_id": "o1", "uses": []},
                        {"kind": "rusty_sword", "item_id": "w1", "uses": ["equip", "attack"]}])
    # must EQUIP the sword (not sell the ore first, and not leave the sword unworn)
    assert bot.on_frame(_vframe(char)) == \
        [{"char_uid": "c1", "action": "equip", "slot": "hand", "item_id": "w1"}]


def test_village_equips_into_empty_slot_when_hand_is_taken():
    bot = _bot()
    char = _equip_char([{"kind": "hide_vest", "item_id": "a1", "uses": ["equip"]}],
                       equipment={"hand": {"kind": "club"}, "offhand": None,
                                  "outfit": None, "trinket": None, "boots": None})
    # hand occupied -> it must probe the first EMPTY slot, not skip the armor
    assert bot.on_frame(_vframe(char)) == \
        [{"char_uid": "c1", "action": "equip", "slot": "offhand", "item_id": "a1"}]


def test_wrong_slot_is_learned_then_next_slot_tried():
    bot = _bot()
    char = _equip_char([{"kind": "hide_vest", "item_id": "a1", "uses": ["equip"]}])
    first = bot.on_frame(_vframe(char, tick=3))
    assert first[0]["slot"] == "hand"                    # first empty slot
    bot.strategy.on_action_error(bot, {"action": "equip", "char_uid": "c1",
                                       "reason": "wrong_slot"})
    # next frame is a later tick (past the v0.14.0 per-char village cooldown).
    second = bot.on_frame(_vframe(char, tick=12))
    assert second[0]["slot"] == "offhand"                # hand now known-wrong


def test_stat_requirement_marks_unusable_and_then_sells():
    bot = _bot()
    char = _equip_char([{"kind": "heavy_maul", "item_id": "m1", "uses": ["equip"]}])
    bot.on_frame(_vframe(char, tick=3))                  # attempt equip
    bot.strategy.on_action_error(bot, {"action": "equip", "char_uid": "c1",
                                       "reason": "stat_requirement"})
    # unusable now -> not re-equipped, and sold rather than hoarded (later tick,
    # past the v0.14.0 per-char village cooldown).
    assert bot.on_frame(_vframe(char, tick=12)) == \
        [{"char_uid": "c1", "action": "sell", "item_id": "m1"}]


def test_field_character_that_is_crafting_rests():
    bot = _bot()
    char = _field_char(craft={"kind": "brew", "ticks_left": 5})
    frame = _field_frame(char, FLOOR3,
                         entities=[{"pos": [1, 0], "faction": "monster",
                                    "kind": "rat_grey", "hp_frac": 0.2}])
    # busy crafting -> take no action (any action would error `crafting`)
    assert bot.on_frame(frame) == []


def _brew_char(inv, gold_stats_capped=True, **over):
    char = {"char_uid": "c1", "hp": 30, "max_hp": 30, "inventory": inv,
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None},
            "stats": {"vit": 8, "end": 8, "str": 8}, "gifts": [], "xp": 0}
    char.update(over)
    return char


def test_village_brews_ingredients_with_a_bottle():
    bot = _bot()
    # v0.8.0: a same-KIND batch (both bitterroot) shares an essence -> can't
    # curdle. (Mixing bitterroot+frostmoss, two different undecoded kinds, would
    # NOT brew now — see test_village_sells_stranded_singleton_brewable.)
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "bitterroot", "item_id": "b2", "uses": ["brew", "taste"]},
                       {"kind": "bottle_empty", "item_id": "bot1", "uses": []}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "brew", "item_ids": ["b1", "b2"]}]


def test_village_does_not_buy_a_bottle_in_gold_rush_hoard():
    # v0.24.0 hoard: bottle-buying is frozen too — a batch with no bottle on hand
    # does NOT trigger a purchase (brewing only proceeds with a bottle already held).
    bot = _bot()
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "bitterroot", "item_id": "b2", "uses": ["brew", "taste"]}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert all(not (a.get("action") == "buy" and a.get("kind") == "bottle_empty")
               for a in bot.on_frame(frame))


def test_village_keeps_ingredients_sells_food_and_loot():
    bot = _bot()
    # batchable brew ingredients listed FIRST so the test fails if _should_sell
    # stops keeping them (it would sell them before reaching the food). v0.19.0:
    # food is now SOLD as loot (was kept), so meat — the first sellable, after the
    # kept brewables — is what sells, proving the brewables were skipped.
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "bitterroot", "item_id": "b2", "uses": ["brew", "taste"]},
                       {"kind": "meat", "item_id": "m1", "uses": ["drink"]},
                       {"kind": "ore_copper", "item_id": "o1", "uses": ["forge"]}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    # gold 5 (<10) so no brew yet; the batchable brew ingredients are kept; food
    # (meat) and pure-loot ore are sold — meat first (it precedes the ore).
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "sell", "item_id": "m1"}]


def test_village_TASTES_an_undecoded_stranded_brewable_before_selling_it():
    """v0.81.0 amended the v0.8.0 contract, deliberately. A stranded singleton is still
    banked — but an UNDECODED one is worth more as an essence than as its ~2g sale, so the
    first of each kind goes to `taste` (destructive, once per kind per run) and only then
    do its kin sell as before. bitterroot has sat in knowledge.py's "resolve with taste
    first" comment since run #8; this is that taste finally happening."""
    bot = _bot()
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "frostmoss", "item_id": "f1", "uses": ["brew", "taste"]}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "taste", "item_id": "b1"}]


def test_village_still_SELLS_a_stranded_brewable_of_a_DECODED_kind():
    """The v0.8.0 rule survives for anything already decoded: a lone moonbell (venom,
    decoded run #8) has nothing left to teach, so it banks its gold as always."""
    bot = _bot()
    char = _brew_char([{"kind": "moonbell", "item_id": "m9", "uses": ["brew", "taste"]}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "sell", "item_id": "m9"}]


def test_a_kind_is_tasted_ONCE_then_its_kin_sell():
    """Taste is destructive; the second bitterroot must not feed a parser that may have
    missed the first result. Same character, two visits."""
    bot = _bot()
    def frame(tick, item_id):
        char = _brew_char([{"kind": "bitterroot", "item_id": item_id,
                            "uses": ["brew", "taste"]}])
        return {"world": "village", "tick": tick,
                "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
                "chars": [char]}
    assert bot.on_frame(frame(3, "b1"))[0]["action"] == "taste"
    acts = bot.on_frame(frame(30, "b2"))
    assert acts and acts[0]["action"] == "sell", f"tasted the same kind twice: {acts}"


def test_village_leaves_a_crafting_character_alone():
    bot = _bot()
    busy = {"char_uid": "c1", "craft": {"kind": "brew", "ticks_left": 7},
            "inventory": [], "equipment": {}, "stats": {}, "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 500, "chars_here": ["c1"],
                       "chars_by_world": {"vale": ["a", "b", "c", "d", "e"],
                                          "mines": ["f", "g", "h", "i", "j"]}},
             "chars": [busy]}
    # roster at world_cap and the only home char is busy -> no action (not sold,
    # not embarked, which would abandon the brew)
    assert bot.on_frame(frame) == []


def _idle_village_char(uid="c1", inv=None, gold_ok=True, **over):
    # armed + stats capped + full HP so every per-char step (equip/sell/buy/brew/
    # smelt/xp/heal) no-ops and control reaches the recruit/embark tail.
    char = {"char_uid": uid, "hp": 30, "max_hp": 30,
            "inventory": inv if inv is not None
            else [{"kind": "potion_red", "item_id": "p1", "tier": 1}],
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None},
            "stats": {"vit": 8, "end": 8, "str": 8}, "gifts": [], "xp": 0}
    char.update(over)
    return char


def _deploy_frame(here, by_world, chars, tick=3, gold=5):
    return {"world": "village", "tick": tick,
            "guild": {"gold": gold, "chars_here": here, "chars_by_world": by_world},
            "chars": chars}


def test_embark_is_not_resent_while_in_flight():
    # v0.10.0: the stale village frame still lists a just-embarked char in
    # chars_here for a few ticks. Without the in-flight guard the bot re-embarks
    # the SAME char every tick (1408 embarks / 28 chars in the 0.9.0 window) and
    # the tail bounces no_such_character once it finally leaves.
    bot = _bot()
    # roster 1 home + 9 fielded = 10 = cap -> no recruit; fielded 9 < world_cap
    # 10 and mines/spire empty -> the one home char embarks.
    frame = _deploy_frame(["c1"], {"vale": [f"v{i}" for i in range(9)]},
                          [_idle_village_char("c1")])
    first = bot.on_frame(frame)
    assert first and first[0]["action"] == "embark" and first[0]["char_uids"] == ["c1"]
    # same tick, same stale frame (c1 still shown home): must NOT re-embark it.
    second = bot.on_frame(frame)
    assert all(a.get("action") != "embark" for a in second)


def test_embark_retries_after_the_cooldown_elapses():
    # if the embark genuinely failed (char still home after EMBARK_COOLDOWN), we
    # retry rather than stranding it forever.
    from steemer.strategy.explorer import EMBARK_COOLDOWN
    bot = _bot()
    by_world = {"vale": [f"v{i}" for i in range(9)]}
    bot.on_frame(_deploy_frame(["c1"], by_world, [_idle_village_char("c1")], tick=3))
    later = bot.on_frame(_deploy_frame(["c1"], by_world, [_idle_village_char("c1")],
                                       tick=3 + EMBARK_COOLDOWN))
    assert later and later[0]["action"] == "embark" and later[0]["char_uids"] == ["c1"]


def test_embarks_any_available_char_to_fill_the_field():
    # v0.21.0 reverted the v0.20.0 armed-only filter (it emptied the field): a bare
    # char still fills a field slot and picks up loot, which beats an empty slot.
    # A bare char home with room in the field is embarked.
    bot = _bot()
    bare = _idle_village_char("c1", equipment={"hand": None, "offhand": None,
                              "outfit": None, "trinket": None, "boots": None})
    frame = _deploy_frame(["c1"], {"vale": [f"v{i}" for i in range(9)]}, [bare], gold=5)
    acts = bot.on_frame(frame)
    assert acts and acts[0]["action"] == "embark" and acts[0]["char_uids"] == ["c1"]


def test_embark_deploys_a_different_available_char_while_one_is_in_flight():
    # in-flight c1 shouldn't freeze deployment — a second home char still embarks.
    bot = _bot()
    by_world = {"vale": [f"v{i}" for i in range(8)]}   # fielded 8 -> room for two
    f1 = _deploy_frame(["c1", "c2"], by_world,
                       [_idle_village_char("c1"), _idle_village_char("c2")])
    first = bot.on_frame(f1)
    assert first[0]["char_uids"] == ["c1"]
    second = bot.on_frame(f1)          # c1 in flight -> c2 goes instead
    assert second and second[0]["action"] == "embark" and second[0]["char_uids"] == ["c2"]


def test_recruit_is_not_resent_within_the_cooldown():
    # v0.10.0: a just-recruited char isn't in the roster for a few frames; re-firing
    # recruit every tick storms roster_cap once at the cap.
    bot = _bot()
    frame = _deploy_frame([], {}, [])       # empty roster -> wants to recruit
    assert bot.on_frame(frame) == [{"action": "recruit"}]
    assert bot.on_frame(frame) == []        # cooldown holds the duplicate


def test_recruit_retries_after_the_cooldown_elapses():
    from steemer.strategy.explorer import RECRUIT_COOLDOWN
    bot = _bot()
    assert bot.on_frame(_deploy_frame([], {}, [], tick=3)) == [{"action": "recruit"}]
    assert bot.on_frame(_deploy_frame([], {}, [], tick=3 + RECRUIT_COOLDOWN)) == \
        [{"action": "recruit"}]


ORE = lambda iid: {"kind": "ore_copper", "item_id": iid, "uses": ["smelt"]}


def test_village_smelts_a_matching_pair_of_ore():
    # M3a: two matching ore -> one ingot. No bottle, no vocabulary needed.
    bot = _bot()
    char = _idle_village_char("c1", inv=[ORE("o1"), ORE("o2")])
    frame = _deploy_frame(["c1"], {}, [char])
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "smelt", "item_ids": ["o1", "o2"]}]


def test_village_keeps_a_smeltable_pair_rather_than_selling_it():
    # the paired ore must be KEPT (so it smelts), not sold as loot. If _should_sell
    # sold it, the sell step would fire first and this would be a `sell`, not `smelt`.
    bot = _bot()
    char = _idle_village_char("c1", inv=[ORE("o1"), ORE("o2")])
    acts = bot.on_frame(_deploy_frame(["c1"], {}, [char]))
    assert all(a.get("action") != "sell" for a in acts)
    assert acts and acts[0]["action"] == "smelt"


def test_village_KEEPS_a_stranded_single_ore_but_sells_the_surplus():
    """v0.59.0 REVERSED the v0.8.0 anti-clog rule for ore specifically.

    A lone ore cannot smelt, so the old rule banked it as stranded clutter — and run #135
    sold 5 `ore_copper` while the forge sat starved and vein-seek had broken 0 veins. A
    singleton of a scarce input is not clutter, it is HALF A PAIR; selling it guarantees it
    stays half a pair forever. The anti-clog intent is preserved by the per-kind cap, which
    is what the second half of this test pins."""
    from steemer.strategy.explorer import SCARCE_LONE_KEEP
    bot = _bot()
    char = _idle_village_char("c1", inv=[ORE("o1")])
    assert all(a.get("action") != "sell"
               for a in bot.on_frame(_deploy_frame(["c1"], {}, [char])))

    # The per-kind cap that preserves the anti-clog intent is asserted on the helper, not
    # through the village loop: with three matching ore a character SMELTS a pair instead,
    # which outranks selling, so the surplus branch is unreachable from here. The cap is a
    # bound on hoarding, not a behaviour the loop exhibits — say so rather than contrive a
    # frame that makes it look otherwise.
    from steemer.strategy.explorer import Explorer
    lots = [ORE(f"x{i}") for i in range(SCARCE_LONE_KEEP + 3)]
    assert len(Explorer._scarce_keep_ids(lots)) == SCARCE_LONE_KEEP


def test_village_smelts_only_the_matching_kind_not_a_mismatched_pair():
    # two DIFFERENT ores don't smelt (needs a matching pair); both are stranded.
    bot = _bot()
    char = _idle_village_char(
        "c1", inv=[{"kind": "ore_copper", "item_id": "o1", "uses": ["smelt"]},
                   {"kind": "ore_iron", "item_id": "o2", "uses": ["smelt"]}])
    acts = bot.on_frame(_deploy_frame(["c1"], {}, [char]))
    assert all(a.get("action") != "smelt" for a in acts)   # no mismatched smelt
    # v0.59.0: each is one of a scarce PAIR we are bottlenecked on, so neither is sold
    # any more. The subject of this test is the mismatched smelt above.
    assert all(a.get("action") != "sell" for a in acts)


class _FakeSpectate:
    """Stands in for bot.spectate — returns a fixed authoritative (total, {field
    world: n}, home) or None (stale/unavailable)."""
    def __init__(self, counts):
        self._counts = counts

    def counts(self):
        return self._counts


def test_gate_uses_the_authoritative_roster_over_the_frame_snapshot():
    # The frame snapshot says the village is EMPTY (snapshot roster 0 -> would
    # recruit), but the spectate endpoint says the roster is already at cap (10).
    # v0.11.0 must trust the authoritative count and NOT recruit.
    bot = _bot()
    bot.spectate = _FakeSpectate((10, {}, 10))     # total 10 == roster_cap 10
    assert all(a.get("action") != "recruit" for a in bot.on_frame(_deploy_frame([], {}, [])))


def test_gate_falls_back_to_the_snapshot_when_spectate_is_unavailable():
    # spectate stale/None -> behave exactly as 0.10.0 did (snapshot roster 0 < cap
    # -> recruit). Guards the fallback path.
    bot = _bot()
    bot.spectate = _FakeSpectate(None)
    assert bot.on_frame(_deploy_frame([], {}, [])) == [{"action": "recruit"}]


def test_embark_gates_on_the_fresh_frame_fielded_not_the_stale_spectate_count():
    # v0.11.1: spectate says only 1 fielded (would allow embark) but the FRESH
    # frame shows the field already at world_cap (10 on vale). Embark must gate on
    # the frame's per-tick distribution and NOT embark. (Guards the split that
    # fixed 0.11.0's stale-spectate world_cap blip.)
    bot = _bot()
    bot.spectate = _FakeSpectate((11, {"vale": 1}, 10))          # stale-low fielded
    char = _idle_village_char("c1")
    frame = _deploy_frame(["c1"], {"vale": [f"v{i}" for i in range(10)]}, [char])
    assert all(a.get("action") != "embark" for a in bot.on_frame(frame))


def test_embarks_a_home_char_toward_the_emptiest_map_from_the_frame_distribution():
    # roster at cap per spectate (no recruit), and the FRAME shows 4 on vale with
    # room under world_cap 10: the home char embarks toward the emptiest map
    # (mines/spire at 0) per the fresh frame per-world counts.
    bot = _bot()
    bot.spectate = _FakeSpectate((10, {"vale": 99}, 0))          # total at cap; its
    #   per-world is IGNORED for embark now — the frame's is used instead.
    char = _idle_village_char("c1")
    frame = _deploy_frame(["c1"], {"vale": [f"v{i}" for i in range(4)]}, [char])
    acts = bot.on_frame(frame)
    assert all(a.get("action") != "recruit" for a in acts)       # spectate total at cap
    assert any(a.get("action") == "embark" and a["char_uids"] == ["c1"]
               and a["map"] in ("mines", "spire") for a in acts)  # emptiest (0) map


def test_a_move_failed_EVENT_teaches_the_blocked_tile_and_stops_reissuing():
    # v0.12.0 wanted this: (0,1) is a north frontier, so the char pushes north; when that
    # move bounces the bot must learn (0,1) is blocked and stop re-issuing it (the freeze
    # that starved field productivity — one char sat at (43,3) for 40+ ticks "pushing
    # north" without moving).
    # v0.50.0 changed the EVIDENCE: the server's own `move_failed` event, which names the
    # character and the tile it could not enter, instead of inferring a bounce from an
    # unchanged position. See the test below for why that inference was fatal.
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]
    char = _field_char(pos=[0, 0], stamina=40)
    char["eid"] = 7

    def frame(tick, events=()):
        return {"world": "vale", "tick": tick, "chars": [dict(char)],
                "events": list(events),
                "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}

    a1 = bot.on_frame(frame(10))
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in a1        # pushes north
    a2 = bot.on_frame(frame(11, events=[
        {"kind": "move_failed", "eid": 7, "pos": [0, 0], "to": [0, 1]}]))
    assert (0, 1) in bot._learned_blocked["vale"]                        # learned it
    assert all(not (x.get("action") == "move" and x.get("dir") == "N") for x in a2)


def test_an_UNCHANGED_POSITION_alone_does_NOT_block_the_tile():
    """THE regression, and it killed two characters on 2026-08-21.

    Frames are stale, so "the character is where it was" is NOT evidence that its move
    bounced. The old code blacklisted on exactly that, and three stale frames in a row
    sealed every exit: Recruit-15469 (vale, tick 1413613) tried S, E then W, had (7,35),
    (8,36) and (6,36) blacklisted for STUCK_BLOCK_TTL with a crab_green on the fourth
    side, and then rested for ten ticks and bled out at 56/56 stamina with `rest` (0.5)
    the only offer left. v0.42.0 had closed the `not_enough_stamina` path; this is the
    no-error-at-all path, and there were zero errors in either fatal window.
    """
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]
    char = _field_char(pos=[0, 0], stamina=40)
    char["eid"] = 7

    def frame(tick):
        return {"world": "vale", "tick": tick, "chars": [dict(char)], "events": [],
                "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}

    bot.on_frame(frame(10))            # issues move N
    bot.on_frame(frame(11))            # same position, and NO move_failed event
    bot.on_frame(frame(12))            # ...still, twice over
    assert bot._learned_blocked.get("vale", {}) == {}, (
        "a stale frame was mistaken for a bounce — this is what entombs a hurt character")


def test_a_move_failed_for_a_DIFFERENT_entity_is_ignored():
    """move_failed fires for rivals and mobs too; blocking on theirs would poison our map
    with tiles that are perfectly walkable for us."""
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]
    char = _field_char(pos=[0, 0], stamina=40)
    char["eid"] = 7
    bot.on_frame({"world": "vale", "tick": 10, "chars": [dict(char)],
                  "events": [{"kind": "move_failed", "eid": 999, "pos": [5, 5],
                              "to": [0, 1]}],
                  "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    assert (0, 1) not in bot._learned_blocked.get("vale", {})


def test_learned_block_does_not_fire_when_the_char_actually_moved():
    # a char that DID move must not have its destination marked blocked.
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]

    def frame(tick, pos):
        return {"world": "vale", "tick": tick, "events": [],
                "chars": [_field_char(pos=pos, stamina=40)],
                "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}

    bot.on_frame(frame(10, [0, 0]))          # issues move N toward (0,1)
    bot.on_frame(frame(11, [0, 1]))          # it moved to (0,1) — success, not a bounce
    assert (0, 1) not in bot._learned_blocked.get("vale", {})


def test_decisions_are_persisted(tmp_path):
    s = Storage(str(tmp_path / "d.db"), commit_every=1)
    bot = _bot(storage=s)
    bot.on_frame(_field_frame(_field_char(), FLOOR3,
                 entities=[{"pos": [1, 0], "faction": "monster",
                            "kind": "rat_grey", "hp_frac": 0.5}]))
    row = s.conn.execute(
        "SELECT char_uid, action, reasoning FROM decisions").fetchone()
    assert row[0] == "c1" and row[1] == "attack"
    assert "attack adjacent" in row[2]     # the verbose reasoning was stored
    s.close()


_SHOP = {"stock": [
    {"kind": "club", "buy_price": 15, "sell_price": 3},
    {"kind": "dagger", "buy_price": 20, "sell_price": 4},
    {"kind": "shortsword", "buy_price": 45, "sell_price": 9, "req": {"str": 4}},
    {"kind": "potion_red", "buy_price": 20, "sell_price": 4}]}


def _barehand_frame(gold, str_=1, potions=0, armed=False):
    # v0.40.0: the weapon-buy is unfrozen, and a bare char above the gold floor arms BEFORE
    # buying a potion (arm-first precedence). Potion-reserve tests pass armed=True to isolate
    # the potion path from the new arm-up.
    hand = {"kind": "club"} if armed else None
    char = {"char_uid": "c1", "hp": 30, "max_hp": 30,
            "inventory": [{"kind": "potion_red", "item_id": f"p{i}", "tier": 1} for i in range(potions)],
            "equipment": {"hand": hand, "offhand": None, "outfit": None, "trinket": None, "boots": None},
            "stats": {"str": str_, "vit": 8, "end": 8}, "gifts": [], "xp": 0}
    return {"world": "village", "tick": 3, "shop": _SHOP,
            "guild": {"gold": gold, "chars_here": ["c1"], "chars_by_world": {}}, "chars": [char]}


def test_bare_handed_char_with_full_shop_hoards_and_buys_no_weapon():
    # v0.28.0 freeze, full shop (club 15 / dagger / shortsword 45 all in stock):
    # an affordable bare char buys NONE of them — proving the freeze covers every
    # weapon kind, not just the club. (Superseded v0.13.0's arm-with-the-club.)
    bot = _bot()
    assert all(a.get("action") != "buy" for a in bot.on_frame(_barehand_frame(15)))


def test_broke_char_below_cheapest_weapon_buys_nothing():
    bot = _bot()
    assert all(a.get("action") != "buy" for a in bot.on_frame(_barehand_frame(14)))


def test_hoard_buys_neither_weapon_nor_potion_while_bare_handed():
    # v0.28.0 + v0.29.0: at gold 20 the old logic would arm (weapon before potion);
    # now the weapon-buy is frozen (0.28.0) and the potion-buy is gated on
    # POTION_RESERVE (0.29.0) — 20 - 20 = 0 is far below the 100 reserve — so a bare
    # char at 20g buys nothing at all; every coin stays in the treasury.
    bot = _bot()
    assert all(a.get("action") != "buy" for a in bot.on_frame(_barehand_frame(20)))


def test_village_heals_a_potionless_char_only_above_the_reserve():
    # v0.29.0 heal-from-surplus, reserve-relative (v0.35.0 raised POTION_RESERVE to 600
    # to uncap the stockpile): once the hoard clears the reserve (gold - 20 >= reserve),
    # a potion-less char tops up a field heal. Weapon-buy stays frozen, so the potion is
    # the only buy.
    from steemer.strategy.explorer import POTION_RESERVE
    bot = _bot()
    acts = bot.on_frame(_barehand_frame(POTION_RESERVE + 20, armed=True))
    assert acts == [{"char_uid": "c1", "action": "buy", "kind": "potion_red"}]


def test_village_holds_the_reserve_floor_and_skips_the_heal_below_it():
    # reserve floor, boundary: one gold short of surplus (reserve+19 - 20 < reserve) the
    # buy is skipped so the stockpile never dips below POTION_RESERVE. Mutation-guards the
    # off-by-one. v0.35.0: at the *live* 600 reserve the treasury (pinned ~100 by the old
    # 100 reserve) is now far below it, so the potion-buy stops consuming income and gold
    # can climb past the 529 cap-test.
    from steemer.strategy.explorer import POTION_RESERVE
    bot = _bot()
    assert all(a.get("action") != "buy" for a in bot.on_frame(_barehand_frame(POTION_RESERVE + 19, armed=True)))


def test_village_does_not_stockpile_a_second_potion():
    # v0.29.0 buys at most POTION_KEEP: a char already carrying its heal buys no more,
    # even with a huge surplus — the heal-buy is bounded, unlike the old club drain.
    bot = _bot()
    assert all(a.get("action") != "buy" for a in bot.on_frame(_barehand_frame(500, potions=1, armed=True)))


def test_afford_potion_respects_the_reserve():
    # Unit-test the gate directly: the potion is offered only when the buy leaves the
    # treasury at or above POTION_RESERVE (100), and the price is read from the shop.
    from steemer.strategy.explorer import Explorer, POTION_RESERVE
    frame = _barehand_frame(0)  # carries _SHOP with potion_red @ 20
    assert Explorer._afford_potion(frame, POTION_RESERVE + 20) == ("potion_red", 20)
    assert Explorer._afford_potion(frame, POTION_RESERVE + 19) is None


def test_afford_weapon_respects_the_stat_requirement():
    # The weapon-buy is frozen at the caller (v0.28.0), but the _afford_weapon
    # selection logic is still live (flip FREEZE_WEAPON_BUY to re-enable arming),
    # so test it directly: str 1 can't qualify for the shortsword (req str4) even
    # at gold 45 -> it picks the club, not the shortsword.
    from steemer.strategy.explorer import Explorer
    char = {"stats": {"str": 1, "vit": 8, "end": 8}, "gifts": []}
    frame = _barehand_frame(45, str_=1)
    assert Explorer._afford_weapon(char, frame, 45) == ("club", 15)


def test_village_action_re_send_guard_skips_a_recent_actor():
    # v0.14.0: a char that just issued a village action is skipped for the cooldown
    # so a stale frame doesn't make it re-issue the same buy/sell every tick (the
    # run-#38 storm: 250 buy + 148 sell actions for ~1 sale). roster is at cap here
    # so nothing recruits/embarks, isolating the per-char guard.
    from steemer.strategy.explorer import VILLAGE_ACTION_COOLDOWN
    bot = _bot()

    def frame(tick):
        return {"world": "village", "tick": tick,
                "guild": {"gold": 100, "chars_here": ["c1"],
                          "chars_by_world": {"vale": [f"v{i}" for i in range(10)]}},
                "chars": [{"char_uid": "c1", "hp": 30, "max_hp": 30,
                           # pure loot; `bone` is a kept vigor herb since v0.59.0
                           "inventory": [{"kind": "tomato", "item_id": "i1", "uses": []}],
                           "equipment": {"hand": {"kind": "club"}, "offhand": None,
                                         "outfit": None, "trinket": None, "boots": None},
                           "stats": {"vit": 8, "end": 8, "str": 8}, "gifts": [], "xp": 0}]}

    assert bot.on_frame(frame(3)) == [{"char_uid": "c1", "action": "sell", "item_id": "i1"}]
    assert bot.on_frame(frame(4)) == []                          # within cooldown -> skipped
    assert bot.on_frame(frame(3 + VILLAGE_ACTION_COOLDOWN)) == \
        [{"char_uid": "c1", "action": "sell", "item_id": "i1"}]   # cooldown elapsed -> retries


# --- v0.41.0 COMBAT-SEEK: now that chars arm (0.40), a DEVELOP-mode char (armed + comfortably
# healthy + stamina) EARNS XP by fighting beatable mobs instead of always fleeing. Two safe
# engagements: (A) fight a LONE melee predator that came adjacent (override the dodge) and
# (B) actively SEEK benign wildlife (0-dmg) to farm free XP. Never a swarm, never undead. ---
_FIGHT_TILES = [[0, 0, "floor"], [1, 0, "floor"], [0, 1, "floor"]]


def _armed(**over):
    """A field char carrying a hand weapon (the develop-mode prerequisite)."""
    c = _field_char(equipment={"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                               "trinket": None, "boots": None})
    c.update(over)
    return c


def test_develop_char_fights_a_lone_adjacent_predator_for_xp():
    # armed + full HP + a LONE wolf adjacent -> ATTACK it for XP, overriding the dodge below.
    bot = _bot()
    frame = _field_frame(_armed(), _FIGHT_TILES,
        entities=[{"pos": [1, 0], "faction": "monster", "kind": "wolf", "hp_frac": 0.6}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [1, 0]} in acts


def test_bare_char_dodges_the_predator_instead_of_fighting():
    # SAME setup but BARE (no weapon) -> not develop-mode -> dodges away, never attacks. The
    # mutation guard on the develop gate: unarm the char and the fight must vanish.
    bot = _bot()
    frame = _field_frame(_field_char(), _FIGHT_TILES,
        entities=[{"pos": [1, 0], "faction": "monster", "kind": "wolf", "hp_frac": 0.6}])
    acts = bot.on_frame(frame)
    assert all(a.get("action") != "attack" for a in acts)
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in acts     # dodges to (0,1)


def test_lightly_hurt_armed_char_dodges_not_fights():
    # armed but at 63% HP (below DEVELOP_HP 0.7, above the 0.6 retreat line) -> not develop -> it
    # dodges rather than pick a fight it might not finish before it has to retreat.
    bot = _bot()
    frame = _field_frame(_armed(hp=19, max_hp=30), _FIGHT_TILES,
        entities=[{"pos": [1, 0], "faction": "monster", "kind": "wolf", "hp_frac": 0.6}])
    acts = bot.on_frame(frame)
    assert all(a.get("action") != "attack" for a in acts)


def test_develop_char_does_not_fight_a_predator_swarm():
    # armed + healthy but TWO melee predators within reach -> a swarm -> combat-seek is skipped
    # and the char dodges/flees instead of trading hits it can't win against two.
    bot = _bot()
    tiles = [[0, 0, "floor"], [1, 0, "floor"], [2, 0, "floor"], [0, 1, "floor"]]
    frame = _field_frame(_armed(), tiles, entities=[
        {"pos": [1, 0], "faction": "monster", "kind": "wolf", "hp_frac": 0.6},
        {"pos": [2, 0], "faction": "monster", "kind": "wolf", "hp_frac": 0.6}])
    acts = bot.on_frame(frame)
    assert all(a.get("action") != "attack" for a in acts)


def test_develop_char_seeks_out_wildlife_to_farm_xp():
    # armed + healthy, a benign chicken 2 tiles SOUTH, a north frontier open. The char CLOSES on
    # the chicken (moves S toward being adjacent) rather than pushing the frontier — free XP.
    bot = _bot()
    tiles = [[0, 1, "floor"], [0, 2, "floor"], [0, 3, "floor"], [0, 4, "floor"]]
    frame = _field_frame(_armed(pos=[0, 3]), tiles,
        entities=[{"pos": [0, 1], "faction": "monster", "kind": "chicken", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts     # closing on the chicken


def test_bare_char_does_not_seek_wildlife():
    # SAME geometry but BARE -> no develop-mode seek; it pushes the NORTH frontier instead of the
    # chicken to the south. Mutation guard on block (B): the seek is gated on the weapon.
    bot = _bot()
    tiles = [[0, 1, "floor"], [0, 2, "floor"], [0, 3, "floor"], [0, 4, "floor"]]
    frame = _field_frame(_field_char(pos=[0, 3]), tiles,
        entities=[{"pos": [0, 1], "faction": "monster", "kind": "chicken", "hp_frac": 1.0}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in acts     # frontier north
    assert {"char_uid": "c1", "action": "move", "dir": "S"} not in acts


# --- v0.42.0 DESPERATION ESCAPE: a hurt char boxed in by a predator pack (its strike-range
# tiles all blocked) whose only clear neighbour is UNKNOWN terrain used to REST and bleed out
# (is_walkable refuses unseen tiles). Now it takes the desperation step — strictly better than
# resting to death. Traced from run #99's vale wolf-swarm cluster (3 foragers died this way). ---

def _cornered_hurt_frame(south_terr=None):
    # char at (2,2), hp 5/30 (hurt), no potion. Wolves at (2,4)/(4,2)/(0,2) put N/E/W in the
    # predator strike-block; S=(2,1) is the only clear tile. south_terr=None leaves S UNKNOWN
    # (the real death case); "wall" makes S a known solid (the guard case).
    char = _field_char(pos=[2, 2], hp=5, max_hp=30, stamina=40, inventory=[])
    tiles = [[2, 2, "floor"]]
    if south_terr is not None:
        tiles.append([2, 1, south_terr])
    ents = [{"pos": p, "faction": "monster", "kind": "wolf", "hp_frac": 0.8}
            for p in ([2, 4], [4, 2], [0, 2])]
    return _field_frame(char, tiles, entities=ents)


def test_hurt_cornered_char_takes_the_desperation_step_onto_a_clear_unknown_tile():
    # N/E/W are predator-strike-blocked, S is clear but unseen -> step S instead of resting.
    bot = _bot()
    acts = bot.on_frame(_cornered_hurt_frame(south_terr=None))
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts


def test_desperation_never_steps_onto_a_known_wall():
    # SAME corner but the only clear tile S is a KNOWN wall -> no candidate -> the char rests
    # (emits no move). Guard on the SOLID check: without it, desperation would step into a wall.
    bot = _bot()
    acts = bot.on_frame(_cornered_hurt_frame(south_terr="wall"))
    assert all(a.get("action") != "move" for a in acts)


def test_hurt_char_with_a_known_escape_still_retreats_normally():
    # regression: a hurt char NOT boxed in (a known floor corridor home) still walks home via the
    # normal retreat — the desperation block doesn't suppress or replace ordinary hurt-retreat.
    bot = _bot()
    char = _field_char(pos=[2, 2], hp=5, max_hp=30, stamina=40, inventory=[])
    tiles = [[2, 0, "floor"], [2, 1, "floor"], [2, 2, "floor"]]
    acts = bot.on_frame(_field_frame(char, tiles))
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in acts     # heading home


def test_stamina_bounce_does_not_learn_block_a_walkable_tile():
    # v0.42.0 ROOT FIX: a move that bounces with not_enough_stamina (transient — the
    # frame-staleness margin, the tile is fine) must NOT blacklist the tile. Blacklisting
    # it for STUCK_BLOCK_TTL walled hurt chars into dead-ends and killed them (run #99:
    # 9687 stamina errors vs ~0 wall errors). The char still sees (0,1) as usable.
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]

    def frame(tick):
        return {"world": "vale", "tick": tick,
                "chars": [_field_char(pos=[0, 0], stamina=40)],
                "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}

    a1 = bot.on_frame(frame(10))
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in a1          # pushes north to (0,1)
    # the server rejected that move for stamina (mirrors the live error stream)
    bot.on_action_error({"action": "move", "char_uid": "c1",
                         "reason": "not_enough_stamina", "tick": 10})
    a2 = bot.on_frame(frame(11))                                            # still at (0,0)
    assert (0, 1) not in bot._learned_blocked.get("vale", {})              # NOT blacklisted
    assert {"char_uid": "c1", "action": "move", "dir": "N"} in a2          # still free to use it


# --- v0.43.0 recruit-burst fix: a post-deploy roster-count lag (the public spectate endpoint
# froze at 9 for ~176 ticks on run #100 while the real roster was ~30) made the gate recruit
# every cooldown, overshooting the fieldable cap into a ~20-char bare bench. Fix: max(auth,
# fresh snapshot) + count our own in-flight recruits so a lagging count can't drive a burst. ---

def _village_frame(tick, n_here, gold=5, by_world=None):
    return {"world": "village", "tick": tick,
            "guild": {"gold": gold, "chars_here": [f"h{i}" for i in range(n_here)],
                      "chars_by_world": by_world or {}},
            "chars": []}


def test_recruit_burst_is_capped_when_the_roster_count_lags():
    # target = min(world_cap 10, roster_cap 10, 5*3+2) = 10. The count reads 9 and STAYS 9 (the
    # just-recruited char hasn't checked in — the run #100 lag). The in-flight counter must cap
    # recruiting at ONE until the count rises or RECRUIT_INFLIGHT_TTL elapses — not a burst.
    bot = _bot()
    assert any(a.get("action") == "recruit" for a in bot.on_frame(_village_frame(10, 9)))  # 9<10
    for t in (20, 30, 40, 50, 60):
        acts = bot.on_frame(_village_frame(t, 9))     # count still 9, recruit in-flight
        assert all(a.get("action") != "recruit" for a in acts), f"burst not capped at t={t}"


def test_recruit_resumes_after_the_inflight_recruit_lands():
    # once the recruited char shows in the count (9 -> 10) OR the in-flight entry ages out, the
    # gate is free to act on the true count again — it must NOT be permanently frozen.
    bot = _bot()
    bot.on_frame(_village_frame(10, 9))               # recruit -> inflight
    # count now genuinely reflects 10 (== target): no recruit, correctly at cap
    assert all(a.get("action") != "recruit" for a in bot.on_frame(_village_frame(20, 10)))


class _StaleSpectate:
    def counts(self):
        return (9, {}, 0)                              # frozen-low authoritative total


def test_recruit_uses_the_fresh_snapshot_when_the_spectate_count_is_stale():
    # the authoritative spectate total lagged our post-deploy roster (frozen at 9). The gate must
    # take the MAX with the fresh frame snapshot, so a stale-low auth can't drive over-recruiting
    # when the snapshot already shows we're over the cap. Mutation guard on the max().
    bot = _bot()
    bot.spectate = _StaleSpectate()
    frame = _village_frame(10, 0, by_world={"vale": [f"v{i}" for i in range(12)]})  # 12 fielded
    assert all(a.get("action") != "recruit" for a in bot.on_frame(frame))   # max(9,12)=12 > 10


# --- v0.44.0 FORGE-TO-ARM probe (slice 1): opportunistic terrain harvest. A safe char adjacent
# to a breakable resource tile (tree/vein) attacks it to harvest lumber/ore — the raw-materials
# layer we'd ignored as scenery. Adjacent-only, scored below real gathering. ---

def test_harvests_an_adjacent_tree_for_materials():
    bot = _bot()
    frame = _field_frame(_field_char(pos=[0, 0]), [[0, 0, "floor"], [0, 1, "tree"]])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [0, 1]} in acts   # chops the tree


def test_no_harvest_when_no_resource_is_adjacent():
    bot = _bot()
    frame = _field_frame(_field_char(pos=[0, 0]), [[0, 0, "floor"], [0, 1, "floor"]])
    acts = bot.on_frame(frame)
    assert all(a.get("action") != "attack" for a in acts)     # nothing to harvest


def test_harvest_yields_to_real_loot_underfoot():
    # loot underfoot (6.0) beats the harvest (3.3): materials only when nothing better is here.
    bot = _bot()
    frame = _field_frame(_field_char(pos=[0, 0]), [[0, 0, "floor"], [0, 1, "tree"]],
                         items=[{"pos": [0, 0], "kind": "egg"}])
    acts = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "pickup"} in acts
    assert {"char_uid": "c1", "action": "attack", "target": [0, 1]} not in acts


def test_a_hurt_char_with_free_floor_is_never_left_with_only_REST():
    """The lethal symptom, asserted directly rather than via its cause.

    Both deaths on 2026-08-21 look identical in the trace: a hurt character at FULL
    stamina, walkable floor beside it, and `rest` (0.5) as the ONLY weighed option —
    retreat (8.5) and the desperation escape (8.0) both silent because every neighbour had
    been blacklisted. Whatever the mechanism, a hurt character with somewhere to go must
    always be offered somewhere to go.
    """
    bot = _bot()
    # open floor all around, one predator to the north, character hurt and at full stamina
    tiles = [[x, y, "floor"] for x in range(-1, 2) for y in range(-1, 2)]
    char = _field_char(pos=[0, 0], stamina=56)
    char.update(hp=6, max_hp=30, eid=7)
    frame = {"world": "vale", "tick": 10, "chars": [char], "events": [],
             "visible": {"tiles": tiles, "items": [], "gold": [],
                         "entities": [{"pos": [0, 1], "faction": "monster",
                                       "kind": "crab_green", "hp_frac": 1.0}]}}
    actions = bot.on_frame(frame)
    mine = [a for a in actions if a.get("char_uid") == "c1"]
    assert mine, "a hurt character with free floor was offered nothing but rest"
    assert mine[0].get("action") == "move", mine
    assert mine[0].get("dir") != "N", "stepped INTO the predator"


def test_a_learned_block_EXPIRES_so_a_temporarily_occupied_tile_is_not_dead_forever():
    """Blocks must age out. A tile is often unenterable only because another character or
    a mob is standing on it this instant; keeping it blacklisted permanently would shrink
    the walkable map every time anything got in the way."""
    from steemer.bot import STUCK_BLOCK_TTL
    bot = _bot()
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]
    char = _field_char(pos=[0, 0], stamina=40)
    char["eid"] = 7

    def frame(tick, events=()):
        return {"world": "vale", "tick": tick, "chars": [dict(char)],
                "events": list(events),
                "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}

    bot.on_frame(frame(10, events=[{"kind": "move_failed", "eid": 7,
                                    "pos": [0, 0], "to": [0, 1]}]))
    assert (0, 1) in bot._learned_blocked["vale"]
    bot.on_frame(frame(10 + STUCK_BLOCK_TTL - 1))
    assert (0, 1) in bot._learned_blocked["vale"], "expired too early"
    bot.on_frame(frame(10 + STUCK_BLOCK_TTL))
    assert (0, 1) not in bot._learned_blocked["vale"], "never expired"


def test_the_DESPERATION_escape_fires_when_the_retreat_has_nowhere_known_to_go():
    """Isolates the last-resort branch, which the test above does NOT reach (there the
    retreat at 8.5 answers first, so it would pass even with desperation scored below
    rest — a mutant proved exactly that).

    Here the only KNOWN tile is the character's own: the homeward route is unknown ground,
    so the retreat finds no walkable step and must hand over to the desperation escape,
    which is allowed to step onto a clear unseen tile. That is the branch standing between
    a cornered, bleeding character and resting to death.
    """
    bot = _bot()
    char = _field_char(pos=[0, 5], stamina=56)
    char.update(hp=5, max_hp=30, eid=7)
    frame = {"world": "vale", "tick": 10, "chars": [char], "events": [],
             "visible": {"tiles": [[0, 5, "floor"]],      # nothing else is known ground
                         "entities": [], "items": [], "gold": []}}
    actions = bot.on_frame(frame)
    mine = [a for a in actions if a.get("char_uid") == "c1"]
    assert mine and mine[0].get("action") == "move", (
        "cornered on unknown ground with nowhere KNOWN to retreat, the character was left "
        "to rest and bleed out")
