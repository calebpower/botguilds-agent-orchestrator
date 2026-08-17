"""``explorer`` — the v0 baseline strategy: explore-first, stay alive, bank loot.

Deliberately broad rather than optimized: it recruits a roster, spreads it
across all three maps to *discover* content, fights what's adjacent, grabs loot,
cracks containers, pushes north into the unknown, and walks home to heal and
sell when hurt or full. The improvement loop specializes it from here, guided by
metrics. Every branch is a scored candidate on the trace, so the reasoning is
legible.
"""

from __future__ import annotations

from typing import Any

from .. import nav
from .base import FieldContext
from ..reasoning import DecisionTrace

RETREAT_HP = 0.4            # retreat below 40% HP
LOW_STAMINA = 25           # below this, resting usually beats a doomed action
MIN_AFFORD = 10            # below this, almost nothing is affordable — rest
KEEP = frozenset({"potion_red"})       # field supplies we never sell
CONTAINERS = frozenset({"chest", "safe"})
DEFAULT_MAPS = ("vale", "mines", "spire")


class Explorer:
    version = "explorer/0.1.0"

    # -- village: economy + even, discovery-first deployment ------------------

    def village(self, bot: "Any", frame: dict[str, Any]) -> list[dict[str, Any]]:
        guild = frame.get("guild", {})
        cfg = bot.config
        chars = frame.get("chars", [])

        # 1) sell the haul (keep field supplies), arm the unarmed, heal first.
        for char in chars:
            uid = char["char_uid"]
            for item in char.get("inventory", []):
                if item["kind"] not in KEEP:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "sell",
                                   "item_id": item["item_id"]},
                        f"selling {item['kind']} (tier {item.get('tier')}) to bank gold")]
            weapon = "shortsword" if char.get("stats", {}).get("str", 0) >= 4 else "club"
            if char.get("equipment", {}).get("hand") is None:
                owned = next((i for i in char.get("inventory", [])
                              if i["kind"] == weapon), None)
                if owned:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "equip",
                                   "item_id": owned["item_id"], "slot": "hand"},
                        f"equipping {weapon} before embarking")]
                if guild.get("gold", 0) >= 45:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": weapon},
                        f"buying a {weapon} (STR {char.get('stats',{}).get('str')})")]
            if char.get("hp", 0) < char.get("max_hp", 1):
                # idling in the village heals fast — wait before shipping out
                self._trace(bot, None, frame.get("world"),
                            [f"{uid} hurt ({char['hp']}/{char['max_hp']}); healing in village"],
                            None, 5.0, "resting in village to heal before embark")
                return []

        # 2) keep the roster full.
        here = guild.get("chars_here", [])
        by_world = guild.get("chars_by_world", {})
        fielded = sum(len(v) for v in by_world.values())
        roster = len(here) + fielded
        world_cap = cfg.get("world_cap", 10)
        roster_cap = cfg.get("roster_cap", world_cap)
        if roster < min(world_cap, roster_cap):
            return [self._village_act(bot, None, {"action": "recruit"},
                                      f"recruiting (roster {roster} < cap)")]

        # 3) deploy evenly across maps — discovery-first.
        if here and fielded < world_cap:
            maps = [m["id"] for m in cfg.get("maps", [])] or list(DEFAULT_MAPS)
            party_cap = cfg.get("party_cap", 5)
            target = min(maps, key=lambda m: len(by_world.get(m, [])))
            if len(by_world.get(target, [])) < party_cap:
                return [self._village_act(
                    bot, None, {"action": "embark", "map": target,
                                "char_uids": [here[0]]},
                    f"embarking to {target} (fewest of us there — spread to explore)")]
        return []

    # -- field: per-character scored decision ---------------------------------

    def act(self, bot: "Any", char: dict[str, Any], frame: dict[str, Any],
            ctx: FieldContext, trace: DecisionTrace) -> None:
        uid = char["char_uid"]
        pos = tuple(char["pos"])
        hp, max_hp = char.get("hp", 0), char.get("max_hp", 1)
        stamina = char.get("stamina", 0)
        carry = char.get("carry", {"used": 0, "cap": 1})
        hurt = hp < max_hp * RETREAT_HP
        full = carry["used"] >= carry["cap"] - 1

        trace.observe(f"at {pos} hp {hp}/{max_hp} sta {stamina} "
                      f"carry {carry['used']}/{carry['cap']}")

        # Resting is always an option; it dominates when too tired to act.
        if stamina < MIN_AFFORD:
            trace.consider(None, 100.0, f"stamina {stamina} < {MIN_AFFORD}: can afford nothing, rest")
            return
        rest_score = 6.5 if stamina < LOW_STAMINA else 0.5
        trace.consider(None, rest_score,
                       f"rest (double regen); stamina {stamina}")

        # Heal / flee when hurt.
        if hurt:
            trace.observe("hurt: below retreat threshold")
            potion = next((i for i in char.get("inventory", [])
                           if i["kind"] == "potion_red"), None)
            if potion:
                trace.consider({"char_uid": uid, "action": "use",
                                "item_id": potion["item_id"]}, 9.0,
                               "drinking a red potion to recover HP")
            exit_step = self._toward(pos, lambda p: p[1] == 0, ctx)
            self._retreat_candidate(uid, pos, exit_step, ctx, trace, 8.5,
                                    "hurt — walking home to heal")

        # Fight what's adjacent (weakest first).
        adj = [p for p in nav.neighbors(pos) if p in ctx.enemies]
        if adj:
            weakest = min(adj, key=lambda p: ctx.enemies[p].get("hp_frac", 1.0))
            e = ctx.enemies[weakest]
            trace.consider({"char_uid": uid, "action": "attack", "target": list(weakest)},
                           8.0, f"attack adjacent {e.get('kind','?')} "
                                f"(hp {e.get('hp_frac',1):.0%}, weakest nearby)")

        # Bank when full.
        if full:
            exit_step = self._toward(pos, lambda p: p[1] == 0, ctx)
            self._retreat_candidate(uid, pos, exit_step, ctx, trace, 7.5,
                                    "pack full — heading home to sell")

        # Loot underfoot / nearby.
        if pos in ctx.loot or pos in ctx.gold:
            trace.consider({"char_uid": uid, "action": "pickup"}, 6.0,
                           "loot underfoot — grab it")
        elif ctx.loot or ctx.gold:
            step = self._toward(pos, lambda p: p in ctx.loot or p in ctx.gold, ctx)
            if step:
                trace.consider({"char_uid": uid, "action": "move",
                                "dir": nav.step_dir(pos, step)}, 4.0,
                               "moving toward visible loot")

        # Crack an adjacent container.
        box = next((p for p in nav.neighbors(pos) if p in ctx.containers), None)
        if box:
            trace.consider({"char_uid": uid, "action": "open", "target": list(box)},
                           5.0, "opening an adjacent container")

        # Explore — push north into the unknown, else any frontier.
        north = self._toward(pos, lambda p: p[1] > pos[1] and nav.frontier(p, ctx.known), ctx)
        if north:
            trace.consider({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, north)},
                           2.5, "pushing north into unexplored ground")
        any_frontier = self._toward(pos, lambda p: nav.frontier(p, ctx.known), ctx)
        if any_frontier:
            trace.consider({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, any_frontier)},
                           2.0, "heading to the nearest frontier")

        # Last resort: any legal step, so a boxed-in char still moves/scouts.
        for d, (dx, dy) in nav.DIRS.items():
            nxt = (pos[0] + dx, pos[1] + dy)
            if nav.is_walkable(nxt, ctx.known, ctx.bodies):
                trace.consider({"char_uid": uid, "action": "move", "dir": d}, 1.0,
                               "no goal reachable — stepping to scout")
                break

    # -- helpers --------------------------------------------------------------

    def _retreat_candidate(self, uid, pos, exit_step, ctx, trace, score, why):
        if pos[1] == 0:
            trace.consider({"char_uid": uid, "action": "move", "dir": "S"}, score,
                           why + " (stepping off the south edge to the village)")
        elif exit_step:
            trace.consider({"char_uid": uid, "action": "move",
                            "dir": nav.step_dir(pos, exit_step)}, score, why)

    @staticmethod
    def _toward(pos, is_goal, ctx: FieldContext):
        return nav.bfs_step(pos, is_goal, ctx.known, ctx.bodies)

    def _village_act(self, bot, uid, action, why):
        self._trace(bot, uid, "village", [why], action, 5.0, why)
        return action

    def _trace(self, bot, uid, world, notes, action, score, why):
        t = DecisionTrace(tick=bot.tick, world=world, char_uid=uid)
        for n in notes:
            t.observe(n)
        t.consider(action, score, why)
        t.decide()
        t.record(bot.storage, self.version)

    def on_hello(self, bot, hello):  # optional hook
        pass
