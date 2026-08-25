"""v0.108.0 — feed the flywheel without spending gold.

#203's census: 30 chars collectively held one vigor herb, gold 20, and the shop's 15g
club was unaffordable — while the vault listed 14 clubs (real: lumber withdrawals prove
non-potion vault entries live) and 202 potion_red probed only ~8 entries deep per run
because the phantom latch reset on every restart. Two levers: (1) a bare char ARMS FROM
THE VAULT (free) before the shop is even considered; (2) phantom vault ids PERSIST via
intel, and the storm latch counts fresh probes per run, so successive runs walk deeper
into the list instead of re-treading the same dead head.
"""
import json

from steemer.bot import GuildBot
from steemer.storage import Storage


def _bot(storage=None):
    b = GuildBot(strategy="explorer", storage=storage)
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 6,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    return b


def _char(uid, hand=None, inventory=None):
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": [3, 3], "hp": 30,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": 3,
            "stats": {}, "gifts": ["vit"], "statuses": [], "spells": [], "spell_cap": 1,
            "carry": {"used": 0, "cap": 20}, "inventory": list(inventory or []),
            "equipment": {"hand": ({"kind": hand} if hand else None)}}


def _village(here_chars, vault=(), gold=20, tick=500):
    return {"world": "village", "tick": tick, "events": [],
            "guild": {"guild_id": "g_us", "gold": gold,
                      "chars_here": [c["char_uid"] for c in here_chars],
                      "chars_by_world": {"vale": ["g1"],
                                         "mines": [f"v{i}" for i in range(4)]},
                      "inventory": [dict(v) for v in vault],
                      "market_listings": []},
            "shop": {"stock": [{"kind": "club", "buy_price": 15}]}, "chars": here_chars}


CLUB = {"kind": "club", "item_id": 9001}


def test_a_bare_char_arms_from_the_vault_for_free():
    # gold 20 is BELOW the weapon floor (45): the shop path is shut, and before
    # v0.108.0 this char stayed bare. The vault club costs nothing.
    acts = _bot().on_frame(_village([_char("c1")], vault=[CLUB], gold=20))
    assert {"char_uid": "c1", "action": "drop", "item_id": 9001} in acts, \
        f"bare char did not withdraw the banked club: {acts}"


def test_an_armED_char_leaves_the_vault_clubs_alone():
    acts = _bot().on_frame(_village([_char("c1", hand="club")], vault=[CLUB], gold=20))
    assert all(not (a.get("action") == "drop" and a.get("item_id") == 9001)
               for a in acts), f"an armed char hoarded a vault club: {acts}"


def test_a_dead_vault_club_id_is_skipped():
    bot = _bot()
    bot.strategy._vault_dead.add(9001)
    acts = bot.on_frame(_village([_char("c1")], vault=[CLUB,
                                                       {"kind": "club", "item_id": 9002}],
                                 gold=20))
    drops = [a for a in acts if a.get("action") == "drop"]
    assert drops and drops[0]["item_id"] == 9002, \
        f"withdrew a known phantom instead of the next entry: {acts}"


def test_phantom_ids_PERSIST_across_a_restart(tmp_path):
    # End-to-end through the REAL error path and the REAL storage: run 1 discovers a
    # phantom (no_such_item on its withdrawal); a FRESH bot on the same storage must
    # skip that id without re-probing it.
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("sha", "test/0")
    bot = _bot(storage=st)
    acts = bot.on_frame(_village([_char("c1")], vault=[CLUB], gold=20))
    assert acts and acts[0]["action"] == "drop" and acts[0]["item_id"] == 9001
    bot.on_action_error({"char_uid": "c1", "action": "drop",
                         "reason": "no_such_item", "tick": 501})
    st.conn.commit()
    # the restart: new process, same DB
    bot2 = _bot(storage=st)
    acts2 = bot2.on_frame(_village([_char("c1")], vault=[CLUB], gold=20, tick=600))
    assert all(not (a.get("action") == "drop" and a.get("item_id") == 9001)
               for a in acts2), f"re-probed a phantom the last run already proved: {acts2}"


def test_the_storm_latch_counts_fresh_probes_not_hydrated_knowledge(tmp_path):
    # With >= VAULT_DEAD_LIMIT phantoms hydrated from earlier runs, the latch must
    # still allow NEW probes this run — else persistence would permanently close the
    # vault the moment 8 phantoms were ever known.
    from steemer.strategy.explorer import VAULT_DEAD_LIMIT
    assert VAULT_DEAD_LIMIT == 8, "the limit moved; re-read the numbers in this test"
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("sha", "test/0")
    from steemer import intel
    import time
    intel.record(st.conn, "vault_phantom", 400, time.time(),
                 {"ids": list(range(8100, 8112))})          # 12 known phantoms
    bot = _bot(storage=st)
    acts = bot.on_frame(_village([_char("c1")], vault=[{"kind": "club", "item_id": 8100},
                                                       CLUB], gold=20))
    drops = [a for a in acts if a.get("action") == "drop"]
    assert drops and drops[0]["item_id"] == 9001, \
        f"hydrated knowledge closed the latch (or the phantom was re-probed): {acts}"


def test_the_POTION_withdrawal_latch_also_counts_fresh_probes(tmp_path):
    # The twin of the club-side latch test — the first draft only covered the club
    # branch and the potion-side mutant survived. Hydrated phantoms must not close
    # the POTION withdrawal either.
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("sha", "test/0")
    from steemer import intel
    import time
    intel.record(st.conn, "vault_phantom", 400, time.time(),
                 {"ids": list(range(8100, 8112))})
    bot = _bot(storage=st)
    vault = [{"kind": "potion_red", "item_id": 8100},        # known phantom
             {"kind": "potion_red", "item_id": 9500}]        # unprobed
    acts = bot.on_frame(_village([_char("c1", hand="club")], vault=vault, gold=20))
    drops = [a for a in acts if a.get("action") == "drop"]
    assert drops and drops[0]["item_id"] == 9500, \
        f"hydrated knowledge closed the potion withdrawal: {acts}"


def test_a_potion_storm_closes_the_POTION_withdrawal_only():
    # v0.108.1 semantics change, deliberate: the potion latch closes the potion
    # withdrawal but must NOT close the club probe (that shared-latch coupling is the
    # #204 starvation bug). An ARMED char after a full potion storm gets no drop at
    # all; the club side is asserted in the starvation test below.
    bot = _bot()
    for n in range(8):                                       # 8 fresh phantoms via the
        bot.strategy._vault_pending["c1"] = 9600 + n         # REAL error path
        bot.on_action_error({"char_uid": "c1", "action": "drop",
                             "reason": "no_such_item", "tick": 500 + n})
    vault = [{"kind": "potion_red", "item_id": 9701}]
    acts = bot.on_frame(_village([_char("c1", hand="club")], vault=vault, gold=20))
    assert all(a.get("action") != "drop" for a in acts), \
        f"the potion withdrawal kept probing after a full storm: {acts}"


def test_a_potion_phantom_storm_does_NOT_starve_the_club_probe():
    # v0.108.1 — the live #204 failure, minutes after 0.108.0 shipped: heal-first runs
    # before arming, burned the full shared latch on potion phantoms, and the 14 clubs
    # were never probed at all. The arm branch has its own failure budget.
    bot = _bot()
    for n in range(8):                                       # a full potion storm,
        bot.strategy._vault_pending["c1"] = 9600 + n         # through the real path
        bot.on_action_error({"char_uid": "c1", "action": "drop",
                             "reason": "no_such_item", "tick": 500 + n})
    acts = bot.on_frame(_village([_char("c1", hand="club"), _char("c2")],
                                 vault=[CLUB], gold=20))
    assert {"char_uid": "c2", "action": "drop", "item_id": 9001} in acts, \
        f"the potion storm starved the club probe: {acts}"


def test_successful_club_withdrawals_never_consume_the_arm_budget():
    # 14 real clubs must arm 14 chars: only FAILURES latch. Issue five arm
    # withdrawals with no errors between them — the fifth must still fire
    # (an issue-counting mutant latches after four).
    from steemer.strategy.explorer import VAULT_ARM_PROBES
    assert VAULT_ARM_PROBES == 4, "the budget moved; re-read the numbers in this test"
    bot = _bot()
    for n in range(5):
        vault = [{"kind": "club", "item_id": 9800 + n}]
        acts = bot.on_frame(_village([_char(f"b{n}")], vault=vault, gold=20,
                                     tick=500 + n))
        assert {"char_uid": f"b{n}", "action": "drop", "item_id": 9800 + n} in acts, \
            f"withdrawal {n} did not fire (successes are latching): {acts}"
        bot.strategy._vault_pending.pop(f"b{n}", None)   # the withdrawal landed


def test_club_phantoms_DO_latch_the_arm_branch():
    # the anti-storm half: four failed club probes close the arm branch for the run.
    bot = _bot()
    for n in range(4):
        t = 500 + 10 * n                # spaced past VILLAGE_ACTION_COOLDOWN (6)
        acts = bot.on_frame(_village([_char("c1")],
                                     vault=[{"kind": "club", "item_id": 9900 + n}],
                                     gold=20, tick=t))
        assert any(a.get("action") == "drop" for a in acts), f"probe {n} missing"
        bot.on_action_error({"char_uid": "c1", "action": "drop",
                             "reason": "no_such_item", "tick": t})
    acts = bot.on_frame(_village([_char("c1")],
                                 vault=[{"kind": "club", "item_id": 9950}],
                                 gold=20, tick=600))
    assert all(a.get("action") != "drop" for a in acts), \
        f"the arm branch kept probing after a full storm: {acts}"


# ---- wire v3 (2026-08-25): grouped guild inventory ---------------------------

def test_wire_v3_grouped_vault_still_arms_and_withdraws():
    """Will's breaking change: one descriptor per kind with count + item_ids. The
    protocol.vault_items seam bridges it; a bare char arms from a grouped club
    entry exactly as it did from a per-item one."""
    vault = [{"kind": "club", "tier": 1, "count": 2, "item_ids": [9001, 9002]}]
    acts = _bot().on_frame(_village([_char("c1")], vault=vault, gold=20))
    drops = [a for a in acts if a.get("action") == "drop"]
    assert drops and drops[0]["item_id"] == 9002, \
        f"grouped vault not bridged (or newest-first lost): {drops}"


def test_wire_v3_dead_ids_are_skipped_within_a_group():
    bot = _bot()
    bot.strategy._vault_dead.add(9002)                  # the newest is a phantom
    vault = [{"kind": "club", "tier": 1, "count": 2, "item_ids": [9001, 9002]}]
    acts = bot.on_frame(_village([_char("c1")], vault=vault, gold=20))
    drops = [a for a in acts if a.get("action") == "drop"]
    assert drops and drops[0]["item_id"] == 9001, \
        f"did not fall through the group past the dead id: {drops}"


def test_old_format_frames_still_work_for_replay():
    """Recorded history predates wire v3; the seam must pass per-item entries
    through untouched — every fixture above this line is that proof, and this test
    names the claim so the ratchet knows it is deliberate."""
    acts = _bot().on_frame(_village([_char("c1")], vault=[CLUB], gold=20))
    assert {"char_uid": "c1", "action": "drop", "item_id": 9001} in acts
