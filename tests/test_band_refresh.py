"""v0.60.0 — BAND-REFRESH AWARENESS: noticing the cycle we had been blind to.

Each world cycles through bands and periodically REFRESHES. The frame has said so all
along — `next_refresh: {band, in_ticks}` — and we ignored the field completely. Iter 71 paid
for that: a refresh collapsed ground loot 18x (1.06 → 0.06 visible items per frame), the
whole economy idled by starvation, and I misread it as a code regression and nearly rolled
back a good change. A starving band was indistinguishable from a broken bot.

The first use of the signal is chests. A refresh REFILLS them — run #136 saw `chest`
sightings spike to 424 in the loot-rich bucket against 14–80 elsewhere — but our map still
records `chest_open` for every one we emptied, and an opened chest is not a container. So we
would never go back, and would only notice a refilled chest by walking past it. There were
2,500–4,600 `chest_open` sightings per bucket sitting in that blind spot.

The recheck set is deliberately kept OUT of `known`: `known` records what we have OBSERVED,
this is a HYPOTHESIS about what a refresh did. Writing the guess into the map would put a
fabrication into the structure every other behaviour trusts.

What these tests do NOT prove: that a refreshed chest actually holds anything. If the
hypothesis is wrong the cost is one bounded trip (FIELD_GOAL_RANGE) and the next sighting
corrects it — `nothing_to_open` is a real error reason we would see in the live stream.
"""
from steemer.bot import GuildBot


def _frame(world="vale", tick=1, tiles=(), band=0, in_ticks=100, chars=None):
    f = {"type": "frame", "world": world, "tick": tick, "events": [],
         "chars": chars if chars is not None else
                  [{"char_uid": "u1", "eid": 1, "pos": [0, 0], "hp": 9, "max_hp": 9,
                    "stamina": 9, "inventory": [], "equipment": {}}],
         "visible": {"tiles": list(tiles), "entities": [], "items": [], "gold": []}}
    if band is not None:
        f["next_refresh"] = {"band": band, "in_ticks": in_ticks}
    return f


def _containers_after(bot, frames):
    """The container set the STRATEGY is handed on the last frame — asserted at the
    boundary a decision actually reads, not on a bot attribute."""
    seen = {}

    class Spy:
        version = "spy/0"

        def act(self, _b, _c, _f, ctx, _t):
            seen["c"] = set(ctx.containers)

        def village(self, _b, _f):
            return []

    bot.strategy = Spy()
    for f in frames:
        bot.on_frame(f)
    return seen.get("c", set())


CHEST_OPEN = [3, 3, "chest_open", 0, 0]
FLOOR = [0, 0, "floor", 0, 0]


# ---- detecting the refresh ---------------------------------------------------

def test_a_changed_band_number_is_a_refresh():
    bot = GuildBot("explorer")
    assert bot._band_refreshed("vale", _frame(band=0, in_ticks=500)) is False, \
        "the first sighting has nothing to compare against"
    assert bot._band_refreshed("vale", _frame(band=1, in_ticks=500)) is True


def test_a_rising_countdown_is_a_refresh():
    """A countdown only ever falls, so a RISE is a new cycle — run #136 showed jumps
    like in_ticks 1 -> 2760 while the band number also moved. Either tell alone must
    be enough, since a cycle can return to the same band."""
    bot = GuildBot("explorer")
    bot._band_refreshed("vale", _frame(band=0, in_ticks=100))
    assert bot._band_refreshed("vale", _frame(band=0, in_ticks=2760)) is True


def test_a_falling_countdown_is_not_a_refresh():
    bot = GuildBot("explorer")
    bot._band_refreshed("vale", _frame(band=0, in_ticks=500))
    assert bot._band_refreshed("vale", _frame(band=0, in_ticks=499)) is False
    assert bot._band_refreshed("vale", _frame(band=0, in_ticks=1)) is False


def test_the_first_frame_for_a_world_is_never_a_refresh():
    """Otherwise it fires on every deploy, which would make the signal worthless
    exactly when we are trying to measure a deploy."""
    bot = GuildBot("explorer")
    assert bot._band_refreshed("mines", _frame(world="mines", band=3, in_ticks=9)) is False


def test_worlds_are_tracked_separately():
    """run #136 showed vale, mines and spire refreshing on their own schedules."""
    bot = GuildBot("explorer")
    bot._band_refreshed("vale", _frame(band=0, in_ticks=500))
    assert bot._band_refreshed("mines", _frame(world="mines", band=1, in_ticks=9)) is False
    assert bot._band_refreshed("vale", _frame(band=2, in_ticks=500)) is True


def test_a_frame_with_no_refresh_field_is_not_a_refresh():
    """Village frames carry no `next_refresh`; absence must never read as a change."""
    bot = GuildBot("explorer")
    bot._band_refreshed("vale", _frame(band=0, in_ticks=500))
    assert bot._band_refreshed("vale", _frame(band=None)) is False


# ---- what the refresh is USED for --------------------------------------------

def test_an_emptied_chest_becomes_a_target_again_after_a_refresh():
    """The defect this buys back: 2,500+ remembered `chest_open` tiles that refill on a
    cycle we can detect, and which we would otherwise only notice by walking past."""
    bot = GuildBot("explorer")
    before = _containers_after(bot, [_frame(tiles=[CHEST_OPEN], band=0, in_ticks=500)])
    assert before == set(), "an opened chest is not a container"
    after = _containers_after(bot, [_frame(tiles=[FLOOR], band=1, in_ticks=500, tick=2)])
    assert (3, 3) in after, "after a refresh it is worth a second look"


def test_no_refresh_means_no_second_look():
    bot = GuildBot("explorer")
    _containers_after(bot, [_frame(tiles=[CHEST_OPEN], band=0, in_ticks=500)])
    after = _containers_after(bot, [_frame(tiles=[FLOOR], band=0, in_ticks=499, tick=2)])
    assert (3, 3) not in after


def test_looking_at_the_tile_settles_the_hypothesis():
    """Whichever way it fell. Seeing it still open drops it (nothing to go back for);
    seeing it refilled makes it a container by KIND, so the guess is not needed."""
    bot = GuildBot("explorer")
    _containers_after(bot, [_frame(tiles=[CHEST_OPEN], band=0, in_ticks=500)])
    _containers_after(bot, [_frame(tiles=[FLOOR], band=1, in_ticks=500, tick=2)])
    still_open = _containers_after(
        bot, [_frame(tiles=[CHEST_OPEN], band=1, in_ticks=499, tick=3)])
    assert (3, 3) not in still_open, "we looked; it is still empty"


def test_a_refilled_chest_is_a_container_on_its_own_merits():
    bot = GuildBot("explorer")
    seen = _containers_after(bot, [_frame(tiles=[[3, 3, "chest", 0, 0]], band=0)])
    assert (3, 3) in seen


def test_the_hypothesis_is_not_written_into_the_map():
    """`known` must keep saying what we OBSERVED. Every other behaviour reads it — nav
    walkability, the frontier, vein-seek — so a fabrication here would spread."""
    bot = GuildBot("explorer")
    _containers_after(bot, [_frame(tiles=[CHEST_OPEN], band=0, in_ticks=500)])
    _containers_after(bot, [_frame(tiles=[FLOOR], band=1, in_ticks=500, tick=2)])
    assert bot.known["vale"][(3, 3)] == "chest_open"


def test_only_EMPTIED_CHESTS_are_revived_not_every_tile_we_have_seen():
    """The hypothesis has to be about chests specifically. A refresh that turned every
    remembered tile into a container would send characters to inspect plain floor —
    and `known` would still look untouched, so the test above cannot see it."""
    bot = GuildBot("explorer")
    _containers_after(bot, [_frame(tiles=[CHEST_OPEN, [7, 7, "floor", 0, 0]],
                                   band=0, in_ticks=500)])
    after = _containers_after(bot, [_frame(tiles=[FLOOR], band=1, in_ticks=500, tick=2)])
    assert (3, 3) in after, "the emptied chest is revived"
    assert (7, 7) not in after, "...but plain floor is not a chest"


def test_a_refresh_in_one_world_does_not_revive_anothers_chests():
    """The mines chest must be revived by the MINES refresh and stay in the mines. A
    shared recheck set is invisible unless the other world's set is actually non-empty,
    so this refreshes mines FIRST and only then looks at vale."""
    bot = GuildBot("explorer")
    _containers_after(bot, [_frame(world="mines", tiles=[CHEST_OPEN], band=0, in_ticks=500)])
    mines = _containers_after(
        bot, [_frame(world="mines", tiles=[FLOOR], band=1, in_ticks=500, tick=2)])
    assert (3, 3) in mines, "premise: the mines refresh put it in the mines recheck set"

    _containers_after(bot, [_frame(world="vale", tiles=[FLOOR], band=0, in_ticks=500, tick=3)])
    vale = _containers_after(
        bot, [_frame(world="vale", tiles=[FLOOR], band=1, in_ticks=500, tick=4)])
    assert (3, 3) not in vale, "a mines chest is not a target in vale"
