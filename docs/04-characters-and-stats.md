# Characters, stats, and progression

## The six stats

Every formula uses the **effective bonus** `B(s)` — a published soft cap, not
the raw stat value:

- Full rate up to 8
- Half rate from 9–16
- Quarter rate past 16

So `B(8) = 8`, `B(16) = 12`, `B(24) = 14`. Stats cap at 24 (`B(24) = 14`).
This means early points are much stronger than late ones — a character with
one stat at 8 gets full value from every one of those points, while pushing
that same stat from 16 to 24 buys only 2 more effective points for a lot more
XP.

| stat | drives |
|---|---|
| **STR** | Heavy-weapon damage; carry cap `18 + 3·B(STR)`; melee attacks cost `−B(STR)//3` less stamina; charge run-up likewise. |
| **DEX** | Light/ranged weapon damage and range; shoot/throw actions cost `−B(DEX)//3` less stamina. |
| **INT** | Implement (wand/scepter) damage; max mana `6 + 4·B(INT)`; mana regen `1 + B(INT)//6`; spell forms you can hold at once, `1 + B(INT)//4`; essences you can stay attuned to, `2 + B(INT)//6`; potion potency (+0.05×B on the drinker's multiplier, capped at ×2). |
| **VIT** | Max HP `18 + 6·B(VIT)`; passive rest-healing `1 + B(VIT)//4` HP per idle tick once unhit long enough. |
| **END** | Max stamina `40 + 8·B(END)`; stamina regen `5 + B(END)//3` per tick. |
| **AGI** | Speed for tick-order (`AGI×5 + d4`, re-rolled every tick); moves cost `−B(AGI)//2` less stamina. |

## Recruiting

`recruit [name]` is free (up to `roster_cap`, a server config value). Each
recruit rolls **1–2 points in every stat** and, separately, **two `gifts`** —
stats that cost *half* XP to raise for that character, visible in the char
frame as `gifts: [...]`. This is the game's build-diversity lever:
specializing a character in its gifted stats is cheap; generalizing (or
raising a non-gifted stat far) is expensive. There are no classes — a
character's build is purely the stat points you choose to buy.

## XP and leveling

XP comes from **kills** (split proportionally by damage dealt among
participants, and worth progressively less once you far outlevel the
victim — grinding an easy band eventually stops paying) and from
**discoveries**. Spend it one point at a time with `spend_xp {stat}`:

```
cost = 8 × v × 2^(v // 10)     # v = the stat's current value
cost //= 2                      # if the stat is one of this character's two gifts
```

Costs double every 10 points in a stat and are cheap early — this rewards
broad early investment and specialization later.

**Level** is a derived shorthand, not a separate resource: it's the character's
total stat points above the 1-per-stat floor, so every point you buy with
`spend_xp` is exactly +1 level. There's no separate level-up mechanic to
manage.

## Death

**Death is permanent.** A dead character drops its entire inventory and
equipment on the tile it died on — free for the taking, by anyone, including
rival guilds. Your guild's gold and guild-level inventory are unaffected.
Recruiting a replacement character is free, so death mainly costs you the
gear and progress that specific character was carrying/had bought stats for
— plan around losing individual characters, not around losing the guild.

## Stamina and resting

Stamina paces the game to roughly one meaningful action per character every
4–5 ticks. There is no explicit rest action:

- **A character you send no action for rests**: stamina and mana regen at
  **double** the normal rate, and — once it has gone unhit for a few ticks —
  it heals `1 + B(VIT)//4` HP per idle tick.
- **Village idling** is even better: full stamina restoration and 10% max HP
  healed per tick.
- **Field healing is a finite reserve per expedition**: `field_heal_mult`
  (server config) × max HP, spent amount tracked on the character as
  `field_healed`. Once that reserve runs dry, resting only restores stamina,
  not HP — you need food, potions, or a walk home. Returning to the village
  resets the reserve. This is a deliberate anti-camping mechanic: you cannot
  turtle forever in the field waiting out cooldowns.

See [03-actions.md](03-actions.md) for the exact stamina cost table.

## Unattended recall

If a character receives **no action for 2000 ticks** (~8 minutes at the
default 0.25s tick), it is automatically recalled to the village, and your
village frame gets a `recalled` event naming it. **Resting counts as
unattended** for this timer — sending literally nothing, tick after tick, is
indistinguishable from an offline bot as far as this mechanic is concerned. To
hold a party in the field indefinitely (e.g. waiting near a chokepoint), send
some action periodically, even a no-op `say`.

This is also why a bot left running overnight is found standing safely in the
village the next morning with everything it was carrying intact — nothing is
lost, you just need to `embark` again.

## Caps to respect

Read these from `hello_ok.config` / `bot.config` rather than hardcoding them
— they're server-tunable:

- `roster_cap` — total living characters across the whole guild.
- `party_cap` — characters fielded on one map at once.
- `world_cap` — characters fielded across *all* maps at once.

Exceeding any of them on `recruit`/`embark` errors with the matching reason
(`roster_cap`, `party_cap`, `world_cap`). Every example bot in the starter
kit computes `away = sum(len(uids) for uids in guild["chars_by_world"].values())`
from the village frame before deciding whether to recruit or embark — see
[10-example-bots.md](10-example-bots.md).
