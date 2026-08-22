"""v0.61.0 — the expectation/reality mismatch detector.

An operator request, and the last four passes each shipped a silent belief-vs-reality
mismatch past a GREEN gate: v0.54 vein-seek fired 751 times with no character ever reaching
a vein; v0.49 bought six clubs for one character; two characters were entombed on stale
frames and bled out at full stamina; v0.35's potion reserve rested on a premise that
silently stopped being true. Each was caught by hand, hours or days later.

The single most important behaviour under test is the one the wishlist entry named before
any code existed: frames are STALE, so "it has not happened yet" must NEVER read as "it did
not happen". That confusion is the direct cause of both deaths above, and a detector that
repeated it would manufacture the very bug it exists to catch. Hence three-valued
resolution, and `expired` is NOT `violated`.
"""
import pytest

from steemer.expectation import ExpectationMonitor, GRACE_TICKS


def _char(uid="u1", pos=(1, 1), inv=(), equipment=None):
    return {"char_uid": uid, "pos": list(pos),
            "inventory": [{"kind": k, "item_id": f"{k}{i}"} for i, k in enumerate(inv)],
            "equipment": equipment or {}}


def _run(monitor, action, before, after_frames, start_tick=0):
    """Issue one action, then feed frames at increasing ticks."""
    monitor.record_actions(start_tick, [dict(action, char_uid="u1")], [before])
    for i, chars in enumerate(after_frames, start=1):
        monitor.observe(start_tick + i, chars)
    return monitor.summary()


# ---- the stale-frame trap, first and loudest ---------------------------------

def test_an_unresolved_prediction_inside_the_grace_window_is_not_a_violation():
    """The trap. A character that has not visibly moved YET is not a character that
    failed to move — that inference killed Recruit-15469 and Recruit-15484."""
    m = ExpectationMonitor()
    s = _run(m, {"action": "move", "dir": "N"}, _char(), [[_char(pos=(1, 1))]] * 3)
    assert s == {}, "nothing may be ruled on before the grace window closes"


def test_it_becomes_a_violation_only_after_the_grace_window():
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "u1", "action": "move", "dir": "N"}], [_char()])
    m.observe(GRACE_TICKS - 1, [_char(pos=(1, 1))])
    assert m.summary() == {}
    m.observe(GRACE_TICKS + 1, [_char(pos=(1, 1))])
    assert m.summary()["move"]["violated"] == 1


def test_a_character_we_never_see_EXPIRES_rather_than_violating():
    """Silence is not evidence. Characters appear intermittently in frames, so an unseen
    character must not be counted as a broken promise."""
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "u1", "action": "move", "dir": "N"}], [_char()])
    m.observe(GRACE_TICKS + 1, [_char(uid="somebody_else")])
    s = m.summary()
    assert s["move"] == {"confirmed": 0, "violated": 0, "expired": 1,
                         "ruled": 0, "confirm_rate": None}


def test_expired_is_reported_apart_from_the_confirmation_rate():
    """A high expiry rate means we are not SEEING our characters — a different problem
    from being wrong about them. Averaging the two would hide both."""
    m = ExpectationMonitor()
    for i in range(3):
        m.record_actions(i * 100, [{"char_uid": "u1", "action": "move", "dir": "N"}],
                         [_char()])
        m.observe(i * 100 + GRACE_TICKS + 1, [])
    m.record_actions(1000, [{"char_uid": "u1", "action": "move", "dir": "N"}], [_char()])
    m.observe(1001, [_char(pos=(1, 2))])
    s = m.summary()
    assert s["move"]["expired"] == 3
    assert s["move"]["confirm_rate"] == 1.0, "the rate covers only what was RULED on"


# ---- what each action promises -----------------------------------------------

def test_a_move_that_moves_is_confirmed():
    m = ExpectationMonitor()
    s = _run(m, {"action": "move", "dir": "N"}, _char(pos=(1, 1)),
             [[_char(pos=(1, 2))]])
    assert s["move"]["confirmed"] == 1


def test_a_move_confirms_on_ANY_displacement_not_just_the_intended_tile():
    """The observable is "did not stand still". A bounce leaves us exactly where we were;
    the server may legitimately put us somewhere else entirely (knockback, a portal), and
    calling that a violation would flood the detector with false alarms."""
    m = ExpectationMonitor()
    s = _run(m, {"action": "move", "dir": "N"}, _char(pos=(1, 1)),
             [[_char(pos=(5, 9))]])
    assert s["move"]["confirmed"] == 1


def test_a_bounced_move_is_a_violation():
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "u1", "action": "move", "dir": "N"}], [_char(pos=(1, 1))])
    m.observe(GRACE_TICKS + 1, [_char(pos=(1, 1))])
    assert m.summary()["move"]["violated"] == 1


def test_a_buy_that_does_not_arrive_is_a_violation():
    """The v0.49.0 defect exactly: six clubs bought for one character because nothing
    checked whether the first had arrived."""
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "u1", "action": "buy", "kind": "club"}], [_char()])
    m.observe(GRACE_TICKS + 1, [_char()])
    assert m.summary()["buy"]["violated"] == 1


def test_a_buy_that_arrives_is_confirmed():
    m = ExpectationMonitor()
    s = _run(m, {"action": "buy", "kind": "club"}, _char(), [[_char(inv=["club"])]])
    assert s["buy"]["confirmed"] == 1


def test_a_buy_counts_that_KIND_not_the_pack_size():
    """Holding one club already, a second buy is only confirmed by a SECOND club — not by
    picking up a berry on the way."""
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "u1", "action": "buy", "kind": "club"}],
                     [_char(inv=["club"])])
    m.observe(GRACE_TICKS + 1, [_char(inv=["club", "berries"])])
    assert m.summary()["buy"]["violated"] == 1


def test_pickup_and_sell_are_measured_in_opposite_directions():
    m = ExpectationMonitor()
    assert _run(m, {"action": "pickup"}, _char(),
                [[_char(inv=["berries"])]])["pickup"]["confirmed"] == 1
    m2 = ExpectationMonitor()
    assert _run(m2, {"action": "sell"}, _char(inv=["berries"]),
                [[_char()]])["sell"]["confirmed"] == 1


def test_an_equip_is_confirmed_by_the_slot_filling():
    m = ExpectationMonitor()
    s = _run(m, {"action": "equip", "slot": "hand", "item_id": 1}, _char(),
             [[_char(equipment={"hand": {"kind": "club"}})]])
    assert s["equip"]["confirmed"] == 1


def test_an_action_we_cannot_check_makes_no_prediction():
    """Better to predict nothing than to invent an oracle. An un-checkable action must not
    inflate either column — a detector padded with unfalsifiable claims reads as healthy."""
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "u1", "action": "rest"}], [_char()])
    m.observe(GRACE_TICKS + 1, [_char()])
    assert m.summary() == {}


def test_an_action_for_a_character_not_in_the_frame_makes_no_prediction():
    """Uses `equip` deliberately. A `move` prediction needs the character's starting
    position, so a missing character produces nothing whatever the guard does — the test
    would pass for the wrong reason. `equip` reads no prior state, so it is the case that
    actually distinguishes "we skipped the ghost" from "we predicted about a ghost"."""
    m = ExpectationMonitor()
    m.record_actions(0, [{"char_uid": "ghost", "action": "equip", "slot": "hand"}],
                     [_char()])
    m.observe(GRACE_TICKS + 1, [_char()])
    assert m.summary() == {}


# ---- the alarm ---------------------------------------------------------------

def _violate(m, n, tick0=0):
    for i in range(n):
        t = tick0 + i
        m.record_actions(t, [{"char_uid": "u1", "action": "move", "dir": "N"}],
                         [_char(pos=(1, 1))])
        m.observe(t + GRACE_TICKS + 1, [_char(pos=(1, 1))])


def test_the_alarm_refuses_to_rule_on_a_small_sample():
    """The v0.48.0 warm-up misread, encoded: 28 offers was not enough to call a branch
    inert, and a detector that cries wolf during warm-up gets ignored when it is right."""
    m = ExpectationMonitor()
    _violate(m, 5)
    assert m.alarm(100) is None


def test_the_alarm_fires_on_a_sustained_violation_rate():
    m = ExpectationMonitor()
    _violate(m, 40)
    a = m.alarm(GRACE_TICKS + 45)
    assert a is not None
    assert a["rate"] == 1.0
    assert a["action"] == "move" and a["violated"] == 40


def test_a_failing_family_is_not_hidden_by_a_healthy_one():
    """The reason the alarm is PER FAMILY. On the detector's first real run `move`
    resolved 29,779 times against `pickup`'s 901, so a pickup failing nine times in ten
    came to 2.6% of the total — invisible to any aggregate threshold. The signal lives in
    the family."""
    m = ExpectationMonitor()
    for i in range(400):                       # a large, perfectly healthy family
        m.record_actions(i, [{"char_uid": "u1", "action": "move", "dir": "N"}],
                         [_char(pos=(1, 1))])
        m.observe(i + 1, [_char(pos=(1, 2))])
    for i in range(30):                        # a small, badly failing one
        t = 400 + i
        m.record_actions(t, [{"char_uid": "u1", "action": "pickup"}], [_char()])
        m.observe(t + GRACE_TICKS + 1, [_char()])
    a = m.alarm(500)
    assert a is not None, "the failing family must be found under the healthy one"
    assert a["action"] == "pickup"


def test_a_healthy_stream_never_alarms():
    """Two oracles for the claim that matters most about any watchdog — it fires when it
    should (above) AND stays silent when it should not."""
    m = ExpectationMonitor()
    for i in range(40):
        m.record_actions(i, [{"char_uid": "u1", "action": "move", "dir": "N"}],
                         [_char(pos=(1, 1))])
        m.observe(i + 1, [_char(pos=(1, 2))])
    assert m.alarm(100) is None
    assert m.summary()["move"]["confirm_rate"] == 1.0


def test_the_alarm_does_not_repeat_inside_its_cooldown():
    m = ExpectationMonitor()
    _violate(m, 40)
    t = GRACE_TICKS + 45
    assert m.alarm(t) is not None
    assert m.alarm(t + 1) is None


def test_violations_are_recorded_with_enough_detail_to_act_on():
    m = ExpectationMonitor()
    _violate(m, 1)
    v = m.violations[-1]
    assert v["char_uid"] == "u1" and v["action"] == "move"
    assert "(1, 1)" in v["expected"], "the expectation must name the state it was made from"


# ---- the contract with the caller --------------------------------------------

def test_an_alarm_is_shaped_for_the_reporter_that_consumes_it():
    """GuildBot._report_anomaly does `a["subtype"]` and record_anomaly stores that as the
    column the dashboard groups by. An alarm without it raises a KeyError INSIDE on_frame
    — i.e. the observability tool would take the bot down. This is the un-enumerated-input
    failure that caused the 0.51.0 segfault and the 0.54.0 inert seek, so it gets a test
    rather than a careful read."""
    m = ExpectationMonitor()
    _violate(m, 40)
    a = m.alarm(GRACE_TICKS + 45)
    assert a["subtype"] == "expectation_mismatch:move"
    assert isinstance(a.get("detail"), str) and a["detail"]


def test_the_reporter_actually_accepts_it_end_to_end():
    """Two oracles: the shape above, and the real consumer not raising. Asserted against
    GuildBot itself rather than a copy of its expectations."""
    from steemer.bot import GuildBot
    bot = GuildBot("explorer")
    m = ExpectationMonitor()
    _violate(m, 40)
    bot._report_anomaly(m.alarm(GRACE_TICKS + 45))     # must not raise
