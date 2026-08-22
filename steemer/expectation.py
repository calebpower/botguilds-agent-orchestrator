"""Expectation vs reality: does what we predicted actually happen?

An operator request, and four consecutive passes made the case for it. Every one of these
shipped past a GREEN gate and was only caught by hand, days or hours later:

  * v0.54.0 vein-seek fired 751 times and NO CHARACTER WAS EVER ADJACENT TO A VEIN. The
    expectation "I am walking toward ore" was violated on every single tick.
  * v0.49.0 bought six clubs for one character. "After `buy club`, a club appears in my
    inventory" was violated five times in a row before the intent latch was written.
  * Two characters were entombed and bled out at full stamina because a tile was blacklisted
    on a stale frame. "After `move S` my position becomes (7,35)" was violated three ticks
    running with nothing watching.
  * v0.35.0's potion reserve rested on "heals are 99.6% free-brewed". Brewing stopped, the
    premise silently stopped being true, and nothing noticed for many runs.

The pattern is one thing: a belief the frames contradict, and no mechanism that compares the
two. v0.49's intent latch and v0.50's server-driven learned-block are both this idea in
miniature, each scoped to one case. This generalises it.

DERIVED, NOT DECLARED. Predictions are read from the ACTION we sent rather than added by
hand at each `offer()` site. Two reasons: a prediction written next to the offer is a second
place to keep in sync (exactly the duplication that would have sold a newly decoded vigor
herb in v0.59.0), and hand-written predictions cover only the cases someone thought of --
which is precisely the failure mode being fixed. Every action of a known kind gets checked,
including the ones nobody suspects.

THE TRAP THIS MUST NOT FALL INTO, named in the wishlist entry before a line was written:
frames are STALE, so "it has not happened yet" must never read as "it did not happen". That
confusion is the direct cause of both deaths above. Every prediction therefore gets a GRACE
WINDOW and can only be called violated after it, and a prediction still unresolved when its
window closes expires QUIETLY -- `expired` is not `violated`.

What this does NOT do: judge whether the decision was WISE. It only checks whether the world
did what the action implied. A character can walk confidently toward a vein that was mined
out an hour ago and every position prediction will confirm.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Callable

# How long a prediction may stay unresolved before it expires. Generous on purpose: a
# server tick is not a frame, actions queue, and the whole point is to avoid mistaking
# lag for a lie. Sized from the observed action->effect latency (a forge takes 10-14
# ticks by its own `forge_started` event), not from a guess about the network.
GRACE_TICKS = 30

# A violation RATE this high within the window is worth shouting about. Kept as a rate
# rather than a count because a quiet band produces few predictions of any kind, and a
# count would make the alarm quieter exactly when the bot is least busy.
WINDOW_TICKS = 600
MIN_RESOLVED = 25          # never rule on a handful; the v0.48.0 warm-up misread again
SPIKE_RATE = 0.5           # >= half of resolved predictions violated => something is wrong
COOLDOWN_TICKS = 1200


def _pos(char: dict[str, Any]) -> tuple[int, int] | None:
    p = char.get("pos")
    return (p[0], p[1]) if isinstance(p, (list, tuple)) and len(p) == 2 else None


def _kinds(char: dict[str, Any]) -> list[str]:
    return [i.get("kind") for i in (char.get("inventory") or [])]


DIRS: dict[str, tuple[int, int]] = {
    "N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0),
}


class Prediction:
    """One checkable claim about the near future, with the evidence to judge it."""

    __slots__ = ("uid", "action", "tick", "label", "check", "_before")

    def __init__(self, uid: str, action: str, tick: int, label: str,
                 check: Callable[[dict[str, Any]], bool | None], before: Any = None):
        self.uid = uid
        self.action = action
        self.tick = tick
        self.label = label
        self.check = check
        self._before = before


class ExpectationMonitor:
    """Derives predictions from issued actions and resolves them against later frames.

    Resolution is three-valued and the third value is the important one:
      confirmed — the world did what the action implied
      violated  — the world demonstrably did NOT, after the grace window
      expired   — we never got a good look; NOT evidence of anything
    """

    def __init__(self, grace_ticks: int = GRACE_TICKS, window_ticks: int = WINDOW_TICKS,
                 min_resolved: int = MIN_RESOLVED, spike_rate: float = SPIKE_RATE,
                 cooldown_ticks: int = COOLDOWN_TICKS) -> None:
        self.grace = grace_ticks
        self.window = window_ticks
        self.min_resolved = min_resolved
        self.spike_rate = spike_rate
        self.cooldown = cooldown_ticks
        self._open: list[Prediction] = []
        self._recent: deque[tuple[int, str, bool]] = deque()   # (tick, action, violated)
        self.totals: dict[str, dict[str, int]] = defaultdict(
            lambda: {"confirmed": 0, "violated": 0, "expired": 0})
        self.violations: deque[dict[str, Any]] = deque(maxlen=50)
        self._last_alarm = -10 ** 9

    # -- recording -------------------------------------------------------------

    def record_actions(self, tick: int, actions: list[dict[str, Any]],
                       chars: list[dict[str, Any]]) -> None:
        """Derive a prediction from each action we are about to send."""
        by_uid = {c.get("char_uid"): c for c in chars}
        for a in actions:
            uid = a.get("char_uid")
            char = by_uid.get(uid)
            if char is None:
                continue
            p = self._predict(uid, a, tick, char)
            if p is not None:
                self._open.append(p)

    def _predict(self, uid: str, a: dict[str, Any], tick: int,
                 char: dict[str, Any]) -> Prediction | None:
        name = a.get("action")
        if name == "move":
            start = _pos(char)
            d = DIRS.get(a.get("dir"))
            if start is None or d is None:
                return None
            target = (start[0] + d[0], start[1] + d[1])
            # MOVED, not "reached the target": a bounce leaves us exactly where we were,
            # which is the observable we care about, while the server may legitimately
            # place us elsewhere (knockback, a portal). Anything but standing still counts.
            return Prediction(uid, "move", tick, f"move {a.get('dir')} from {start}",
                              lambda c, s=start: (None if _pos(c) is None
                                                  else _pos(c) != s), start)
        if name == "pickup":
            n = len(_kinds(char))
            return Prediction(uid, "pickup", tick, f"pickup (holding {n})",
                              lambda c, n=n: len(_kinds(c)) > n, n)
        if name == "buy" and a.get("kind"):
            kind = a["kind"]
            n = _kinds(char).count(kind)
            return Prediction(uid, "buy", tick, f"buy {kind} (holding {n})",
                              lambda c, k=kind, n=n: _kinds(c).count(k) > n, n)
        if name == "equip" and a.get("slot"):
            slot = a["slot"]
            return Prediction(uid, "equip", tick, f"equip -> {slot}",
                              lambda c, s=slot: (c.get("equipment") or {}).get(s) is not None)
        if name == "sell":
            n = len(_kinds(char))
            return Prediction(uid, "sell", tick, f"sell (holding {n})",
                              lambda c, n=n: len(_kinds(c)) < n, n)
        return None

    # -- resolution ------------------------------------------------------------

    def observe(self, tick: int, chars: list[dict[str, Any]]) -> None:
        """Resolve what this frame settles; expire what has run out of grace."""
        by_uid = {c.get("char_uid"): c for c in chars}
        still_open: list[Prediction] = []
        for p in self._open:
            char = by_uid.get(p.uid)
            verdict = None if char is None else p.check(char)
            if verdict is True:
                self._resolve(p, tick, violated=False)
                continue
            if tick - p.tick < self.grace:
                still_open.append(p)          # too early to judge — this is the whole point
                continue
            if verdict is False:
                self._resolve(p, tick, violated=True)
            else:
                # Never got a look at the character: silence is not evidence.
                self.totals[p.action]["expired"] += 1
        self._open = still_open
        self._trim(tick)

    def _resolve(self, p: Prediction, tick: int, violated: bool) -> None:
        self.totals[p.action]["violated" if violated else "confirmed"] += 1
        self._recent.append((tick, p.action, violated))
        if violated:
            self.violations.append({"tick": tick, "char_uid": p.uid,
                                    "action": p.action, "expected": p.label})

    def _trim(self, tick: int) -> None:
        while self._recent and tick - self._recent[0][0] > self.window:
            self._recent.popleft()

    # -- reporting -------------------------------------------------------------

    def alarm(self, tick: int) -> dict[str, Any] | None:
        """A violation rate worth waking someone for, or None.

        PER ACTION FAMILY, not in aggregate, and that distinction is the difference
        between this being useful and decorative. The first real run showed why: `move`
        resolved 29,779 times against `pickup`'s 901, so a `pickup` that was failing NINE
        TIMES IN TEN came to 2.6% of the total and would never have tripped an aggregate
        threshold. The signal lives in the family, exactly as it does in anomaly.py.

        Refuses to rule on a small sample (MIN_RESOLVED, per family) for the same reason
        `shadow.MIN_DECISIONS` does: v0.48.0 was declared inert from 28 offers and was not.
        A detector that cries wolf during warm-up gets ignored precisely when it is right.
        """
        self._trim(tick)
        if tick - self._last_alarm < self.cooldown:
            return None
        per: dict[str, list[int]] = defaultdict(lambda: [0, 0])   # action -> [resolved, bad]
        for _, action, v in self._recent:
            per[action][0] += 1
            per[action][1] += int(v)
        worst = None
        for action, (resolved, bad) in per.items():
            if resolved < self.min_resolved:
                continue
            rate = bad / resolved
            if rate >= self.spike_rate and (worst is None or rate > worst[1]):
                worst = (action, rate, resolved, bad)
        if worst is None:
            return None
        self._last_alarm = tick
        action, rate, resolved, bad = worst
        # `subtype` and `detail` are the contract GuildBot._report_anomaly reads (it does
        # `a["subtype"]` and prints `a["detail"]`), and record_anomaly stores subtype as the
        # queryable column the dashboard groups by. Emitting a dict without them raised a
        # KeyError inside on_frame -- caught here before shipping, and pinned by a test,
        # because "the caller's expectations" is exactly the un-enumerated input that has
        # bitten this project twice (the 0.51.0 segfault, the 0.54.0 inert seek).
        return {"kind": "expectation_mismatch",
                "subtype": f"expectation_mismatch:{action}",
                "detail": (f"{bad}/{resolved} {action} predictions violated "
                           f"({rate:.0%}) in the last {self.window} ticks"),
                "tick": tick, "action": action,
                "rate": round(rate, 3), "resolved": resolved, "violated": bad}

    def summary(self) -> dict[str, dict[str, Any]]:
        """Per-action confirmed/violated/expired counts and the confirmation rate.

        `expired` is reported alongside rather than folded in: a high expiry rate means we
        are not SEEING our characters, which is a different problem from being wrong about
        them, and averaging the two would hide both.
        """
        out: dict[str, dict[str, Any]] = {}
        for action, t in sorted(self.totals.items()):
            ruled = t["confirmed"] + t["violated"]
            out[action] = dict(t, ruled=ruled,
                               confirm_rate=round(t["confirmed"] / ruled, 3) if ruled else None)
        return out
