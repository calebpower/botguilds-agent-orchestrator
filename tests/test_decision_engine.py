"""The decision engine end to end: synthetic frames -> chosen actions.

These exercise GuildBot + the explorer strategy without any network, which is
the frame-replay tier — the same shape :mod:`steemer.replay` uses on recorded
history.
"""

from steemer.bot import GuildBot
from steemer.storage import Storage


def _bot(storage=None):
    b = GuildBot(strategy="explorer", storage=storage)
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    return b


def _field_char(**over):
    char = {"char_uid": "c1", "pos": [0, 0], "hp": 30, "max_hp": 30,
            "stamina": 40, "carry": {"used": 0, "cap": 20},
            "inventory": [], "stats": {}, "equipment": {}}
    char.update(over)
    return char


def _field_frame(char, tiles, entities=(), items=(), gold=()):
    return {"world": "vale", "tick": 10, "chars": [char],
            "visible": {"tiles": list(tiles), "entities": list(entities),
                        "items": list(items), "gold": list(gold)}}


FLOOR3 = [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]]


def test_attacks_the_adjacent_enemy():
    bot = _bot()
    frame = _field_frame(
        _field_char(),
        FLOOR3,
        entities=[{"pos": [1, 0], "faction": "monster", "kind": "rat", "hp_frac": 0.5}],
    )
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [1, 0]} in actions


def test_drinks_a_potion_when_hurt():
    bot = _bot()
    char = _field_char(hp=5, inventory=[{"kind": "potion_red", "item_id": "p1"}])
    actions = bot.on_frame(_field_frame(char, FLOOR3))
    assert {"char_uid": "c1", "action": "use", "item_id": "p1"} in actions


def test_rests_when_stamina_too_low_to_act():
    bot = _bot()
    char = _field_char(stamina=5)     # below MIN_AFFORD -> rest (send nothing)
    actions = bot.on_frame(_field_frame(char, FLOOR3,
                           entities=[{"pos": [1, 0], "faction": "monster",
                                      "kind": "rat", "hp_frac": 0.1}]))
    assert actions == []              # no action emitted for a resting char


def test_picks_up_loot_underfoot():
    bot = _bot()
    actions = bot.on_frame(_field_frame(_field_char(), FLOOR3,
                                        items=[{"pos": [0, 0], "kind": "egg"}]))
    assert {"char_uid": "c1", "action": "pickup"} in actions


def test_village_sells_before_embarking():
    bot = _bot()
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [{"char_uid": "c1",
                        "inventory": [{"kind": "bone", "item_id": "i1", "tier": 1}],
                        "equipment": {"hand": None}, "stats": {"str": 2},
                        "hp": 10, "max_hp": 10}]}
    actions = bot.on_frame(frame)
    assert actions == [{"char_uid": "c1", "action": "sell", "item_id": "i1"}]


def test_village_recruits_toward_the_cap_when_empty_handed():
    bot = _bot()
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 0, "chars_here": [], "chars_by_world": {}},
             "chars": []}
    assert bot.on_frame(frame) == [{"action": "recruit"}]


def test_affordability_rests_rather_than_attempting_unaffordable(tmp_path):
    # stamina 15 cannot afford an attack (~20) or a move (~20): the character
    # rests (sends nothing) instead of a doomed action that would only earn a
    # not_enough_stamina error and forfeit the idle regen. (0.1.0 would attack.)
    bot = _bot()
    char = _field_char(stamina=15)
    frame = _field_frame(char, FLOOR3,
                         entities=[{"pos": [1, 0], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.5}])
    assert bot.on_frame(frame) == []


def test_acts_once_stamina_is_affordable():
    bot = _bot()
    char = _field_char(stamina=25)     # >= attack cost (~20)
    frame = _field_frame(char, FLOOR3,
                         entities=[{"pos": [1, 0], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.5}])
    assert {"char_uid": "c1", "action": "attack", "target": [1, 0]} in bot.on_frame(frame)


def test_adjacent_monster_is_attacked_never_walked_onto():
    bot = _bot()
    frame = _field_frame(_field_char(), FLOOR3,
                         entities=[{"pos": [0, 1], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.9}])
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "attack", "target": [0, 1]} in actions
    # no emitted move steps onto the monster tile (0,1)
    from steemer import nav
    for a in actions:
        if a.get("action") == "move":
            dx, dy = nav.DIRS[a["dir"]]
            assert (0 + dx, 0 + dy) != (0, 1)


def test_two_characters_do_not_move_onto_the_same_tile():
    # a 1-wide corridor with a single open middle tile; both ends would pick it.
    # Reservation must stop the second from colliding. (0.1.0 collides.)
    bot = _bot()
    W = "wall"
    tiles = [[0, 0, "floor"], [0, 1, "floor"], [0, 2, "floor"],
             [1, 0, W], [1, 1, W], [1, 2, W], [-1, 0, W], [-1, 1, W], [-1, 2, W],
             [0, -1, W], [0, 3, W]]
    a = _field_char(char_uid="a", pos=[0, 0])
    b = _field_char(char_uid="b", pos=[0, 2])
    frame = {"world": "vale", "tick": 10, "chars": [a, b],
             "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}
    actions = bot.on_frame(frame)
    dests = []
    for act in actions:
        if act.get("action") == "move":
            base = a["pos"] if act["char_uid"] == "a" else b["pos"]
            from steemer import nav
            dx, dy = nav.DIRS[act["dir"]]
            dests.append((base[0] + dx, base[1] + dy))
    assert len(dests) == len(set(dests)), f"two chars collided on a tile: {dests}"


def _south_corridor():
    # a north-south corridor: (0,0)=exit row, (0,1), (0,2); an enemy sits east.
    return [[0, 0, "floor"], [0, 1, "floor"], [0, 2, "floor"]]


def test_retreats_at_60pct_even_when_it_would_have_fought_before(tmp_path):
    # 50% HP: below 0.3.0's 0.6 threshold but above 0.2.0's 0.4 — so 0.2.0 would
    # attack the adjacent monster and 0.3.0 flees toward the exit.
    bot = _bot()
    char = _field_char(pos=[0, 1], hp=15, max_hp=30, stamina=40)
    frame = _field_frame(char, _south_corridor(),
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.9}])
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in actions   # fleeing
    assert all(a.get("action") != "attack" for a in actions)             # not fighting


def test_poison_triggers_retreat_even_at_full_hp(tmp_path):
    bot = _bot()
    char = _field_char(pos=[0, 1], hp=30, max_hp=30, stamina=40,
                       statuses=[{"kind": "poison", "ticks_left": 5, "power": 1}])
    frame = _field_frame(char, _south_corridor(),
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.9}])
    actions = bot.on_frame(frame)
    assert {"char_uid": "c1", "action": "move", "dir": "S"} in actions
    assert all(a.get("action") != "attack" for a in actions)


def test_hurt_suppresses_offense_when_it_cannot_flee(tmp_path):
    # boxed in (no walkable exit) and hurt, adjacent to a monster it could afford
    # to hit: 0.2.0 would attack; 0.3.0 offers only heal/flee -> rests (empty).
    W = "wall"
    bot = _bot()
    char = _field_char(pos=[0, 1], hp=10, max_hp=30, stamina=40)
    tiles = [[0, 1, "floor"], [1, 1, "floor"],
             [0, 0, W], [0, 2, W], [-1, 1, W]]
    frame = _field_frame(char, tiles,
                         entities=[{"pos": [1, 1], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.5}])
    assert bot.on_frame(frame) == []          # heal/flee only, both impossible -> rest


def test_village_buys_a_potion_when_armed_and_carrying_none():
    bot = _bot()
    char = {"char_uid": "c1", "inventory": [], "equipment": {"hand": {"kind": "club"}},
            "stats": {"str": 2}, "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == [{"char_uid": "c1", "action": "buy", "kind": "potion_red"}]


def test_village_does_not_buy_a_second_potion():
    bot = _bot()
    char = {"char_uid": "c1",
            "inventory": [{"kind": "potion_red", "item_id": "p1", "tier": 1}],
            "equipment": {"hand": {"kind": "club"}}, "stats": {"str": 2},
            "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 100, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    actions = bot.on_frame(frame)
    assert all(not (a.get("action") == "buy" and a.get("kind") == "potion_red")
               for a in actions)


def _village_char(**over):
    # armed + carrying a potion so the sell/weapon/potion steps all no-op and we
    # reach the spend_xp step.
    char = {"char_uid": "c1", "hp": 30, "max_hp": 30,
            "inventory": [{"kind": "potion_red", "item_id": "p1", "tier": 1}],
            "equipment": {"hand": {"kind": "club"}},
            "stats": {"vit": 1, "end": 1, "str": 1}, "gifts": [], "xp": 0}
    char.update(over)
    return char


def _village_frame1(char, gold=100):
    return {"world": "village", "tick": 3,
            "guild": {"gold": gold, "chars_here": ["c1"], "chars_by_world": {}},
            "chars": [char]}


def test_village_spends_xp_on_vit_first():
    bot = _bot()
    char = _village_char(stats={"vit": 1, "end": 1, "str": 1}, xp=10)
    assert bot.on_frame(_village_frame1(char)) == \
        [{"char_uid": "c1", "action": "spend_xp", "stat": "vit"}]


def test_village_spends_end_after_vit_capped():
    bot = _bot()
    char = _village_char(stats={"vit": 8, "end": 1, "str": 1}, xp=10)
    assert bot.on_frame(_village_frame1(char)) == \
        [{"char_uid": "c1", "action": "spend_xp", "stat": "end"}]


def test_village_gift_halves_xp_cost():
    # vit=2 costs 16 XP normally, 8 as a gift. With exactly 8 XP, only the gifted
    # character can afford the point.
    bot = _bot()
    gift = _village_char(stats={"vit": 2, "end": 8, "str": 8}, xp=8, gifts=["vit"])
    assert {"char_uid": "c1", "action": "spend_xp", "stat": "vit"} in bot.on_frame(_village_frame1(gift))
    nongift = _village_char(stats={"vit": 2, "end": 8, "str": 8}, xp=8, gifts=[])
    assert all(a.get("action") != "spend_xp" for a in bot.on_frame(_village_frame1(nongift)))


def test_village_no_xp_spend_when_stats_capped():
    bot = _bot()
    char = _village_char(stats={"vit": 8, "end": 8, "str": 8}, xp=9999)
    assert all(a.get("action") != "spend_xp" for a in bot.on_frame(_village_frame1(char)))


def _equip_char(inv, equipment=None, uid="c1"):
    return {"char_uid": uid, "hp": 30, "max_hp": 30, "inventory": inv,
            "equipment": equipment or {"hand": None, "offhand": None,
                                       "outfit": None, "trinket": None, "boots": None},
            "stats": {"vit": 1, "end": 1, "str": 1}, "gifts": [], "xp": 0}


def _vframe(char, gold=100):
    return {"world": "village", "tick": 3,
            "guild": {"gold": gold, "chars_here": [char["char_uid"]], "chars_by_world": {}},
            "chars": [char]}


def test_village_equips_carried_gear_before_selling():
    bot = _bot()
    char = _equip_char([{"kind": "ore_copper", "item_id": "o1", "uses": []},
                        {"kind": "rusty_sword", "item_id": "w1", "uses": ["equip", "attack"]}])
    # must EQUIP the sword (not sell the ore first, and not leave the sword unworn)
    assert bot.on_frame(_vframe(char)) == \
        [{"char_uid": "c1", "action": "equip", "slot": "hand", "item_id": "w1"}]


def test_village_equips_into_empty_slot_when_hand_is_taken():
    bot = _bot()
    char = _equip_char([{"kind": "hide_vest", "item_id": "a1", "uses": ["equip"]}],
                       equipment={"hand": {"kind": "club"}, "offhand": None,
                                  "outfit": None, "trinket": None, "boots": None})
    # hand occupied -> it must probe the first EMPTY slot, not skip the armor
    assert bot.on_frame(_vframe(char)) == \
        [{"char_uid": "c1", "action": "equip", "slot": "offhand", "item_id": "a1"}]


def test_wrong_slot_is_learned_then_next_slot_tried():
    bot = _bot()
    char = _equip_char([{"kind": "hide_vest", "item_id": "a1", "uses": ["equip"]}])
    first = bot.on_frame(_vframe(char))
    assert first[0]["slot"] == "hand"                    # first empty slot
    bot.strategy.on_action_error(bot, {"action": "equip", "char_uid": "c1",
                                       "reason": "wrong_slot"})
    second = bot.on_frame(_vframe(char))
    assert second[0]["slot"] == "offhand"                # hand now known-wrong


def test_stat_requirement_marks_unusable_and_then_sells():
    bot = _bot()
    char = _equip_char([{"kind": "heavy_maul", "item_id": "m1", "uses": ["equip"]}])
    bot.on_frame(_vframe(char))                          # attempt equip
    bot.strategy.on_action_error(bot, {"action": "equip", "char_uid": "c1",
                                       "reason": "stat_requirement"})
    # unusable now -> not re-equipped, and sold rather than hoarded
    assert bot.on_frame(_vframe(char)) == \
        [{"char_uid": "c1", "action": "sell", "item_id": "m1"}]


def test_field_character_that_is_crafting_rests():
    bot = _bot()
    char = _field_char(craft={"kind": "brew", "ticks_left": 5})
    frame = _field_frame(char, FLOOR3,
                         entities=[{"pos": [1, 0], "faction": "monster",
                                    "kind": "rat", "hp_frac": 0.2}])
    # busy crafting -> take no action (any action would error `crafting`)
    assert bot.on_frame(frame) == []


def _brew_char(inv, gold_stats_capped=True, **over):
    char = {"char_uid": "c1", "hp": 30, "max_hp": 30, "inventory": inv,
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None},
            "stats": {"vit": 8, "end": 8, "str": 8}, "gifts": [], "xp": 0}
    char.update(over)
    return char


def test_village_brews_ingredients_with_a_bottle():
    bot = _bot()
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "frostmoss", "item_id": "f1", "uses": ["brew", "taste"]},
                       {"kind": "bottle_empty", "item_id": "bot1", "uses": []}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "brew", "item_ids": ["b1", "f1"]}]


def test_village_buys_a_bottle_when_it_has_ingredients_but_none():
    bot = _bot()
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "frostmoss", "item_id": "f1", "uses": ["brew", "taste"]}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 15, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "buy", "kind": "bottle_empty"}]


def test_village_keeps_ingredients_and_food_sells_pure_loot():
    bot = _bot()
    # brewable + food listed FIRST so the test fails if _should_sell stops
    # keeping them (it would sell b1/m1 before reaching the ore).
    char = _brew_char([{"kind": "bitterroot", "item_id": "b1", "uses": ["brew", "taste"]},
                       {"kind": "meat", "item_id": "m1", "uses": ["drink"]},
                       {"kind": "ore_copper", "item_id": "o1", "uses": ["forge"]}])
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 5, "chars_here": ["c1"], "chars_by_world": {}},
             "chars": [char]}
    # only one brewable (<2) so no brew; the ore is pure loot -> sold; the
    # brew ingredient and the food are kept, not sold.
    assert bot.on_frame(frame) == \
        [{"char_uid": "c1", "action": "sell", "item_id": "o1"}]


def test_village_leaves_a_crafting_character_alone():
    bot = _bot()
    busy = {"char_uid": "c1", "craft": {"kind": "brew", "ticks_left": 7},
            "inventory": [], "equipment": {}, "stats": {}, "hp": 30, "max_hp": 30}
    frame = {"world": "village", "tick": 3,
             "guild": {"gold": 500, "chars_here": ["c1"],
                       "chars_by_world": {"vale": ["a", "b", "c", "d", "e"],
                                          "mines": ["f", "g", "h", "i", "j"]}},
             "chars": [busy]}
    # roster at world_cap and the only home char is busy -> no action (not sold,
    # not embarked, which would abandon the brew)
    assert bot.on_frame(frame) == []


def test_decisions_are_persisted(tmp_path):
    s = Storage(str(tmp_path / "d.db"), commit_every=1)
    bot = _bot(storage=s)
    bot.on_frame(_field_frame(_field_char(), FLOOR3,
                 entities=[{"pos": [1, 0], "faction": "monster",
                            "kind": "rat", "hp_frac": 0.5}]))
    row = s.conn.execute(
        "SELECT char_uid, action, reasoning FROM decisions").fetchone()
    assert row[0] == "c1" and row[1] == "attack"
    assert "attack adjacent" in row[2]     # the verbose reasoning was stored
    s.close()
