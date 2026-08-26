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


# --- v0.116.0 KPI deviation families (operator-directed, 2026-08-26): the outage
# postmortem's lesson made executable — the hold battery watched OUTCOMES while the
# bot's ability to ACT collapsed. These two watch capability-shaped KPIs live and
# emit through the same [anomaly] channel the wake-up monitor consumes.
FIELDED_COLLAPSE_TICKS = 600   # fielded stuck this long -> flag (2.5 min of paralysis;
                               # the 2026-08-26 outage ran 90 min unflagged)
FIELDED_COLLAPSE_MAX = 1       # "collapsed" = at most this many fielded...
FIELDED_BENCH_MIN = 5          # ...while at least this many sit at home able to embark
                               # (a genuinely tiny roster fielding nobody is not a bug)
XP_STALL_WINDOW = 3000         # zero xp this long AFTER a window that had some -> flag
                               # (the transition is the signal; a cold start or an
                               # all-night dry band never had xp to lose)


class KpiMonitor:
    """Capability-KPI watcher: fielded-collapse and xp-stall, one [anomaly] each,
    per-family cooldown. Fed every frame (xp) + every village frame (fielded/bench)."""

    def __init__(self, collapse_ticks: int = FIELDED_COLLAPSE_TICKS,
                 collapse_max: int = FIELDED_COLLAPSE_MAX,
                 bench_min: int = FIELDED_BENCH_MIN,
                 stall_window: int = XP_STALL_WINDOW,
                 cooldown_ticks: int = COOLDOWN_TICKS) -> None:
        self.collapse_ticks = collapse_ticks
        self.collapse_max = collapse_max
        self.bench_min = bench_min
        self.stall_window = stall_window
        self.cooldown = cooldown_ticks
        self._collapse_since: int | None = None
        self._xp_ticks: deque[int] = deque()
        self._last_flagged: dict[str, int] = {}

    def note_xp(self, tick: int, n: int) -> None:
        """Register xp events seen on ANY frame (they happen in the field; the
        village frame that carries fielded/bench never sees them)."""
        for _ in range(max(0, n)):
            self._xp_ticks.append(tick)
        while self._xp_ticks and tick - self._xp_ticks[0] > 2 * self.stall_window:
            self._xp_ticks.popleft()

    def _cooled(self, family: str, tick: int) -> bool:
        last = self._last_flagged.get(family)
        return last is None or tick - last >= self.cooldown

    def observe(self, tick: int, fielded: int, bench: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if fielded <= self.collapse_max and bench >= self.bench_min:
            if self._collapse_since is None:
                self._collapse_since = tick
            elif (tick - self._collapse_since >= self.collapse_ticks
                  and self._cooled("fielded_collapse", tick)):
                self._last_flagged["fielded_collapse"] = tick
                out.append({
                    "subtype": "kpi:fielded_collapse",
                    "detail": (f"fielded {fielded} for {tick - self._collapse_since} "
                               f"ticks with {bench} on the bench — the roster can "
                               "embark and is not"),
                })
        else:
            self._collapse_since = None
        recent = sum(1 for t in self._xp_ticks if tick - t <= self.stall_window)
        prior = sum(1 for t in self._xp_ticks
                    if self.stall_window < tick - t <= 2 * self.stall_window)
        if recent == 0 and prior >= 1 and self._cooled("xp_stall", tick):
            self._last_flagged["xp_stall"] = tick
            out.append({
                "subtype": "kpi:xp_stall",
                "detail": (f"zero xp in {self.stall_window} ticks after {prior} "
                           "in the window before — the leveling engine stopped"),
            })
        return out
