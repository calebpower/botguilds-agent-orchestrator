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


def test_decode_handles_zlib_compressed_and_plain():
    # the server began zlib-compressing wire frames mid-run; decode must handle
    # both a compressed stream (0x78 header) and plain JSON, or every frame
    # crash-loops the bot on json.loads (UnicodeDecodeError on byte 0x9c).
    import json as _json
    import zlib as _zlib
    msg = {"type": "frame", "tick": 42, "world": "vale"}
    plain = _json.dumps(msg).encode("utf-8")
    compressed = _zlib.compress(plain)
    assert compressed[:2] == b"\x78\x9c"          # zlib default header
    assert p.decode(plain) == msg
    assert p.decode(compressed) == msg


# --- v0.44.0 delta frames: seq-gap detection + tile reassembly ---

def test_is_seq_gap():
    assert p.is_seq_gap(None, 5) is False        # no baseline yet
    assert p.is_seq_gap(5, 6) is False           # contiguous
    assert p.is_seq_gap(5, 5) is False           # repeat (not a gap)
    assert p.is_seq_gap(5, 8) is True            # 6,7 dropped
    assert p.is_seq_gap(5, None) is False        # server sent no seq -> nothing to check


def test_reassemble_full_frame_seeds_the_visible_set():
    mem, vis = {}, {}
    frame = {"world": "vale", "delta": False,
             "visible": {"tiles": [[0, 0, "floor"], [1, 0, "wall"]],
                         "entities": [{"eid": 1}], "items": [], "gold": []}}
    p.reassemble_tiles(frame, mem, vis)
    assert vis["vale"] == {(0, 0), (1, 0)}
    assert {tuple(t[:2]) for t in frame["visible"]["tiles"]} == {(0, 0), (1, 0)}
    assert frame["visible"]["entities"] == [{"eid": 1}]     # non-tile layers untouched


def test_reassemble_delta_frame_rebuilds_the_full_visible_tiles():
    mem, vis = {}, {}
    # a full frame establishes vision at (0,0) and (1,0)
    p.reassemble_tiles({"world": "vale", "delta": False,
                        "visible": {"tiles": [[0, 0, "floor"], [1, 0, "wall"]]}}, mem, vis)
    # a delta: (0,0) left vision (gone), (2,0) newly visible; (1,0) unchanged & not re-sent
    delta = {"world": "vale", "delta": True,
             "visible": {"tiles": [[2, 0, "floor"]], "gone": [[0, 0]], "entities": [{"eid": 9}]}}
    p.reassemble_tiles(delta, mem, vis)
    got = {tuple(t[:2]) for t in delta["visible"]["tiles"]}
    assert got == {(1, 0), (2, 0)}          # full CURRENT visible set, not just the delta
    assert delta["visible"]["entities"] == [{"eid": 9}]    # entities passed through
    assert (0, 0) in mem["vale"]            # gone tile is remembered (ever-seen), not deleted


def test_reassemble_never_raises_on_a_malformed_frame():
    # a garbled reassembly must not stop the bot playing
    p.reassemble_tiles({"world": "vale", "delta": True, "visible": {"tiles": [[1]], "gone": None}}, {}, {})
    p.reassemble_tiles({"world": "vale"}, {}, {})          # no 'visible'
    p.reassemble_tiles({"visible": "nonsense"}, {}, {})
