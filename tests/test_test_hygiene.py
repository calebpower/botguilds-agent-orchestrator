"""Two test-craft mistakes this loop has made repeatedly, turned into ratchets.

Mutation testing caught both over and over — which is the point: they are invisible to a
green suite and only show up when you try to make a test FAIL.

  1. FIXTURES DERIVED FROM THE CONSTANT UNDER TEST. Caught four times (VEIN_SEEK_RANGE,
     SCARCE_LONE_KEEP, OVERBURDENED_TTL, FORGE_FAIL_LIMIT). A fixture sized as
     `range(CONST - 1)` moves WITH the constant, so a mutant that changes it leaves the
     test green — the test agrees with itself no matter what the value becomes. The remedy
     is to hardcode the POLICY claim ("one refusal does not condemn; three do") and pin the
     constant's band in a SEPARATE assertion, which is why the band assertion is what this
     check looks for.

  2. HAND-ROLLED TEST DOUBLES for objects the strategy actually calls. Caught three times.
     A stub `_Bot` or `Spy` only stays correct until the real object grows a method — and
     when it drifts, the test fails for a reason unrelated to what it tests (a missing
     `observe`, then a missing `recently_forged`). Use the real `GuildBot`; it is cheap.

Both budgets are RATCHETS. They record where we were on 2026-08-22 and may only ever go
DOWN. Lower them by fixing a test, never by raising the number — a bound that moves with the
violation is the same mistake as a fixture that moves with its constant.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# Where we stood when this check was introduced. DECREASE ONLY.
DERIVED_FIXTURE_BUDGET = 12
HANDROLLED_DOUBLE_BUDGET = 5

DOUBLE_RE = re.compile(
    r'class\s+(_?\w*(?:Bot|Trace|Spy)\w*)\b[^\n]*:\n((?:\s+.*\n)+?)(?=\S|\Z)')
DRIVEN_METHOD_RE = re.compile(r'def (act|village|consider|observe|on_frame)\(')


def _test_sources() -> dict[str, str]:
    return {fn: open(os.path.join(HERE, fn)).read()
            for fn in sorted(os.listdir(HERE))
            if fn.startswith("test_") and fn.endswith(".py")}


def _imported_constants(src: str) -> set[str]:
    return {n for m in re.finditer(r'from steemer[\w.]* import \(?([^)\n]+)', src)
            for n in re.findall(r'\b([A-Z][A-Z0-9_]{3,})\b', m.group(1))}


def derived_fixtures() -> list[tuple[str, str]]:
    """Files that size a fixture from an imported constant without pinning its band."""
    out = []
    for fn, src in _test_sources().items():
        for c in sorted(_imported_constants(src)):
            derived = re.search(rf'(range\(\s*{c}\b|{c}\s*[-+]\s*\d+)', src)
            banded = re.search(rf'\d+\s*<[=]?\s*{c}\s*<[=]?\s*\d+', src)
            if derived and not banded:
                out.append((fn, c))
    return out


def handrolled_doubles() -> list[tuple[str, str]]:
    """Stub classes standing in for objects the strategy drives."""
    out = []
    for fn, src in _test_sources().items():
        for m in DOUBLE_RE.finditer(src):
            if DRIVEN_METHOD_RE.search(m.group(2)):
                out.append((fn, m.group(1)))
    return out


def test_no_new_fixtures_derived_from_the_constant_under_test():
    """If this fails for a test you just wrote: hardcode the policy claim the fixture is
    making, and assert the constant's band separately (`assert 5 < TTL < 500`). Do not
    raise the budget."""
    found = derived_fixtures()
    assert len(found) <= DERIVED_FIXTURE_BUDGET, (
        f"{len(found)} derived fixtures against a budget of {DERIVED_FIXTURE_BUDGET}:\n  "
        + "\n  ".join(f"{fn}: {c}" for fn, c in found))


def test_no_new_handrolled_doubles_for_objects_the_strategy_drives():
    """If this fails: use the real `GuildBot` (see tests/test_bottle_buy.py's `_Bot`
    helper, which constructs one). Do not raise the budget."""
    found = handrolled_doubles()
    assert len(found) <= HANDROLLED_DOUBLE_BUDGET, (
        f"{len(found)} hand-rolled doubles against a budget of "
        f"{HANDROLLED_DOUBLE_BUDGET}:\n  "
        + "\n  ".join(f"{fn}: {cls}" for fn, cls in found))


def test_the_detectors_can_actually_see_their_targets():
    """Self-test the oracle — tools/mutate.py lied twice in this project, both times by
    reporting success it had not verified. A hygiene check that silently matches nothing
    is the same failure wearing different clothes."""
    assert derived_fixtures(), "the derived-fixture detector matches nothing at all"
    assert handrolled_doubles(), "the double detector matches nothing at all"


def test_the_budgets_describe_the_current_state_not_a_wish():
    """A ratchet set above where we stand is slack, and slack is what a ratchet is for
    removing. These must be tight enough that the next violation trips them."""
    assert DERIVED_FIXTURE_BUDGET == len(derived_fixtures())
    assert HANDROLLED_DOUBLE_BUDGET == len(handrolled_doubles())
