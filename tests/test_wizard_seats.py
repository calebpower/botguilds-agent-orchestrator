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


def test_the_operators_tie_order_int_then_GIFT_then_level_then_stats():
    """v0.94.0 (operator): the int GIFT now outranks LEVEL. Rationale in wizard_rank_key —
    a protected wizard levels slower than bold foragers, so a level-first tiebreak evicted
    exactly the int-gifted ceiling-breaker (the #184 arch-wizard). The gift halves every
    future INT point, so it belongs above a level the cautious wizard can never win on.
    Here `by_gift` (int 2, level 5, int-gift) must now out-rank `by_level` (int 2, level 7,
    no gift) — the mutation that would restore the old order flips exactly this pair."""
    chars = [_mk("by_int", int_=3),
             _mk("by_gift", int_=2, level=5, gifts=("int",)),
             _mk("by_level", int_=2, level=7),
             _mk("by_stats", int_=2, level=5, others=2),
             _mk("plain", int_=2, level=5)] + _pool(12)
    chosen = select_wizards(chars)
    for u in ("by_int", "by_gift", "by_level", "by_stats", "plain"):
        assert u in chosen, f"{u} should out-rank the int-1 pool: {sorted(chosen)}"
    from steemer.strategy.explorer import wizard_rank_key
    order = [c["char_uid"] for c in sorted(chars, key=wizard_rank_key)][:5]
    assert order == ["by_int", "by_gift", "by_level", "by_stats", "plain"], order


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


def _village_bot():
    from support import seat_bench
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 9,
                  "maps": [{"id": "vale"}, {"id": "mines"}]}
    bot.tick = 500
    return seat_bench(bot)


def _vchar(uid, int_=1, gifts=()):
    return {"char_uid": uid, "eid": abs(hash(uid)) % 9999, "hp": 30, "max_hp": 30,
            "xp": 0, "inventory": [], "level": 5,
            # sum >= 8: all-ones summed to 6 and classified EVERYONE fodder — including
            # the would-be guardian — which silently disabled the wizard branch entirely
            "stats": {"str": 2, "dex": 1, "int": int_, "vit": 2, "end": 1, "agi": 1},
            "gifts": list(gifts),
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None}}


def test_the_picker_finds_the_wizard_BEHIND_the_queue():
    """Run #177: 3 pair-embarks all run, because the 0.87.0 picker broke on
    here_avail[0] whatever its role — the wizard branch ran only by coincidence of queue
    order. The wizard here is LAST in chars_here; the pair-embark must still happen."""
    bot = _village_bot()
    acts = bot.on_frame({"world": "village", "tick": 500, "events": [],
        "guild": {"guild_id": "g_us", "gold": 50,
                  "chars_here": ["f1", "f2", "guard", "wiz"],
                  "chars_by_world": {"mines": [f"v{i}" for i in range(5)]},
                  "market_listings": []},
        "shop": {"stock": []},
        "chars": [_vchar("f1"), _vchar("f2"), _vchar("guard"),
                  _vchar("wiz", int_=5, gifts=("int",))]})
    emb = [a for a in acts if a.get("action") == "embark"]
    assert emb and "wiz" in (emb[0].get("char_uids") or []), \
        f"the wizard at the back of the queue never shipped: {acts}"
    assert len(emb[0]["char_uids"]) == 2, f"shipped alone, not paired: {emb}"


def test_a_DEAD_char_is_never_commanded_again():
    """Run #177 sent 4,626 commands to corpses (unknown_character). After the death
    event, a stale field frame still listing the char must produce nothing for it."""
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10, "maps": [{"id": "vale"}]}
    bot.tick = 500
    tiles = [[x, y, "floor", 0, 0] for x in range(4) for y in range(4)]
    live = {"char_uid": "c1", "eid": 7, "pos": [1, 1], "hp": 30, "max_hp": 30,
            "stamina": 40, "max_stamina": 56, "inventory": [], "stats": {},
            "carry": {"used": 0, "cap": 20}, "equipment": {"hand": {"kind": "club"}}}
    assert bot.on_frame({"world": "vale", "tick": 500, "events": [], "chars": [live],
                         "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    bot.on_frame({"world": "vale", "tick": 501,
                  "events": [{"kind": "death", "char_uid": "c1", "eid": 7}], "chars": [],
                  "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    acts = bot.on_frame({"world": "vale", "tick": 502, "events": [], "chars": [live],
                         "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    assert not acts, f"commanded a corpse: {acts}"


def test_a_RETURNED_char_sits_out_stale_field_frames_briefly():
    """12,384 not_in_village moves on #177: the char walks home, the old world frame
    still lists it for a few ticks, and we kept commanding the ghost. Within the grace
    the stale frame yields nothing; after it, a genuine re-embark acts normally."""
    GRACE = 4      # steemer.bot.RETURN_GRACE, duplicated (hygiene ratchet) and pinned:
    from steemer.bot import RETURN_GRACE
    assert RETURN_GRACE == GRACE, "the grace moved; re-read the numbers in this test"
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10, "maps": [{"id": "vale"}]}
    bot.tick = 500
    tiles = [[x, y, "floor", 0, 0] for x in range(4) for y in range(4)]
    ch = {"char_uid": "c1", "eid": 7, "pos": [1, 1], "hp": 30, "max_hp": 30,
          "stamina": 40, "max_stamina": 56, "inventory": [], "stats": {},
          "carry": {"used": 0, "cap": 20}, "equipment": {"hand": {"kind": "club"}}}
    bot.on_frame({"world": "vale", "tick": 500,
                  "events": [{"kind": "returned", "char_uid": "c1", "eid": 7}],
                  "chars": [], "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    stale = bot.on_frame({"world": "vale", "tick": 501, "events": [], "chars": [ch],
                          "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    assert not stale, f"commanded a returned ghost: {stale}"
    later = bot.on_frame({"world": "vale", "tick": 500 + GRACE + 2, "events": [],
                          "chars": [ch],
                          "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}})
    assert later, "the grace never ended — a re-embarked char could never act again"


# ---- v0.94.0: light hysteresis --------------------------------------------------------
from steemer.strategy.explorer import HYSTERESIS_SLACK


def test_hysteresis_RECLAIMS_a_seat_for_a_marginally_outranked_incumbent():
    """The anti-thrash that stops a protected wizard flapping to bold-forager (the #184
    arch-wizard): an incumbent that has dipped JUST outside the base (within SLACK)
    reclaims its seat from the newcomer that edged it. cap=2 for a legible boundary.
    inc_out is OUTSIDE the pure top-2 (a newcomer out-levels it) — hysteresis must pull
    it back IN, which is why inverting the incumbency check changes the result."""
    # ranked (gift>level>stats): inc_top int5 (rank0), newcomer int4 level5 (rank1),
    # inc_out int4 level1 (rank2 — just outside). incumbents = {inc_top, inc_out}.
    chars = [_mk("inc_top", int_=5),
             _mk("newcomer", int_=4, level=5),
             _mk("inc_out", int_=4, level=1)] + _pool(12)
    incs = {"inc_top", "inc_out"}
    seats = select_wizards(chars, cap=2, incumbents=incs)
    assert seats == {"inc_top", "inc_out"}, \
        f"incumbent did not reclaim its seat from the 1-rank newcomer: {seats}"
    # WITHOUT incumbency (fresh restart), the pure top-2 wins: the newcomer keeps the seat
    fresh = select_wizards(chars, cap=2)
    assert fresh == {"inc_top", "newcomer"}, f"fresh selection should be pure top-2: {fresh}"


def test_hysteresis_does_NOT_block_a_clearly_superior_newcomer():
    """The bug this replaced: stale incumbents must never keep out a much-better new
    char. A brand-new int-9 char (far above the slack margin) always takes a seat even
    though every current seat is an incumbent."""
    chars = [_mk("star", int_=9)] + [_mk(f"inc{i}", int_=2) for i in range(6)] + _pool(12, int_=1)
    incs = {f"inc{i}" for i in range(6)}
    seats = select_wizards(chars, cap=6, incumbents=incs)
    assert "star" in seats, f"a clearly-superior newcomer was blocked by incumbents: {seats}"
    assert len(seats) == 6


def test_hysteresis_slack_is_bounded_a_far_fallen_incumbent_loses_the_seat():
    """Sustained decline still evicts: an incumbent that falls MORE than SLACK places
    past the cutoff does lose its seat — hysteresis is a margin, not tenure."""
    assert HYSTERESIS_SLACK == 2      # pinned; the fixture below is sized to it
    # cap=2, incumbent inc1 has fallen to rank 5 (0-indexed 4) — 3 past the cutoff of 2,
    # beyond SLACK=2 — so it must NOT reclaim a seat.
    chars = [_mk("a", int_=9), _mk("b", int_=8),
             _mk("c", int_=7), _mk("d", int_=6),
             _mk("inc1", int_=5)] + _pool(12, int_=1)
    seats = select_wizards(chars, cap=2, incumbents={"inc1"})
    assert "inc1" not in seats, f"a far-fallen incumbent kept its seat: {seats}"
    assert seats == {"a", "b"}
