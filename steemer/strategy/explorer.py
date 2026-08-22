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

from .. import knowledge, nav
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
UNDEAD_SEVERE_GUARDIAN = 0.08  # veteran trips "severe" at half the undead fraction...
MELEE_DENSE_GUARDIAN = 2       # ...and at 2 melee predators (disengage early)
UNDEAD_SEVERE_FORAGER = 0.20   # recruit tolerates a denser band before disengaging...
MELEE_DENSE_FORAGER = 4        # ...and needs 4 melee predators to call it severe
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
                           "rat_grey", "mole", "bat_brown"})
# Confirmed-dangerous kinds seen so far (documentation only — the LOGIC uses the
# allowlist above, so this need not be exhaustive): golem_stone, delver, boar, drake,
# lake_drake, spider_brown, wolf, crab_green, lava_ant, rhino_beetle.
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
SAY_SCORE = 2.1
SAY_READY_FRAC = 0.9       # ...and only from a character with nothing to gain by resting.
# The first draft claimed "it can only displace an idle rest tick" and that was FALSE:
# rest is also the RECOVERY action, and it wins exactly when a character is too tired to
# do anything else. Three decision-engine tests caught it — a character with no affordable
# action was talking instead of recovering. A rest is only idle when hp and stamina are
# already topped up, so that is the gate. `max_stamina` is absent -> treated as NOT ready,
# because the conservative reading of missing data is the one that cannot cost a recovery.
POTION_KEEP = 1            # potions to carry into the field per character

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
POTION_RESERVE = 150       # never let the potion-buy pull the treasury below this
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
ARMOR_BUY_FLOOR = 200

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
WEAPON_BUY_FLOOR = 150

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
DEVELOP_HP = 0.7          # only pick a fight comfortably above the 0.6 retreat line
DEVELOP_STAMINA = 15      # enough stamina to attack AND still afford a step to disengage
COMBAT_SEEK_RADIUS = 5    # seek wildlife / gauge predator density within this many tiles
COMBAT_SWARM = 2          # >=2 melee predators within reach -> too dangerous to fight, flee

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

EMBARK_COOLDOWN = 8   # v0.10.0: after commanding a char to embark, don't re-send
#   that char's embark for this many ticks. The village frame we decide on is a few
#   ticks stale, so a just-embarked char still shows in `chars_here` — without the
#   guard the bot re-embarks it every tick and the tail bounces no_such_character
#   once it finally leaves. Observed embark latency ~3 ticks; 8 is safe headroom and
#   still retries a genuinely-failed embark after ~2 s.
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


def role_of(char: dict[str, Any]) -> str:
    """v0.39.0 per-character role, derived from level (not stored, so it self-adjusts as a
    char levels up). A leveled veteran is a GUARDIAN (worth protecting -> disengages early);
    a fresh recruit is a FORAGER (cheap -> works the edges of danger for income). Shared by
    the strategy (biases the severity threshold) and the dashboard (shows the role), so the
    role has ONE source of truth."""
    return "guardian" if (char.get("level") or 0) >= GUARDIAN_LEVEL else "forager"


class Explorer:
    version = "explorer/0.75.1"

    def __init__(self) -> None:
        # Equip-slot learning (persists across frames): slots a kind has been
        # rejected from (wrong_slot), and kinds that fail a stat requirement.
        self.slot_wrong: dict[str, set[str]] = defaultdict(set)
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
        # v0.52.0: a REJECTED forge teaches us its recipe was wrong. Record the exact
        # (product, ingots, lumber) so it is attempted once and never again — the recipe
        # quantities are undocumented, so the server's rejection IS the documentation.
        # v0.74.0: `say` is an action we had never sent before. If the server refuses it,
        # stop — a rejected action every cooldown would be a slow error-spam of exactly the
        # kind the anomaly monitor exists to shout about.
        if message.get("action") == "say":
            bot.chatter.note_rejected()
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
        gold = guild.get("gold", 0)
        self._learn_prices(frame)
        self._hydrate_forge(bot)

        for char in chars:
            uid = char["char_uid"]
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
            for item in inv:
                if self._should_sell(item, eqp, brew_keep, smelt_keep, feedstock_keep,
                                     scarce_keep, can_learn):
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
            if eqp.get("hand") is None and gold > WEAPON_BUY_FLOOR:   # v0.40.0: arm above the floor
                buy = self._afford_weapon(char, frame, gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying a {kind} ({price}g; bare-handed — arming to break the poverty trap)")]
            # 3b) ARMORED, not just armed (v0.47.0). Only once the hand is filled, and
            #     only above ARMOR_BUY_FLOOR (> the weapon floor), so arming a bare char
            #     always outranks armoring an equipped one.
            if eqp.get("hand") is not None and gold > ARMOR_BUY_FLOOR:
                buy = self._afford_armor(char, eqp, frame, gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying {kind} ({price}g; armouring an empty slot -- we have "
                        f"never bought armor and rivals field ~60% armored)")]
            # 4) HEAL FROM SURPLUS (v0.29.0): the 0.24.0 hoard froze potion-buying;
            #    now that a stockpile exists (0.28.0), spend its SURPLUS on the one
            #    thing that outruns poison's DoT — a field heal for a potion-less
            #    char — but only while gold stays above POTION_RESERVE, so the hoard
            #    floor holds and keeps climbing. Run #84 proved the need: a poison
            #    cycle bled potion-less chars out mid-retreat (deaths 0.2 -> 2.23/1k).
            potions_held = sum(1 for i in inv if i["kind"] == "potion_red")
            if potions_held < POTION_KEEP:
                buy = self._afford_potion(frame, gold)
                if buy is not None:
                    kind, price = buy
                    return [self._village_act(
                        bot, uid, {"char_uid": uid, "action": "buy", "kind": kind},
                        f"buying a {kind} ({price}g from surplus; a heal to outrun poison's tick)")]
            # 4b) brew looted ingredients into potions — but only with a bottle we
            #     already hold; the bottle-BUY is frozen too (hoard). Free potions
            #     from foraged herbs still help protect a char's carried loot.
            bottles = sum(1 for i in inv if i["kind"] == "bottle_empty")
            picks, ess, healing = self._choose_brew(brewables)
            # 4a-bis) BUY A BOTTLE (v0.58.0) -- but only for a character that could brew
            # RIGHT NOW if it had one. Gating on `picks` is what makes this provably
            # useful rather than a standing 2g tax: it means the herbs are already in the
            # pack and a bottle is the only missing part. Ordered AFTER arming and
            # armouring, so a bare character is never left bare for a bottle, and floored
            # at WEAPON_BUY_FLOOR so the 2g can never eat into arming money.
            if picks and bottles < BOTTLE_KEEP and gold > WEAPON_BUY_FLOOR:
                price = self._shop_price(frame, "bottle_empty")
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
            forge = self._choose_forge(inv, eqp, char.get("stamina", 0))
            if forge is not None:
                recipe, item_ids, why = forge
                self._forge_attempt[uid] = recipe        # (product, n_ingot, n_lumber)
                return [self._village_act(
                    bot, uid, {"char_uid": uid, "action": "forge",
                               "product": recipe[0], "item_ids": item_ids}, why)]
            # 5) spend banked XP on durability (safe in the village).
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

        # In-flight guard (v0.10.0): drop embark records for chars that have left
        # the village (their embark landed), then treat the rest as still pending
        # so we neither re-embark them nor count them as home for the world cap.
        tick = bot.tick
        here_set = set(chars_here)
        self._embark_at = {u: t for u, t in self._embark_at.items() if u in here_set}
        inflight = {u for u, t in self._embark_at.items() if tick - t < EMBARK_COOLDOWN}

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
        recruit_target = min(world_cap, roster_cap, party_cap * len(maps) + RECRUIT_BENCH)
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
        if roster < recruit_target and (
                self._recruit_at is None or tick - self._recruit_at >= RECRUIT_COOLDOWN):
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
        if here_avail and fielded + len(inflight) < world_cap:
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
                target = min(open_maps, key=lambda m: (threat(m), by_world.get(m, 0)))
                uid = here_avail[0]
                self._embark_at[uid] = tick
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
        for mp, en in ctx.enemies.items():
            if self._is_melee_predator(en.get("kind")):
                blocked |= (set(nav.neighbors(mp)) - chest_access)

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
        develop = (armed and not homing and hp >= max_hp * DEVELOP_HP
                   and stamina >= DEVELOP_STAMINA)
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
                    role = role_of(char)
                    has_value = bool(ctx.gold or ctx.loot or ctx.containers)
                    if role == "forager" and has_value:
                        uf, dn = UNDEAD_SEVERE_FORAGER, MELEE_DENSE_FORAGER
                    else:
                        uf, dn = UNDEAD_SEVERE_GUARDIAN, MELEE_DENSE_GUARDIAN
                    severe = undead_frac >= uf or len(preds) >= dn
                    score = SPACE_SCORE_SEVERE if severe else SPACE_SCORE_CALM
                    band = "severe" if severe else "calm"
                    label = role if (role == "guardian" or has_value) else "forager(barren)"
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
        form_up = bool(allies) and not homing and self._world_is_dangerous(ctx.world, bot.tick)
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
                gstep = self._step(pos, lambda p: p in ctx.gold, ctx, blocked)
                if gstep:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, gstep)},
                          5.0, "beeline to a gold coin (instant banked gold)")
                    productive = True
                cstep = self._step(pos, lambda p: any(n in ctx.containers for n in nav.neighbors(p)),
                                   ctx, blocked)
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
                lstep = self._step(pos, lambda p: p in loot_goal, ctx, blocked)
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
            if develop:
                wild = {p for p, en in ctx.enemies.items()
                        if en.get("kind") in WILDLIFE_SAFE
                        and abs(p[0] - pos[0]) + abs(p[1] - pos[1]) <= COMBAT_SEEK_RADIUS}
                if wild:
                    wstep = self._step(pos, lambda p: any(n in wild for n in nav.neighbors(p)),
                                       ctx, blocked)
                    if wstep:
                        offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, wstep)},
                              3.5, "develop: closing on wildlife to farm XP")
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
                    VEIN_SEEK_RANGE_HEALED if healed else VEIN_SEEK_RANGE)
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
            has_heal = any(i.get("kind") == "potion_red"
                           for i in char.get("inventory", []) or [])
            if not has_heal and pos[1] >= POISON_SAFE_DEPTH:
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

                north = self._step(pos, lambda p: p[1] > pos[1] and nav.frontier(p, ctx.known, ctx.bounds), ctx, blocked)
                if north:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, north)},
                          FRONTIER_NORTH_SCORE, "pushing north into unexplored ground")
                    productive = True
                any_frontier = self._step(pos, lambda p: nav.frontier(p, ctx.known, ctx.bounds), ctx, blocked)
                if any_frontier:
                    offer({"char_uid": uid, "action": "move", "dir": nav.step_dir(pos, any_frontier)},
                          FRONTIER_SCORE, "heading to the nearest frontier")
                    productive = True

                # v0.36.0 DEPLETION-AWARE retreat: nothing to grab and nowhere to explore
                # -> this world is looted-out for us. Rather than scout-wander (below) and
                # idle exposed, head HOME to re-embark somewhere fresher — UNLESS a refresh
                # is about to replenish coins right here, in which case wait it out.
                if not productive:
                    nr = frame.get("next_refresh") or {}
                    in_ticks = nr.get("in_ticks")
                    refresh_soon = isinstance(in_ticks, int) and in_ticks <= REFRESH_STAY_TICKS
                    if not refresh_soon:
                        self._retreat(uid, pos, ctx, blocked, offer, 1.5,
                                      "world looted-out, no refresh imminent — home to re-embark")

                for d, (dx, dy) in nav.DIRS.items():
                    nxt = (pos[0] + dx, pos[1] + dy)
                    if nav.is_walkable(nxt, ctx.known, blocked):
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
        for item in inv:
            kind = item["kind"]
            if "equip" not in (item.get("uses") or []) or self._wont_fit(kind, uid):
                continue
            slot = next((s for s in EQUIP_SLOTS
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
        d = self._world_danger.get(world or "")
        if not d or tick - d[2] >= THREAT_TTL:
            return False
        return d[0] >= UNDEAD_SEVERE_GUARDIAN or d[1] >= COHESION_PRED_DENSE

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
        cx = sum(a[0] for a in allies) // len(allies)
        cy = sum(a[1] for a in allies) // len(allies)

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
    def _ore_step(pos: tuple[int, int], ctx: "FieldContext", blocked,
                  reach: int = VEIN_SEEK_RANGE) -> tuple[int, int] | None:
        """One step toward the nearest known ORE tile within ``VEIN_SEEK_RANGE``, or None.

        The goal tile is SOLID (a vein is scenery you break, not ground you stand on), so
        this asks for the step that brings us ADJACENT to it and lets slice 1's
        adjacent-harvest offer do the breaking. bfs_step already permits a goal tile to be
        entered when nothing else is; here we never want to enter it, only to reach its
        neighbour -- which is why the goal is "a walkable tile beside a vein", not the vein.
        """
        def beside_ore(t: tuple[int, int]) -> bool:
            return any(ctx.known.get(n) in ORE_KINDS for n in nav.neighbors(t))
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

    @staticmethod
    def _afford_potion(frame: dict[str, Any], gold: int) -> tuple[str, int] | None:
        """The field heal (``potion_red``) from live shop stock, but ONLY if buying
        it leaves the treasury at or above POTION_RESERVE (v0.29.0 heal-from-surplus).
        Prices read from the frame, never hardcoded. ``None`` if out of stock or the
        buy would dip the hoard below the reserve — so the stockpile floor holds."""
        stock = (frame.get("shop", {}) or {}).get("stock", []) or []
        for s in stock:
            if s.get("kind") == "potion_red" and isinstance(s.get("buy_price"), int):
                price = s["buy_price"]
                if gold - price >= POTION_RESERVE:
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
        for product in FORGE_PRODUCTS:
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
    def _pick_xp_stat(char: dict[str, Any], wants_int: bool = False) -> str | None:
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
        step = self._step(pos, lambda p: p[1] == 0, ctx, blocked, max_depth=None)
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
