"""Tests for the learned mob bestiary (steemer.bestiary)."""
from steemer.bestiary import build_bestiary, normalize_frame, MAX_GAP


def _frame(tick, chars, mobs, world="w"):
    return {"world": world, "tick": tick, "chars": chars, "mobs": mobs}


def _char(cid="c1", pos=(0, 0), hp=24, statuses=()):
    return {"id": cid, "pos": pos, "hp": hp, "statuses": list(statuses)}


def _mob(eid, kind, pos, hit=False, dormant=False, elite=False, statuses=()):
    return {"eid": eid, "kind": kind, "pos": pos, "hp_frac": 1.0, "hit": hit,
            "dormant": dormant, "elite": elite, "statuses": list(statuses)}


def test_a_mob_that_closes_on_a_character_is_classified_chaser():
    # two wolves walk one tile straight at a stationary char every tick from dist 12 in.
    # every move shortens the distance -> chaser_score 1.0 and enough samples to trust it.
    frames = []
    for i in range(12):                      # dist 12 -> 1
        d = 12 - i
        frames.append(_frame(100 + i, [_char(pos=(0, 0))], [
            _mob(1, "wolf", (d, 0)),         # approaches along x
            _mob(2, "wolf", (0, d)),         # approaches along y
        ]))
    b = build_bestiary(frames)
    w = b["wolf"]
    assert w["behavior"] == "chaser"
    assert w["chaser_score"] == 1.0
    assert w["dir_samples"] >= 15            # both wolves contribute -> past MIN_DIR_SAMPLES
    assert w["move_rate"] == 1.0
    assert w["aggro_range"] == 12            # furthest distance it was still seen closing


def test_a_mob_that_never_moves_is_classified_stationary():
    # a golem sits on one tile while a char stands two away -> move_rate 0 -> stationary,
    # NOT mislabeled a chaser just because a char is nearby.
    frames = [_frame(200 + i, [_char(pos=(5, 7))], [_mob(9, "golem_stone", (5, 5))])
              for i in range(10)]
    g = build_bestiary(frames)["golem_stone"]
    assert g["behavior"] == "stationary"
    assert g["move_rate"] == 0.0
    assert g["chaser_score"] is None         # it never moved, so no directional evidence


def test_damage_is_attributed_only_when_one_hostile_is_adjacent():
    # char loses 6 hp with a single adjacent delver that struck -> that delver owns the hit.
    frames = [
        _frame(1, [_char(hp=24, pos=(0, 0))], [_mob(3, "delver", (1, 0), hit=True)]),
        _frame(2, [_char(hp=18, pos=(0, 0))], [_mob(3, "delver", (1, 0), hit=True)]),
        _frame(3, [_char(hp=13, pos=(0, 0))], [_mob(3, "delver", (1, 0), hit=True)]),
    ]
    d = build_bestiary(frames)["delver"]
    assert d["est_dmg_per_hit"] == 5.5       # drops of 6 then 5
    assert d["dmg_samples"] == 2
    assert d["hit_rate"] == 1.0


def test_two_adjacent_hostiles_make_the_blow_unattributable():
    # with a delver AND a wolf both adjacent, a drop is ambiguous -> attributed to neither.
    frames = [
        _frame(1, [_char(hp=24)], [_mob(3, "delver", (1, 0)), _mob(4, "wolf", (0, 1))]),
        _frame(2, [_char(hp=14)], [_mob(3, "delver", (1, 0)), _mob(4, "wolf", (0, 1))]),
    ]
    b = build_bestiary(frames)
    assert b["delver"]["est_dmg_per_hit"] is None
    assert b["wolf"]["est_dmg_per_hit"] is None


def test_benign_wildlife_adjacent_is_never_blamed_for_damage():
    # a chicken next to a char losing HP is not a suspect (benign) -> no attribution to it.
    frames = [
        _frame(1, [_char(hp=20)], [_mob(7, "chicken", (1, 0))]),
        _frame(2, [_char(hp=10)], [_mob(7, "chicken", (1, 0))]),
    ]
    c = build_bestiary(frames)["chicken"]
    assert c["est_dmg_per_hit"] is None
    assert c["dmg_samples"] == 0


def test_a_status_gained_next_to_one_hostile_is_attributed():
    # char gains 'poison' while a lone cultist is adjacent -> the cultist applied it.
    frames = [
        _frame(1, [_char(hp=20, statuses=[])], [_mob(5, "cultist", (1, 0))]),
        _frame(2, [_char(hp=20, statuses=["poison"])], [_mob(5, "cultist", (1, 0))]),
    ]
    assert build_bestiary(frames)["cultist"]["status_applied"] == {"poison": 1}


def test_a_move_across_a_long_sight_gap_is_not_counted():
    # the same eid seen again MAX_GAP+1 ticks later is a re-sighting, not a measured move;
    # scoring the jump would invent a huge (false) approach.
    frames = [
        _frame(1, [_char(pos=(0, 0))], [_mob(2, "wolf", (10, 0))]),
        _frame(1 + MAX_GAP + 1, [_char(pos=(0, 0))], [_mob(2, "wolf", (1, 0))]),
    ]
    w = build_bestiary(frames)["wolf"]
    assert w["move_rate"] is None            # no valid consecutive pair -> nothing to rate
    assert w["dir_samples"] == 0


def test_normalize_frame_extracts_monsters_and_chars_from_a_real_shape():
    decoded = {
        "world": "vale", "tick": 555,
        "chars": [{"char_uid": "u1", "pos": [5, 44], "hp": 20,
                   "statuses": [{"kind": "poison"}]}],
        "visible": {"entities": [
            {"eid": 219250, "kind": "lake_drake", "pos": [54, 65], "hp_frac": 1.0,
             "faction": "monster", "elite": False, "dormant": False, "hit": False,
             "statuses": []},
            {"eid": 9, "kind": "recruit-2", "pos": [6, 44], "faction": "guild"},  # dropped
        ]},
    }
    n = normalize_frame(decoded)
    assert n["world"] == "vale" and n["tick"] == 555
    assert n["chars"] == [{"id": "u1", "pos": (5, 44), "hp": 20, "statuses": ["poison"]}]
    assert len(n["mobs"]) == 1               # the guild entity is excluded
    assert n["mobs"][0]["kind"] == "lake_drake" and n["mobs"][0]["pos"] == (54, 65)
