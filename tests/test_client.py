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
