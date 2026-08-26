# BotGuilds server bugs

Suspected bugs, spec ambiguities, or surprising behaviours in the **BotGuilds
game server** (bot.willmorrison.net), to report to its developer. This is only
for the *game server* — not this bot, and not the reaper framework (reaper issues
go to /home/cal/reaper_bugs.md).

For each entry: what was observed, the frame/tick and conditions, what was
expected, and — where possible — a minimal reproduction. Keep it factual; the
game deliberately hides content, so "I don't know the recipe" is not a bug.

---

## SEC-1 (HIGH) — Guild token sent in CLEARTEXT over unencrypted TCP → session hijack

**Observed.** The game push API is a ZeroMQ DEALER→ROUTER socket over plain
`tcp://bot.willmorrison.net:5570` (per `guild_token.json` and docs 01/02/09). There
is no ZMQ CURVE encryption and no TLS. The `hello` handshake carries the guild's
long-lived bearer token as cleartext JSON: `{"type":"hello","guild_id":"g_…",
"token":"…"}` (docs/02-protocol.md line 36; steemer/client.py sends it via a plain
`json.dumps` with no crypto).

**Why it matters.** Any on-path observer (shared/hostile Wi-Fi, a compromised
router, an ISP/backbone tap, a malicious exit relay) can read the token off the
wire. Two documented behaviours turn a captured token into a full account takeover:
(a) "a new `hello` supersedes the guild's previous session" (client.py comment;
observed live as `kicked: another session hello'd as this guild — exiting`), and
(b) the token appears long-lived — it's minted once at guild creation and there's
no documented rotation/expiry. So one passive capture lets an attacker kick the
owner offline and issue actions as all of their characters, indefinitely.

**Expected.** Credentials should not traverse the network in the clear. Encrypt the
transport (ZMQ CURVE, or terminate TLS at a proxy / offer a `wss://` gateway),
and/or bind a token to a session/nonce so a replayed token can't silently seize an
active session.

**Repro.** Point tcpdump/wireshark at traffic to :5570 during a bot's `hello`; the
`token` field is visible in the first client frame. (Not exploiting — just noting
the field is cleartext.)

**Scope test (done, on our own guild).** Sent a `hello` with the correct
`guild_id` but a WRONG 32-char token while our legitimate session was connected. The
server replied `{"type":"hello_err","reason":"bad_token"}` and did **NOT** kick or
disturb the active session (frames kept flowing, no `kicked` line). Good: the
session-supersede requires a VALID token — so this is NOT a knows-the-public-guild_id
DoS (spectate exposes guild_id, but that alone can't kick anyone). It correctly
bounds SEC-1 to *token-capture* hijack.

**Token strength (analysed, our own token, not printed).** 32 chars of mixed-case
alphanumeric, ~4.6 bits/char Shannon entropy (near the sample ceiling), no structure
(base64→24 bytes of ~random binary), and NOT derived from the public guild_id. So
it's a genuine high-entropy secret (~190 bits if uniform over [A-Za-z0-9]) — good.
That means brute-force is a non-issue and this is purely a *transport* problem: the
one and only realistic path to the token is reading it off the unencrypted wire. Fix
= encrypt the transport (ZMQ CURVE / TLS proxy / wss). (Caveat: single-sample check —
comparing several freshly-minted tokens would confirm the generator has no
counter/timestamp/weak-RNG structure, but this one shows none.)

---

## ~~SEC-2 — `/api/spectate/guilds` full-roster disclosure~~ — NOT A BUG (intended)

Considered and dismissed: the unauthenticated full-roster/gear exposure via
`GET /api/spectate/guilds` is **intended** — spectate is deliberately public and
read-only, and all *mutating* endpoints (the `/me` path) are the ones that are
gated. So the read-only exposure is by design, not an oversight. (Kept here so it
isn't re-flagged in a future review.)

---

## ~~SEC-3 — guild `color` stored CSS-injection~~ — NOT A BUG (server validates)

Considered and **dismissed by test.** The concern was that the web client renders
the guild colour into `element.style.background` (reference_web/app.js ~line 657),
so an unvalidated value like `url(...)` would be a stored CSS-injection. Tested on
our own guild (logged in with write creds, then `POST /api/guild/color` with
`color = url(data:image/png;base64,…)`): the server rejected it with **HTTP 400
`{"error":"bad_color"}`**. So `/api/guild/color` validates server-side and does not
store arbitrary CSS — no injection. (Kept so it isn't re-flagged.)

---

_Notes: after review + testing, **SEC-1 is the only open issue** (cleartext token over
an unencrypted transport — encrypt it; the token itself is a strong ~190-bit secret,
so capture-on-the-wire is the sole realistic path). SEC-2 dismissed (public spectate
is intended; mutations gated on `/me`). SEC-3 dismissed by test (server rejects a
non-colour value with HTTP 400 `bad_color`). Testing was limited to our own guild
(a wrong-token hello, and a bad colour); no attacks on other guilds or the server.
Analysis by the steemer bot's owner for responsible disclosure._

## 2026-08-21 — RETRACTED: "per-world seq gaps" — the world-confinement was an artifact

Observed on run #120 (`explorer/0.50.1`), 86,395 frames stored over ~108 minutes, of which
58,808 (68%) carried the `delta` flag.

**31 discontinuities in `seq`, totalling 4,064 missed frames — 4.5% of the stream.**

What makes this look server-side rather than transport:

* **Every one of the 31 gaps is in `vale`.** Zero in `mines`, `spire` or `village`, which
  were streaming normally throughout. Network loss would not respect world boundaries.
* **The gaps are large and block-shaped**: median 138 frames, mean 131, max 356. At the
  observed ~11.9 frames/s that is a **~11-second blackout** per event, not a dropped packet.
  Largest: 356 @tick 1450674, 308 @1450884, 270 @1451709, 237 @1451529, 235 @1450470.
* **They are spread out, not bursty** — 31 separate events across 6,826 ticks, so it is not
  one bad minute.
* Our client is NOT behind: measured processing lag against the newest tick seen is 0
  throughout, and frame throughput is a steady 11.9/s with 3.9 ticks/s, matching earlier runs.
* The authoritative portal (`/api/spectate/guilds`) shows our roster stable at 10 across the
  whole window, and the ZeroMQ frames never name a character the portal lacks — so the
  frames are not inventing state, they simply stop arriving for a stretch.

**Consequence for a client.** During each ~11s blackout we keep acting on the last known
world state; characters move, return to the village, or are replaced, and the commands we
send then bounce. On this run that showed up as `unknown_character` at 104/1k frames (vs
1.1/1k two runs earlier), `not_in_village` at 115/1k, and `out_of_range` elevated — the
error rate rose from 12.7% to 42.9%. The correlation is direct: bucketing the run into
eighths, the dropped-frame rate goes 0,0,0,0,22,228,172,0 per 1k and the
`unknown_character` rate tracks it.

**What would help a client most**, if the underlying stall cannot be removed: on resuming
after a gap, mark the affected world's state as stale until a full frame arrives, or emit an
explicit "you missed N frames" marker. Right now a gap is only inferable from a `seq` jump,
and a client cannot tell a stall from a silent resync.

Reported with a specific hypothesis rather than a diagnosis: we can see the gaps and their
shape, but not what produces them.

### RETRACTION (same day, before anyone acted on it)

**The central claim above — that every gap was confined to `vale` — is WRONG, and the
report should not be sent to the server author.**

`seq` is GLOBAL, not per-world. It round-robins across the worlds a guild has characters
in: `vale=1, mines=2, village=3, vale=4, …`. So a gap spanning whole tick-cycles simply
resumes at whichever world comes next in the rotation, and `vale` leads it. "All 31 gaps in
vale" was an artifact of never checking that assumption, and it was the load-bearing
argument for calling this server-side.

**What the evidence actually shows, having looked properly:**

* Across a gap, the very next frame arrives in a median of **9 ms**. A server-side stall
  would make that interval as long as the gap (~11 s). Frames resume *immediately* with
  jumped sequence numbers, which is the signature of messages being **discarded**, not
  delayed or withheld.
* The connection is stable throughout: the gaps appear back to back in the log with no
  reconnect, no `silent 10s` re-hello, and no kick between them.
* **Our consumer is periodically too slow.** Against a production rate of ~12 frames/s (3
  worlds x ~4 ticks/s, an 83 ms budget per frame), **34% of frames take longer than 83 ms**
  to handle, 12.3% exceed 200 ms, and the worst observed is **2,972 ms**.

A ZeroMQ DEALER drops rather than blocks when its send queue is full, so a slow consumer
produces exactly this: a healthy connection, no stall, and holes in the sequence.

**Conclusion: this is OUR bug, not the server's.** It belongs in the client, and the fix is
to get the per-frame work off the receive path. Left in this file only as a record of the
retraction — a wrong report to a third party is worse than no report.

## Frame `guild.inventory` is a stale/phantom manifest (2026-08-23, runs #160–#161)

The village frame's `guild` dict carries live `gold` (updates every sale/buy) alongside an
`inventory` list that appears frozen: 404 `bottle_empty` + 202 `potion_red` + 14 `club`,
identical across runs #159–#161 and across server restarts. `drop {item_id}` in the
village — documented in 03-actions.md as "moves an item *out of* guild inventory onto the
character" — was rejected `no_such_item` for the first EIGHT distinct potion `item_id`s in
that list (13913, 13914, 13949, 13965, 14116, 14126, 14128, 14259), two attempts each,
from characters standing in the village.

Either the inventory snapshot is stale (items long consumed, list never compacted), or the
ids are re-keyed server-side, or village-`drop` does not implement the documented
withdrawal. Any of the three makes the manifest unusable as a source of truth. Our client
now fails closed after 8 phantom ids (explorer/0.78.1) rather than storming.

Repro: connect, read any village frame's `guild.inventory`, `drop` the first item_id from
a village character → `no_such_item`.

## Frame ghosts: dead-to-the-roster characters keep rendering in world frames (2026-08-23, run #179)

A character the action handler no longer recognises (`unknown_character` on every
command) continues to appear in that world's frame `chars` list, tick after tick, at a
fixed position. Observed on `g_cd0e2a_c18748`: present in consecutive spire frames at
ticks 2176242-2176246 while `move` commands sent for it in the same window were refused
`unknown_character`. The divergence class began after involuntary portal transits
(portal (63,0)->(57,44), vale): some transited characters die normally, others vanish
from the roster with NO death event, leaving a renderable ghost. Cost to a client that
trusts frames: it commands the ghost forever (1,481 unknown_character errors this run).

Repro sketch: walk a character onto vale (63,0), let the portal fire, then keep
commanding it; if it entered the vanish state, frames still render it while every
command bounces.

## roster_cap counts village-present chars, not total roster (2026-08-23, run #184)

The server enforces `roster_cap` (default 30) at the `recruit` action — confirmed by
1,597 `roster_cap` action-error refusals across runs. But the count it checks is
characters PHYSICALLY IN THE VILLAGE, not the total roster: on run #184, recruits
succeeded while the true roster (village + fielded) was already 31, with zero roster_cap
refusals in that run. Reproduced pattern: recruit @tick 2221263 succeeded with 30 in the
village frame and 1+ fielded elsewhere.

Consequence: with k characters fielded/adventuring, the total roster can be grown to
roughly 30 + k by recruiting to refill the emptied village barracks. Whether this is
intended (a barracks-occupancy cap) or a bug (the cap was meant to bound total roster)
is undetermined. Observed, not exploited.

## Guild inventory listing is (almost) entirely phantom (2026-08-24, runs #197-#205)

The village frame's `guild.inventory` lists 404 `bottle_empty`, 202 `potion_red`, 14
`club`, ~30 `lumber`. Withdrawing (`drop {item_id}` in the village) is refused
`no_such_item` for every potion and club id probed — 20 distinct ids across runs
#197-#205, spanning the HEAD of the potion list and 4/4 club probes — while the listing
itself never shrinks. The 404 bottles were already documented phantom (see the earlier
entry). Lumber withdrawals have succeeded historically (0.98.0's smith pipeline), so the
staleness is item-kind- or age-correlated, not universal. Working hypothesis: consumed/
expired stack entries are never garbage-collected from the listing. Cost to a client
that trusts the listing: it budgets around ~600 items of wealth that do not exist (our
heal economy planned around "202 banked potions" for a week). Client-side mitigation
shipped: phantom ids persist across runs (intel `vault_phantom`) with a bounded per-run
probe budget; each run walks deeper into the list. If any tail entries are real, that
will eventually surface — none found in the first 20.

## Character in server limbo: alive to the roster, refused by every handler (2026-08-24, run #202)

`g_cd0e2a_c19532`: NO death event ever, listed in the village frame's
`guild.chars_here` continuously, but EVERY command for it — village moves, buys, embark
— is refused (`not_in_village` x23,109 + `unknown_character` x5,565 over ~50k ticks in
one run). Distinct from the frame-ghost entry above (2026-08-23): that ghost RENDERED in
world frames after vanishing from the roster; this one is the inverse — the roster
lists it, no world frame renders it, and the handlers refuse both village-context and
world-context actions. It never recovered. Client mitigation shipped: quarantine on
refusal (GHOST_TTL). Repro unknown; began near a run boundary/redeploy window.

## The world tick clock stalls for hours while frames keep flowing (2026-08-24, 08:10-15:20+ EDT)

Measured from our frame stream (frame `received_at` vs `tick`): normal service
(~130-230 ticks/10min) until ~08:10 EDT, then a step change: a 2h10m DEAD STOP
(08:40-10:50, zero tick advancement), one 1,527-tick burst at ~10:50 (2-3x normal rate
— catch-up shaped), sputtering dribbles 11:30-12:50, and near-total freeze from 13:00
onward (two small bursts; still frozen at 15:20). Cumulative real game-time in 7 hours:
~45 minutes. Throughout, frames CONTINUE to arrive every few seconds carrying the same
tick — so the connection, frame pump, and handlers are up; only the simulation clock is
stopped. The pause-then-sprint shape suggests the server process being suspended and
resumed (host sleep? VM migration?) rather than load, which degrades gradually. Effect
on clients: every tick-driven mechanic (band refreshes, cooldowns, regen) is frozen —
a bot can look "idle/broken" while behaving correctly against a stopped world.

## Wire v3 addendum: the grouped vault's `count` is a tally of ghosts (2026-08-25, runs #204-#212)

The v3 regrouping exposed the full shape of the phantom-inventory bug: the potion_red
stack lists `count: 202` with 202 `item_ids`, and **78 distinct ids probed across
runs — head AND tail of the list — all answer `no_such_item`, with zero successful
withdrawals ever**. The docs' "use any of those ids in actions" therefore reads as
"any valid id", and this stack appears to contain none: the count is a tally that
survived whatever consumed the items (drunk potions? old brews?) and the regrouping
compacted the stale ids rather than collecting them. Repro: `drop` any id from the
potion_red group's `item_ids` in the village. Contrast: lumber withdrawals succeed,
so the staleness is kind- or event-correlated, not universal. Client mitigation:
probe only ids NEWER than the newest known phantom (ids ascend with creation), so a
genuinely new banked item is tried automatically and the graveyard is never re-walked.

### Evidence strengthening (2026-08-25, on operator request for verification rigor)

Verification is necessarily single-session (a second authenticated client risks the
single-session kick-war), so three within-session axes substitute for independence:

1. **Live-vs-frozen kind contrast** (the decisive one): one village frame sampled per
   run across #190-#213 (~200k ticks). `lumber` count ticked 20 -> 40 (deposits land,
   withdrawals succeed — the listing machinery demonstrably UPDATES), while
   `potion_red` (202), `club` (14), and `bottle_empty` (404) never moved once. Same
   listing, same session, same serializer: one kind live, three fossils.
2. **Format-migration invariance**: the phantom ids survived the v2->v3 wire rewrite
   byte-identical (the v3 potion group's first 8 item_ids are exactly the 8 ids probed
   dead under v2) — two different server serialization paths agree on the stale data,
   so the rot is in the underlying store, not a serializer.
3. **Cross-run, cross-restart persistence**: 78 distinct ids probed dead across 9+
   client restarts and both wire formats; zero successes ever.

Also noted: the server's own web viewer (web/app.js, sha de9a52bd..., baselined) reads
only `count` from the grouped inventory and never dereferences `item_ids` — the ids'
validity is exercised by nothing but the `drop` action, which is presumably how the
rot went unnoticed.

## Frame ghosts, live-char edition: a RETURNED char renders frozen in its old world (2026-08-25, run #214)

The 2026-08-23 frame-ghost entry covered dead-to-the-roster chars. Run #214 shows the
same render bug for a LIVE char: c19534 returned to the village (its village frame
listed it; village actions worked), but the MINES frames kept rendering it at a frozen
position (20,7) with stamina **64 of a 56 max** — an impossible value, a corrupt/stale
snapshot — for ~2,000 ticks. Any client that trusts world-frame residency commands the
ghost forever (we ate 3,654 `not_in_village` before mitigating). Signature for
detection: frame-char state (pos/stamina/hp) identical across many ticks, stamina
possibly above max. Mitigation shipped client-side: world-frame sightings only count
as proof-of-life when the state CHANGES between sightings.

## Frame ghosts, LETHAL edition: an input-paralyzed char takes damage but no commands (2026-08-25, run #215 — KILLS CHARACTERS)

Third manifestation of the entity-lifecycle bug family, and the worst. Recruit-19575,
mines (13,17), bat_brown swarm adjacent, ticks 2530752-2530759:

- our client commanded `move S` EVERY tick (south tile: clear floor, verified);
- the server neither executed them (pos frozen for 8 ticks), errored them (zero
  action_errors during the fight — the unknown_character flap starts only AFTER
  death), nor bounced them (zero move_failed events);
- the char's stamina sat FROZEN at 48 the whole time — no move costs deducted AND no
  regen applied, so its server-side actor loop was not running at all;
- meanwhile combat resolution still targeted it: seven bat_brown `attack` events
  landed (hp 13 -> 7 -> 4 -> 1 -> dead) and the death dropped its kit.

Signature for detection: commands accepted silently (no error, no effect), pos AND
stamina frozen across ticks, hp changing only from incoming attacks, statuses empty.
Family resemblance: c19532 (roster limbo, refuses loudly), c19534 (frozen render
after returning home), and now this — alive, attackable, and input-dead. All three
observed within the wire-v3 deploy window (2026-08-24/25), suggesting the change
exposed or introduced an actor-lifecycle race. Client-side there is NO mitigation:
the char cannot move, fight, or heal — it is doomed from the first eaten command.
Priority for the server: this one costs permadeath characters through no fault of
the client.

## Error echo: one rejected command produces ~20 `action_err` messages (2026-08-25, run #215)

Windowed evidence (airtight): our client sent exactly ONE `move` for c19579 at tick
2530529 (`actions_sent` has the single row); the server answered with ~20
`not_in_village` action_err messages spread across ticks 2530531-2530550. The char was
village-resident and village-listed the whole window — the rejection itself is
plausible (a stale-frame command); the AMPLIFICATION is not. Effect: error-rate
telemetry inflates ~20x per rejected command, which turned a handful of stale-frame
flaps into what read as a 719-error storm client-side. Same 2026-08-24/25 window as
the entity-lifecycle family; possibly the same underlying actor-queue fault
re-delivering the rejection each tick until the queued command expires. Detection:
multiple identical action_err for one (char, action) with NO matching actions_sent
rows between them.

## Silent character disappearances, quantified (2026-08-25, run #220)

39 successful `recruit` events against 2 recorded deaths on a roster that spectate
reports stable at 30 — ~37 characters left the roster in one run with NO death event.
The client's roster count chronically reads 29/30 (one char invisible to every
counting surface), so its recruit gate kept refilling, and each refill bought a 15g
club: the vanish bug converted the guild's entire run income (~585g) into equipment
for bodies that then evaporated. Same entity-lifecycle family as the limbo/frozen-
render entries; this is its economic cost. Client mitigation shipped: recruit
throttling (chronic shortfall <= 3 refills at most once per 2,000 ticks).

## Batch silent disappearances while FIELDED (2026-08-25, run #224) — the strongest characterization yet

**13 of 27 roster chars vanished in ~20k ticks, 12 of them batch-clustered in a ~3k-tick
window (t≈2,761,000–2,764,000), with exactly ONE death event among them.** Evidence chain:

- Roster (village `chars_here` + `chars_by_world`, deduped uids): 27 at t2750566 → 17 at
  t2771227. Gone: c19749, c19762, c19774, c19781, c19782, c19789–c19795 (seven
  CONSECUTIVE uids), c19798. Only c19798 has a death event (cultist, mines).
- **All 12 silent ones were last seen FIELDED** (not benched) — refutes an idle/bench
  garbage-collection hypothesis we explicitly tested.
- No client-side cause window: zero village-frame gaps >30t in the window, no reconnects
  (last hello t2748246, well before), no error storms.
- Death attribution is NOT the issue: the same window carries 9 fully-attributed rival
  deaths (g_001df9 Scholars, spire vampire_bat band) plus our one attributed death —
  the server emits proper char death events; these chars simply never got one.
- Cost this run is contained by 0.115.0 (recruit toward field demand 18): the deep bench
  absorbed 9 vanishes for free; the drip refilled 4 at exactly 2000-tick spacing only
  once the roster fell below 18. Pre-0.115 this window would have burned ~200g of clubs.
- STRATEGIC exposure: the vanished include earlier top-INT wizard candidates (c19781,
  c19793) — the INT/tome pipeline can be silently decapitated. Likely the same class as
  the c19532 roster-limbo entry above, now observed as a fielded BATCH.

**Recurrence (same run #224, t≈2,791,700-2,792,400):** a second batch — roster fell to ~10
(five wipe-cadence refills at ~100t spacing prove the read), ~30k ticks after the first
batch. Of 20 chars recruited across the run, only 10 remained at t2792400 (3 died with
events, ~7 vanished silently). The vanish tax measured this run: ~1.45 chars/1k ticks
≈ 22g/1k in replacement clubs — the whole margin of a coin-average band. Pattern:
batches ~30k ticks apart, always fielded chars, never death events.

**DECISIVE (run #224 late, t≈2,788,000–2,802,900): chars are deleted SERVER-SIDE, and the
drain went continuous.** 25 chars vanished in ~14k ticks (~1.8/1k, tripled from the early-run
rate) with zero death events. The public spectate API (`/api/spectate/guilds`) confirms
roster=15 — matching our frames — so this is genuine server-side deletion, not frame-side
invisibility/limbo. **7 of the 25 vanished while sitting in the VILLAGE** (c19810, c19813,
c19817, c19818, c19820, c19823, c19826) — not band danger, not deep-field state. Fresh
recruits are heavily represented (c19809–c19829 cohort, many gone within 2–5k ticks of
recruitment), though the roster is mostly fresh recruits by now (confounded). The drain
began/accelerated mid-run — if a server deploy landed today, a char-cleanup/GC regression
is a plausible shape. Our recruit spend at this rate: ~30g/1k (clubs), pinning guild gold
at ~0-11 despite healthy income — the tome/magic pipeline is fully blocked on this bug.

## CONCLUSIVE (2026-08-26 ~02:55): per-guild frame PRODUCTION lag — the server builds our
## guild's frames slower than real time; the guild is fully paralyzed

Measured directly: public `/api/spectate/guilds` reports tick **2,862,974** while our
freshest delivered frame is tick **2,862,783** — **191 ticks (~48 s) behind**, up from 22
ticks at session birth ~20 min earlier, i.e. the offset GROWS ~0.1 s/s even though the
client now consumes at wire speed. Every action we send is therefore stale on arrival:
**0 of our moves have landed for hours** (4,352 stale_frame rejections in the last 1.3k
ticks alone). Rivals are unaffected (their move volume unchanged all night), so the lag
is OUR GUILD's frame pipeline server-side.

Client-side exhausted, all shipped + verified tonight: 0.115.1 self-heal re-hello (fired
autonomously; sessions inherit the lag — it is per-GUILD, not per-session), 0.115.2
decide-on-freshest (we no longer add ANY client-side backlog; verified by wall==tick-
implied consumption). Tick-compensation was considered and rejected: the offset grows
without bound, so no constant correction converges.

Hypothesis for Will: our guild's server-side state was churned hard today by the char
DELETION bug (~100 chars silently deleted + our recruit refills). If frame assembly
walks any per-guild registry that never GCs deleted chars, our build cost now exceeds
tick_seconds — matching the growth curve, the cross-session persistence, and the
guild-specificity. A server restart or a purge of our guild's dead-char state should
confirm. (Also observed: guild color changed #00ffff -> #ff8000 tonight — if a manual
poke at guild state happened, that's a correlation datum, not an accusation.)

EXPOSURE while this stands: ~7 fielded chars cannot flee (permadeath); the guild cannot
recruit, embark, gather, or bank.

**Addendum (~04:20): the guild now DUTY-CYCLES.** The 0.115.1 self-heal fires at its
hysteresis floor (~every 2,400t): each re-hello buys a brief clean window (offset ~0-1,
actions LAND — 8 embarks observed in one window) before the lag rebuilds; windows have
shrunk from ~6.7k ticks (first fresh session tonight) to ~300 ticks now. Working
hypothesis FOR WILL: each re-hello may leave a dead session the server keeps preparing
frames for (we're 213 connects lifetime, dozens tonight) — per-guild frame-production
cost grows with every reconnect, which fits the monotonically shrinking clean windows.
Check the server's session GC for our guild. If sessions do GC on a timer, our next
mitigation is to reconnect LESS (raise heal hysteresis), not more.

**Trend (~04:25):** the deep lag is back and at its worst — offset 332 ticks (~83 s),
3,076 rejections/600t, 0 actions landing. Remission windows tonight: ~6.7k ticks, then
~300, then ~2.0k, then a ~4k-tick healthy stretch (~03:40-04:00, offset 3-5, 179 landed
moves/300t), now the deepest storm yet. The oscillation pattern (recovery without any
action on our side, then regression) reads like the server intermittently catching up
and falling behind on our guild's frame pipeline. Our deaths tonight: 4 this run — chars
stranded mid-field during paralysis windows cannot flee. INT pipeline decapitated a
3rd time (c19796, INT 4, vanished in the storms; top survivor is INT 2).
