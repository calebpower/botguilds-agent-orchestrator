"""THE SOAK — the real GuildBot against the reverse-engineered server (operator
directive, 2026-08-24). See tests/simserver.py for what the sim models and why.

Two layers here:

1. SIM SELF-TESTS — the oracle must be able to complain (house rule): the lag model
   reproduces the departure flap, the phantom vault refuses, the slot truth rejects,
   the poison bites, the stalled clock freezes ticks while frames flow.

2. THE SOAK — thousands of simulated ticks of the full bot loop (frames -> on_frame ->
   actions -> sim.apply -> on_action_error), then the invariant battery on the WHOLE
   history: no dance windows, no error-family storms, the field is worked, the economy
   progresses (dead-capital buys + equips LAND per the sim's own events), no char
   deeper than its potion budget, deaths zero. This is the tier that would have caught
   the ghost re-command storm, the departure-flap quarantine mute, and the mirage flip
   BEFORE deploy — each escaped a green 1,100-test suite because no unit fixture
   modeled incoherence.

Determinism: seed printed; override with STEEMER_SIM_SEED to replay a failure.
"""
import os
from collections import Counter, defaultdict

from steemer.bot import GuildBot

from simserver import SimServer, POISON_DEPTH
from test_no_oscillation import dance_windows

SEED = int(os.environ.get("STEEMER_SIM_SEED", "20260824"))


# ---- 1. sim self-tests -------------------------------------------------------

def test_sim_lag_reproduces_the_departure_flap():
    sim = SimServer(seed=1, lag=3)
    sim.add_char("c1", hand="club")
    sim.apply([{"action": "embark", "map": "vale", "char_uids": ["c1"]}])
    sim.step()
    village = sim.frames()[0]
    assert "c1" in village["guild"]["chars_here"], "no lag — the flap can't exist"
    # a village-context move commanded off that stale listing is rejected the way
    # the live server rejected 51 of them on run #208
    r = sim.apply([{"char_uid": "c1", "action": "sell", "item_id": 1}])
    assert r and r[0]["reason"] == "not_in_village"
    for _ in range(4):
        sim.step()
    village = sim.frames()[0]
    assert "c1" not in village["guild"]["chars_here"], "the view never catches up"


def test_sim_phantom_vault_refuses_and_real_entries_withdraw():
    sim = SimServer(seed=1)
    sim.add_char("c1")
    ghost = sim.add_vault("potion_red", phantom=True)
    real = sim.add_vault("club", phantom=False)
    r = sim.apply([{"char_uid": "c1", "action": "drop", "item_id": ghost}])
    assert r and r[0]["reason"] == "no_such_item"
    assert not sim.apply([{"char_uid": "c1", "action": "drop", "item_id": real}])
    assert any(i["kind"] == "club" for i in sim.chars["c1"]["inventory"])


def test_sim_slot_truth_and_str_gate():
    sim = SimServer(seed=1)
    sim.add_char("c1", inventory=[{"kind": "club", "item_id": 7,
                                   "uses": ["equip", "attack"]},
                                  {"kind": "spear", "item_id": 8,
                                   "uses": ["equip", "attack"]}])
    r = sim.apply([{"char_uid": "c1", "action": "equip", "slot": "offhand",
                    "item_id": 7}])
    assert r and r[0]["reason"] == "wrong_slot"
    r = sim.apply([{"char_uid": "c1", "action": "equip", "slot": "hand",
                    "item_id": 8}])
    assert r and r[0]["reason"] == "stat_requirement", "the STR gate is open"
    assert not sim.apply([{"char_uid": "c1", "action": "equip", "slot": "hand",
                           "item_id": 7}])
    assert any(e["kind"] == "equip" for e in sim.events_out), "no equip event emitted"


def test_sim_poison_bites_past_the_depth():
    sim = SimServer(seed=1)
    sim.add_char("c1")
    sim.chars["c1"]["world"] = "vale"
    sim.chars["c1"]["pos"] = [0, POISON_DEPTH + 1]
    hp0 = sim.chars["c1"]["hp"]
    for _ in range(5):
        sim.step()
    assert sim.chars["c1"]["hp"] < hp0, "poison never bit"
    assert "poison" in sim.chars["c1"]["statuses"]


def test_sim_stall_freezes_the_clock_while_frames_flow():
    sim = SimServer(seed=1)
    sim.add_char("c1")
    t0 = sim.tick
    sim.stall(5)
    for _ in range(5):
        sim.step()
        assert sim.frames(), "frames stopped during the stall"
    assert sim.tick == t0, "the stalled clock advanced"
    sim.step()
    assert sim.tick == t0 + 1, "the clock never resumed"


# ---- 2. the soak -------------------------------------------------------------

def _soak(sim: SimServer, ticks: int):
    bot = GuildBot(strategy="explorer")
    bot.config = dict(sim.config)
    tracks = defaultdict(list)
    for _ in range(ticks):
        sim.step()
        for frame in sim.frames():
            acts = bot.on_frame(frame)
            for rej in sim.apply(acts):
                bot.on_action_error(rej)
        for uid, c in sim.chars.items():
            if c["world"] != "village":
                tracks[uid].append(tuple(c["pos"]))
    return bot, tracks


def test_SOAK_the_full_bot_against_the_incoherent_server():
    print(f"[soak] seed {SEED} (override with STEEMER_SIM_SEED)")
    sim = SimServer(seed=SEED, lag=3, mirage_dist=None)
    for n in range(8):
        sim.add_char(f"c{n}", hand=("club" if n < 2 else None),
                     stats={"int": 5} if n == 7 else {})
    sim.guild_gold = 16                      # the dead-capital treasury, exactly
    sim.add_vault("potion_red", phantom=True)
    sim.add_vault("potion_red", phantom=True)
    sim.add_vault("club", phantom=False)
    for w in ("vale", "mines", "spire"):
        for k in range(3):
            sim.seed_loot(w, (2 + k * 3, 4 + k), kind="egg")
    bot, tracks = _soak(sim, 1500)

    # -- the invariant battery --
    fam = Counter(e["reason"] for e in sim.errors)
    total_cmd_errors = sum(fam.values())
    assert sim.deaths == [], f"deaths in a mob-free world: {sim.deaths}"
    for uid, track in tracks.items():
        assert not dance_windows(track), \
            f"{uid} danced: {dance_windows(track)[:2]}"
    # error storms: no family may exceed 40 over 1500 ticks (the live steady state
    # is single digits; 40 leaves room for legitimate trial-ladders and flaps)
    for reason, n in fam.items():
        assert n <= 40, f"error storm: {reason} x{n} (families: {dict(fam)})"
    # the field is worked: chars spent real time out there
    assert tracks and max(len(t) for t in tracks.values()) > 100, \
        f"the field was barely worked: {[len(t) for t in tracks.values()]}"
    equipped = sum(1 for c in sim.chars.values()
                   if (c["equipment"].get("hand") or {}).get("kind"))
    assert equipped >= 3, \
        f"arming never spread past the seeds ({equipped} armed; errors {dict(fam)})"
    # nobody past its potion budget (no potions were obtainable -> hard cap 12...
    # allow the boundary itself)
    for uid, track in tracks.items():
        deep = max((p[1] for p in track), default=0)
        assert deep <= POISON_DEPTH, f"{uid} over-ranged to y={deep} with no heal"


def test_SOAK_with_mirage_and_a_mid_run_stall():
    """The chaos combination that summarizes 2026-08-24: flickering loot plus a
    stalled clock. The battery must still hold."""
    sim = SimServer(seed=SEED + 1, lag=3, mirage_dist=3)
    for n in range(6):
        sim.add_char(f"m{n}", hand=("club" if n < 3 else None))
    sim.guild_gold = 30
    for w in ("vale", "mines", "spire"):
        sim.seed_loot(w, (5, 9), kind="egg", mirage=True)   # ONE flickering item per
        sim.seed_loot(w, (2, 3), kind="egg")                # world, among real loot
    bot, tracks = _soak(sim, 700)
    sim.stall(120)
    bot2, tracks2 = bot, tracks               # continue the same bot through the stall
    for _ in range(300):
        sim.step()
        for frame in sim.frames():
            acts = bot.on_frame(frame)
            for rej in sim.apply(acts):
                bot.on_action_error(rej)
        for uid, c in sim.chars.items():
            if c["world"] != "village":
                tracks[uid].append(tuple(c["pos"]))
    assert sim.deaths == []
    for uid, track in tracks.items():
        assert not dance_windows(track), f"{uid} danced through the mirage/stall"
    fam = Counter(e["reason"] for e in sim.errors)
    for reason, n in fam.items():
        assert n <= 40, f"error storm under chaos: {reason} x{n}"


def test_sim_vault_is_wire_v3_grouped_and_the_bot_still_withdraws():
    """The sim's fidelity contract: guild.inventory is the GROUPED wire-v3 shape
    (one descriptor per kind, count + item_ids) — and the bot's withdrawal chooser,
    routed through protocol.vault_items, still finds a real id behind a phantom."""
    sim = SimServer(seed=3)
    sim.add_char("c1", hand="club")           # armed: heal-first is the live branch
    ghost = sim.add_vault("potion_red", phantom=True)
    real = sim.add_vault("potion_red", phantom=False)
    village = sim.frames()[0]
    inv = village["guild"]["inventory"]
    assert all("item_ids" in e and "item_id" not in e for e in inv), inv
    from steemer.protocol import vault_items
    ids = [i["item_id"] for i in vault_items(village["guild"])
           if i["kind"] == "potion_red"]
    assert set(ids) == {ghost, real}
    assert ids[0] == real, "newest-first ordering lost (the phantom head wins again)"


def test_SOAK_a_frozen_render_must_not_become_an_error_storm():
    """The live 2026-08-25 storm (run #214, 3,654 not_in_village): the server kept
    rendering a RETURNED char in its old world at frozen pos and stamina-above-max;
    the bot commanded moves off the ghost render every tick, and the quarantine and
    the sighting-based unghosting re-armed each other at one error per tick. The
    bounded-cost contract: a frozen render may cost a handful of probes, never a
    storm."""
    sim = SimServer(seed=SEED + 7, lag=3)
    for n in range(4):
        sim.add_char(f"f{n}", hand="club")
    sim.guild_gold = 30
    sim.seed_loot("vale", (4, 5), kind="egg")
    bot, tracks = _soak(sim, 300)
    # the ghost event: f0 (wherever it truly is) starts rendering frozen in the mines
    sim.chars["f0"]["world"] = "village"
    sim.freeze_render("f0", "mines")
    for _ in range(600):
        sim.step()
        for frame in sim.frames():
            acts = bot.on_frame(frame)
            for rej in sim.apply(acts):
                bot.on_action_error(rej)
    niv = sum(1 for e in sim.errors if e["reason"] == "not_in_village")
    assert niv <= 25, f"the frozen render became a storm: {niv} not_in_village"


def test_SOAK_a_DUAL_render_live_here_frozen_there_cannot_storm():
    """Run #215's residual (719 not_in_village at 1-tick gaps): the char is LIVE in
    one world (moving — each sighting proves life and clears the quarantine) while a
    FROZEN render of it persists in another (commands -> errors -> re-quarantine).
    The live render and the dead one fight through a per-uid quarantine. Bounded-cost
    contract: a handful of errors per episode, never a storm — and the live-world
    char keeps working."""
    sim = SimServer(seed=SEED + 11, lag=3)
    for n in range(3):
        sim.add_char(f"d{n}", hand="club")
    sim.guild_gold = 30
    sim.seed_loot("vale", (4, 5), kind="egg")
    bot, tracks = _soak(sim, 200)
    # d0 is truly in the VALE and active; a frozen render of it appears in the MINES
    sim.chars["d0"]["world"] = "vale"
    sim.chars["d0"]["pos"] = [2, 2]
    sim.freeze_render("d0", "mines")
    for _ in range(500):
        sim.step()
        for frame in sim.frames():
            acts = bot.on_frame(frame)
            for rej in sim.apply(acts):
                bot.on_action_error(rej)
        for uid, c in sim.chars.items():
            if c["world"] != "village":
                tracks[uid].append(tuple(c["pos"]))
    niv = sum(1 for e in sim.errors if e["reason"] == "not_in_village")
    assert niv <= 25, f"the dual render stormed: {niv} not_in_village"
    # the live char was not frozen out: it kept moving in the vale
    d0 = tracks.get("d0", [])
    assert len(set(d0[-200:])) > 3, f"the live char was starved by its own ghost: {set(d0[-200:])}"


# ---- sim pass 2 (2026-08-25): mobs ------------------------------------------


def test_sim_a_chaser_pursues_and_bites_and_a_wanderer_never_does():
    sim = SimServer(seed=5)
    sim.add_char("c1")
    sim.chars["c1"]["world"] = "vale"
    sim.chars["c1"]["pos"] = [5, 5]
    sim.chars["c1"]["hp"] = sim.chars["c1"]["max_hp"] = 200   # survive the whole test
    wolf = sim.add_mob("vale", "wolf", (9, 5), behavior="chaser", dmg=4)
    sim.add_mob("vale", "chicken", (5, 7), behavior="wanderer", dmg=0)
    d0 = abs(sim.mobs[wolf]["pos"][0] - 5)
    hp0 = sim.chars["c1"]["hp"]
    for _ in range(8):
        sim.step()
    assert abs(sim.mobs[wolf]["pos"][0] - 5) < d0 or sim.chars["c1"]["hp"] < hp0, \
        "the chaser neither closed nor bit"
    for _ in range(10):
        sim.step()
    assert sim.chars["c1"]["hp"] < hp0, "adjacent chaser never dealt damage"
    assert not any(e.get("attacker_name") == "chicken"
                   for e in sim.events_out), "the wanderer attacked"


def test_sim_a_kill_yields_xp_and_the_bone_drop():
    sim = SimServer(seed=5)
    sim.add_char("c1", hand="club")
    sim.chars["c1"]["world"] = "vale"
    sim.chars["c1"]["pos"] = [5, 5]
    sim.add_mob("vale", "chicken", (5, 6), behavior="wanderer", hp=8, xp=3, drop="bone")
    r = sim.apply([{"char_uid": "c1", "action": "attack", "target": [5, 6]}])
    assert not r, r
    assert not sim.mobs, "one club swing (8) should fell an 8hp chicken"
    kinds = [e["kind"] for e in sim.events_out]
    assert "xp" in kinds and "death" in kinds, kinds
    assert any(i["kind"] == "bone" for i in sim.worlds["vale"]["items"].values()), \
        "the bone never dropped"


def test_SOAK_the_current_build_holds_against_a_mob_world():
    """The leveling lever's precondition measurement: with wildlife to farm and one
    wolf hunting, the CURRENT build must keep its promises — nobody dies to
    wildlife, the wolf's kills stay bounded (dodge/spacing exist), no dancers, and
    armed DEVELOP chars actually farm some xp."""
    sim = SimServer(seed=SEED + 21, lag=3)
    for n in range(6):
        sim.add_char(f"w{n}", hand="club")
    sim.guild_gold = 40
    for w in ("vale", "mines", "spire"):
        for k in range(4):
            sim.add_mob(w, "chicken", (3 + k * 2, 5 + (k % 3)), behavior="wanderer",
                        hp=8, xp=3, drop="bone" if k == 0 else None)
    sim.add_mob("vale", "wolf", (9, 9), behavior="chaser", dmg=4, hp=14, xp=8)
    bot, tracks = _soak(sim, 1200)
    fam = Counter(e["reason"] for e in sim.errors)
    xp_events = sum(1 for uid, c in sim.chars.items())  # survivors
    total_xp = sum(c.get("xp", 0) for c in sim.chars.values())
    assert len(sim.deaths) <= 1, \
        f"the mob world killed {sim.deaths} (dodge/spacing failed)"
    for uid, track in tracks.items():
        assert not dance_windows(track), f"{uid} danced among mobs"
    for reason, n in fam.items():
        assert n <= 40, f"error storm in the mob world: {reason} x{n}"
    assert total_xp > 0, "six armed chars farmed ZERO xp in a world full of chickens"


def test_SOAK_the_leveling_lever_farms_wildlife_at_range():
    """v0.111.1's expression, written FIRST (it fails on the pre-lever build): the
    live map's wildlife sits 6-8 tiles off the strip (4 frog sightings at range vs
    the old radius 5), so a world with all its wildlife at distance ~7 yields ZERO
    xp under the old gates. The lever (COMBAT_SEEK_RADIUS 5 -> 8 for wildlife,
    DEVELOP_HP 0.7 -> 0.6) must convert exactly this world into farmed xp — with
    the chaser-safety promises still held (the wolf config in the base mob soak
    keeps guarding those)."""
    sim = SimServer(seed=SEED + 31, lag=3)
    for n in range(5):
        sim.add_char(f"h{n}", hand="club")
    sim.guild_gold = 40
    # wildlife ONLY at distance ~7 from the y0-2 strip the chars work
    for w in ("vale", "mines", "spire"):
        sim.add_mob(w, "chicken", (4, 7), behavior="wanderer", hp=8, xp=3, drop="bone")
        sim.add_mob(w, "chicken", (8, 8), behavior="wanderer", hp=8, xp=3)
    bot, tracks = _soak(sim, 1200)
    total_xp = sum(c.get("xp", 0) for c in sim.chars.values())
    # calibrated: pre-lever build measured xp 9 on this exact seed; post-lever 12
    # (and 18/18 on neighbour seeds). 11 splits the distributions.
    assert total_xp >= 11, \
        f"the radius wall is back (xp {total_xp}; pre-lever measured 9)"
    assert sim.deaths == [], f"the wider seek got someone killed: {sim.deaths}"
    for uid, track in tracks.items():
        assert not dance_windows(track), f"{uid} danced while hunting"
