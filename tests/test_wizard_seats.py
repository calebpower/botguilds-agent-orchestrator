"""v0.88.0 — the chosen six (operator directive, verbatim pieces in each test).

Seats are a PURE function of the roster snapshot: top-WIZARD_SEATS by (int, level,
int-gift, stat sum, uid). No stored seat state exists to corrupt — a restart re-derives
the set, and one ground INT point entrenches a holder against every INT-1 challenger.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import select_wizards, WIZARD_SEATS, WIZARD_MIN_POOL

# 12 duplicated as a literal in fixtures (the hygiene ratchet forbids sizing them from the
# constant under test); the pin keeps the duplication honest.
POOL = 12


def test_the_pool_floor_is_what_these_fixtures_assume():
    assert WIZARD_MIN_POOL == POOL, "the floor moved; re-read the numbers in this file"


def _mk(uid, int_=1, level=1, gifts=(), others=1):
    return {"char_uid": uid, "stats": {"str": others, "dex": others, "int": int_,
                                       "vit": others, "end": others, "agi": others},
            "level": level, "gifts": list(gifts)}


def _pool(n=POOL, int_=1):
    return [_mk(f"p{i}", int_=int_) for i in range(n)]


def test_exactly_six_seats_no_matter_how_many_qualify():
    chars = [_mk(f"w{i}", int_=5) for i in range(9)] + _pool()
    assert len(select_wizards(chars)) == WIZARD_SEATS == 6


def test_the_operators_tie_order_int_then_level_then_gift_then_stats():
    chars = [_mk("by_int", int_=3),
             _mk("by_level", int_=2, level=7),
             _mk("by_gift", int_=2, level=5, gifts=("int",)),
             _mk("by_stats", int_=2, level=5, others=2),
             _mk("plain", int_=2, level=5)] + _pool(12)
    ranked = sorted(select_wizards(chars) | set(), key=lambda u: u)  # membership only
    chosen = select_wizards(chars)
    for u in ("by_int", "by_level", "by_gift", "by_stats", "plain"):
        assert u in chosen, f"{u} should out-rank the int-1 pool: {sorted(chosen)}"
    from steemer.strategy.explorer import wizard_rank_key
    order = [c["char_uid"] for c in sorted(chars, key=wizard_rank_key)][:5]
    assert order == ["by_int", "by_level", "by_gift", "by_stats", "plain"], order


def test_below_the_pool_floor_there_are_NO_seats():
    """Two chars sighted right after a restart must not both crown themselves wizard and
    walk home — the roster-wide paralysis the pool floor exists to prevent."""
    assert select_wizards([_mk("a", int_=9), _mk("b", int_=9)]) == set()


def test_a_death_PROMOTES_the_next_candidate_through_the_bot():
    """Operator: 'If a wizard dies, a non-wizard gets immediately promoted according to
    stats.' The death event prunes the ledger, and the same pure ranking now includes
    the runner-up — no ceremony, no stored state, nothing to race."""
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 20, "maps": [{"id": "vale"}]}
    bot.tick = 500
    for i in range(POOL):
        bot.strategy._char_ledger[f"p{i}"] = _mk(f"p{i}")
    for i in range(6):
        bot.strategy._char_ledger[f"w{i}"] = _mk(f"w{i}", int_=5)
    bot.strategy._char_ledger["runner_up"] = _mk("runner_up", int_=4)
    seats0 = bot.strategy.wizard_seats()
    assert "runner_up" not in seats0 and "w3" in seats0
    bot.on_frame({"world": "vale", "tick": 501, "chars": [
        {"char_uid": "x", "eid": 1, "pos": [0, 0], "hp": 1, "max_hp": 1, "stamina": 1,
         "inventory": [], "stats": {}, "equipment": {}}],
        "events": [{"kind": "death", "eid": 99, "char_uid": "w3"}],
        "visible": {"tiles": [[0, 0, "floor", 0, 0]], "entities": [], "items": [], "gold": []}})
    seats1 = bot.strategy.wizard_seats()
    assert "w3" not in seats1, "the corpse kept its seat"
    assert "runner_up" in seats1, f"no promotion: {sorted(seats1)}"
