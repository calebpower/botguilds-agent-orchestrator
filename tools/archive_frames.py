# /// script
# requires-python = ">=3.12"
# ///
"""Retention pass: archive aged-out runs' frames off-box, then reclaim locally.

For every CLOSED run whose newest frame is older than the hot window
(default 48h), this exports the run's frames to a gzip-JSONL archive, ships it to
the NAS, independently re-verifies the shipped copy (size + sha256), and only
THEN deletes the local frames and checkpoints the WAL. If verification fails for
a run, that run is left fully intact locally and flagged — nothing is lost.

Runnable without Claude (this is what the cron calls):

    uv run tools/archive_frames.py                      # real pass, 48h window
    uv run tools/archive_frames.py --dry-run            # show what it WOULD do
    uv run tools/archive_frames.py --hot-hours 24       # tighter window

The mount at /mnt/nas is provided by the smbnetfs rc.d service; if it is not
mounted, this refuses to run rather than pile archives onto the local disk.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from steemer import archive, shippers  # noqa: E402
from steemer import db as _db  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(REPO, "guild_log.db")
DEFAULT_STAGE = os.path.join(REPO, "archive")
DEFAULT_DEST = "/mnt/nas/truenas.chack.internal/samba_share/steemer-archives"


def _log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _mounted(path: str, mount_root: str = "/mnt/nas") -> bool:
    """True if `mount_root` is a live mount (not the bare local dir we'd get if
    smbnetfs is down). os.path.ismount is unreliable for FUSE, so compare device
    IDs: a mounted fs gives mount_root a different st_dev than its parent; an
    unmounted local dir shares its parent's device. Guards against silently
    staging archives on the local disk when the NAS is down."""
    try:
        return os.stat(mount_root).st_dev != os.stat(os.path.dirname(mount_root)).st_dev
    except OSError:
        return False


def _archive_name(conn: _db.Connection, run_id: int) -> str:
    row = conn.execute(
        "SELECT git_sha, strategy_version FROM runs WHERE run_id=?", (run_id,)).fetchone()
    sha = (row[0] or "nosha")[:10] if row else "nosha"
    strat = (row[1] or "nostrat").replace("/", "_") if row else "nostrat"
    return f"run{run_id:04d}_{sha}_{strat}.frames.jsonl.gz"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None,
                    help="SQLite path override; else use --config/config.toml")
    ap.add_argument("--config", default=None, help="path to config.toml")
    ap.add_argument("--dest", default=DEFAULT_DEST, help="NAS archive directory")
    ap.add_argument("--stage", default=DEFAULT_STAGE, help="local staging dir")
    ap.add_argument("--hot-hours", type=float, default=48.0,
                    help="keep full frames younger than this locally")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    if not args.dry_run and not _mounted(args.dest):
        _log(f"ABORT: {args.dest} is not on a live mount (/mnt/nas). "
             "Is the smbnetfs service up? Refusing to stage archives on local disk.")
        return 2

    os.makedirs(args.stage, exist_ok=True)
    # --db (a SQLite path) overrides config; otherwise resolve the backend from
    # --config/config.toml (default DEFAULT_DB when no config exists).
    db_cfg = {"type": "sqlite", "path": args.db} if args.db \
        else _db.load_db_config(args.config)
    conn = _db.connect(db_cfg)

    before_ts = time.time() - args.hot_hours * 3600.0
    runs = archive.archivable_runs(conn, before_ts)
    if not runs:
        _log(f"nothing to archive (no closed run older than {args.hot_hours}h)")
        archive.checkpoint(conn)
        return 0

    _log(f"{len(runs)} run(s) eligible (older than {args.hot_hours}h): "
         + ", ".join(str(r["run_id"]) for r in runs))
    if args.dry_run:
        for r in runs:
            _log(f"  DRY run {r['run_id']}: {r['rows']} frames "
                 f"-> {_archive_name(conn, r['run_id'])}")
        return 0

    shipper = shippers.LocalDirShipper(args.dest)
    archived = failed = 0
    for r in runs:
        rid = r["run_id"]
        name = _archive_name(conn, rid)
        stage_path = os.path.join(args.stage, name)
        try:
            res = archive.export_run(conn, rid, stage_path)
            archive.record_archive(conn, rid, stage_path, res["sha256"], res["rows"],
                                   res["bytes"], r["started_at"], r["stopped_at"],
                                   archived_at=time.time())
            uri = shipper.put(stage_path, name)
            archive.mark_shipped(conn, rid, uri)
            ok, why = shippers.verify(shipper, uri, res["bytes"], res["sha256"])
            if not ok:
                failed += 1
                _log(f"  run {rid}: VERIFY FAILED ({why}) — NOT pruning, kept intact")
                continue
            archive.mark_verified(conn, rid)
            deleted = archive.prune_run_frames(conn, rid)
            os.remove(stage_path)          # staging copy no longer needed
            archived += 1
            _log(f"  run {rid}: {res['rows']} frames -> {uri} ({why}); "
                 f"pruned {deleted} local rows")
        except Exception as e:                      # noqa: BLE001 - report, don't crash the box
            failed += 1
            _log(f"  run {rid}: ERROR {e!r} — left intact")

    archive.checkpoint(conn)
    _log(f"done: {archived} archived, {failed} failed/skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
