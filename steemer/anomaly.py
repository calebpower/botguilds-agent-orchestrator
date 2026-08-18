"""On-the-fly anomaly self-reporting for the live bot.

The bot cannot reconstruct the true roster from frames — the server shows
characters intermittently, so a single frame's ``guild`` snapshot is a partial
view of a large persistent roster (see ``findings.jsonl``). What it CAN do is
watch its own action-error stream and flag when a failure *family* spikes: a
sustained burst of ``no_such_character`` / ``not_in_village`` / ``roster_cap`` /
``unknown_character`` is the observable symptom of a desync — acting on a char
the authoritative state no longer holds, a wrong world, or a full roster — and
that is what tells the operator "something is off" without a false precision
about counts it can't measure.

Low-noise by construction: a family must exceed a real count within a rolling
tick window before it is flagged, and each family is re-reported at most once per
cooldown. A quiet, healthy stream produces nothing.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

WINDOW_TICKS = 300      # rolling window the rate is measured over
SPIKE_COUNT = 80        # >= this many errors of ONE family in the window => a spike
COOLDOWN_TICKS = 1200   # re-report a still-spiking family at most this often (a
#   chronically-elevated family — e.g. the field death-echo unknown_character —
#   then reminds ~once per 5 min rather than spamming, while a NEW family still
#   trips immediately).


class AnomalyMonitor:
    """Rolling per-reason action-error counter that emits a spike anomaly when a
    single family exceeds ``spike_count`` within ``window_ticks``."""

    def __init__(self, window_ticks: int = WINDOW_TICKS,
                 spike_count: int = SPIKE_COUNT,
                 cooldown_ticks: int = COOLDOWN_TICKS) -> None:
        self.window = window_ticks
        self.spike = spike_count
        self.cooldown = cooldown_ticks
        self._events: deque[tuple[int, str]] = deque()   # (tick, reason), oldest-first
        self._counts: dict[str, int] = defaultdict(int)
        self._last_flagged: dict[str, int] = {}

    def record(self, tick: int, reason: str | None) -> dict[str, Any] | None:
        """Register one action error at ``tick``. Return an anomaly dict if
        ``reason`` is now spiking (and not on cooldown), else ``None``."""
        if reason is None:
            return None
        self._events.append((tick, reason))
        self._counts[reason] += 1
        self._evict(tick)
        n = self._counts.get(reason, 0)
        if n < self.spike:
            return None
        last = self._last_flagged.get(reason)
        if last is not None and tick - last < self.cooldown:
            return None
        self._last_flagged[reason] = tick
        rate = n / self.window
        return {
            "subtype": f"error_spike:{reason}",
            "reason": reason, "count": n,
            "window_ticks": self.window, "rate_per_frame": round(rate, 3),
            "detail": (f"action-error family '{reason}' spiking: {n} in the last "
                       f"{self.window} ticks ({rate:.2f}/frame)"),
        }

    def _evict(self, now: int) -> None:
        while self._events and now - self._events[0][0] > self.window:
            _, r = self._events.popleft()
            self._counts[r] -= 1
            if self._counts[r] <= 0:
                del self._counts[r]
