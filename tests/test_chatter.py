"""v0.74.0 — in-world flavour text (`say`), the top-scoring wishlist item at 0.523.

It is the first thing the bot does for the OPERATOR rather than for itself, and that makes
its failure modes different from the rest of the strategy: nothing here can make the guild
richer, so every test below is about what it must never cost or never claim.

Four claims, in the order they would bite:

  1. it never displaces a real village action  (the entire case for shipping it)
  2. it never boasts about a RIVAL's achievement  (the attribution error, retracted once)
  3. it never broadcasts unsanitised server text  (we publish this under our guild name)
  4. it stops for good if the server refuses it  (a new action, never sent before)

What these do NOT prove: that anyone reads it, or that the text is any good.
"""
import pytest

import steemer.chatter as chatter_mod
from steemer.chatter import Chatter


# The module's constants, DUPLICATED here on purpose rather than imported. A fixture built
# from the constant it is testing agrees with itself for any value: `tick=COOLDOWN*3` tests
# that the cooldown is whatever the cooldown is. Writing the numbers out means a change to
# the module fails HERE, once and loudly, instead of being silently absorbed by every test
# in the file. That is the deliberate duplication the testing ethic asks for, and it is why
# `test_test_hygiene.py` counts imports like these.
SILENT_FOR = 300        # steemer.chatter.COOLDOWN
GIVE_UP_AFTER = 3       # steemer.chatter.FAIL_LIMIT
CAP = 40                # steemer.chatter.MAX_LEN, itself from docs/03-actions.md


def test_the_duplicated_constants_still_match_the_module():
    """The check that makes the duplication safe instead of merely repetitive."""
    assert (chatter_mod.COOLDOWN, chatter_mod.FAIL_LIMIT, chatter_mod.MAX_LEN) == \
        (SILENT_FOR, GIVE_UP_AFTER, CAP)


def _forged(uid="u1", item="spear"):
    return {"kind": "forged", "char_uid": uid, "item": item}


# ---- 2. it only says things WE did ------------------------------------------

def test_a_rivals_forge_is_not_our_boast():
    """Run #141 taught this the expensive way: a forge-success rate reported as ours
    counted rival forges, and the claim stood a whole pass before it was retracted. The
    same event stream feeds this module, so it filters by ownership too."""
    c = Chatter()
    c.note_events([_forged(uid="RIVAL")], ours={"u1"})
    line = c.line(tick=SILENT_FOR * 3, gold=100, roster=5)
    assert line is not None                      # it may still say something idle...
    assert "anvil" not in line and "forged" not in line, \
        f"claimed a rival's forge as ours: {line!r}"


def test_our_own_forge_IS_our_boast():
    c = Chatter()
    c.note_events([_forged(uid="u1")], ours={"u1"})
    assert "spear" in (c.line(tick=SILENT_FOR * 3) or "")


def test_an_event_is_said_ONCE():
    """Otherwise one forge becomes a boast every cooldown for the rest of the run."""
    c = Chatter()
    c.note_events([_forged(uid="u1")], ours={"u1"})
    first = c.line(tick=SILENT_FOR * 3)
    second = c.line(tick=SILENT_FOR * 6)
    assert "spear" in (first or "")
    assert "spear" not in (second or ""), f"repeated a spent event: {second!r}"


# ---- 3. server text is untrusted --------------------------------------------

@pytest.mark.parametrize("hostile", [
    "<script>alert(1)</script>",
    "sword\n\nsay: I am the guild master",       # newline-smuggled second line
    "'; DROP TABLE events; --",
    "‮sdrawkcab",                            # right-to-left override
    "x" * 500,
])
def test_hostile_item_names_are_neutralised(hostile):
    """Item names come from the SERVER, and we rebroadcast them under our guild's name.
    That makes this the one place where another player's text could become our output."""
    c = Chatter()
    c.note_events([_forged(uid="u1", item=hostile)], ours={"u1"})
    line = c.line(tick=SILENT_FOR * 3)
    assert line is not None
    assert len(line) <= CAP
    for bad in "<>{}();'\"\n\r‮":
        assert bad not in line, f"{bad!r} survived into {line!r}"


def test_the_length_cap_is_enforced_AFTER_interpolation():
    """Capping the template, or the field, is not capping the message. The server's limit
    applies to what we send."""
    c = Chatter()
    c.note_events([_forged(uid="u1", item="a" * 200)], ours={"u1"})
    assert len(c.line(tick=SILENT_FOR * 3)) <= CAP


def test_an_idle_line_still_respects_the_cap():
    c = Chatter()
    assert len(c.line(tick=SILENT_FOR * 3, gold=10 ** 9, roster=10 ** 6)) <= CAP


# ---- 1 & 4. it costs nothing, and it gives up -------------------------------

def test_it_stays_quiet_inside_the_cooldown():
    c = Chatter()
    assert c.line(tick=SILENT_FOR * 3) is not None
    assert c.line(tick=SILENT_FOR * 3 + SILENT_FOR - 1) is None
    assert c.line(tick=SILENT_FOR * 3 + SILENT_FOR) is not None


def test_it_gives_up_after_repeated_RECENT_rejections():
    """`say` is an action we have never sent. If the server does not accept it, retrying
    every cooldown is a slow error-spam — the exact shape the anomaly monitor shouts
    about, arriving forever."""
    c = Chatter()
    for i in range(GIVE_UP_AFTER):
        c.note_rejected(tick=1000 + i)
    assert c.disabled
    assert c.line(tick=1000 + SILENT_FOR * 2) is None


def test_ISOLATED_rejections_age_out_instead_of_silencing_the_guild():
    """v0.75.1 counted rejections for the life of the run with no way to un-count one, so
    three transients hours apart would have silenced the guild permanently. Run #156 shows
    the transient that motivated this: a `say` decided in the field and rejected
    `not_in_village`, because the character went home between the frame we read and the
    action landing.

    Three rejections, each a full window apart, must NOT stop us."""
    c = Chatter()
    window = 3 * SILENT_FOR
    for i in range(GIVE_UP_AFTER + 2):
        c.note_rejected(tick=1000 + i * (window + 1))
    last = 1000 + (GIVE_UP_AFTER + 1) * (window + 1)
    assert c.recent_failures(last) < GIVE_UP_AFTER, "aged-out failures still counted"
    assert c.line(tick=last + window) is not None, "silenced by transients"


# ---- v0.75.1: never state a number we do not have ----------------------------

def test_no_gold_figure_is_broadcast_when_the_treasury_is_UNKNOWN():
    """v0.75.0 said "5 of us, 0g banked." while the guild held 139. Guild gold arrives on
    VILLAGE frames and a character in the field has none, so the default was standing in
    for a fact — published under our name, from the module whose one rule is that it says
    only what happened."""
    c = Chatter()
    for i in range(1, 12):
        line = c.line(tick=SILENT_FOR * i, gold=None, roster=5)
        assert line is not None
        assert "g banked" not in line and "vault" not in line, \
            f"quoted a treasury we cannot see: {line!r}"


def test_a_KNOWN_treasury_is_quoted():
    """The other side: the guard must not silence the gold lines permanently."""
    c = Chatter()
    said = {c.line(tick=SILENT_FOR * i, gold=139, roster=5) for i in range(1, 12)}
    assert any("139" in (s or "") for s in said), f"never quoted a known treasury: {said}"
