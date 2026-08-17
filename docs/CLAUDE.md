# CLAUDE.md — working in `docs/`

This folder documents **BotGuilds**, a persistent multiplayer bot-programming
game (`https://bot.willmorrison.net`). It is *documentation*, written by
reading the server's own `/docs` manual, the starter kit's `AGENTS.md`, and
the actual `botguilds` client library source vendored at the repo root as the
`reference_starter_kit` git submodule.

## What you're actually being asked to do here

If you (an agent) were pointed at this repo to help someone write or improve
a **BotGuilds bot**, start at [README.md](README.md) — it indexes every topic
doc in this folder and gives a one-paragraph mental model. Read
[10-example-bots.md](10-example-bots.md) before writing new bot logic; it's
faster to fork a working pattern (`starter_bot.py` → `farmer_bot.py` →
`ranger_bot.py`, in increasing sophistication) than to derive movement/combat
logic from the mechanics docs from scratch.

If you're being asked to **update these docs** (e.g. the server added a
mechanic, or `reference_starter_kit` was bumped to a newer commit), treat
`reference_starter_kit/AGENTS.md` and the live `/docs` page as the sources of
truth to re-diff against — see [Keeping this in sync](#keeping-this-in-sync).

## Ground rules specific to this documentation

- **Never invent numbers.** Every formula, cap, and cost in these docs was
  copied from the server's manual or the `AGENTS.md`/source in
  `reference_starter_kit`. If you add a new fact, it must trace to one of
  those two places (or to your own observed `guild_log.db` data, clearly
  labeled as an example rather than a guaranteed constant).
- **Respect the "what isn't written down" boundary.** The server
  deliberately does not publish items, enemies, recipes, per-world
  vocabularies, or boss mechanics — see
  [08-world-and-economy.md](08-world-and-economy.md#what-isnt-written-down).
  Do not add speculative content docs (a bestiary, an item list, a recipe
  table) even if you're asked to guess — that content is meant to be
  discovered per-world through play and logged locally, not published here.
  If someone wants that kind of reference, point them at their own
  `guild_log.db` (see [09-client-library.md](09-client-library.md#the-local-database)).
- **Keep the topic-doc split.** Files are numbered and single-topic
  (protocol, actions, characters, combat, magic, crafting, world/economy,
  client library, examples, map viewer) on purpose — it's what makes this
  navigable for an agent mid-task. Extend an existing file before adding a
  new one; only add a new numbered doc for a genuinely new topic area.
- **Prefer the code over the prose manual when they'd ever disagree.** The
  server's `/docs` page is the friendly narrative version; `AGENTS.md` and
  `botguilds/protocol.py`/`client.py` are the wire-level ground truth written
  specifically for coding agents. These docs already reconcile the two, but
  if you're updating them and find a discrepancy, the code wins.

## Keeping this in sync

The `reference_starter_kit` submodule at the repo root is the vendored copy
of `https://bot.willmorrison.net/starter.git`. To check whether these docs
are stale relative to it:

```bash
cd reference_starter_kit
git fetch
git log HEAD..origin/main --oneline   # anything here means the kit has moved on
```

To pull in updates and re-derive docs against the new commit:

```bash
git submodule update --remote reference_starter_kit
```

Then re-read `reference_starter_kit/AGENTS.md` and the changed source files,
and diff their content against the numbered docs in this folder — most
changes will land in exactly one topic file. Also re-fetch the live
`/docs` page (`https://bot.willmorrison.net/docs`) since server-side mechanic
changes show up there first, often before the starter kit's `AGENTS.md` catches
up.

## Layout

```
docs/
  README.md                       index + one-paragraph mental model
  01-getting-started.md           registration, starter kit, first run
  02-protocol.md                  tick loop, wire protocol, frame shape
  03-actions.md                   every action, args, legality, cost
  04-characters-and-stats.md      stats, XP, gifts, death, recall
  05-combat-and-damage.md         damage formula, tick order, statuses, PvP
  06-magic.md                     mana, implements, spellweaving, attunement
  07-crafting.md                  brewing, forging, tells, quality tiers
  08-world-and-economy.md         maps, bands, terrain, carrying, gold
  09-client-library.md            botguilds.client / .protocol, SQLite schema
  10-example-bots.md              annotated starter/farmer/ranger bots
  11-map-viewer.md                map_viewer.py
  CLAUDE.md                       this file
```
