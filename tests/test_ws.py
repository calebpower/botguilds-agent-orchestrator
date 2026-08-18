"""The dashboard's hand-rolled WebSocket push: handshake correctness, framing,
and the watcher's push-only-on-change behaviour asserted from BOTH sides (a
change DOES notify; an idle window does NOT).

The framing/handshake tests are pure and always run. The end-to-end test spins a
real server + watcher on an ephemeral port over a temp SQLite DB — no MariaDB
needed — and drives an actual socket through the RFC6455 handshake."""

import socket
import threading
import time

import ui.server as srv
from steemer.storage import Storage


# --- handshake + framing (pure, known-answer) ------------------------------- #

def test_accept_key_matches_rfc6455_example():
    # The canonical example from RFC6455 section 1.3.
    assert srv._ws_accept_key("dGhlIHNhbXBsZSBub25jZQ==") == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


def test_encode_small_text_frame():
    f = srv._ws_encode(b"hi")
    assert f == bytes([0x81, 0x02]) + b"hi"     # FIN|text, len 2, payload


def test_read_frame_unmasks_client_data():
    # Build a masked client frame carrying "ok" and confirm we unmask it.
    import io
    mask = bytes([0x01, 0x02, 0x03, 0x04])
    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(b"ok"))
    raw = bytes([0x81, 0x80 | 0x02]) + mask + payload
    opcode, data = srv._ws_read_frame(io.BytesIO(raw))
    assert opcode == 0x1 and data == b"ok"


# --- end-to-end: push only on change ---------------------------------------- #

def _frame(tick):
    return {"tick": tick, "world": "vale", "visible": {"tiles": []}, "events": []}


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


def _recv_text(sock, timeout):
    """Read one server text frame (unmasked); raises socket.timeout if none."""
    sock.settimeout(timeout)
    hdr = sock.recv(2)
    if len(hdr) < 2:
        raise AssertionError("socket closed")
    length = hdr[1] & 0x7F                     # server frames are small + unmasked
    data = b""
    while len(data) < length:
        data += sock.recv(length - len(data))
    return data.decode("utf-8")


def test_ws_pushes_on_change_and_stays_quiet_when_idle(tmp_path):
    from http.server import ThreadingHTTPServer

    dbfile = str(tmp_path / "ws.db")
    seed = Storage(dbfile, commit_every=1)
    seed.record_frame(_frame(1))
    seed.close()
    cfg = {"type": "sqlite", "path": dbfile}

    srv.Handler.db_config = cfg
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    stop = threading.Event()
    # Start the watcher and let it establish its baseline (last=current) with no
    # clients connected yet, so a fresh client gets no spurious initial push.
    threading.Thread(target=srv._watch_and_push, args=(cfg, stop, 0.1),
                     daemon=True).start()
    time.sleep(0.4)

    sock = socket.create_connection(("127.0.0.1", port))
    try:
        resp = _handshake(sock)
        assert b" 101 " in resp
        assert b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=" in resp

        # Drain any push that raced the baseline, so the idle window is clean.
        try:
            _recv_text(sock, 0.3)
        except socket.timeout:
            pass

        # Oracle A (absence): no DB change -> no push within a generous window.
        # Assert the precondition first: we are a registered client.
        assert len(srv._ws_clients) >= 1
        got_idle = None
        try:
            got_idle = _recv_text(sock, 0.7)
        except socket.timeout:
            got_idle = None
        assert got_idle is None, f"unexpected push while idle: {got_idle!r}"

        # Oracle B (presence): a new frame advances MAX(seq) -> a "changed" push.
        writer = Storage(dbfile, commit_every=1)
        writer.record_frame(_frame(2))
        writer.close()
        msg = _recv_text(sock, 3.0)
        assert '"type": "changed"' in msg or '"type":"changed"' in msg
    finally:
        sock.close()
        stop.set()
        httpd.shutdown()
        httpd.server_close()
        with srv._ws_lock:
            srv._ws_clients.clear()
