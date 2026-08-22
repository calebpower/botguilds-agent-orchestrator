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
FAIL_LIMIT = 3              # rejections within FAIL_WINDOW after which we stop entirely
FAIL_WINDOW = 3 * COOLDOWN  # ...and they must be RECENT. v0.75.1 counted rejections for the
                            # life of the run and had no way to un-count one, so three
                            # transients hours apart would silence the guild for good.
                            # Run #156 shows the transient: a `say` decided in the field
                            # and rejected `not_in_village`, because the character had gone
                            # home between the frame we read and the action landing. Three
                            # inside three cooldowns means the last three attempts all
                            # failed, which is the "the server does not accept this" case
                            # the limit was written for; isolated ones age out.

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

# Split by what they need to be TRUE. The gold lines are only sayable when we actually
# know the treasury: guild gold arrives on VILLAGE frames, and a character in the field has
# no idea. v0.75.0 broadcast "5 of us, 0g banked." while the guild held 139 — a false
# statement, published under our name, from the one module whose whole rule is that it only
# says things that happened.
_IDLE_ALWAYS = ("stanley steemer, still standing.", "{roster} of us, still out here.")
_IDLE_WITH_GOLD = ("{roster} of us, {gold}g banked.", "{gold}g in the vault and counting.")


class Chatter:
    """Decides whether to say something, and what. Holds only its own state."""

    def __init__(self) -> None:
        self._last_said: int = -10 ** 9
        self._fails: list[int] = []
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

    def note_rejected(self, tick: int = 0) -> None:
        """The server refused a `say`. Three inside FAIL_WINDOW and we stop for the run."""
        self._fails.append(tick)

    def recent_failures(self, tick: int) -> int:
        return sum(1 for t in self._fails if tick - t < FAIL_WINDOW)

    @property
    def disabled(self) -> bool:
        """Whether the LAST recorded failures alone are enough to stop us.

        Kept as a property because callers ask before they have a tick to hand; it reads
        the newest failure as `now`, which is the only honest reading available without
        one.
        """
        return bool(self._fails) and self.recent_failures(max(self._fails)) >= FAIL_LIMIT

    # -- output ------------------------------------------------------------------

    def peek(self, tick: int, gold: int | None = None, roster: int = 0) -> str | None:
        """The line we WOULD say, with no side effects. None is the common answer.

        Split from `commit` in v0.75.0, when the say moved into the field ladder. There an
        offer competes and usually loses, and a `line()` that marked itself said on the way
        past would burn the cooldown — and spend the one event we had to talk about — on a
        tick where nothing was ever broadcast. The offer asks; only the send commits.
        """
        if self.recent_failures(tick) >= FAIL_LIMIT or tick - self._last_said < COOLDOWN:
            return None
        variants = _IDLE_ALWAYS + (_IDLE_WITH_GOLD if gold is not None else ())
        fields: dict = {}
        if self._recent is not None:
            kind, ev = self._recent
            variants = _LINES[kind]
            fields = {"item": _clean(ev.get("item") or ev.get("kind_name") or "thing"),
                      "world": _clean(ev.get("world") or "field")}
        fields.setdefault("gold", int(gold) if gold is not None else 0)
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

    def line(self, tick: int, gold: int | None = None, roster: int = 0) -> str | None:
        """peek + commit, for callers that send whatever they are given."""
        text = self.peek(tick, gold=gold, roster=roster)
        if text is not None:
            self.commit(tick)
        return text
