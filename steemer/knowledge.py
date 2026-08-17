"""Learned per-world game model, kept as DATA the strategy reads.

This is Stanley_Steemer's brewing essence map, DECODED from live play (run #8,
git a44958d): 34 blind brews whose products and *curdle* pattern pinned each
ingredient's essence on the weave circle. ``vigor`` and ``venom`` sit at
opposite poles — every observed curdle was a brew that mixed the two — so the
strategy groups same-essence ingredients and prefers ``vigor`` (which brews
``potion_red``, the only field heal fast enough to beat poison). See
``findings.jsonl`` (the essence-map / product discoveries) for the evidence and
per-entry confidence.

Only HIGH-confidence entries live here on purpose: acting on a guess would
curdle the brew. Ingredients we have not decoded (``essence_of`` -> ``None``)
are brewed only among *themselves*, as a learning batch — never mixed with a
known essence they might oppose.

This map is per-WORLD (the game shuffles the vocabulary each world), so it is
knowledge, not logic — it lives in data. When a ``taste`` probe or more brews
resolve a new herb, update this dict; the strategy needs no code change.
"""

from __future__ import annotations

# ingredient kind -> essence on THIS world's weave circle.
# vigor and venom are opposite poles (mixing them curdles).
ESSENCE: dict[str, str] = {
    # fixed calibration anchors (server-documented, world-invariant)
    "bone": "vigor",
    "venom_sac": "venom",
    "ectoplasm": "aether",
    # decoded HIGH confidence (run #8): see findings.jsonl
    "embercap": "vigor",      # the 'ember' in the name is a deliberate red herring
    "moonbell": "venom",
    # LEFT OUT until confirmed (LOW/MED only): glimmerweed(~venom),
    # bitterroot(~vigor), fickle_pearl(~aether), frostmoss/sungrass (off-axis).
    # Acting on those guesses would curdle — resolve them with `taste` first.
}


def essence_of(kind: str) -> str | None:
    """This world's decoded essence for an ingredient kind, or None if unknown."""
    return ESSENCE.get(kind)
