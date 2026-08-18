# reference_web — vendored server web client

`app.js` is a verbatim copy of the BotGuilds web dashboard's client script,
fetched from **https://bot.willmorrison.net/web/app.js**. It is reference-only —
never imported, executed, or bundled. We keep it here for the same reason we
vendor `reference_starter_kit`: it is the richest public description of the
server's **HTTP/SSE surface**, and the wire (ZeroMQ) protocol our bot speaks does
not document those endpoints. A new useful endpoint tends to appear here first.

## Keeping it current

Periodically (each improvement tick, alongside the submodule check):

```bash
uv run tools/check_webclient.py            # report drift vs this copy
uv run tools/check_webclient.py --update   # re-fetch, then `git diff` to review
```

Review the diff and *deliberately* decide whether to wire any changed/new
endpoint into the bot — never a blind adoption. Log the decision in
`decisions.log`.

## Endpoints it reveals (as of first vendor, 2026-08-18)

- **`GET /api/spectate/guilds`** — public (no auth). Returns
  `{tick, maps:[{id,name,width,height}], guilds:[{guild_id, name, characters,
  roster:[{char_uid, name, level, world, look, equipment}], color}]}`. `characters`
  is the **authoritative total roster count** and each roster entry carries its
  current `world` — the true count + per-world distribution the ZeroMQ village
  frame only *partially* shows (frame `chars_here`/`chars_by_world` is a lagged,
  intermittent subset). Also exposes rival guilds' rosters (levels + gear).
- **`GET /events/spectate?guild=&char=&map=&x=&y=`** — public SSE stream of a
  map's frames (all guilds' chars, tiles, view). Rival-position / free-roam view.
- **`GET /api/tiles`** — public tile/atlas metadata:
  `{columns, count, tiles, fx_tiles, types, tier_tiles, surface_tiles, bare_tile,
  looks}` — kind→sprite/type maps that can help decode observed tile `kind`s.
- **`GET /api/me`** / **`GET /events/me`** — the guild's own village state / frame
  SSE, gated by the guild cookie. Redundant with the ZeroMQ frames the bot
  already receives.
- **`POST /api/guild/color`** — cosmetic (set the guild's map color).

The client's `LOGGED` event set also enumerates the full server event
vocabulary, including craft events we care about (`smelted`, `forge_started`,
`forge_struck`, `forged`, `craft_spoiled`, `learned`, `attuned`, ...).
