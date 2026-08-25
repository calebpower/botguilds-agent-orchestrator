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
