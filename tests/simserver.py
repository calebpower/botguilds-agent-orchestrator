"""A reverse-engineered BotGuilds server — the pre-deploy test bed (operator directive,
2026-08-24: "if you're... redoing your work because you found a bug after 2 minutes,
then your tests are shit. Consider reverse-engineering the server").

Every bug that escaped the 0.103-0.109 suites was a CONSISTENCY artifact: stale
`chars_here` re-listing departed chars (the 23k-error re-command storm), departure-lag
flaps, phantom vault listings, vision-edge loot flicker, tick stalls. Unit fixtures hand
the bot one coherent frame; the live server is never coherent. This sim's defining
feature is therefore the INCOHERENCE, modeled deliberately:

  * VIEW LAG — the village frame's guild view (chars_here / chars_by_world, and the
    frame's own chars array) trails the true state by `lag` ticks, exactly the window
    that produced the ghost re-command storm and the departure flap.
  * PHANTOM VAULT — a configurable share of guild-inventory ids answer `no_such_item`.
  * MIRAGE ITEMS — items visible only from >= `mirage_dist` tiles, vanishing on
    approach (the vision-edge flicker that produced run #209's dance).
  * CHAOS CLOCK — `stall(n)` freezes the tick counter while frames keep flowing;
    `burst(n)` leaps it (the 2026-08-24 server behavior).

Rules implemented from docs/02-08 + recorded-trace arithmetic: config-driven stamina
costs (move 14 observed with AGI discounts), double-rate rest regen (+10 observed),
village idling (full stamina, +10% hp), poison DOT past depth 12, band refreshes
spawning shallow loot, the action-error taxonomy (not_in_village, not_enough_stamina,
wrong_slot, stat_requirement, no_such_item, not_enough_gold, party_cap), equip slot
truth (club/dagger/spear->hand with spear's STR gate, shield->offhand, robes->outfit),
buy/sell (sell = 20% of list), embark/return, permadeath with drops, `equip` events.

Stated narrowings (pass 1): NO mobs/combat (movement+economy invariants only — the
combat ladder keeps its unit suites), no crafting timers, no portals, no market, one
band per world. Each is a candidate for pass 2; none silently.

Determinism: seeded RNG, seed printed by the soak and overridable via STEEMER_SIM_SEED.
"""
from __future__ import annotations

import random
from collections import deque
from typing import Any

SLOT_TRUTH = {"club": "hand", "dagger": "hand", "spear": "hand",
              "shield_wood": "offhand", "elder_robes": "outfit"}
STR_GATE = {"spear": 4}
SHOP = [{"kind": "club", "buy_price": 15}, {"kind": "spear", "buy_price": 45},
        {"kind": "potion_red", "buy_price": 20}, {"kind": "bottle_empty", "buy_price": 2}]
LIST_PRICE = {s["kind"]: s["buy_price"] for s in SHOP}
POISON_DEPTH = 12
REFRESH_PERIOD = 300
VILLAGE_ONLY = {"buy", "sell", "recruit", "embark", "brew", "smelt", "spend_xp", "list",
                "unlist"}


class SimServer:
    def __init__(self, seed: int = 0, worlds=("vale", "mines", "spire"),
                 width: int = 12, height: int = 20, lag: int = 3,
                 phantom_share: float = 0.5, mirage_dist: int | None = None):
        self.rng = random.Random(seed)
        self.tick = 1000
        self.lag = lag
        self.mirage_dist = mirage_dist
        self.width, self.height = width, height
        self.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 30,
                       "maps": [{"id": w} for w in worlds],
                       "move_stamina": 14, "item_stamina": 10, "punch_stamina": 20}
        self.worlds: dict[str, dict] = {
            w: {"items": {}, "gold": set(), "next_refresh": REFRESH_PERIOD - (i * 37)}
            for i, w in enumerate(worlds)}
        self.chars: dict[str, dict] = {}
        self.guild_gold = 0
        self._item_seq = 90000
        self.vault: list[dict] = []
        self._phantoms: set[int] = set()
        self.phantom_share = phantom_share
        # the lagged view: a queue of (apply_at_tick, uid, world) transitions plus the
        # view state they eventually update; village-frame chars render from a SNAPSHOT
        # taken when the char was last truly in the village.
        self._view_world: dict[str, str] = {}
        self._view_queue: deque = deque()
        self._village_snapshot: dict[str, dict] = {}
        self.errors: list[dict] = []          # everything ever rejected (for asserts)
        self.events_out: list[dict] = []      # per-tick event feed (equip, death, ...)
        self.deaths: list[str] = []
        self._stalled = 0
        self.mobs: dict[int, dict] = {}                # eid -> mob (pass 2)
        self._frozen_renders: dict[tuple, dict] = {}   # (world, uid) -> frozen char
                                                       # snapshot (the live server's
                                                       # frame-ghost bug, 2026-08-25:
                                                       # a returned char kept rendering
                                                       # in its old world at frozen
                                                       # pos/stamina for ~2000 ticks)

    # -- setup helpers ---------------------------------------------------------

    def add_char(self, uid: str, level=3, stats=None, hand=None, gifts=(),
                 inventory=None):
        self.chars[uid] = {
            "char_uid": uid, "eid": len(self.chars) + 1, "world": "village",
            "pos": [self.rng.randrange(self.width), 0],
            "hp": 30, "max_hp": 30, "stamina": 56, "max_stamina": 56,
            "level": level, "xp": 0, "stats": dict(stats or {}),
            "gifts": list(gifts), "statuses": [], "spells": [], "spell_cap": 1,
            "carry": {"used": 0, "cap": 20}, "inventory": list(inventory or []),
            "equipment": {"hand": ({"kind": hand, "item_id": self._nid()} if hand
                                   else None), "offhand": None, "outfit": None,
                          "trinket": None, "boots": None},
            "acted": False, "rested_village": False,
        }
        self._view_world[uid] = "village"
        self._village_snapshot[uid] = self._char_public(self.chars[uid])

    def add_vault(self, kind: str, phantom: bool) -> int:
        iid = self._nid()
        self.vault.append({"kind": kind, "item_id": iid})
        if phantom:
            self._phantoms.add(iid)
        return iid

    def add_mob(self, world: str, kind: str, pos, behavior: str = "wanderer",
                dmg: int = 0, hp: int = 6, xp: int = 3, drop: str | None = None) -> int:
        """Pass 2 (2026-08-25): wildlife and chasers. `wanderer` steps randomly and
        never attacks (the bestiary's chicken/rat shape); `chaser` steps toward the
        nearest char each tick and attacks when adjacent (the wolf/lava_ant shape,
        ~one step/tick, contact damage). Kills yield an xp event and an optional
        drop (bone = the vigor brew input)."""
        eid = self._nid()
        self.mobs[eid] = {"eid": eid, "kind": kind, "world": world,
                          "pos": list(pos), "behavior": behavior, "dmg": dmg,
                          "hp": hp, "max_hp": hp, "xp": xp, "drop": drop}
        return eid

    def seed_loot(self, world: str, pos, kind="egg", mirage=False):
        """mirage=True marks THIS item as a vision-edge flicker (visible only from
        >= mirage_dist). Refresh-spawned loot is always real — a world where ALL
        loot is illusion is beyond the real server (stated narrowing: the
        multi-mirage ping-pong is not asserted against)."""
        self.worlds[world]["items"][tuple(pos)] = {"kind": kind,
                                                   "item_id": self._nid(),
                                                   "mirage": mirage}

    def _nid(self) -> int:
        self._item_seq += 1
        return self._item_seq

    # -- chaos knobs -----------------------------------------------------------

    def stall(self, n: int) -> None:
        self._stalled = n

    def burst(self, n: int) -> None:
        self.tick += n

    def freeze_render(self, uid: str, world: str) -> None:
        """Model the live frame-ghost bug: keep emitting this char in ``world``'s
        frames at its current (frozen) state even after it leaves — with the same
        corrupt signature observed live (stamina pinned above max)."""
        c = self.chars[uid]
        snap = self._char_public(c)
        snap["pos"] = list(c["pos"])
        snap["stamina"] = c["max_stamina"] + 8          # the impossible 64/56
        self._frozen_renders[(world, uid)] = snap

    # -- the tick --------------------------------------------------------------

    def step(self) -> None:
        if self._stalled > 0:
            self._stalled -= 1              # frames flow, the clock does not
        else:
            self.tick += 1
        self.events_out = []
        # apply matured view transitions
        while self._view_queue and self._view_queue[0][0] <= self.tick:
            _, uid, world = self._view_queue.popleft()
            self._view_world[uid] = world
        for uid, c in list(self.chars.items()):
            if c["world"] == "village":
                c["stamina"] = c["max_stamina"]
                c["hp"] = min(c["max_hp"], c["hp"] + max(1, c["max_hp"] // 10))
                self._village_snapshot[uid] = self._char_public(c)
            else:
                if not c["acted"]:
                    c["stamina"] = min(c["max_stamina"], c["stamina"] + 10)
                if c["pos"][1] >= POISON_DEPTH:
                    c["hp"] -= 1
                    if "poison" not in c["statuses"]:
                        c["statuses"].append("poison")
                elif "poison" in c["statuses"]:
                    c["statuses"].remove("poison")
                if c["hp"] <= 0:
                    self._die(uid)
            c["acted"] = False
        # -- mob turn (pass 2): chasers pursue and bite; wanderers drift --------
        for m in list(self.mobs.values()):
            live = [c for c in self.chars.values() if c["world"] == m["world"]]
            if m["behavior"] == "chaser" and live:
                tgt = min(live, key=lambda c: abs(c["pos"][0] - m["pos"][0])
                          + abs(c["pos"][1] - m["pos"][1]))
                d = abs(tgt["pos"][0] - m["pos"][0]) + abs(tgt["pos"][1] - m["pos"][1])
                if d <= 1:
                    tgt["hp"] -= m["dmg"]
                    self.events_out.append({"kind": "attack", "attacker": m["eid"],
                                            "attacker_name": m["kind"],
                                            "target_name": tgt["char_uid"],
                                            "damage": m["dmg"]})
                    if tgt["hp"] <= 0:
                        self._die(tgt["char_uid"])
                else:
                    dx = (1 if tgt["pos"][0] > m["pos"][0] else
                          -1 if tgt["pos"][0] < m["pos"][0] else 0)
                    dy = 0 if dx else (1 if tgt["pos"][1] > m["pos"][1] else -1)
                    m["pos"][0] += dx
                    m["pos"][1] += dy
            elif m["behavior"] == "wanderer" and self.rng.random() < 0.2:
                dx, dy = self.rng.choice([(0, 1), (0, -1), (1, 0), (-1, 0)])
                nx, ny = m["pos"][0] + dx, m["pos"][1] + dy
                if 0 <= nx < self.width and 0 <= ny < self.height:
                    m["pos"] = [nx, ny]
        for w, st in self.worlds.items():
            st["next_refresh"] -= 1
            if st["next_refresh"] <= 0:
                st["next_refresh"] = REFRESH_PERIOD
                for _ in range(6):
                    p = (self.rng.randrange(self.width),
                         self.rng.randrange(0, min(10, self.height)))
                    if self.rng.random() < 0.5:
                        st["gold"].add(p)
                    else:
                        st["items"][p] = {"kind": self.rng.choice(
                            ["egg", "embercap", "bone"]), "item_id": self._nid()}

    def _die(self, uid: str) -> None:
        c = self.chars.pop(uid)
        self.deaths.append(uid)
        self.events_out.append({"kind": "death", "char_uid": uid,
                                "name": uid, "pos": list(c["pos"]),
                                "guild_id": "g_sim"})
        self._view_queue.append((self.tick + self.lag, uid, None))

    # -- frames ----------------------------------------------------------------

    def _char_public(self, c: dict) -> dict:
        pub = {k: (list(v) if isinstance(v, list) else
                   dict(v) if isinstance(v, dict) else v)
               for k, v in c.items() if k not in ("acted", "rested_village", "world")}
        pub["inventory"] = [dict(i) for i in c["inventory"]]
        pub["equipment"] = {s: (dict(v) if isinstance(v, dict) else v)
                            for s, v in c["equipment"].items()}
        pub["statuses"] = [{"kind": k} for k in c["statuses"]]   # protocol shape:
                                                                 # status OBJECTS
        return pub

    def frames(self) -> list[dict]:
        out = []
        # village frame renders from the LAGGED view + stale snapshots
        here = [u for u, w in self._view_world.items() if w == "village"]
        by_world: dict[str, list] = {}
        for u, w in self._view_world.items():
            if w not in (None, "village"):
                by_world.setdefault(w, []).append(u)
        out.append({"type": "frame", "world": "village", "tick": self.tick,
                    "events": list(self.events_out),
                    "guild": {"guild_id": "g_sim", "gold": self.guild_gold,
                              "chars_here": list(here),
                              "chars_by_world": by_world,
                              # wire v3 (2026-08-25): grouped inventory — one
                              # descriptor per kind with count + item_ids; phantom
                              # ids stay IN the listing (observed: the live head ids
                              # are exactly the probed-dead set)
                              "inventory": self._grouped_vault(),
                              "market_listings": []},
                    "shop": {"stock": [dict(s) for s in SHOP]},
                    "chars": [self._village_snapshot[u] for u in here
                              if u in self._village_snapshot]})
        for w, st in self.worlds.items():
            live = [c for c in self.chars.values() if c["world"] == w]
            ghosts = [snap for (gw, gu), snap in self._frozen_renders.items()
                      if gw == w and (gu not in self.chars
                                      or self.chars[gu]["world"] != w)]
            if not live and not ghosts:
                continue
            items = []
            for p, it in st["items"].items():
                if it.get("mirage") and self.mirage_dist is not None:
                    near = min(abs(p[0] - c["pos"][0]) + abs(p[1] - c["pos"][1])
                               for c in live)
                    if near < self.mirage_dist:
                        continue
                items.append({"pos": list(p), "kind": it["kind"],
                              "item_id": it["item_id"]})
            tiles = [[x, y, "floor", 0, 0] for x in range(self.width)
                     for y in range(self.height)]
            ents = [{"eid": m["eid"], "kind": m["kind"], "faction": "monster",
                     "pos": list(m["pos"]),
                     "hp_frac": m["hp"] / max(1, m["max_hp"])}
                    for m in self.mobs.values() if m["world"] == w]
            out.append({"type": "frame", "world": w, "tick": self.tick,
                        "events": list(self.events_out),
                        "bounds": [self.width, self.height],
                        "next_refresh": {"band": 0, "in_ticks": st["next_refresh"]},
                        "chars": [dict(self._char_public(c), pos=list(c["pos"]))
                                  for c in live] + [dict(g) for g in ghosts],
                        "visible": {"tiles": tiles, "entities": ents, "items": items,
                                    "gold": [{"pos": list(p), "amount": 2}
                                             for p in st["gold"]]}})
        return out

    def _grouped_vault(self) -> list[dict]:
        groups: dict[str, list[int]] = {}
        for v in self.vault:
            groups.setdefault(v["kind"], []).append(v["item_id"])
        return [{"kind": k, "tier": 1, "count": len(ids),
                 "item_ids": sorted(ids)} for k, ids in sorted(groups.items())]

    # -- action application ----------------------------------------------------

    def _reject(self, uid, action, reason) -> dict:
        msg = {"char_uid": uid, "action": action, "reason": reason, "tick": self.tick}
        self.errors.append(msg)
        return msg

    def apply(self, actions: list[dict]) -> list[dict]:
        rejected = []
        for a in actions or []:
            r = self._apply_one(a)
            if r is not None:
                rejected.append(r)
        return rejected

    def _apply_one(self, a: dict):        # noqa: C901 — the rule table is the point
        act = a.get("action")
        uid = a.get("char_uid")
        if act == "embark":
            uids = a.get("char_uids") or []
            world = a.get("map")
            for u in uids:
                c = self.chars.get(u)
                if c is None or c["world"] != "village":
                    return self._reject(u, act, "not_in_village")
                if sum(1 for x in self.chars.values()
                       if x["world"] == world) >= self.config["party_cap"]:
                    return self._reject(u, act, "party_cap")
                c["world"] = world
                c["pos"] = [self.rng.randrange(self.width), 0]
                self._view_queue.append((self.tick + self.lag, u, world))
            return None
        if act == "recruit":
            # guild-level: creates a fresh level-0 char in the village, capped at
            # roster_cap counted over VILLAGE-PRESENT chars (the server's own quirk,
            # documented in server_bugs.md 2026-08-23).
            here_n = sum(1 for x in self.chars.values() if x["world"] == "village")
            if here_n >= self.config["roster_cap"]:
                return self._reject(None, act, "roster_cap")
            nid = f"r{self._nid()}"
            self.add_char(nid)
            self.events_out.append({"kind": "recruit", "char_uid": nid})
            return None
        c = self.chars.get(uid)
        if c is None:
            return self._reject(uid, act, "unknown_character")
        in_village = c["world"] == "village"
        if act in VILLAGE_ONLY and not in_village:
            return self._reject(uid, act, "not_in_village")
        cost = {"move": self.config["move_stamina"],
                "attack": self.config["punch_stamina"]}.get(
                    act, self.config["item_stamina"])
        if not in_village and act in ("move", "attack", "pickup", "use", "drop",
                                      "open") and c["stamina"] < cost:
            return self._reject(uid, act, "not_enough_stamina")
        if act == "move":
            if in_village:
                # THE FLAP, reproduced: a move commanded off a stale FIELD frame for
                # a char that has truly returned home is what the live server rejects
                # `not_in_village` (51x on run #208, 2-6 per departing char).
                return self._reject(uid, act, "not_in_village")
            dx, dy = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}.get(
                a.get("dir"), (0, 0))
            nx, ny = c["pos"][0] + dx, c["pos"][1] + dy
            c["acted"] = True
            c["stamina"] -= cost
            if ny < 0:                     # stepping off row 0 exits to the village
                c["world"] = "village"
                self._view_queue.append((self.tick + self.lag, uid, "village"))
                return None
            if 0 <= nx < self.width and 0 <= ny < self.height:
                c["pos"] = [nx, ny]
            else:
                self.events_out.append({"kind": "move_failed", "char_uid": uid})
            return None
        if act == "pickup":
            if in_village:
                return self._reject(uid, act, "not_in_village")
            c["acted"] = True
            c["stamina"] -= cost
            st = self.worlds[c["world"]]
            p = tuple(c["pos"])
            if p in st["items"]:
                it = st["items"].pop(p)
                c["inventory"].append({"kind": it["kind"], "item_id": it["item_id"],
                                       "uses": ["equip", "attack"]
                                       if it["kind"] in SLOT_TRUTH else ["brew"]
                                       if it["kind"] in ("embercap", "bone") else []})
                c["carry"]["used"] += 1
                self.events_out.append({"kind": "pickup", "char_uid": uid,
                                        "item": it["kind"]})
            elif p in st["gold"]:
                st["gold"].discard(p)
                self.guild_gold += self.rng.randrange(1, 4)
            return None
        if act == "use":
            item = next((i for i in c["inventory"]
                         if i.get("item_id") == a.get("item_id")), None)
            if item is None:
                return self._reject(uid, act, "no_such_item")
            if item["kind"] == "potion_red":
                c["hp"] = min(c["max_hp"], c["hp"] + 15)
                c["inventory"].remove(item)
            return None
        if act == "buy":
            kind = a.get("kind")
            price = LIST_PRICE.get(kind)
            if price is None:
                return self._reject(uid, act, "no_such_item")
            if self.guild_gold < price:
                return self._reject(uid, act, "not_enough_gold")
            self.guild_gold -= price
            c["inventory"].append({"kind": kind, "item_id": self._nid(),
                                   "uses": ["equip", "attack"] if kind in SLOT_TRUTH
                                   else ["use"] if kind == "potion_red" else ["brew"]})
            self.events_out.append({"kind": "buy", "char_uid": uid, "item": kind})
            return None
        if act == "sell":
            item = next((i for i in c["inventory"]
                         if i.get("item_id") == a.get("item_id")), None)
            if item is None:
                return self._reject(uid, act, "no_such_item")
            c["inventory"].remove(item)
            self.guild_gold += max(1, LIST_PRICE.get(item["kind"], 5) // 5)
            self.events_out.append({"kind": "sale", "char_uid": uid,
                                    "item": item["kind"]})
            return None
        if act == "drop":
            iid = a.get("item_id")
            if in_village:
                if iid in self._phantoms:
                    return self._reject(uid, act, "no_such_item")
                ventry = next((v for v in self.vault if v["item_id"] == iid), None)
                if ventry is None:
                    return self._reject(uid, act, "no_such_item")
                self.vault.remove(ventry)
                c["inventory"].append({"kind": ventry["kind"], "item_id": iid,
                                       "uses": ["equip", "attack"]
                                       if ventry["kind"] in SLOT_TRUTH else ["use"]})
                return None
            item = next((i for i in c["inventory"]
                         if i.get("item_id") == iid), None)
            if item is None:
                return self._reject(uid, act, "no_such_item")
            c["inventory"].remove(item)
            self.worlds[c["world"]]["items"][tuple(c["pos"])] = item
            return None
        if act == "equip":
            item = next((i for i in c["inventory"]
                         if i.get("item_id") == a.get("item_id")), None)
            if item is None:
                return self._reject(uid, act, "no_such_item")
            kind, slot = item["kind"], a.get("slot")
            truth = SLOT_TRUTH.get(kind)
            if truth is not None and slot != truth:
                return self._reject(uid, act, "wrong_slot")
            if kind in STR_GATE and c["stats"].get("str", 1) < STR_GATE[kind]:
                return self._reject(uid, act, "stat_requirement")
            if c["equipment"].get(slot) is not None:
                return self._reject(uid, act, "wrong_slot")
            c["equipment"][slot] = {"kind": kind, "item_id": item["item_id"]}
            c["inventory"].remove(item)
            self.events_out.append({"kind": "equip", "eid": c["eid"], "item": kind,
                                    "slot": slot, "pos": list(c["pos"])})
            return None
        if act == "attack":
            c["acted"] = True
            c["stamina"] -= cost
            tp = a.get("target")
            if isinstance(tp, list) and not in_village:
                m = next((m for m in self.mobs.values()
                          if m["world"] == c["world"] and m["pos"] == list(tp)
                          and abs(tp[0] - c["pos"][0]) + abs(tp[1] - c["pos"][1]) <= 1),
                         None)
                if m is not None:
                    m["hp"] -= 8                       # a club swing
                    if m["hp"] <= 0:
                        self.mobs.pop(m["eid"])
                        self.events_out.append({"kind": "death", "eid": m["eid"],
                                                "kind_name": m["kind"],
                                                "name": m["kind"],
                                                "pos": list(m["pos"])})
                        self.events_out.append({"kind": "xp", "char_uid": uid,
                                                "amount": m["xp"]})
                        c["xp"] = c.get("xp", 0) + m["xp"]
                        if m["drop"]:
                            self.worlds[c["world"]]["items"][tuple(m["pos"])] = {
                                "kind": m["drop"], "item_id": self._nid()}
            return None
        if act in ("open", "say", "taste", "recruit", "brew", "smelt",
                   "spend_xp", "ride", "return"):
            c["acted"] = act in ("open", "ride")
            return None
        return None
