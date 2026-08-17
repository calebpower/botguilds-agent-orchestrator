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
