"""Tests for rival spectate tracking (steemer.spectate_track) — the pure parse/extract core."""
from steemer.spectate_track import (parse_sse_events, rival_entities, moves_of,
                                     spectate_url, rival_targets)

OURS = "g_cd0e2a"

_FRAME = {
    "tick": 100, "world": "vale",
    "entities": [
        {"eid": 1, "kind": "char", "faction": "guild", "guild_id": "g_cd0e2a",
         "name": "Recruit-1", "pos": [5, 5], "hp_frac": 1.0},            # ours -> excluded
        {"eid": 2, "kind": "char", "faction": "guild", "guild_id": "g_63837f",
         "name": "Willy", "pos": [9, 12], "hp_frac": 0.8, "held": "sword", "outfit": "mail"},  # RIVAL
        {"eid": 3, "kind": "turtle", "faction": "monster", "guild_id": None,
         "pos": [7, 7], "hp_frac": 1.0},                                  # monster -> excluded
    ],
    "events": [
        {"kind": "move", "eid": 2, "from": [9, 11], "to": [9, 12]},       # the rival moved
        {"kind": "attack", "eid": 2, "pos": [9, 12]},                     # not a move
    ],
}


def _sse(*frames):
    import json
    return "".join(f"data: {json.dumps(f)}\n\n" for f in frames)


def test_parse_sse_extracts_data_lines_and_skips_keepalives():
    text = _sse(_FRAME) + ": keepalive comment\n\ndata: not-json\n\n\n"
    got = parse_sse_events(text)
    assert len(got) == 1                       # the one valid data: frame; junk lines dropped
    assert got[0]["tick"] == 100


def test_rival_entities_keeps_only_other_guilds_chars():
    r = rival_entities(_FRAME, OURS)
    assert len(r) == 1                          # our char + the monster are excluded
    assert r[0]["guild_id"] == "g_63837f"
    assert r[0]["pos"] == [9, 12] and r[0]["name"] == "Willy"
    assert r[0]["held"] == "sword" and r[0]["outfit"] == "mail"   # gear captured for recon


def test_our_own_chars_are_never_treated_as_rivals():
    ours_only = {"entities": [
        {"eid": 1, "kind": "char", "faction": "guild", "guild_id": "g_cd0e2a_c1", "pos": [1, 1]}]}
    assert rival_entities(ours_only, OURS) == []   # prefix match -> not a rival


def test_moves_of_returns_only_move_events_with_from_to():
    m = moves_of(_FRAME)
    assert m == [{"eid": 2, "from": [9, 11], "to": [9, 12]}]   # the attack event is dropped


def test_rival_targets_picks_fielded_rival_chars_only():
    roster = {"guilds": [
        {"guild_id": "g_cd0e2a", "roster": [{"char_uid": "g_cd0e2a_c1", "world": "vale"}]},  # us
        {"guild_id": "g_63837f", "roster": [
            {"char_uid": "g_63837f_c9", "world": "vale"},        # rival, fielded -> target
            {"char_uid": "g_63837f_c8", "world": "village"}]},   # rival, parked -> skipped
    ]}
    assert rival_targets(roster, "g_cd0e2a") == [("g_63837f_c9", "vale")]


def test_spectate_url_shape():
    assert spectate_url("https://bot.willmorrison.net/", "g_x_c1", "vale") == \
        "https://bot.willmorrison.net/events/spectate?char=g_x_c1&map=vale"
