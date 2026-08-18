"""The dashboard's hand-rolled WebSocket push.

The socket carries the *data*: a client subscribes to the view it is showing with
a seq/version cursor, and the server streams only what is newer. These tests cover
the RFC6455 framing/handshake (pure, known-answer), the per-view delta builders
(unit, over a temp SQLite DB), and an end-to-end subscribe -> write -> receive-the-
new-rows path asserted from BOTH sides (a write DOES push; an idle window does NOT).
"""

import io
import json
import socket
import threading
import time

import ui.server as srv
from steemer import db as _db
from steemer.storage import Storage


# --- handshake + framing (pure, known-answer) ------------------------------- #

def test_accept_key_matches_rfc6455_example():
    assert srv._ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_encode_small_text_frame():
    f = srv._ws_encode(b"hi")
    assert f == bytes([0x81, 0x02]) + b"hi"     # FIN|text, len 2, payload


def test_read_frame_unmasks_client_data():
    mask = bytes([0x01, 0x02, 0x03, 0x04])
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(b"ok"))
    raw = bytes([0x81, 0x80 | 0x02]) + mask + payload
    opcode, data = srv._ws_read_frame(io.BytesIO(raw))
    assert opcode == 0x1 and data == b"ok"


# --- subscription parsing --------------------------------------------------- #

class _DummySock:
    def sendall(self, *_):  # WSClient only touches the sock on send/pong
        pass


def test_apply_sub_records_view_and_ignores_garbage():
    c = srv.WSClient(_DummySock())
    srv._apply_sub(c, b'{"t":"sub","tab":"decisions","params":{"world":"vale"},"cursor":{"seq":5}}')
    sub = c.get_sub()
    assert sub == {"tab": "decisions", "params": {"world": "vale"}, "cursor": {"seq": 5}}
    srv._apply_sub(c, b"not json at all")        # malformed -> ignored, sub kept
    assert c.get_sub()["tab"] == "decisions"


def test_advance_cursor_no_ops_after_a_view_change():
    # A stale push must not clobber the cursor of a view the client switched to.
    c = srv.WSClient(_DummySock())
    c.set_sub("decisions", {"world": "vale"}, {"seq": 10})
    c.set_sub("map", {"world": "vale"}, {"seq": 3})          # user switched tabs
    c.advance_cursor("decisions", {"world": "vale"}, {"seq": 99})   # late decisions push
    assert c.get_sub() == {"tab": "map", "params": {"world": "vale"}, "cursor": {"seq": 3}}


# --- per-view delta builders (unit, temp SQLite) ---------------------------- #

def _seed(tmp_path):
    db = str(tmp_path / "d.db")
    s = Storage(db, commit_every=1)
    s.begin_run("sha", "v/1")
    for i in range(3):
        s.record_decision(tick=i, world="vale", char_uid="c1",
                           chosen={"action": "move"}, alternatives=[],
                           reasoning=f"r{i}", strategy_version="v/1")
    s.close()
    return {"type": "sqlite", "path": db}


def test_delta_decisions_returns_only_rows_past_cursor(tmp_path):
    cfg = _seed(tmp_path)
    conn = _db.connect(cfg, readonly=True)
    try:
        msg, cur = srv._delta_decisions(conn, {}, {"seq": 0})
        allrows = msg["rows"]                    # newest-first
        assert [r["reasoning"] for r in allrows] == ["r2", "r1", "r0"]
        assert cur["seq"] == allrows[0]["seq"]
        # cursor at the middle row -> only the newest is new
        mid = allrows[1]["seq"]
        msg2, _ = srv._delta_decisions(conn, {}, {"seq": mid})
        assert [r["reasoning"] for r in msg2["rows"]] == ["r2"]
        # cursor at the top -> nothing new
        assert srv._delta_decisions(conn, {}, {"seq": cur["seq"]}) is None
    finally:
        conn.close()


def test_delta_decisions_respects_the_char_filter(tmp_path):
    db = str(tmp_path / "f.db")
    s = Storage(db, commit_every=1)
    s.begin_run("sha", "v/1")
    s.record_decision(tick=1, world="vale", char_uid="c1", chosen={"action": "a"},
                      alternatives=[], reasoning="c1-move", strategy_version="v/1")
    s.record_decision(tick=2, world="vale", char_uid="c2", chosen={"action": "b"},
                      alternatives=[], reasoning="c2-move", strategy_version="v/1")
    s.close()
    conn = _db.connect({"type": "sqlite", "path": db}, readonly=True)
    try:
        msg, _ = srv._delta_decisions(conn, {"char": "c2"}, {"seq": 0})
        assert [r["reasoning"] for r in msg["rows"]] == ["c2-move"]
    finally:
        conn.close()


def _map_frame(tick):
    return {"type": "frame", "tick": tick, "world": "vale",
            "chars": [{"char_uid": "c2", "pos": [3, 4], "hp": 9, "max_hp": 10}],
            "visible": {"tiles": [[3, 4, "grass", 1], [3, 5, "wall", 2]],
                        "entities": [{"pos": [5, 5], "faction": "monster"}],
                        "items": [], "gold": []}}


def test_delta_map_pushes_overlay_plus_new_tiles_then_settles(tmp_path):
    db = str(tmp_path / "m.db")
    s = Storage(db, commit_every=1)
    s.begin_run("sha", "v/1")
    s.record_frame(_map_frame(10))
    s.close()
    conn = _db.connect({"type": "sqlite", "path": db}, readonly=True)
    try:
        msg, cur = srv._delta_map(conn, {"world": "vale"}, {"seq": 0, "tick": -1})
        assert msg["t"] == "map" and msg["world"] == "vale"
        assert msg["overlay"] is not None            # a new frame -> overlay sent
        assert len(msg["tiles"]) == 2                # both tiles are newer than -1
        assert msg["overlay"]["entities"][0]["faction"] == "monster"
        assert cur["seq"] > 0 and cur["tick"] == 10
        # nothing new since that cursor
        assert srv._delta_map(conn, {"world": "vale"}, cur) is None
    finally:
        conn.close()


def test_delta_snapshot_pushes_once_per_version(monkeypatch):
    with srv._snap_lock:
        srv._snap_state.update(snap=None, computed_at=0.0, error=None, version=0)
    monkeypatch.setattr(srv.metrics, "snapshot", lambda db: {"volume": {"frames": 1}})
    srv._publish_snapshot("db")                      # version 0 -> 1
    msg, cur = srv._delta_snapshot({"version": 0})
    assert msg["t"] == "snapshot" and cur["version"] == 1
    assert msg["data"]["version"] == 1 and msg["data"]["ok"] is True
    assert srv._delta_snapshot({"version": 1}) is None      # same version -> quiet


def test_delta_logs_streams_tail_and_resends_on_rotation(tmp_path, monkeypatch):
    import os
    p = tmp_path / "x.log"
    p.write_text("hello\n")
    monkeypatch.setitem(srv.LOG_FILES, "x", str(p))
    sz = os.path.getsize(p)
    # cursor at current size -> nothing new
    assert srv._delta_logs({"name": "x"}, {"name": "x", "size": sz}) is None
    # append -> only the new tail is pushed, cursor advances to the new byte size
    with open(p, "a") as fh:
        fh.write("world\n")
    msg, cur = srv._delta_logs({"name": "x"}, {"name": "x", "size": sz})
    assert msg["append"] == "world\n" and cur["size"] == os.path.getsize(p)
    # size shrank (rotation/truncation) -> full resend, not a bogus tail
    p.write_text("re\n")
    msg2, cur2 = srv._delta_logs({"name": "x"}, {"name": "x", "size": 999})
    assert msg2["full"] == "re\n" and cur2["size"] == os.path.getsize(p)
    # the client is on a different file than the cursor -> REST load owns it, no push
    assert srv._delta_logs({"name": "x"}, {"name": "decisions", "size": 0}) is None


# --- end-to-end: subscribe -> write -> receive the new rows ----------------- #

def _handshake(sock):
    sock.sendall(
        b"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
        b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        b"Sec-WebSocket-Version: 13\r\n\r\n")
    resp = b""
    sock.settimeout(3.0)
    while b"\r\n\r\n" not in resp:
        chunk = sock.recv(1024)
        if not chunk:
            break
        resp += chunk
    return resp


def _send_text(sock, text):
    """Send a masked client text frame (RFC6455 requires client frames masked)."""
    payload = text.encode("utf-8")
    mask = b"\x01\x02\x03\x04"
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    n = len(payload)
    hdr = (bytes([0x81, 0x80 | n]) if n < 126
           else bytes([0x81, 0x80 | 126]) + n.to_bytes(2, "big"))
    sock.sendall(hdr + mask + masked)


def _recvn(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise AssertionError("socket closed mid-frame")
        buf += chunk
    return buf


def _recv_text(sock, timeout):
    """Read one server text frame (unmasked), handling extended lengths."""
    sock.settimeout(timeout)
    hdr = _recvn(sock, 2)
    length = hdr[1] & 0x7F
    if length == 126:
        length = int.from_bytes(_recvn(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(_recvn(sock, 8), "big")
    return _recvn(sock, length).decode("utf-8")


def test_ws_streams_new_decisions_and_stays_quiet_when_idle(tmp_path):
    from http.server import ThreadingHTTPServer

    dbfile = str(tmp_path / "ws.db")
    cfg = {"type": "sqlite", "path": dbfile}
    seed = Storage(dbfile, commit_every=1)
    seed.begin_run("sha", "v/1")
    seed.record_decision(tick=1, world="vale", char_uid="c1", chosen={"action": "a"},
                         alternatives=[], reasoning="seed", strategy_version="v/1")
    seed.close()
    top = _db.connect(cfg, readonly=True).execute(
        "SELECT MAX(seq) FROM decisions").fetchone()[0]

    srv.Handler.db_config = cfg
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    stop = threading.Event()
    threading.Thread(target=srv._push_loop, args=(cfg, stop, 0.1), daemon=True).start()

    sock = socket.create_connection(("127.0.0.1", port))
    try:
        assert b" 101 " in _handshake(sock)
        # Subscribe to the decisions feed at the current high-water cursor, so
        # only decisions written AFTER now are streamed.
        _send_text(sock, json.dumps(
            {"t": "sub", "tab": "decisions", "params": {}, "cursor": {"seq": top}}))
        time.sleep(0.3)                          # let the sub register

        # Oracle A (absence): no write -> no push in a generous window.
        assert len(srv._ws_clients) >= 1         # precondition: we are subscribed
        idle = None
        try:
            idle = _recv_text(sock, 0.6)
        except socket.timeout:
            idle = None
        assert idle is None, f"unexpected push while idle: {idle!r}"

        # Oracle B (presence): a new decision -> a data push carrying that row.
        writer = Storage(dbfile, commit_every=1)
        writer.begin_run("sha", "v/1")
        writer.record_decision(tick=2, world="vale", char_uid="c1",
                               chosen={"action": "move"}, alternatives=[],
                               reasoning="fresh-after-subscribe", strategy_version="v/1")
        writer.close()
        msg = json.loads(_recv_text(sock, 3.0))
        assert msg["t"] == "decisions"
        assert msg["rows"][0]["reasoning"] == "fresh-after-subscribe"
        assert msg["rows"][0]["seq"] > top
        assert msg["cursor"]["seq"] == msg["rows"][0]["seq"]
    finally:
        sock.close()
        stop.set()
        httpd.shutdown()
        httpd.server_close()
        with srv._ws_lock:
            srv._ws_clients.clear()
