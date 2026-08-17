"""Verbose decision traces — the bot's "thinking", made first-class.

Every per-character decision builds a :class:`DecisionTrace`: the observations
that fed it, the candidate actions it weighed (each with a score and a reason),
and the choice it made. The trace renders to human-readable text and persists to
:mod:`steemer.storage`, where the web UI surfaces it. Making reasoning a
structured artifact — not a stray log line — is what lets both a person and the
analysis loop see *why* the bot did what it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    """One action the bot considered, with the score and rationale behind it."""

    action: dict[str, Any] | None       # None represents "rest" (send nothing)
    score: float
    why: str

    def label(self) -> str:
        if self.action is None:
            return "rest"
        name = self.action.get("action", "?")
        extra = {k: v for k, v in self.action.items()
                 if k not in ("action", "char_uid")}
        return f"{name} {extra}" if extra else name


@dataclass
class DecisionTrace:
    """Accumulates the reasoning for one character on one tick."""

    tick: int
    world: str | None
    char_uid: str | None
    notes: list[str] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    chosen: Candidate | None = None

    def observe(self, text: str) -> "DecisionTrace":
        """Record an observation that fed the decision (state, threats, goals)."""
        self.notes.append(text)
        return self

    def consider(self, action: dict[str, Any] | None, score: float, why: str) -> "DecisionTrace":
        """Record a candidate action, its score, and why it scored that way."""
        self.candidates.append(Candidate(action, score, why))
        return self

    def decide(self) -> dict[str, Any] | None:
        """Pick the highest-scoring candidate; return the action to send.

        Ties keep the earliest considered (stable), so ordering candidates by
        intent priority gives sensible tie-breaks. Returns ``None`` for rest.
        """
        if not self.candidates:
            self.chosen = Candidate(None, 0.0, "no candidate offered — resting")
            return None
        self.chosen = max(self.candidates, key=lambda c: c.score)
        return self.chosen.action

    def reasoning_text(self) -> str:
        """Render the whole trace as readable prose for storage and the UI."""
        lines: list[str] = []
        if self.notes:
            lines.append("saw: " + "; ".join(self.notes))
        if self.candidates:
            ranked = sorted(self.candidates, key=lambda c: c.score, reverse=True)
            lines.append("weighed:")
            for c in ranked:
                mark = "→" if c is self.chosen else " "
                lines.append(f"  {mark} [{c.score:+.1f}] {c.label()} — {c.why}")
        if self.chosen is not None:
            lines.append(f"chose: {self.chosen.label()}")
        return "\n".join(lines)

    def alternatives(self) -> list[dict[str, Any]]:
        """The candidates as plain dicts, for structured storage / the UI."""
        return [
            {"action": c.label(), "score": c.score, "why": c.why,
             "chosen": c is self.chosen}
            for c in sorted(self.candidates, key=lambda c: c.score, reverse=True)
        ]

    def record(self, storage: Any, strategy_version: str) -> None:
        """Persist this trace (no-op if there is no storage)."""
        if storage is None:
            return
        storage.record_decision(
            tick=self.tick,
            world=self.world,
            char_uid=self.char_uid,
            chosen=self.chosen.action if self.chosen else None,
            alternatives=self.alternatives(),
            reasoning=self.reasoning_text(),
            strategy_version=strategy_version,
        )
