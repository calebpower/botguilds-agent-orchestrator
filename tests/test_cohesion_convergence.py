"""v0.72.0 — a rally must converge; chasing the nearest ally does not.

Run #150, the largest single waste this project has measured: **cohesion was 25% of ALL
decisions** and achieved nothing. Characters closed on the NEAREST ALLY, which is mutual
pursuit — everyone chasing a target that is itself chasing something else.

  * one character logged 482 consecutive cohesion decisions, ally distance reading
    13, 9, 8, 7, 6, 8, 8, 6, 8 — never reaching COHESION_HOLD=2
  * at tick 1769538 four characters were all "closing", two walking north and two south,
    every one of them reporting a distance of 7
  * another spent the run chasing an ally 19 tiles away: 19, 18, 17, 19, 19, 17

With rest at ~47%, roughly 72% of decisions were producing no progress at all.

The centre of the group is a FIXED POINT for the tick, so every character targets the same
tile and the spread shrinks monotonically. That is the difference between a rally and a
chase.

What these tests do NOT prove: that forming up is worth doing. v0.48.0 argued that on
survival grounds and this change does not revisit it — only that when we do it, it ends.
"""
from steemer.strategy.base import FieldContext
from steemer.strategy.explorer import Explorer, COHESION_HOLD


def _ctx(w=60, h=60):
    return FieldContext(world="vale", known={(x, y): "floor"
                                             for x in range(w) for y in range(h)})


def _step(pos, allies, ctx=None):
    return Explorer._cohesion_step(pos, allies, ctx or _ctx(), set())


def _simulate(starts, rounds=60):
    """Every character moves toward the rally each tick, as the live loop would."""
    ctx = _ctx()
    pos = list(starts)
    for _ in range(rounds):
        nxt = []
        for i, p in enumerate(pos):
            others = [q for j, q in enumerate(pos) if j != i]
            s = _step(p, others, ctx)
            nxt.append(s or p)
        if nxt == pos:
            break
        pos = nxt
    return pos


def _spread(pos):
    return max(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a in pos for b in pos)


# ---- it converges ------------------------------------------------------------

def test_a_scattered_group_actually_gathers():
    """The whole point. Under the old nearest-ally rule these characters traded places
    forever; the run-#150 traces are four of them oscillating at distance 7."""
    start = [(2, 2), (30, 4), (6, 28), (28, 30)]
    assert _spread(start) > 20
    end = _simulate(start)
    # Tight, not merely "closer": an arbitrary per-character rally point (say, each
    # character's first ally) also shrinks the spread somewhat, and a loose bound would
    # accept it. A real rally ends with everyone within a couple of tiles of one place.
    assert _spread(end) <= 4, f"still scattered: {end}"


def test_the_run_150_oscillation_settles():
    """Modelled on the actual trace, because two characters are not enough to show it —
    a pair under the old rule walk toward each other and do converge. The failure needs
    THREE OR MORE, where each one's nearest ally is someone else's chaser. At tick
    1769538 four characters were all "closing" at distance 7, two heading north and two
    south, and the group never tightened.
    """
    start = [(10, 10), (10, 17), (17, 10), (17, 17)]
    end = _simulate(start, rounds=80)
    assert _spread(end) <= 4, f"still trading places: {end}"


def test_two_characters_meet():
    end = _simulate([(0, 0), (14, 0)])
    assert _spread(end) <= 4, f"oscillating: {end}"


def test_the_group_settles_and_stops_moving():
    """A rally that never ends is just a slower chase — it must terminate, or cohesion
    keeps outranking ore-seeking (2.8 vs 2.7) for the rest of the run."""
    settled = _simulate([(4, 4), (10, 4), (7, 10)], rounds=80)
    again = _simulate(settled, rounds=5)
    assert again == settled, "still shuffling once gathered"


def test_they_meet_IN_THE_MIDDLE_not_wherever_one_character_happens_to_stand():
    """Convergence alone does not distinguish a rally from a pile-on: everyone walking to
    one arbitrary member also converges. What separates them is WHERE, and therefore how
    much walking the group does in total — and walking is the scarce resource here, since
    a move costs ~15 stamina against 10-12 regen per tick.

    Two tight clusters 40 apart must meet near the midpoint, each travelling about half,
    rather than one cluster marching the whole way."""
    left = [(0, 10), (1, 10), (0, 11)]
    right = [(40, 10), (41, 10), (40, 11)]
    end = _simulate(left + right, rounds=120)
    mid_x = sum(p[0] for p in end) / len(end)
    assert 14 <= mid_x <= 26, f"met at x={mid_x:.1f}, not near the midpoint 20"
    assert _spread(end) <= 6, f"did not gather: {end}"


def test_a_distant_straggler_still_closes():
    """Run #150 had a character chasing an ally 19 tiles away and never gaining."""
    end = _simulate([(0, 0), (1, 1), (2, 0), (30, 30)])
    assert _spread(end) < 20


# ---- the stopping rule -------------------------------------------------------

def test_a_character_already_at_the_centre_does_not_move():
    assert _step((10, 10), [(9, 10), (11, 10), (10, 9)]) is None


def test_the_centre_is_the_MEAN_not_the_nearest_ally():
    """A character between a near ally and a far cluster must walk toward the CLUSTER.
    Under the old rule it stopped at the near ally and the group never merged."""
    step = _step((0, 0), [(1, 0), (20, 0), (20, 1), (20, 2)])
    assert step is not None and step[0] > 0, f"walked away from the group: {step}"


def test_no_allies_means_no_rally():
    assert _step((5, 5), []) is None


def test_the_hold_radius_is_respected():
    """Within COHESION_HOLD of the centre is close enough — otherwise characters jostle
    for the exact centre tile, which is occupied by whoever got there first."""
    allies = [(10, 10), (10, 12)]
    assert _step((10, 11 + COHESION_HOLD), allies) is None
