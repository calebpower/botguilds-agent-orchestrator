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


def seat_bench(bot, n=6, int_=2, level=9):
    """Seed the wizard-seat ledger with `n` bench-holders (v0.88.0).

    Seats are the top-6 of the WHOLE roster, gated on WIZARD_MIN_POOL — so a tiny test
    fixture would otherwise put its every character into a seat (or, below the pool
    floor, none at all). The bench dummies rank ABOVE ordinary fixture characters
    (int 2, level 9) and BELOW any fixture character given int >= 3, letting each test
    say exactly who its wizards are: give a char int>=3 for a seat, int 1 for none.
    """
    from steemer.strategy.explorer import WIZARD_MIN_POOL
    total = max(n, WIZARD_MIN_POOL)
    for i in range(total):
        boost = int_ if i < n else 0
        bot.strategy._char_ledger[f"_bench{i}"] = {
            "char_uid": f"_bench{i}",
            "stats": {"str": 1, "dex": 1, "int": boost if i < n else 1,
                      "vit": 1, "end": 1, "agi": 1},
            "level": level if i < n else 1, "gifts": []}
    return bot
