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

## ~~SEC-2 — `/api/spectate/guilds` full-roster disclosure~~ — NOT A BUG (intended)

Considered and dismissed: the unauthenticated full-roster/gear exposure via
`GET /api/spectate/guilds` is **intended** — spectate is deliberately public and
read-only, and all *mutating* endpoints (the `/me` path) are the ones that are
gated. So the read-only exposure is by design, not an oversight. (Kept here so it
isn't re-flagged in a future review.)

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

_Notes: SEC-1 is confirmed from the wire format/docs (the real one to fix). SEC-2 was
considered and dismissed — public spectate is intended (mutations are gated on the
`/me` path). SEC-3 depends on whether the server validates the colour (needs Will to
check). None were exploited — no malicious payloads were sent to the live server.
Analysis by the steemer bot's owner for responsible disclosure._
