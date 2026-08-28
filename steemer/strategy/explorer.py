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

v0.16.0 — 0.15.0 measured as a PARTIAL win with a nasty regression: run #55
(0.15.0, 137k frames) cut permanent-stuck overburden (raw overburdened 30->11/1k,
status_damage 41->17/1k) and pickups leapt (10->60/1k) — BUT `sale`/`returned`
per-frame FELL and gold stayed ~14, and drop matched pickup almost 1:1 (8190 vs
7029). Event-stream drill found a PICKUP<->DROP THRASH: the shed `drop` lands the
item on the char's own tile; shedding takes `used` back below `cap-1` so the char
reads as "not full" again and re-grabs the very item it just dropped — overburden,
drop, re-grab, forever (one char logged the loop hundreds of times on a single
tile, and even at the village edge [47,0]). The `not full` gate can't stop it
because a single drop flips the char out of "full". Fix: a HOMING LATCH — once a
char is full it enters a `_homing` state in which ALL looting (pickup and
loot-seeking) is suppressed, so a dropped item is never re-grabbed; it heals/flees
if hurt, sheds if overburdened (to stay mobile), and otherwise only retreats
toward the village. The latch clears once the char is light again (`used <=
cap*HOME_CLEAR_FRAC`, i.e. after the village sells its haul), with hysteresis
(enter at cap-1, exit at half-cap) so it can't flicker. Expected: drop collapses
toward the rare genuine shed, pickups convert to `returned`/`sale`, gold rises.

v0.17.0 — 0.16.0 measured as a DECISIVE win (run #56 vs #55/#52): drop/pickup
collapsed 0.86->0.065 (thrash dead), returned leapt 0.9->9.5/1k (~93% of pickups
now reach the village vs ~10% before), sale 0.8->3.4/1k, gold income 2.1->11.0/1k
(2.7x the 0.14.0 baseline), overburden 10.4->0.4/1k, our deaths 1.4->0.84/1k. The
mechanical loot->gold pipeline is fixed. BUT the gold BALANCE still oscillates
0-18 and won't accumulate: the guild earns ~11/1k and spends it all, and it is too
poor to cross the 20-gold potion price, so fielded chars go out potion-less (only
1 of 9 carried one) and die to poison (status_damage is the top damage source) —
dropping their gear+loot, a death->reloss treadmill. Root cause in the spend
order: the per-char village loop arms any bare char (club, 15g, step 3) BEFORE an
armed char can reach the potion step (25g, step 4), and we already hold ~12 armed
chars > world_cap (10) — so scarce gold is drained arming bench-warmers who can't
even be fielded, instead of keeping armed EARNERS alive. Fix: (1) POTION_MIN_GOLD
25->20 — buy the potion at its actual price (a poison death loses far more than
20g). (2) a survival reserve on arming: once the guild HAS earners (any char
fielded or armed), only buy a weapon for a bare char from gold ABOVE a
WEAPON_BUY_RESERVE (=one potion), so the treasury can climb past the potion
threshold and armed earners get healed. When there are NO earners yet (bootstrap),
arm with no reserve — preserving the 0.13.0 escape from the broke-and-bare
deadlock. Expected: weapon over-buying tapers, potion buys appear, fielded chars
survive poison, deaths fall further, and gold finally accumulates off ~14.

v0.18.0 — 0.17.0 measured as a REGRESSION and is reverted (the WEAPON_BUY_RESERVE
part). Run #73 (0.17.0, 67k frames) vs run #56 (0.16.0): our deaths did crater
(0.68->0.01/1k) and recruit churn collapsed (216->21 — confirming the churn was
death-replacement) — BUT income and productivity fell with them: gold income
9.9->2.3/1k, sales 220->46, pickups 9.3->3.1/1k, attacks 79->34/1k, and gold still
stuck (mean ~9, max 18). The near-zero deaths came WITH near-zero engagement — the
chars were idle, not thriving. And an EMBARK<->RETURN churn appeared: 32 surviving
chars each embarked ~360x / returned ~130x (11.5k embark events, but only 46 sales)
— armed, healthy, FULL-of-loot chars cycling the field edge without offloading.
The exact churn mechanism is not yet pinned (chars_here always matched the village
`chars` list, so it is NOT a just-returned-not-yet-sellable timing gap; embarks far
exceed returns, hinting at silently-accepted redundant embark sends) — logged as an
open question rather than guessed at. What IS clear is the reserve made things
worse, so it is reverted: arm a bare char whenever affordable again (as in 0.16.0).
POTION_MIN_GOLD stays 20 (harmless — buy a potion at its real price). The gold-
accumulation goal remains open; the next lever is the embark-churn root cause.

v0.19.0 — ROOT-CAUSED the embark<->return churn / stuck-gold; it is the same bug in
every version. Traced the top embarker (run #74, c9888): it carried 22-23/24 — FULL
— the entire time, of egg/meat/tomato/berries/turnip (all `uses:['drink']`) plus
bottles. `_should_sell` refused to sell ANY `drink` item ("keep food"), but the
guild never EATS food, so packs fill with unsellable food, chars are pinned `full`
(homing) forever, and — having no sellable action in the village — the per-char
loop finds nothing to do, so `village()` re-EMBARKS the char straight off the
boundary back into the field. It walks to the edge, is yanked back, walks to the
edge… never offloading (c9888: 1183 embarks, ~0 sales). That is why gold never
accumulates in ANY version — masked before by death-churn, exposed once 0.17.0 kept
chars alive. Food is demonstrably SELLABLE (meat/egg/berries are among the top-sold
items historically; the shop buys anything) and chars sit at full HP hoarding it,
so it is pure loot. Fix: `_should_sell` now sells food — it keeps only KEEP field
supplies and actual medicinal drinks (potion*/vial*/elixir*/tonic*), and sells
everything else including raw `drink` food. This unclogs the pack, so a returning
char SELLS (a per-char action) instead of being re-embarked, breaking the thrash.
Expected: sales rise toward the pickup/return rate, the embark:return ratio falls
toward 1, and gold finally climbs off ~9.

v0.20.0 — 0.19.0 WORKED (run #75 vs #74: gold_max 19->542, gold_mean 6.3->99.9,
sale/1k 2.1->9.82, embark churn 8101->906) — the poverty arc is CLOSED, gold
accumulates. The binding constraint is now EQUIPMENT, not gold: a run-#75 snapshot
showed 6 of 10 fielded chars BARE-handed and 0 with armor, despite gold cycling to
500+. Cause: the embark section fields `here_avail[0]` with NO armed-status check,
so a bare char gets shipped out during a gold-dip (gold oscillates below the 15g
club price) before the village arms it, then stays bare (returns are rare). Fix:
embark only ARMED chars — keep bare chars home to be armed first (now affordable),
so the field is a capable force that fights, survives, and earns. Bootstrap
exception: if nothing is fielded AND no armed char is home, field a bare char so a
cold-started guild can still begin looting (preserves the 0.13.0 escape). Expected:
fielded-armed fraction rises toward 100%, deaths fall, income/kills rise.

v0.21.0 — 0.20.0 was a REGRESSION and is reverted. Run #76 (0.20.0) vs #75 (0.19.0):
the armed-only embark filter EMPTIED the field — fielded_mean 9.9->1.8 — because the
guild does not hold enough ARMED chars to fill world_cap (only ~4), so removing the
bare "padding" collapsed the field to ~2. Income cratered with it: sale/1k
9.18->2.84, gold_mean 93.7->6.5, gold_max 530->13 — straight back to poverty, a
death spiral (empty field -> no income -> no gold -> can't arm -> field stays
empty). Lesson: a bare char in the field still picks up loot and holds a slot, which
beats an empty slot; arming is the village loop's job, not grounds to bench them.
Reverted to fielding ANY available char (0.19.0 behaviour). The real equipment lever
must improve chars WITHOUT shrinking the field — upgrade weapons on already-fielded
chars, wire spend_xp, or forge armor — not gate who gets fielded.

v0.22.0 — after the 0.20.0 spiral, run #77 (0.21.0) recovered only PARTIALLY: field
full again but gold stuck (mean 8.6, max 48 vs run #75's mean 93.7/max 530) because
OUR deaths doubled (38->80) — a poison-death churn (status_damage/1k 26.9->50.3;
chars die at low-y, mid-retreat) that spawned 303 recruits and keeps the roster
young (lvl 2-6) and weak, capping income. The gold-independent counter is DURABILITY
— but spend_xp has fired 0 times in ALL history. Root cause found: `_pick_xp_stat`
returned the top survival-priority stat (VIT) regardless of cost, and VIT's cost
grows with its value (v=5 -> 40 XP), so a char banking ~17 XP was stuck wanting an
unaffordable VIT and never spent the XP on a CHEAP stat it could afford (END at v=1
costs 8 — and END, at 1, is the real deficit: low stamina can't outrun poison). Fix:
`_pick_xp_stat` now returns the highest-priority stat that is BOTH below the cap AND
affordable with the char's banked XP, so spend_xp finally fires and chars convert
their idle XP into durability (END stamina first while cheap, then VIT/STR). Gold-
independent, no field-size effect. Expected: spend_xp goes 0->active, stats climb,
deaths fall, the roster matures, and gold accumulation resumes.

v0.23.0 — 0.22.0's spend_xp fix proved INERT (spend_xp still 0 over run #78's 65k
frames): the xp-rich chars are perpetually fielded and the roster is so small
(~8, all fielded) the village is essentially EMPTY, so the village XP step never
runs. Meanwhile the poison-death spiral WORSENED (deaths/1k 0.57 run#75 -> 1.33
#77 -> 1.57 #78; gold stuck ~7, all income drained re-arming 268 dying recruits).
Root of the deaths: chars get poisoned deep in the field (death y-depths median 28)
and die mid-retreat before reaching the poison-clearing village — with only ~1/10
carrying a heal, and potions/bottles unaffordable at gold 7. The gold-free,
field-size-safe, gold-drain-safe counter: keep an UN-HEALED char (no potion_red)
SHALLOW — it only pushes into frontier/unexplored ground while above
POISON_SAFE_DEPTH, so its poison-retreat home is short enough to survive. A char
carrying a potion may still range deep (it can drink en route). Expected: fewer
mid-retreat poison deaths, the roster survives to mature, and the churn/gold-drain
unwind.

v0.24.0 — GOLD-RUSH (operator directive: with the world now overrun by poison undead
that our broke/young roster can't beat, stop trying to fight it — pivot to grabbing
and STOCKPILING gold). Data behind it: income is ~half FIELD GOLD COINS (banked to
the treasury instantly = death-proof; only ~3% are tied to a kill, so no fighting
needed) and ~half sales; CHESTS give direct gold (1-21g) PLUS loot and there are
~39/run (renewed each band-refresh); the NPC shop has no arbitrage (sell ~= 20% of
buy) and the player market is empty. So: (1) FIELD — beeline to gold coins (5.0) and
chests (4.5) over ordinary loot (4.0); cracking an adjacent chest is a top priority
(7.0); do NOT chase monsters (combat isn't the gold source and it's what kills us) —
only the adjacent-attack (8.0) still defends. (2) VILLAGE HOARD — freeze potion-buys
and bottle-buys; keep only the cheap 15g club for a bare char (operator's call) and
free brewing with bottles already held; everything else is banked. Survival now
leans on v0.23.0's shallow-venture + not fighting. GOAL: stockpile — and, since the
most gold ever held is 529 (run #75), find out whether a gold CAP exists by actually
pushing past it.

v0.25.0 — EXTRAORDINARILY DRASTIC gold-rush + band-mood awareness (operator
directive). 0.24.0 stalled because the world was in a 100%-UNDEAD band and "don't
chase" wasn't enough — chars still got poisoned in the unavoidable adjacent
skirmishes. The maps refresh on a periodic ~14.4-15.6k-tick BAND cycle (4 bands per
world, announced by `next_refresh {band,in_ticks}` and `band_refresh_warning
{in_ticks:240}`), rotating the mob set between benign wildlife and poison undead.
So the fix is mood-adaptive: when THREAT mobs (undead — cultist/zombie/ghoul/…) are
within FLEE_RADIUS, the char FLEES to the village and does NOT loot or fight —
snatching only a coin already underfoot (instant, banked) on the way, and fighting
only if cornered with no escape. When the local band is safe (wildlife), the 0.24.0
gold-rush runs normally. Net: evade the undead rushes, harvest gold during the calm
bands. The band cycle is analysed each loop pass to characterise/anticipate rushes.

v0.26.0 — 0.25.0 halved deaths (2.74->1.02/1k) but gold still would not stockpile
(mean ~10): the world was undead-heavy most of run #81 (7+/12 windows >=60% undead),
so chars spent most of their time FLEEING and the wildlife harvest windows were too
short/rare — a "survive but barely earn" state. Two fixes to actually accumulate:
(1) SAFE-WORLD ROUTING — track each world's live undead fraction (self._world_threat,
expiring after THREAT_TTL so an emptied world is re-scouted) and, at embark, field
chars into the SAFEST world (lowest undead), concentrating the guild in the wildlife
world and out of the undead ones (a fled char re-routes to safety). (2) LOOSENED
FLEE — a fleeing char may still fetch a gold coin that lies farther from every threat
than it does (a coin in the safe direction), recovering income during an undead band
without re-engaging the swarm. Expected: gold finally builds as the guild clusters
where it's safe and still banks the easy coins.

v0.27.0 — 0.26.0 was a big win (deaths 1.02->0.2/1k; chars correctly cluster in the
wildlife worlds and shun the undead one; chest/coin income recovered) BUT gold STILL
would not stockpile (mean ~11, one spike to 51): the drain was RECRUITING. Recruit
is free, but it fired toward the server's high roster/world cap (roster grew to 23
while we only field ~10), and every new bare recruit got a 15g club — so income
(~362g/run) cycled straight back out as clubs (gold went 0->14->buy->0 forever).
Fix: recruit only up to what we can FIELD — party_cap * maps + a small bench
(RECRUIT_BENCH) — instead of the full cap. The undeployable bench stops growing, the
club-arming drain tapers once the current roster is armed, and income can finally
accumulate. (Keeps the operator's 'a club per char' — it just stops recruiting chars
we can't field.) Expected: gold climbs off ~11 and, at last, tests the 529 ceiling.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .. import intel, knowledge, nav, protocol
from .base import FieldContext
from ..reasoning import DecisionTrace

RETREAT_HP = 0.6           # flee below 60% HP — early enough to still afford the run
POISON_SAFE_DEPTH = 12     # v0.23.0: a char with no field heal (potion_red) only
#   pushes into frontier/unexplored ground while shallower than this (rows north of
#   the y=0 village edge). Poison is a DOT that kills chars mid-retreat from deep
#   ground; capping how far an un-healed char ventures keeps its walk home short
#   enough to survive. A char carrying a potion may range deep (it can drink en route).
# v0.36.0: DEPLETION-AWARE retreat. Run #91 study: 58% of fielded char-frames have ZERO
# gold-tiles visible — worlds go COIN-DEPLETED between band refreshes, and a char with
# nothing left to grab or explore currently just scout-WANDERS (the 1.0 "stepping to
# scout" offer) — wasting stamina (move_failed) and idling exposed to predators (the
# post-mortem's stuck-deaths). A band refresh REPLENISHES coins (vale gold-tiles 0.12
# -> 1.43 across a refresh). So: when a char is genuinely out of work (no reachable
# gold/loot/chest AND no frontier), head HOME to re-embark to a fresher world — UNLESS
# this world's next_refresh is imminent (fresh coins land here in < REFRESH_STAY_TICKS),
# in which case stay put and wait for them rather than pay a home round-trip.
REFRESH_STAY_TICKS = 400
DOT_KINDS = frozenset({"poison", "burn"})   # damage-over-time: flee regardless of HP
# v0.25.0: THREAT mobs — the poison/burn-dealing undead that the periodic band-refresh
# rushes bring (they drive the death spiral). When one is within FLEE_RADIUS a healthy
# char EVADES (flees, no loot/fight) instead of skirmishing. These CHASE/range, so we
# keep a wide berth. (Everything that isn't undead and isn't in WILDLIFE_SAFE is treated
# as a melee predator — block-adjacent + dodge — see _is_melee_predator.)
THREAT_KINDS = frozenset({"cultist", "zombie", "ghoul", "vampire_bat", "cinder_wisp",
                          "skeleton", "wraith", "lich", "ghast", "specter", "revenant"})
FLEE_RADIUS = 4            # Manhattan tiles: flee when a THREAT is this close or nearer
# --------------------------------------------------------------------------- #
# v0.48.0 ADAPTIVE COHESION — draw together where it pays, stay spread where it does not.
#
# MEASURED before building (2026-08-21, from our own event history; rivals cluster and we
# do not, so their kills were the experiment):
#   participants   DPS on the mob   party dmg taken/tick   per-MEMBER dmg taken/tick
#        1              2.36                0.51                    0.51
#        2              4.80                0.49                    0.24
# Damage output roughly doubles, and it holds within mob kind (rat_grey 1.86->6.07, wolf
# 3.78->10.42, skunk 2.59->5.97). The party's total intake per tick is FLAT because a mob
# swings at ONE target per tick -- so per-member intake halves. Net ~2x kill speed at ~half
# personal damage: roughly 4x less damage taken per member per kill.
#
# XP is SPLIT (total per kill is flat in participant count: 5.70 at 1p, 5.87 at 2p), so
# cohesion is not an XP multiplier -- but halved share x doubled kill rate leaves XP/TIME
# about unchanged, and the safety margin is what buys access to content worth more XP.
#
# WHY THE LEASH IS STANDING AND NOT REACTIVE: median solo time-to-kill is 6 ticks, our mean
# pairwise distance was 22-25 steps, and movement is a tile per tick. "Gang up, a mob is
# near" therefore arrives ~16 ticks AFTER the fight ended. Only the spreading-out half can
# be reactive; the coming-together has to already have happened.
COHESION_SCORE = 2.8       # ABOVE frontier(2.5)/scout(1.0) so idle chars close up, BELOW
                           # spacing(3.0) so predator-avoidance always wins -- never walk
                           # into a mob to reach a friend -- and below gather(4.0+).
COHESION_PULL = 4          # start closing when the nearest ally is farther than this...
COHESION_HOLD = 2          # ...and stop once within this. The GAP is deliberate: without
                           # hysteresis two chars each closing on the other oscillate, and
                           # cohesion-vs-spacing is the known deadlock hazard (v0.37).
COHESION_PRED_DENSE = 2    # a world with this many melee predators in view counts dangerous
# v0.48.1 — 0.48.0 shipped INERT. Measured on run #116: cohesion was offered 28 times and
# chosen 0, losing every single time to "moving toward loot" (4.0). Placing it at 2.8 to
# avoid displacing income was correct in intent and useless in practice, because loot is
# almost always available, and the existing ladder already puts gathering ABOVE spacing —
# so "below spacing" forces "below gathering" too, and cohesion can never win a tick.
# The fix is not a higher score, which would cost income and break the spacing ordering:
# it is to stop COMPETING with gathering and instead BIAS it. When a character is out of
# position in a dangerous world, prefer loot that lies near an ally. Same action, same
# score, same income — the formation just closes while we work.
COHESION_DETOUR = 10       # ...but only if such loot is within this far, so forming up can
                           # never send a character across the map past nearer loot.
# v0.73.0 — 0.72.0 fixed the mutual pursuit and the group STILL did not converge. Measured
# on #150 vs #151: group spread median 43 -> 39 tiles, frames with the group tight
# (spread<=6) 1.7% -> 1.3%, while cohesion's share of CHOSEN decisions went UP, 11.6% ->
# 17.6%. The centre rally converges in simulation and not in play, because a rally is not
# a one-tick action: it needs uninterrupted ticks, and a FIELD STINT IS MEDIAN 9-10 TICKS
# (only 1.6-3.4% run to 60). Distance to the group centre is median 13, p75 22 — so for
# most characters most of the time the rally CANNOT finish before the stint ends, and the
# movement is spent for nothing. This is the same defect as the over-long ore errand: an
# errand must be sized against uninterrupted time, not against how far the target is.
# The fix is not another pathing change. It is to attempt the rally ONLY when it can
# actually complete, and otherwise leave the character to do something productive.
# PREMISE(2026-08-22, a rally is worth starting only if a median field stint can close it):
#   SELECT ... -- see tools/field_stints.py; re-derive COHESION_RANGE from the stint median
COHESION_RANGE = 8         # rally only from within this far of the centre: ~8 ticks of
                           # walking, inside the median stint. Held 34.6% of the time on
                           # #151, so cohesion becomes an occasional achievable action
                           # instead of a permanent unachievable one.
PRED_SPACING_RADIUS = 2    # v0.37.0: step away from a MELEE predator this close (not yet
#   adjacent) BEFORE it lands the first hit — the anti-stuck lever (see the act() block).
# v0.38.0 MODE-GATED SPACING: 0.37 spaced at a flat 3.0 in EVERY band, which cost ~-49%
#   gold-coin gathering (chars fled coins in calm wildlife bands too). Now the spacing SCORE
#   depends on band severity: in a SEVERE band (undead-heavy or predator-swarmed) it stays
#   high so a char disengages; in a CALM band it drops below the explore/gather offers so a
#   char keeps working — but still above rest, so it never idles adjacent to a predator.
SPACE_SCORE_SEVERE = 3.0    # beats scout(1.0)/frontier(2.0-2.5): char leaves a dangerous band
SPACE_SCORE_CALM = 1.5      # beats rest(0.5)/scout(1.0), LOSES to frontier(2.0+)/gather(4.0+)
# v0.39.0 PER-CHARACTER ROLES (operator's Phase 2): a char's role biases the severity
# threshold at which it flips harvest<->survive, so the roster diversifies its risk. The
# role is DERIVED from level (protect the XP investment), not stored, so it self-adjusts:
#   GUARDIAN = a leveled veteran -> disengages EARLY (low thresholds), protect the investment.
#   FORAGER  = a fresh recruit   -> works the EDGES of danger for income (high thresholds);
#              cheap to replace, and a forager that banks coins before dying beats a timid one.
GUARDIAN_LEVEL = 4             # level >= this -> Guardian; else Forager
FODDER_STAT_SUM = 7            # v0.87.0: stats sum <= this (and no int gift) = fodder

# v0.96.0 THE NUISANCE (operator, for fun): one of our characters shadows rival guild
# WillMorr's party in the vale — hangs in the centre of their group, helps kill what
# they fight, loots their fallen, and cackles home with the spoils. A whole questline
# for one volunteer, alive only while Will's party is actually in the vale.
NUISANCE_GUILD = "g_63837f"        # WillMorr (his chars are named Barbarian/Ranger/…)
NUISANCE_GUILD_NAME = "WillMorr"
NUISANCE_WORLD = "vale"            # the operator's chosen stage
NUISANCE_TRIGGER = 3              # designate once this many of Will's chars share the vale
NUISANCE_GONE_TTL = 40           # ticks unseen before Will counts as gone and we stand down
NUISANCE_FOLLOW_SCORE = 3.6       # hang near Will's centroid — above frontier, below gather
NUISANCE_HANG_RADIUS = 2         # "in the centre" = within this of the party centroid
                                # (the centroid tile itself is usually one of Will's chars)
NUISANCE_LOOT_SCORE = 6.0        # beeline to a fallen Will member's drop (above gather)
NUISANCE_DELIVER_SCORE = 6.0     # beeline home with the spoils
NUISANCE_LAUGH_SCORE = 6.1       # the cackle wins the FIRST deliver tick (above the
                                # beeline 6.0), then laughed=True and it runs home
NUISANCE_POUT_SCORE = 3.8        # ":(" when Will hits us — just above the follow (3.6) so
                                # a hit shows, below loot/deliver (6.0) and survival (8.0+)
NUISANCE_POUT_COOLDOWN = 25
NUISANCE_POUT = ":("
NUISANCE_LAUGH = "mwahahahaha"    # said once, running away with the loot
UNDEAD_SEVERE_GUARDIAN = 0.08  # veteran trips "severe" at half the undead fraction...
MELEE_DENSE_GUARDIAN = 2       # ...and at 2 melee predators (disengage early)
UNDEAD_SEVERE_FORAGER = 0.20   # recruit tolerates a denser band before disengaging...
MELEE_DENSE_FORAGER = 4        # ...and needs 4 melee predators to call it severe
MELEE_DENSE_FODDER = 6         # v0.87.0: fodder barely acknowledges a swarm at all
# v0.32.0: INVERTED to a benign ALLOWLIST. The 0.30/0.31 denylist (golem_stone,
# delver, boar, spider_brown, …) was structurally doomed: every band-refresh rotates
# in NEW mobs, so a hardcoded threat list is always a cycle behind and chars die to
# each newcomer until it's cataloged. Run #87 proved it — the dodge/block ZEROED the
# known killers (delver 25->0, spider 6->0) but deaths ROSE to 4.0/1k because a fresh
# band brought lava_ant (40 HP-drops) and rhino_beetle (7), in no set. So flip the
# model: a monster is a MELEE PREDATOR by DEFAULT unless it's confirmed-benign wildlife
# here. New/unknown mobs are now avoided (block-adjacent + dodge) on sight instead of
# after the first corpse. WILDLIFE_SAFE holds only kinds never once blamed for a
# >=5/tick HP-drop across runs #85-87 (turtle/chicken/cow/sheep/frog/skunk/rat/mole/
# bat). Undead (THREAT_KINDS) keep their wider radius-4 flee; everything else that
# isn't benign gets the melee treatment.
WILDLIFE_SAFE = frozenset({"turtle", "chicken", "cow", "sheep", "frog", "skunk",
                           "rat_grey", "mole"})
# v0.111.0: bat_brown REMOVED from the allowlist on evidence — 27 recorded attacks at
# ~3 damage each across runs #210-215 (a swarm of them finished Recruit-19575), and
# the kind is ABSENT from the frozen bestiary snapshot: it post-dates the profile
# freeze, so "safe" was never measured, only assumed. Combat-seek must not walk
# armed chars into bat swarms believing them harmless.
# Confirmed-dangerous kinds seen so far (documentation only — the LOGIC uses the
# allowlist above, so this need not be exhaustive): golem_stone, delver, boar, drake,
# lake_drake, spider_brown, wolf, crab_green, lava_ant, rhino_beetle.
DEATH_GATE_TTL = 900       # v0.92.1: one of OUR corpses marks its world dangerous for
                           # this long — under a band cycle, so a cleared band un-gates,
                           # but serial killings re-latch on every victim
THREAT_TTL = 1200          # v0.26.0: a world's observed undead level is trusted for this
#   many ticks; after that it's treated as unknown (re-scoutable) so a world that has
#   emptied out (everyone fled) gets re-checked once its band may have cycled back to
#   wildlife — otherwise safe-world routing would avoid it forever.
KEEP = frozenset({"potion_red", "bottle_empty"})   # field/craft supplies we never sell

# v0.46.0 FORGE FEEDSTOCK. 0.45 taught chars to chop trees, and run #113 chopped 282 of
# them -- then SOLD 189 lumber, 4 ore and even 2 INGOTS we had deliberately smelted. The
# leak was `_should_sell`: lumber and ingots carry no `uses` we recognise, so they fell
# through its "pure loot -> bank it" branch and the whole harvest went to the shop instead
# of the forge. Seeking MORE material would have been pointless while that door was open.
FORGE_FEEDSTOCK_PREFIXES = ("lumber", "ingot", "flux", "plank", "timber")
# v0.47.0 — 0.46 reserved lumber UNCONDITIONALLY and that was wrong within one run: a
# forge needs ingots AND lumber, we had no ore and no ingots, so the reserve stockpiled a
# shaft with nothing to put on the end of it while cutting real income (189 lumber sales
# on #113). Gold fell to 139, under the 150 WEAPON_BUY_FLOOR, so nothing could be armed
# either. Lumber is therefore reserved only when the character actually holds METAL --
# an ingot, or an ore pair that can still smelt into one. Ingots and flux stay reserved
# unconditionally: they are scarce, directly forgeable, and worth almost nothing sold.
FORGE_METAL_PREFIXES = ("ingot", "ore")
FORGE_SHAFT_PREFIXES = ("lumber", "plank", "timber")
# Bounded on purpose. An UNBOUNDED reserve is the v0.19.0 regression: an unsold-food pack
# pinned chars `full` forever and drove the embark<->return thrash that stopped gold ever
# accumulating. Keep a few per character, sell the surplus -- enough to forge with, never
# enough to clog a ~20-slot carry.
FORGE_RESERVE_PER_CHAR = 4

# --------------------------------------------------------------------------- #
# v0.52.0 FORGING — the last step of the M3a chain, deferred since docs/07 because the
# `product` name was unpublished and a blind guess storms `unknown_product`.
#
# It was never unpublished. It has been in our own event stream all along: 189 rival
# `forged`/`forge_started` events name it outright —
#   {"kind": "forge_started", "eid": 111263, "product": "shield_iron", "ticks": 14}
# Observed products, with shop prices for comparison: shield_iron 64 (NOT SOLD), dagger 47
# (20g), spear 25 (70g), sickle 19 (35g), hook_chain 11 (not sold), shortsword 10 (45g),
# pickaxe 6 (40g), pike 5 (not sold), bow 2 (85g).
#
# `shield_iron` leads the ladder deliberately: it is ARMOUR, the shop does not sell it at
# any price, and 100% of our characters have an empty offhand. It is the one product where
# forging is not a cheaper route but the ONLY route.
FORGE_PRODUCTS = ("shield_iron", "spear", "shortsword", "dagger")
# v0.95.0: the same products, weapon-first, for a character whose HAND is empty — arming
# the hand outranks armouring the offhand when a char can't fight. Same tuple contents so
# every recipe/proven/failed key still applies; only the try-order changes.
FORGE_WEAPON_FIRST = ("spear", "shortsword", "dagger", "shield_iron")
# v0.98.0: hand items that are TOOLS, not combat weapons — a char holding one still needs
# a real weapon forged (the #189 miner spammed shields because its pickaxe read as armed).
FORGE_HAND_TOOLS = frozenset({"pickaxe", "sickle", "hook_chain"})

# v0.99.0 ORE-HUNGRY FIELDING. Ingots are the arm-rate bottleneck (smelted only from
# mines ORE, 2 ore -> 1 ingot); on #190 nobody mined (1 char in the mines, 4 smelts) so
# the smith pipeline had ~0 ingots to forge. When the guild is ingot-poor, a GATHERER's
# embark destination is biased toward the ore world so ore->ingot production scales. The
# ore world is DERIVED from where we have seen vein tiles (not hardcoded), and the bias
# stays inside the green-gate — a bare forager only goes to a CALM ore world; fodder (the
# designed risk-taker) is exempt as always. Lumber is plentiful (surface), so we bias only
# when actually short on ingots; as they accrue the bias releases (self-correcting).
INGOT_HUNGRY = 3           # guild ingots (stash) at/below this = bias gatherers to ore
# Recipe quantities are NOT documented. Rather than guess once and give up, try a small
# ordered ladder of (ingots, lumber) and let the server's rejection teach us — an
# action_error here is INFORMATION, the same stance the exploration matrix takes. Cheapest
# combinations first so a failure costs the least stamina.
FORGE_RECIPES = ((1, 1), (2, 1), (1, 2), (2, 2), (3, 1))
FORGE_STAMINA = 15
# v0.64.0: refusals needed before a never-proven recipe is abandoned. More than one,
# because `wrong_materials` is not deterministic in what we key on (see _forge_proven);
# still small, because an unlimited retry is the storm every latch in this file exists to
# stop.
FORGE_FAIL_LIMIT = 3          # docs/07: brew/forge cost 15, paid once up front
# Medicinal drinks we keep rather than sell (potions, vials, elixirs, tonics). Raw
# FOOD is also `uses:['drink']` but is NOT kept — the guild never eats it, so
# hoarding it just fills the pack and strands chars homing (v0.19.0: the stuck-gold
# / embark-thrash root cause). Food is sold as loot (the shop buys it).
DRINK_KEEP_PREFIXES = ("potion", "vial", "elixir", "tonic")
CONTAINERS = frozenset({"chest", "safe"})
DEFAULT_MAPS = ("vale", "mines", "spire")
REST_SCORE = 0.5           # the floor: rest wins only when nothing affordable beats it
# The two idle FILLERS, named in v0.75.0. Both were bare literals referenced by number in
# five comments, and the say had to be placed relative to them — a placement argued against
# a magic number is an argument nobody can check.
SCOUT_SCORE = 1.0          # "no goal reachable — stepping to scout": the real floor, since
                           # it is offered on essentially every idle tick
FRONTIER_NORTH_SCORE = 2.5 # pushing north into unexplored ground
# v0.77.0 — FRONTIER TREK. Measured on #158 (58k frames, mature) after heal-first shipped:
# potion buys 0 -> 17, but median fielded y stayed at 3 and looted-out stayed at 29% — the
# stated falsification's "not the only pin" branch fired. The actual pin: since 0.70.0
# removed the 572 false frontiers, the nearest TRUE frontier is 192 tiles from the vale
# spawn strip (86 mines, 64 spire) — all far beyond FIELD_GOAL_RANGE=20, so the frontier
# offers can never fire from where the roster lives, nothing pulls north, and "looted-out
# -> home" (1.5) wins by default. The heal opened the door (POISON_SAFE_DEPTH) and this is
# the legs: an UNBOUNDED walk toward the nearest true frontier, exactly symmetric with
# `_retreat`, which is already deliberately unbounded for the same map in the other
# direction. Gated on carrying a heal, because a bare character bounces off the poison
# gate at y=12 and the trek would walk it into a forced U-turn.
TREK_SCORE = 2.2           # above looted-out(1.5)/say(2.1), below the bounded local
                           # frontier pushes — but it only fires when those found nothing
FRONTIER_SCORE = 2.0       # heading to the nearest frontier
# v0.75.0 — flavour text (`say`). 0.74.x issued it from the VILLAGE and the server refused
# all three attempts with `not_in_village`; docs/03-actions.md gives its scope as "map",
# which I had read as "map-visible" rather than as WHERE IT IS LEGAL. The scope column had
# the answer before the first line of chatter.py was written.
#
# WHERE IT SITS, after getting this wrong twice in one session. The first attempt scored it
# at 0.6, just above REST, reasoning that a rest is the cheapest thing it could displace. It
# fired zero times: rest is almost never the alternative, because "no goal reachable —
# stepping to scout" (1.0) is offered on nearly every idle tick. Moving it to 1.1 fired zero
# times too — the looted-out walk home (1.5) and the frontier pushes (2.0/2.5) are also
# always there. "Score it below everything so it cannot cost anything" keeps producing a
# behaviour that cannot happen, which is the same defect as v0.48.0's cohesion and this
# session's rally, arrived at from a different direction each time.
#
# The cost is small enough to state plainly instead of engineering around: ONE action, for
# one character, once per 300 ticks, guild-wide — with ~7 fielded that is under 0.1% of the
# actions we issue. So it is scored above the idle FILLERS it displaces (scout 1.0, the
# looted-out walk home 1.5, the nearest-frontier step 2.0) and below everything that is
# ever load-bearing: the north push (2.5), every retreat (2.5 and up), predator spacing
# (3.0), gathering (4.0+), the dodge and the desperation escape.
#
# The `rested` gate below is the other half: a character with full hp and stamina is one
# that would have wandered, not one that would have recovered or run.
RIDE_PROBE_SCORE = 4.5     # v0.93.0: above routine gathering (4.0+) so the once-per-run
                           # probe actually fires on a healthy calm tick; never urgent
RIDE_PROBE_HP_FRAC = 0.7
RIDE_PROBE_MIN_STA = 15
RIDE_SEEK_SCORE = 3.1      # v0.93.1: a qualified prober WALKS to a known rail — below
                           # harvest(3.3)/gather so real income wins, above frontier(2.5)
RIDE_SEEK_RANGE = 24       # bounded: a detour to a nearby rail, not an expedition
SAY_SCORE = 2.1
SAY_READY_FRAC = 0.9       # ...and only from a character with nothing to gain by resting.
# The first draft claimed "it can only displace an idle rest tick" and that was FALSE:
# rest is also the RECOVERY action, and it wins exactly when a character is too tired to
# do anything else. Three decision-engine tests caught it — a character with no affordable
# action was talking instead of recovering. A rest is only idle when hp and stamina are
# already topped up, so that is the gate. `max_stamina` is absent -> treated as NOT ready,
# because the conservative reading of missing data is the one that cannot cost a recovery.
POTION_KEEP = 1            # potions to carry into the field per character
VAULT_DEAD_LIMIT = 8       # phantom vault ids tolerated before withdrawals stop for the run
# v0.82.0 — PLAYER-MARKET PROBE. The market is EMPTY: guild.market_listings has been []
# in every frame ever recorded — no guild on this server, the dev's included, has ever
# listed an item — while the shop pays 20% of list and the docs say in as many words
# "sell to players when you can; only use the shop's buyback as a last resort". One
# listing per run probes whether ANY rival bot buys: a surplus lumber, at triple its ~1g
# shop-sell. Cost of a never-sold probe: the foregone ~1g, reclaimed by unlist at the
# NEXT run's start. Every listing/sale event shape is unobserved; the parser pattern is
# taste's — tolerant fields, loud raw print, fail closed on rejection.
# PREMISE(2026-08-22, the player market is unused and lumber shop-sells at ~1g):
#   market_listings in any village frame; sale events item=lumber gold<=1
MARKET_PROBE_KIND = "lumber"
MARKET_PROBE_PRICE = 3
# v0.83.0 — THE CASTER PIPELINE. Magic is the one mechanic nobody on the server has
# touched, and its unblock chain is: tome (shop 120g; loot has gone dry — zero tome
# events in two runs) -> INT (the `use` is refused `stat_requirement`; threshold unknown
# but discoverable free, since a refusal costs nothing and _tome_to_learn already retries
# after stat growth) -> the `learned` event -> casting, whose essence ammunition the
# taste engine has already stocked (9 kinds, 6 essences).
#
# Two gaps this closes: (1) nobody banked INT until a tome was ALREADY refused in their
# pack, so the tome and the INT grind ran sequentially when the int-GIFTED character
# (half-cost INT) could pre-bank in parallel; (2) nothing ever bought a tome.
# PREMISE(2026-08-23, tome INT threshold unknown; 6 is a guess spanning docs/06's
#   spell_cap breakpoints): first successful `use` reveals it — re-derive then.
CASTER_INT_TARGET = 6      # pre-bank INT up to this on int-gifted characters
TOME_BUY_KIND = "tome_veil"   # the cheap form (120g); bolt (150g) can wait
TOME_BUY_MIN_INT = 4       # ...and only once the designate's INT grind is nearly done
# v0.85.0 — THE ESCORT (operator: "can you make guardians protect wizards? And wizards
# without guardians fall back to the village until they venture out with a guardian?").
# Guardians shadow a co-fielded wizard; a wizard with no guardian within ESCORT_NEAR
# walks home; the village embarks a wizard only INTO a world where a guardian is already
# fielded. Known cost, accepted by the operator: no fielded guardian anywhere -> wizards
# wait in the village and the INT grind pauses.
ESCORT_SCORE = 4.2         # above gathering (4.0): escort duty wins over one more coin;
                           # below every survival behaviour, so a hurt guardian still runs
ESCORT_PULL = 4            # guardian closes when the wizard is farther than this...
ESCORT_HOLD = 2            # ...and holds inside this (hysteresis like cohesion's)
ESCORT_NEAR = 10           # a wizard with no guardian inside this radius has no escort
# v0.86.0 — THE PARTY IS THE UNIT (operator: "the _party_ needs to have a target square...
# guardian should go 'do I have a wizard with me? go find a wizard, okay now I'm in a
# party with the wizard'"). 0.85.0 was individualized: each character computed its own
# target from the others' positions, and because every such computation EXCLUDES SELF,
# each member had a DIFFERENT rally point — mutual pursuit, i.e. the jitter the operator
# watched. Now: a wizard and a guardian PAIR into a persistent party (self._party); the
# party's anchor square is the WIZARD'S TILE — one fixed point per tick, identical for
# every member — the guardian holds formation on it, the wizard chases nobody, and
# partied characters are excluded from cohesion (the party IS their formation).
ESCORT_MAX_GAP = 20        # v0.85.1: a guardian escorts only inside this. The first live
                           # trace read "escorting the wizard (130 away)" — an unbounded
                           # escort is a cross-map errand (stints are 10-12 ticks; the
                           # trap this session already paid for twice). Beyond this gap,
                           # RE-PAIRING is the village's job: the wizard falls back
                           # (ESCORT_NEAR) and the embark gate fields it back alongside
                           # a guardian.
WIZARD_FALLBACK_SCORE = 6.0  # above all income (<=5.0), below hurt-retreat (8.5)/dodge
# v0.102.0 WIZARD RECALL HYSTERESIS. A wizard only KNOWS a world is dangerous while it
# stands in it; back home that knowledge expires (THREAT_TTL), so the embark check reads
# the world "safe" and re-dispatches it into the same bad band it just fled — the arch-
# wizard oscillated home 222x on #194. After a band-danger fallback, hold the wizard home
# for this long so the band actually cycles before it can re-embark (band windows are
# ~120-240 ticks; band_refresh_deferred payloads carry in_ticks 120).
WIZARD_RECALL_COOLDOWN = 200

# v0.58.0 BOTTLES. The heal supply had a hole in it that nothing was watching.
#
# v0.35.0 raised POTION_RESERVE 100 -> 600 on good evidence: heals were 99.6% FREE-BREWED
# (4,511 drinks against 16 buys), and the potion-buy was pinning gold at ~100. Correct --
# GIVEN that brewing keeps supplying heals. Nothing guaranteed that it would. Brewing needs
# a `bottle_empty`, and there has never been a path to ACQUIRE one: the kind appears in
# exactly two places, KEEP (never sell it) and the brew gate (count them). We could only
# ever find bottles as loot.
#
# The bottles ran out, and the premise failed silently. Measured on run #134, 31,011 frames:
# 0 brews, 0 potion_red carried by ANY character, and the buy fallback frozen because
# `gold - 20 >= 600` cannot pass at 183 gold. The consequences run all the way down the
# chain this project has spent three passes on -- an un-healed char is capped at
# POISON_SAFE_DEPTH=12 (v0.23.0), the shallowest vein is at y=26, our characters sat at a
# MEDIAN DEPTH OF 2, and so v0.54.0's vein-seek walked toward ore it could never reach:
# 751 seek decisions, 0 char-frames ever adjacent to a vein, 0 veins broken.
#
# A bottle costs 2 gold. This is the cheapest unlock in the entire chain, and it restores
# the free-brew pipeline the 600 reserve was explicitly premised on rather than arguing
# with that reserve.
BOTTLE_KEEP = 1            # empty bottles to carry per character (one brew's worth)

# v0.59.0 SCARCE CHAIN INPUTS. The stranded-singleton rule (v0.8.0/v0.10.0) sells a lone
# brewable or a lone ore because it cannot form a batch or a pair, and that rule is right
# for ABUNDANT things: an unsold-food pack once pinned characters `full` forever.
#
# It is wrong for the two inputs we are actually bottlenecked on, and run #135 caught both
# going over the counter: 2 `bone` (a VIGOR herb -- the potion_red that lifts
# POISON_SAFE_DEPTH, the cap this project spent iter 70 tracing) and 5 `ore_copper` (raw
# forge feedstock; note FORGE_FEEDSTOCK_PREFIXES covers `ingot` but NOT `ore`, so unpaired
# ore falls to the smelt branch and is banked).
#
# A singleton of a scarce input is not clutter, it is HALF A PAIR. Selling it guarantees it
# stays half a pair forever, which is the same self-defeating leak v0.46.0 fixed for lumber
# and ingots. Bounded exactly as that fix was: at most SCARCE_LONE_KEEP per KIND per
# character, so this can never grow into the carry-clog the original rule exists to prevent.
SCARCE_LONE_KEEP = 2

# v0.63.0 TOMES. Magic has been "blocked" on this list for fifty passes, and the block was
# never cost. A tome teaches a spell FORM by being `use`d (docs/06), and we have SOLD 74 of
# them -- tome_ring x22, tome_step x16, tome_field x14, tome_veil x13, tome_bolt x9, most
# recently on runs #130/#135/#137 -- for 36-44 gold apiece, against a shop price of 120-150.
# We have never once cast a spell, and `learned` events in our whole history number ZERO.
#
# The mechanism is the same leak as `bone` and raw `ore`: a tome carries `use`, not `equip`,
# so `_should_sell` files it under "pure loot -> bank it". Buying one is out of reach (150g
# against a 150g arm floor, so it would strand a bare character), but we do not need to buy
# what keeps falling into our hands.
TOME_PREFIX = "tome"
# v0.29.0: heal from SURPLUS. The 0.24.0 hoard froze the potion-buy to stockpile;
# 0.28.0 froze the last spend (clubs) and the treasury finally climbed (run #84
# gold mean 5.7 -> 68, median 2 -> 92, climbing past 155 with ZERO drops). But the
# freeze left every fielded char 100% bare AND heal-less, and a poison-heavy band
# cycle (undead 1.6% -> 9.3%) spiked deaths 10x to 2.23/1k. The deaths are NOT
# combat: 21/22 had no undead adjacent — chars get poisoned deep, flee, and BLEED
# OUT from the DoT mid-retreat (traced: hp 18->12->6->3 with a potion-less pack).
# So now that a stockpile EXISTS, spend its SURPLUS on the one thing that outruns
# poison's tick: buy a heal-less char a potion, but ONLY while gold stays above
# POTION_RESERVE. This keeps a growing hoard floor (never spends below the reserve)
# yet keeps earners alive -> more looting -> the hoard grows FASTER. Bounded, unlike
# the old club drain: at most POTION_KEEP potion per char, and gated on the reserve.
# v0.35.0: raised 100 -> 600 to UNCAP the stockpile. Run #90 gold-flow proved the
# potion-buy was pinning gold at ~100: all 16 gold drops were -20 potion buys (318g)
# and consumed essentially all the +311g income -> gold flat at the reserve floor. But
# heals are 99.6% FREE-BREWED (4511 drinks vs 16 buys), and 0.29's heal-from-surplus
# was premised on POISON deaths — a diagnosis iter20 REFUTED (the killers are melee
# predators, which a potion can't out-heal). So the bought potions barely help survival
# and only cap the hoard. A 600 reserve lets gold climb PAST the 529 cap-test (answering
# the operator's open "is there a gold cap?" question) while still topping up heals once
# the guild is genuinely rich. Brewing covers heals meanwhile. (KPI alarm watches deaths.)
# v0.69.0: 600 -> the arm floor. v0.35.0 raised this to 600 on a premise that has since
# expired: "heals are 99.6% FREE-BREWED (4,511 drinks vs 16 buys)". That was true then and is
# not true now. Across runs #141/#143/#145/#147 -- roughly 180,000 frames -- we brewed SEVEN
# `potion_red` in total, and only 4.1% of character-frames carry one. Brewing is no longer the
# supply it was: it needs a bottle AND two vigor ingredients in one pack at once, and only
# 0.34% of village character-frames can assemble that.
#
# Meanwhile the reserve made the fallback unreachable by arithmetic: gold runs 156-200, a
# potion_red costs 20, and 600 + 20 = 620 is a threshold we have never approached.
#
# So the heal now ranks WITH arming rather than behind a hoard we do not have. Written as the
# weapon floor rather than a fresh number, because that is the claim: a character with no heal
# is capped at POISON_SAFE_DEPTH, which gates ore, the deeper content that carries the XP, and
# every vein we have failed to reach. It is bounded by POTION_KEEP=1 per character and by the
# floor itself, so it cannot become the 0.24.0-era drain that pinned gold at ~100.
# NB the literal, not `WEAPON_BUY_FLOOR`, only because that constant is defined further down
# this file; a test pins the two equal so the intent cannot drift apart from the number.
# PREMISE(2026-08-22, brewing does NOT supply our heals so the shop must): count our
#   `brewed` potion_red across the last ~180k frames; expect < 20. If brewing recovers,
#   this reserve should rise again — v0.35.0 was right for the world it measured.
# v0.76.0 — MEASURED ON RUN #157, and it is the largest single finding of the project so
# far. A heal is not a safety item, it is the PASSPORT NORTH:
#
#     fielded char-frames carrying a heal:      0.5%   median y ~50, ranging past y=70
#     fielded char-frames carrying none:       99.5%   median y   0, 79% at y 0-9
#
# `POISON_SAFE_DEPTH` pulls an un-healed character home from y>=12, exactly as designed —
# so with almost nobody healed, the whole roster is pinned to the bottom 12 rows of a
# 199-row map. That is why 31% of #157's decisions were "world looted-out — home to
# re-embark" (the spawn strip really is stripped), why 30% of field visits lasted <=5
# ticks, and why XP is flat: the content worth XP is north of a line we cannot cross.
#
# v0.69.0 set this EQUAL to WEAPON_BUY_FLOOR, reasoning that a heal ranks WITH arming.
# The arithmetic made that strictly worse than it sounds: the weapon fires at gold > 150
# while `_afford_potion` needs gold - 20 >= 150, i.e. 170 — so the heal is HARDER to
# afford than the weapon, and is checked after it. With a bare bench there is always
# someone to arm, so the surplus is spent at 151 every time and 170 is never reached.
# Run #157: 0 potions bought, 0 brewed, gold sitting at 149.
#
# So the heal now sits BELOW the arm floor and is checked FIRST. It buys map access; a
# weapon buys marginal damage in content we are not allowed to walk to. Bounded by
# POTION_KEEP=1 per character, so this is a one-off redirection that stops of its own
# accord once the roster is healed, not a standing drain.
# PREMISE(2026-08-22, an un-healed character cannot leave the spawn strip): compare the
#   y-distribution of fielded char-frames with and without a potion_red -- see decisions.log
HEAL_DEPTH_BONUS = 16      # v0.107.0: extra rows of allowed depth per CARRIED potion_red
                           # (a potion is single-use retreat margin — the range it buys
                           # must be coverable by one potion; y<28 with one still reaches
                           # the observed veins at 26-27, while the arch-wizard's fatal
                           # y=31 is barred). Wizards get NO bonus (protected, shallow).
DEAD_CAPITAL_KEEP = 1      # v0.109.0: what a dead-capital weapon buy leaves behind —
                           # a token float; the point is converting unusable coins into
                           # a fighter, not zeroing the ledger.
POTION_MIN_BUFFER = 10     # v0.106.0: what a POTION (or bottle) buy must leave behind —
                           # a minimal operating float, NOT the full POTION_RESERVE.
                           # The reserve protects heal-spending from weapons/armor; it
                           # must never veto the heal itself (that inversion held every
                           # potion buy hostage at gold 33-42 across #197-199 while the
                           # un-healed roster was depth-capped into the revolving door).
POTION_RESERVE = 30        # v0.100.0: RECALIBRATED for the coin-dry reality. The old
                           # 100/150/200 floors were set when we sat at ~600 gold; the
                           # guild is now chronically at ~85, BELOW ALL THREE, so it
                           # bought nothing — no weapons, barely any potions — and we
                           # built the whole ore->forge chain to route around a frozen
                           # reserve while clubs sat unbought in the shop. A hoard that
                           # blocks its own use is worthless; gold is a FLOOR not the
                           # goal (operator). Ordering preserved: potion < weapon <
                           # armour. never let the potion-buy pull the treasury below this
POTION_MIN_GOLD = 20       # buy a potion once we can afford one (its shop price is
#   20g; v0.17.0 dropped the old arbitrary 25g buffer — a poison death loses the
#   char's gear+loot, far more than 20g, so a heal is worth buying at cost).
#   (v0.17.0 also added a WEAPON_BUY_RESERVE that gated arming bare chars behind a
#   one-potion reserve; it REGRESSED income/engagement and is removed in v0.18.0 —
#   arm a bare char whenever affordable, as before.)
XP_PRIORITY = ("vit", "end", "str")   # survival first: HP, then stamina, then damage
# v0.67.0: INT is deliberately ABSENT from the list above, and that quietly locked magic out
# of the game for us. INT gates which tomes a character may use (docs/06), `max_mana`,
# `spell_cap` AND `essence_cap` — so with INT stuck at its starting 1-2 there is no route to
# a spell at all, however many tomes we keep.
#
# Run #145 finally showed the whole chain: two tomes DROPPED, we picked them up and kept them
# (0.63.0 — zero sold, against 74 sold historically), we issued `use` on exactly those
# item_ids, and the server answered `stat_requirement` five times. Every link works except
# the stat.
#
# Raised for the character that DEMONSTRABLY needs it rather than by reordering the survival
# priority for everyone: a character holding a tome it has been refused. That refusal is
# already recorded, the retry on growth is already built (v0.65.1), so this closes the loop
# with no new machinery and no cost to any character that is not carrying a tome.
XP_PRIORITY_CASTER = ("int",) + XP_PRIORITY
XP_STAT_TARGET = 8         # grow each toward the full-rate effective-bonus cap
EQUIP_SLOTS = ("hand", "offhand", "outfit", "trinket", "boots")
# v0.53.0: how many distinct (kind, slot) swap refusals before we conclude the server has
# no equip-into-occupied-slot mechanic at all and stop attempting upgrades for the run.
SWAP_GIVE_UP = 3
BREW_MIN = 2               # a brew takes 2-4 ingredients
BREW_MAX = 4
BREW_MIN_GOLD = 10         # keep a little gold buffer before buying bottles
# Hand-weapon kinds the shop sells (observed; the offhand shield, tool pickaxe/
# sickle, and consumables are excluded). Used to buy the cheapest affordable one
# to arm a bare-handed char — v0.13.0's poverty-bootstrap unlock.
WEAPON_KINDS = frozenset({"club", "dagger", "shortsword", "spear", "bow"})
# v0.47.0 ARMOR. Every character has five slots (EQUIP_SLOTS) and in 114 runs we bought
# for exactly one of them: the buy was gated on WEAPON_KINDS and on `hand` being empty, so
# we have NEVER bought a shield, trinket or boots -- 0% of our characters wear armor while
# rival g_63837f fields ~60% spear+smith_apron. `shield_wood` is 25g with NO stat
# requirement and every one of our characters has an empty offhand. The gap was
# self-inflicted. Kinds are checked against the LIVE shop stock, never assumed present.
ARMOR_KINDS = frozenset({"shield_wood", "shield_iron", "striders", "fickle_pearl",
                         "smith_apron"})
# Armor is bought only above this, ABOVE the weapon floor: a weapon is what makes a
# character able to fight at all, so it must never lose a coin race to a shield.
ARMOR_BUY_FLOOR = 70       # v0.100.0: recalibrated (armour is the luxury tier)

# v0.28.0 PURE HOARD: freeze the weapon-buy entirely. Measurement of run #83
# (0.27.0) proved the club-buy is the SOLE remaining drain on the treasury —
# every gold DROP was exactly -15 at a `buy`, 26 clubs = 390g/run, spent the
# instant gold cleared 15 — so gold peaked ~155 then bled straight back to ~2
# (recent mean 5.7, median 2) and NEVER stockpiled. And the clubs are near-dead
# weight now: since safe-world routing + undead-flee (0.25/0.26) chars AVOID
# combat (attacks fell to ~21/1k) — they flee undead and loot wildlife, and
# ~28 of 42 recruits/run churn out before ever fighting, each having been armed
# with a club they never swing. Field COINS bank instantly and CHESTS give
# direct gold+loot regardless of a weapon; only ~3% of gold is kill-tied. So
# freezing the buy makes net income ~+607g/run and lets gold finally accumulate.
# Tradeoff (named, not hidden): a truly COLLAPSED guild (0 armed chars, needing
# to fight its way out of a poverty trap — the v0.13.0 bootstrap case) can no
# longer auto-arm. That case isn't live (12 chars, fielding 10, income healthy),
# and the operator's governing directive is "extraordinarily drastic" hoarding;
# flip this back to False to restore arming if the guild ever re-collapses.
# v0.40.0 DIRECTION CHANGE (operator): master the game + LEVEL chars while the progression
# window is open; gold is now a FLOOR, not the objective. The rival scan showed the hoard's
# cost (us level 3-5 with ZERO gear vs WillMorr's level 29, armed). So the weapon-buy is
# UNFROZEN and re-gated on a gold floor: arm a bare char whenever the treasury is above
# WEAPON_BUY_FLOOR (~15g/club; we sit at ~600). Gear is the prerequisite for combat/XP; the
# combat-SEEK that earns the XP is the next lever (0.41). spend_xp already converts XP live.
WEAPON_BUY_FLOOR = 45      # v0.100.0: recalibrated — arm a bare char down to this

# v0.41.0 COMBAT-SEEK (the leveling lever): now that chars ARM (0.40), a DEVELOP-mode char
# EARNS XP by fighting beatable mobs instead of always fleeing them — reversing the 0.24
# no-chase. DEVELOP-mode = armed + comfortably healthy + stamina to sustain a fight; below
# any of these a char reverts to the survival behaviour (flee/dodge/harvest) untouched. Two
# safe engagements: (A) fight a LONE melee predator that comes ADJACENT (override the dodge —
# the char was going to be adjacent anyway; armed+healthy it trades hits and wins, and
# hurt-retreat still bails it out below 60% HP), and (B) actively SEEK benign wildlife (0-dmg
# mobs) to farm free XP. NEVER fought: undead (DoT — flee wins above) or a SWARM (>=2 melee
# predators within reach — too much incoming). Predators are not actively walked into (their
# strike-range tiles stay blocked); we only fight the lone ones that reach us. Gold-floor is
# enforced INDIRECTLY: develop-mode requires a weapon, and the weapon-buy is itself gated on
# WEAPON_BUY_FLOOR, so a poor guild can't arm -> its chars aren't in develop-mode -> they
# harvest/survive. No per-tick treasury read needed in the field.
DEVELOP_HP = 0.7          # predator ENGAGEMENT keeps its comfort margin: a fight you
                           # might not finish before the 0.6 retreat line is a fight
                           # you dodge (the pre-lever pin, deliberately preserved)
HUNT_HP = 0.6             # v0.111.1: WILDLIFE hunting runs AT the retreat line — a
                           # chicken cannot hit back, so the margin a wolf demands is
                           # pure hesitancy against prey; split from DEVELOP_HP when
                           # the old dodge-not-fight pin caught the single gate
                           # loosening PREDATOR fights the evidence never justified
DEVELOP_STAMINA = 15      # enough stamina to attack AND still afford a step to disengage
DEVELOP_HP_FODDER = 0.4   # v0.87.0: fodder keeps swinging far below the 0.7 line
COMBAT_SEEK_RADIUS = 5    # gauge predator density within this many tiles (swarm gate)
WILDLIFE_SEEK_RADIUS = 15 # v0.112.0: raised 8 -> 15 on the live window capture
                          # (run #219, 11:00): a chicken at (29,8) — shallow, VISIBLE,
                          # in every budget — parked 11 tiles from the nearest armed
                          # char while the window expired unhunted. Live strips are
                          # looted, chars sit parked, and nothing walked toward
                          # visible prey beyond the old 8. Vision bounds the chase
                          # naturally; deep_ok still gates depth; wildlife-only.
                          # (v0.111.1 history: raised 5 -> 8 on frog sightings —
                          # live sightings put frogs at 6-8 tiles off the strip (4 at
                          # range vs 0 in the old radius 5); the calibrated soak: xp 9
                          # pre -> 12 post over 1200 ticks (+33%, kills 3 -> 4, zero
                          # deaths). Modest because FIELDED COUNT is the next binder —
                          # the hunting-release slice. Chasing stays wildlife-only;
                          # the swarm gate keeps its tighter radius 5.
COMBAT_SWARM = 2          # >=2 melee predators within reach -> too dangerous to fight, flee

# --- v0.114.0 PROPOSAL B (operator: "go for proposal B, but protect my wizards"):
# beatable-predator ENGAGEMENT. v0.114.1 re-priced the list by TIME-TO-KILL, not dph:
# the first live engagement (run 222, c19750 vs lava_ant) proved the dph-only pricing
# wrong — our swings land every OTHER tick (attack costs 20 stamina), the mob bites every
# tick, so a 4-swing mob out-trades us even at dph 3.4. Damage-sunk telemetry across 8
# runs: wolf <=15hp (2 swings) and crab_green <=15hp (2 swings) are winnable; lava_ant
# 21-27hp (4 swings, plus a BURN DoT that rightly triggers the early retreat) and
# spider_brown ~18hp (3 swings; also #180's recruit-killer) are NOT. Still excluded from
# ever entering: boar (6.0 dph, 26+hp), delver, golem_stone (the -15 hitter), every
# undead kind (doctrine), and anything without BOTH a measured dph and a measured hp.
ENGAGE_KINDS = frozenset({"wolf", "crab_green"})
ENGAGE_SEEK_RADIUS = 10   # close on a lone allowlisted predator this far out. Wider than
                          # the spacing bubble (2), narrower than wildlife (15): a predator
                          # trek costs hp on arrival, so we only cross ground we can see.

# v0.44.0 FORGE-TO-ARM probe (slice 1): breakable terrain we HARVEST for raw materials by
# attacking the tile (docs/08: "trees/bushes/fences break after a few attacks; vein drops ore").
# We treated all of these as impassable scenery (nav.SOLID) and never touched them — the entire
# raw-materials layer went unmined. Start with the two forge inputs: trees -> lumber, veins ->
# ore (-> smelt -> ingot). Kept deliberately narrow (not bush/rock/fence) until the mechanic and
# the drops are measured, then expand. These are still SOLID for pathing — we only ATTACK them
# from an adjacent tile, never stand on them.
HARVEST_KINDS = frozenset({"tree", "vein"})

# v0.54.0 FORGE-TO-ARM slice 2: SEEK ore. Run #130 measured the M3a bottleneck precisely and
# it is not what "harvest more" would suggest -- 120 trees destroyed against 5 veins, and
# lumber piling up while ore trickles. The cause is not scarcity: the accumulated map knows
# 83 vein tiles in the mines, and HALF our character-frames are already IN the mines. It is
# DENSITY. Slice 1 harvests only what a character is already ADJACENT to, and vale's 357
# trees are thick enough to brush past constantly while 83 veins among ~4,900 mine floor
# tiles are not. So a character that wants ore must now WALK to one.
#
# Deliberately narrow, because the 0.46.0 regression was exactly this shape -- a change made
# "for the forge" that quietly cost us our income:
#   * ORE ONLY. Trees are not sought; slice 1 already gets more lumber than we can use.
#   * Only when the character can USE more metal (under the per-char forge reserve) and has
#     carry room, so it is never a march for cargo we would drop or sell.
#   * Bounded by VEIN_SEEK_RANGE, so it is a detour and not an expedition.
ORE_KINDS = frozenset({"vein"})
VEIN_SEEK_RANGE = 14
# v0.71.0: a character CARRYING A HEAL may go much further for ore, and the numbers say it
# must. Veins in the mines sit at median depth 88 and the shallowest at 24; the median
# distance from one of our characters to the nearest vein is 30, and only 4.72% of mines
# character-frames are within 14. So the ore errand was sized to never reach the ore, and
# runs #148/#149 broke 4 and 3 veins against 44 and 193 trees.
#
# Gated on the heal rather than granted to everyone, because the two facts are the same
# fact: veins are DEEP, depth is where poison kills, and POISON_SAFE_DEPTH exists for
# exactly that. The character that can safely make the trip is the one carrying the answer
# to what makes it dangerous — and since v0.69.0 that is 27% of them rather than 4%.
#
# The move-failure budget says this is affordable: 0.24-0.33% of moves currently fail,
# against a 5.2% historical baseline and the 19.4% of the v0.55.0 regression. Long errands
# were dangerous when they were UNBOUNDED over a freshly-hydrated map (v0.57.0); this is a
# bound, raised deliberately, for one purpose, with the headroom measured first.
VEIN_SEEK_RANGE_HEALED = 32
# Scored ABOVE frontier(2.5) -- walking toward a known resource beats walking at random --
# but BELOW cohesion(2.8), so a character in a world dangerous enough to form up does not
# wander off alone to mine, and well below adjacent harvest(3.3) and any real gathering.
VEIN_SEEK_SCORE = 2.7

# v0.57.0: how far a field errand may travel. Every goal search in the field used to be
# UNBOUNDED, which was harmless only because the map was small: before v0.55.0 a character
# knew a few hundred tiles around itself, so "the nearest chest" was necessarily nearby and
# usually had no known corridor leading to it anyway.
#
# Hydrating the map removed that accidental limit and the bot fell over. Run #132: move
# failures 5.2% -> 19.4% of moves, and chest-beelining went from 0.047 to 0.70 decisions
# PER FRAME — a fifteenfold rise — as every chest ever seen became reachable from anywhere.
# v0.56.0 scoped WHICH chests count (contents are not durable) and recovered only 19.4% ->
# 16.5%, because the remaining ones were still reachable from across the world.
#
# A long errand is not merely slow, it is failure-prone: it is planned over remembered
# terrain where the DYNAMIC obstacles — rivals, monsters, our own characters — cannot be
# seen, and re-planned every tick from a frame that may already be stale. The map should
# tell a character where the ground is, not send it on a pilgrimage.
FIELD_GOAL_RANGE = 20


# PREMISE(2026-08-22, frame staleness still makes a bare-cost move fail): shown-stamina at
#   `not_enough_stamina` move failures; expect a max near 30 for a cost-20 move. Re-measured
#   2026-08-22 (max 29-30, median 26-28) and deliberately LEFT UNCHANGED — see the negative
#   result in decisions.log iter 83 before re-litigating this.
MOVE_STAMINA_SAFETY = 1.5   # v0.9.0: require this ×raw move cost of stamina before
#   stepping — headroom so a ~1-tick-stale frame reading still affords the move on
#   the server (moves failed not_enough_stamina at shown-sta up to ~29 for a cost-20
#   move; the gap is staleness, not terrain). Rest/regen instead of a doomed step.

# v0.106.0: RETURNED_EMPTY_COOLDOWN (a fixed 150-tick nap) is GONE. #199 measured it
# merely pacing the commute (419 embarks/2797 ticks; chars rotating through worlds that
# were all still empty for them). The re-embark condition is now CAUSAL: a looted-out
# returner goes back only into a world that has replenished since its stamp (observed
# band refresh, or past the last-known refresh ETA) — or the moment it holds a heal,
# which moots the stamp entirely. See _replenished_since and the village embark gate.
SCOUT_RESEND_TICKS = 40    # v0.106.1: after releasing a scout toward an empty world,
                           # wait this long before releasing another to the same world —
                           # chars_by_world lags an embark by a few frames (the 0.43.0
                           # lagging-count lesson), and one sensor per world is the point.
VAULT_ARM_KINDS = frozenset({"club"})   # v0.108.0: vault weapon kinds worth a free arm
VAULT_ARM_PROBES = 4       # v0.108.1: the ARM branch's own storm budget, counting
                           # FAILED probes only (successful withdrawals never latch — 14
                           # real clubs should arm 14 chars). #204 proved the shared
                           # latch a design flaw within minutes: heal-first runs earlier,
                           # burned all 8 probes on potion phantoms, and the clubs were
                           # never tried at all. Separate budgets — a potion storm must
                           # not starve the club probe (and vice versa).
GHOST_REASONS = frozenset({"not_in_village", "unknown_character", "no_such_character"})
GHOST_TTL = 600            # v0.107.1: how long a server-refused ("ghost") char is barred
                           # from village candidacy. Long on purpose — a real char
                           # mistakenly ghosted returns in ~10 min, while a phantom that
                           # re-errors re-arms the clock and never wastes another command.
EMBARK_ISSUED_TTL = 30     # v0.107.0: how long an issued embark blocks re-issuing for
                           # that char, ROSTER-INDEPENDENT (chars_here flaps stale for
                           # frames after a departure; presence-based dropping caused the
                           # not_in_village re-command storm — 3,347 errors on #197).
#   that char's embark for this many ticks. The village frame we decide on is a few
#   ticks stale, so a just-embarked char still shows in `chars_here` — without the
#   guard the bot re-embarks it every tick and the tail bounces no_such_character
#   once it finally leaves. Observed embark latency ~3 ticks; 8 is safe headroom and
#   still retries a genuinely-failed embark after ~2 s.
RECRUIT_MIN_INTERVAL = 2000  # v0.113.0 (the gold-leak fix, operator-ordered): run #220
                             # burned 39 recruits x 15g clubs = ~585g — THE ENTIRE
                             # RUN'S INCOME — because the roster count reads a chronic
                             # 29<30 (one char invisible to every counter: ~37 silent
                             # disappearances per run, the vanish-bug class, filed).
                             # A chronic 1-2 shortfall now refills at ~8/run instead of
                             # 39; four tomes' worth of gold stays in the treasury.
RECRUIT_CHRONIC_MAX = 3      # a shortfall this small is the vanish drip (or ordinary
RECRUIT_TARGET_FIELDABLE = 18  # v0.115.0: recruit toward FIELD DEMAND, not capacity.
                               # Run 223 exposed the 0.113.0 throttle as an oscillator:
                               # silent vanishes (~1.1/1k) outpace the 2000-tick drip, so
                               # the shortfall crosses RECRUIT_CHRONIC_MAX, the "wipe"
                               # fast path bursts the roster back, and steady-state spend
                               # returned to 0.89 recruits/1k — the leak the throttle was
                               # meant to close. The target was the real bug: roster_cap
                               # (30) refills a bench nobody fields (3-6 fielded all run;
                               # measured fieldable ceiling ~17 — stamina and errand
                               # pacing bound fielding, not roster). Recruiting now stops
                               # entirely while the roster exceeds field demand and the
                               # bench absorbs vanishes for free.
                             # deaths), not a wipe — shortfall-relative so the rule
                             # holds under any roster_cap, unlike an absolute floor
RECRUIT_COOLDOWN = 8  # v0.10.0: same staleness for recruit — a just-recruited char
#   isn't in the roster for a few frames, so re-firing recruit storms roster_cap.
RECRUIT_BENCH = 2     # v0.27.0: recruit only up to (party_cap * maps) + this small
#   rotation bench — the practical number we can field — instead of the server's much
#   higher roster/world cap. Over-recruiting grew an undeployable bench and armed each
#   new bare char with a 15g club, draining all income; capping it lets gold stockpile.
RECRUIT_INFLIGHT_TTL = 100   # v0.43.0: how long a just-issued recruit counts toward the
#   roster estimate before it's assumed to have landed (and shown up in the counts). Bridges
#   the post-deploy window where the public spectate endpoint AND the frame snapshot both lag
#   our real roster, which let the recruit gate fire a ~21-char burst on run #100. Sized well
#   above the observed recruit-appearance lag (~a few tens of ticks) so the burst is capped at
#   ~1 recruit until the counts catch up; deaths are ~0 so the slow back-fill this implies is fine.
# v0.49.0 IN-FLIGHT INTENT LATCH. The cooldown below is a TIMER, and a timer is the wrong
# termination condition for "has my purchase landed yet?": when the frame is staler than the
# cooldown, the character still looks bare after it expires, so the buy is issued again.
# Measured on run #117 — one character bought SIX clubs at ticks 1397061/67/73/79/85/91,
# exactly VILLAGE_ACTION_COOLDOWN apart, and another bought four then re-equipped the SAME
# item_id five times. That is ~135 gold wasted in one run, against a treasury that hovers
# at ~145 and has never sustained the 200 armor floor.
# So latch on the INTENT and clear it when the frame CONFIRMS it, with a TTL only as a
# safety net so a genuinely failed action cannot block a character forever. This is the
# v0.14.0 re-send storm returning through the same door; the fix closes it properly.
INTENT_TTL = 60               # ticks before an unconfirmed intent is abandoned as failed
# v0.50.1 — which REJECTIONS may free an in-flight intent early. v0.49.0 freed it on ANY
# error for the character, and run #119 showed why that is wrong: 15 of 15 duplicate buys
# were preceded by a `not_in_village` rejection. The character had actually left the
# village; the stale frame still showed it there, so clearing the latch just re-issued an
# identical buy that failed identically — a retry storm on a PERSISTENT condition. (It
# only surfaced now because v0.50.0 unblocked movement, taking `not_in_village` from 8.6
# to 47.6 per 1k frames.)
# So free the latch only when the next attempt would DIFFER: a wrong_slot rejection makes
# us try another slot, and a stat_requirement rejection makes us stop trying that kind.
# Everything else re-issues the same doomed action, and waits out INTENT_TTL instead.
INTENT_RETRY_DIFFERS = frozenset({"wrong_slot", "stat_requirement"})
VILLAGE_ACTION_COOLDOWN = 6   # v0.14.0: after a char issues a per-char village
#   action (buy/sell/equip/brew/smelt/spend_xp), don't issue it another for this
#   many ticks — the frame is a few ticks stale, so re-issuing the same buy/sell
#   spams no_such_item / over-buys before the change is reflected.
HOME_CLEAR_FRAC = 0.5   # v0.16.0: a char latches into "heading home" when full and
#   stays there — looting suppressed — until it is light again (used <= cap*this),
#   which happens after the village sells its haul. Hysteresis (enter at cap-1, exit
#   at half-cap) stops the latch flickering, and suppressing pickup while homing is
#   what kills the 0.15.0 pickup<->drop thrash (a shed item re-grabbed off own tile).


WIZARD_SEATS = 6           # v0.88.0 (operator): a MAXIMUM of six wizards, two per map
HYSTERESIS_SLACK = 2       # v0.94.0: an incumbent seat-holder must fall more than this
                           # many places below the cutoff to be evicted (anti-thrash)
WIZARD_SEATS_PER_WORLD = 2


def wizard_rank_key(char: dict[str, Any]):
    """The operator's ordering, verbatim: 'chosen by their int. If we have a tie, order
    by level and by other stats.' The int GIFT slots between level and raw stats (it
    halves every future INT point, which is exactly what the seats exist to buy), and the
    uid tail makes ties deterministic so the seat set can never flap between frames."""
    stats = char.get("stats") or {}
    # v0.94.0 (operator): the int GIFT now outranks LEVEL. The prior order (int, level,
    # gift, ...) evicted exactly the char worth keeping: a protected wizard levels SLOWER
    # than bold foragers, so higher-level non-gifted chars displaced the int-gifted one
    # from its seat, and demotion removed its protection and got it killed deep (#184,
    # the arch-wizard). The gift halves every future INT point — it IS the ceiling-breaker
    # — so it belongs above a level the cautious wizard can never win on.
    return (-stats.get("int", 0),
            0 if "int" in (char.get("gifts") or []) else 1,
            -(char.get("level") or 0),
            -sum(v for v in stats.values() if isinstance(v, int)),
            str(char.get("char_uid") or ""))


MAKE_ROOM_TTL = 300        # ticks a make-room flag stays live before the request lapses
WIZARD_MIN_POOL = 12       # seats exist only when the ranked pool is at least this deep.
                           # Without the floor, the two chars sighted right after a
                           # restart would BOTH rank into the top-6, turn wizard, and
                           # fall back home — momentary roster-wide paralysis until the
                           # ledger fills (the exact state weirdness the operator warned
                           # about). Below the floor there are NO wizards and everyone
                           # plays their level/stat role; the ledger crosses 12 within a
                           # frame or two of the first village sighting.


def select_wizards(chars: list[dict[str, Any]], cap: int = WIZARD_SEATS,
                   incumbents: "set | frozenset" = frozenset()) -> set:
    """The chosen circle: a PURE function of (roster snapshot, current incumbents) — still
    no seat state stored INSIDE here; the caller owns the tiny incumbent set and an empty
    one (the default, and every restart's first frame) reduces this to plain top-cap.

    Self-stabilising by construction: the moment a seat-holder spends one INT point it
    outranks every lower challenger. v0.94.0 adds LIGHT HYSTERESIS: an incumbent keeps its
    seat while it stays within cap+HYSTERESIS_SLACK by rank, so a one-tick dip (a new
    higher-INT sighting, a pool wobble) no longer evicts a protected wizard into a bold
    forager and gets it killed — the arch-wizard failure on #184. It takes a sustained
    fall of more than SLACK places to actually lose a seat."""
    uids = {}
    for c in chars:
        u = c.get("char_uid")
        if u and u not in uids:
            uids[u] = c
    if len(uids) < WIZARD_MIN_POOL:
        return set()
    ranked = [c["char_uid"] for c in sorted(uids.values(), key=wizard_rank_key)]
    pos = {uid: i for i, uid in enumerate(ranked)}
    seats = list(ranked[:cap])                     # the pure top-cap is the base...
    # ...then LIGHT hysteresis: an incumbent that dipped JUST outside (within SLACK ranks)
    # reclaims its seat from the newcomer that displaced it — but ONLY when that newcomer
    # beat it by no more than SLACK ranks. A clearly-superior newcomer (a new high-INT
    # char) is never blocked; only a near-tie at the boundary is held steady. That margin
    # is the whole anti-thrash: it stops a protected wizard flapping to bold-forager and
    # dying (the #184 arch-wizard) without letting a stale seat outstay a real challenger.
    # only chars OUTSIDE the base can reclaim; the rank-gap check below is what bounds
    # the slack (an incumbent more than SLACK past the cutoff can never find a displacer
    # within SLACK, so no separate window limit is needed — one source of truth for it).
    for inc in ranked[cap:]:
        if inc not in incumbents:
            continue
        displacers = [u for u in seats
                      if u not in incumbents and pos[inc] - pos[u] <= HYSTERESIS_SLACK]
        if displacers:
            worst = max(displacers, key=lambda u: pos[u])   # the weakest such newcomer
            seats.remove(worst)
            seats.append(inc)
    return set(seats)


def role_of(char: dict[str, Any], wizard_uids: "set | None" = None,
            nuisance_uid: "str | None" = None) -> str:
    """v0.39.0 per-character role, derived from level (not stored, so it self-adjusts as a
    char levels up). A leveled veteran is a GUARDIAN (worth protecting -> disengages early);
    a fresh recruit is a FORAGER (cheap -> works the edges of danger for income). Shared by
    the strategy (biases the severity threshold) and the dashboard (shows the role), so the
    role has ONE source of truth."""
    # v0.83.1 (operator: "I would like to have a wizard... I'd like them to be
    # protected"): the caster-designate is a GUARDIAN at ANY level. Death is permanent,
    # so a dead wizard loses the INT grind, the learned form, and the consumed tome —
    # the entire pipeline — where a dead forager loses a club. Protection costs the
    # designate some XP rate (cautious thresholds, no predator trades); the investment
    # maths favours it long before level 4.
    # v0.88.0: wizardhood is a CHOSEN SEAT (top-WIZARD_SEATS by wizard_rank_key over the
    # whole roster), not a gift of the dice. Callers with a roster view pass the seat set;
    # the gift-based fallback survives ONLY for callers that cannot see the roster, and
    # over-approximates deliberately (an int-gifted char is a likely seat) rather than
    # under-protecting.
    # v0.96.0: the nuisance overlay is display-only — passed by the dashboard, never by
    # the strategy's own my_role (whose survival thresholds use the base role), so a
    # nuisance still flees/heals as the forager or guardian it actually is.
    if nuisance_uid is not None and char.get("char_uid") == nuisance_uid:
        return "nuisance"
    if wizard_uids is not None:
        if char.get("char_uid") in wizard_uids:
            return "wizard"
    elif "int" in (char.get("gifts") or []):
        return "wizard"
    # v0.87.0 (operator: "if we get a really shitty recruit, we should probably
    # classify them as 'fodder' and have them sacrifice themselves"): a roll in the
    # bottom ~11% (stats sum <= FODDER_STAT_SUM; rolls are 1-2 per stat, so the range is
    # 6-12 and mean 9) with no int gift is FODDER — no coin is ever spent on it, it
    # works at maximum boldness, and it trades hits where others dodge. Checked after
    # wizard (an int-gifted bad roll is still a wizard: INT is the point) and before
    # guardian (levelling does not promote fodder out of its class — its stats stay
    # cheap and so does it).
    stats = char.get("stats") or {}
    _SIX = ("str", "dex", "int", "vit", "end", "agi")
    if all(k in stats for k in _SIX) and sum(stats[k] for k in _SIX) <= FODDER_STAT_SUM:
        # ALL six must be present: an absent stat is unknown, not zero, and a char we
        # cannot fully read must never be condemned to the expendable class by default.
        return "fodder"
    return "guardian" if (char.get("level") or 0) >= GUARDIAN_LEVEL else "forager"


class Explorer:
    version = "explorer/0.118.1"

    def __init__(self) -> None:
        # Equip-slot learning (persists across frames): slots a kind has been
        # rejected from (wrong_slot), and kinds that fail a stat requirement.
        self.slot_wrong: dict[str, set[str]] = defaultdict(set)
        self._slots_hydrated = False
        self._slots_persisted = 0
        self.slot_right: dict[str, str] = {}  # v0.109.1: kind -> slot PROVEN by seeing
                                              # any of our chars wear it (frames are
                                              # truth); a proven kind never slot-probes
        # v0.65.0: kind -> the stat TOTAL of the character that failed its requirement.
        #
        # This was a plain set, and that made it a ratchet with a known key: the gate is a
        # STAT requirement, and stats GROW -- `spend_xp` has fired 2,151 times, and between
        # runs #129 and #141 our maxima went str 2->6, vit 3->8, level 6->18. A kind refused
        # at str 2 stayed refused at str 6, forever, in all seven places this is consulted
        # (equip x2, armour buy, forge product choice, and the sell rule, which then banks
        # the item). Worse, being keyed on KIND alone, one weak character's refusal
        # condemned the kind for every stronger character too.
        #
        # Storing the threshold makes the restoring event explicit: a character whose stats
        # now EXCEED the ones that were refused may try again. A second refusal simply
        # raises the bar to that character's total.
        self.wont_fit: dict[str, int] = {}
        # uid -> stat total, refreshed from every frame we see the character in, so
        # on_action_error can attribute a refusal to the stats it was refused at.
        self._stat_total: dict[str, int] = {}
        self.equipping: dict[str, tuple[str, str]] = {}   # uid -> (kind, slot) in flight
        # In-flight guild-command tracking (v0.10.0): the tick each char was last
        # embarked, and the tick recruit last fired — so a stale village frame does
        # not make us re-send the same command every tick (the phantom-character
        # duplicate-send storm). Pruned once the char leaves `chars_here`.
        self._embark_at: dict[str, int] = {}
        self._recruit_at: int | None = None
        # v0.43.0: ticks of recruits we've issued that may not yet show in the roster counts,
        # so a post-deploy count lag can't drive a recruit burst (see the recruit gate).
        self._recruit_inflight: list[int] = []
        # In-flight guard for per-char VILLAGE actions (v0.14.0): the tick each
        # char last issued a village action, so a stale frame doesn't make it
        # re-send the same buy/sell/equip every tick (run #38: 250 buy + 148 sell
        # actions for ~1 sale — the same duplicate-send storm as embark).
        self._village_acted: dict[str, int] = {}
        # uid -> (intent_key, tick_issued); see INTENT_TTL.
        # v0.78.1: vault item_ids the server has REFUSED with no_such_item. The frame's
        # guild.inventory turned out to carry PHANTOM entries — run #160 opened with item
        # 13913 first in the list, and 1,181 withdrawals of it were all rejected: a dead id
        # is not a stale-frame repeat, it is dead forever, so it must be remembered, not
        # retried. Maps item_id -> True; guild-level because the vault is guild-level.
        self._vault_dead: set = set()
        self._vault_dead_new = 0            # v0.108.0: phantoms discovered THIS run —
        self._vault_arm_failures = 0        # v0.108.1: FAILED club probes THIS run
        self._vault_pending_arm: set = set()  # item_ids issued by the ARM branch
                                            # the storm latch counts fresh probes, not
                                            # the hydrated knowledge (else persistence
                                            # would close the latch at startup forever)
        self._vault_hydrated = False
        # v0.81.0: ingredient kinds we have SENT a taste for this run (or had refused).
        # Once per kind per run — taste is destructive, and a parser that missed the
        # result must not eat a second herb for nothing.
        self._tasted: set = set()
        # v0.82.0: one market probe per run; True also on rejection (fail closed).
        self._listed = False
        self._market_reclaimed = False   # stale-probe unlist, once per run
        self._ride_probed = False        # v0.93.0: one ride experiment per run
        self._tome_bought = False        # v0.83.0: one tome purchase per run
        # v0.85.0: uid -> role, updated on every sighting (field or village). The village
        # frame does not carry FIELDED chars' gifts, so the embark gate reads this ledger
        # to know which worlds hold a guardian.
        self._roles: dict = {}
        self._escorting: set = set()   # guardians mid-escort (hysteresis)
        self._party: dict = {}         # v0.86.0: wizard_uid -> guardian_uid (the pairing IS the party)
        # v0.88.0: per-character sightings ledger — the roster never appears in one frame
        # (village frames show villagers, field frames show one world), so seat selection
        # ranks over the union of last sightings. Pruned on death; a restart re-derives
        # the same seats because the seat-holders' invested INT outranks the pool.
        self._char_ledger: dict = {}
        self._wizard_incumbents: set = set()   # v0.94.0: last tick's seats (hysteresis)
        # v0.96.0 the nuisance: one volunteer's tour of duty against WillMorr's party.
        self._nuisance: dict = {"uid": None, "phase": "shadow", "loot_pos": None,
                                "seen_tick": -10 ** 9, "pout_tick": -10 ** 9,
                                "laughed": False}
        self._will_eids: dict = {}     # Will's char eid -> tick last seen (attack blame)
        self._make_room: dict = {}     # world -> tick: a seat needs a slot there
        self._wizard_recall: dict = {}   # v0.102.0: uid -> tick of last band-danger fallback
        self._returned_empty: dict = {}  # v0.105.0: uid -> tick the looted-out retreat fired
        self._looted_home: dict = {}     # v0.109.4: uid -> tick it COMMITTED to the
                                         # looted-out walk; gather beelines stay off
                                         # until arrival (y<=2) or an observed refresh
                                         # — the mirage-loot flip (run #209, c19550:
                                         # N-loot/S-looted-out x2) dies of commitment
        self._scout_sent: dict = {}      # v0.106.1: world -> tick a scout was released to it
        self._ghosted: dict = {}         # v0.107.1: uid -> tick the server refused its command
        self._ghost_seen: dict = {}      # v0.110.3: uid -> last sighted (pos, sta, hp)
        self._nuisance_hold = -1         # v0.111.3: tick the nuisance held station
        self._vault_pending: dict = {}      # char_uid -> item_id of an in-flight withdrawal
        self._village_intent: dict[str, tuple[str, int]] = {}
        # v0.52.0: (product, n_ingot, n_lumber) combinations the server has REJECTED, so a
        # failed recipe is tried once and never again. Mirrors slot_wrong/wont_fit.
        self._forge_failed: set[tuple[str, int, int]] = set()
        # uid -> the (product, n_ingot, n_lumber) most recently attempted, so
        # on_action_error can attribute a rejection to the recipe that earned it.
        self._forge_attempt: dict[str, tuple[str, int, int]] = {}
        # v0.64.0: recipes a `forged` event has PROVEN, and a per-recipe failure tally.
        #
        # v0.52.0 blacklisted a recipe on its FIRST `wrong_materials`, which assumed the
        # server's refusal is a function of (product, ingots, lumber). Run #140 shows it is
        # not: the identical product, material KINDS and quantities both succeeded and
        # failed within one run. Against a non-deterministic signal, a one-strike permanent
        # blacklist is a ratchet -- it only ever removes options -- and it had condemned ALL
        # FIVE spear recipes and ALL FIVE shield_iron recipes, including `(spear, 1, 1)`,
        # which produced `forged` events on runs #129 AND #140.
        #
        # So: proof outranks refusal. A recipe that has ever worked is never blacklisted,
        # and one that has not needs FORGE_FAIL_LIMIT refusals before we give up on it.
        self._forge_proven: set[tuple[str, int, int]] = set()
        self._forge_hydrated = False
        self._forge_fails: dict[tuple[str, int, int], int] = defaultdict(int)
        # v0.63.0: (uid, tome_kind) the server refused -- INT gates which tomes a character
        # may use, so a refusal is durable information about that character.
        # (uid, tome_kind) -> the stat TOTAL that was refused. INT gates which tomes a
        # character may use (docs/06) and INT GROWS, so this is the same ratchet `wont_fit`
        # was and gets the same release: out-grow the refusal and you may try again.
        self._tome_failed: dict[tuple[str, str], int] = {}
        self._using: dict[str, str] = {}     # uid -> kind of the `use` in flight
        # v0.53.0: kind -> the shop's buy_price, learned from every village frame we see.
        # This is the only QUALITY ranking the game exposes: items carry no damage or
        # armour number, just `tier` -- and run #129 showed tier is not ordered, since a
        # forged spear came out tier 0 beside a tier-1 club. The shop's own valuation is
        # the game's opinion of what a kind is worth, read from the same frame field the
        # weapon and armour buys already trust.
        self.price: dict[str, int] = {}
        # (kind, slot) pairs the server refused to SWAP into while occupied, and the
        # kill-switch that stops trying at all if swapping turns out to be unsupported.
        self._swap_failed: set[tuple[str, str]] = set()
        self._swap_refusals = 0
        self._swap_unsupported = False
        self._equip_upgrade: set[str] = set()   # uids whose in-flight equip is a swap
        # "Heading home to sell" latch (v0.16.0): uids that filled up and are now
        # walking home. While latched, looting is suppressed so a shed item is
        # never re-grabbed off the char's own tile (the 0.15.0 pickup<->drop
        # thrash). Cleared once the char is light again (see HOME_CLEAR_FRAC).
        self._homing: set[str] = set()
        # Per-world undead threat (v0.26.0): world -> (undead_fraction, tick_observed).
        # Updated live from what fielded chars see; drives safe-world routing at embark
        # and expires after THREAT_TTL so an emptied world gets re-scouted.
        self._world_threat: dict[str, tuple[float, int]] = {}
        # v0.48.0: per-world DANGER for cohesion — (undead_frac, melee_pred_count, tick).
        # _world_threat above tracks UNDEAD only (it exists for safe-world routing), and
        # that reads ~0 in the mines, whose bats/rats/moles/delvers are melee predators
        # rather than undead. Cohering on it alone would leave us dispersed in exactly the
        # world we most want to raid, so danger counts both.
        self._world_danger: dict[str, tuple[float, int, int]] = {}
        self._death_gate: dict[str, int] = {}   # world -> tick of our last death there
        # Characters currently closing on an ally — the hysteresis latch.
        self._cohering: set[str] = set()

    def on_action_error(self, bot: "Any", message: dict[str, Any]) -> None:
        """Learn equip slots from the server's rejections. We send at most one
        equip per character per frame, so the pending (kind, slot) identifies it."""
        # v0.49.0/v0.50.1: a rejection frees the in-flight intent ONLY when the next
        # attempt would differ — otherwise we simply re-issue the same doomed action. See
        # INTENT_RETRY_DIFFERS. Silence, and every other rejection, waits out INTENT_TTL.
        uid = message.get("char_uid")
        if uid is not None and message.get("reason") in INTENT_RETRY_DIFFERS:
            self._village_intent.pop(uid, None)
        # v0.107.1 GHOST QUARANTINE — trust the refusal over the roster (the 0.62.0
        # rule). Run #202: c19532 had no death event and chars_here listed it home,
        # but the server refused its every command (not_in_village x23k,
        # unknown_character x5.5k) — and the village re-commanded it every TTL for
        # HOURS, each failed embark refreshing _scout_sent and thereby choking the
        # scout release for the other 29 benched chars. One ghost char parked the
        # whole roster. A char whose commands the server says make no sense is
        # quarantined from candidacy for GHOST_TTL; if it is real, it returns.
        if uid is not None and message.get("reason") in GHOST_REASONS:
            self._ghosted[uid] = message.get("tick", bot.tick)
            self._embark_at.pop(uid, None)      # stop the re-command loop at once
        # v0.52.0: a REJECTED forge teaches us its recipe was wrong. Record the exact
        # (product, ingots, lumber) so it is attempted once and never again — the recipe
        # quantities are undocumented, so the server's rejection IS the documentation.
        # v0.74.0: `say` is an action we had never sent before. If the server refuses it,
        # stop — a rejected action every cooldown would be a slow error-spam of exactly the
        # kind the anomaly monitor exists to shout about.
        # v0.78.1: a refused withdrawal names a PHANTOM vault id — remember it so the
        # next attempt tries the next entry instead of the same corpse forever (run #160:
        # 1,181 rejections of one id in 1,083 frames).
        if (message.get("action") == "drop" and message.get("reason") == "no_such_item"
                and uid is not None):
            dead = self._vault_pending.pop(uid, None)
            if dead is not None and dead not in self._vault_dead:
                self._vault_dead.add(dead)
                if dead in self._vault_pending_arm:
                    self._vault_pending_arm.discard(dead)
                    self._vault_arm_failures += 1   # v0.108.1: the ARM branch's budget
                else:
                    self._vault_dead_new += 1       # the potion branch's budget
                # v0.108.0: persist the cumulative phantom set (intel, observational —
                # the learned table is positive-facts-only by doctrine) so every run
                # probes DEEPER into the 202-entry vault list instead of re-treading
                # the same dead head. If ANY entries are real, we eventually find them.
                st = getattr(bot, "storage", None)
                if st is not None:
                    try:
                        import time as _t
                        intel.record(st.conn, "vault_phantom", bot.tick, _t.time(),
                                     {"ids": sorted(self._vault_dead)})
                    except Exception:
                        pass            # persistence is best-effort, never load-bearing
        # v0.82.0: NO on_action_error handler for `list`, deliberately — the offer sets
        # _listed when it fires, so a refusal has nothing left to disable and a handler
        # here would be unobservable dead code (the 0.74.1/0.80.0 deletions, same rule).
        # v0.81.0: a refused `taste` — whatever the reason — burns no more herbs of that
        # kind this run. The kind is already in _tasted (set when offered), so nothing to
        # do beyond not clearing it; recorded here for the reader.
        if message.get("action") == "say":
            bot.chatter.note_rejected(bot.tick)
        if message.get("action") == "forge" and uid is not None:
            pend = self._forge_attempt.pop(uid, None)
            if pend is not None and pend not in self._forge_proven:
                self._forge_fails[pend] += 1
                if self._forge_fails[pend] >= FORGE_FAIL_LIMIT:
                    self._forge_failed.add(pend)
        # v0.63.0: a refused `use` of a tome is durable information about this character.
        if message.get("action") == "use" and uid is not None:
            kind = self._using.pop(uid, None)
            if kind is not None and kind.startswith(TOME_PREFIX):
                have = self._stat_total.get(uid, 0)
                key = (uid, kind)
                self._tome_failed[key] = max(self._tome_failed.get(key, 0), have)
        if message.get("action") != "equip":
            return
        pend = self.equipping.get(message.get("char_uid"))
        if not pend:
            return
        kind, slot = pend
        reason = message.get("reason")
        was_upgrade = uid in self._equip_upgrade
        self._equip_upgrade.discard(uid)
        if reason == "wrong_slot":
            self.slot_wrong[kind].add(slot)     # not this slot — try another next time
        elif reason == "stat_requirement":
            # Record the bar rather than a bare "no": whoever tries next with better
            # stats deserves the attempt (v0.65.0).
            have = self._stat_total.get(uid, 0)
            self.wont_fit[kind] = max(self.wont_fit.get(kind, 0), have)
        elif was_upgrade:
            # v0.53.0: equipping into an OCCUPIED slot is an undocumented mechanic. Any
            # other rejection means this pair cannot be swapped -- record it so it is
            # tried once, and if enough distinct pairs are refused, conclude the server
            # has no swap at all and stop paying for the lesson.
            self._swap_failed.add((kind, slot))
            self._swap_refusals += 1
            if self._swap_refusals >= SWAP_GIVE_UP:
                self._swap_unsupported = True

    # -- village: gear + economy + healing supply + discovery-first deployment --

    def village(self, bot: "Any", frame: dict[str, Any]) -> list[dict[str, Any]]:
        guild = frame.get("guild", {})
        cfg = bot.config
        chars = frame.get("chars", [])
        # v0.101.0 TOME FUND. The magic ceiling nobody on the server has touched is ONE
        # tome (150g) away — the arch-wizard is INT 6, well past the gate — but on #193
        # gold sat pinned at ~30 because DISCRETIONARY buys (armour @70, bottles @32) kept
        # draining it below the 150 tome line before it could accumulate. While a
        # tome-ready seat exists and no tome has been bought this run, SAVE: the ARMOUR
        # buy (40-70g, the real drain) is suppressed so gold climbs to the tome. Bottles
        # (2g, the heal supply) and essentials (heal, arming a bare char) are untouched;
        # the fund releases the instant the tome is bought.
        # note THIS frame's chars into the seat ledger before the seat check, or a
        # just-arrived wizard is invisible to it (the ledger is what wizard_seats reads).
        for _c in chars:
            self.note_char(_c)
        _seats_now = self.wizard_seats()
        saving_for_tome = (not self._tome_bought and any(
            (c.get("stats") or {}).get("int", 0) >= TOME_BUY_MIN_INT
            for c in chars if c.get("char_uid") in _seats_now))
        # v0.96.0: a nuisance that reached home carrying WillMorr's spoils has finished
        # its tour. The loot is now in the village — the sell/equip economy banks it
        # (and selling it even funds the arm rate). Stand the tour down so a relief is
        # designated the next time Will's party is in the vale.
        here_now = {c.get("char_uid") for c in chars}
        if (self._nuisance["uid"] in here_now
                and self._nuisance["phase"] == "deliver"):
            self._nuisance_standdown(bot.tick, "spoils delivered home — tour complete")
            self._record_nuisance(bot)
        gold = guild.get("gold", 0)
        self._learn_prices(frame)
        self._hydrate_forge(bot)
        self._hydrate_vault(bot)
        self._hydrate_slots(bot)
        self._persist_slots(bot)   # no-op unless the proof map grew last frame

        for char in chars:
            uid = char["char_uid"]
            self._looted_home.pop(uid, None)   # v0.109.4: home — the stint is over
            # v0.107.1: a ghost (server-refused) char gets NO village economy actions
            # either — the 23k not_in_village errors on #202 were largely village
            # moves/buys re-commanded for a char the server said was not there.
            if bot.tick - self._ghosted.get(uid, -10 ** 9) < GHOST_TTL:
                continue
            self.note_char(char)            # v0.88.0: ledger BEFORE any seat check —
                                            # the spend/tome branches below ask
                                            # wizard_seats() and a char absent from the
                                            # ledger can hold no seat
            if char.get("craft"):
                continue                    # busy crafting; don't disturb or embark it
            # In-flight guard: a char that just acted is skipped for a few ticks so
            # the stale frame doesn't make it re-issue the same buy/sell/equip
            # (v0.14.0 — kills the run-#38 buy/sell re-send storm).
            if bot.tick - self._village_acted.get(uid, -10**9) < VILLAGE_ACTION_COOLDOWN:
                continue
            # v0.49.0: a gold-spending intent already in flight blocks this char until the
            # frame CONFIRMS it (or the TTL gives up), so a stale frame cannot buy twice.
            pending = self._village_intent.get(uid)
            if pending is not None:
                key, issued = pending
                if self._intent_landed(key, char):
                    del self._village_intent[uid]
                elif bot.tick - issued < INTENT_TTL:
                    continue                      # still in flight — do not re-issue
                else:
                    del self._village_intent[uid]  # gave up; let the char try again
            self._stat_total[uid] = self._stat_sum(char)
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
            # Forge feedstock (lumber/ingots/flux) reserved up to a per-char cap, so
            # 0.45's harvest actually reaches the forge instead of the shop counter.
            feedstock_keep = self._feedstock_keep_ids(inv)
            # v0.59.0: lone VIGOR herbs and raw ORE are half a pair, not clutter.
            scarce_keep = self._scarce_keep_ids(inv)
            # v0.63.0: can this character still take a new spell form? At the cap, learning
            # forgets the oldest (docs/06), so a tome is only worth holding under it.
            can_learn = self._can_learn(char)
            # 1) EQUIP carried gear into empty slots — BEFORE selling, or we sell
            #    the weapons/armor we ought to be wearing (the original bug: 0
            #    equips ever, everyone bare-handed and unarmored).
            eq = self._equip_action(uid, inv, eqp)
            if eq is not None:
                return [self._village_act(bot, uid, eq, eq.pop("_why"))]
            # 1b) LEARN A SPELL FORM (v0.63.0), ordered before selling for the same reason
            #     equipping is: otherwise the tome is banked for 36 gold before anything can
            #     use it, which is exactly what happened 74 times.
            tome = self._tome_to_learn(uid, inv, can_learn)
            if tome is not None:
                self._using[uid] = tome["kind"]
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "use",
                               "item_id": tome["item_id"]},
                    f"learning {tome['kind']} — a spell FORM; we have sold 74 of these "
                    f"and never cast once")]
            # 2) sell what we can't use: loot, gear that won't fit, and brewables
            #    that can't form a batch (stranded singletons).
            #
            # 2-pre) v0.81.0 TASTE BEFORE SELLING. `taste` — never once sent in the
            #    project's history — destructively consumes an ingredient and reports its
            #    essence, and knowledge.py has carried "resolve them with `taste` first"
            #    beside its undecoded guesses since run #8. The herbs it wants are
            #    EXACTLY the stranded singletons this branch sells for 1-3g: an undecoded
            #    lone brewable is worth more as knowledge than as coins, ONCE per kind.
            #    Every future one of its kind then either batches (decoded vigor -> heal
            #    supply) or sells as before. Ground survey on #165: glimmerweed 490,
            #    bitterroot 392, frostmoss 272 sightings — if even one decodes to vigor,
            #    the brew supply multiplies.
            # 2-pre-a0) v0.82.0 RECLAIM a stale probe: a listing of ours present before
            #    we listed anything this run survived a prior run unsold — nobody buys at
            #    that price. Unlist it (the item returns to inventory; the shop fallback
            #    banks its ~1g) and let the probe branch below post a fresh one. Listing
            #    shapes have never been observed; unreadable ones are logged and left.
            if not self._market_reclaimed and not self._listed:
                for l in guild.get("market_listings") or []:
                    if str(l.get("guild_id") or "") != str(guild.get("guild_id") or "\0"):
                        continue
                    lid = l.get("listing_id") or l.get("id")
                    if lid is None:
                        print(f"[market] unreadable listing of ours: {l!r}", flush=True)
                        continue
                    self._market_reclaimed = True
                    return [self._village_act(
                        bot, None, {"action": "unlist", "listing_id": lid},
                        f"unlisting probe {lid} — it survived a full run unsold, so "
                        f"nobody buys at that price")]
                self._market_reclaimed = True
            # 2-pre-a) v0.82.0 MARKET PROBE — before shop-selling a surplus lumber, list
            #    ONE on the player market per run. Guarded three ways: once per run
            #    (_listed), never while we already have a live listing (market_listings),
            #    and fail-closed on rejection (on_action_error sets _listed).
            if (not self._listed
                    and not any(str(l.get("guild_id") or "") == str(guild.get("guild_id") or "\0")
                                for l in (guild.get("market_listings") or []))):
                probe = next((i for i in inv
                              if i["kind"] == MARKET_PROBE_KIND
                              and i["item_id"] not in feedstock_keep
                              and self._should_sell(i, eqp, brew_keep, smelt_keep,
                                                    feedstock_keep, scarce_keep,
                                                    can_learn)), None)
                if probe is not None:
                    self._listed = True
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "list",
                                   "item_id": probe["item_id"],
                                   "price": MARKET_PROBE_PRICE},
                        f"listing a surplus {MARKET_PROBE_KIND} on the player market at "
                        f"{MARKET_PROBE_PRICE}g (shop pays ~1) — the market has been "
                        f"EMPTY all project; probing whether anyone buys")]
            for item in inv:
                if (knowledge.essence_of(item["kind"]) is None
                        and "brew" in (item.get("uses") or [])
                        and item["kind"] not in self._tasted
                        and self._should_sell(item, eqp, brew_keep, smelt_keep,
                                              feedstock_keep, scarce_keep, can_learn)):
                    self._tasted.add(item["kind"])
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "taste",
                                   "item_id": item["item_id"]},
                        f"tasting a stranded {item['kind']} — undecoded, and worth more "
                        f"as an essence than as the ~2g its sale would bank")]
            for item in inv:
                if self._should_sell(item, eqp, brew_keep, smelt_keep, feedstock_keep,
                                     scarce_keep, can_learn):
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "sell",
                                   "item_id": item["item_id"]},
                        f"selling {item['kind']} (tier {item.get('tier')}) to bank gold")]
            # 3) HEAL FIRST (v0.76.0). This used to sit below arming and armouring, and
            #    the ordering was the whole bug: see POTION_RESERVE. A character with no
            #    heal is confined to the bottom 12 rows of the map, so this is the cheapest
            #    20 gold we can spend — it is the difference between a roster that can
            #    reach the content carrying the XP and one that cannot.
            # v0.87.0: not one coin is ever spent on FODDER — no heal, no weapon, no
            # armor, no bottle. It sells, tastes, brews with what it has, banks XP
            # (spend_xp is free and its stats are cheap), and dies working.
            is_fodder = role_of(char, self.wizard_seats()) == "fodder"
            potions_held = sum(1 for i in inv if i["kind"] == "potion_red")
            if potions_held < POTION_KEEP and not is_fodder:
                # 3-zero) WITHDRAW FROM THE BANK FIRST (v0.78.0). Found on run #159 while
                # measuring the trek: the guild inventory held 202 potion_red — banked
                # loot and old brews, roughly TEN TIMES everything we have ever bought —
                # while characters went bare and the treasury ground at 109 buying more at
                # 20g. In the village, `drop {item_id}` moves an item OUT of the guild
                # inventory onto the character (docs/03-actions.md; the verb reads
                # backwards). A withdrawal costs zero gold, so it outranks the buy
                # unconditionally, and no intent latch is needed for the same reason
                # `sell` is excluded from it: each names a distinct item_id, so a
                # stale-frame repeat cannot double-spend — it bounces off no_such_item
                # and the per-char cooldown already spaces the retries.
                banked = next((i for i in protocol.vault_items(frame.get("guild"))
                               if i.get("kind") == "potion_red"
                               and i.get("item_id") is not None
                               and i.get("item_id") > self._vault_frontier()), None)
                # Fail closed: a vault whose first VAULT_DEAD_LIMIT potion ids are all
                # phantoms is a vault we do not understand — stop withdrawing this run
                # rather than walking 202 entries of an error storm, and let the shop buy
                # below carry the heal.
                if banked is not None and self._vault_dead_new >= VAULT_DEAD_LIMIT:
                    banked = None
                if banked is not None:
                    self._vault_pending[uid] = banked["item_id"]
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "drop",
                                   "item_id": banked["item_id"]},
                        f"withdrawing a banked potion_red (item {banked['item_id']}; "
                        f"{sum(i.get('count', 1) for i in frame['guild']['inventory'] if i.get('kind') == 'potion_red')} "
                        f"in the vault) — free, unlike the 20g shop buy")]
                buy = self._afford_potion(frame, gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying a {kind} ({price}g) — an un-healed char is capped at "
                        f"POISON_SAFE_DEPTH and never reaches the content worth XP")]
            # 3a) still bare-handed with nothing to equip? buy the best weapon we
            #    can AFFORD and qualify for (v0.13.0). The old gate was a hardcoded
            #    `gold >= 45` = shortsword's price, so a broke guild NEVER bought
            #    the 15-gold club and instead drained gold into 20-gold potions —
            #    a self-inflicted piece of the poverty deadlock. Read the live shop
            #    prices + stat reqs; a club at 15 lowers the bootstrap escape from
            #    45 gold to 15, so the guild can arm a char the moment it scrapes
            #    a little loot, and that char can then survive → loot → recover.
            # v0.108.0 ARM FROM THE VAULT FIRST: the stash holds real clubs (14 on
            # #203's census, and lumber withdrawals prove non-potion vault entries
            # are live). A withdrawal costs ZERO gold against the shop's 15 — at the
            # 20-gold treasury we actually run, every vault club is two-thirds of a
            # potion the flywheel keeps not affording. No gold floor on this branch
            # (it spends none); same vault-dead/pending machinery as the potion
            # withdrawal, so phantoms latch instead of storming.
            if (eqp.get("hand") is None and not is_fodder
                    and uid not in self._vault_pending
                    and self._vault_arm_failures < VAULT_ARM_PROBES):
                banked_club = next(
                    (i for i in protocol.vault_items(frame.get("guild"))
                     if i.get("kind") in VAULT_ARM_KINDS
                     and i.get("item_id") is not None
                     and i.get("item_id") > self._vault_frontier()), None)
                if banked_club is not None:
                    self._vault_pending_arm.add(banked_club["item_id"])
                    self._vault_pending[uid] = banked_club["item_id"]
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "drop",
                                   "item_id": banked_club["item_id"]},
                        f"withdrawing a banked {banked_club['kind']} (free, vs 15g at "
                        f"the shop) — arming from the stash instead of the treasury")]
            # v0.109.0 DEAD-CAPITAL ARMING: at 2026-08-24's treasury (gold 16, 1/30
            # armed) the gold could buy NOTHING — below the potion gate (30) AND the
            # weapon floor (45) — while the disarmed roster generated no kills, no
            # bones, no brews, no income. When the POTION BUY ITSELF says it cannot
            # fire (_afford_potion is None: priced out or out of stock), the floor is
            # protecting a heal that cannot happen; a bare char may then buy the
            # cheapest weapon it qualifies for, keeping DEAD_CAPITAL_KEEP behind.
            # The reachable-heal case is untouched: while a potion IS affordable,
            # only the classic floor opens the weapon branch.
            _dead_capital = (self._afford_potion(frame, gold) is None)
            if (eqp.get("hand") is None and not is_fodder
                    and (gold > WEAPON_BUY_FLOOR or _dead_capital)):
                buy = self._afford_weapon(char, frame, gold - DEAD_CAPITAL_KEEP
                                          if _dead_capital and gold <= WEAPON_BUY_FLOOR
                                          else gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying a {kind} ({price}g; bare-handed — arming to break the poverty trap)")]
            # 3a-bis) v0.83.0 BUY THE TOME — the magic unlock, for the caster-designate
            #    only ("int" in gifts). Gated like every other purchase on the potion
            #    reserve, so it can never eat the heal; once per run; skipped while ANY
            #    tome is already in this character's pack (one unlock at a time — the
            #    tome is consumed on learning, so a second is a hoard, not a spare).
            # v0.83.1 (operator: "worried about the bought-tome path... don't want to
            # burn gold"): the buy also waits for the designate's INT to be nearly there
            # (>= TOME_BUY_MIN_INT), shrinking the stranded-capital window to almost
            # nothing. NB a tome is only CONSUMED on successful learning — a refused
            # `use` keeps the item — so the true worst case was always a shelf, not a
            # burn; this makes the shelf-time short too.
            if (uid in self.wizard_seats() and not self._tome_bought
                    and char.get("stats", {}).get("int", 0) >= TOME_BUY_MIN_INT
                    and not any(str(i.get("kind", "")).startswith(TOME_PREFIX)
                                for i in inv)):
                price = self._shop_price(frame, TOME_BUY_KIND)
                if price is not None and gold - price >= POTION_RESERVE:
                    self._tome_bought = True
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy",
                                   "kind": TOME_BUY_KIND},
                        f"buying a {TOME_BUY_KIND} ({price}g) — the magic unlock nobody "
                        f"on this server has touched; INT pre-banked on this char")]
            # 3b) ARMORED, not just armed (v0.47.0). Only once the hand is filled, and
            #     only above ARMOR_BUY_FLOOR (> the weapon floor), so arming a bare char
            #     always outranks armoring an equipped one.
            if (eqp.get("hand") is not None and gold > ARMOR_BUY_FLOOR
                    and not is_fodder and not saving_for_tome):
                buy = self._afford_armor(char, eqp, frame, gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying {kind} ({price}g; armouring an empty slot -- we have "
                        f"never bought armor and rivals field ~60% armored)")]
            # 4b) brew looted ingredients into potions — but only with a bottle we
            #     already hold; the bottle-BUY is frozen too (hoard). Free potions
            #     from foraged herbs still help protect a char's carried loot.
            bottles = sum(1 for i in inv if i["kind"] == "bottle_empty")
            picks, ess, healing = self._choose_brew(brewables)
            # 4a-bis) BUY A BOTTLE (v0.58.0) -- but only for a character that could brew
            # RIGHT NOW if it had one. Gating on `picks` is what makes this provably
            # useful rather than a standing 2g tax: it means the herbs are already in the
            # pack and a bottle is the only missing part. Ordered AFTER arming and
            # armouring, so a bare character is never left bare for a bottle.
            #
            # v0.79.0: floored at the POTION reserve, not the weapon floor. The 150 floor
            # made this branch DEAD at the 100-150 gold this guild actually runs (zero
            # bottle buys ever recorded), which silently killed brewing — the supply that
            # once provided 99.6% of heals (potion_red is still the all-time top brew
            # product, 137 of them). A 2g bottle that becomes a heal is the same purchase
            # as the 20g shop potion at a tenth the price, so it clears the same floor the
            # potion-buy clears, and BOTTLE_KEEP=1 with the `picks` gate keeps it from
            # ever becoming a standing drain. The vault's 404 listed bottles are phantoms
            # (see server_bugs.md), so the shop is the only real source.
            # PREMISE(2026-08-23, brewing is our cheap heal supply and the shop its only
            #   bottle source): brew products by kind; vault withdrawal rejections
            # v0.106.0: floored at POTION_MIN_BUFFER like the potion buy — a 2g bottle
            # that turns held herbs into a heal is the heal supply, and the reserve
            # must not veto the very spending it exists to protect.
            if picks and bottles < BOTTLE_KEEP and not is_fodder:
                price = self._shop_price(frame, "bottle_empty")
                if price is not None and gold - price < POTION_MIN_BUFFER:
                    price = None
                if price is not None:
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": "bottle_empty"},
                        f"buying a bottle_empty ({price}g) — we hold {len(picks)} brewable "
                        f"ingredients and no bottle, and brewing is where our heals come from")]
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
            # 4d) FORGE (v0.52.0) — ingots + lumber into gear the shop will not sell.
            #     Placed after smelting so ore becomes an ingot first, and before the XP
            #     spend so a forge-ready character does not idle its materials.
            # v0.64.0: a completed forge PROVES the recipe that character last attempted.
            # Credited here, where we have both the bot's event view and our own pending
            # attempt -- proof is the only positive evidence this ladder ever receives, and
            # without it failures ratchet the options away one by one.
            if bot.recently_forged(uid):
                proven = self._forge_attempt.pop(uid, None)
                if proven is not None:
                    self._prove_forge(bot, proven)
            # v0.98.0 SMITH PIPELINE — material CONVERGENCE. A spear needs 1 lumber AND
            # 1 ingot on the SAME char; on #189 0/28 bare chars held both, so nobody
            # forged. Ingots are the scarce material (smelted from mines ore) and lumber
            # is plentiful (19 sat in the guild stash while chars stayed bare). So a char
            # holding an INGOT but no lumber WITHDRAWS a lumber from the stash — free
            # (drop moves an item OUT of guild inventory onto the char) — to become
            # forge-ready. Same vault-dead failsafe as the potion withdrawal: a stash
            # whose first VAULT_DEAD_LIMIT lumber ids are phantoms stops withdrawing.
            has_ingot = any(str(i.get("kind", "")).startswith("ingot") for i in inv)
            has_lumber = any(str(i.get("kind", "")).startswith("lumber") for i in inv)
            if (has_ingot and not has_lumber
                    and uid not in self._vault_pending
                    and len(self._vault_dead) < VAULT_DEAD_LIMIT):
                banked_lum = next(
                    (i for i in protocol.vault_items(guild)
                     if str(i.get("kind", "")).startswith("lumber")
                     and i.get("item_id") is not None
                     and i.get("item_id") > self._vault_frontier()), None)
                if banked_lum is not None:
                    self._vault_pending[uid] = banked_lum["item_id"]
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "drop",
                                   "item_id": banked_lum["item_id"]},
                        f"smith: withdrawing a lumber (item {banked_lum['item_id']}) to "
                        f"pair with a held ingot and forge a weapon")]
            forge = self._choose_forge(inv, eqp, char.get("stamina", 0))
            if forge is not None:
                recipe, item_ids, why = forge
                self._forge_attempt[uid] = recipe        # (product, n_ingot, n_lumber)
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "forge",
                               "product": recipe[0], "item_ids": item_ids}, why)]
            # 5) spend banked XP on durability (safe in the village).
            # v0.88.0 (operator: "max int on selected chosen characters as quickly as
            # possible"): a SEAT-holder routes EVERY XP to INT, uncapped (the stat cap is
            # 24), banking when the next point is unaffordable — never a coin of XP on
            # vit. Everyone else keeps the survival priority.
            is_seat = uid in self.wizard_seats()
            if is_seat:
                stat = self._pick_xp_stat(char, wants_int=True, int_only=True)
            else:
                stat = self._pick_xp_stat(char, wants_int=self._needs_int(uid, inv))
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
        # v0.43.0: take the MAX of the authoritative spectate total and the fresh frame
        # snapshot, not auth-when-present. On run #100 the public spectate endpoint lagged
        # our post-deploy roster — it reported 9 for ~176 ticks while the real roster climbed
        # to 30 — so the gate below recruited every cooldown against a phantom-low count and
        # overshot the fieldable cap to ~30 (a bare bench of ~20). The roster essentially only
        # grows (deaths ~0), so a low read from either source is the stale one; the max is the
        # truer floor. The startup window where BOTH read low is covered by the in-flight
        # recruit count added in the gate below.
        roster_seen = max((auth[0] if auth is not None else 0), len(here) + fielded)

        # In-flight guard, v0.107.0: records now expire by TIME, not by roster
        # presence. The v0.10.0 rule dropped a record the moment the char left the
        # STALE chars_here — then a later, staler frame re-listed the char, the
        # cooldown had no record to check, and the village re-commanded the embark
        # into a not_in_village error, 3,347 times on #197 alone. A record now lives
        # for EMBARK_ISSUED_TTL ticks regardless of what the lagging roster claims;
        # a genuinely failed embark retries after the TTL (a bounded delay), while a
        # landed one can no longer be re-commanded off a ghost listing.
        tick = bot.tick
        self._embark_at = {u: t for u, t in self._embark_at.items()
                           if tick - t < EMBARK_ISSUED_TTL}
        inflight = set(self._embark_at)

        # RECRUIT — but only up to what we can actually FIELD, not the server's high
        # roster/world cap (v0.27.0). We field at most party_cap per world, and
        # safe-world routing keeps us out of undead worlds, so the practical field is
        # ~party_cap * maps; recruiting toward the full cap just grows a bench we never
        # deploy AND arms each new bare char with a 15g club — which was draining every
        # scrap of income (gold cycled 0->14->buy-a-club->0 and never stockpiled).
        # Cap the roster at the fieldable size + a small rotation bench so the
        # club-arming drain stops and gold can accumulate. (Still at most once per
        # RECRUIT_COOLDOWN — a just-recruited char isn't in the count for a few frames.)
        maps = [m["id"] for m in cfg.get("maps", [])] or list(DEFAULT_MAPS)
        party_cap = cfg.get("party_cap", 5)
        # v0.87.0 (operator: "we should probably fill the roster"): recruit to ROSTER
        # CAP. Recruits are free and the gift lottery is the only wizard source — two
        # random gifts a roll means ~1 in 3 recruits comes int-gifted, so an empty bench
        # is unfilled wizard candidates. The old min() kept the roster near the fieldable
        # count out of recruit-burst trauma (0.43.0), but that bug was lagging COUNTS,
        # not bench size, and the settled-count gate already fixed it.
        recruit_target = min(roster_cap, RECRUIT_TARGET_FIELDABLE)
        # v0.43.0: count recruits WE'VE just issued that may not show in either count yet, so a
        # startup burst can't overshoot before the counts catch up. Without this, at t+0 both
        # counts read the not-yet-checked-in roster (9) and the gate fires every RECRUIT_COOLDOWN
        # for ~170 ticks (21 recruits) before the snapshot reflects reality. Each issued recruit
        # lifts the estimate immediately, so recruiting stops within ~1 of the target and resumes
        # only as recruits land (drop out of in-flight after RECRUIT_INFLIGHT_TTL) or the counts
        # rise. Mirrors the embark in-flight guard above.
        self._recruit_inflight = [t for t in self._recruit_inflight
                                  if tick - t < RECRUIT_INFLIGHT_TTL]
        roster = roster_seen + len(self._recruit_inflight)
        _interval = (RECRUIT_MIN_INTERVAL
                     if recruit_target - roster <= RECRUIT_CHRONIC_MAX
                     else RECRUIT_COOLDOWN)
        if roster < recruit_target and (
                self._recruit_at is None or tick - self._recruit_at >= _interval):
            self._recruit_at = tick
            self._recruit_inflight.append(tick)
            return [self._village_act(bot, None, {"action": "recruit"},
                                      f"recruiting (roster {roster} < {recruit_target})")]

        # EMBARK — skip chars whose embark is already in flight (the stale-frame
        # duplicate-send storm that bounced no_such_character), and count those
        # in-flight embarks toward the world cap so we don't over-deploy either.
        here_avail = [u for u in here if u not in inflight]
        # v0.21.0: field ANY available char (reverted the v0.20.0 armed-only filter).
        # Fielding only armed chars EMPTIED the field — we don't hold enough armed
        # chars to fill world_cap, so removing the bare "padding" collapsed fielded
        # from ~10 to ~2 and income cratered (a death spiral: empty field -> no
        # income -> no gold -> can't arm -> field stays empty). A bare char in the
        # field still picks up loot and pads a slot, which beats an empty one; arming
        # them is the village loop's job, not a reason to bench them.
        # v0.117.0 BUNKER (absorbs the 0.116.1 shelter): while the health machine
        # reads the server unhealthy — sustained frame lag or a poison-rejection
        # storm — fielding anyone walks them into a stranding. The bench waits out
        # the weather; the state machine's grace periods (enter 120t sustained /
        # storm-confirmed, exit 2000t clean) mean a stray lag spike never benches
        # the guild and a brief lull never un-benches it.
        _sheltering = getattr(bot, "server_health", lambda: "ok")() != "ok"
        if _sheltering and here_avail:
            if tick - getattr(self, "_shelter_said", -10**9) >= 300:
                self._shelter_said = tick
                print(f"[shelter] holding {len(here_avail)} embarks — server "
                      "health: bunker", flush=True)
        if here_avail and not _sheltering and fielded + len(inflight) < world_cap:
            maps = [m["id"] for m in cfg.get("maps", [])] or list(DEFAULT_MAPS)
            party_cap = cfg.get("party_cap", 5)
            # v0.26.0: SAFE-WORLD routing — field into the world with the lowest
            # recently-observed undead level (stale/unseen = unknown = 0, re-scoutable),
            # so the guild concentrates in the wildlife world and out of the undead
            # ones (a char that fled an undead world re-routes to the safe one). Break
            # ties by fewest of us there (still spread within equally-safe worlds).
            def threat(m: str) -> float:
                t = self._world_threat.get(m)
                return t[0] if (t and tick - t[1] < THREAT_TTL) else 0.0
            open_maps = [m for m in maps if by_world.get(m, 0) < party_cap]
            if open_maps:
                # v0.85.0 ESCORT GATE: a wizard embarks only into a world where one of
                # our GUARDIANS is already fielded (per the sighting ledger), and if no
                # such world is open it stays home — the operator's explicit wish, at the
                # explicit cost that a thin guardian bench pauses the INT grind. Never
                # blocks anyone else: the picker walks past held-back wizards.
                by_world_uids = guild.get("chars_by_world", {}) or {}
                guardian_count = {w: sum(1 for u in (uids or [])
                                         if self._roles.get(u) == "guardian")
                                  for w, uids in by_world_uids.items()}
                guardian_worlds = {w for w, n in guardian_count.items() if n > 0}
                here_chars = {c.get("char_uid"): c for c in chars}
                for c in chars:
                    self.note_char(c)
                seats = self.wizard_seats()
                seat_count = {w: sum(1 for u in (uids or []) if u in seats)
                              for w, uids in by_world_uids.items()}
                for cand in here_avail:
                    cch = here_chars.get(cand)
                    if cch is not None:
                        self._roles[cand] = role_of(cch, seats)
                uid = None
                target = None
                pair_with = None
                # v0.89.0: the picker SCANS for a wizard first instead of taking
                # here_avail[0] whatever it is. The 0.87.0 loop broke on the first
                # candidate of ANY role, so the wizard branch only ran when a wizard
                # happened to stand first in line — 3 pair-embarks in all of run #177
                # against a six that fielded 0.0% of char-frames and banked zero XP.
                # The operator's directive says wizards ship out with guardians; a
                # picker that only pairs by coincidence is a defect, not a policy.
                ordered = sorted(here_avail,
                                 key=lambda u: 0 if role_of(here_chars.get(u) or {},
                                                            seats) == "wizard" else 1)
                for cand in ordered:
                    # v0.107.1: a ghost (server-refused) char is no candidate at all.
                    if tick - self._ghosted.get(cand, -10 ** 9) < GHOST_TTL:
                        continue
                    cch = here_chars.get(cand)
                    crole = role_of(cch, seats) if cch is not None else None
                    # v0.106.0: the HONEST re-embark condition, replacing 0.105.0's
                    # blind 150-tick nap (which merely PACED the commute — #199:
                    # 419 embarks/2797 ticks, chars rotating mines->vale->spire
                    # through worlds that were all still empty for them). A char
                    # that walked home looted-out re-embarks only into a world
                    # that has REPLENISHED since its stamp — unless it has since
                    # acquired a heal, which explodes its reachable set and moots
                    # the stamp (this is what makes potions the cure, not a nap).
                    c_maps = open_maps
                    _stamp = self._returned_empty.get(cand)
                    if _stamp is not None:
                        if any(i.get("kind") == "potion_red"
                               for i in (cch or {}).get("inventory") or []):
                            self._returned_empty.pop(cand, None)
                        else:
                            c_maps = [m for m in open_maps
                                      if self._replenished_since(bot, m, _stamp)]
                            if not c_maps:
                                # v0.106.1 NEVER STARVE THE FIELD. Run #200, 1300
                                # ticks in: all 30 chars benched (everyone stamped,
                                # ETAs far out) — and with nobody fielded, NO frames
                                # arrive, so no refresh can ever be OBSERVED: the
                                # gate had removed its own eyes. A fielded char is a
                                # sensor; an empty world may always be scouted by a
                                # stamped char (one at a time — the resend guard
                                # covers the frames chars_by_world lags behind an
                                # embark, the 0.43.0 lagging-count lesson).
                                c_maps = [m for m in open_maps
                                          if not by_world.get(m, 0)
                                          and tick - self._scout_sent.get(m, -10 ** 9)
                                          >= SCOUT_RESEND_TICKS]
                                if not c_maps:
                                    continue  # every world watched or freshly scouted
                    # v0.92.2: green = BARE HANDS, any level, any nominal role except
                    # fodder. #182 closed two loopholes at once: the level clause
                    # (victims were level 2-5 — cheap early spend_xp promotes past
                    # level<=1 in minutes) and the GUARDIAN branch (a level-5 bare-
                    # hander is a "guardian" by title and shipped un-gated — c19219
                    # died exactly this way). A bare-handed char routes through the
                    # gated generic branch whatever its title; wizards keep their own
                    # stricter gate.
                    green = (cch is not None
                             and not ((cch.get("equipment") or {}).get("hand"))
                             and crole != "fodder")
                    if crole == "wizard":
                        # v0.102.0: a wizard just recalled for a dangerous band WAITS out
                        # the band at home — don't re-dispatch it into the danger its
                        # (now-expired) memory no longer sees. The observation-staleness
                        # loop is what made the arch-wizard bounce home 222x on #194.
                        if tick - self._wizard_recall.get(cand, -10 ** 9) < WIZARD_RECALL_COOLDOWN:
                            continue
                        # v0.87.0 PAIR-EMBARK (operator): a guardian standing HERE ships
                        # out WITH the wizard in one embark — the party forms at the
                        # gate, not by luck in the field. Failing that, join a world
                        # that already holds a guardian; failing that, wait.
                        guard_here = next((u for u in here_avail if u != cand
                                           and role_of(here_chars.get(u) or {}, seats) == "guardian"),
                                          None)
                        # v0.88.0: two seats per world, and never into danger. When
                        # every safe under-seated world is party-full, flag it so its
                        # lowest-stat non-seat walks home and makes the slot.
                        safe_maps = [m for m in c_maps
                                     if not self._world_is_dangerous(m, tick)
                                     and seat_count.get(m, 0) < WIZARD_SEATS_PER_WORLD]
                        full_safe = [m for m in maps
                                     if m not in open_maps
                                     and not self._world_is_dangerous(m, tick)
                                     and seat_count.get(m, 0) < WIZARD_SEATS_PER_WORLD]
                        if not safe_maps and full_safe:
                            self._make_room[full_safe[0]] = tick
                        if (guard_here is not None and safe_maps
                                and fielded + len(inflight) + 2 <= world_cap):
                            uid, pair_with = cand, guard_here
                            target = min(safe_maps,
                                         key=lambda m: (threat(m), by_world.get(m, 0)))
                            break
                        # v0.87.1: wizards sit out DANGEROUS bands entirely. #175's
                        # undead cycle killed 9 wizards at y=2-16 — near home, escorts
                        # present — because the doctrine shipped them wherever a guardian
                        # stood. In a hostile band a wizard has nothing to gain (xp was
                        # 2.0/10k) and a pipeline to lose; guardians and fodder work the
                        # band, wizards wait it out.
                        w_opts = [m for m in c_maps if m in guardian_worlds
                                  and not self._world_is_dangerous(m, tick)
                                  and seat_count.get(m, 0) < WIZARD_SEATS_PER_WORLD]
                        if not w_opts:
                            continue          # no SAFE escorted world — the wizard waits
                        uid = cand
                        target = min(w_opts, key=lambda m: (threat(m), by_world.get(m, 0)))
                        break
                    if crole == "guardian" and not green:
                        # v0.87.0 (operator): "at least two guardians per world" — a
                        # guardian reinforces the open world with the FEWEST guardians
                        # (worlds under 2 first, then threat, then headcount).
                        uid = cand
                        target = min(c_maps,
                                     key=lambda m: (min(guardian_count.get(m, 0), 2),
                                                    threat(m), by_world.get(m, 0)))
                        break
                    # v0.92.0 GREEN-RECRUIT BAND GATE. Run #180, first hours: 16
                    # deaths, ALL fresh recruits, ALL shallow — vale's band 0 (the spawn
                    # strip is itself a numbered band strip) rolled a chaser pit
                    # (lava_ant x8, spider_brown x4, delver x2; chaser_score ~0.93) and
                    # level-1 unarmed replacements from the #179 refill walked straight
                    # into it and were run down fleeing (11/16). Zero were fodder by
                    # choice — the doctrine wasn't the cause, the door was. Mirror of
                    # the 0.87.1 wizard gate: a GREEN char (level<=1 AND bare hands)
                    # only embarks into non-dangerous worlds; if none is open it waits
                    # in the village exactly as a gated wizard does. Fodder is exempt
                    # (sacrifice doctrine, operator-directed) and so is anyone armed or
                    # level 2+ — this gate is about newborn legs vs chaser speed, not
                    # about avoiding fights.
                    g_opts = ([m for m in c_maps
                               if not self._world_is_dangerous(m, tick)]
                              if green else c_maps)
                    if not g_opts:
                        continue          # every open world is hot — the recruit waits
                    uid = cand
                    # v0.99.1: ingot-hungry -> route a MINE-WORTHY gatherer to the ORE
                    # world, else safest/least-crowded. #191 showed the flaw in v0.99.0:
                    # sending BARE foragers to the more-dangerous mines just churned them
                    # (embark -> hurt -> flee home; median 38-tick stints, one char
                    # embarked 58x) — they cannot hold the field to actually mine. So only
                    # a char that can SURVIVE the mines mines it: FODDER (expendable,
                    # gate-exempt, bold — exactly this class's job) or an ARMED char. A
                    # bare forager stays on the safer surface. Wizards never reach this
                    # branch (their own escort/band-gated branch runs first), so the ore
                    # dispatch can never send one into the mines.
                    ore_w = self._ore_world(bot)
                    mine_worthy = (crole == "fodder"
                                   or bool((cch or {}).get("equipment", {}).get("hand")))
                    if (ore_w is not None and ore_w in g_opts
                            and self._ingot_hungry(guild) and mine_worthy):
                        target = ore_w
                    else:
                        target = min(g_opts, key=lambda m: (threat(m), by_world.get(m, 0)))
                    break
                if uid is None:
                    return []
                self._embark_at[uid] = tick
                self._scout_sent[target] = tick   # v0.106.1: this world has eyes en route
                if pair_with is not None:
                    self._embark_at[pair_with] = tick
                    return [self._village_act(
                        bot, None, {"action": "embark", "map": target,
                                    "char_uids": [pair_with, uid]},
                        f"pair-embarking guardian {pair_with} + wizard {uid} to {target} "
                        f"— the party forms at the village gate")]
                return [self._village_act(
                    bot, None, {"action": "embark", "map": target,
                                "char_uids": [uid]},
                    f"embarking {uid} to {target} (safest: threat "
                    f"{round(threat(target), 2)}, {by_world.get(target, 0)} of us there)")]

        return []

    # -- field: per-character scored decision ---------------------------------

    def act(self, bot: "Any", char: dict[str, Any], frame: dict[str, Any],
            ctx: FieldContext, trace: DecisionTrace) -> None:
        uid = char["char_uid"]
        # v0.109.3/v0.110.3: EVIDENCE-BASED UNGHOSTING, render-distrust edition.
        # 0.109.3 popped the quarantine on ANY field sighting — and run #214's storm
        # (3,654 not_in_village) proved the server can render a RETURNED char frozen
        # in its old world (pos pinned, stamina 64 of a 56 max) for thousands of
        # ticks: each ghost render "proved life", the bot re-commanded a move, the
        # error re-stamped, one per tick. A sighting now counts only when the char's
        # STATE CHANGES between sightings (pos/stamina/hp — a live char moves within
        # ticks; a frozen render never does). A distrusted render gets NO actions;
        # the 600-tick GHOST_TTL expiry remains the bounded escape for a genuinely
        # motionless char (cost: one re-probe per TTL, never a storm).
        if uid in self._ghosted:
            _cur = (tuple(char["pos"]), char.get("stamina"), char.get("hp"))
            _prev = self._ghost_seen.get(uid)
            if _prev is not None and _prev != _cur:
                self._ghosted.pop(uid, None)
                self._ghost_seen.pop(uid, None)
            elif bot.tick - self._ghosted.get(uid, 0) < GHOST_TTL:
                self._ghost_seen[uid] = _cur
                trace.observe("quarantined — frozen render distrusted, no commands")
                trace.consider(None, 1.0, "ghost render; wait for real state change")
                return
            else:
                self._ghosted.pop(uid, None)      # TTL expiry: one re-probe allowed
                self._ghost_seen.pop(uid, None)
        if char.get("craft"):
            # A craft (brew/smelt/forge) occupies the character; any other action
            # is rejected with `crafting`, and moving/embarking abandons the work.
            trace.observe(f"crafting ({char['craft'].get('ticks_left')} ticks left) — busy")
            trace.consider(None, 1.0, "crafting in progress; wait it out")
            return
        pos = tuple(char["pos"])
        hp, max_hp = char.get("hp", 0), char.get("max_hp", 1)
        stamina = char.get("stamina", 0)
        self._stat_total[uid] = self._stat_sum(char)
        self.note_char(char)                      # v0.88.0: the seat ranking's ledger
        _seats = self.wizard_seats()
        my_role = role_of(char, _seats)           # v0.87.0: hoisted — used by combat,
        self._roles[uid] = my_role                # spacing, and the party block alike
        carry = char.get("carry", {"used": 0, "cap": 1})
        cfg = bot.config
        statuses = char.get("statuses", []) or []
        dot = any(s.get("kind") in DOT_KINDS for s in statuses)
        hurt = hp < max_hp * RETREAT_HP or dot
        # v0.62.0: OR the server's own verdict. Our test counts SLOTS while capacity is
        # spent in BULK, so a character with two free slots that cannot take a bulk-3 item
        # is refused by the server while reading as "not full" here -- run #137 lost 1,164
        # pickups to exactly that gap, all in carry state (19, 21). `overburdened` arrives
        # as an EVENT rather than an action_error, which is why no error query ever showed
        # it. Trust the refusal over the arithmetic.
        server_full = bot.recently_overburdened(uid)
        full = carry["used"] >= carry["cap"] - 1 or server_full
        # Heading-home latch (v0.16.0): a full char commits to walking home and
        # stays committed — looting suppressed — until it is light again, so it
        # never re-grabs a shed item off its own tile. Hysteresis: enter at full
        # (cap-1), leave only once the village has sold it down to <= half cap.
        if full:
            self._homing.add(uid)
        elif carry["used"] <= carry["cap"] * HOME_CLEAR_FRAC:
            self._homing.discard(uid)
        homing = uid in self._homing
        # Don't walk onto other characters OR monsters.
        blocked = ctx.bodies | set(ctx.enemies)
        # v0.103.0: hoisted from the retreat block (was v0.23.0, computed ~650 lines
        # down). An un-healed char (no potion_red) is capped at POISON_SAFE_DEPTH —
        # the retreat block turns it home from y>=cap at 2.5. But the gather block
        # above offers loot/gold/chest steps at 4.0-5.0 with NO depth check, so a
        # loot tile just past the cap out-scores the home-retreat: the char steps
        # deeper for loot, the safe-depth rule turns it back, and the two alternate
        # every tick at the boundary — the "line dance" (run #195, c19457 at y12/13).
        # Gating gather steps on the SAME threshold the retreat uses stops the pull
        # past the cap, so an un-healed char at the boundary heads home decisively.
        heals = sum(1 for i in char.get("inventory", []) or []
                    if i.get("kind") == "potion_red")
        # v0.107.0 DEPTH IS A BUDGET, NOT A BOOLEAN. The 0.106.0 heal-release let any
        # healed char range without limit — and the arch-wizard (c19403, level 9, the
        # INT ladder's top) died at y=31 in the mines on #201: it spent its ONE potion
        # on a burn DOT deep, instantly becoming an un-healed char 31 rows from home,
        # and stamina-starved to death mid-retreat at y=28. A potion is single-use
        # margin; the range it buys must be a distance one potion can actually cover.
        # Each carried heal extends the cap by HEAL_DEPTH_BONUS rows (one potion ->
        # y < 28, which still covers the observed veins at 26-27, so ore flows; y=31
        # is barred). WIZARDS GET NO BONUS — the operator's standing directive is a
        # PROTECTED caster investment, and a wizard has no business hauling ore past
        # the safe line however many potions it holds.
        depth_cap = POISON_SAFE_DEPTH + (
            0 if my_role == "wizard" else HEAL_DEPTH_BONUS * heals)

        def deep_ok(step, _cap=depth_cap):
            """An outward STEP/GOAL is allowed only below this char's depth budget.
            STRICT `<` (v0.104.0): the retreat fires AT `y >= cap`, so landing ON the
            cap tile is landing on ground the retreat immediately vacates (the 0.103.0
            off-by-one dance). Gates EVERY idle/seek pull (gather, combat-seek,
            ride/vein seek, rally, frontier, trek, scout), never survival moves
            (dodge/spacing/escape step wherever safety is) and never the nuisance
            (its mission scores outrank the retreat, so it cannot dance)."""
            return step[1] < _cap

        # v0.109.4: the looted-home COMMITMENT clears on the causal conditions only —
        # REACHING THE VILLAGE (the stint's true end; cleared in the village routine)
        # or the world visibly refreshing (fresh spawns are a real reason to stop
        # walking). NOT on nearing the strip edge: the oracle's mirage config caught
        # the first draft clearing at y<=2, where the still-visible mirage re-pulled
        # the char to y9 in a 14-tile macro cycle the window detector cannot see.
        if uid in self._looted_home:
            if (getattr(bot, "refreshed_at", {}).get(frame.get("world"), -1)
                    > self._looted_home[uid]):
                self._looted_home.pop(uid, None)
        _committed_home = uid in self._looted_home

        # v0.96.0: nuisance upkeep — learn Will's positions, (re)designate a volunteer,
        # stand down when he leaves the vale. Cheap; runs for every vale char.
        self._nuisance_track(bot, char, uid, frame, bot.tick)
        # v0.30.0: melee predators (golem_stone/delver/boar/…) only hit when we're
        # ADJACENT, so also block the tiles next to them — pathing then routes around
        # their strike range instead of stepping into it (run #85: a full-HP char that
        # stepped next to a golem_stone took -15 and died).
        # v0.33.0: but do NOT wall chars off from CHESTS that merely sit by a predator.
        # Run #88 showed 0.32.0's block-everything-adjacent cratered chest-opens (-69%)
        # and income (-53%) at a constant undead level — chars couldn't reach chests
        # next to mobs. A chest is 1-21g PLUS loot (tomes 24-44g), easily worth one hit
        # + a dodge; a single ~2g coin is NOT worth stepping into a -15 golem swing, so
        # only chest-ACCESS tiles are exempted from the block (coins/loot beside a mob
        # stay blocked — but an underfoot coin is grabbed for free in the dodge below,
        # since standing there already incurs the hit). The char cracks the chest, then
        # the dodge steps it out next tick.
        chest_access = {n for c in ctx.containers for n in nav.neighbors(c)}
        # v0.84.0: strike-range tiles are kept as their OWN set too. `blocked` treats them
        # as walls, which is right for every opportunistic goal — but a cornered escape
        # needs them priced, not banned, so the planner can cross one on purpose.
        strike = set()
        for mp, en in ctx.enemies.items():
            if self._is_melee_predator(en.get("kind")):
                strike |= (set(nav.neighbors(mp)) - chest_access)
        blocked |= strike

        trace.observe(f"at {pos} hp {hp}/{max_hp} sta {stamina} "
                      f"carry {carry['used']}/{carry['cap']}"
                      + (f" statuses={[s.get('kind') for s in statuses]}" if statuses else ""))

        # Rest is always available (cost 0) and is the floor.
        trace.consider(None, REST_SCORE, f"rest (double regen); stamina {stamina}")

        def offer(action: dict[str, Any], score: float, why: str,
                  urgent: bool = False) -> None:
            name = action["action"]
            cost = self._cost(name, cfg)
            # Moves need headroom above the raw cost (v0.9.0): the frame we decide
            # on can be ~1 tick stale, so a step that looks affordable is rejected
            # not_enough_stamina when the server's live stamina is lower. A margin
            # keeps the char resting (double-rate regen) until the step is a safe
            # bet. Non-movement actions barely ever error on stamina — leave them
            # at the raw cost so combat/healing aren't throttled.
            # v0.34.0: an URGENT survival move (flee/dodge/retreat from a threat) skips
            # the margin — a possibly-bounced step is far better than resting adjacent
            # to a predator and dying. (Operator saw a low-stamina char sit and take
            # wolf hits: the 1.5x margin was starving its only escape.)
            if name in ("move", "ride") and not urgent:
                need = int(cost * MOVE_STAMINA_SAFETY)
            else:
                need = cost
            if stamina >= need:
                trace.consider(action, score, why)
            else:
                trace.observe(f"wanted {name} ({why}) but stamina {stamina} < ~{need}: resting")

        # v0.96.0: the nuisance's tour, as OFFERS — survival (added below at 8.0+) still
        # wins, so 'try not to die' holds by construction. Loot/deliver (6.0) outrank
        # ordinary gather (4.0); follow (3.6) fills an idle tick.
        self._nuisance_act(bot, char, uid, pos, frame, ctx, hp, max_hp, hurt, offer, trace)

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
            self._retreat(uid, pos, ctx, blocked, offer, 8.5, "hurt — walking home to heal",
                          urgent=True)
            # v0.42.0 DESPERATION ESCAPE: the retreat above only offers a KNOWN-walkable
            # homeward step. A hurt char boxed in by a predator PACK (every strike-range tile
            # is in `blocked`) or standing at the edge of explored ground frequently has its
            # ONLY clear tile on UNKNOWN terrain — which is_walkable refuses — so the retreat
            # offers nothing and the char RESTS and bleeds out. Traced live: run #99's vale
            # wolf-swarm cluster, 3 foragers rested at FULL stamina (48-56) with a clear-but-
            # unseen escape tile one step away and died (hp 13->9->5->1). When cornered like
            # this, a step onto a clear non-solid (incl. unseen) tile is strictly better than
            # resting: a wall just bounces the move (no worse than resting), floor lets the
            # char escape. Candidates exclude `blocked` (enemies, bodies, AND predator strike-
            # range) and known WALLS, so we never step INTO a strike tile — only out through a
            # gap. Prefer the tile FARTHEST from every visible enemy (break out of the pack),
            # tiebreak toward home (lower y). Scored 8.0 < the retreat (8.5) so a known homeward
            # step always wins; this fires ONLY when the retreat found none. Urgent (no stamina
            # margin) — a possibly-bounced step beats resting to death.
            # v0.84.0 PLANNED ESCAPE (the operator's mob-box screenshot, with corpses:
            # two wizards died boxed in on run #170 — one RESTED six ticks at full
            # stamina, one bounced the same doomed move four times). Danger becomes a
            # PRICE: strike-range tiles cost nav.AVOID_COST (~one eaten hit) instead of
            # being walls, so the router finds the least-dangerous corridor HOME and
            # crosses strike range once, on purpose, when that is the only way out.
            # Bodies and learned walls stay absolute. Scored 8.2: above the one-step
            # desperation (8.0), below the clean retreat (8.5) — a safe route still wins.
            esc_step = nav.weighted_step(pos, lambda p: p[1] == 0, ctx.known,
                                         blocked - strike, fresh=ctx.fresh, avoid=strike)
            if esc_step is not None:
                offer({"char_uid": uid, "action": "move",
                       "dir": nav.step_dir(pos, esc_step)}, 8.2,
                      "hurt & boxed in — planned escape through the least-dangerous "
                      "corridor (crossing strike range beats resting to death)",
                      urgent=True)
            esc = [n for n in nav.neighbors(pos)
                   if n not in blocked and ctx.known.get(n) not in nav.SOLID]
            if esc:
                def _enemy_dist(t: tuple[int, int]) -> int:
                    return min((abs(t[0] - q[0]) + abs(t[1] - q[1]) for q in ctx.enemies),
                               default=99)
                best = max(esc, key=lambda t: (_enemy_dist(t), -t[1]))
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, best)}, 8.0,
                      "hurt & cornered — desperation step to a clear tile (beats resting to death)",
                      urgent=True)
            return

        # v0.75.0 FLAVOUR TEXT. Offered here so a hurt or cornered character — which has
        # already returned above — never stops to talk, and scored one notch over REST so
        # the only thing it can ever displace is an idle rest tick. PEEKED, not taken: this
        # offer usually loses, and consuming the line here would spend the cooldown, and the
        # one event we had to talk about, on a tick where nothing was broadcast. The bot
        # commits when the action is actually sent.
        max_sta = char.get("max_stamina")
        rested = (max_sta is not None and stamina >= SAY_READY_FRAC * max_sta
                  and hp >= max_hp)
        chat = bot.chatter.peek(bot.tick, gold=getattr(bot, "guild_gold", None),
                                roster=len(frame.get("chars", []) or [])) if rested else None
        if chat is not None:
            offer({"char_uid": uid, "action": "say", "text": chat}, SAY_SCORE,
                  f"flavour text — saying {chat!r}; unlike a rest this also resets "
                  f"the unattended-recall timer")

        # --- v0.93.0 RIDE PROBE (wishlist top qualifier, operator-committed) --------
        # `ride` has never been issued by ANYONE on this server (0 events all-time).
        # Docs: from a `track` tile, ride {dir} slides to the rail's end at flat cost,
        # ramming whatever blocks it; ride_max_tiles is NOT in the live config, so the
        # cap is empirical. Slice 1 is ONE experiment per run, exploration-matrix
        # guarded: a healthy ARMED char (bare hands never probe — the green doctrine),
        # calm surroundings, standing ON a rail, riding toward an adjacent rail tile.
        # The error taxonomy is the payload: a clean slide, `missing_item` (operator's
        # minecart hypothesis), or anything else — every outcome teaches. Scored above
        # routine gathering so the once-per-run probe actually fires.
        # v0.93.1: the probe was UNREACHABLE as shipped — it waited for a char to already
        # be standing on a rail, which never happened (run #184: 0 sends; our armed chars
        # never crossed a track tile, all at mines y-shallow while the rails sit y12-82).
        # A passive experiment that no behaviour routes toward is the starvation trap.
        # _ride_prober_ready factors the gate so seek and fire cannot drift; the seek
        # (below, in the safe non-homing branch) walks a qualified prober to the nearest
        # known rail, and this fires when it arrives.
        if (self._ride_prober_ready(char, pos, hp, max_hp, stamina, ctx)
                and ctx.known.get(pos) == "track"):
            for d, nxt in (("N", (pos[0], pos[1] - 1)), ("S", (pos[0], pos[1] + 1)),
                           ("E", (pos[0] + 1, pos[1])), ("W", (pos[0] - 1, pos[1]))):
                if ctx.known.get(nxt) == "track":
                    self._ride_probed = True     # spent on OFFER, not send: one per run
                    print(f"[ride] probe: {uid} riding {d} from {pos}", flush=True)
                    offer({"char_uid": uid, "action": "ride", "dir": d},
                          RIDE_PROBE_SCORE,
                          f"[probe] first-ever ride — {d} along the rail from {pos}; "
                          f"outcome (slide/error/ram) is the experiment's payload")
                    break

        # --- DRASTIC undead-flee (v0.25.0): mood-driven. If a THREAT mob (poison
        # undead) is within FLEE_RADIUS, do NOT loot or fight — run to the village.
        # Snatch only a coin already underfoot (instant, banked, worth one tick) on
        # the way out, and fight ONLY if cornered with no escape. A homing char is
        # already walking home, so it is exempt. In a wildlife band no THREAT is near
        # and the gold-rush below runs normally — the behaviour adapts to the band. ---
        threats = [p for p, en in ctx.enemies.items() if en.get("kind") in THREAT_KINDS]
        # Record this world's undead level for safe-world routing at embark (v0.26.0).
        world = frame.get("world")
        if world:
            frac = (len(threats) / len(ctx.enemies)) if ctx.enemies else 0.0
            self._world_threat[world] = (frac, bot.tick)
            # Danger is the MAX seen within THREAT_TTL, not the instantaneous view. Written
            # naively (overwrite every tick) a character standing somewhere quiet resets the
            # world to "safe" on the spot — which defeats a STANDING formation entirely, since
            # the whole point is to be together BEFORE anything appears. The timestamp is
            # refreshed only when danger is actually observed, so a genuinely emptied world
            # still ages out and gets re-scouted rather than being feared forever.
            pred_n = sum(1 for en in ctx.enemies.values()
                         if self._is_melee_predator(en.get("kind")))
            prev = self._world_danger.get(world)
            fresh = prev if (prev and bot.tick - prev[2] < THREAT_TTL) else None
            if frac or pred_n:
                self._world_danger[world] = (
                    max(frac, fresh[0]) if fresh else frac,
                    max(pred_n, fresh[1]) if fresh else pred_n,
                    bot.tick)
            elif fresh is None and prev is not None:
                del self._world_danger[world]        # expired and nothing seen: forget it
        if threats and not homing:
            near = any(abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= FLEE_RADIUS for p in threats)
            if near:
                trace.observe(f"undead within {FLEE_RADIUS} — evade: flee (grab safe gold only)")
                if pos in ctx.gold:            # one grab of instant banked gold
                    offer({"char_uid": uid, "action": "pickup"}, 8.0,
                          "snatching the coin underfoot, then fleeing")
                # v0.26.0: still grab a coin that lies AWAY from the undead — one that
                # is farther from every threat than we are, so fetching it moves us
                # toward safety AND banks gold. Recovers income during an undead band
                # without re-engaging the swarm. (Above the plain flee, below the
                # underfoot grab.)
                my_d = min(abs(p[0] - pos[0]) + abs(p[1] - pos[1]) for p in threats)
                safe_gold = {c for c in ctx.gold
                             if min(abs(c[0] - p[0]) + abs(c[1] - p[1]) for p in threats) > my_d}
                if safe_gold and pos not in ctx.gold:
                    step = self._step(pos, lambda p: p in safe_gold, ctx, blocked)
                    if step:
                        offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                              7.5, "grabbing a coin in the safe direction while evading",
                              urgent=True)
                # Flee to the village (handles the y==0 edge by stepping off it).
                self._retreat(uid, pos, ctx, blocked, offer, 7.0,
                              "undead near — fleeing to the village", urgent=True)
                # Cornered fallback (scored below the flee): if the retreat is blocked
                # there is no escape step, so fight the weakest adjacent enemy out.
                adj_e = [p for p in nav.neighbors(pos) if p in ctx.enemies]
                if adj_e:
                    w = min(adj_e, key=lambda p: ctx.enemies[p].get("hp_frac", 1.0))
                    offer({"char_uid": uid, "action": "attack", "target": list(w)},
                          6.9, "cornered by undead — fighting out (fallback)")
                return

        # --- Melee-predator DODGE (v0.31.0): golem/delver/boar/spider/… hit hard ONLY
        # in melee, and some drift onto a stationary/looting char (0.30.0's block stops
        # US stepping adjacent, but not the MOB). If one is ADJACENT, step to the tile
        # that maximises distance from every melee predator — do NOT fight it (attacking
        # a delver is a fast death) and do NOT linger to loot. Scoped to dist 1, so the
        # wildlife worlds stay lootable otherwise (this is NOT the radius-4 undead flee).
        preds = [p for p, en in ctx.enemies.items() if self._is_melee_predator(en.get("kind"))]

        # --- v0.41.0 COMBAT-SEEK (A): fight a LONE predator that came adjacent. A DEVELOP-mode
        # char (armed + comfortably healthy + stamina to fight) that has a single melee predator
        # ADJACENT and no swarm nearby ATTACKS it for XP instead of dodging (below). It was going
        # to be adjacent regardless; armed and healthy it wins the trade, and if it drops below
        # the retreat line the hurt-block bails it out next tick. Undead never reach here (the
        # flee returned above); a swarm (>=2 melee predators within reach) skips this and falls
        # through to the dodge. This is what turns the 0.40 arm-up into actual leveling. ---
        armed = (char.get("equipment") or {}).get("hand") is not None
        # v0.83.1: the caster-designate never trades hits with predators — benign
        # wildlife XP still flows, but the dodge-override and the closing seek are for
        # characters whose death costs a club, not a pipeline.
        caster = "int" in (char.get("gifts") or [])
        # v0.87.0: fodder trades hits down to DEVELOP_HP_FODDER — it is the one class
        # whose death is budgeted. (It is usually bare-handed since no coin buys it a
        # weapon, but looted and forged gear still equips for free.)
        hp_bar = DEVELOP_HP_FODDER if my_role == "fodder" else DEVELOP_HP
        # v0.114.0 (operator: "protect my wizards"): the caster check alone had a hole —
        # wizard SEATS are rank-chosen (int gift preferred, not required), so a non-gifted
        # seat-holder passed `not caster` and would trade hits with predators. The seat is
        # the protection contract, so the ROLE gates too.
        develop = (armed and not homing and not caster and my_role != "wizard"
                   and hp >= max_hp * hp_bar and stamina >= DEVELOP_STAMINA)
        hunt = (armed and not homing and not caster and stamina >= DEVELOP_STAMINA
                and hp >= max_hp * (DEVELOP_HP_FODDER if my_role == "fodder" else HUNT_HP))
        near_preds = [p for p in preds
                      if abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= COMBAT_SEEK_RADIUS]
        if develop and len(near_preds) < COMBAT_SWARM:
            adj_pred = [p for p in nav.neighbors(pos) if p in preds]
            if adj_pred:
                target = min(adj_pred, key=lambda p: ctx.enemies[p].get("hp_frac", 1.0))
                kind = ctx.enemies[target].get("kind", "predator")
                trace.observe(f"develop: fighting a lone {kind} for XP (armed, healthy) — not dodging")
                offer({"char_uid": uid, "action": "attack", "target": list(target)},
                      7.6, f"develop: fighting a lone {kind} for XP (not dodging)")
                return

        melee_adj = [p for p in nav.neighbors(pos) if p in preds]
        if melee_adj:
            kind = ctx.enemies[melee_adj[0]].get("kind", "melee predator")
            trace.observe(f"a {kind} is adjacent — dodging (not fighting)")
            # v0.33.0: harvest the value we came for BEFORE stepping away — one grab is
            # worth a hit (banked gold is death-proof), and the dodge takes us out next
            # tick. Scored above the dodge (7.3) so grab/crack wins this tick.
            if pos in ctx.gold or pos in ctx.loot:
                offer({"char_uid": uid, "action": "pickup"}, 7.5,
                      f"grabbing the loot underfoot before dodging the {kind}")
            box = next((p for p in nav.neighbors(pos) if p in ctx.containers), None)
            if box:
                offer({"char_uid": uid, "action": "open", "target": list(box)}, 7.5,
                      f"cracking the adjacent chest before dodging the {kind}")
            def _pred_dist(t: tuple[int, int]) -> int:
                return min(abs(t[0] - q[0]) + abs(t[1] - q[1]) for q in preds)
            cands = [t for t in nav.neighbors(pos)
                     if nav.is_walkable(t, ctx.known, blocked) and _pred_dist(t) > _pred_dist(pos)]
            if cands:
                best = max(cands, key=_pred_dist)
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, best)},
                      7.3, f"dodging an adjacent {kind}", urgent=True)
            else:
                # boxed in (all escape tiles border a predator): retreat homeward — still
                # better than standing to be hit. _retreat handles the y==0 edge.
                self._retreat(uid, pos, ctx, blocked, offer, 7.2,
                              f"cornered by a {kind} — retreating", urgent=True)
            return

        # --- v0.117.0 BUNKER RETREAT: the server is unhealthy (sustained frame lag
        # or poison storm — see bot._health_step) and this character is in the field.
        # Walk home NOW, while actions still land, rather than being stranded
        # paralyzed when the lag deepens (run 229: 8 stranding deaths). Scored 6.0:
        # above every gather/seek (gold beeline 5.0) so income never delays the
        # recall, below the survival ladder (dodge 7.3 / develop-attack 7.6 / hurt
        # retreat 8.5) so getting home never overrides staying alive on the way.
        if getattr(bot, "server_health", lambda: "ok")() != "ok":
            self._retreat(uid, pos, ctx, blocked, offer, 6.0,
                          "bunker: server unhealthy — returning to the village")

        # --- Melee-predator PROACTIVE SPACING (v0.37.0, anti-stuck): the death
        # analysis (postmortem #92) found ~80% of our deaths are STUCK chars, and the
        # accumulated-map diagnostic REFUTED terrain-cornering (only 8/168 death-neighbours
        # were known walls) — the real failure is chars that REST or scout-wander while a
        # melee predator closes from dist 2. The dist-1 dodge above fires too late: a
        # same-speed chaser that reaches adjacency lands a hit and often stays adjacent.
        # But every chaser moves at ~0.22 tiles/tick (bestiary), so a char that keeps
        # MOVING outruns it. So if a melee predator is within PRED_SPACING_RADIUS (2) —
        # not adjacent (handled above) — step to the tile that maximises distance from
        # every near predator. Scored 3.0: ABOVE aimless scout(1.0)/frontier(2.0-2.5) so a
        # char steps away instead of idling/wandering into it, but BELOW real gathering
        # (loot 4.0 / gold 5.0 / pickup 6.0) so a grab is still worth one tick (banked gold
        # is death-proof; this fires next tick). Scoped to MELEE predators (benign wildlife
        # is excluded via _is_melee_predator) so wildlife bands stay lootable. ---
        if not homing:
            near_preds = [p for p in preds
                          if abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= PRED_SPACING_RADIUS]
            if near_preds:
                def _sp_dist(t: tuple[int, int]) -> int:
                    return min(abs(t[0] - q[0]) + abs(t[1] - q[1]) for q in near_preds)
                cands = [t for t in nav.neighbors(pos)
                         if nav.is_walkable(t, ctx.known, blocked) and _sp_dist(t) > _sp_dist(pos)]
                if cands:
                    best = max(cands, key=_sp_dist)
                    kind = ctx.enemies[near_preds[0]].get("kind", "melee predator")
                    # v0.38.0: is THIS band severe? undead fraction (poison-DoT bands are the
                    # lethal ones) or a melee-predator swarm. `threats` (undead here) and `preds`
                    # were computed above. In a calm band, spacing yields to gather/explore.
                    # v0.39.0: the char's ROLE biases the threshold — a Guardian (veteran)
                    # disengages early; a Forager (recruit) works a denser band for income.
                    undead_frac = (len(threats) / len(ctx.enemies)) if ctx.enemies else 0.0
                    # v0.39.1: a Forager only EARNS its bold thresholds when there is value to
                    # gather in view (gold/loot/chest). In a coin-dry band there's no income
                    # upside to the risk, so it reverts to the cautious (Guardian) thresholds and
                    # plays safe — fixing the 0.39 flaw where bold foragers died for nothing in
                    # barren bands (re-feeding the death->recruit drain). Guardians are always
                    # cautious (protect the XP investment).
                    role = my_role
                    has_value = bool(ctx.gold or ctx.loot or ctx.containers)
                    if (role == "forager" and has_value) or role == "fodder":
                        # fodder is bold UNCONDITIONALLY — barren band or not, its job
                        # is to be out there soaking risk the real roster should not
                        uf, dn = UNDEAD_SEVERE_FORAGER, MELEE_DENSE_FODDER if role == "fodder" else MELEE_DENSE_FORAGER
                    else:
                        uf, dn = UNDEAD_SEVERE_GUARDIAN, MELEE_DENSE_GUARDIAN
                    severe = undead_frac >= uf or len(preds) >= dn
                    score = SPACE_SCORE_SEVERE if severe else SPACE_SCORE_CALM
                    band = "severe" if severe else "calm"
                    label = role if (role != "forager" or has_value) else "forager(barren)"
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, best)},
                          score, f"{label}: a {kind} is {_sp_dist(pos)} away ({band} band) — spacing off",
                          urgent=True)

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
        # v0.62.0: shed on the SERVER's refusal too, not only when our slot arithmetic says
        # the pack is full. Without this a refused character stops looting (via `full`) but
        # never lightens, so it walks home carrying the load that caused the refusal instead
        # of dropping the least-useful thing and carrying on.
        if carry["used"] >= carry["cap"] or server_full:
            shed = self._shed_item(char)
            if shed is not None:
                offer({"char_uid": uid, "action": "drop", "item_id": shed}, 8.0,
                      "overburdened — dropping loot to regain mobility")

        if homing:
            self._retreat(uid, pos, ctx, blocked, offer, 7.5,
                          "pack full — heading home to sell")

        # Pursue loot only when NOT heading home (v0.16.0): a homing char that
        # grabs or chases loot re-fills — and would re-grab the item it just shed
        # off its own tile (the 0.15.0 thrash). It should walk its haul home.
        productive = False   # v0.36.0: did anything worth staying for turn up this tick?
        # v0.48.1 COHESION CONTEXT, computed once and used twice: to bias which loot we
        # walk toward (below) and, failing that, as a standalone move when there is nothing
        # to gather at all. `form_up` is the whole gate — a dangerous world, an ally to
        # form on, and a gap wider than the hysteresis threshold.
        allies = [tuple(c["pos"]) for c in frame.get("chars", []) or []
                  if c.get("char_uid") != uid and c.get("pos")]
        # v0.85.0 THE ESCORT. Field frames carry every co-fielded char's gifts, so both
        # sides of the pact read the frame directly. The wizard side: no guardian within
        # ESCORT_NEAR -> walk home (6.0 preempts all income; survival still outranks it).
        # The guardian side: a wizard drifting past ESCORT_PULL is closed on at 4.2 —
        # escort duty beats one more coin, never beats staying alive.
        in_party = False
        if not homing:
            # v0.87.0 THE DETAIL (operator: wizards may cluster into a single party; "the
            # wizard with the most int needs to be protected by the other wizards too").
            # The per-world party square is the ARCH-WIZARD'S TILE — the highest-INT
            # wizard present (uid tiebreak, so every member computes the same anchor).
            # Guardians AND lesser wizards hold formation on it; the arch-wizard chases
            # nobody; wizards with no guardian in the world go home, arch or not.
            chars_here = [c for c in frame.get("chars", []) or []
                          if c.get("char_uid") and c.get("pos")]
            wizards = [c for c in chars_here if role_of(c, _seats) == "wizard"]
            has_guardian = any(role_of(c, _seats) == "guardian" for c in chars_here)
            def _int_of(c):
                return (c.get("stats") or {}).get("int", 0)
            arch = max(wizards, key=lambda c: (_int_of(c), c["char_uid"])) if wizards else None
            # v0.88.0 MAKE ROOM: the village flagged this world because a chosen wizard
            # is waiting for a slot in it. The LOWEST-STAT non-seat character here walks
            # home (deterministic: stat sum, uid tiebreak — every member computes the
            # same victim, so exactly one leaves).
            room_tick = self._make_room.get(ctx.world)
            if (room_tick is not None and bot.tick - room_tick < MAKE_ROOM_TTL
                    and my_role != "wizard"):
                pool = [(sum(v for v in (c.get("stats") or {}).values()
                             if isinstance(v, int)), c.get("char_uid"))
                        for c in chars_here if c.get("char_uid") not in _seats]
                if pool and min(pool)[1] == uid:
                    self._retreat(uid, pos, ctx, blocked, offer, WIZARD_FALLBACK_SCORE,
                                  "recalled — making room for a chosen wizard in this "
                                  "world")
            if my_role == "wizard":
                if self._world_is_dangerous(ctx.world, bot.tick):
                    self._wizard_recall[uid] = bot.tick   # v0.102.0: start the re-embark cooldown
                    self._retreat(uid, pos, ctx, blocked, offer, WIZARD_FALLBACK_SCORE,
                                  "band too dangerous for the wizard — the pipeline "
                                  "waits out the cycle at home")
                elif not has_guardian:
                    self._retreat(uid, pos, ctx, blocked, offer, WIZARD_FALLBACK_SCORE,
                                  "no guardian to party with — falling back to the "
                                  "village until one ventures out with me")
                elif arch is not None and arch.get("char_uid") == uid:
                    in_party = True          # the protected asset holds the square
                else:
                    in_party = True
                    self._hold_formation(uid, pos, tuple(arch["pos"]), ctx, blocked,
                                         offer, "a lesser wizard shields the arch-wizard")
            elif my_role == "guardian" and arch is not None:
                in_party = True
                self._hold_formation(uid, pos, tuple(arch["pos"]), ctx, blocked,
                                     offer, "guardians protect the INT investment")
        form_up = (bool(allies) and not homing and not in_party
                   and self._world_is_dangerous(ctx.world, bot.tick))
        rally = False
        centre_gap = 0
        if form_up:
            _gap = min(abs(pos[0] - a[0]) + abs(pos[1] - a[1]) for a in allies)
            # Hysteresis: once closing, keep closing until inside HOLD.
            form_up = _gap > (COHESION_HOLD if uid in self._cohering else COHESION_PULL)
            if not form_up:
                self._cohering.discard(uid)
            else:
                # v0.73.0: the standalone rally is gated on the distance to the CENTRE,
                # because the centre is what _cohesion_step walks toward. Gating it on the
                # nearest ally (what 0.72.0 shipped) measures one thing and moves toward
                # another: a character 5 tiles from an ally would start a rally to a centre
                # 20 tiles away and never arrive. The centre here is the ALLIES' centroid,
                # self excluded, matching the helper exactly — the two must agree or the
                # gate and the stopping rule disagree about when we have arrived.
                _cx = sum(a[0] for a in allies) // len(allies)
                _cy = sum(a[1] for a in allies) // len(allies)
                centre_gap = abs(pos[0] - _cx) + abs(pos[1] - _cy)
                rally = COHESION_HOLD < centre_gap <= COHESION_RANGE
                if not rally:
                    self._cohering.discard(uid)
        if not homing:
            if pos in ctx.loot or pos in ctx.gold:
                offer({"char_uid": uid, "action": "pickup"}, 6.0, "loot/gold underfoot — grab it")
                productive = True
            else:
                # GOLD-RUSH (v0.24.0): grabbing & stockpiling gold is the priority.
                # Beeline to GOLD coins first — they are instant, banked to the
                # treasury (death-proof), ~half our income, and only ~3% are tied to
                # a kill (so they need no fighting). Then to chests (direct 1-21g +
                # loot). Then ordinary loot.
                # v0.105.0: deep_ok gates the GOAL, not just the step. Run #197: gating
                # only steps relocated the line dance one tile shallower — at cap-2 the
                # first step toward a past-cap chest is legal, at cap-1 it is not, so the
                # offer flickered on/off with position and the char thrashed y10<->y11
                # while the village kept re-embarking it (1051 embarks). A goal an
                # un-healed char may not reach must generate NO pull at any distance;
                # then "looted-out" is a true statement and the char goes home once.
                gstep = self._step(pos, lambda p: p in ctx.gold and deep_ok(p), ctx, blocked)
                if gstep and _committed_home:
                    gstep = None       # v0.109.4: committed to the looted-out walk
                if gstep and not deep_ok(gstep):
                    gstep = None
                if gstep:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, gstep)},
                          5.0, "beeline to a gold coin (instant banked gold)")
                    productive = True
                cstep = self._step(pos, lambda p: deep_ok(p) and
                                   any(n in ctx.containers for n in nav.neighbors(p)),
                                   ctx, blocked)
                if cstep and _committed_home:
                    cstep = None       # v0.109.4: committed to the looted-out walk
                if cstep and not deep_ok(cstep):
                    cstep = None
                if cstep:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, cstep)},
                          4.5, "beeline to a chest (direct gold + loot)")
                    productive = True
                # v0.48.1: while out of position in a dangerous world, prefer loot that
                # lies near an ally — gathering and forming up at the same time, at the
                # same score, instead of cohesion losing this tick and every other one.
                loot_goal, loot_why = ctx.loot, "moving toward loot"
                if form_up:
                    toward = {q for q in ctx.loot
                              if min(abs(q[0] - a[0]) + abs(q[1] - a[1]) for a in allies)
                              <= COHESION_PULL
                              and abs(q[0] - pos[0]) + abs(q[1] - pos[1]) <= COHESION_DETOUR}
                    if toward:
                        loot_goal = toward
                        loot_why = "moving toward loot near an ally (forming up as we work)"
                lstep = self._step(pos, lambda p: p in loot_goal and deep_ok(p), ctx, blocked)
                if lstep and _committed_home:
                    lstep = None       # v0.109.4: committed to the looted-out walk
                if lstep and not deep_ok(lstep):
                    lstep = None
                if lstep:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, lstep)},
                          4.0, loot_why)
                    productive = True

            # v0.41.0 COMBAT-SEEK (B): with no better income underfoot, a DEVELOP char CLOSES on
            # benign WILDLIFE (0-dmg mobs) to farm free XP — step to a tile adjacent to the
            # nearest wildlife within COMBAT_SEEK_RADIUS, and the 8.0 adjacent-attack finishes it
            # next tick. Scored 3.5: BELOW real gathering (gold 5.0 / chest 4.5 / loot 4.0 — free
            # income still comes first) but ABOVE frontier(2.5)/scout(1.0), so leveling beats
            # aimless wandering. Only wildlife is sought (its neighbour tiles are walkable);
            # predators are fought only when they reach us (block A), never chased into.
            if hunt:
                wild = {p for p, en in ctx.enemies.items()
                        if en.get("kind") in WILDLIFE_SAFE
                        and abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= WILDLIFE_SEEK_RADIUS}
                if wild:
                    wstep = self._step(pos, lambda p: deep_ok(p) and
                                       any(n in wild for n in nav.neighbors(p)),
                                       ctx, blocked)
                    if wstep and not deep_ok(wstep):
                        wstep = None
                    if wstep:
                        offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, wstep)},
                              3.5, "develop: closing on wildlife to farm XP")
                        productive = True
            # --- v0.114.0 PROPOSAL B: engage a LONE beatable predator. Gated on `develop`
            # (the 0.7 comfort margin — a predator fight is entered with room to lose two
            # hits, unlike the 0.6 wildlife bar) and on the develop-block's own swarm gate
            # via the loneness filter: the TARGET must have no second predator within
            # COMBAT_SEEK_RADIUS of it, or we'd arrive into the exact pair the swarm gate
            # exists to refuse. Scored 3.3: below wildlife (3.5 — free xp first), ABOVE
            # spacing (3.0) so approach beats back-away and the pair can't tug-of-war;
            # on arrival the develop-attack (7.6) outranks the adjacent-dodge (7.3), and
            # if hp dips below the bar mid-fight `develop` flips false and the ordinary
            # dodge/retreat ladder owns the exit. Wizards never enter: `develop` now
            # excludes the role outright (the gate fix above).
            # NB: near_preds was re-bound by the spacing block (radius 2); the swarm
            # gate here needs the develop-block's meaning (COMBAT_SEEK_RADIUS around US),
            # so compute it locally rather than trusting whichever binding survived.
            eng_near = [p for p in preds
                        if abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= COMBAT_SEEK_RADIUS]
            if develop and len(eng_near) < COMBAT_SWARM:
                lone = {p for p, en in ctx.enemies.items()
                        if en.get("kind") in ENGAGE_KINDS
                        and abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= ENGAGE_SEEK_RADIUS
                        and not any(q != p and self._is_melee_predator(ctx.enemies[q].get("kind"))
                                    and abs(q[0] - p[0]) + abs(q[1] - p[1]) <= COMBAT_SEEK_RADIUS
                                    for q in ctx.enemies)}
                if lone:
                    # The v0.30 strike-halo marks every predator-adjacent tile as a
                    # wall, which is right for every seek EXCEPT this one — walking
                    # into strike range of the TARGET is the entire point of an
                    # engagement. Un-wall only the target's own halo; the loneness
                    # filter already guarantees no other predator within
                    # COMBAT_SEEK_RADIUS of it, so no foreign halo overlaps.
                    eng_blocked = blocked - {n for p in lone
                                             for n in nav.neighbors(p)}
                    estep = self._step(pos, lambda p: deep_ok(p) and
                                       any(n in lone for n in nav.neighbors(p)),
                                       ctx, eng_blocked)
                    if estep and not deep_ok(estep):
                        estep = None
                    if estep:
                        kinds = {ctx.enemies[p].get("kind") for p in lone}
                        offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, estep)},
                              3.3, f"engage: closing on a lone beatable {'/'.join(sorted(k for k in kinds if k))} for XP")
                        productive = True

        # Gather/explore only when NOT heading home (v0.16.0): a homing char that
        # opens a container spills loot it won't grab, and scouting/frontier-pushing
        # walks it away from the village — it should just retreat (defence via the
        # adjacent-attack offer above still applies).
        if not homing:
            box = next((p for p in nav.neighbors(pos) if p in ctx.containers), None)
            if box:
                offer({"char_uid": uid, "action": "open", "target": list(box)},
                      7.0, "cracking a chest — direct gold + loot (gold-rush v0.24.0)")

            # v0.44.0 FORGE-TO-ARM probe (slice 1): opportunistic terrain HARVEST. A safe,
            # non-homing char ALREADY ADJACENT to a breakable resource tile ATTACKS it to
            # harvest raw materials (tree -> lumber, vein -> ore) instead of ignoring it as
            # scenery. Adjacent-only so there is ZERO extra pathing/danger — a predator near
            # or adjacent already returned above (dodge/spacing), so reaching here is safe to
            # spend the few ticks a break costs. Needs no weapon (it's gathering, not combat),
            # so bare chars harvest too. Scored 3.3: below real gathering (loot 4.0 / wildlife-
            # seek 3.5) and adjacent-attack (8.0), above frontier(2.5)/scout(1.0) — it fires
            # only when nothing better is underfoot. Feeds the craft chain we already run
            # (smelt ore->ingot; the forge step + arming come in later slices).
            # v0.68.0: LEARN A SPELL FORM IN THE FIELD. The learn step lived only in
            # village(), and run #146 showed what that costs: the character holding
            # `tome_field` spent all 10,933 of its tome-carrying frames in vale and never
            # once went home, so it never learned and never even earned the refusal that
            # v0.67.0's INT investment keys on. Nothing in the chain fires for a character
            # that does not return.
            #
            # `use` is not a village verb — it is how potions are drunk in the field. Scored
            # 3.0: below adjacent harvest (3.3) and everything urgent, above the frontier
            # push (2.5), so it fills an idle tick and never competes with survival. Reached
            # only inside the safe, non-homing branch, so a character in trouble ignores it.
            tome = self._tome_to_learn(uid, char.get("inventory") or [],
                                       self._can_learn(char))
            if tome is not None:
                self._using[uid] = tome["kind"]
                offer({"char_uid": uid, "action": "use", "item_id": tome["item_id"]}, 3.0,
                      f"learning {tome['kind']} in the field — a spell FORM, and this "
                      f"character may never walk home")
                productive = True

            # v0.93.1: route a qualified prober to the nearest known rail so the
            # once-per-run ride experiment can actually run (slice 1 sat unreachable).
            # Only when NOT already on a rail (the fire offer handles that) and a
            # rideable rail is known within RIDE_SEEK_RANGE. Below harvest/gather, so a
            # prober still takes free income first; it only walks to a rail on a tick it
            # would otherwise spend wandering.
            if (self._ride_prober_ready(char, pos, hp, max_hp, stamina, ctx)
                    and not self._is_rideable_rail(ctx, pos)):
                rstep = self._rail_step(pos, ctx, blocked, goal_ok=deep_ok)
                if rstep is not None and deep_ok(rstep):
                    offer({"char_uid": uid, "action": "move",
                           "dir": nav.step_dir(pos, rstep)}, RIDE_SEEK_SCORE,
                          "walking to a known rail to run the once-per-run ride probe")
                    productive = True

            harvest = next((p for p in nav.neighbors(pos)
                            if ctx.known.get(p) in HARVEST_KINDS), None)
            if harvest is not None:
                hkind = ctx.known.get(harvest)
                offer({"char_uid": uid, "action": "attack", "target": list(harvest)}, 3.3,
                      f"harvesting an adjacent {hkind} for materials (forge-to-arm probe)")
                productive = True
            elif self._wants_ore(char):
                # v0.54.0 slice 2: nothing breakable underfoot, so WALK to ore. Only ore --
                # see ORE_KINDS. Guarded by _wants_ore so this is never a march for cargo we
                # would only drop or sell at the other end.
                # A healed character may range further: see VEIN_SEEK_RANGE_HEALED.
                healed = any(i.get("kind") == "potion_red"
                             for i in char.get("inventory", []) or [])
                step = self._ore_step(
                    pos, ctx, blocked,
                    VEIN_SEEK_RANGE_HEALED if healed else VEIN_SEEK_RANGE,
                    goal_ok=deep_ok)
                if step is not None and not deep_ok(step):
                    step = None
                if step is not None:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                          VEIN_SEEK_SCORE,
                          "walking to a known vein — ore is the forge bottleneck "
                          f"({FORGE_METAL_PREFIXES[0]}/{FORGE_METAL_PREFIXES[1]} under reserve)")
                    productive = True

            # GOLD-RUSH (v0.24.0): do NOT chase monsters. Combat is not the gold
            # source and it is what gets our under-equipped chars killed (poison
            # undead). The adjacent-attack offer above (8.0) still defends and grabs
            # the occasional drop when something is already next to us.

            # An un-healed char (no potion_red) stays SHALLOW: poison is a DOT that
            # kills chars mid-retreat from deep ground, so past POISON_SAFE_DEPTH it
            # stops venturing deeper and heads HOME instead — a short retreat it can
            # survive (v0.23.0). Adjacent loot/attack (offered above, higher score)
            # still win, so it stays opportunistic; it just won't push further out.
            # A char carrying a heal may range deep (it can drink en route home).
            # has_heal is hoisted to the loop header (v0.103.0) — the gather block
            # gates on the same POISON_SAFE_DEPTH threshold this retreat uses.
            if (pos[1] >= depth_cap
                    and not (self._nuisance["uid"] == uid
                             and self._nuisance_hold == bot.tick)):
                # v0.107.0: the SAME budget the goals use. For an un-healed char this
                # is the old cap; for a healed one it fires beyond the potion-covered
                # range; for a WIZARD it fires at the base cap however healed — the
                # protected-caster directive, in the field and not just at the gate.
                self._retreat(uid, pos, ctx, blocked, offer, 2.5,
                              "no heal past the safe depth — heading home before poison strands us")
            else:
                # --- v0.48.0 ADAPTIVE COHESION: in a dangerous world, close up while the
                # coast is CLEAR so we are already together when something starts. Offered
                # here — below gathering, above frontier/scout — so it fills idle ticks
                # rather than displacing income, and it loses outright to spacing (3.0),
                # the dodge (7.3) and the retreat (8.5). A homing char is exempt (it is
                # walking to the village); so is a world we have not scouted. ---
                if rally:
                    step = self._cohesion_step(pos, allies, ctx, blocked)
                    if step is not None and not deep_ok(step):
                        step = None
                    if step is not None:
                        self._cohering.add(uid)
                        offer({"char_uid": uid, "action": "move",
                               "dir": nav.step_dir(pos, step)}, COHESION_SCORE,
                              f"rallying to the group centre ({centre_gap} away, close "
                              f"enough to arrive within one field stint) — dangerous "
                              f"world, forming up while it is clear")
                        productive = True
                    else:
                        self._cohering.discard(uid)

                north = self._step(pos, lambda p: p[1] > pos[1] and deep_ok(p)
                                   and nav.frontier(p, ctx.known, ctx.bounds), ctx, blocked)
                if north and not deep_ok(north):
                    north = None
                if north:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, north)},
                          FRONTIER_NORTH_SCORE, "pushing north into unexplored ground")
                    productive = True
                any_frontier = self._step(pos, lambda p: deep_ok(p)
                                          and nav.frontier(p, ctx.known, ctx.bounds), ctx, blocked)
                if any_frontier and not deep_ok(any_frontier):
                    any_frontier = None
                if any_frontier:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, any_frontier)},
                          FRONTIER_SCORE, "heading to the nearest frontier")
                    productive = True

                # v0.36.0 DEPLETION-AWARE retreat: nothing to grab and nowhere to explore
                # -> this world is looted-out for us. Rather than scout-wander (below) and
                # idle exposed, head HOME to re-embark somewhere fresher — UNLESS a refresh
                # is about to replenish coins right here, in which case wait it out.
                if not productive:
                    # v0.77.0 FRONTIER TREK — before declaring the world looted-out, a
                    # HEALED character walks toward the nearest true frontier, however far.
                    # Unbounded on purpose: this is terrain, which the map remembers
                    # durably, not contents (the 0.57.0 bound exists for contents). The
                    # trek outranks the looted-out retreat below, so an idle healed
                    # character explores while an idle bare one still heads home.
                    trek_heal = any(i.get("kind") == "potion_red"
                                    for i in char.get("inventory", []) or [])
                    if trek_heal:
                        # v0.80.0: the trek paths THROUGH breakable terrain (operator
                        # screenshot: a character read a pine belt as a dead end while
                        # holding the chop mechanic it has had since 0.45.0). A tree on
                        # the route costs BREAK_COST (~4 attack ticks + the step), so a
                        # short detour still wins and a long one loses to the axe. When
                        # the next tile on the cheapest route is a breakable, the offer
                        # is the ATTACK that clears it, not a move into it.
                        # NO attack branch here, deliberately: weighted_step returns a
                        # NEIGHBOUR, and a breakable neighbour already triggers the
                        # opportunistic adjacent-harvest (3.3) above, which sets
                        # `productive` and skips this block entirely. A trek-side chop was
                        # written, shadowed in every reachable case, and deleted when its
                        # mutant survived — the composition IS the design: the trek walks
                        # TO the belt, the harvest swings the axe, and the felled tile is
                        # a path next tick.
                        tstep = nav.weighted_step(
                            pos, lambda p: deep_ok(p) and nav.frontier(p, ctx.known, ctx.bounds),
                            ctx.known, blocked, breakable=HARVEST_KINDS,
                            fresh=ctx.fresh)
                        if tstep is not None and ctx.known.get(tstep) not in HARVEST_KINDS:
                            offer({"char_uid": uid, "action": "move",
                                   "dir": nav.step_dir(pos, tstep)}, TREK_SCORE,
                                  "trekking to the nearest unexplored frontier — healed, "
                                  "and everything local is farmed out")
                    nr = frame.get("next_refresh") or {}
                    in_ticks = nr.get("in_ticks")
                    refresh_soon = isinstance(in_ticks, int) and in_ticks <= REFRESH_STAY_TICKS
                    if (self._nuisance["uid"] == uid
                            and self._nuisance_hold == bot.tick):
                        refresh_soon = True   # v0.111.3: ON STATION is the job —
                                              # holding beside Will's party is not
                                              # "looted-out"; no home walk, no stamp
                    if not refresh_soon:
                        # v0.105.0: stamp the reason the char is heading home, so the
                        # village won't bounce it straight back into the same farmed
                        # strip (run #197's revolving door: 1051 embarks, chars doing
                        # vale->village->vale in 1-4 ticks). Stamped at OFFER time: if
                        # something better wins and the char never reaches the village,
                        # the stamp expires harmlessly in the field.
                        self._returned_empty[uid] = bot.tick
                        self._looted_home[uid] = bot.tick   # v0.109.4: commit the walk
                        self._retreat(uid, pos, ctx, blocked, offer, 1.5,
                                      "world looted-out, no refresh imminent — home to re-embark")

                # v0.109.5 HOLD FOR THE SWEEP: with nothing productive and a refresh
                # imminent, the scout-wander is worse than standing still — the sim
                # soak caught a scout-vs-mirage oscillator (recruit r90008, tiles
                # (3,9)-(3,11)) that only exists because short band cycles keep
                # refresh_soon TRUE, which suppresses the looted-out retreat AND its
                # commitment latch. Camping until the sweep is the mines-crew posture,
                # now explicit: no scout while (idle and refresh_soon).
                _nr = (frame.get("next_refresh") or {}).get("in_ticks")
                _hold = (not productive and isinstance(_nr, int)
                         and _nr <= REFRESH_STAY_TICKS)
                if not _hold:
                    for d, (dx, dy) in nav.DIRS.items():
                        nxt = (pos[0] + dx, pos[1] + dy)
                        if nav.is_walkable(nxt, ctx.known, blocked) and deep_ok(nxt):
                            offer({"char_uid": uid, "action": "move", "dir": d}, SCOUT_SCORE,
                                  "no goal reachable — stepping to scout")
                            break
                        break

    # -- helpers --------------------------------------------------------------

    def _equip_action(self, uid: str, inv: list[dict[str, Any]],
                      eqp: dict[str, Any]) -> dict[str, Any] | None:
        """Equip the first carried, equippable item into an empty slot it has not
        already been rejected from. Slots are learned by trial (see
        on_action_error), so this needs no content knowledge of which item goes
        where. Returns an equip action (with a ``_why`` note) or None."""
        # v0.109.1: LEARN right slots from what is actually worn — run #206's cost
        # of not doing so: a char already wearing a club walked a SECOND club through
        # offhand/outfit/trinket/boots, four wrong_slot errors for a kind whose slot
        # its own hand was proving the whole time.
        for s_ in EQUIP_SLOTS:
            worn = eqp.get(s_)
            wk = worn.get("kind") if isinstance(worn, dict) else worn
            if wk:
                self.slot_right.setdefault(wk, s_)
        for item in inv:
            kind = item["kind"]
            if "equip" not in (item.get("uses") or []) or self._wont_fit(kind, uid):
                continue
            proven = self.slot_right.get(kind)
            candidates = (proven,) if proven else EQUIP_SLOTS
            slot = next((s for s in candidates
                         if eqp.get(s) is None and s not in self.slot_wrong[kind]), None)
            if slot is None:
                continue                    # no empty, not-known-wrong slot for it
            self.equipping[uid] = (kind, slot)
            self._equip_upgrade.discard(uid)
            return {"char_uid": uid, "action": "equip", "slot": slot,
                    "item_id": item["item_id"],
                    "_why": f"equipping {kind} -> {slot} "
                            f"(wrong so far: {sorted(self.slot_wrong[kind]) or 'none'})"}
        # v0.53.0 UPGRADE pass. Filling only EMPTY slots meant a character never
        # improved on what it already wore -- and run #129 showed what that costs: we
        # forged a spear, the slot search learned outfit/trinket/boots were wrong for it,
        # `hand` was occupied by a 15-gold club, so `_should_sell` concluded no slot
        # remained and SOLD the spear we had just spent an ingot and a lumber to make.
        # Forging is worth nothing until its output can displace something worse.
        for item in inv:
            kind = item["kind"]
            if "equip" not in (item.get("uses") or []) or self._wont_fit(kind, uid):
                continue
            slot = self._upgrade_slot(kind, eqp)
            if slot is None:
                continue
            self.equipping[uid] = (kind, slot)
            self._equip_upgrade.add(uid)
            worn = self._worn_kind(eqp.get(slot))
            return {"char_uid": uid, "action": "equip", "slot": slot,
                    "item_id": item["item_id"],
                    "_why": f"upgrading {slot}: {kind} ({self.price.get(kind)}g) "
                            f"over {worn} ({self.price.get(worn)}g)"}
        return None

    def _learn_prices(self, frame: dict[str, Any]) -> None:
        """Remember what the shop charges for each kind. Learned rather than hardcoded
        for the same reason `_afford_weapon` reads prices live: the economy shuffles per
        world, and a price we never see stays unknown (which blocks a swap rather than
        guessing at one)."""
        for sitem in (frame.get("shop", {}) or {}).get("stock", []) or []:
            kind, price = sitem.get("kind"), sitem.get("buy_price")
            if isinstance(kind, str) and isinstance(price, int):
                self.price[kind] = price

    @staticmethod
    def _worn_kind(slot_value: Any) -> str | None:
        """The kind in an equipment slot. Slots hold an item dict, but tolerate a bare
        kind string so this never depends on which shape a frame happens to use."""
        if isinstance(slot_value, dict):
            k = slot_value.get("kind")
            return k if isinstance(k, str) else None
        return slot_value if isinstance(slot_value, str) else None

    def _upgrade_slot(self, kind: str, eqp: dict[str, Any]) -> str | None:
        """The OCCUPIED slot this kind should displace, or None.

        Three conditions, each of which a test earned:

        * SAME CLASS. A price only means something against a comparable item -- a 70g
          spear is not an "upgrade" over a 25g shield, they do different jobs, and
          ranking across classes proposed exactly that nonsense (spear -> offhand).
        * STRICTLY dearer. Equal is not better, or two same-priced kinds displace each
          other every village visit forever. This is also what stops a kind displacing
          ITSELF -- a second spear ranks equal to the worn one, so it never swaps, and
          no separate identity check is needed (an earlier one was redundant).
        * BOTH prices KNOWN. An unseen price is not zero -- treating it so would let
          anything displace anything the shop happens not to stock.

        Consequence worth naming: `shield_iron` is not sold at any price, so it has no
        price to rank and can never be SWAPPED in -- only worn into an offhand that is
        still empty. Ranking the unbuyable would mean inventing a value for it, which is
        the guess this method exists to avoid."""
        if self._swap_unsupported:
            return None
        mine = self.price.get(kind)
        if mine is None:
            return None
        # An unclassified kind needs no early-out of its own: its class is None, and the
        # per-slot check below compares classes, so it matches nothing wearable. (An
        # explicit guard here was redundant and mutation-testing proved it -- no test
        # could tell the two versions apart, because no behaviour differs.)
        klass = self._gear_class(kind)
        for slot in EQUIP_SLOTS:
            if slot in self.slot_wrong[kind] or (kind, slot) in self._swap_failed:
                continue
            worn = self._worn_kind(eqp.get(slot))
            if worn is None:
                continue                    # empty -- that is pass 1's job, not a swap
            if self._gear_class(worn) != klass:
                continue                    # not comparable -- different job
            theirs = self.price.get(worn)
            if theirs is not None and mine > theirs:
                return slot
        return None

    @staticmethod
    def _gear_class(kind: str | None) -> str | None:
        """Which job a kind does: a hand weapon, or armour. ``None`` for anything we
        have no classification for, which blocks the comparison rather than guessing."""
        if kind in WEAPON_KINDS:
            return "weapon"
        if kind in ARMOR_KINDS:
            return "armor"
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

    def _afford_armor(self, char: dict[str, Any], eqp: dict[str, Any],
                      frame: dict[str, Any], gold: int) -> tuple[str, int] | None:
        """The cheapest shop ARMOR the char can afford, qualifies for, and has a slot for.

        "Has a slot for" is the important guard: the shop does not tell us which slot a
        kind occupies (every `slot` field is null), so we reuse what equipping has already
        LEARNED -- `slot_wrong` and `wont_fit` -- and refuse to buy a kind that has no
        empty slot left it could still go into. Without that we would re-buy a shield for
        a character already holding one, forever."""
        stock = (frame.get("shop", {}) or {}).get("stock", []) or []
        stats = char.get("stats", {}) or {}
        held = {i.get("kind") for i in (char.get("inventory") or [])}
        worn = {v.get("kind") if isinstance(v, dict) else v for v in eqp.values()}
        affordable = []
        for sitem in stock:
            kind = sitem.get("kind")
            if kind not in ARMOR_KINDS or not isinstance(sitem.get("buy_price"), int):
                continue
            if gold < sitem["buy_price"] or self._wont_fit(kind, char.get("char_uid")):
                continue
            if kind in held or kind in worn:
                continue                    # already carrying/wearing one
            if not all(stats.get(k, 0) >= v for k, v in (sitem.get("req") or {}).items()):
                continue
            # at least one EMPTY slot this kind is not already known to be wrong for
            if any(eqp.get(slot) is None and slot not in self.slot_wrong[kind]
                   for slot in EQUIP_SLOTS):
                affordable.append(sitem)
        if not affordable:
            return None
        best = min(affordable, key=lambda s: s["buy_price"])
        return best["kind"], best["buy_price"]

    def _world_is_dangerous(self, world: str | None, tick: int) -> bool:
        """Is this world worth holding formation in? Undead present, or melee predators
        dense enough that a lone character keeps losing trades.

        Unknown or STALE (older than THREAT_TTL) reads False: the default is to DISPERSE,
        which preserves the gathering economy and means a world we have not scouted cannot
        silently collapse the roster into one tile.
        """
        dg = self._death_gate.get(world or "")
        if dg is not None and tick - dg < DEATH_GATE_TTL:
            return True                    # v0.92.1: a recent corpse outranks any census
        d = self._world_danger.get(world or "")
        if not d or tick - d[2] >= THREAT_TTL:
            return False
        return d[0] >= UNDEAD_SEVERE_GUARDIAN or d[1] >= COHESION_PRED_DENSE

    def note_char(self, char: dict) -> None:
        """Feed the sightings ledger (call for every char in every frame)."""
        u = char.get("char_uid")
        if u:
            self._char_ledger[u] = {"char_uid": u, "stats": dict(char.get("stats") or {}),
                                    "level": char.get("level") or 0,
                                    "gifts": list(char.get("gifts") or [])}

    def on_char_death(self, uid: str, world: str | None = None,
                      tick: int | None = None) -> None:
        """v0.88.0: a death frees its seat INSTANTLY — the pure ranking promotes the next
        candidate the moment the corpse leaves the ledger. Called from the bot's event
        parser (the same place forged/overburdened learn).

        v0.92.1: OUR death also LATCHES the world's danger gate for DEATH_GATE_TTL. Run
        #181 exposed the green gate's blind spot: _world_is_dangerous needs >=2 melee
        predators in one view, but a spread-out chaser band kills SERIALLY — each lone
        recruit meets ONE delver, so vale never read dangerous while the median victim
        lasted 38 ticks from embark. A corpse needs no density threshold. Only a uid we
        held in OUR ledger latches (a rival's death is not in it), and only field worlds."""
        was_ours = self._char_ledger.pop(uid, None) is not None
        if was_ours and world and world != "village" and tick is not None:
            self._death_gate[world] = tick
        # v0.96.0: if the nuisance itself fell, stand the tour down (a relief volunteers
        # when Will is still in the vale). It tried not to die; sometimes Will wins.
        if uid == self._nuisance.get("uid"):
            self._nuisance_standdown(tick if tick is not None else 0, "the nuisance fell")
        self._party.pop(uid, None)

    def wizard_seats(self) -> set:
        # v0.94.0: feed last tick's seats back as incumbents for light hysteresis, and
        # remember the result. Empty on the first call after a restart -> pure top-cap,
        # then it stabilises within a frame (the same graceful-degrade the pool floor has).
        seats = select_wizards(list(self._char_ledger.values()),
                               incumbents=self._wizard_incumbents)
        self._wizard_incumbents = seats
        return seats

    def _hold_formation(self, uid, pos, anchor, ctx, blocked, offer, why_tail):
        """One member holding the party square: step toward `anchor` (a tile every member
        computes identically) with escort hysteresis; never beyond ESCORT_MAX_GAP —
        re-pairing at distance is the village's job."""
        agap = abs(anchor[0] - pos[0]) + abs(anchor[1] - pos[1])
        threshold = ESCORT_HOLD if uid in self._escorting else ESCORT_PULL
        if threshold < agap <= ESCORT_MAX_GAP:
            wstep = nav.weighted_step(
                pos, lambda t: abs(t[0] - anchor[0]) + abs(t[1] - anchor[1]) <= ESCORT_HOLD,
                ctx.known, blocked, fresh=ctx.fresh)
            if wstep is not None:
                self._escorting.add(uid)
                offer({"char_uid": uid, "action": "move",
                       "dir": nav.step_dir(pos, wstep)}, ESCORT_SCORE,
                      f"holding formation on the party square ({agap} away) — {why_tail}")
                return
        self._escorting.discard(uid)

    @staticmethod
    def _cohesion_step(pos: tuple[int, int], allies: list[tuple[int, int]],
                       ctx: "FieldContext", blocked) -> tuple[int, int] | None:
        """One step toward the group's CENTRE, or None once we are there.

        v0.72.0: this used to close on the NEAREST ALLY, and that is mutual pursuit — every
        character chasing a target that is chasing something else. It does not converge, and
        run #150 shows it consuming 25% of ALL DECISIONS while achieving nothing. One
        character logged 482 consecutive cohesion decisions with the ally distance reading
        13, 9, 8, 7, 6, 8, 8, 6, 8; at tick 1769538 four characters were "closing" on each
        other, two walking north and two south, all reporting a distance of 7. Another spent
        the run chasing an ally 19 tiles away: 19, 18, 17, 19, 19, 17.

        The centre is a FIXED POINT for the tick, so moving toward it monotonically shrinks
        the group's spread instead of trading places with it. Every character targets the
        same tile, which is what makes a rally converge rather than oscillate.

        The GOAL is proximity to that centre, not the centre tile itself: it may be solid, or
        occupied by whichever ally is standing on it, and pathing onto an occupied tile
        always fails.
        """
        if not allies:
            return None
        # v0.86.0: the centroid INCLUDES SELF. Excluding it gave every member a slightly
        # DIFFERENT rally square (the operator's jitter diagnosis, and cohesion's original
        # sin): with self included, all members of a group compute the identical point,
        # which is what makes a rally a rally.
        pts = list(allies) + [pos]
        cx = sum(a[0] for a in pts) // len(pts)
        cy = sum(a[1] for a in pts) // len(pts)

        def close_enough(t: tuple[int, int]) -> bool:
            return abs(t[0] - cx) + abs(t[1] - cy) <= COHESION_HOLD
        # Short-circuit if we are ALREADY in range: nav.bfs_step answers "which neighbour
        # leads to the nearest goal" and does not treat the start tile as a goal, so
        # without this it would hand back a pointless step. The caller's hysteresis check
        # normally prevents that, but the helper should not depend on its caller for
        # correctness.
        if close_enough(pos):
            return None
        return nav.bfs_step(pos, close_enough, ctx.known, blocked)

    @staticmethod
    def _will_party(frame: dict) -> list[dict]:
        """WillMorr's characters visible in this frame — faction 'guild', his guild_id,
        with a position. The live signal (the track feed is unreliable/stale)."""
        return [e for e in (frame.get("visible") or {}).get("entities") or []
                if e.get("faction") == "guild"
                and e.get("guild_id") == NUISANCE_GUILD and e.get("pos")]

    @staticmethod
    def _greedy_toward(pos, target, known, blocked) -> tuple[int, int] | None:
        """The walkable neighbour that most reduces Manhattan distance to target, or None.
        Simpler and more predictable than a region-goal BFS for 'drift toward a point' —
        the nuisance only needs to close on Will's centroid, not path optimally to it."""
        best, bestd = None, abs(pos[0] - target[0]) + abs(pos[1] - target[1])
        for n in nav.neighbors(pos):
            if n in blocked or known.get(n) in nav.SOLID:
                continue
            d = abs(n[0] - target[0]) + abs(n[1] - target[1])
            if d < bestd:
                best, bestd = n, d
        return best

    @staticmethod
    def _centroid(points: list) -> tuple[int, int] | None:
        if not points:
            return None
        return (round(sum(p[0] for p in points) / len(points)),
                round(sum(p[1] for p in points) / len(points)))

    def _record_nuisance(self, bot) -> None:
        """Expose the current nuisance uid to the dashboard (runtime state it cannot
        otherwise see). Fail-closed: a recording hiccup never touches play."""
        try:
            storage = getattr(bot, "storage", None)
            if storage is None:
                return
            import time as _time
            from steemer import intel
            intel.record(storage.conn, "nuisance", bot.tick, _time.time(),
                         {"uid": self._nuisance.get("uid")})
        except Exception as e:                        # noqa: BLE001
            print(f"[nuisance] record failed ({e.__class__.__name__})", flush=True)

    def _nuisance_standdown(self, tick: int, reason: str) -> None:
        """Reclassify the nuisance: it reverts to its stat/seat role automatically once
        the designation clears. Called when Will leaves, the nuisance dies, or a tour
        completes (loot delivered)."""
        self._nuisance.update(uid=None, phase="shadow", loot_pos=None, laughed=False)
        self._nuisance["_standdown_reason"] = reason

    def _nuisance_track(self, bot, char, uid, frame, tick) -> None:
        """Per-acting-char upkeep (cheap, runs for every vale char): learn Will's eids,
        refresh 'last seen', DESIGNATE a volunteer when >=3 of his chars share the vale,
        and STAND DOWN when he's been gone longer than the TTL. Designation is dynamic —
        it exists only while Will's party is actually here."""
        if frame.get("world") != NUISANCE_WORLD:
            return
        party = self._will_party(frame)                 # locally visible Will chars
        for e in party:
            self._will_eids[e["eid"]] = tick
        # v0.97.0: also count Will via the sidecar's HINTS (map-wide), so we designate
        # even when Will is across the vale, out of our chars' local sight — the reason
        # the nuisance never fired while Will was demonstrably in the vale.
        hint_party = [h for h in getattr(bot, "rival_hints", {}).get(NUISANCE_WORLD, [])
                      if h.get("guild_id") == NUISANCE_GUILD]
        seen_count = max(len(party), len(hint_party))
        if seen_count >= NUISANCE_TRIGGER:
            self._nuisance["seen_tick"] = tick
            if self._nuisance["uid"] is None:
                # this char sees Will and is here — it volunteers (armed volunteers are
                # better nuisances, but any healthy body will do; the tour self-selects)
                self._nuisance["uid"] = uid
                self._nuisance["phase"] = "shadow"
                self._nuisance["laughed"] = False
                self._record_nuisance(bot)
        # stand down if Will has not been seen in TTL ticks (he left the vale)
        if (self._nuisance["uid"] is not None
                and tick - self._nuisance["seen_tick"] > NUISANCE_GONE_TTL):
            self._nuisance_standdown(tick, "will's party left the vale")
            self._record_nuisance(bot)

    def _nuisance_act(self, bot, char, uid, pos, frame, ctx, hp, max_hp, hurt,
                      offer, trace) -> None:
        """The nuisance's tour, as scored OFFERS (survival still outranks all of them, so
        'try not to die' is honoured by construction). Phases: SHADOW (follow Will's
        centroid, pout when hit), LOOT (a fallen Will member dropped spoils — go grab
        them), DELIVER (cackle and run the loot home)."""
        if self._nuisance["uid"] != uid:
            return
        # v0.110.2: THE TOUR PAUSES OFF-STAGE. The designation is made in the vale
        # (_nuisance_track is world-guarded) but the OFFERS weren't — a designated
        # nuisance that strayed (or whose target moved) kept shadowing through LOCAL
        # visibility in any world: run #213, c19460 followed WillMorr's party into
        # the MINES at y=28, un-healed, flickering follow(3.6)-vs-poison-retreat(2.5)
        # at the vision edge. The operator's spec is vale-only ("if Will's party
        # leaves the vale... reclassify"); outside the stage the ordinary ladder
        # (incl. the depth cap) governs.
        if frame.get("world") != NUISANCE_WORLD:
            return
        tick = bot.tick
        events = frame.get("events") or []
        # ":(" — a Will character just hit us
        if tick - self._nuisance["pout_tick"] >= NUISANCE_POUT_COOLDOWN:
            my_eid = char.get("eid")
            if any(ev.get("kind") == "attack" and ev.get("target") == my_eid
                   and ev.get("attacker") in self._will_eids for ev in events):
                self._nuisance["pout_tick"] = tick
                offer({"char_uid": uid, "action": "say", "text": NUISANCE_POUT},
                      NUISANCE_POUT_SCORE, f"nuisance: {NUISANCE_GUILD_NAME} hit me — {NUISANCE_POUT}")
        # a Will member died and dropped spoils -> switch to LOOT (nearest such drop)
        if self._nuisance["phase"] == "shadow":
            drops = [tuple(ev["pos"]) for ev in events
                     if ev.get("kind") == "death" and ev.get("guild_id") == NUISANCE_GUILD
                     and ev.get("dropped") and ev.get("pos")]
            if drops:
                self._nuisance["phase"] = "loot"
                self._nuisance["loot_pos"] = min(
                    drops, key=lambda d: abs(d[0] - pos[0]) + abs(d[1] - pos[1]))
        # ONLY IF SUCCESSFUL (operator): a real pickup EVENT for our eid — not merely
        # offering one — flips loot -> deliver, so we cackle home only with loot in hand.
        if self._nuisance["phase"] == "loot":
            my_eid = char.get("eid")
            if any(ev.get("kind") == "pickup" and ev.get("eid") == my_eid for ev in events):
                self._nuisance["phase"] = "deliver"
        phase = self._nuisance["phase"]
        if phase == "loot":
            target = self._nuisance["loot_pos"]
            if target is None:
                self._nuisance["phase"] = "shadow"
            elif tuple(pos) == target:
                # standing on the spoils — grab them. The flip to DELIVER waits for the
                # actual `pickup` EVENT (below): "only if successful", per the operator.
                offer({"char_uid": uid, "action": "pickup"}, NUISANCE_LOOT_SCORE,
                      f"nuisance: looting {NUISANCE_GUILD_NAME}'s fallen")
            else:
                step = self._step(pos, lambda t: t == target, ctx,
                                  ctx.bodies | set(ctx.enemies))
                if step is not None:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                          NUISANCE_LOOT_SCORE, f"nuisance: beelining to {NUISANCE_GUILD_NAME}'s drop")
            return
        if phase == "deliver":
            if not self._nuisance["laughed"]:
                self._nuisance["laughed"] = True
                offer({"char_uid": uid, "action": "say", "text": NUISANCE_LAUGH},
                      NUISANCE_LAUGH_SCORE, f"nuisance: {NUISANCE_LAUGH} (running home with the loot)")
            # beeline home (y -> 0); arrival is handled in the village loop, which banks
            # the spoils into the guild inventory and stands this tour down for a relief.
            step = self._step(pos, lambda t: t[1] == 0, ctx, ctx.bodies | set(ctx.enemies))
            if step is not None:
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                      NUISANCE_DELIVER_SCORE, "nuisance: carrying the spoils home to the guild")
            return
        # SHADOW: hang in the CENTRE of Will's group. Prefer LOCALLY-visible chars (exact
        # positions); if none are in sight, fall back to the sidecar's HINT positions to
        # cross the vale toward him (map-wide knowledge closing the local-vision gap).
        local = [tuple(e["pos"]) for e in self._will_party(frame)]
        if local:
            centroid = self._centroid(local)
        else:
            hints = [h["pos"] for h in getattr(bot, "rival_hints", {}).get(NUISANCE_WORLD, [])
                     if h.get("guild_id") == NUISANCE_GUILD]
            centroid = self._centroid(hints)
        if centroid is not None:
            cx, cy = centroid
            near = abs(pos[0] - cx) + abs(pos[1] - cy) <= NUISANCE_HANG_RADIUS
            if near:
                # v0.111.3 ON STATION: within hang radius the mission's offer goes
                # QUIET, and run #218 showed what fills the silence — the un-healed
                # depth retreat (2.5) pulls one step home, exits the radius, the
                # follow (3.6) pulls back: a hang-boundary dance (c19657 at y22/23).
                # Holding station is a deliberate choice, not an absence: stamp the
                # tick and the depth retreat yields for it (survival offers at 7+
                # still outrank everything and evacuate a genuinely hurt nuisance).
                self._nuisance_hold = bot.tick
                trace.observe("nuisance on station — holding in the centre")
            step = None if near else self._greedy_toward(
                pos, centroid, ctx.known, ctx.bodies | set(ctx.enemies))
            if step is not None:
                offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                      NUISANCE_FOLLOW_SCORE,
                      f"nuisance: shadowing {NUISANCE_GUILD_NAME}'s party (hanging in the centre)")

    def _ride_prober_ready(self, char, pos, hp, max_hp, stamina,
                           ctx: "FieldContext") -> bool:
        """The shared ride-probe gate (v0.93.1): not yet probed this run, ARMED (bare
        hands never probe — the green doctrine extends to experiments), healthy, calm.
        The on-rail check is NOT here — seek needs 'ready but off the rail', fire needs
        'ready and on it' — so factoring only the common part keeps them from drifting."""
        return (not self._ride_probed
                and bool((char.get("equipment") or {}).get("hand"))
                and bool(max_hp) and hp >= RIDE_PROBE_HP_FRAC * max_hp
                and stamina >= RIDE_PROBE_MIN_STA
                and not any(abs(q[0] - pos[0]) + abs(q[1] - pos[1]) <= FLEE_RADIUS
                            for q in ctx.enemies))

    @staticmethod
    def _is_rideable_rail(ctx: "FieldContext", t: tuple[int, int]) -> bool:
        """A track tile the probe could ACTUALLY ride from: a track with a track
        NEIGHBOUR to give the ride a direction. A lone track is a dead ride. Shared by
        the seek goal AND the seek guard so 'where we head' and 'when we stop heading'
        use one definition."""
        return (ctx.known.get(t) == "track"
                and any(ctx.known.get(n) == "track" for n in nav.neighbors(t)))

    @classmethod
    def _rail_step(cls, pos: tuple[int, int], ctx: "FieldContext", blocked,
                   reach: int = RIDE_SEEK_RANGE,
                   goal_ok=lambda t: True) -> tuple[int, int] | None:
        """One step toward the nearest known RIDE-ABLE rail tile within reach, or None.
        A track tile is WALKABLE (you stand ON it, unlike a vein), so the goal is the
        tile itself. ``goal_ok`` filters the GOAL (v0.105.1): run #198 showed the ride
        probe staging a chorus line at the poison cap — an un-healed anchor marched to
        y11 chasing a past-cap rail it could never reach, and its two escorts held
        formation on the stall (the exact goal-vs-step lesson of 0.105.0, in the seek
        this project shipped step-gated only and NAMED as the gap)."""
        return nav.bfs_step(pos, lambda t: goal_ok(t) and cls._is_rideable_rail(ctx, t),
                            ctx.known, blocked, max_depth=reach)

    @staticmethod
    def _ore_step(pos: tuple[int, int], ctx: "FieldContext", blocked,
                  reach: int = VEIN_SEEK_RANGE,
                  goal_ok=lambda t: True) -> tuple[int, int] | None:
        """One step toward the nearest known ORE tile within ``VEIN_SEEK_RANGE``, or None.

        The goal tile is SOLID (a vein is scenery you break, not ground you stand on), so
        this asks for the step that brings us ADJACENT to it and lets slice 1's
        adjacent-harvest offer do the breaking. bfs_step already permits a goal tile to be
        entered when nothing else is; here we never want to enter it, only to reach its
        neighbour -- which is why the goal is "a walkable tile beside a vein", not the vein.
        """
        def beside_ore(t: tuple[int, int]) -> bool:
            return goal_ok(t) and any(ctx.known.get(n) in ORE_KINDS
                                      for n in nav.neighbors(t))
        # The range limit is `max_depth` alone. An explicit manhattan check here was
        # redundant — a path of at most N steps cannot end further than N away — and
        # mutation testing proved it: no test could tell the two versions apart.
        return nav.bfs_step(pos, beside_ore, ctx.known, blocked, max_depth=reach)

    @staticmethod
    def _wants_ore(char: dict[str, Any]) -> bool:
        """Would this character actually benefit from another ore? Only if it is under the
        per-char forge reserve AND has carry room -- otherwise the walk ends in a drop or a
        sale, which is the v0.46.0 mistake (reserving feedstock we could not use, at the
        cost of the income that was paying for weapons)."""
        inv = char.get("inventory") or []
        metal = sum(1 for i in inv if (i.get("kind") or "").startswith(FORGE_METAL_PREFIXES))
        if metal >= FORGE_RESERVE_PER_CHAR:
            return False
        carry = char.get("carry") or {}
        used, cap = carry.get("used"), carry.get("cap")
        if isinstance(used, int) and isinstance(cap, int) and used >= cap - 1:
            return False                    # no room for what the trip would bring back
        return True

    @staticmethod
    def _is_melee_predator(kind: str | None) -> bool:
        """v0.32.0: a hostile monster (ctx.enemies is faction==monster only) is a
        melee predator to avoid UNLESS it is confirmed-benign wildlife or one of the
        ranged/chasing undead (which get the wider radius-4 flee instead). Default-
        dangerous, so a brand-new band mob is dodged on sight, not after the first
        death."""
        return bool(kind) and kind not in WILDLIFE_SAFE and kind not in THREAT_KINDS

    @staticmethod
    def _shop_price(frame: dict[str, Any], kind: str) -> int | None:
        """The live shop price of a kind, or None if it is not stocked. Read from the
        frame like every other price in this file -- the economy shuffles per world, so a
        hardcoded price is a bug waiting for a band refresh."""
        for s in (frame.get("shop", {}) or {}).get("stock", []) or []:
            if s.get("kind") == kind and isinstance(s.get("buy_price"), int):
                return s["buy_price"]
        return None

    def _replenished_since(self, bot: "Any", world: str, stamp: int) -> bool:
        """Has ``world`` plausibly replenished since ``stamp``? True on an OBSERVED band
        refresh after the stamp (bot.refreshed_at), or when the clock has passed the
        last-known refresh ETA (bot.refresh_eta = frame tick + next_refresh.in_ticks —
        the fallback for worlds we lost eyes on, since an empty world sends no frames).
        A world we have never seen either signal for is allowed: benching a char on
        zero information would deadlock the roster, and one scouting trip re-arms the
        clocks."""
        ra = getattr(bot, "refreshed_at", {}).get(world)
        if ra is not None and ra > stamp:
            return True
        eta = getattr(bot, "refresh_eta", {}).get(world)
        if eta is not None and bot.tick >= eta:
            return True
        return ra is None and eta is None

    @staticmethod
    def _afford_potion(frame: dict[str, Any], gold: int) -> tuple[str, int] | None:
        """The field heal (``potion_red``) from live shop stock, if buying it leaves a
        minimal operating buffer (POTION_MIN_BUFFER). Prices read from the frame,
        never hardcoded.

        v0.106.0: the old gate demanded ``gold - price >= POTION_RESERVE`` — the
        reserve whose whole purpose is to protect potion buys from weapon/armor
        spending was VETOING the potion buy itself (gold ran 33-42 across #197-199
        and needed 50; zero potions bought while the roster stood depth-capped and
        the whole map read looted-out). The reserve still floors the OTHER buys
        (weapons 45, armor 70, bottles/tome via POTION_RESERVE); the potion has
        first claim on it by design."""
        stock = (frame.get("shop", {}) or {}).get("stock", []) or []
        for s in stock:
            if s.get("kind") == "potion_red" and isinstance(s.get("buy_price"), int):
                price = s["buy_price"]
                if gold - price >= POTION_MIN_BUFFER:
                    return "potion_red", price
                return None
        return None

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
        # v0.106.0: a VIGOR singleton is half a heal — it pairs with the next vigor
        # herb foraged and becomes a potion_red, the supply the whole depth economy
        # hangs on. Selling it for ~1.4g was the leak that kept brewing at zero
        # (runs #195-199: 0 brews). A "singleton" group is at most ONE item (BREW_MIN
        # is 2), so this cannot re-open the 0.8.0 carry-clog.
        vig = by_ess.get("vigor") or []
        if len(vig) < BREW_MIN:
            keep.update(it["item_id"] for it in vig)
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

    FORGE_TOPIC = "forge_recipe"

    @staticmethod
    def _recipe_fact(recipe: tuple[str, int, int]) -> str:
        return "%s:%d:%d" % recipe

    @staticmethod
    def _fact_recipe(fact: str) -> tuple[str, int, int] | None:
        parts = fact.split(":")
        if len(parts) != 3:
            return None
        try:
            return parts[0], int(parts[1]), int(parts[2])
        except ValueError:
            return None

    def _vault_frontier(self) -> int:
        """The newest item_id ever proven phantom. Wire v3 exposed the truth of the
        vault (2026-08-25): 78 distinct ids probed across runs, head AND tail, zero
        successes — the listed stacks are graveyards, and ids ascend with creation.
        Only ids ABOVE this frontier are worth a probe: a genuinely new banked item
        (a brew, a delivery) gets a fresh higher id and is tried automatically,
        while the known-dead range is never re-walked. Zero standing waste, no
        writeoff risk."""
        return max(self._vault_dead, default=-1)

    def _hydrate_slots(self, bot: "Any") -> None:
        """Load the kind->slot proofs from EARLIER runs, once per process. The ladder
        re-learned from zero on every restart (run #207: 4 wrong_slot probes for kinds
        proven the run before) — and we restart several times a day. Best-effort."""
        if self._slots_hydrated:
            return
        self._slots_hydrated = True
        st = getattr(bot, "storage", None)
        if st is None:
            return
        try:
            row = intel.latest(st.conn, "slot_right")
            if row and isinstance(row.get("data"), dict):
                for k, v in (row["data"].get("map") or {}).items():
                    self.slot_right.setdefault(k, v)
        except Exception as e:
            print(f"[equip] could not load slot proofs ({e}) — starting fresh",
                  flush=True)

    def _persist_slots(self, bot: "Any") -> None:
        """Write the proof map when it has grown. Cheap (a dict of a few entries)."""
        if len(self.slot_right) == self._slots_persisted:
            return
        st = getattr(bot, "storage", None)
        if st is None:
            return
        try:
            import time as _t
            intel.record(st.conn, "slot_right", bot.tick, _t.time(),
                         {"map": dict(self.slot_right)})
            self._slots_persisted = len(self.slot_right)
        except Exception:
            pass                    # best-effort, never load-bearing

    def _hydrate_vault(self, bot: "Any") -> None:
        """Load the phantom vault ids proven in EARLIER runs, once per process — the
        vault list is ~202 entries and the per-run storm latch allows only
        VAULT_DEAD_LIMIT fresh probes, so without persistence every run re-probes the
        same dead head and the real entries (if any) are never reached. Best-effort,
        like the forge hydration it mirrors."""
        if self._vault_hydrated:
            return
        self._vault_hydrated = True
        st = getattr(bot, "storage", None)
        if st is None:
            return
        try:
            row = intel.latest(st.conn, "vault_phantom")
            if row and isinstance(row.get("data"), dict):
                self._vault_dead |= set(row["data"].get("ids") or [])
        except Exception as e:
            print(f"[vault] could not load phantom ids ({e}) — starting fresh",
                  flush=True)

    def _hydrate_forge(self, bot: "Any") -> None:
        """Load recipes proven in EARLIER runs, once per process.

        Without this every deploy re-walks the ladder from scratch, and run #143 shows the
        bill: one character spent 20 of the run's 23 forge attempts rediscovering that its
        affordable `shield_iron` quantities all fail -- something run #129 had already
        proven, since shield_iron needs (3, 1) and it held two ingots. We redeploy several
        times a day, so that tuition is paid over and over.

        Best-effort, like the map hydration it mirrors: no storage, a read-only replay or an
        older schema must still start, just ignorant as before.
        """
        if self._forge_hydrated:
            return
        self._forge_hydrated = True
        st = getattr(bot, "storage", None)
        if st is None:
            return
        try:
            for fact in st.load_learned(self.FORGE_TOPIC):
                recipe = self._fact_recipe(fact)
                if recipe is not None:
                    self._forge_proven.add(recipe)
        except Exception as e:      # pragma: no cover - exercised by the None path
            print(f"[forge] could not load proven recipes ({e}) — starting fresh",
                  flush=True)

    def _prove_forge(self, bot: "Any", recipe: tuple[str, int, int]) -> None:
        """Record a proven recipe in memory AND in storage, so the next deploy inherits it."""
        self._forge_proven.add(recipe)
        self._forge_failed.discard(recipe)
        self._forge_fails.pop(recipe, None)
        st = getattr(bot, "storage", None)
        if st is None:
            return
        try:
            st.record_learned(self.FORGE_TOPIC, self._recipe_fact(recipe))
        except Exception as e:      # pragma: no cover
            print(f"[forge] could not persist a proven recipe ({e}) — continuing", flush=True)

    def _ore_world(self, bot) -> str | None:
        """The world where we have seen ORE VEINS — derived from accumulated tile memory,
        cached, so the ore-hungry bias needs no hardcoded map name. None until a vein is
        seen (then no bias, which is correct — we cannot route to ore we have never found)."""
        cached = getattr(self, "_ore_world_cache", None)
        if cached is not None:
            return cached
        for w, tiles in (getattr(bot, "known", {}) or {}).items():
            if any(k == "vein" for k in tiles.values()):
                self._ore_world_cache = w
                return w
        return None

    @staticmethod
    def _ingot_hungry(guild: dict) -> bool:
        """Is the guild short on ingots? Counted from the shared stash (the surplus pool
        the smith pipeline draws on). Ore is the scarce half; lumber is plentiful, so this
        is the signal to route gatherers to the mines rather than more surface worlds."""
        n = sum(i.get("count", 1) for i in (guild.get("inventory") or [])
                if str(i.get("kind", "")).startswith("ingot"))
        return n <= INGOT_HUNGRY

    def _choose_forge(self, inv: list[dict[str, Any]], eqp: dict[str, Any],
                      stamina: int) -> tuple[tuple[str, int, int], list[Any], str] | None:
        """Pick a forge to attempt: ``((product, n_ingot, n_lumber), item_ids, why)``.

        The RECIPE is returned alongside the ids because an ``item_id`` is opaque — it
        cannot tell us afterwards whether it was an ingot or a plank, and the recipe is
        exactly what a rejection has to blacklist.

        Prefers a product whose slot is still EMPTY — forging a shield for a character
        already holding one banks nothing. Skips combinations the server has already
        rejected, and refuses below FORGE_STAMINA so the cost is not paid for a bounce.
        """
        if stamina < FORGE_STAMINA:
            return None
        ingots = [i for i in inv if str(i.get("kind", "")).startswith("ingot")]
        lumber = [i for i in inv if str(i.get("kind", "")).startswith("lumber")]
        if not ingots or not lumber:
            return None
        worn = {v.get("kind") if isinstance(v, dict) else v for v in eqp.values()}
        # v0.95.0: forge to the char's NEED. The static shield-first order was written
        # when 100% of offhands were empty and armour was the crisis; now the crisis is
        # BARE HANDS (28/30 unarmed can neither fight nor flee cleanly — the idle-village
        # and passive-char reports). A character with an EMPTY HAND forges a WEAPON first
        # (spear's recipe is proven: 1 ingot + 1 lumber), so scarce materials arm the hand
        # before they armour the offhand; an already-armed char still makes a shield.
        # v0.98.0 SMITH PIPELINE: a TOOL in the hand (pickaxe/sickle) is not a combat
        # weapon — treat it as an empty hand for weapon-first. #189's whole forge queue
        # was one pickaxe-wielding miner forging shield_iron 418x (hand full of a tool ->
        # armour path) while its spear materials sat unused. A spear beats a pickaxe for
        # fighting; the equip-upgrade pass swaps the dearer weapon in.
        hand = eqp.get("hand")
        hand_kind = hand.get("kind") if isinstance(hand, dict) else hand
        needs_weapon = (not hand_kind) or hand_kind in FORGE_HAND_TOOLS
        order = FORGE_WEAPON_FIRST if needs_weapon else FORGE_PRODUCTS
        for product in order:
            if product in worn or self._wont_fit(product):
                continue
            # v0.66.0: once a product has a PROVEN recipe, that is the only quantity worth
            # sending. Walking the rest of the ladder anyway is what cost run #143 thirteen
            # attempts on `shield_iron` from a character holding two ingots, when #129 had
            # already proven it needs three. If the proven quantity is unaffordable right
            # now, this product is simply not on today's menu -- move to the next one.
            proven = [r for r in FORGE_RECIPES if (product, *r) in self._forge_proven]
            for n_ing, n_lum in (proven or FORGE_RECIPES):
                if (product, n_ing, n_lum) in self._forge_failed:
                    continue
                if len(ingots) < n_ing or len(lumber) < n_lum:
                    continue
                ids = [i["item_id"] for i in ingots[:n_ing] + lumber[:n_lum]]
                return ((product, n_ing, n_lum), ids,
                        f"forging {product} from {n_ing}x ingot + {n_lum}x lumber "
                        f"(M3a: the shop does not sell this at any price)")
        return None

    @staticmethod
    def _feedstock_keep_ids(inv: list[dict[str, Any]]) -> set[str]:
        """Item_ids of forge feedstock to RESERVE -- up to ``FORGE_RESERVE_PER_CHAR`` of
        each kind per character; the surplus above that still sells.

        Deliberately a per-kind cap rather than "keep it all": the reserve exists to feed
        the forge, and an unbounded one re-creates the v0.19.0 carry clog. Selection
        follows the inventory's own order so the choice is deterministic and replayable."""
        # Is there metal to forge WITH? An ingot, or >=2 of one ore kind (which smelts
        # into one). Without it a reserved shaft is dead weight and lost income.
        ore_counts: dict[str, int] = defaultdict(int)
        has_ingot = False
        for it in inv:
            k = str(it.get("kind", ""))
            if k.startswith("ingot"):
                has_ingot = True
            elif k.startswith("ore"):
                ore_counts[k] += 1
        has_metal = has_ingot or any(v >= 2 for v in ore_counts.values())

        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for it in inv:
            kind = str(it.get("kind", ""))
            if not kind.startswith(FORGE_FEEDSTOCK_PREFIXES):
                continue
            if kind.startswith(FORGE_SHAFT_PREFIXES) and not has_metal:
                continue                    # shaft with no metal -> sell it, bank the gold
            by_kind[it["kind"]].append(it)
        keep: set[str] = set()
        for g in by_kind.values():
            keep.update(it["item_id"] for it in g[:FORGE_RESERVE_PER_CHAR])
        return keep

    def _wont_fit(self, kind: str, uid: str | None = None) -> bool:
        """Is this kind still out of reach on stats?

        Only while the candidate has not out-grown the refusal. With a `uid` the question
        is about that character; without one (the sell rule and the forge ladder have no
        character in hand) it is about the BEST of us, because a kind one character can
        wear is not something to bank.
        """
        bar = self.wont_fit.get(kind)
        if bar is None:
            return False
        have = (self._stat_total.get(uid, 0) if uid is not None
                else max(self._stat_total.values(), default=0))
        return have <= bar

    @staticmethod
    def _stat_sum(char: dict[str, Any]) -> int:
        """A character's total stats -- the single number that says whether it has grown
        since a requirement refused it. Deliberately the SUM rather than the specific stat
        the requirement named: the frame never tells us which stat was short, and the sum
        rises whenever `spend_xp` lands, which is exactly the event worth retrying on."""
        return sum(v for v in (char.get("stats") or {}).values() if isinstance(v, int))

    @staticmethod
    def _can_learn(char: dict[str, Any]) -> bool:
        """Room for another spell form? `spell_cap` is 1 + B(INT)//4 (docs/06), and at the
        cap a new form FORGETS the oldest, so learning there is a trade rather than a gain
        -- and not one we can evaluate until we have cast anything at all."""
        cap = char.get("spell_cap")
        if not isinstance(cap, int):
            return False                    # unknown capability -> do not guess
        return len(char.get("spells") or []) < cap

    def _tome_to_learn(self, uid: str, inv: list[dict[str, Any]],
                       can_learn: bool) -> dict[str, Any] | None:
        """The first carried tome this character could learn from, or None.

        Skips kinds the server has already refused for this character: INT gates which
        tomes you can use (docs/06), so a refusal is durable information about THIS
        character, not about the tome -- the same learn-by-rejection the equip slots and
        the forge recipes use.
        """
        if not can_learn:
            return None
        for item in inv:
            kind = item.get("kind") or ""
            bar = self._tome_failed.get((uid, kind))
            if kind.startswith(TOME_PREFIX) and (bar is None
                                                 or self._stat_total.get(uid, 0) > bar):
                return item
        return None

    @staticmethod
    def _scarce_keep_ids(inv: list[dict[str, Any]]) -> set[str]:
        """Item ids of SCARCE chain inputs to hold even when they are stranded.

        Two families, both measured going over the counter on run #135 while the chain
        that needs them was starved:

        * VIGOR herbs -- the only route to `potion_red`, which is what lifts
          POISON_SAFE_DEPTH. Read from `knowledge.ESSENCE` rather than listed here, so a
          newly decoded vigor herb is covered the moment the knowledge file learns it and
          this code needs no edit (the essence map is per-world DATA by design).
        * Raw ORE -- forge feedstock that FORGE_FEEDSTOCK_PREFIXES misses, since that
          tuple covers `ingot` but not the ore an ingot is smelted from.

        Capped at SCARCE_LONE_KEEP per KIND so this can never become the carry-clog the
        stranded-singleton rule exists to prevent.
        """
        by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for it in inv:
            kind = it.get("kind") or ""
            if knowledge.essence_of(kind) == "vigor" or kind.startswith("ore"):
                by_kind[kind].append(it)
        keep: set[str] = set()
        for g in by_kind.values():
            keep.update(it["item_id"] for it in g[:SCARCE_LONE_KEEP])
        return keep

    def _should_sell(self, item: dict[str, Any], eqp: dict[str, Any],
                     brew_keep: set[str], smelt_keep: set[str],
                     feedstock_keep: set[str] | None = None,
                     scarce_keep: set[str] | None = None,
                     can_learn: bool = False) -> bool:
        """Sell only what we can't use. Keep: field supplies (KEEP), medicinal
        drinks (potions/vials/elixirs/tonics), brew ingredients that can still form
        a batch (`brew_keep`), ore that can still form a smelt pair (`smelt_keep`),
        forge feedstock up to the per-char reserve (`feedstock_keep`, v0.46.0),
        and gear we might still equip. Everything else — pure loot, raw FOOD (which
        is `drink` but never eaten), AND stranded singleton brewables/ore
        (v0.8.0/v0.10.0) — is banked for gold, so food/herbs/ore don't hoard up and
        clog carry (v0.19.0: an unsold-food pack pinned chars `full` forever and
        drove the embark<->return thrash that kept gold from ever accumulating)."""
        kind = item["kind"]
        uses = item.get("uses") or []
        if kind in KEEP or kind.startswith(DRINK_KEEP_PREFIXES):
            return False
        # v0.59.0: a stranded SCARCE input is half a pair, not clutter -- keep a couple.
        if item["item_id"] in (scarce_keep or set()):
            return False
        # v0.63.0: a tome is a SPELL FORM, not loot. Kept only while this character can
        # actually learn from it -- at the cap a new form would forget the old one, so
        # there it really is surplus and the anti-clog rule stands.
        if kind.startswith(TOME_PREFIX):
            return not can_learn
        if "brew" in uses:
            return item["item_id"] not in brew_keep   # sell stranded brewables
        if "smelt" in uses:
            return item["item_id"] not in smelt_keep   # sell stranded (unpaired) ore
        # Checked BEFORE the pure-loot branch below -- that branch is exactly where lumber
        # and ingots were being lost, since they carry no recognised `uses`. Surplus above
        # the per-char reserve still sells.
        if kind.startswith(FORGE_FEEDSTOCK_PREFIXES):
            return item["item_id"] not in (feedstock_keep or set())
        if "equip" not in uses:
            return True                     # pure loot -> bank it
        if self._wont_fit(kind):
            return True                     # equippable but fails its stat requirement
        # v0.53.0: keep it if it out-values something we are WEARING. Without this the
        # upgrade pass never gets a turn -- selling runs first for any char whose slots
        # are all occupied or known-wrong, which is exactly the case an upgrade is for.
        if self._upgrade_slot(kind, eqp) is not None:
            return False
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

    def _needs_int(self, uid: str, inv: list[dict[str, Any]]) -> bool:
        """Is this character carrying a tome the server has already refused it on stats?

        Deliberately narrow. Not "holds a tome" — an unrefused tome may simply not have been
        tried yet, and the next village visit will try it. Only a character we have WATCHED
        be turned away has demonstrated that INT is what stands between it and a spell.
        """
        return any((uid, item.get("kind")) in self._tome_failed
                   for item in inv if str(item.get("kind", "")).startswith(TOME_PREFIX))

    @staticmethod
    def _pick_xp_stat(char: dict[str, Any], wants_int: bool = False,
                      int_only: bool = False) -> str | None:
        """The stat to raise next: the highest survival-priority stat (VIT>END>STR)
        that is BOTH below the cap AND affordable with the character's banked XP.

        v0.22.0: the old version returned the top priority regardless of cost, so a
        char stuck wanting an unaffordable VIT (whose cost grows with its value)
        never spent XP on a cheap END/STR it *could* afford — spend_xp logged 0
        across all history. Checking affordability here unblocks it (and naturally
        raises the cheap, low — i.e. most deficient — stats first). None once
        nothing is both needed and affordable (bank the rest)."""
        stats = char.get("stats", {})
        gifts = set(char.get("gifts", []))
        xp = char.get("xp", 0)
        # v0.88.0: a SEAT maxes INT — int_only banks everything for the next INT point
        # (stat cap 24 is the only ceiling; the operator's glass-ceiling directive).
        if int_only:
            v = stats.get("int", 0)
            if v < 24 and Explorer._xp_cost(v, "int" in gifts) <= xp:
                return "int"
            return None
        for s in (XP_PRIORITY_CASTER if wants_int else XP_PRIORITY):
            v = stats.get(s, 0)
            if v < XP_STAT_TARGET and Explorer._xp_cost(v, s in gifts) <= xp:
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

    def _retreat(self, uid, pos, ctx, blocked, offer, score, why, urgent=False):
        if pos[1] == 0:
            offer({"char_uid": uid, "action": "move", "dir": "S"}, score,
                  why + " (stepping off the south edge to the village)", urgent=urgent)
            return
        # EXPLICITLY UNBOUNDED, and this is not an oversight. Going home is not an errand:
        # a character may be at y=126 in the mines or y=199 in vale, and every caller here
        # is a survival behaviour — hurt and walking home to heal (8.5), fleeing undead
        # (7.2), pack-full (7.5). Capping this at FIELD_GOAL_RANGE would leave a hurt
        # character unable to find a route home and offering `rest` instead, which is the
        # stuck-death that v0.42.0 and v0.50.0 were both spent on. The bound exists for
        # OPPORTUNISTIC goals; retreat is the opposite of opportunistic.
        #
        # v0.80.1: routed with the FRESHNESS bias (nav.STALE_COST), because the walk home
        # is where run #164's 7x move_failed regression lived — deep trekkers retreating
        # across remembered-from-past-runs map, bouncing off regrown bush/rock/water (524
        # solid bounces, 239 of them under this very offer). A bias reorders among routes
        # and never removes one, so reachability — the stuck-death constraint — is intact,
        # and the only-stale-route case has a test.
        step = nav.weighted_step(pos, lambda p: p[1] == 0, ctx.known, blocked,
                                 fresh=ctx.fresh)
        if step:
            offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, step)},
                  score, why, urgent=urgent)

    @staticmethod
    def _step(pos, is_goal, ctx: FieldContext, blocked, max_depth: int | None = FIELD_GOAL_RANGE):
        return nav.bfs_step(pos, is_goal, ctx.known, blocked, max_depth=max_depth)

    @staticmethod
    def _intent_key(action: dict[str, Any]) -> str | None:
        """The identity of a village action worth latching — the ones that SPEND or that we
        watched storm. Selling is deliberately excluded: each sale names a distinct
        ``item_id``, so a repeat cannot double-spend the way a repeated ``buy {kind}`` can.
        """
        name = action.get("action")
        if name == "buy" and action.get("kind"):
            return f"buy:{action['kind']}"
        if name == "equip" and action.get("item_id") is not None:
            return f"equip:{action['item_id']}"
        return None

    @staticmethod
    def _intent_landed(key: str, char: dict[str, Any]) -> bool:
        """Has the frame caught up with this intent? Observation, not elapsed time."""
        what = key.split(":", 1)[1]
        inv = char.get("inventory") or []
        if key.startswith("buy:"):
            if any(i.get("kind") == what for i in inv):
                return True
            eqp = (char.get("equipment") or {}).values()
            return any(isinstance(v, dict) and v.get("kind") == what for v in eqp)
        if key.startswith("equip:"):
            # an equipped item leaves the inventory, so its absence IS the confirmation
            return not any(str(i.get("item_id")) == what for i in inv)
        return True

    def _village_act(self, bot, uid, action, why):
        # Record per-char village actions for the in-flight re-send guard (v0.14.0).
        # Guild-level actions (recruit/embark, uid=None) have their own guards.
        if uid is not None:
            self._village_acted[uid] = bot.tick
            key = self._intent_key(action)
            if key is not None:
                self._village_intent[uid] = (key, bot.tick)
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
