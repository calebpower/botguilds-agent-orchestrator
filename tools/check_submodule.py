# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Check whether the reference starter kit (a submodule) has upstream updates.

    uv run tools/check_submodule.py

The reference kit is inspiration only and is never imported, but the server owner
updates it (protocol tweaks, client fixes). This reports how far behind we are
and what changed, so the improvement loop can review and *deliberately* port
relevant fixes into our own code — never a blind submodule bump into the bot.

Stdlib only (PEP 723, no deps). Fetches from the network. Always exits 0; the
report is the point.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

SUBMODULE = "reference_starter_kit"


def git(*args: str, cwd: pathlib.Path) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def main() -> int:
    repo = pathlib.Path(__file__).resolve().parent.parent
    sub = repo / SUBMODULE
    if not (sub / ".git").exists() and not (sub).exists():
        print(f"submodule {SUBMODULE} not initialized (git submodule update --init)")
        return 0

    fetch = git("fetch", "--quiet", cwd=sub)
    if fetch.returncode != 0:
        print(f"could not fetch upstream: {fetch.stderr.strip() or 'unknown error'}")
        return 0

    local = git("rev-parse", "HEAD", cwd=sub).stdout.strip()
    upstream_ref = git("rev-parse", "--abbrev-ref", "origin/HEAD", cwd=sub).stdout.strip()
    if not upstream_ref:
        upstream_ref = "origin/main"
    remote = git("rev-parse", upstream_ref, cwd=sub).stdout.strip()
    if not remote:
        print(f"could not resolve upstream ref {upstream_ref!r}")
        return 0

    if local == remote:
        print(f"reference_starter_kit: up-to-date ({local[:8]}, {upstream_ref})")
        return 0

    behind = git("rev-list", "--count", f"{local}..{remote}", cwd=sub).stdout.strip()
    log = git("log", "--oneline", f"{local}..{remote}", cwd=sub).stdout.strip()
    files = git("diff", "--stat", f"{local}..{remote}", cwd=sub).stdout.strip()

    print(f"reference_starter_kit: {behind} commit(s) BEHIND {upstream_ref}")
    print(f"  local  {local[:8]}\n  remote {remote[:8]}\n")
    print("new upstream commits:")
    print("  " + log.replace("\n", "\n  "))
    print("\nfiles changed upstream:")
    print("  " + files.replace("\n", "\n  "))
    print("\nACTION: review these and consider porting relevant fixes into steemer/ "
          "by hand. Do NOT merge the submodule into the bot. Log the decision in "
          "decisions.log. To advance the pin after review: "
          "cd reference_starter_kit && git checkout <sha>.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
