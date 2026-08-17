"""Pluggable, versioned strategies.

A strategy decides what the guild does; the bot (:mod:`steemer.bot`) owns the
plumbing (persistent map memory, decision traces, storage). New strategies are
added here and selected by name so the improvement loop can swap them and
attribute metrics to a version.
"""

from __future__ import annotations

from .base import FieldContext, Strategy
from .explorer import Explorer

_REGISTRY: dict[str, type[Strategy]] = {
    "explorer": Explorer,
}


def get_strategy(name: str) -> Strategy:
    """Instantiate a strategy by name (default ``explorer``)."""
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise SystemExit(
            f"unknown strategy {name!r}; known: {', '.join(sorted(_REGISTRY))}"
        )


__all__ = ["FieldContext", "Strategy", "Explorer", "get_strategy"]
