"""v0.79.1 — the hello config is written down.

`hello_ok.config` carries server constants (`ride_max_tiles`, `ride_stamina`, caps) that
exist ONLY in that message. `ride_max_tiles` blocked the rail analysis for two passes
because nothing recorded it — the bot stashed it in memory and it died with the process.

What these do not prove: that the values are READ back by anything. This is capture only.
"""
import json

from steemer.bot import GuildBot
from steemer.storage import Storage


def _hello(config):
    return {"type": "hello_ok", "tick": 7, "config": config, "guild": {"gold": 5}}


def test_the_hello_config_lands_in_learned(tmp_path):
    st = Storage(str(tmp_path / "c.db"))
    st.begin_run("sha", "test/0")
    bot = GuildBot("explorer", storage=st)
    bot.on_hello(_hello({"ride_max_tiles": 9, "party_cap": 5}))
    rows = st.conn.execute(
        "SELECT fact FROM learned WHERE topic='server_config'").fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0]) == {"party_cap": 5, "ride_max_tiles": 9}


def test_a_reconnect_with_the_same_config_writes_no_duplicate(tmp_path):
    """Reconnects happen every server_pause; record_learned is idempotent on (topic,fact)
    and this pins that the capture actually rides on that idempotence."""
    st = Storage(str(tmp_path / "c.db"))
    st.begin_run("sha", "test/0")
    bot = GuildBot("explorer", storage=st)
    for _ in range(3):
        bot.on_hello(_hello({"ride_max_tiles": 9}))
    n = st.conn.execute(
        "SELECT COUNT(*) FROM learned WHERE topic='server_config'").fetchone()[0]
    assert n == 1


def test_a_CHANGED_config_keeps_both_versions(tmp_path):
    """Will patches the server mid-week; both configs must stay visible with timestamps
    rather than the new one silently replacing the history."""
    st = Storage(str(tmp_path / "c.db"))
    st.begin_run("sha", "test/0")
    bot = GuildBot("explorer", storage=st)
    bot.on_hello(_hello({"ride_max_tiles": 9}))
    bot.on_hello(_hello({"ride_max_tiles": 14}))
    n = st.conn.execute(
        "SELECT COUNT(*) FROM learned WHERE topic='server_config'").fetchone()[0]
    assert n == 2


def test_no_storage_no_crash():
    """Tests and replays run storage-less; the hello must survive that."""
    bot = GuildBot("explorer", storage=None)
    bot.on_hello(_hello({"ride_max_tiles": 9}))
    assert bot.config["ride_max_tiles"] == 9
