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

v0.5.0 — the operator noticed characters carrying weapons/armor but wearing
none. Cause: `equip` had fired 0 times ever — the village SOLD gear (everything
outside KEEP) before the equip step could reach it, and there was no path to
equip looted armor/shields/trinkets at all. Fix:
  * **Equip carried gear into empty slots, BEFORE selling.** Slots are learned
    by trial (wrong_slot advances to another slot; stat_requirement marks the
    kind unusable) so it needs no content knowledge of which item goes where.
  * **Never sell gear we can still use** — only loot and gear that won't fit.
    Unarmored characters were almost certainly compounding the death problem.

v0.6.0 — start of the crafting arc (gameplan M3b, brewing): the guild constantly
loots brewable herbs/parts (bitterroot, frostmoss, bone, ectoplasm) and was
*selling them for pennies*. Now, in the village, it keeps them, buys a cheap
`bottle_empty`, and `brew`s 2-4 together — the pot decides the product from the
majority essence, and the result + `tells` teach this world's herb->essence map
(analysis loop infers it from logged events). Crafting occupies the character, so
a `craft`-busy character is left alone (never actioned, moved, or embarked — that
would abandon the work). Consumables/food (`drink`) are now kept too (M3c sustain).
Brewing was chosen before forging (M3a) because `forge` needs an unpublished
`product` name; brewing needs no such vocabulary and proves the craft machinery.

v0.7.0 — the 34 blind brews of 0.6.0 curdled ~50% of the time. Analysis of the
logged products + tells decoded this world's essence map (``knowledge.py``):
``vigor`` and ``venom`` are opposite poles, and every curdle was a brew that
mixed them. So brewing is now **essence-aware**: group brewables by their known
essence and brew a *single-essence* batch — never a mix — preferring ``vigor``
(which brews ``potion_red``, the field heal). Ingredients we haven't decoded are
brewed only among themselves, as a learning batch, so discovery continues
without poisoning the healing supply.

v0.8.0 — 0.7.0 lifted brew success 49%->87% but regressed carry: declining to
brew minority/singleton herbs left them hoarded (never sold), so avg brewables
held rose 0.49->1.83, carry filled (0%->14.5% of field chars full), and full
chars spammed failed move-home steps (move/not_enough_stamina 7%->17%). Two
fixes: (1) SELL stranded brewables — a herb that can't form a no-curdle batch is
banked for gold, not hoarded; (2) learn undecoded herbs with same-KIND batches
(can't curdle) instead of mixing different unknowns (which caused 0.7.0's only
curdles). Keeps the brew win, unclogs carry, and cleans up the learning path.

v0.9.0 — the 0.8.0 window's action-error rate held at ~0.5, of which
not_enough_stamina is 45%. A DB drill-down killed the standing theory that the
village loop was the culprit: village economy actions (sell/buy/brew/equip/
spend_xp) produce ZERO not_enough_stamina across all history — they cost no
stamina — so gating them would be a no-op. The real leak is the FIELD: 98% of
not_enough_stamina is `move`, and it fails at a *shown* stamina of 13-29 (median
23) on 94% plain floor (web/rime = 0%), even though the measured floor move cost
is 20 and the gate already checks `stamina >= 20`. The bot only issues a move it
believes it can afford, yet the server rejects it — the tell of a ~1-tick STALE
frame: the acted-on stamina reading is higher than the server's live value (a
prior move's cost not yet reflected). Fix: give the field move gate HEADROOM
(``MOVE_STAMINA_SAFETY``) above the raw cost, so a stale-high reading still
affords the move on the server; otherwise the char rests and regens (double
rate) rather than spamming a doomed step. Applied to `move`/`ride` only —
attack/use/etc. barely ever error on stamina, and margining them would needlessly
throttle combat and healing.

v0.10.0 — the 0.9.0 window's residual error rate is dominated by the
*phantom-character* family (no_such_character / unknown_character /
not_in_village ≈ 60% of the live-backend errors). A DB drill-down pinned the
cause: NOT rival players (the failing uids are all our own guild) but a
DUPLICATE-SEND STORM. `village()` re-issues the *same* `embark`/`recruit` every
tick because it decides on a ~few-tick-stale village frame — the just-commanded
char still shows in `chars_here` before the command lands — so the bot fires
1408 embarks for ~28 chars in one run, and the tail bounces `no_such_character`
(294) / `roster_cap` (48) once the char finally leaves the village. Fix: an
in-flight guard — track the tick each char was embarked and each recruit, and
don't re-send while one is pending (EMBARK/RECRUIT_COOLDOWN), counting in-flight
embarks toward the world cap so we don't over-deploy either. (The field-move
`unknown_character` remainder is a *different* mechanism — the server's lagging
echo of moves already queued for a char that then died mid-field; those actions
were legitimate when sent and are not bot-fixable from the frame.)

Also v0.10.0 — start of M3a (forging supply, the top durability lever): the
guild loots `ore_copper`/`ore_iron` and was *selling* it. Now, in the village, a
character that holds two matching ore `smelt`s them into an ingot (metal
feedstock), reusing the craft-busy handling brewing already proved and needing
no per-world vocabulary (`smelt` takes only item_ids). `forge` itself is
deliberately NOT wired yet: it requires a per-world `product` NAME that no
`forged` event in all recorded history reveals, and — unlike brewing, where the
pot infers the product so a blind brew never errors — a guessed forge product is
an `unknown_product` action error, the exact class this version is reducing. So
smelting banks the ingots and logs the metal `tells`; forging lands once a
product name is learned (see decisions.log / findings.jsonl).

v0.11.0 — the recruit/embark gates were built on the village frame's `guild`
snapshot (`chars_here` + `chars_by_world`), which the operator caught disagreeing
with the server's map (our UI read 7 while the true roster was 28). The snapshot
is a lagged, PARTIAL view of a large persistent roster — the server shows
characters intermittently (a live char is absent from every frame for up to ~350
ticks), so the count swings 30->6->30 with almost no real deaths, and gating on
it over-recruits (`roster_cap`) and over-embarks. The true count is NOT
reconstructable from frames, but the public web endpoint `GET
/api/spectate/guilds` returns it directly: our guild's `characters` total plus
each char's current `world`. The bot now polls it in the background
(`steemer/spectate.py`, attached by the live runner) and the gates use that
authoritative `(roster, fielded, per-world)` when it is fresh, falling back to
the frame snapshot otherwise. `here` (who we can embark *this* frame) still comes
from the frame's `chars_here` — only a char the frame shows in the village can be
embarked. Offline replay and tests have no `bot.spectate`, so they use the
snapshot fallback and never touch the network.

v0.11.1 — measuring 0.11.0 (run #34) showed `roster_cap` was ALREADY ~0 under
0.10.0 (the recruit cooldown had fixed it), so authoritative gating didn't reduce
a live error — and using the ~45 s-stale spectate count for the EMBARK gate added
a small `world_cap`/`party_cap` blip on the restart deploy wave (5 errors in the
first ~46 ticks). Fix: split the two gates — RECRUIT keeps the authoritative
spectate TOTAL (the frame total swings, so this is the right source and it keeps
the dashboard/roster count honest), but EMBARK reverts to the frame's fresh,
per-tick `chars_by_world` (accurate for the current per-map field, no staleness).

v0.12.0 — the master lever, found once the loop finally *saw* field productivity:
the guild had collapsed into a poverty trap (0 loot/xp for 8 runs, chars bare-
handed, gold 13; move_failed ~1%→~30% since the MariaDB cutover). Root cause was
NOT the DB (record_frame is ~11 ms) — it was a NAV FREEZE: a char that issues a
move into a blocked tile bounces (`move_failed`) but never learns, so it
re-issues the identical doomed move *every tick, forever* (observed: one char
frozen at (43,3) for 40+ ticks "pushing north" without moving). Fix lives in
`GuildBot._field` (not the strategy proper — the version bump marks the deployed
behavior): detect "issued a move but didn't move" and add that tile to a
per-world learned-blocked set (TTL `STUCK_BLOCK_TTL`) that nav routes around, so
a stuck char frees itself next tick. Expected: move_failed collapses, chars
explore/loot/earn again, and the village economy (equip/sell/brew/smelt/spend_xp,
all at 0 for 8 runs) restarts.

v0.13.0 — 0.12.0 fixed the freeze (move_failed 30%->7.5%, economy 0->128
actions/run) but the guild stayed hard-broke: gold flat at ~14 for a whole
30k-tick run, home chars empty and bare-handed, pickup/xp ~0, 11 chars died. The
economic diagnosis found a SELF-INFLICTED deadlock: the buy-weapon gate was a
hardcoded `gold >= 45` (the shortsword's price) while a **club costs 15**, so a
broke guild never armed a char — and in the 25-44 gold band it bought 20-gold
POTIONS instead (that is where the guild's 10-potion stockpile came from), draining
the treasury while chars fought bare-handed and lost. Fix: buy the CHEAPEST
affordable weapon from the live shop stock (`_afford_weapon`, prices/reqs read
from the frame, never hardcoded), which lowers the bootstrap escape from 45 gold
to 15; and never buy a potion for a still-bare-handed char, so scarce gold arms
a weapon first. One armed char can then survive → loot → sell → fund the next.
Expected: the moment the guild scrapes ~15 gold it arms a char (not at 45, never
reached), gold starts rising, kills/xp/pickups climb. Falsified if gold stays
pinned at ~14 (then the binding constraint is field income — chars not reaching
loot — not spending, and that is the next target).

v0.14.0 — 0.13.0 measured as PARTIALLY working: gold rose 14->34 (income
appeared), chars armed (buy actions 0->250), pickups 1->8, xp 1->12 — the
deadlock is cracking. But run #38 exposed a duplicate-send storm on the per-char
VILLAGE economy (250 buy + 148 sell actions for ~1 sale / a few real buys),
exactly like the old embark storm: a char decides on a ~few-tick-stale frame and
re-issues the same buy/sell/equip every tick until the change is reflected,
spamming no_such_item and over-buying. Fix: a per-char village-action re-send
guard — after a char issues a village action, skip it for `VILLAGE_ACTION_COOLDOWN`
ticks so the frame catches up (recorded in `_village_act`, checked at the top of
the per-char loop). Generalises the embark/recruit guards to the economy loop.
Expected: buy/sell action counts collapse toward the number of real purchases,
no_such_item errors fall, gold isn't wasted on duplicate buys — a cleaner, faster
bootstrap. (The still-low pickup rate — chars reach loot but bare `pickup` often
no-ops — is a separate income bottleneck, under investigation.)

v0.15.0 — the "pickup no-op" premise was FALSE: run #52 (0.14.0) measured 672
pickups (10.8/1k) — looting works and always did; the earlier "~8 pickups"
reading was crash-loop-contaminated (runs #39-#51 were empty). The real income
leak, found by drilling the run-#52 events, is OVERBURDEN → strand → die. `carry`
is *weight* not slots (16 items = 20/21 weight); a near-full char that grabs one
heavy meat/ore crosses `used > cap` and the server's overburden penalty cripples
its movement, so the stamina-gated walk-home step becomes unaffordable — and
nothing sheds the weight, so it sits `overburdened` for hundreds of ticks (one
char logged 939) burning a scarce world slot until poison finishes it. Only 74 of
687 pickups ever returned to be sold; that is why gold stays pinned at 14 despite
healthy looting. Two fixes: (1) gate `pickup` on `not full` — a char at/over
`cap-1` stops grabbing, so it never crosses into overburden from a near-full state
(previously pickup was offered unconditionally, and beat rest whenever the
walk-home move was stamina-suppressed — exactly the danger case). (2) an
overburden escape: when `used >= cap`, offer `drop` of the least-useful carried
item (pure loot/clutter first; gear, KEEP supplies and craft pairs preserved) at a
priority above the full-retreat, so the char sheds weight, regains mobility, and
walks its remaining loot home instead of dying on it. Expected: overburden events
and our char-deaths fall, `returned`/`sale` counts rise toward the pickup count,
gold finally accumulates.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import knowledge, nav
from .base import FieldContext
from ..reasoning import DecisionTrace

RETREAT_HP = 0.6           # flee below 60% HP — early enough to still afford the run
DOT_KINDS = frozenset({"poison", "burn"})   # damage-over-time: flee regardless of HP
KEEP = frozenset({"potion_red", "bottle_empty"})   # field/craft supplies we never sell
CONTAINERS = frozenset({"chest", "safe"})
DEFAULT_MAPS = ("vale", "mines", "spire")
REST_SCORE = 0.5           # the floor: rest wins only when nothing affordable beats it
POTION_KEEP = 1            # potions to carry into the field per character
POTION_MIN_GOLD = 25       # only buy a potion with this much gold to spare
XP_PRIORITY = ("vit", "end", "str")   # survival first: HP, then stamina, then damage
XP_STAT_TARGET = 8         # grow each toward the full-rate effective-bonus cap
EQUIP_SLOTS = ("hand", "offhand", "outfit", "trinket", "boots")
BREW_MIN = 2               # a brew takes 2-4 ingredients
BREW_MAX = 4
BREW_MIN_GOLD = 10         # keep a little gold buffer before buying bottles
# Hand-weapon kinds the shop sells (observed; the offhand shield, tool pickaxe/
# sickle, and consumables are excluded). Used to buy the cheapest affordable one
# to arm a bare-handed char — v0.13.0's poverty-bootstrap unlock.
WEAPON_KINDS = frozenset({"club", "dagger", "shortsword", "spear", "bow"})


MOVE_STAMINA_SAFETY = 1.5   # v0.9.0: require this ×raw move cost of stamina before
#   stepping — headroom so a ~1-tick-stale frame reading still affords the move on
#   the server (moves failed not_enough_stamina at shown-sta up to ~29 for a cost-20
#   move; the gap is staleness, not terrain). Rest/regen instead of a doomed step.

EMBARK_COOLDOWN = 8   # v0.10.0: after commanding a char to embark, don't re-send
#   that char's embark for this many ticks. The village frame we decide on is a few
#   ticks stale, so a just-embarked char still shows in `chars_here` — without the
#   guard the bot re-embarks it every tick and the tail bounces no_such_character
#   once it finally leaves. Observed embark latency ~3 ticks; 8 is safe headroom and
#   still retries a genuinely-failed embark after ~2 s.
RECRUIT_COOLDOWN = 8  # v0.10.0: same staleness for recruit — a just-recruited char
#   isn't in the roster for a few frames, so re-firing recruit storms roster_cap.
VILLAGE_ACTION_COOLDOWN = 6   # v0.14.0: after a char issues a per-char village
#   action (buy/sell/equip/brew/smelt/spend_xp), don't issue it another for this
#   many ticks — the frame is a few ticks stale, so re-issuing the same buy/sell
#   spams no_such_item / over-buys before the change is reflected.


class Explorer:
    version = "explorer/0.15.0"

    def __init__(self) -> None:
        # Equip-slot learning (persists across frames): slots a kind has been
        # rejected from (wrong_slot), and kinds that fail a stat requirement.
        self.slot_wrong: dict[str, set[str]] = defaultdict(set)
        self.wont_fit: set[str] = set()
        self.equipping: dict[str, tuple[str, str]] = {}   # uid -> (kind, slot) in flight
        # In-flight guild-command tracking (v0.10.0): the tick each char was last
        # embarked, and the tick recruit last fired — so a stale village frame does
        # not make us re-send the same command every tick (the phantom-character
        # duplicate-send storm). Pruned once the char leaves `chars_here`.
        self._embark_at: dict[str, int] = {}
        self._recruit_at: int | None = None
        # In-flight guard for per-char VILLAGE actions (v0.14.0): the tick each
        # char last issued a village action, so a stale frame doesn't make it
        # re-send the same buy/sell/equip every tick (run #38: 250 buy + 148 sell
        # actions for ~1 sale — the same duplicate-send storm as embark).
        self._village_acted: dict[str, int] = {}

    def on_action_error(self, bot: "Any", message: dict[str, Any]) -> None:
        """Learn equip slots from the server's rejections. We send at most one
        equip per character per frame, so the pending (kind, slot) identifies it."""
        if message.get("action") != "equip":
            return
        pend = self.equipping.get(message.get("char_uid"))
        if not pend:
            return
        kind, slot = pend
        reason = message.get("reason")
        if reason == "wrong_slot":
            self.slot_wrong[kind].add(slot)     # not this slot — try another next time
        elif reason == "stat_requirement":
            self.wont_fit.add(kind)             # can't meet the requirement; stop trying

    # -- village: gear + economy + healing supply + discovery-first deployment --

    def village(self, bot: "Any", frame: dict[str, Any]) -> list[dict[str, Any]]:
        guild = frame.get("guild", {})
        cfg = bot.config
        chars = frame.get("chars", [])
        gold = guild.get("gold", 0)

        for char in chars:
            uid = char["char_uid"]
            if char.get("craft"):
                continue                    # busy crafting; don't disturb or embark it
            # In-flight guard: a char that just acted is skipped for a few ticks so
            # the stale frame doesn't make it re-issue the same buy/sell/equip
            # (v0.14.0 — kills the run-#38 buy/sell re-send storm).
            if bot.tick - self._village_acted.get(uid, -10**9) < VILLAGE_ACTION_COOLDOWN:
                continue
            inv = char.get("inventory", [])
            eqp = char.get("equipment", {}) or {}
            # Brewables we can actually make a no-curdle batch from — the rest are
            # "stranded" (lone herbs that can't pair) and are sold, not hoarded
            # (v0.8.0: hoarding them filled carry and stalled chars in the field).
            brewables = [i for i in inv
                         if "brew" in (i.get("uses") or []) and i["kind"] not in KEEP]
            brew_keep = self._brew_keep_ids(brewables)
            # Ore we can smelt (M3a): kept only while a matching pair exists — a
            # lone ore can't smelt, so it's stranded and sold (same rule as a
            # singleton brewable, v0.8.0, so it never clogs carry).
            smeltables = [i for i in inv if "smelt" in (i.get("uses") or [])]
            smelt_keep = self._smelt_keep_ids(smeltables)
            # 1) EQUIP carried gear into empty slots — BEFORE selling, or we sell
            #    the weapons/armor we ought to be wearing (the original bug: 0
            #    equips ever, everyone bare-handed and unarmored).
            eq = self._equip_action(uid, inv, eqp)
            if eq is not None:
                return [self._village_act(bot, uid, eq, eq.pop("_why"))]
            # 2) sell what we can't use: loot, gear that won't fit, and brewables
            #    that can't form a batch (stranded singletons).
            for item in inv:
                if self._should_sell(item, eqp, brew_keep, smelt_keep):
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "sell",
                                   "item_id": item["item_id"]},
                        f"selling {item['kind']} (tier {item.get('tier')}) to bank gold")]
            # 3) still bare-handed with nothing to equip? buy the best weapon we
            #    can AFFORD and qualify for (v0.13.0). The old gate was a hardcoded
            #    `gold >= 45` = shortsword's price, so a broke guild NEVER bought
            #    the 15-gold club and instead drained gold into 20-gold potions —
            #    a self-inflicted piece of the poverty deadlock. Read the live shop
            #    prices + stat reqs; a club at 15 lowers the bootstrap escape from
            #    45 gold to 15, so the guild can arm a char the moment it scrapes
            #    a little loot, and that char can then survive → loot → recover.
            if eqp.get("hand") is None:
                buy = self._afford_weapon(char, frame, gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying a {kind} ({price}g; bare-handed — arming to break the poverty trap)")]
            # 4) stock a field potion — but only for an ARMED char (v0.13.0): a
            #    bare-handed char can't fight anyway, so gold goes to a weapon
            #    first, never a 20-gold potion while chars are unarmed and broke.
            potions = sum(1 for i in inv if i["kind"] == "potion_red")
            if eqp.get("hand") is not None and potions < POTION_KEEP and gold >= POTION_MIN_GOLD:
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "buy", "kind": "potion_red"},
                    "buying a red potion for the field (survival)")]
            # 4b) brew looted ingredients into potions (M3b), essence-aware
            #     (v0.7.0). Group brewables by their DECODED essence and brew a
            #     single-essence batch — never a vigor+venom mix, which curdles —
            #     preferring vigor (-> potion_red healing). Undecoded herbs brew
            #     only as same-KIND batches (v0.8.0: a same-kind batch shares an
            #     essence so it can't curdle, and its product reveals that kind's
            #     essence cleanly). KEEP items are never spent as ingredients.
            bottles = sum(1 for i in inv if i["kind"] == "bottle_empty")
            picks, ess, healing = self._choose_brew(brewables)
            if picks and bottles == 0 and gold >= BREW_MIN_GOLD:
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "buy", "kind": "bottle_empty"},
                    f"buying an empty bottle to brew a {ess or 'unknown'}-essence batch")]
            if picks and bottles >= 1:
                label = (f"{ess} (-> potion_red heal)" if healing
                         else f"{ess}-essence" if ess else "undecoded (learning batch)")
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "brew",
                               "item_ids": [i["item_id"] for i in picks]},
                    f"brewing {label}: {[i['kind'] for i in picks]}")]
            # 4c) smelt a matching pair of ore into an ingot (M3a forge feedstock).
            #     Needs no bottle and no per-world vocabulary — `smelt` takes only
            #     the two ore item_ids — so, unlike forging, it can never earn an
            #     unknown_* action error. The ingot is banked as metal for forging
            #     (wired once a `product` name is learned; see the class docstring).
            smelt_pair = self._choose_smelt(smeltables)
            if smelt_pair:
                a, b = smelt_pair
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "smelt",
                               "item_ids": [a["item_id"], b["item_id"]]},
                    f"smelting 2×{a['kind']} into an ingot (M3a forge feedstock)")]
            # 5) spend banked XP on durability (safe in the village).
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
            # 6) heal before shipping out.
            if char.get("hp", 0) < char.get("max_hp", 1):
                self._trace(bot, None, frame.get("world"),
                            [f"{uid} hurt ({char['hp']}/{char['max_hp']}); healing in village"],
                            None, 5.0, "resting in village to heal before embark")
                return []

        crafting = {c["char_uid"] for c in chars if c.get("craft")}
        chars_here = guild.get("chars_here", [])
        here = [u for u in chars_here if u not in crafting]
        world_cap = cfg.get("world_cap", 10)
        roster_cap = cfg.get("roster_cap", world_cap)

        # Roster counts for the gates, split by which view is more accurate for each
        # (v0.11.1):
        #  * EMBARK gates on the CURRENT per-map field distribution — the frame's
        #    `chars_by_world` is fresh every tick and accurate for "who is on each
        #    map right now". (v0.11.0 used the spectate count here; being ~45 s
        #    stale it briefly over-embarked on a restart deploy wave -> world_cap.)
        #  * RECRUIT gates on the TOTAL roster vs roster_cap. The frame snapshot's
        #    total is a lagged, partial view that swings 30->6->30, so prefer the
        #    AUTHORITATIVE total from the public spectate endpoint (bot.spectate)
        #    when it is attached and fresh; else fall back to the snapshot total.
        # `here` (who we can embark *now*) always comes from the frame's chars_here.
        by_world = {k: len(v) for k, v in (guild.get("chars_by_world", {}) or {}).items()}
        fielded = sum(by_world.values())
        auth = bot.spectate.counts() if getattr(bot, "spectate", None) else None
        roster = auth[0] if auth is not None else len(here) + fielded

        # In-flight guard (v0.10.0): drop embark records for chars that have left
        # the village (their embark landed), then treat the rest as still pending
        # so we neither re-embark them nor count them as home for the world cap.
        tick = bot.tick
        here_set = set(chars_here)
        self._embark_at = {u: t for u, t in self._embark_at.items() if u in here_set}
        inflight = {u for u, t in self._embark_at.items() if tick - t < EMBARK_COOLDOWN}

        # RECRUIT — but at most once per RECRUIT_COOLDOWN ticks: a just-recruited
        # char is not in the roster for a few frames, so re-firing every tick
        # storms roster_cap once we reach the cap.
        if roster < min(world_cap, roster_cap) and (
                self._recruit_at is None or tick - self._recruit_at >= RECRUIT_COOLDOWN):
            self._recruit_at = tick
            return [self._village_act(bot, None, {"action": "recruit"},
                                      f"recruiting (roster {roster} < cap)")]

        # EMBARK — skip chars whose embark is already in flight (the stale-frame
        # duplicate-send storm that bounced no_such_character), and count those
        # in-flight embarks toward the world cap so we don't over-deploy either.
        here_avail = [u for u in here if u not in inflight]
        if here_avail and fielded + len(inflight) < world_cap:
            maps = [m["id"] for m in cfg.get("maps", [])] or list(DEFAULT_MAPS)
            party_cap = cfg.get("party_cap", 5)
            target = min(maps, key=lambda m: by_world.get(m, 0))
            if by_world.get(target, 0) < party_cap:
                uid = here_avail[0]
                self._embark_at[uid] = tick
                return [self._village_act(
                    bot, None, {"action": "embark", "map": target,
                                "char_uids": [uid]},
                    f"embarking {uid} to {target} (fewest of us there — spread to explore)")]
        return []

    # -- field: per-character scored decision ---------------------------------

    def act(self, bot: "Any", char: dict[str, Any], frame: dict[str, Any],
            ctx: FieldContext, trace: DecisionTrace) -> None:
        uid = char["char_uid"]
        if char.get("craft"):
            # A craft (brew/smelt/forge) occupies the character; any other action
            # is rejected with `crafting`, and moving/embarking abandons the work.
            trace.observe(f"crafting ({char['craft'].get('ticks_left')} ticks left) — busy")
            trace.consider(None, 1.0, "crafting in progress; wait it out")
            return
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
            # Moves need headroom above the raw cost (v0.9.0): the frame we decide
            # on can be ~1 tick stale, so a step that looks affordable is rejected
            # not_enough_stamina when the server's live stamina is lower. A margin
            # keeps the char resting (double-rate regen) until the step is a safe
            # bet. Non-movement actions barely ever error on stamina — leave them
            # at the raw cost so combat/healing aren't throttled.
            need = int(cost * MOVE_STAMINA_SAFETY) if name in ("move", "ride") else cost
            if stamina >= need:
                trace.consider(action, score, why)
            else:
                trace.observe(f"wanted {name} ({why}) but stamina {stamina} < ~{need}: resting")

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

        # Overburdened (carry weight at/over cap): the server's overburden penalty
        # makes the walk home unaffordable, so a stranded char sits here for
        # hundreds of ticks until poison kills it (v0.15.0). Shed the least-useful
        # loot to get back under cap and regain mobility — above the full-retreat
        # so it drops before it tries (and fails) to step, and pickup is suppressed
        # below since `full` is necessarily true here.
        if carry["used"] >= carry["cap"]:
            shed = self._shed_item(char)
            if shed is not None:
                offer({"char_uid": uid, "action": "drop", "item_id": shed}, 8.0,
                      "overburdened — dropping loot to regain mobility")

        if full:
            self._retreat(uid, pos, ctx, blocked, offer, 7.5,
                          "pack full — heading home to sell")

        # Pursue loot only with room to spare: a `full` char (used >= cap-1) that
        # grabs or chases more loot crosses into overburden and strands (v0.15.0) —
        # it should be heading home to sell, not collecting more.
        if not full:
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

    def _equip_action(self, uid: str, inv: list[dict[str, Any]],
                      eqp: dict[str, Any]) -> dict[str, Any] | None:
        """Equip the first carried, equippable item into an empty slot it has not
        already been rejected from. Slots are learned by trial (see
        on_action_error), so this needs no content knowledge of which item goes
        where. Returns an equip action (with a ``_why`` note) or None."""
        for item in inv:
            kind = item["kind"]
            if "equip" not in (item.get("uses") or []) or kind in self.wont_fit:
                continue
            slot = next((s for s in EQUIP_SLOTS
                         if eqp.get(s) is None and s not in self.slot_wrong[kind]), None)
            if slot is None:
                continue                    # no empty, not-known-wrong slot for it
            self.equipping[uid] = (kind, slot)
            return {"char_uid": uid, "action": "equip", "slot": slot,
                    "item_id": item["item_id"],
                    "_why": f"equipping {kind} -> {slot} "
                            f"(wrong so far: {sorted(self.slot_wrong[kind]) or 'none'})"}
        return None

    @staticmethod
    def _afford_weapon(char: dict[str, Any], frame: dict[str, Any],
                       gold: int) -> tuple[str, int] | None:
        """The CHEAPEST hand-weapon the char can afford and meets the stat
        requirement for, from the live shop stock — so a broke guild arms the most
        chars per gold (a 15-gold club beats waiting for a 45-gold shortsword).
        Prices/reqs are read from the frame, never hardcoded (the economy shuffles
        per world). ``None`` if we can't afford any."""
        stock = (frame.get("shop", {}) or {}).get("stock", []) or []
        stats = char.get("stats", {}) or {}
        affordable = [
            s for s in stock
            if s.get("kind") in WEAPON_KINDS and isinstance(s.get("buy_price"), int)
            and gold >= s["buy_price"]
            and all(stats.get(k, 0) >= v for k, v in (s.get("req") or {}).items())]
        if not affordable:
            return None
        best = min(affordable, key=lambda s: s["buy_price"])
        return best["kind"], best["buy_price"]

    @staticmethod
    def _choose_brew(brewables: list[dict[str, Any]]
                     ) -> tuple[list[dict[str, Any]] | None, str | None, bool]:
        """Pick a *single-essence* batch of 2-4 ingredients so the brew can't
        curdle, preferring vigor (which yields the healing ``potion_red``).

        Returns ``(picks, essence, is_healing)``. ``picks`` is None when no
        brewable batch is safe (e.g. one vigor + one venom and nothing else —
        every pairing would mix opposites, so we brew nothing rather than curdle).
        Undecoded ingredients (essence None) are only ever batched with each
        other, as a learning brew — never mixed with a known essence they might
        oppose."""
        groups: dict[str | None, list[dict[str, Any]]] = defaultdict(list)
        for it in brewables:
            groups[knowledge.essence_of(it["kind"])].append(it)
        # Prefer a vigor batch (heals), then any other decoded essence, then a
        # batch of purely-undecoded herbs (to keep learning) — never a mix.
        known = [e for e in groups if e is not None]
        order = (["vigor"] if "vigor" in known else []) \
            + sorted(e for e in known if e != "vigor")
        for ess in order:
            g = groups[ess]
            if len(g) >= BREW_MIN:
                return g[:BREW_MAX], ess, ess == "vigor"
        # No decoded batch. Learn undecoded herbs with a same-KIND batch (shares
        # an essence -> can't curdle -> product cleanly reveals that kind's
        # essence). Never mix different unknowns (that curdled in 0.7.0).
        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for it in groups.get(None) or []:
            by_kind[it["kind"]].append(it)
        for kind in sorted(by_kind):
            g = by_kind[kind]
            if len(g) >= BREW_MIN:
                return g[:BREW_MAX], None, False
        return None, None, False

    @staticmethod
    def _brew_keep_ids(brewables: list[dict[str, Any]]) -> set[str]:
        """Item_ids of brewables that can currently form a no-curdle batch — a
        decoded-essence group of >=2 (any kinds) or a same-kind group of >=2
        undecoded herbs. Everything else is a stranded singleton: worth more as
        banked gold than as carry-clogging clutter that stalls the character."""
        by_ess: dict[str, list[dict[str, Any]]] = defaultdict(list)
        by_unknown_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for it in brewables:
            e = knowledge.essence_of(it["kind"])
            (by_ess[e] if e is not None else by_unknown_kind[it["kind"]]).append(it)
        keep: set[str] = set()
        for g in list(by_ess.values()) + list(by_unknown_kind.values()):
            if len(g) >= BREW_MIN:
                keep.update(it["item_id"] for it in g[:BREW_MAX])
        return keep

    @staticmethod
    def _choose_smelt(smeltables: list[dict[str, Any]]
                      ) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """Two matching ore (same kind) to smelt into an ingot, or None. `smelt`
        needs a MATCHING pair — a lone ore or two different ores can't smelt — so
        we group by kind and take the first kind with >=2."""
        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for it in smeltables:
            by_kind[it["kind"]].append(it)
        for kind in sorted(by_kind):
            g = by_kind[kind]
            if len(g) >= 2:
                return g[0], g[1]
        return None

    @staticmethod
    def _smelt_keep_ids(smeltables: list[dict[str, Any]]) -> set[str]:
        """Item_ids of ore worth keeping to smelt — every ore of a kind that has a
        matching pair (>=2 of that kind). A lone ore of its kind can't smelt, so it
        is stranded and sold rather than hoarded (the v0.8.0 carry lesson)."""
        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for it in smeltables:
            by_kind[it["kind"]].append(it)
        keep: set[str] = set()
        for g in by_kind.values():
            if len(g) >= 2:
                keep.update(it["item_id"] for it in g)
        return keep

    def _should_sell(self, item: dict[str, Any], eqp: dict[str, Any],
                     brew_keep: set[str], smelt_keep: set[str]) -> bool:
        """Sell only what we can't use. Keep: field supplies (KEEP), consumables
        and food (`drink`), brew ingredients that can still form a batch
        (`brew_keep`), ore that can still form a smelt pair (`smelt_keep`), and
        gear we might still equip. Everything else — pure loot AND stranded
        singleton brewables/ore (v0.8.0/v0.10.0) — is banked for gold, so lone
        herbs and ore don't hoard up and clog carry."""
        kind = item["kind"]
        uses = item.get("uses") or []
        if kind in KEEP or "drink" in uses:
            return False
        if "brew" in uses:
            return item["item_id"] not in brew_keep   # sell stranded brewables
        if "smelt" in uses:
            return item["item_id"] not in smelt_keep   # sell stranded (unpaired) ore
        if "equip" not in uses:
            return True                     # pure loot -> bank it
        if kind in self.wont_fit:
            return True                     # equippable but fails its stat requirement
        # otherwise keep it only while a slot it could still go into remains:
        return all(s in self.slot_wrong[kind] or eqp.get(s) is not None
                   for s in EQUIP_SLOTS)

    @staticmethod
    def _shed_item(char: dict[str, Any]) -> str | None:
        """The least-useful carried item to drop when overburdened (v0.15.0).

        Shed pure loot clutter first — items with no craft/consume use — so a
        stranded char regains mobility while keeping what's worth carrying home:
        field supplies (``KEEP``), equippable gear, and craft ingredients (brew
        pairs, smelt ore). If only those remain, fall back to dropping a non-gear
        item anyway (better to lose one ore than the whole char and all its loot
        to a poison death). Returns an ``item_id`` or ``None`` if nothing but
        equipped-class gear and KEEP supplies is carried."""
        inv = char.get("inventory", []) or []

        def droppable(i: dict[str, Any]) -> bool:
            return i.get("kind") not in KEEP and "equip" not in (i.get("uses") or [])

        craft_or_consume = {"brew", "smelt", "drink"}
        clutter = [i for i in inv
                   if droppable(i) and not (craft_or_consume & set(i.get("uses") or []))]
        pool = clutter or [i for i in inv if droppable(i)]
        return pool[0]["item_id"] if pool else None

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
        # Record per-char village actions for the in-flight re-send guard (v0.14.0).
        # Guild-level actions (recruit/embark, uid=None) have their own guards.
        if uid is not None:
            self._village_acted[uid] = bot.tick
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
