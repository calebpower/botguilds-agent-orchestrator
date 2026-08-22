"""Constants justified by a measurement must say when that measurement was last true.

Twice a well-reasoned constant has outlived its evidence, and nothing noticed:

  * `POTION_RESERVE = 600` — raised in v0.35.0 because heals were "99.6% FREE-BREWED
    (4,511 drinks vs 16 buys)". By 2026-08-22 we brewed SEVEN potion_red across ~180,000
    frames, and the 600 floor had made the buy unreachable at our 156-200 gold for the
    entire life of the reserve.
  * v0.8.0's stranded-singleton sell rule — correct for abundant items, and quietly wrong
    for the scarce chain inputs the bot later depended on. It ate lumber, ingots, `bone`,
    raw ore and 74 TOMES before anyone re-read it.

Both were right when written. Both carried comments that still READ persuasively years
later — that is precisely the trap: a justification is a claim about the world, and the
prose keeps its confidence long after the world has moved.

So a constant justified by a measurement carries a PREMISE line:

    # PREMISE(2026-08-22, brewing supplies our heals): SELECT ... ; expect > 0.9

and this test fails when one goes unverified for too long. It cannot check whether the
premise is TRUE — that needs the live database and a judgement — it makes the re-check
DUE, which is the step that never happened on its own. Re-verifying is a loop-pass action:
run the query, and either bump the date or change the constant.
"""
import datetime as _dt
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCES = [os.path.join(HERE, "..", "steemer", "strategy", "explorer.py"),
           os.path.join(HERE, "..", "steemer", "bot.py"),
           os.path.join(HERE, "..", "steemer", "metrics.py")]

# How long a measured premise may stand unchecked. Deliberately generous: the cost of a
# re-check is one query, and the cost of a stale premise was measured in months of a
# mechanic being unreachable.
MAX_AGE_DAYS = 45

PREMISE_RE = re.compile(r'#\s*PREMISE\((\d{4}-\d{2}-\d{2}),\s*([^)]+)\):\s*(.+)')


def premises() -> list[dict]:
    out = []
    for path in SOURCES:
        if not os.path.exists(path):
            continue
        for i, line in enumerate(open(path), 1):
            m = PREMISE_RE.search(line)
            if m:
                out.append({"file": os.path.basename(path), "line": i,
                            "date": m.group(1), "claim": m.group(2).strip(),
                            "check": m.group(3).strip()})
    return out


def test_every_premise_parses():
    """A malformed annotation is worse than none: it looks like coverage and checks
    nothing."""
    for p in premises():
        _dt.date.fromisoformat(p["date"])
        assert p["claim"], f"{p['file']}:{p['line']} has no claim"
        assert p["check"], f"{p['file']}:{p['line']} has no way to re-check it"


def test_no_premise_has_gone_stale():
    """If this fails: run the premise's own check against the live database, then either
    bump its date or change the constant it justifies. Do not simply bump the date without
    running the query — that converts this from a check into a chore."""
    today = _dt.date.today()
    stale = [(p, (today - _dt.date.fromisoformat(p["date"])).days)
             for p in premises()]
    overdue = [(p, age) for p, age in stale if age > MAX_AGE_DAYS]
    assert not overdue, (
        "premises unverified for more than "
        f"{MAX_AGE_DAYS} days:\n  "
        + "\n  ".join(f"{p['file']}:{p['line']} ({age}d) {p['claim']}"
                      for p, age in overdue))


def test_the_annotated_constants_are_the_ones_that_burned_us():
    """Self-test the oracle: an annotation scheme nobody has applied is decoration. The two
    constants whose premises actually expired must carry one, so this check has something
    to be about."""
    claims = " ".join(p["claim"].lower() + " " + p["check"].lower() for p in premises())
    assert premises(), "no PREMISE annotations exist at all"
    assert "brew" in claims, "POTION_RESERVE's premise is not annotated"
    assert "stale" in claims or "staleness" in claims or "move" in claims, \
        "MOVE_STAMINA_SAFETY's premise is not annotated"
