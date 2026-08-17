# Example bots, annotated

Three bots ship in the starter kit, each demonstrating progressively more of
the patterns you'll want in your own bot. Source:
`reference_starter_kit/{starter_bot,farmer_bot,ranger_bot}.py`.

## `starter_bot.py` — the floor

The simplest thing that plays the game correctly. No memory across frames, no
retreat plan.

```python
class StarterBot(GuildBot):
    def on_frame(self, frame):
        if frame["world"] == "village":
            return self.in_village(frame)
        return self.in_dungeon(frame)
```

**Village logic:** keep the roster at `party_cap` by recruiting until full,
then embark everyone currently in the village:

```python
def in_village(self, frame):
    guild = frame["guild"]
    cap = self.config.get("party_cap", 5)
    away = sum(len(uids) for uids in guild["chars_by_world"].values())
    here = guild["chars_here"]
    if len(here) + away < cap:
        return [{"action": "recruit"}]
    if here and away < cap:
        return [{"action": "embark", "map": "vale", "char_uids": here[:cap - away]}]
    return []
```

Note the pattern for computing occupancy from a village frame:
`guild["chars_by_world"]` maps map-id → list of `char_uid`s already fielded
there; summing its values plus `len(here)` gives total roster size against
`party_cap`/`roster_cap`.

**Dungeon logic:** attack adjacent enemies, pick up loot underfoot, otherwise
wander into any open, unblocked direction:

```python
def in_dungeon(self, frame):
    enemies = {tuple(e["pos"]) for e in frame["visible"]["entities"]
               if e["faction"] == "monster"}
    loot = {tuple(i["pos"]) for i in frame["visible"]["items"]}
    gold = {tuple(g["pos"]) for g in frame["visible"]["gold"]}
    walls = {(t[0], t[1]) for t in frame["visible"]["tiles"] if t[2] in SOLID}
    blocked = walls | {tuple(e["pos"]) for e in frame["visible"]["entities"]
                       if e["faction"] == "guild"}
    for char in frame["chars"]:
        if char["stamina"] < 25:
            continue   # idle to rest rather than send a doomed action
        ...
```

Worth internalizing: **character tiles (yours and rivals') block movement as
hard as walls**, and a bounced move still costs stamina — so `blocked`
includes `faction == "guild"` entities, not just `SOLID` terrain kinds.
Monster tiles stay walkable in this set because the bot's *intent* is to
walk adjacent and attack, not path through them.

This bot has **no exit plan**: characters fight until they die, and the
guild just recruits a free replacement. Fine for exploring the game's
surface; not a real strategy.

## `farmer_bot.py` — memory, a plan, and a retreat

Adds two ideas worth stealing directly:

1. **Remember the map.** Frames only carry the current vision union, but
   tiles you've seen are yours to keep across frames:

   ```python
   def __init__(self):
       super().__init__()
       self.known = {}   # (x, y) -> tile kind, remembered across frames

   def in_dungeon(self, frame):
       for x, y, kind, *_rest in frame["visible"]["tiles"]:
           self.known[(x, y)] = kind
   ```

   This accumulated memory is what lets the bot path through gates between
   bands at all — a frame alone never shows enough of the map.

2. **A plan per character**, driven by a simple state machine encoded as
   `if`/`elif` priority: heal if hurt, fight what's adjacent, retreat if hurt
   or full, grab loot underfoot, chase visible loot/enemies, push toward a
   target row (`HUNT_Y = 42`) while healthy, otherwise explore frontier
   tiles.

   ```python
   def act(self, char, enemies, loot):
       uid, pos = char["char_uid"], tuple(char["pos"])
       if char["stamina"] < 30:
           return None
       hurt = char["hp"] < char["max_hp"] * RETREAT_HP    # RETREAT_HP = 0.4
       if hurt or char["carry"]["used"] >= char["carry"]["cap"] - 1:
           self.retreating.add(uid)
       if hurt:
           for item in char["inventory"]:
               if item["kind"] == "potion_red":
                   return {"char_uid": uid, "action": "use", "item_id": item["item_id"]}
       adjacent = [p for p in neighbors(pos) if p in enemies]
       if adjacent and uid not in self.retreating:
           weakest = min(adjacent, key=lambda p: enemies[p]["hp_frac"])
           return {"char_uid": uid, "action": "attack", "target": list(weakest)}
       if uid in self.retreating:
           return self.travel(uid, pos, lambda p: p[1] == 0)   # walk off the bottom edge
       if pos in loot:
           return {"char_uid": uid, "action": "pickup"}
       if loot:
           return self.travel(uid, pos, lambda p: p in loot)
       if enemies:
           return self.travel(uid, pos, lambda p: p in enemies)
       if pos[1] < HUNT_Y:
           return self.travel(uid, pos, lambda p: p[1] >= HUNT_Y)
       return self.travel(uid, pos, self.unexplored)
   ```

   `self.retreating` is a set of `char_uid`s currently walking home — once
   added, a character stays in retreat mode (fighting is skipped) until it
   reaches the village and the village logic clears the flag. This avoids a
   hurt character "flip-flopping" between fighting and fleeing tick to tick.

**Path-finding (`travel`)** is a plain BFS over `self.known`, treating
unknown tiles as walls (`self.known.get(step, "wall") in SOLID`) and current
character positions (`self.bodies`) as blocked:

```python
def travel(self, uid, start, is_goal):
    came_from = {start: None}
    queue = deque([start])
    goal = None
    while queue:
        current = queue.popleft()
        if current != start and is_goal(current):
            goal = current
            break
        for step in neighbors(current):
            if step in came_from or step in self.bodies \
                    or self.known.get(step, "wall") in SOLID:
                continue
            came_from[step] = current
            queue.append(step)
    if goal is None:
        # fall back to a random legal step — keeps exploring instead of pacing
        ...
    # walk back from goal to find the single next step from `start`
```

If no path to a goal exists in what's been explored yet, it falls back to a
random open step — this is what keeps an unlucky bot *exploring* (eventually
discovering a path) instead of standing still forever.

**Village logic** adds selling and re-equipping: sell everything except
`potion_red`, buy a `shortsword` (or `club` if the character's STR is too
low) once affordable, equip it, and wait for full HP before re-embarking
(idling in the village heals).

## `ranger_bot.py` — spreading a party across every map

Builds on `farmer_bot.py` with three additional ideas:

1. **Even deployment across maps.** Instead of always embarking to `vale`,
   send each newly-available character to whichever map currently holds the
   *fewest* of your characters:

   ```python
   maps = [m["id"] for m in self.config.get("maps", [])]
   target = min(maps, key=lambda m: len(by_world.get(m, [])))
   if len(by_world.get(target, [])) < self.config.get("party_cap", 5):
       return [{"action": "embark", "map": target, "char_uids": [here[0]]}]
   ```

   An even spread falls out of this `min`-by-count rule without any quota
   bookkeeping — one character embarks per tick, always to the
   currently-thinnest map.

2. **Per-map memory**, since frames arrive one-per-world-per-tick and a
   naive single `self.known` dict would conflate the Vale's layout with the
   Embermines':

   ```python
   self.known = {}   # world id -> {(x, y): tile kind}
   known = self.known.setdefault(frame["world"], {})
   ```

3. **Learning equip slots from errors**, since a frame never tells you which
   slot an item wants — the bot tries a slot and listens on the error
   channel:

   ```python
   EQUIP_SLOTS = ("hand", "offhand", "outfit", "trinket")

   def on_action_error(self, message):
       kind = self.equipping.get(message.get("char_uid"))
       if message.get("action") != "equip" or kind is None:
           return
       if message.get("reason") == "wrong_slot":
           self.slot_try[kind] += 1        # try the next slot next time
       elif message.get("reason") == "stat_requirement":
           self.wont_fit.add((message.get("char_uid"), kind))   # stop trying entirely

   def equip_step(self, char):
       for item in char["inventory"]:
           kind = item["kind"]
           if "equip" not in item["uses"] or (char["char_uid"], kind) in self.wont_fit:
               continue
           guess = self.slot_try.setdefault(kind, 0)
           if guess >= len(EQUIP_SLOTS):
               continue
           slot = EQUIP_SLOTS[guess]
           ...
   ```

   `self.equipping` tracks which item kind is currently "in flight" for each
   character (at most one `equip` sent per character per tick), so the next
   `on_action_error` call can attribute a rejection to the right item. This
   is the general pattern for **any** capability you can't read directly off
   a frame: try, listen to `action_err`, adjust, and cache what you learned
   per item kind so you don't relearn it every time.

It also adds container handling — a chest/safe needs several *consecutive*
`open` actions on the same tile (moving away resets progress), so the bot
keeps re-issuing `open` on a known box until it pops, ahead of chasing loot
or exploring.

## Picking a starting point

- Want the absolute minimum to see the game move? Run `starter_bot.py`
  unmodified.
- Want a single competent party that farms one map sustainably? Fork
  `farmer_bot.py` — it's the shortest bot that has a real retreat/sell loop.
- Want to work all three maps (and all three crafting pillars) from one
  guild? Fork `ranger_bot.py`.
- Whatever you fork, keep the shared skeleton: `if frame["world"] ==
  "village"` branch vs. field branch, remembered tiles keyed appropriately,
  a `retreating` set, and BFS-over-known-tiles for movement. None of that is
  specific to any one strategy — see [09-client-library.md](09-client-library.md)
  for what the library already gives you underneath all three.
