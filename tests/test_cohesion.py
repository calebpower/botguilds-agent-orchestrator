"""v0.48.0 — adaptive cohesion: form up in dangerous worlds, stay spread in safe ones.

Built on measurements taken first (see the module comment in explorer.py): a second
attacker roughly doubles damage output while the party's incoming damage per tick stays
flat, so per-member damage taken halves. XP is SPLIT, so this is not an XP multiplier —
the case is survivability, which is what buys access to content worth more XP.

The tests below pin the three things most likely to go wrong, in the order they would
bite: cohering in the WRONG world (which would collapse our gathering economy), losing to
predator-spacing (which would walk a character into a mob to reach a friend), and
oscillating between two characters each closing on the other.
"""
from steemer.strategy.base import FieldContext
from steemer.strategy.explorer import (Explorer, COHESION_SCORE, COHESION_PULL,
                                       COHESION_HOLD, COHESION_PRED_DENSE,
                                       SPACE_SCORE_SEVERE, SPACE_SCORE_CALM,
                                       UNDEAD_SEVERE_GUARDIAN, THREAT_TTL)


def _open_known(w=30, h=30):
    return {(x, y): "floor" for x in range(w) for y in range(h)}


# ---- the world gate: WHERE we cohere -----------------------------------------

def test_an_unscouted_world_does_NOT_cohere():
    """The default must be DISPERSE. A world we have not seen cannot be allowed to
    silently collapse the roster onto one tile — dispersal is our gathering economy."""
    exp = Explorer()
    assert exp._world_is_dangerous("mines", tick=100) is False


def test_a_wildlife_world_does_NOT_cohere():
    """vale: no undead, few melee predators — 4.93 char-deaths/1k frames and where our
    income comes from. Cohering here would cost coverage for nothing."""
    exp = Explorer()
    exp._world_danger["vale"] = (0.0, 1, 100)
    assert exp._world_is_dangerous("vale", tick=110) is False


def test_a_melee_DENSE_world_coheres_even_with_zero_undead():
    """The mines are the case that motivated a second signal: bats/rats/moles/delvers are
    melee predators, not undead, so the pre-existing `_world_threat` (undead-only, built
    for safe-world routing) reads ~0 there — and cohering on it alone would leave us
    dispersed in exactly the world we most want to raid."""
    exp = Explorer()
    exp._world_danger["mines"] = (0.0, COHESION_PRED_DENSE, 100)
    assert exp._world_is_dangerous("mines", tick=110) is True


def test_an_UNDEAD_world_coheres_even_with_few_predators():
    """spire: all undead, 6.64 deaths/1k and the hardest hitters."""
    exp = Explorer()
    exp._world_danger["spire"] = (UNDEAD_SEVERE_GUARDIAN, 0, 100)
    assert exp._world_is_dangerous("spire", tick=110) is True


def test_a_STALE_reading_stops_cohering():
    """An emptied world must be re-scouted rather than trusted forever — the same TTL
    discipline `_world_threat` already uses for safe-world routing."""
    exp = Explorer()
    exp._world_danger["mines"] = (0.9, 9, 100)
    assert exp._world_is_dangerous("mines", tick=100 + THREAT_TTL) is False
    assert exp._world_is_dangerous("mines", tick=100 + THREAT_TTL - 1) is True


# ---- the step: HOW we close ---------------------------------------------------

def test_the_goal_is_PROXIMITY_not_the_ally_tile():
    """An ally's own tile is occupied and therefore blocked, so pathing to it would always
    fail and cohesion would never fire at all."""
    exp = Explorer()
    ctx = FieldContext(world="mines", known=_open_known())
    ally = (10, 10)
    step = exp._cohesion_step((10, 20), [ally], ctx, blocked={ally})
    assert step is not None
    assert abs(step[0] - 10) + abs(step[1] - 20) == 1        # exactly one step
    assert abs(step[1] - 10) < 10                            # ...and it is toward the ally


def test_no_step_when_already_close_enough():
    exp = Explorer()
    ctx = FieldContext(world="mines", known=_open_known())
    assert exp._cohesion_step((10, 10), [(10, 10 + COHESION_HOLD)], ctx, blocked=set()) is None


def test_no_step_when_the_ally_is_unreachable():
    """Walled off: cohesion must decline rather than thrash against the wall."""
    exp = Explorer()
    known = {(x, y): "floor" for x in range(5) for y in range(5)}
    known[(9, 9)] = "floor"                                   # island, no path
    ctx = FieldContext(world="mines", known=known)
    assert exp._cohesion_step((0, 0), [(9, 9)], ctx, blocked=set()) is None


# ---- ordering: cohesion must LOSE to danger -----------------------------------

def test_cohesion_scores_below_spacing_and_above_frontier():
    """The whole safety argument depends on this ordering. Above frontier (2.5) so idle
    characters actually close up; strictly below spacing (3.0) so a character never walks
    into a predator to reach a friend."""
    assert COHESION_SCORE > 2.5
    assert COHESION_SCORE < SPACE_SCORE_SEVERE
    assert COHESION_SCORE < 4.0            # below gathering
    assert SPACE_SCORE_CALM < COHESION_SCORE  # ...but it beats CALM-band spacing


def test_the_hysteresis_gap_exists():
    """Without a gap between the pull and hold thresholds, two characters each closing on
    the other oscillate across the boundary forever — and move_failed is where that shows
    up. v0.37's anti-stuck work is the precedent for how this goes wrong."""
    assert COHESION_PULL > COHESION_HOLD


# ---- wiring: the offer actually fires in act() --------------------------------

from steemer.bot import GuildBot     # noqa: E402


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    return b


def _char(uid, pos, **over):
    c = {"char_uid": uid, "pos": list(pos), "hp": 30, "max_hp": 30, "stamina": 40,
         "carry": {"used": 0, "cap": 20}, "inventory": [], "stats": {},
         "equipment": {"hand": {"kind": "club"}}}
    c.update(over)
    return c


def _frame(chars, world="mines", tick=10, w=14):
    tiles = [[x, y, "floor"] for x in range(w) for y in range(w)]
    return {"world": world, "tick": tick, "chars": chars,
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def _mark_dangerous(bot, world, tick):
    bot.strategy._world_danger[world] = (0.0, COHESION_PRED_DENSE, tick)


def test_a_separated_char_in_a_dangerous_world_MOVES_toward_its_ally():
    """The ally is placed WEST on purpose. The frontier push also moves north (scored 2.5),
    so an ally to the NORTH would make "moved north" ambiguous between cohesion and
    ordinary exploring — the first version of this test had exactly that hole. West is
    unambiguous: nothing else in the ladder sends an idle character that way.

    v0.73.0 moved the separated character from 10 tiles out to 6. Ten tiles is no longer a
    rally we start at all — beyond COHESION_RANGE it cannot finish inside a median field
    stint, so the character explores instead, which is the point of the change. The claim
    under test is unchanged: a separated character in a dangerous world closes on its ally.
    `test_cohesion_range.py` holds the other half — that a rally out of reach is declined."""
    bot = _bot()
    far, near = _char("c1", (6, 0)), _char("c2", (0, 0))
    _mark_dangerous(bot, "mines", 10)
    acts = bot.on_frame(_frame([far, near]))
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine and mine[0]["action"] == "move", mine
    assert mine[0]["dir"] == "W", f"expected to close WEST on the ally, got {mine[0]}"


def test_the_SAME_situation_in_a_safe_world_does_NOT_close_up():
    """The control: identical geometry, only the world's danger differs, so any difference
    in direction is the gate and not the layout."""
    bot = _bot()
    far, near = _char("c1", (10, 0)), _char("c2", (0, 0))
    acts = bot.on_frame(_frame([far, near], world="vale"))   # never marked dangerous
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine, "expected the character to do something"
    assert mine[0].get("dir") != "W", f"closed up in a SAFE world: {mine[0]}"


def test_a_HOMING_char_is_exempt():
    """A full character is committed to walking to the village to sell; diverting it to
    form up would re-create the embark<->return thrash v0.16.0's latch exists to stop."""
    bot = _bot()
    full = _char("c1", (10, 0), carry={"used": 19, "cap": 20})
    ally = _char("c2", (0, 0))
    _mark_dangerous(bot, "mines", 10)
    acts = bot.on_frame(_frame([full, ally]))
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine, "expected the homing character to act"
    assert mine[0].get("dir") != "W", f"a homing char was diverted to form up: {mine[0]}"


def test_a_lone_char_never_treats_ITSELF_as_an_ally():
    """Both halves of the claim. A character alone in a world must act normally rather than
    crash — and, more subtly, it must not count its own tile as an ally, which would make
    the gap 0 for everyone and quietly disable cohesion altogether. The second half is what
    the separated-char test above actually detects; this one covers the lone case."""
    bot = _bot()
    _mark_dangerous(bot, "mines", 10)
    acts = bot.on_frame(_frame([_char("c1", (5, 5))]))
    assert isinstance(acts, list) and acts
    assert bot.strategy._cohering == set(), "a lone char latched onto itself"


def test_danger_PERSISTS_when_a_char_later_sees_an_empty_view():
    """The flaw that made the first cut inert: danger was rewritten from the instantaneous
    view every tick, so a character standing somewhere quiet reset the world to "safe" on
    the spot — and a STANDING formation cannot exist if the signal collapses the moment
    nothing is in sight. Danger is the MAX within the TTL window."""
    bot = _bot()
    strat = bot.strategy
    # tick 10: a character sees predators
    strat._world_danger["mines"] = (0.0, COHESION_PRED_DENSE, 10)
    # tick 20: another character sees an entirely empty view of the same world
    bot.on_frame(_frame([_char("c1", (0, 0))], world="mines", tick=20))
    assert strat._world_is_dangerous("mines", tick=20) is True, strat._world_danger


def test_danger_still_AGES_OUT_so_an_emptied_world_is_re_scouted():
    """The other side: persistence must not become permanence, or a world cleared long ago
    would keep the roster bunched forever."""
    bot = _bot()
    strat = bot.strategy
    strat._world_danger["mines"] = (0.0, COHESION_PRED_DENSE, 10)
    assert strat._world_is_dangerous("mines", tick=10 + THREAT_TTL) is False


def test_a_QUIETER_look_does_not_lower_a_recent_danger_reading():
    """max, not last-write-wins: seeing one predator after seeing three must not downgrade
    the world."""
    bot = _bot()
    strat = bot.strategy
    strat._world_danger["mines"] = (0.5, 5, 10)
    bot.on_frame(_frame([_char("c1", (0, 0))], world="mines", tick=11))
    frac, preds, _ = strat._world_danger["mines"]
    assert frac == 0.5 and preds == 5, strat._world_danger["mines"]


# ---- v0.48.1: cohesion BIASES gathering instead of competing with it ----------

def _frame_loot(chars, loot, world="mines", tick=10, w=20):
    tiles = [[x, y, "floor"] for x in range(w) for y in range(w)]
    return {"world": world, "tick": tick, "chars": chars,
            "visible": {"tiles": tiles, "entities": [],
                        "items": [{"pos": list(p)} for p in loot], "gold": []}}


def test_out_of_position_it_walks_to_loot_NEAR_AN_ALLY():
    """0.48.0 shipped inert: cohesion was offered 28 times on run #116 and chosen 0,
    losing every tick to "moving toward loot" (4.0). Raising its score was the wrong fix —
    the ladder already puts gathering above spacing, so "below spacing" forces "below
    gathering". Instead the gather TARGET is biased, so we gather and form up at once.

    Two loot piles equidistant-ish from the character; only one is near the ally. It must
    choose that one, and it must still be a LOOT move, not a cohesion move — income intact.
    """
    bot = _bot()
    me, ally = _char("c1", (10, 10)), _char("c2", (2, 10))
    _mark_dangerous(bot, "mines", 10)
    acts = bot.on_frame(_frame_loot([me, ally], loot=[(3, 10), (17, 10)]))
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine and mine[0]["action"] == "move", mine
    assert mine[0]["dir"] == "W", f"went for the loot away from the ally: {mine[0]}"


def test_in_a_SAFE_world_it_takes_the_NEARER_loot_not_the_ally_side_one():
    """The control, and it must OFFER A CHOICE to mean anything: loot on both sides, the
    ally-side pile FARTHER. In a safe world the bias must not apply, so the character takes
    the nearer pile. The first version put loot only to the east, so removing the world
    gate changed nothing and a mutant survived."""
    bot = _bot()
    me, ally = _char("c1", (10, 10)), _char("c2", (2, 10))
    # west pile (3,10) is 7 away and beside the ally; east pile (13,10) is only 3 away
    acts = bot.on_frame(_frame_loot([me, ally], loot=[(3, 10), (13, 10)], world="vale"))
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine and mine[0].get("dir") == "E", f"biased toward the ally in a SAFE world: {mine}"


def test_a_gap_INSIDE_the_hysteresis_band_does_not_start_forming_up():
    """Exercises the gap between HOLD (2) and PULL (4), which nothing else did — every
    other test uses a gap far outside it, so a mutant collapsing the two thresholds into
    one survived. At gap 3, a character not already closing must NOT start."""
    bot = _bot()
    me, ally = _char("c1", (5, 10)), _char("c2", (2, 10))      # gap 3: HOLD < 3 < PULL
    _mark_dangerous(bot, "mines", 10)
    assert "c1" not in bot.strategy._cohering
    # ally-side pile (1,10) is 4 away; the east pile (7,10) is only 2 away
    acts = bot.on_frame(_frame_loot([me, ally], loot=[(1, 10), (7, 10)]))
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine and mine[0].get("dir") == "E", f"started forming up inside the band: {mine}"


def test_it_will_not_cross_the_map_to_form_up():
    """COHESION_DETOUR bounds the bias: ally-side loot that is very far away must not pull
    a character past everything nearer. Without the bound, forming up would cost real
    income on a large map."""
    bot = _bot()
    me, ally = _char("c1", (18, 10)), _char("c2", (0, 10))
    _mark_dangerous(bot, "mines", 10)
    # ally-side loot at (1,10) is 17 away — beyond COHESION_DETOUR; nearer loot sits east
    acts = bot.on_frame(_frame_loot([me, ally], loot=[(1, 10), (19, 10)]))
    mine = [a for a in acts if a.get("char_uid") == "c1"]
    assert mine and mine[0].get("dir") == "E", f"crossed the map to form up: {mine[0]}"
