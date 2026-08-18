"""The authoritative-roster client (steemer/spectate.py): parsing our guild out
of /api/spectate/guilds, the total/fielded/home split, staleness, and the
network-error fallback. No real network — a fake opener feeds canned JSON."""

import json

import pytest

from steemer import spectate as S
from steemer.spectate import SpectateRoster, http_base_from_server


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(payload):
    return lambda url: _FakeResp(payload)


SPECT = {"tick": 1, "guilds": [
    {"guild_id": "g_me", "name": "Us", "characters": 16,
     "roster": [{"char_uid": f"h{i}", "world": "village"} for i in range(11)]
     + [{"char_uid": f"v{i}", "world": "vale"} for i in range(5)]},
    {"guild_id": "g_rival", "name": "Them", "characters": 25, "roster": []},
]}


def test_parse_extracts_our_guilds_authoritative_counts():
    sr = SpectateRoster("g_me", http_base="https://x", opener=_opener(SPECT))
    assert sr.fetch_once() is True
    total, field, home = sr.counts()
    assert total == 16 and field == {"vale": 5} and home == 11


def test_counts_is_none_until_the_first_successful_fetch():
    sr = SpectateRoster("g_me", http_base="https://x", opener=_opener(SPECT))
    assert sr.counts() is None


def test_our_guild_absent_leaves_the_cache_untouched():
    sr = SpectateRoster("g_missing", http_base="https://x", opener=_opener(SPECT))
    assert sr.fetch_once() is False
    assert sr.counts() is None


def test_home_is_total_minus_fielded_even_if_the_roster_list_lags():
    # characters=20 but roster lists only 5 vale + 3 village -> fielded 5, home 15.
    data = {"guilds": [{"guild_id": "g", "characters": 20,
            "roster": [{"char_uid": f"v{i}", "world": "vale"} for i in range(5)]
            + [{"char_uid": f"h{i}", "world": "village"} for i in range(3)]}]}
    sr = SpectateRoster("g", http_base="https://x", opener=_opener(data))
    sr.fetch_once()
    total, field, home = sr.counts()
    assert total == 20 and field == {"vale": 5} and home == 15


def test_stale_data_reads_as_unavailable(monkeypatch):
    sr = SpectateRoster("g_me", http_base="https://x", poll_seconds=1, opener=_opener(SPECT))
    sr.fetch_once()
    assert sr.counts() is not None
    now = S.time.monotonic()
    monkeypatch.setattr(S.time, "monotonic", lambda: now + 100)   # >> 3× poll
    assert sr.counts() is None


def test_a_network_error_is_swallowed_and_keeps_the_last_good_value():
    sr = SpectateRoster("g_me", http_base="https://x", opener=_opener(SPECT))
    assert sr.fetch_once() is True
    good = sr.counts()

    def boom(url):
        raise OSError("connection refused")
    sr._opener = boom
    assert sr.fetch_once() is False        # error -> False, cache untouched
    assert sr.counts() == good


def test_http_base_derives_from_the_zeromq_server_url():
    assert http_base_from_server("tcp://bot.willmorrison.net:5570") == "https://bot.willmorrison.net"
    assert http_base_from_server("tcp://1.2.3.4:5570") == "https://1.2.3.4"
    assert http_base_from_server(None) == "https://bot.willmorrison.net"
