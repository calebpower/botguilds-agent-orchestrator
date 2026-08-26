"""Client delta-frame handling: seq-gap -> REFRESH resync (v0.44.0).

Constructed via __new__ with a fake transport so no token file or ZeroMQ socket is
needed — we exercise the pure decision logic of _maybe_refresh in isolation.
"""

from steemer.client import Client
from steemer import protocol as p


class _FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, message):
        self.sent.append(message)


def _client():
    c = Client.__new__(Client)
    c.transport = _FakeTransport()
    c._last_seq = None
    c._refresh_at = 0.0
    c.verbose = False
    return c


def test_no_refresh_on_contiguous_seq():
    c = _client()
    for s in (1, 2, 3, 4):
        c._maybe_refresh({"seq": s})
    assert c.transport.sent == []           # no gap -> never asks for a refresh
    assert c._last_seq == 4


def test_seq_gap_requests_one_full_refresh():
    c = _client()
    c._maybe_refresh({"seq": 1})
    c._maybe_refresh({"seq": 5})            # 2,3,4 dropped -> resync
    assert [m["type"] for m in c.transport.sent] == [p.REFRESH]
    assert c._last_seq == 5                  # still advances past the gap


def test_refresh_is_throttled_to_one_per_window():
    c = _client()
    c._maybe_refresh({"seq": 1})
    c._maybe_refresh({"seq": 5})            # gap -> one REFRESH
    c._maybe_refresh({"seq": 20})           # another gap immediately -> throttled (<2s)
    assert len(c.transport.sent) == 1


def test_missing_seq_is_not_treated_as_a_gap():
    c = _client()
    c._maybe_refresh({"seq": 3})
    c._maybe_refresh({})                     # server sent no seq -> nothing to resync
    assert c.transport.sent == []


# ---- v0.115.1 self-heal: a sustained session-poison storm triggers ONE re-hello ------

def _heal_client():
    c = Client.__new__(Client)
    c.transport = _FakeTransport()
    c.verbose = False
    return c


def test_a_storm_of_stale_frame_heals_exactly_once():
    from steemer.client import HEAL_THRESHOLD, HEAL_WINDOW, HEAL_MIN_SPACING
    assert (HEAL_THRESHOLD, HEAL_WINDOW, HEAL_MIN_SPACING) == (60, 600, 2400), \
        "heal tuning moved; re-read the numbers in these tests"
    c = _heal_client()
    fired = [c._maybe_heal("stale_frame", 1000 + i) for i in range(80)]
    assert fired.count(True) == 1, f"expected exactly one heal, got {fired.count(True)}"
    # the 60th error qualifies (index 59) — LITERAL on purpose, pinned above; deriving
    # this from HEAL_THRESHOLD would let the test agree with any broken value.
    assert fired.index(True) == 59


def test_calm_error_trickle_never_heals():
    # 59 errors inside one window is below threshold; spread errors NEVER accumulate
    # across windows (the deque prunes) — the calm baseline must not reconnect.
    c = _heal_client()
    assert not any(c._maybe_heal("stale_frame", 1000 + i) for i in range(59))
    assert not any(c._maybe_heal("stale_frame", 5000 + i * 20) for i in range(100)), \
        "spread errors (1 per 20 ticks) healed — the window prune is broken"


def test_a_second_storm_inside_the_spacing_does_not_flap():
    c = _heal_client()
    assert any(c._maybe_heal("stale_frame", 1000 + i) for i in range(70))
    # immediate second storm: suppressed by hysteresis
    assert not any(c._maybe_heal("stale_frame", 1200 + i) for i in range(70)), \
        "healed twice within HEAL_MIN_SPACING — reconnect flap"
    # a storm after the spacing heals again
    assert any(c._maybe_heal("stale_frame", 4000 + i) for i in range(70)), \
        "the heal never re-armed after HEAL_MIN_SPACING"


def test_non_poison_reasons_never_heal():
    # not_enough_stamina storms are ordinary play (100+/window in hot bands, run 219)
    # and must never cost us a session.
    c = _heal_client()
    assert not any(c._maybe_heal("not_enough_stamina", 1000 + i) for i in range(500))
