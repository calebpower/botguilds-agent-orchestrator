"""v0.117.0 — the dashboard PHASE chip (operator wishlist, 2026-08-26: '"bunker" or
"embark" or "nuisance" etc' replacing the online/offline dot). Five enumerated
states; resolve_phase is pure, api_phase reads the DB bus the bot writes."""
import json
import time
import zlib

from ui.server import resolve_phase, PHASES, PHASE_OFFLINE_S
from steemer.bot import GuildBot


def test_the_enumeration_is_pinned():
    assert PHASES == ("offline", "bunker", "recall", "squall", "fielding", "mustering")
    assert PHASE_OFFLINE_S == 15


def test_every_state_is_reachable_and_distinct():
    cases = {
        ("offline",):   resolve_phase(None, "ok", 0),          # never a frame
        ("offline", 2): resolve_phase(60.0, "ok", 5),          # frames stopped
        ("bunker",):    resolve_phase(1.0, "bunker", 0),       # unhealthy, all home
        ("recall",):    resolve_phase(1.0, "bunker", 3),       # unhealthy, walking home
        ("squall",):    resolve_phase(1.0, "squall", 7),       # burst hold, in place
        ("fielding",):  resolve_phase(1.0, "ok", 7),           # normal play afield
        ("mustering",): resolve_phase(1.0, "ok", 0),           # normal play, all home
    }
    assert list(cases.values()) == ["offline", "offline", "bunker", "recall",
                                    "squall", "fielding", "mustering"]
    assert set(cases.values()) == set(PHASES)


def test_the_offline_boundary_is_strict():
    assert resolve_phase(PHASE_OFFLINE_S + 0.1, "ok", 5) == "offline"
    assert resolve_phase(PHASE_OFFLINE_S - 0.1, "ok", 5) == "fielding"


class _PhaseSpyStorage:
    def __init__(self):
        self.rows = []

    def record_anomaly(self, tick, subtype, detail):
        self.rows.append((tick, subtype, detail))


def test_the_bot_persists_phase_on_transition_and_on_hello():
    """The DB bus the chip reads: hello anchors phase:ok; a poison storm writes
    phase:bunker. End-to-end through on_hello / on_action_error / on_frame."""
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                  "maps": [{"id": "vale"}]}
    bot.storage = _PhaseSpyStorage()
    bot.on_hello({"config": bot.config, "guild": {}, "tick": 900})
    assert [s for _, s, _ in bot.storage.rows] == ["phase:ok"], \
        "the hello did not anchor the phase row"
    for i in range(12):
        bot.on_action_error({"tick": 780 + i * 20, "reason": "stale_frame"})
    bot._health_step(1012)
    assert [s for _, s, _ in bot.storage.rows][-1] == "phase:bunker", \
        f"the bunker transition never reached the bus: {bot.storage.rows}"


def test_api_phase_is_cached_single_flight(monkeypatch, tmp_path):
    """2026-08-28: storm-slow DB + per-tab 5s polling stacked 147 concurrent
    connections and exhausted MariaDB (1040). Rapid calls must share one query."""
    from ui import server
    calls = []
    monkeypatch.setattr(server, "_api_phase_uncached",
                        lambda db: calls.append(1) or {"ok": True, "phase": "offline"})
    server._phase_cache["data"] = None
    server._phase_cache["at"] = 0.0
    a = server.api_phase("x")
    b = server.api_phase("x")
    c = server.api_phase("x")
    assert a["phase"] == b["phase"] == c["phase"] == "offline"
    assert len(calls) == 1, f"cache miss on rapid repeat: {len(calls)} queries"
