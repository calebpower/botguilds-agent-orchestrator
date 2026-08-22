"""In-world flavour text: the guild says what it just did.

`say` is map-visible flavour with no mechanical effect (docs/03-actions.md: text <= 40
chars). It buys the bot nothing, and it is on the wishlist because the operator watches
this guild play — a line in the world is how a run reads as a story rather than as a
frame counter.

Three constraints shape the whole module.

FREE OR NOT AT ALL. The village loop returns at most one action per tick, so chatter is
offered only on a tick that produced nothing else. It can never displace a buy, a sale,
an embark or a recruit; the worst case is that a benched character — and we carry a bench
of ~14-20 — spends an idle tick talking.

WHAT IT SAYS MUST BE TRUE. Every line is keyed to an event the server actually sent us
this run: a forge, a smelt, a chest, a death. A generated boast that nothing backs is a
worse version of the same reporting problem the claims ledger exists to fix, and it would
be the one part of the system where prose is not accountable to the record.

TEXT FROM THE SERVER IS UNTRUSTED. Item and world names are interpolated into what we
broadcast, so they are the injection path: a crafted item name reaching `say` is us
publishing someone else's text under our guild's name. `_clean` whitelists and truncates,
and the length cap is enforced on the FINAL string, after interpolation, never before.
"""

from __future__ import annotations

import re
from typing import Any

MAX_LEN = 40                # docs/03-actions.md
COOLDOWN = 300              # ticks between lines — occasional, not a firehose
FAIL_LIMIT = 3              # consecutive rejections after which we stop trying entirely

# The whitelist is deliberately tighter than "what the server might send": lowercase,
# digits, space, dash, underscore. Anything else is dropped rather than escaped, because
# we do not know what the chat renderer treats as markup.
_UNSAFE = re.compile(r"[^a-z0-9 _-]")


def _clean(value: Any, cap: int = 16) -> str:
    """Whitelist and truncate a server-supplied token."""
    return _UNSAFE.sub("", str(value).lower())[:cap].strip()


# Templates take exactly the fields listed. Keep them short: the cap is enforced, and a
# truncated boast reads worse than a brief one.
_LINES: dict[str, tuple[str, ...]] = {
    "forged":    ("forged a {item}. still got it.", "new {item}, straight off the anvil."),
    "smelted":   ("another ingot out of the mines.", "ore in, ingot out."),
    "brewed":    ("brewed a {item}. cheers.", "fresh {item}. drink up."),
    "opened":    ("cracked another chest.", "that chest was ours."),
    "stat_up":   ("stronger than yesterday.", "levelling nicely."),
    "equip":     ("kitted out with a {item}.", "{item} equipped. much better."),
    "death":     ("we lost one in the {world}.", "the {world} took one of ours."),
}

_IDLE = ("{roster} of us, {gold}g banked.", "stanley steemer, still standing.",
         "{gold}g in the vault and counting.")


class Chatter:
    """Decides whether to say something, and what. Holds only its own state."""

    def __init__(self) -> None:
        self._last_said: int = -10 ** 9
        self._fails: int = 0
        self._recent: tuple[str, dict] | None = None

    # -- inputs ------------------------------------------------------------------

    def note_events(self, events: list[dict[str, Any]], ours: set[str] | None = None) -> None:
        """Remember the most recent notable event. `ours`, when given, filters by
        char_uid — chatter must never boast about a RIVAL's forge, which is exactly the
        attribution error that cost us a retracted claim."""
        for ev in events or []:
            kind = ev.get("kind")
            if kind not in _LINES:
                continue
            if ours is not None and ev.get("char_uid") not in ours:
                continue
            self._recent = (kind, dict(ev))

    def note_rejected(self) -> None:
        """The server refused a `say`. Three of those and we stop for the run."""
        self._fails += 1

    def note_accepted(self) -> None:
        self._fails = 0

    @property
    def disabled(self) -> bool:
        return self._fails >= FAIL_LIMIT

    # -- output ------------------------------------------------------------------

    def peek(self, tick: int, gold: int = 0, roster: int = 0) -> str | None:
        """The line we WOULD say, with no side effects. None is the common answer.

        Split from `commit` in v0.75.0, when the say moved into the field ladder. There an
        offer competes and usually loses, and a `line()` that marked itself said on the way
        past would burn the cooldown — and spend the one event we had to talk about — on a
        tick where nothing was ever broadcast. The offer asks; only the send commits.
        """
        if self.disabled or tick - self._last_said < COOLDOWN:
            return None
        variants, fields = _IDLE, {}
        if self._recent is not None:
            kind, ev = self._recent
            variants = _LINES[kind]
            fields = {"item": _clean(ev.get("item") or ev.get("kind_name") or "thing"),
                      "world": _clean(ev.get("world") or "field")}
        fields.setdefault("gold", int(gold))
        fields.setdefault("roster", int(roster))
        # Rotate deterministically. Randomness here would be untestable and unreplayable
        # for no benefit — the tick already varies.
        text = variants[(tick // COOLDOWN) % len(variants)]
        try:
            text = text.format(**fields)
        except (KeyError, IndexError, ValueError):
            return None
        text = text[:MAX_LEN]
        return text or None

    def commit(self, tick: int) -> None:
        """Called when a `say` is actually sent: start the cooldown, spend the event."""
        self._last_said = tick
        self._recent = None      # say each thing once

    def line(self, tick: int, gold: int = 0, roster: int = 0) -> str | None:
        """peek + commit, for callers that send whatever they are given."""
        text = self.peek(tick, gold=gold, roster=roster)
        if text is not None:
            self.commit(tick)
        return text
