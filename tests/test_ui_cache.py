"""The /api/snapshot TTL cache: ~1s polling must coalesce onto one recompute."""

import ui.server as srv


def test_snapshot_cached_coalesces_within_ttl(monkeypatch):
    calls = {"n": 0}

    def fake(db):
        calls["n"] += 1
        return {"v": calls["n"]}

    monkeypatch.setattr(srv.metrics, "snapshot", fake)
    srv._snap_cache.clear()
    a = srv._snapshot_cached("db1")
    b = srv._snapshot_cached("db1")          # within TTL -> cached, no recompute
    assert a is b
    assert calls["n"] == 1


def test_snapshot_cache_recomputes_after_ttl(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(srv.metrics, "snapshot", lambda db: {"v": calls.__setitem__("n", calls["n"] + 1) or calls["n"]})
    monkeypatch.setattr(srv, "_SNAP_TTL", 0.0)   # force expiry
    srv._snap_cache.clear()
    srv._snapshot_cached("db1")
    srv._snapshot_cached("db1")
    assert calls["n"] == 2                    # TTL 0 -> always recompute
