"""``explorer`` — explore-first baseline: discover content, stay alive, bank loot.

Recruits a roster, spreads it across all three maps to *discover* content, fights
what's adjacent, grabs loot, cracks containers, pushes north, and walks home to
heal and sell when hurt or full. Every branch is a scored candidate on the trace,
so the reasoning is legible.

v0.2.0 — from the first live window (explorer/0.1.0 had ~50% move_failed and a
9.9% action-error rate dominated by not_enough_stamina):
  * **Monster tiles are blocked for pathing** (attack when adjacent, route around
    otherwise) — the baseline stepped onto monsters and bounced.
  * **Every action is gated by its stamina cost** — a character that cannot afford
    its best action rests (sends nothing) instead of spamming a doomed action,
    which also reclaims the double idle-regen. The unaffordable want is still
    written to the trace so the reasoning shows why it rested.
"""

from __future__ import annotations

from typing import Any

from .. import nav
from .base import FieldContext
from ..reasoning import DecisionTrace

RETREAT_HP = 0.4            # retreat below 40% HP
KEEP = frozenset({"potion_red"})       # field supplies we never sell
CONTAINERS = frozenset({"chest", "safe"})
DEFAULT_MAPS = ("vale", "mines", "spire")
REST_SCORE = 0.5           # the floor: rest wins only when nothing affordable beats it


class Explorer:
    version = "explorer/0.2.0"

    # -- village: economy + even, discovery-first deployment ------------------

    def village(self, bot: "Any", frame: dict[str, Any]) -> list[dict[str, Any]]:
        guild = frame.get("guild", {})
        cfg = bot.config
        chars = frame.get("chars", [])

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
                self._trace(bot, None, frame.get("world"),
                            [f"{uid} hurt ({char['hp']}/{char['max_hp']}); healing in village"],
                            None, 5.0, "resting in village to heal before embark")
                return []

        here = guild.get("chars_here", [])
        by_world = guild.get("chars_by_world", {})
        fielded = sum(len(v) for v in by_world.values())
        roster = len(here) + fielded
        world_cap = cfg.get("world_cap", 10)
        roster_cap = cfg.get("roster_cap", world_cap)
        if roster < min(world_cap, roster_cap):
            return [self._village_act(bot, None, {"action": "recruit"},
                                      f"recruiting (roster {roster} < cap)")]

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
        cfg = bot.config
        hurt = hp < max_hp * RETREAT_HP
        full = carry["used"] >= carry["cap"] - 1
        # Don't walk onto other characters OR monsters; attack adjacent monsters
        # instead, and route around the rest.
        blocked = ctx.bodies | set(ctx.enemies)

        trace.observe(f"at {pos} hp {hp}/{max_hp} sta {stamina} "
                      f"carry {carry['used']}/{carry['cap']}")

        # Rest is always available (cost 0) and is the floor.
        trace.consider(None, REST_SCORE, f"rest (double regen); stamina {stamina}")

        def offer(action: dict[str, Any], score: float, why: str) -> None:
            """Consider an action only if its stamina cost is affordable; else
            note the unaffordable want on the trace and rest instead."""
            name = action["action"]
            cost = self._cost(name, cfg)
            if stamina >= cost:
                trace.consider(action, score, why)
            else:
                trace.observe(f"wanted {name} ({why}) but stamina {stamina} < ~{cost}: resting")

        # Heal / flee when hurt.
        if hurt:
            trace.observe("hurt: below retreat threshold")
            potion = next((i for i in char.get("inventory", [])
                           if i["kind"] == "potion_red"), None)
            if potion:
                offer({"char_uid": uid, "action": "use", "item_id": potion["item_id"]},
                      9.0, "drinking a red potion to recover HP")
            self._retreat(uid, pos, ctx, blocked, offer, 8.5, "hurt — walking home to heal")

        # Fight what's adjacent (weakest first).
        adj = [p for p in nav.neighbors(pos) if p in ctx.enemies]
        if adj:
            weakest = min(adj, key=lambda p: ctx.enemies[p].get("hp_frac", 1.0))
            e = ctx.enemies[weakest]
            offer({"char_uid": uid, "action": "attack", "target": list(weakest)},
                  8.0, f"attack adjacent {e.get('kind','?')} (hp {e.get('hp_frac',1):.0%})")

        # Bank when full.
        if full:
            self._retreat(uid, pos, ctx, blocked, offer, 7.5,
                          "pack full — heading home to sell")

        # Loot underfoot / nearby.
        if pos in ctx.loot or pos in ctx.gold:
            offer({"char_uid": uid, "action": "pickup"}, 6.0, "loot underfoot — grab it")
        else:
            step = self._step(pos, lambda p: p in ctx.loot or p in ctx.gold, ctx, blocked)
            if step:
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                      4.0, "moving toward visible loot")

        # Crack an adjacent container.
        box = next((p for p in nav.neighbors(pos) if p in ctx.containers), None)
        if box:
            offer({"char_uid": uid, "action": "open", "target": list(box)},
                  5.0, "opening an adjacent container")

        # Close on a visible-but-not-adjacent monster: step to a tile beside it.
        if ctx.enemies and not adj:
            near = self._step(pos, lambda p: any(n in ctx.enemies for n in nav.neighbors(p)),
                              ctx, blocked)
            if near:
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, near)},
                      3.5, "closing to attack range on a monster")

        # Explore — push north into the unknown, else any frontier.
        north = self._step(pos, lambda p: p[1] > pos[1] and nav.frontier(p, ctx.known), ctx, blocked)
        if north:
            offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, north)},
                  2.5, "pushing north into unexplored ground")
        any_frontier = self._step(pos, lambda p: nav.frontier(p, ctx.known), ctx, blocked)
        if any_frontier:
            offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, any_frontier)},
                  2.0, "heading to the nearest frontier")

        # Last resort: any legal step (never onto a body or monster).
        for d, (dx, dy) in nav.DIRS.items():
            nxt = (pos[0] + dx, pos[1] + dy)
            if nav.is_walkable(nxt, ctx.known, blocked):
                offer({"char_uid": uid, "action": "move", "dir": d}, 1.0,
                      "no goal reachable — stepping to scout")
                break

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _cost(action_name: str, cfg: dict[str, Any]) -> int:
        """Conservative stamina cost per action, from server config where known.
        Conservative (base costs, ignoring stat discounts) so we err toward
        resting rather than a rejected action."""
        move = cfg.get("move_stamina", 20)
        item = cfg.get("item_stamina", 10)
        punch = cfg.get("punch_stamina", 20)
        return {
            "move": move, "ride": cfg.get("ride_stamina", 12),
            "attack": punch, "charge": punch, "throw": 15,
            "use": item, "pickup": item, "drop": item, "equip": item,
            "open": item, "taste": item,
        }.get(action_name, item)

    def _retreat(self, uid, pos, ctx, blocked, offer, score, why):
        if pos[1] == 0:
            offer({"char_uid": uid, "action": "move", "dir": "S"}, score,
                  why + " (stepping off the south edge to the village)")
            return
        step = self._step(pos, lambda p: p[1] == 0, ctx, blocked)
        if step:
            offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)}, score, why)

    @staticmethod
    def _step(pos, is_goal, ctx: FieldContext, blocked):
        return nav.bfs_step(pos, is_goal, ctx.known, blocked)

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

    def on_hello(self, bot, hello):
        pass
