"""GuildBot — the plumbing between the client and a strategy.

It owns what every strategy needs but should not re-implement: persistent
per-world map memory (frames only show current vision), the per-character
decision-trace lifecycle, and access to server config/guild snapshots. The
strategy decides; the bot remembers and records.
"""

from __future__ import annotations

from typing import Any

from . import nav
from .reasoning import DecisionTrace
from .storage import Storage
from .strategy import FieldContext, Strategy, get_strategy

CONTAINER_KINDS = frozenset({"chest", "safe"})


class GuildBot:
    def __init__(self, strategy: Strategy | str = "explorer", storage: Storage | None = None):
        self.strategy: Strategy = get_strategy(strategy) if isinstance(strategy, str) else strategy
        self.storage = storage
        self.known: dict[str, dict[tuple[int, int], str]] = {}   # world -> tiles
        self.tick = 0
        self.config: dict[str, Any] = {}
        self.guild: dict[str, Any] = {}
        self.client: Any = None   # set by Client

    # -- client callbacks -----------------------------------------------------

    def on_hello(self, message: dict[str, Any]) -> None:
        self.config = message.get("config", {}) or {}
        self.guild = message.get("guild", {}) or {}
        self.tick = message.get("tick", 0)
        hook = getattr(self.strategy, "on_hello", None)
        if callable(hook):
            hook(self, message)

    def on_frame(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        self.tick = frame.get("tick", self.tick)
        if frame.get("world") == "village":
            return self.strategy.village(self, frame) or []
        return self._field(frame)

    def on_action_error(self, message: dict[str, Any]) -> None:
        # The client already mirrors errors to storage; give the strategy a look.
        hook = getattr(self.strategy, "on_action_error", None)
        if callable(hook):
            hook(self, message)

    # -- field frame ----------------------------------------------------------

    def _field(self, frame: dict[str, Any]) -> list[dict[str, Any]]:
        world = frame["world"]
        known = self.known.setdefault(world, {})
        visible = frame.get("visible", {}) or {}
        for t in visible.get("tiles", []):
            known[(t[0], t[1])] = t[2]

        enemies = {tuple(e["pos"]): e for e in visible.get("entities", [])
                   if e.get("faction") == "monster"}
        loot = {tuple(i["pos"]) for i in visible.get("items", [])}
        gold = {tuple(g["pos"]) for g in visible.get("gold", [])}
        # characters (ours and rivals') block a step as hard as a wall, and a
        # bounced move still costs stamina.
        bodies = {tuple(c["pos"]) for c in frame.get("chars", [])}
        bodies |= {tuple(e["pos"]) for e in visible.get("entities", [])
                   if e.get("faction") == "guild"}
        containers = {p for p, k in known.items() if k in CONTAINER_KINDS}

        ctx = FieldContext(world=world, known=known, enemies=enemies, loot=loot,
                           gold=gold, bodies=bodies, containers=containers)

        actions: list[dict[str, Any]] = []
        for char in frame.get("chars", []):
            trace = DecisionTrace(tick=self.tick, world=world,
                                  char_uid=char["char_uid"])
            self.strategy.act(self, char, frame, ctx, trace)
            action = trace.decide()
            trace.record(self.storage, self.strategy.version)
            if action:
                actions.append(action)
                # Reserve this character's move destination so a later character
                # in the same frame won't pick the same tile — two of our own
                # moving onto one tile is a bounce (move_failed) for one of them.
                if action.get("action") == "move" and action.get("dir") in nav.DIRS:
                    dx, dy = nav.DIRS[action["dir"]]
                    ctx.bodies.add((char["pos"][0] + dx, char["pos"][1] + dy))
        return actions
