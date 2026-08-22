"""The strategy interface and the per-tick field context passed to it."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:  # avoid a runtime import cycle with bot.py
    from ..bot import GuildBot
    from ..reasoning import DecisionTrace


@dataclass
class FieldContext:
    """Everything a strategy needs about the current map frame, pre-digested so
    each character's decision does not re-parse the frame. ``known`` is the
    guild's accumulated memory of this world, not just what's visible now."""

    world: str
    known: dict[tuple[int, int], str]
    enemies: dict[tuple[int, int], dict[str, Any]] = field(default_factory=dict)
    loot: set[tuple[int, int]] = field(default_factory=set)
    gold: set[tuple[int, int]] = field(default_factory=set)
    bodies: set[tuple[int, int]] = field(default_factory=set)   # tiles held by chars
    containers: set[tuple[int, int]] = field(default_factory=set)
    # v0.80.1: tiles SEEN THIS RUN — the verified subset of `known`. Long-range routing
    # charges nav.STALE_COST to walk on memory-only tiles; None means "no freshness data,
    # treat everything as fresh" so tests and replays without it are unaffected.
    fresh: "set[tuple[int, int]] | None" = None
    # v0.70.0: the world's [width, height] from the frame, so `nav.frontier` can tell the
    # unexplored from the edge of the map. Optional: without it nav keeps its old,
    # edge-blind behaviour.
    bounds: tuple[int, int] | None = None


@runtime_checkable
class Strategy(Protocol):
    """A strategy turns frames into actions and fills decision traces.

    ``version`` must change whenever behaviour changes, so metrics attribute to
    the right code. The improvement loop stamps this into ``decisions`` and
    ``runs``.
    """

    version: str

    def on_hello(self, bot: "GuildBot", hello: dict[str, Any]) -> None: ...

    def village(self, bot: "GuildBot", frame: dict[str, Any]) -> list[dict[str, Any]]:
        """Guild-level decisions in the village (recruit/embark/sell/equip)."""
        ...

    def act(
        self,
        bot: "GuildBot",
        char: dict[str, Any],
        frame: dict[str, Any],
        ctx: FieldContext,
        trace: "DecisionTrace",
    ) -> None:
        """Fill ``trace`` with observations and scored candidates for one
        character on a map. The bot calls ``trace.decide()`` afterwards."""
        ...
