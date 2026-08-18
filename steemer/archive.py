"""Archival retention for the raw ``frames`` table.

``frames`` (one zlib-compressed world snapshot per tick, ~14 KB × 4/s) is the
only table that grows without bound — ~7 GiB/day — so on a walk-away box it
would fill the disk in days. The operator's policy is **archive, don't delete**:
ship old frames off-box to durable storage, then reclaim the local space. The
mined signal (events / decisions / actions / metrics / findings) is cheap and
stays local for the UI and analysis.

Safety invariant (two oracles before any local delete):
  a frame is pruned **only** after its archive is (1) reported shipped by the
  transport AND (2) independently re-observed on the remote with a matching
  size/checksum. Either check failing leaves the DB full but intact — the bot
  keeps playing; we alert instead of losing data.

This module is pure and connection-based (no live-DB or network coupling) so it
can be exercised end-to-end in tests. The transport ("shipper") and the
scheduling live outside it; ``record_archive`` / ``mark_verified`` /
``prune_run_frames`` are the ordered handshake the orchestrator drives.

Archive format: gzip-compressed JSONL. Line 1 is a header object
(``{"_schema": 1, "run_id": ..., ...}``); each remaining line is one frame,
``{"seq","tick","world","received_at","run_id","z"}`` where ``z`` is base64 of
the exact stored zlib blob — so a restore reconstructs the original rows byte
for byte.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
from typing import Any, Iterator

from . import db as _db

SCHEMA = 1


def ensure_manifest(conn: _db.Connection) -> None:
    """Create the archives manifest table if absent (SQLite or MariaDB)."""
    _db.apply_manifest(conn)


def archivable_runs(conn: _db.Connection, before_ts: float) -> list[dict[str, Any]]:
    """Closed runs whose frames are all older than ``before_ts`` and are not yet
    archived. Never returns the open run (stopped_at NULL) or a run with no
    frames, so recent/live history is always left intact locally."""
    ensure_manifest(conn)
    rows = conn.execute(
        """
        SELECT r.run_id, r.started_at, r.stopped_at,
               COUNT(f.seq) AS n, MIN(f.received_at) AS lo, MAX(f.received_at) AS hi
        FROM runs r
        JOIN frames f ON f.run_id = r.run_id
        WHERE r.stopped_at IS NOT NULL
          AND r.run_id NOT IN (SELECT run_id FROM archives WHERE pruned = 1)
        GROUP BY r.run_id
        HAVING hi < ?
        ORDER BY r.run_id
        """,
        (before_ts,),
    ).fetchall()
    return [dict(run_id=r[0], started_at=r[1], stopped_at=r[2],
                 rows=r[3], lo=r[4], hi=r[5]) for r in rows]


def export_run(conn: _db.Connection, run_id: int, out_path: str) -> dict[str, Any]:
    """Write every frame of ``run_id`` to a gzip-JSONL archive at ``out_path``.
    Returns ``{rows, bytes, sha256}``. Streams row-by-row so a huge run does not
    have to fit in memory."""
    meta = conn.execute(
        "SELECT git_sha, strategy_version, started_at, stopped_at, note "
        "FROM runs WHERE run_id=?", (run_id,)).fetchone()
    header = {"_schema": SCHEMA, "run_id": run_id,
              "git_sha": meta[0] if meta else None,
              "strategy_version": meta[1] if meta else None,
              "started_at": meta[2] if meta else None,
              "stopped_at": meta[3] if meta else None,
              "note": meta[4] if meta else None}
    rows = 0
    cur = conn.execute(
        "SELECT seq, tick, world, received_at, run_id, json FROM frames "
        "WHERE run_id=? ORDER BY seq", (run_id,))
    with gzip.open(out_path, "wt", encoding="utf-8") as gz:
        gz.write(json.dumps(header) + "\n")
        for seq, tick, world, received_at, rid, blob in cur:
            gz.write(json.dumps({
                "seq": seq, "tick": tick, "world": world,
                "received_at": received_at, "run_id": rid,
                "z": base64.b64encode(blob).decode("ascii")}) + "\n")
            rows += 1
    h = hashlib.sha256()
    nbytes = 0
    with open(out_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
            nbytes += len(chunk)
    return {"rows": rows, "bytes": nbytes, "sha256": h.hexdigest()}


def read_archive(path: str) -> Iterator[dict[str, Any]]:
    """Yield frame rows from an archive as dicts with the raw zlib blob restored
    to ``blob`` (bytes). The header line is skipped. This is the restore/verify
    oracle: it must reconstruct exactly what ``export_run`` was given."""
    with gzip.open(path, "rt", encoding="utf-8") as gz:
        first = True
        for line in gz:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if first:
                first = False
                if obj.get("_schema") is not None:
                    continue        # header
            yield {"seq": obj["seq"], "tick": obj["tick"], "world": obj["world"],
                   "received_at": obj["received_at"], "run_id": obj["run_id"],
                   "blob": base64.b64decode(obj["z"])}


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record_archive(conn: _db.Connection, run_id: int, path: str, sha256: str,
                   rows: int, nbytes: int, run_started: float | None,
                   run_stopped: float | None, archived_at: float,
                   remote_uri: str | None = None) -> None:
    """Record an exported (not yet verified) archive in the manifest."""
    ensure_manifest(conn)
    conn.execute(
        _db.archive_upsert(conn.dialect),
        (run_id, path, remote_uri, sha256, rows, nbytes,
         run_started, run_stopped, archived_at))
    conn.commit()


def mark_shipped(conn: _db.Connection, run_id: int, remote_uri: str) -> None:
    conn.execute("UPDATE archives SET remote_uri=? WHERE run_id=?",
                 (remote_uri, run_id))
    conn.commit()


def mark_verified(conn: _db.Connection, run_id: int) -> None:
    """Set verified=1. Caller must have confirmed BOTH oracles (shipped + remote
    re-observed with matching size/sha) before calling this."""
    conn.execute("UPDATE archives SET verified=1 WHERE run_id=?", (run_id,))
    conn.commit()


def prune_run_frames(conn: _db.Connection, run_id: int) -> int:
    """Delete a run's frames — ONLY if its archive is verified. Refuses (raises)
    otherwise: the whole point is that we never drop un-shipped data. Returns
    rows deleted. events/decisions/actions for the run are intentionally kept."""
    row = conn.execute(
        "SELECT verified FROM archives WHERE run_id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError(f"run {run_id} has no archive manifest row — refusing to prune")
    if not row[0]:
        raise ValueError(f"run {run_id} archive not verified — refusing to prune")
    cur = conn.execute("DELETE FROM frames WHERE run_id=?", (run_id,))
    conn.execute("UPDATE archives SET pruned=1 WHERE run_id=?", (run_id,))
    conn.commit()
    return cur.rowcount


def checkpoint(conn: _db.Connection) -> None:
    """Fold the WAL back into the main DB and truncate it (SQLite). Pages freed by
    a prune become free-list pages the live writer reuses, so the file stops
    *growing* even though it does not shrink — what bounds disk on a walk-away box.

    Deliberately does NOT VACUUM (that needs an exclusive lock). No-op on MariaDB,
    where InnoDB manages its own storage — see :func:`steemer.db.checkpoint`."""
    _db.checkpoint(conn)


def reclaim_space(conn: _db.Connection) -> None:
    """VACUUM the DB to physically shrink the file after large prunes (SQLite;
    requires an exclusive lock, so run it only in a maintenance window). No-op on
    MariaDB — see :func:`steemer.db.reclaim_space`."""
    _db.reclaim_space(conn)
