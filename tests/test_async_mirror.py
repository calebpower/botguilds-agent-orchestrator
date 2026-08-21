"""v0.51.0 — storage writes moved off the receive path.

The bug this fixes, measured on run #120: the receive loop zlib-compressed each frame and
ran three INSERTs before it could read the next message. 34% of frames took longer than the
~83ms production budget, 12.3% over 200ms, worst 2,972ms. A ZeroMQ DEALER DROPS rather than
blocks when its send queue fills, so those stalls cost 4.5% of the frame stream (31 gaps,
mean 131 frames), and the bot then commanded characters that had already moved on —
`unknown_character` went from 1.1 to 104 per 1k frames and the error rate from 13% to 43%.

The tell that it was us rather than the server: across a gap, the NEXT frame arrived in a
median of 9ms. Nothing had stalled; messages were being discarded.

So the property that matters is NOT "every write lands" — it is "the caller is never made
to wait". These tests assert that from both sides.
"""
import threading
import time

import pytest

from steemer.client import _AsyncMirror


class _Slow:
    """A storage stand-in that blocks, the way MariaDB does under load."""
    def __init__(self, delay=0.0):
        self.delay = delay
        self.calls = []
        self.gate = threading.Event()

    def record_frame(self, frame):
        if self.delay:
            time.sleep(self.delay)
        self.calls.append(frame)

    def record_error(self, msg):
        self.calls.append(msg)

    def blocking_write(self, x):
        self.gate.wait(timeout=5)
        self.calls.append(x)

    def boom(self, x):
        raise RuntimeError("db is on fire")


def _drain(m, storage, n, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end and len(storage.calls) < n:
        time.sleep(0.01)


def test_writes_actually_land():
    s = _Slow()
    m = _AsyncMirror(s, say=lambda *a: None)
    for i in range(20):
        m.submit("record_frame", {"i": i})
    _drain(m, s, 20)
    m.close()
    assert [c["i"] for c in s.calls] == list(range(20))       # and IN ORDER


def test_the_caller_is_NEVER_made_to_wait():
    """THE property. A submit must return immediately even while the database is wedged —
    blocking here is precisely the bug that cost 4.5% of the frame stream."""
    s = _Slow()
    m = _AsyncMirror(s, say=lambda *a: None, maxsize=50)
    m.submit("blocking_write", 1)          # the worker is now stuck on the gate
    time.sleep(0.05)
    t0 = time.perf_counter()
    for i in range(200):                   # 4x the queue size, so it must also shed
        m.submit("record_frame", {"i": i})
    elapsed = time.perf_counter() - t0
    s.gate.set()
    m.close(timeout=2)
    assert elapsed < 0.5, f"submitting blocked for {elapsed:.2f}s while the DB was stuck"


def test_overflow_drops_the_OLDEST_and_COUNTS_it():
    """Bounded, and shedding the oldest: recent frames are what an analysis wants. The
    count matters as much as the drop — an unobservable loss is how the original bug went
    unnoticed for a whole session."""
    s = _Slow()
    m = _AsyncMirror(s, say=lambda *a: None, maxsize=10)
    m.submit("blocking_write", "held")     # wedge the worker so nothing drains
    time.sleep(0.05)
    for i in range(60):
        m.submit("record_frame", {"i": i})
    assert m.dropped > 0, "overflowed without counting a single drop"
    s.gate.set()
    m.close(timeout=2)
    landed = [c["i"] for c in s.calls if isinstance(c, dict)]
    assert landed, "nothing landed at all"
    assert max(landed) == 59, "kept the OLDEST and shed the newest — backwards"


def test_a_failing_write_does_not_kill_the_worker():
    """Logging must never stop the bot playing: one bad write cannot end the thread and
    silently discard everything after it."""
    said = []
    s = _Slow()
    m = _AsyncMirror(s, say=said.append)
    m.submit("boom", 1)
    m.submit("record_frame", {"i": 99})
    _drain(m, s, 1)
    m.close()
    assert s.calls and s.calls[-1] == {"i": 99}, "the worker died on the first failure"
    assert m.failed == 1 and said, "a failure was neither counted nor reported"


def test_failures_are_reported_but_not_once_per_write():
    """A wedged database must not turn the log into a flood — that is its own outage."""
    said = []
    m = _AsyncMirror(_Slow(), say=said.append)
    for _ in range(300):
        m.submit("boom", 1)
    end = time.time() + 5
    while time.time() < end and m.failed < 300:
        time.sleep(0.01)
    m.close()
    assert m.failed == 300
    assert len(said) <= 5, f"logged {len(said)} times for 300 failures"


def test_close_drains_what_is_queued():
    s = _Slow()
    m = _AsyncMirror(s, say=lambda *a: None)
    for i in range(50):
        m.submit("record_frame", {"i": i})
    m.close(timeout=5)
    assert len(s.calls) == 50, "close() abandoned queued writes"


def test_close_actually_STOPS_the_worker_thread():
    """close() must end the thread, not merely drain it. A worker that keeps looping after
    close leaks a thread per session and would keep a database handle open — and the drain
    assertion above passes either way, so a mutant that never stopped survived it."""
    s = _Slow()
    m = _AsyncMirror(s, say=lambda *a: None)
    m.submit("record_frame", {"i": 1})
    m.close(timeout=5)
    assert not m._thread.is_alive(), "the worker thread outlived close()"


# ---- ordering: the decision must not wait on the database --------------------

def test_the_frame_is_RECORDED_AFTER_the_actions_are_SENT():
    """v0.51.0 reordered the receive loop so the storage write no longer sits between
    receiving a frame and answering it.

    This drives the REAL `_loop` with a fake transport. An earlier version of this test
    replayed the sequence itself and asserted its own ordering — a tautology that a mutant
    swapping the two lines in client.py sailed straight through.
    """
    from steemer.client import Client
    from steemer import protocol as p

    order = []

    class _T:
        def __init__(self):
            self.frames = [{"type": p.FRAME, "tick": 1, "world": "vale", "seq": 1,
                            "chars": []}]

        def poll(self, timeout_ms=0):
            return self.frames.pop(0) if self.frames else None

        def send(self, message):
            if message.get("type") == p.ACTIONS:
                order.append("send_actions")

        def close(self):
            pass

    class _Bot:
        version = "test/0"
        def on_frame(self, frame):
            return [{"char_uid": "c1", "action": "move", "dir": "N"}]

    class _Storage:
        run_id = 1
        def record_frame(self, frame):
            order.append("record_frame")
        def flush(self):
            pass

    # Every attribute _loop touches, mirroring Client.__init__ without a socket or a
    # token file. Set them from the real __init__'s list rather than discovering them one
    # AttributeError at a time.
    c = Client.__new__(Client)
    c.transport = _T(); c.bot = _Bot(); c.storage = _Storage()
    c._async_mirror = None            # synchronous: ordering is directly observable
    c.verbose = False; c.running = True; c.tick = 0; c.dropped_sends = 0
    c.config = {}; c.guild = {}
    c._last_seq = None; c._refresh_at = 0.0
    c._tiles_mem = {}; c._visible = {}      # v0.44.0 delta reassembly caches

    c._loop(max_ticks=1)              # one frame, then the loop stops itself
    assert order == ["send_actions", "record_frame"], order
