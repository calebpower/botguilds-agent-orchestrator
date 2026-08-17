"""Transports that put an archive file off-box, plus the two-oracle verify.

A ``Shipper`` is deliberately tiny: ``put`` uploads a local file under a key and
returns a remote URI; ``stat`` independently re-observes that URI (size, and a
checksum when the remote can report one). ``verify`` is the safety gate the
archival orchestrator calls before it is allowed to delete anything locally —
it fails closed.

Only ``LocalDirShipper`` (copy to a directory — e.g. a mounted NAS, or a test
tmpdir) ships here. The concrete off-box transport (S3-compatible object store,
or rsync/scp over SSH) is added once the operator provides credentials; it just
implements the same two methods.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from typing import Any, Protocol


class Shipper(Protocol):
    def put(self, local_path: str, key: str) -> str: ...
    def stat(self, remote_uri: str) -> dict[str, Any]: ...


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class LocalDirShipper:
    """Copy the archive into ``dest_dir`` (a mounted share or a test dir). ``stat``
    re-reads the destination independently, so it exercises the same verify path
    a network shipper would."""

    def __init__(self, dest_dir: str) -> None:
        self.dest_dir = dest_dir
        os.makedirs(dest_dir, exist_ok=True)

    def put(self, local_path: str, key: str) -> str:
        dest = os.path.join(self.dest_dir, key)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        shutil.copyfile(local_path, dest)
        return "file://" + os.path.abspath(dest)

    def stat(self, remote_uri: str) -> dict[str, Any]:
        path = remote_uri[len("file://"):] if remote_uri.startswith("file://") else remote_uri
        if not os.path.exists(path):
            return {"exists": False, "size": None, "sha256": None}
        return {"exists": True, "size": os.path.getsize(path), "sha256": _sha256(path)}


def verify(shipper: Shipper, remote_uri: str, expected_size: int,
           expected_sha256: str) -> tuple[bool, str]:
    """The second oracle: independently re-observe the shipped object and confirm
    it matches the local archive. Fails closed (returns False) on any mismatch or
    if the remote can't be observed. Returns ``(ok, reason)``.

    Size is always checked. The checksum is checked only when the transport can
    report one (``stat`` returns a sha256); a transport that can't must not be
    treated as if it verified — but a size match on an independent re-stat is the
    minimum bar, and callers should prefer a checksum-capable transport."""
    st = shipper.stat(remote_uri)
    if not st.get("exists"):
        return False, "remote object not found on re-stat"
    if st.get("size") != expected_size:
        return False, f"size mismatch: remote {st.get('size')} != local {expected_size}"
    remote_sha = st.get("sha256")
    if remote_sha is not None and remote_sha != expected_sha256:
        return False, f"sha256 mismatch: remote {remote_sha} != local {expected_sha256}"
    return True, ("verified size+sha256" if remote_sha is not None else "verified size only")
