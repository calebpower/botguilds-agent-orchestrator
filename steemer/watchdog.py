"""Liveness watchdog — is data still flowing? (wishlist item "always-on watchdog").

The improvement loop's blind spot has always been *silence*: a bot that has crash-looped
(the zlib bug left runs #39-51 empty), been kicked into a single-session war, or simply
gone down (a stopped `svc.sh bot`) writes NO frames — and every KPI/post-mortem tool here
reads *completed* runs, so none of them notice the pipeline is dead. This is the detection
half of that alarm: it asks one cheap question — *how long since the last frame landed?* —
and classifies the answer. Read-only; it never touches the bot. (The external push half is
intentionally out of scope; a cron can act on the exit code / JSON.)

Two layers, split so the judgement is unit-testable without a clock or a database:

* :func:`classify_liveness` — PURE: given ``now`` and the latest frame's ``received_at``,
  return a status/level. ``now`` is a parameter (not read from the wall clock) so the
  oracle is deterministic and replayable.
* :func:`check_db` — read the newest frame's ``received_at`` via the indexed ``seq`` (an
  instant PK lookup, not a full-table ``MAX``) and classify it.

This is the DATA-plane oracle (are frames being written?). It deliberately does NOT prove
the host process is healthy — a complementary process-plane check (``pgrep run-live``) is
the other side of that claim and belongs to the host, not this DB tool.
"""
from __future__ import annotations

import time
from typing import Any

# No frame for this many seconds => stale (a healthy bot writes many frames/second).
DEFAULT_STALE_S = 120.0
# No frame for this many seconds => almost certainly dead/crash-looped, not a hiccup.
DEFAULT_DEAD_S = 600.0


def classify_liveness(now: float, latest_received_at: float | None,
                      stale_s: float = DEFAULT_STALE_S,
                      dead_s: float = DEFAULT_DEAD_S) -> dict[str, Any]:
    """Classify pipeline liveness from the age of the newest frame. PURE — ``now`` is
    passed in, never read from the clock, so this replays deterministically.

    Returns ``{ok, level, status, age_s, stale_s, dead_s}`` where ``level`` is
    ``ok``/``warn``/``critical`` and ``status`` is ``alive``/``stale``/``dead``/``no_data``.
    ``ok`` is the boolean an alerting cron branches on (True only when level==ok).
    """
    if latest_received_at is None:
        return {"ok": False, "level": "critical", "status": "no_data",
                "age_s": None, "stale_s": stale_s, "dead_s": dead_s}
    age = now - latest_received_at
    if age >= dead_s:
        level, status = "critical", "dead"
    elif age >= stale_s:
        level, status = "warn", "stale"
    else:
        level, status = "ok", "alive"
    return {"ok": level == "ok", "level": level, "status": status,
            "age_s": round(age, 1), "stale_s": stale_s, "dead_s": dead_s}


def latest_received_at(conn: Any) -> float | None:
    """The newest frame's wall-clock ``received_at`` via the ``seq`` PK (instant lookup)."""
    row = conn.execute(
        "SELECT received_at FROM frames ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    # row may be a mapping or a tuple depending on the DB layer
    return row["received_at"] if hasattr(row, "keys") else row[0]


def check_db(conn: Any, now: float | None = None,
             stale_s: float = DEFAULT_STALE_S,
             dead_s: float = DEFAULT_DEAD_S) -> dict[str, Any]:
    """Read the newest frame's age from ``conn`` and classify it. ``now`` defaults to the
    wall clock; pass it explicitly in tests for determinism."""
    now = time.time() if now is None else now
    return classify_liveness(now, latest_received_at(conn), stale_s, dead_s)


if __name__ == "__main__":       # pragma: no cover - thin CLI wrapper
    import argparse
    import json as _json
    import sys
    from steemer import db
    ap = argparse.ArgumentParser(description="Frame-liveness watchdog (read-only)")
    ap.add_argument("--stale-seconds", type=float, default=DEFAULT_STALE_S)
    ap.add_argument("--dead-seconds", type=float, default=DEFAULT_DEAD_S)
    args = ap.parse_args()
    conn = db.connect(db.load_db_config())
    report = check_db(conn, stale_s=args.stale_seconds, dead_s=args.dead_seconds)
    print(_json.dumps(report))
    # exit non-zero on trouble so a cron/`||` can alert without parsing JSON
    sys.exit(0 if report["ok"] else (1 if report["level"] == "warn" else 2))
