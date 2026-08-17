"""Archival retention: exact roundtrip, verify-before-prune safety, oracle self-test.

The whole point of "archive, don't delete" is that no frame is ever lost. These
tests hold that line: the archive reconstructs frames byte-for-byte, pruning
refuses without a verified shipment, and the verify oracle fails closed when the
remote copy is wrong (mutation testing pointed at the oracle itself).
"""

import gzip
import json

import pytest

from steemer import archive, shippers
from steemer.storage import Storage


def _db(tmp_path):
    return Storage(str(tmp_path / "t.db"), commit_every=1)


def _make_run(s, version, ticks, world="vale"):
    rid = s.begin_run("sha_" + version, version)
    for t in ticks:
        s.record_frame({"tick": t, "world": world, "events": []})
    s.end_run()
    return rid


def _set_received(s, run_id, ts):
    s.conn.execute("UPDATE frames SET received_at=? WHERE run_id=?", (ts, run_id))
    s.conn.commit()


def _frames_in_db(s, run_id):
    return s.conn.execute(
        "SELECT seq, tick, world, received_at, run_id, json FROM frames "
        "WHERE run_id=? ORDER BY seq", (run_id,)).fetchall()


def test_export_roundtrips_frames_exactly(tmp_path):
    s = _db(tmp_path)
    rid = _make_run(s, "explorer/0.1.0", [1, 2, 3])
    out = str(tmp_path / "run.jsonl.gz")
    res = archive.export_run(s.conn, rid, out)
    assert res["rows"] == 3
    db_rows = _frames_in_db(s, rid)
    arch = list(archive.read_archive(out))
    assert len(arch) == 3
    for (seq, tick, world, recv, r, blob), a in zip(db_rows, arch):
        assert (a["seq"], a["tick"], a["world"], a["received_at"], a["run_id"]) == \
               (seq, tick, world, recv, r)
        assert a["blob"] == blob                # exact zlib bytes -> restorable
    s.close()


def test_export_sha256_matches_file(tmp_path):
    s = _db(tmp_path)
    rid = _make_run(s, "explorer/0.1.0", [1, 2])
    out = str(tmp_path / "run.jsonl.gz")
    res = archive.export_run(s.conn, rid, out)
    assert res["sha256"] == archive.sha256_file(out)
    s.close()


def test_archivable_excludes_open_and_too_recent(tmp_path):
    s = _db(tmp_path)
    old = _make_run(s, "explorer/0.1.0", [1, 2]); _set_received(s, old, 1000.0)
    recent = _make_run(s, "explorer/0.2.0", [3, 4]); _set_received(s, recent, 9000.0)
    open_run = s.begin_run("sha_open", "explorer/0.3.0")   # left open on purpose
    s.record_frame({"tick": 5, "world": "vale", "events": []})
    _set_received(s, open_run, 500.0)                      # old, but still OPEN
    got = {r["run_id"] for r in archive.archivable_runs(s.conn, before_ts=5000.0)}
    assert got == {old}          # not the recent one, not the open one
    s.close()


def test_prune_refuses_without_manifest_or_verification(tmp_path):
    s = _db(tmp_path)
    rid = _make_run(s, "explorer/0.1.0", [1, 2])
    archive.ensure_manifest(s.conn)
    with pytest.raises(ValueError):                 # no manifest row at all
        archive.prune_run_frames(s.conn, rid)
    assert len(_frames_in_db(s, rid)) == 2          # nothing deleted
    out = str(tmp_path / "run.jsonl.gz")
    res = archive.export_run(s.conn, rid, out)
    archive.record_archive(s.conn, rid, out, res["sha256"], res["rows"],
                           res["bytes"], 0.0, 1.0, archived_at=2.0)
    with pytest.raises(ValueError):                 # recorded but not verified
        archive.prune_run_frames(s.conn, rid)
    assert len(_frames_in_db(s, rid)) == 2          # still nothing deleted
    s.close()


def test_full_handshake_ships_verifies_prunes_only_target(tmp_path):
    s = _db(tmp_path)
    keep = _make_run(s, "explorer/0.1.0", [1, 2, 3])      # must survive
    old = _make_run(s, "explorer/0.2.0", [4, 5]); _set_received(s, old, 1000.0)
    out = str(tmp_path / "old.jsonl.gz")
    res = archive.export_run(s.conn, old, out)
    archive.record_archive(s.conn, old, out, res["sha256"], res["rows"],
                           res["bytes"], 0.0, 1.0, archived_at=2.0)
    shipper = shippers.LocalDirShipper(str(tmp_path / "remote"))
    uri = shipper.put(out, "old.jsonl.gz")
    archive.mark_shipped(s.conn, old, uri)
    ok, why = shippers.verify(shipper, uri, res["bytes"], res["sha256"])
    assert ok, why
    archive.mark_verified(s.conn, old)
    deleted = archive.prune_run_frames(s.conn, old)
    assert deleted == 2
    assert _frames_in_db(s, old) == []                    # target gone locally
    assert len(_frames_in_db(s, keep)) == 3               # the other run untouched
    # durability: the shipped archive still reconstructs the pruned frames.
    assert len(list(archive.read_archive(uri[len("file://"):]))) == 2
    s.close()


def test_verify_fails_closed_on_corrupt_remote(tmp_path):
    # Self-test the oracle: a truncated/altered remote copy must NOT verify, so a
    # prune driven off it must be refused. This is the check that makes the whole
    # "never delete un-shipped data" guarantee mean something.
    s = _db(tmp_path)
    rid = _make_run(s, "explorer/0.1.0", [1, 2])
    out = str(tmp_path / "run.jsonl.gz")
    res = archive.export_run(s.conn, rid, out)
    shipper = shippers.LocalDirShipper(str(tmp_path / "remote"))
    uri = shipper.put(out, "run.jsonl.gz")
    # corrupt the remote after upload
    dest = uri[len("file://"):]
    with open(dest, "ab") as fh:
        fh.write(b"tampered")
    ok, why = shippers.verify(shipper, uri, res["bytes"], res["sha256"])
    assert not ok and "size mismatch" in why
    s.close()


def test_verify_fails_when_remote_missing(tmp_path):
    s = _db(tmp_path)
    shipper = shippers.LocalDirShipper(str(tmp_path / "remote"))
    ok, why = shippers.verify(shipper, "file://" + str(tmp_path / "nope.gz"),
                              123, "deadbeef")
    assert not ok and "not found" in why
    s.close()
