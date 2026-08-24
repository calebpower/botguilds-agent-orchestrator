"""THE OSCILLATION ORACLE — the class invariant, not another instance test.

Runs #195-199 produced four distinct movement loops (the y12/13 line dance, its
one-tile-shallower relocation, the mines chorus line, the world-rotating commute) and
each shipped past a green suite, because every test pinned the PREVIOUS instance. This
harness drives the REAL GuildBot for ~120 ticks over a small simulated world — applying
its chosen moves, removing what it picks up — and asserts the CLASS invariant on the
whole trajectory:

  * NO DANCING: in any 16-tick window with >= 8 moves, the char covers > 3 distinct
    tiles. (Catches period-2 N/S/N/S and period-4 N/N/S/S alike — every recorded dance
    concentrated many moves on 2-3 tiles.)
  * NO CAMPING ON NOTHING: an un-healed char whose only attractors are past the poison
    cap ENDS at home (y <= 2, or issued `return`) — it neither dances at the wall nor
    stands at it forever.
  * NO OVER-SUPPRESSION (the starvation lesson): a HEALED char in the same world still
    reaches the deep loot. An oracle that only rewards going home would bless a bot
    that never works.

Modeling choices, stated: stamina is pinned to max every tick (rests only ever slowed
the dances down — removing them makes cycles faster and this oracle stricter); no
poison DOT (these are movement-cycle invariants, not survival ones).

Self-test: the window detector is run against the RECORDED shapes of the real dances
(#195's N/S alternation, #199's N/N/S/S chorus) and must fire on both.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import POISON_SAFE_DEPTH


def test_pinned_cap():
    assert POISON_SAFE_DEPTH == 12, "cap moved — revisit this file's literal geometry"


CAP = 12          # POISON_SAFE_DEPTH, pinned above (hygiene: literal + pin)
DIRS = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    return b


def _char(uid, pos, healed=False, armed=True, int_gift=False):
    inv = [{"kind": "potion_red", "item_id": f"{uid}-pot"}] if healed else []
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos),
            "hp": 30, "max_hp": 30, "stamina": 56, "max_stamina": 56, "level": 3,
            "stats": {"int": 5 if int_gift else 1},
            "gifts": (["int"] if int_gift else []), "statuses": [], "spells": [],
            "spell_cap": 1, "carry": {"used": 0, "cap": 20}, "inventory": inv,
            "equipment": ({"hand": {"kind": "club"}} if armed else {})}


def simulate(tiles, bounds, chars, items=(), ticks=120, world="vale"):
    """Drive the real bot; return {uid: [positions...]} and the surviving item set.
    Walkable set derives from the tile list (same rule the bot's nav uses for floor)."""
    bot = _bot()
    solid = {"vein", "tree", "rock", "wall", "forge", "cauldron", "portal", "bush"}
    walk = {(t[0], t[1]) for t in tiles if t[2] not in solid}
    state = {c["char_uid"]: tuple(c["pos"]) for c in chars}
    left = {c["char_uid"]: c for c in chars}
    items = {tuple(p): k for p, k in items}
    tracks = {c["char_uid"]: [tuple(c["pos"])] for c in chars}
    done = set()
    for t in range(ticks):
        live = [dict(left[u], pos=list(state[u]), stamina=56)
                for u in state if u not in done]
        if not live:
            break
        frame = {"type": "frame", "world": world, "tick": 1000 + t, "events": [],
                 "bounds": list(bounds), "chars": live,
                 "visible": {"tiles": tiles, "entities": [],
                             "items": [{"pos": list(p), "kind": k}
                                       for p, k in items.items()],
                             "gold": []}}
        for a in bot.on_frame(frame):
            uid = a.get("char_uid")
            if uid not in state or uid in done:
                continue
            if a.get("action") == "move" and a.get("dir") in DIRS:
                dx, dy = DIRS[a["dir"]]
                nxt = (state[uid][0] + dx, state[uid][1] + dy)
                occupied = {p for u, p in state.items() if u != uid}
                if nxt in walk and nxt not in occupied:
                    state[uid] = nxt
            elif a.get("action") == "pickup":
                items.pop(state[uid], None)
            elif a.get("action") == "return":
                done.add(uid)                     # reached the gate — arrived home
        for uid in state:
            if uid not in done:
                tracks[uid].append(state[uid])
            if state[uid][1] <= 0:
                done.add(uid)
    return tracks, items


def dance_windows(track, win=16, min_moves=8, max_tiles=3):
    """Windows where many moves cover almost no ground — the dance signature."""
    bad = []
    for i in range(len(track) - win):
        w = track[i:i + win]
        moves = sum(1 for a, b in zip(w, w[1:]) if a != b)
        if moves >= min_moves and len(set(w)) <= max_tiles:
            bad.append((i, sorted(set(w))))
    return bad


def assert_clean_and_home(tracks, uid):
    track = tracks[uid]
    assert not dance_windows(track), \
        f"{uid} danced: {dance_windows(track)[:2]} in {track[-30:]}"
    assert track[-1][1] <= 2, \
        f"{uid} never went home; ended at {track[-1]} (tail {track[-12:]})"


# ---- oracle self-test: the detector must fire on the REAL recorded dance shapes ----

def test_the_detector_fires_on_the_recorded_line_dance_shapes():
    # #195 c19457: N/S alternation with rests between (period 2)
    a, b = (5, 11), (5, 12)
    period2 = [a, a, b, b, a, a, b, b, a, a, b, b, a, a, b, b, a, a]
    # #199 chorus (c19455's N,N,S,S walk between y10 and y12 over three tiles)
    p, q, r = (8, 10), (8, 11), (8, 12)
    period4 = [p, q, r, q, p, q, r, q, p, q, r, q, p, q, r, q, p, q]
    assert dance_windows(period2), "detector blind to the #195 period-2 dance"
    assert dance_windows(period4), "detector blind to the #199 period-4 chorus"
    # and it must NOT fire on honest work: a straight 18-tile walk
    walk = [(0, y) for y in range(18)]
    assert not dance_windows(walk), "detector fires on a plain walk (over-broad)"


# ---- the class invariant, over every historical dance world ----

def _corridor(top, kinds=None):
    kinds = kinds or {}
    return [[0, y, kinds.get(y, "floor")] for y in range(top + 1)]


def test_unhealed_loot_past_cap_no_dance_goes_home():
    # the 0.103/0.104/0.105 class: loot at y >= cap, char below it
    tracks, _ = simulate(_corridor(CAP + 4), (1, CAP + 5),
                         [_char("c1", (0, CAP - 2))],
                         items=(((0, CAP + 1), "egg"),))
    assert_clean_and_home(tracks, "c1")


def test_unhealed_loot_AT_the_boundary_no_dance_goes_home():
    tracks, _ = simulate(_corridor(CAP + 4), (1, CAP + 5),
                         [_char("c1", (0, CAP - 1))],
                         items=(((0, CAP), "egg"),))
    assert_clean_and_home(tracks, "c1")


def test_unhealed_rail_past_cap_no_dance_goes_home():
    # the 0.105.1 chorus-line anchor: a rideable rail at y >= cap
    tiles = [[x, y, "floor"] for x in range(3) for y in range(CAP + 5)]
    tiles += [[1, CAP + 1, "track"], [1, CAP + 2, "track"], [1, CAP + 3, "track"]]
    tracks, _ = simulate(tiles, (3, CAP + 5), [_char("c1", (1, CAP - 2))])
    assert_clean_and_home(tracks, "c1")


def test_unhealed_vein_past_cap_no_dance_goes_home():
    tiles = _corridor(CAP + 4, kinds={CAP + 1: "vein"})
    tracks, _ = simulate(tiles, (1, CAP + 5), [_char("c1", (0, CAP - 2))])
    assert_clean_and_home(tracks, "c1")


def test_unhealed_empty_world_no_dance_goes_home():
    tracks, _ = simulate(_corridor(CAP + 4), (1, CAP + 5),
                         [_char("c1", (0, CAP - 2))])
    assert_clean_and_home(tracks, "c1")


def test_the_escort_pair_follows_its_anchor_home_not_into_the_wall():
    # the #198 chorus line: an INT anchor + a guardian, rails past the cap. Both must
    # end home without a dance — the escort must not parade at the boundary.
    from support import seat_bench
    tiles = [[x, y, "floor"] for x in range(6) for y in range(CAP + 5)]
    tiles += [[2, CAP + 1, "track"], [2, CAP + 2, "track"], [2, CAP + 3, "track"]]
    bot_chars = [_char("wiz", (2, CAP - 2), int_gift=True),
                 _char("guard", (3, CAP - 2))]
    tracks, _ = simulate(tiles, (6, CAP + 5), bot_chars)
    for uid in ("wiz", "guard"):
        track = tracks[uid]
        assert not dance_windows(track), \
            f"{uid} danced at the wall: {dance_windows(track)[:2]}"
        assert track[-1][1] <= 4, f"{uid} parked in the field: {track[-12:]}"


def test_a_HEALED_char_still_reaches_the_deep_loot():
    # the over-suppression control: with a potion the cap lifts, and the same world
    # that sends an un-healed char home must let this one WORK.
    tracks, items = simulate(_corridor(CAP + 4), (1, CAP + 5),
                             [_char("c1", (0, CAP - 2), healed=True)],
                             items=(((0, CAP + 1), "egg"),), ticks=60)
    assert (0, CAP + 1) not in items, \
        f"healed char never collected the deep loot; track tail {tracks['c1'][-12:]}"
