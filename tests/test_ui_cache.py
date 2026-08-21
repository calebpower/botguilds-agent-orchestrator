"""The KPI snapshot is computed off the HTTP request path.

A background worker (:func:`ui.server._snapshot_worker`) computes the heavy
multi-GB aggregate and publishes it; the ``/api/snapshot`` request thread only
ever *reads* that cache. It must never trigger an inline compute — that
request-thread hang (which, via the browser's ~6-connections-per-host cap,
starved every other tab) is exactly the bug this design replaced.
"""

import sqlite3

import ui.server as srv


def _reset_snapshot_state():
    with srv._snap_lock:
        srv._snap_state.update(snap=None, computed_at=0.0, error=None)


def test_api_snapshot_never_computes_on_request_thread(monkeypatch):
    """Cold cache degrades to ``reason:"computing"`` and does NOT call
    ``metrics.snapshot`` — the request thread must never own that cost."""
    _reset_snapshot_state()
    calls = {"n": 0}

    def must_not_run(db):
        calls["n"] += 1
        raise AssertionError("snapshot must not be computed on the request thread")

    monkeypatch.setattr(srv.metrics, "snapshot", must_not_run)
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: True)

    out = srv.api_snapshot("db1")
    assert out == {"ok": False, "reason": "computing"}
    assert calls["n"] == 0


def test_publish_then_read_serves_the_cached_copy(monkeypatch):
    """The background worker computes once; repeated reads serve that one copy
    without recomputing (this is what keeps request threads cheap)."""
    _reset_snapshot_state()
    calls = {"n": 0}

    def fake(db):
        calls["n"] += 1
        return {"volume": {"frames": calls["n"]}}

    monkeypatch.setattr(srv.metrics, "snapshot", fake)
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: True)

    srv._publish_snapshot("db1")             # the background worker's job
    a = srv.api_snapshot("db1")              # request thread: read-only
    b = srv.api_snapshot("db1")              # request thread: read-only
    assert calls["n"] == 1                   # computed once, served twice
    assert a["ok"] is True and a["volume"]["frames"] == 1
    assert b["ok"] is True and b["volume"]["frames"] == 1


def test_publish_refreshes_when_the_worker_recomputes(monkeypatch):
    """A later background compute replaces the published snapshot in place."""
    _reset_snapshot_state()
    seq = iter([{"volume": {"frames": 10}}, {"volume": {"frames": 20}}])
    monkeypatch.setattr(srv.metrics, "snapshot", lambda db: next(seq))
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: True)

    srv._publish_snapshot("db1")
    assert srv.api_snapshot("db1")["volume"]["frames"] == 10
    srv._publish_snapshot("db1")             # worker's next cycle
    assert srv.api_snapshot("db1")["volume"]["frames"] == 20


def test_publish_error_surfaces_as_reason_not_raised(monkeypatch):
    """A DB error during a background compute is captured, not raised, and shows
    up as the endpoint's ``reason`` so the page can degrade rather than crash."""
    _reset_snapshot_state()
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: True)

    def fail(db):
        raise sqlite3.OperationalError("boom")   # a member of srv._db.Error

    monkeypatch.setattr(srv.metrics, "snapshot", fail)

    srv._publish_snapshot("db1")                 # must not propagate
    out = srv.api_snapshot("db1")
    assert out["ok"] is False and out["reason"] == "boom"


# --- the worlds/chars filter-list cache ------------------------------------- #
# These lists come from DISTINCT scans over large tables; a short TTL stops a
# tab-switch / reconnect storm from re-running them.

def test_cached_list_coalesces_within_ttl():
    srv._list_cache.clear()
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return ["vale"]

    a = srv._cached_list("k", fn)
    b = srv._cached_list("k", fn)             # within TTL -> served from cache
    assert a == b == ["vale"]
    assert calls["n"] == 1


def test_cached_list_recomputes_after_ttl(monkeypatch):
    srv._list_cache.clear()
    monkeypatch.setattr(srv, "_LIST_TTL", 0.0)   # force immediate expiry
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        return [str(calls["n"])]

    srv._cached_list("k", fn)
    srv._cached_list("k", fn)
    assert calls["n"] == 2                    # TTL 0 -> always recompute


# --- the background worker's change-detection guard ------------------------- #
# The snapshot is minutes of DB load; the worker must NOT re-aggregate a static
# DB every cycle. _snapshot_step recomputes only when the data signature moves.

def test_snapshot_step_recomputes_on_first_pass_then_skips_when_static(monkeypatch):
    _reset_snapshot_state()
    monkeypatch.setattr(srv, "_data_signature", lambda cfg: (100, 200))
    computes = {"n": 0}

    def fake(db):
        computes["n"] += 1
        return {"volume": {"frames": computes["n"]}}

    monkeypatch.setattr(srv.metrics, "snapshot", fake)

    sig = object()                            # sentinel "never computed"
    sig = srv._snapshot_step("db1", sig)      # first pass -> computes + publishes
    assert computes["n"] == 1
    sig = srv._snapshot_step("db1", sig)      # data unchanged -> skip
    sig = srv._snapshot_step("db1", sig)      # still unchanged -> skip
    assert computes["n"] == 1                 # guard held: no needless recompute


def test_snapshot_step_recomputes_when_data_advances(monkeypatch):
    _reset_snapshot_state()
    sigs = iter([(100, 200), (100, 201)])     # decisions seq advanced
    monkeypatch.setattr(srv, "_data_signature", lambda cfg: next(sigs))
    computes = {"n": 0}
    monkeypatch.setattr(srv.metrics, "snapshot",
                        lambda db: computes.__setitem__("n", computes["n"] + 1) or {"v": 1})

    carry = srv._snapshot_step("db1", (100, 200))   # equals first sig -> but nothing published yet
    assert computes["n"] == 1                        # published==None forces the first compute
    srv._snapshot_step("db1", carry)                 # sig now (100,201) != carry -> recompute
    assert computes["n"] == 2


# ---- the exploration matrix endpoint -----------------------------------------

def _reset_matrix_cache():
    srv._matrix_cache.update(run=None, data=None)


def test_the_matrix_renders_with_NO_DATABASE_at_all(monkeypatch):
    """A fresh checkout has no history, and that must show the cube rather than an error.

    The vocabulary fixture is committed, so nouns, verbs and priors are all computable
    without a database; only the TESTED layer needs one, and with no history everything is
    untried — which is exactly right. Returning "no database" hid the most useful view
    precisely when there was nothing else to look at, and the Playwright test caught it.
    """
    _reset_matrix_cache()
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    d = srv.api_matrix("db-that-does-not-exist")
    assert d["ok"] is True
    assert len(d["verbs_never"]) > 0 and d["cells_total"] > 0
    assert d["grid"]["counts"]["tried"] == 0        # nothing has been tried yet
    assert d["frontier_size"] > 0


def test_the_matrix_is_cached_per_run(monkeypatch):
    """It costs ~2-3s against the live DB (a DISTINCT plus a bounded scan). The request
    thread must never own that cost twice — the same rule api_snapshot exists for."""
    _reset_matrix_cache()
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    monkeypatch.setattr(srv, "_codex_latest_run", lambda cfg: 42)
    first = srv.api_matrix("db")
    second = srv.api_matrix("db")
    assert second is first, "a second call rebuilt the report instead of serving the cache"


def test_a_NEW_RUN_invalidates_the_matrix_cache(monkeypatch):
    """The other side: the frontier shrinks as we try things, so a stale cache would keep
    showing cells we have since explored."""
    _reset_matrix_cache()
    monkeypatch.setattr(srv, "_db_ready", lambda cfg: False)
    monkeypatch.setattr(srv, "_codex_latest_run", lambda cfg: 1)
    first = srv.api_matrix("db")
    monkeypatch.setattr(srv, "_codex_latest_run", lambda cfg: 2)
    second = srv.api_matrix("db")
    assert second is not first, "a new run served the previous run's frontier"
