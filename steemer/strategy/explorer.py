"""``explorer`` — explore-first baseline: discover content, stay alive, bank loot.

Recruits a roster, spreads it across all three maps to *discover* content, fights
what's adjacent, grabs loot, cracks containers, pushes north, and walks home to
heal and sell when hurt or full. Every branch is a scored candidate on the trace,
so the reasoning is legible.

v0.2.0 — from the first live window (~50% move_failed, 9.9% action errors):
  * Block monster tiles when pathing (attack adjacent, route around).
  * Gate every action by its stamina cost — rest instead of the unaffordable.

v0.3.0 — from the death analysis (0.31 permadeaths/recruit; 76% died within
~20 s of embarking, ~22% HP, 35% poisoned, and 45% of hurt-decisions "rested"
because they couldn't afford the step home):
  * **Retreat earlier and commit to it.** RETREAT_HP 0.4 -> 0.6 (flee while there
    is still HP *and* stamina to run), poison/burn triggers retreat regardless of
    HP, and a hurt character offers *only* heal/flee — no attack/loot/explore, so
    its scarce stamina goes to escaping, not to the fight that is killing it.
  * **Carry field healing.** The village stocks a `potion_red` per character; the
    field's drink-when-hurt branch was dead code with no ammunition, and a potion
    is the only heal fast enough to outrun poison's tick.

v0.4.0 — 0.3.0 cut the death *rate* 43% but chars now survive-while-poisoned
(status_damage tripled) and were still frozen at their recruit stats (max_hp
24-30) because XP was banked and never spent:
  * **Spend XP for durability.** In the village, pour banked XP into VIT (HP to
    tank poison) then END (stamina to outrun it) then STR, each toward the
    full-rate effective-bonus cap of 8, preferring the character's half-cost
    gifts. This is what turns 0.3.0's survivors into characters that actually grow.
"""

from __future__ import annotations

from typing import Any

from .. import nav
from .base import FieldContext
from ..reasoning import DecisionTrace

RETREAT_HP = 0.6           # flee below 60% HP — early enough to still afford the run
DOT_KINDS = frozenset({"poison", "burn"})   # damage-over-time: flee regardless of HP
KEEP = frozenset({"potion_red"})            # field supplies we never sell
CONTAINERS = frozenset({"chest", "safe"})
DEFAULT_MAPS = ("vale", "mines", "spire")
REST_SCORE = 0.5           # the floor: rest wins only when nothing affordable beats it
POTION_KEEP = 1            # potions to carry into the field per character
POTION_MIN_GOLD = 25       # only buy a potion with this much gold to spare
XP_PRIORITY = ("vit", "end", "str")   # survival first: HP, then stamina, then damage
XP_STAT_TARGET = 8         # grow each toward the full-rate effective-bonus cap


class Explorer:
    version = "explorer/0.4.0"

    # -- village: economy + healing supply + even, discovery-first deployment --

    def village(self, bot: "Any", frame: dict[str, Any]) -> list[dict[str, Any]]:
        guild = frame.get("guild", {})
        cfg = bot.config
        chars = frame.get("chars", [])
        gold = guild.get("gold", 0)

        for char in chars:
            uid = char["char_uid"]
            inv = char.get("inventory", [])
            # 1) sell the haul (keep field supplies).
            for item in inv:
                if item["kind"] not in KEEP:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "sell",
                                   "item_id": item["item_id"]},
                        f"selling {item['kind']} (tier {item.get('tier')}) to bank gold")]
            # 2) arm the unarmed.
            weapon = "shortsword" if char.get("stats", {}).get("str", 0) >= 4 else "club"
            if char.get("equipment", {}).get("hand") is None:
                owned = next((i for i in inv if i["kind"] == weapon), None)
                if owned:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "equip",
                                   "item_id": owned["item_id"], "slot": "hand"},
                        f"equipping {weapon} before embarking")]
                if gold >= 45:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": weapon},
                        f"buying a {weapon} (STR {char.get('stats',{}).get('str')})")]
            # 3) stock a field potion (the only heal fast enough to beat poison).
            potions = sum(1 for i in inv if i["kind"] == "potion_red")
            if potions < POTION_KEEP and gold >= POTION_MIN_GOLD:
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "buy", "kind": "potion_red"},
                    "buying a red potion for the field (survival)")]
            # 4) spend banked XP on durability (safe in the village).
            stat = self._pick_xp_stat(char)
            if stat is not None:
                v = char.get("stats", {}).get(stat, 1)
                gifted = stat in set(char.get("gifts", []))
                cost = self._xp_cost(v, gifted)
                if char.get("xp", 0) >= cost:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "spend_xp", "stat": stat},
                        f"spending XP on {stat} (v{v}->{v+1}, "
                        f"{'gift ' if gifted else ''}cost {cost}) for durability")]
            # 5) heal before shipping out.
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
        statuses = char.get("statuses", []) or []
        dot = any(s.get("kind") in DOT_KINDS for s in statuses)
        hurt = hp < max_hp * RETREAT_HP or dot
        full = carry["used"] >= carry["cap"] - 1
        # Don't walk onto other characters OR monsters.
        blocked = ctx.bodies | set(ctx.enemies)

        trace.observe(f"at {pos} hp {hp}/{max_hp} sta {stamina} "
                      f"carry {carry['used']}/{carry['cap']}"
                      + (f" statuses={[s.get('kind') for s in statuses]}" if statuses else ""))

        # Rest is always available (cost 0) and is the floor.
        trace.consider(None, REST_SCORE, f"rest (double regen); stamina {stamina}")

        def offer(action: dict[str, Any], score: float, why: str) -> None:
            name = action["action"]
            cost = self._cost(name, cfg)
            if stamina >= cost:
                trace.consider(action, score, why)
            else:
                trace.observe(f"wanted {name} ({why}) but stamina {stamina} < ~{cost}: resting")

        # --- Hurt: disengage. Offer ONLY heal + flee, then stop. A hurt char
        # that keeps attacking/looting spends the stamina it needs to escape and
        # dies stuck at low HP (the failure mode the death analysis found). ---
        if hurt:
            reason = "poisoned/burning" if dot and hp >= max_hp * RETREAT_HP else "low HP"
            trace.observe(f"hurt ({reason}) — disengaging, heal or run only")
            potion = next((i for i in char.get("inventory", []) if i["kind"] == "potion_red"), None)
            if potion:
                offer({"char_uid": uid, "action": "use", "item_id": potion["item_id"]},
                      9.0, "drinking a red potion to recover HP")
            self._retreat(uid, pos, ctx, blocked, offer, 8.5, "hurt — walking home to heal")
            return

        # --- Healthy: fight / gather / explore. ---
        adj = [p for p in nav.neighbors(pos) if p in ctx.enemies]
        if adj:
            weakest = min(adj, key=lambda p: ctx.enemies[p].get("hp_frac", 1.0))
            e = ctx.enemies[weakest]
            offer({"char_uid": uid, "action": "attack", "target": list(weakest)},
                  8.0, f"attack adjacent {e.get('kind','?')} (hp {e.get('hp_frac',1):.0%})")

        if full:
            self._retreat(uid, pos, ctx, blocked, offer, 7.5,
                          "pack full — heading home to sell")

        if pos in ctx.loot or pos in ctx.gold:
            offer({"char_uid": uid, "action": "pickup"}, 6.0, "loot underfoot — grab it")
        else:
            step = self._step(pos, lambda p: p in ctx.loot or p in ctx.gold, ctx, blocked)
            if step:
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                      4.0, "moving toward visible loot")

        box = next((p for p in nav.neighbors(pos) if p in ctx.containers), None)
        if box:
            offer({"char_uid": uid, "action": "open", "target": list(box)},
                  5.0, "opening an adjacent container")

        if ctx.enemies and not adj:
            near = self._step(pos, lambda p: any(n in ctx.enemies for n in nav.neighbors(p)),
                              ctx, blocked)
            if near:
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, near)},
                      3.5, "closing to attack range on a monster")

        north = self._step(pos, lambda p: p[1] > pos[1] and nav.frontier(p, ctx.known), ctx, blocked)
        if north:
            offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, north)},
                  2.5, "pushing north into unexplored ground")
        any_frontier = self._step(pos, lambda p: nav.frontier(p, ctx.known), ctx, blocked)
        if any_frontier:
            offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, any_frontier)},
                  2.0, "heading to the nearest frontier")

        for d, (dx, dy) in nav.DIRS.items():
            nxt = (pos[0] + dx, pos[1] + dy)
            if nav.is_walkable(nxt, ctx.known, blocked):
                offer({"char_uid": uid, "action": "move", "dir": d}, 1.0,
                      "no goal reachable — stepping to scout")
                break

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _pick_xp_stat(char: dict[str, Any]) -> str | None:
        """The stat to raise next: survival-priority (VIT>END>STR), each grown to
        the full-rate cap. None once all three are there (bank the rest)."""
        stats = char.get("stats", {})
        for s in XP_PRIORITY:
            if stats.get(s, 0) < XP_STAT_TARGET:
                return s
        return None

    @staticmethod
    def _xp_cost(value: int, gifted: bool) -> int:
        """XP to raise a stat from ``value``: 8·v·2^(v//10), halved for a gift."""
        cost = 8 * value * (2 ** (value // 10))
        return cost // 2 if gifted else cost

    @staticmethod
    def _cost(action_name: str, cfg: dict[str, Any]) -> int:
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
