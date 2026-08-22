"""Every behaviour must have an answer to: WHERE does this run, and FOR WHOM?

Four separate behaviours in this project were correct, tested, gated, deployed — and never
executed:

  v0.54.0  vein-seek     validated against a map the running PROCESS did not have
  v0.64.0  proof rule    events parsed only on frames it never saw (village frames)
  v0.67.0  INT buy       keyed on state that dies at every deploy
  v0.68.0  learn step    ran in the village; the character never went there

Each cost a pass or more, and in every case the unit tests passed throughout because they
drove the function directly and nothing drove the WIRING. The suite was measuring the code
being called, not the code the bot runs.

This is the forcing function. It does not prove a behaviour fires in play — nothing offline
can. What it does is make the question unavoidable at the moment it is cheapest to answer:
adding an offer to the strategy fails the suite until its reachability is stated, either as a
test that drives `GuildBot.on_frame`, or as an exemption with a written reason.

WHAT THIS DOES NOT PROVE, stated plainly so nobody reads more into a green suite than is
there: an entry naming a test proves that test exists and goes through the bot, not that it
exercises this specific branch. It is a ratchet against a repeated, expensive mistake, not a
coverage guarantee.
"""
import json
import os
import re

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
STRATEGY = os.path.join(HERE, "..", "steemer", "strategy", "explorer.py")
REGISTRY = os.path.join(HERE, "reachability.json")

# The literal prefix of an offer's reason, up to the first interpolation — stable enough to
# identify a behaviour across edits to its wording's variable parts.
OFFER_RE = re.compile(r'offer\(\{[^}]*\},\s*[A-Za-z_0-9.]+\s*,\s*\n?\s*f?"([^"{]{8,})')


def behaviours() -> set[str]:
    src = open(STRATEGY).read()
    return {m.group(1).strip() for m in OFFER_RE.finditer(src)}


def registry() -> dict:
    return json.load(open(REGISTRY))


def test_every_behaviour_is_registered():
    """A new offer fails here until someone says how it is reached.

    If this fails for code you just wrote: add an entry to tests/reachability.json naming
    either the test that drives GuildBot.on_frame, or an exemption with a reason. Do not
    delete the behaviour from the registry to make it pass.
    """
    known = set(registry()["behaviours"])
    found = behaviours()
    unregistered = found - known
    assert not unregistered, (
        "unregistered behaviour(s) — state how each is reached in "
        f"tests/reachability.json:\n  " + "\n  ".join(sorted(unregistered)))


def test_the_registry_has_not_gone_stale():
    """Entries for behaviours that no longer exist are noise that hides the real ones."""
    known = set(registry()["behaviours"])
    stale = known - behaviours()
    assert not stale, (
        "registry names behaviours that no longer exist in explorer.py:\n  "
        + "\n  ".join(sorted(stale)))


def test_every_entry_states_a_test_or_a_reason():
    bad = [name for name, e in registry()["behaviours"].items()
           if not e.get("through_bot_test") and not e.get("exempt_reason")]
    assert not bad, f"entries with neither a test nor an exemption reason: {bad}"


def test_named_tests_exist_and_actually_drive_the_bot():
    """The claim "this is reached through GuildBot.on_frame" has to be true of the named
    test, or the registry is decoration. Checked against the test SOURCES rather than a
    list, so a renamed or deleted test fails here."""
    sources = {}
    for fn in os.listdir(HERE):
        if fn.startswith("test_") and fn.endswith(".py"):
            sources[fn] = open(os.path.join(HERE, fn)).read()
    joined = "\n".join(sources.values())
    for name, entry in registry()["behaviours"].items():
        test = entry.get("through_bot_test")
        if not test:
            continue
        assert f"def {test}(" in joined, f"{name}: named test {test} does not exist"
        owner = next(s for s in sources.values() if f"def {test}(" in s)
        assert "on_frame" in owner, (
            f"{name}: {test} does not drive GuildBot.on_frame, so it cannot show the "
            f"behaviour is reachable")


def test_exemptions_are_few_enough_to_read():
    """A ratchet only works if the exemption list is embarrassing to grow. If this fails,
    the honest fix is to write through-the-bot tests, not to raise the bound."""
    exempt = [n for n, e in registry()["behaviours"].items() if e.get("exempt_reason")]
    assert len(exempt) <= registry()["exempt_budget"], (
        f"{len(exempt)} exemptions against a budget of {registry()['exempt_budget']}")


# ---- the same ratchet, for the VILLAGE loop ----------------------------------
#
# OFFER_RE reads the field ladder only. Village actions never pass through `offer`, so the
# whole village loop was outside this gate — including v0.68.0's learn step, which is one
# of the four failures named at the top of this file. A guardrail that cannot see the bug
# it was built for is worth exactly as much as the tests it replaced.
#
# Seeded at the true count on 2026-08-22 rather than at zero, because the alternative is a
# green suite that means nothing. It decreases from here, like the other one.

VILLAGE_RE = re.compile(r'_village_act\(\s*\n?\s*bot,[^)]*?\}\s*,\s*\n?\s*f?"([^"{]{8,})',
                        re.S)


def village_behaviours() -> set[str]:
    src = open(STRATEGY).read()
    return {m.group(1).strip() for m in VILLAGE_RE.finditer(src)}


def test_the_village_detector_finds_something():
    """Self-test: a regex that matches nothing would make every check below vacuous, and
    would look identical to a clean bill of health."""
    found = village_behaviours()
    assert len(found) >= 5, f"the village detector has stopped matching: {found}"
    assert any("embarking" in b for b in found), \
        "embark is the one village action we are certain exists"


def test_every_village_behaviour_is_registered():
    registered = set(registry().get("village_behaviours", {}))
    missing = village_behaviours() - registered
    assert not missing, (
        "village behaviours with no stated reachability:\n  " + "\n  ".join(sorted(missing))
        + "\n\nAdd a through_bot_test, or an exempt_reason, in tests/reachability.json.")


def test_the_village_registry_has_not_gone_stale():
    stale = set(registry().get("village_behaviours", {})) - village_behaviours()
    assert not stale, (
        "registry names village behaviours that no longer exist in explorer.py:\n  "
        + "\n  ".join(sorted(stale)))


def test_the_village_exemption_budget_only_shrinks():
    reg = registry()
    exempt = [b for b, v in reg.get("village_behaviours", {}).items() if "exempt_reason" in v]
    budget = reg.get("village_exempt_budget", 0)
    assert len(exempt) <= budget, (
        f"{len(exempt)} village behaviours are exempt but the budget is {budget}. Write a "
        "test that drives GuildBot.on_frame; do not raise the number.")
    assert budget <= 9, "village_exempt_budget is a ratchet seeded at 9 — it may only fall"
