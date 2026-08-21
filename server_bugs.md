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

## 2026-08-21 — large per-world gaps in the frame `seq` stream, confined to ONE world

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
