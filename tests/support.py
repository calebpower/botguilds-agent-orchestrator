"""Shared test doubles.

Every strategy-level test needs a `bot` to pass into `Explorer.act`, and four files each
grew their own four-attribute stand-in. They drift: adding `bot.chatter` in v0.74.0 broke
13 tests across three files at once, and `bot.config` broke a fourth the same day. A double
that keeps working while diverging from the object it imitates is worse than no double —
it tests a bot we do not ship.

So there is no double here. `strategy_bot` returns a REAL `GuildBot` with no storage and no
socket, which is what the local doubles were approximating anyway. It cannot drift, because
it is the thing.
"""
from steemer.bot import GuildBot


def strategy_bot(storage=None, tick: int = 500, config: dict | None = None) -> GuildBot:
    bot = GuildBot(strategy="explorer", storage=storage)
    bot.tick = tick
    if config is not None:
        bot.config = config
    return bot
