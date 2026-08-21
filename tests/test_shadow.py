"""The shadow-evaluation gate (steemer.shadow).

This exists because a green test suite proved insufficient three times in one session: a
change can be correct, fully tested, and still never win a tick live. v0.46.0 stockpiled
feedstock for a forge that could not run; v0.48.0's cohesion was offered 28 times and
chosen ZERO, losing every tick to loot-seek. Both shipped green.

So the oracle here is INERTNESS, and it is self-tested from both sides: fed a candidate
whose new branch wins ticks it must approve, and fed one whose new branch never wins it
must refuse. A gate only ever observed approving is indistinguishable from one that cannot
refuse — which is exactly what the pytest suite was.
"""
from steemer.shadow import branch_of, tally, compare, verdict


def _alt(why, score=1.0, chosen=False):
    return {"action": "move", "score": score, "why": why, "chosen": chosen}


# ---- branch normalisation ----------------------------------------------------

def test_specifics_collapse_to_the_branch():
    assert (branch_of("spacing: a wolf is 2 away (severe band) — spacing off")
            == branch_of("spacing: a wolf is 3 away (calm band) — spacing off"))


def test_character_uids_do_not_shatter_a_branch():
    assert (branch_of("embarking g_cd0e2a_c15192 to vale")
            == branch_of("embarking g_cd0e2a_c15206 to vale"))


def test_distinct_branches_stay_distinct():
    assert branch_of("moving toward loot") != branch_of("closing on the nearest ally")


# ---- tally -------------------------------------------------------------------

def test_tally_counts_offers_and_wins_separately():
    t = tally([[_alt("moving toward loot", chosen=True), _alt("closing on the nearest ally")],
               [_alt("moving toward loot"), _alt("closing on the nearest ally")]])
    assert t["moving toward loot"] == {"offered": 2, "chosen": 1}
    assert t["closing on the nearest ally"] == {"offered": 2, "chosen": 0}


# ---- the inertness verdict, BOTH directions ----------------------------------
# These pass min_decisions=0 on purpose: they exercise the RULING logic in isolation, with
# the sample-size guard disabled. The guard itself is tested separately at the bottom —
# keeping them apart means neither can silently mask the other.

def test_it_REFUSES_a_change_whose_new_branch_never_wins():
    """THE regression this module exists for — v0.48.0 exactly: a new branch offered many
    times and chosen zero times."""
    inc = tally([[_alt("moving toward loot", chosen=True)]])
    cand = tally([[_alt("moving toward loot", chosen=True),
                   _alt("closing on the nearest ally")] for _ in range(28)])
    ok, why = verdict(compare(cand, inc), min_decisions=0)
    assert ok is False and "INERT" in why


def test_it_APPROVES_a_change_whose_new_branch_wins_ticks():
    """The other side. v0.48.1: the new branch actually takes ticks."""
    inc = tally([[_alt("moving toward loot", chosen=True)]])
    cand = tally([[_alt("moving toward loot"),
                   _alt("moving toward loot near an ally", chosen=True)]])
    ok, why = verdict(compare(cand, inc), min_decisions=0)
    assert ok is True and "win ticks" in why


def test_a_PARTLY_live_change_is_approved_and_names_which_branch_won():
    cand = tally([[_alt("new branch A"), _alt("new branch B", chosen=True)]])
    ok, why = verdict(compare(cand, tally([])), min_decisions=0)
    assert ok is True and "new branch B" in why


def test_a_pure_TUNING_change_is_not_called_inert():
    """No new branches at all — only the balance between existing ones moved. Calling that
    inert would cry wolf on every score adjustment."""
    inc = tally([[_alt("a", chosen=True), _alt("b")]])
    cand = tally([[_alt("a"), _alt("b", chosen=True)]])
    ok, why = verdict(compare(cand, inc), min_decisions=0)
    assert ok is True and "tuning" in why


# ---- the diff ----------------------------------------------------------------

def test_new_and_dropped_branches_are_identified():
    inc = tally([[_alt("gone branch", chosen=True), _alt("kept branch", chosen=True)]])
    cand = tally([[_alt("kept branch", chosen=True), _alt("fresh branch", chosen=True)]])
    c = compare(cand, inc)
    assert "fresh branch" in c["new_branches"]
    assert "gone branch" in c["dropped_branches"]
    assert "kept branch" not in c["new_branches"]


def test_shifts_in_existing_branches_are_reported_with_direction():
    inc = tally([[_alt("shared", chosen=True)] for _ in range(5)])
    cand = tally([[_alt("shared", chosen=True)] for _ in range(2)])
    c = compare(cand, inc)
    assert c["shifted"]["shared"]["delta"] == -3


def test_inert_lists_every_never_chosen_branch_not_only_new_ones():
    """An EXISTING branch that has stopped winning is also worth seeing — that is how a
    change silently kills behaviour it did not mean to touch."""
    inc = tally([[_alt("old faithful", chosen=True)]])
    cand = tally([[_alt("old faithful"), _alt("something else", chosen=True)]])
    assert "old faithful" in compare(cand, inc)["inert"]


# ---- the warm-up guard: refuse to rule on too small a sample -----------------

def test_it_REFUSES_TO_RULE_on_a_sample_too_short_for_a_warm_up():
    """The v0.48.0 error, encoded. Cohesion was called inert on 28 offers taken 130 ticks
    after a deploy; it first won at tick 461 and won 349 ticks in total. An INERT verdict
    from a short window reads as evidence when it is only ignorance, so the gate must say
    INCONCLUSIVE rather than guess."""
    inc = tally([[_alt("moving toward loot", chosen=True)]])
    cand = tally([[_alt("moving toward loot", chosen=True), _alt("a brand new branch")]
                  for _ in range(28)])
    ok, why = verdict(compare(cand, inc))
    assert ok is True and "INCONCLUSIVE" in why


def test_a_LONG_window_still_calls_a_truly_inert_branch_inert():
    """The other side — the guard must not make the gate unable to ever refuse."""
    inc = tally([[_alt("moving toward loot", chosen=True)]])
    cand = tally([[_alt("moving toward loot", chosen=True), _alt("a brand new branch")]
                  for _ in range(3000)])
    ok, why = verdict(compare(cand, inc))
    assert ok is False and "INERT" in why
