"""The lab notebook: discoveries, conjectures, and orchestration considerations.

BotGuilds hides its content on purpose (items, enemies, recipes, the weave
circle, crafting tells), so the most valuable thing this system builds is an
evidence-backed model of how the game actually works. That model lives in
``findings.jsonl`` at the repo root — git-tracked, so it outlives the log DB's
retention and is diffable.

One JSON object per line:

    {"kind": "discovery|conjecture|consideration",
     "status": "open|confirmed|refuted|shipped",
     "title": "...", "detail": "...", "evidence": "...",
     "test": "how it would be falsified",   # required for conjectures
     "confidence": "low|medium|high" or 0..1,
     "tags": ["crafting", ...],
     "created": "ISO-8601", "updated": "ISO-8601"}

Discipline (enforced by :func:`validate`): a conjecture without a falsification
``test`` and a ``confidence`` is just noise; a confirmed discovery needs
``evidence``. Same spirit as "every fix ships with a test".
"""

from __future__ import annotations

import datetime
import json
import os
from typing import Any

FINDINGS_PATH = "findings.jsonl"

KINDS = frozenset({"discovery", "conjecture", "consideration"})
STATUSES = frozenset({"open", "confirmed", "refuted", "shipped"})


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def validate(entry: Any) -> str | None:
    """None if the entry is well-formed, else a short reason."""
    if not isinstance(entry, dict):
        return "not_an_object"
    if entry.get("kind") not in KINDS:
        return "bad_kind"
    if entry.get("status") not in STATUSES:
        return "bad_status"
    if not entry.get("title"):
        return "missing_title"
    if entry["kind"] == "conjecture":
        if not entry.get("test"):
            return "conjecture_needs_test"      # how would we falsify it?
        if entry.get("confidence") in (None, ""):
            return "conjecture_needs_confidence"
    if entry["kind"] == "discovery" and entry.get("status") == "confirmed" \
            and not entry.get("evidence"):
        return "confirmed_discovery_needs_evidence"
    return None


def load(path: str = FINDINGS_PATH) -> list[dict[str, Any]]:
    """Read all findings; skip blank/malformed lines rather than raising, so a
    half-written line never takes the notebook (or the UI) down."""
    out: list[dict[str, Any]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    except FileNotFoundError:
        return []
    return out


def append(entry: dict[str, Any], path: str = FINDINGS_PATH) -> dict[str, Any]:
    """Validate, timestamp, and append one finding. Raises ValueError if invalid
    — the loop should never write a finding that fails the discipline check."""
    entry = dict(entry)
    entry.setdefault("created", _now())
    entry["updated"] = _now()
    entry.setdefault("status", "open")
    entry.setdefault("tags", [])
    reason = validate(entry)
    if reason is not None:
        raise ValueError(f"invalid finding ({reason}): {entry.get('title')!r}")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def rewrite(entries: list[dict[str, Any]], path: str = FINDINGS_PATH) -> None:
    """Replace the whole notebook — the supported way to *curate* (resolve a
    conjecture to confirmed/refuted, mark a consideration shipped, prune a
    duplicate) rather than only append. Every entry is validated; created/updated
    are preserved as given (the caller bumps ``updated`` on what it changed).
    Written atomically so a crash can't leave a half-file.
    """
    lines = []
    for e in entries:
        e = dict(e)
        e.setdefault("status", "open")
        e.setdefault("tags", [])
        e.setdefault("created", _now())
        e.setdefault("updated", e["created"])
        reason = validate(e)
        if reason is not None:
            raise ValueError(f"invalid finding ({reason}): {e.get('title')!r}")
        lines.append(json.dumps(e, ensure_ascii=False))
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(tmp, path)
