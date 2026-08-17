"""Wire protocol: (de)serialization and action shape validation."""

from steemer import protocol as p


def test_encode_decode_roundtrip():
    m = p.msg(p.ACTIONS, tick=7, actions=[{"action": "move", "dir": "N", "char_uid": "c1"}])
    assert m["type"] == "actions"
    assert p.decode(p.encode(m)) == m


def test_valid_per_character_action():
    assert p.check_action({"char_uid": "c1", "action": "move", "dir": "N"}) is None


def test_guild_action_needs_no_char_uid():
    assert p.check_action({"action": "recruit"}) is None
    assert p.check_action({"action": "embark", "map": "vale", "char_uids": ["c1"]}) is None


def test_per_character_action_requires_char_uid():
    assert p.check_action({"action": "move", "dir": "N"}) == "missing_char_uid"


def test_unknown_action_rejected():
    assert p.check_action({"char_uid": "c1", "action": "teleport"}) == "unknown_action"


def test_missing_required_arg():
    assert p.check_action({"char_uid": "c1", "action": "move"}) == "missing_dir"
    assert p.check_action({"char_uid": "c1", "action": "attack"}) == "missing_target"


def test_direction_and_ride_rules():
    # diagonal move is a valid *shape* (server gates it), but not for ride.
    assert p.check_action({"char_uid": "c1", "action": "move", "dir": "NE"}) is None
    assert p.check_action({"char_uid": "c1", "action": "ride", "dir": "NE"}) == "bad_dir"
    assert p.check_action({"char_uid": "c1", "action": "move", "dir": "X"}) == "bad_dir"


def test_target_must_be_two_ints():
    assert p.check_action(
        {"char_uid": "c1", "action": "attack", "target": [1, 2]}) is None
    assert p.check_action(
        {"char_uid": "c1", "action": "attack", "target": [1, 2, 3]}) == "bad_target"
    assert p.check_action(
        {"char_uid": "c1", "action": "attack", "target": ["a", "b"]}) == "bad_target"


def test_embark_char_uids_must_be_list_of_str():
    assert p.check_action({"action": "embark", "map": "vale", "char_uids": "c1"}) == "bad_char_uids"


def test_string_field_types_checked():
    assert p.check_action({"action": "buy", "kind": 5}) == "bad_kind"


def test_not_an_object():
    assert p.check_action(["nope"]) == "not_an_object"
