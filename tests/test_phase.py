"""v0.117.0 — the dashboard PHASE chip (operator wishlist, 2026-08-26: '"bunker" or
"embark" or "nuisance" etc' replacing the online/offline dot). Five enumerated
states; resolve_phase is pure, api_phase reads the DB bus the bot writes."""
import json
import time
import zlib

from ui.server import resolve_phase, PHASES, PHASE_OFFLINE_S
from steemer.bot import GuildBot


def test_the_enumeration_is_pinned():
    assert PHASES == ("offline", "bunker", "recall", "fielding", "mustering")
    assert PHASE_OFFLINE_S == 15


def test_every_state_is_reachable_and_distinct():
    cases = {
        ("offline",):   resolve_phase(None, "ok", 0),          # never a frame
        ("offline", 2): resolve_phase(60.0, "ok", 5),          # frames stopped
        ("bunker",):    resolve_phase(1.0, "bunker", 0),       # unhealthy, all home
        ("recall",):    resolve_phase(1.0, "bunker", 3),       # unhealthy, walking home
        ("fielding",):  resolve_phase(1.0, "ok", 7),           # normal play afield
        ("mustering",): resolve_phase(1.0, "ok", 0),           # normal play, all home
    }
    assert list(cases.values()) == ["offline", "offline", "bunker", "recall",
                                    "fielding", "mustering"]
    assert set(cases.values()) == set(PHASES) - {""} - (set(PHASES) - set(cases.values()))


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
        bot.on_action_error({"tick": 1000 + i, "reason": "stale_frame"})
    bot._health_step(1012)
    assert [s for _, s, _ in bot.storage.rows][-1] == "phase:bunker", \
        f"the bunker transition never reached the bus: {bot.storage.rows}"
