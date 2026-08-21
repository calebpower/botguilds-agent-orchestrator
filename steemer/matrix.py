"""The cross-referencing exploration matrix — slice (A): the cube and THE FRONTIER.

Operator's idea (2026-08-21). A cube of **noun x verb x equipped**, each cell scored 0..1
for "is there something one could plausibly do here — a mechanic that exists in real life
or in other games?", used to drive deliberate discovery instead of lucky reading.

This slice is READ-ONLY and issues no actions. It answers one question:

    WHICH HIGH-PLAUSIBILITY CELLS HAVE WE NEVER ONCE TRIED?

That is worth having on its own. The 0.45 harvest win was literally one cell of this cube —
`tree x attack x none` — found by hand after trees had sat in `nav.SOLID` as scenery for the
whole project. And the frontier is not a few odd corners: across 4.3M actions we have only
ever used 14 of the protocol's verbs.

DESIGN NOTES

* **Priors come from auditable RULE FAMILIES, not per-cell guesses.** The cube is thousands
  of cells; hand-scoring them does not scale and does not survive the game inventing a new
  noun (it is an evolving target). A family states its reasoning once — "a chopping verb on
  a woody target with a bladed tool is highly plausible" — and every matching cell inherits
  it. Per-cell overrides exist for where a family is wrong.
* **The TESTED layer is free and retroactive.** `actions_sent` x `action_errors` x `events`
  already records what we sent, whether it bounced and with which reason, and what happened.
  No new action is issued to populate it.
* **An `action_error` is INFORMATION, not failure.** `unknown_action` says the verb does not
  exist; `out_of_range` says it does and we were merely too far away. The second is a much
  more interesting cell than the first.
* **`say` gets a different depth axis.** Equipment barely varies the outcome of speaking;
  the variable is the WORD. Handled by :func:`say_wordlist` rather than the equip axis.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Iterable

# --------------------------------------------------------------------------- #
# Priors: rule families
# --------------------------------------------------------------------------- #

WOODY = frozenset({"tree", "bush", "crop", "lily", "tall_grass", "web"})
STONY = frozenset({"rock", "vein", "wall"})
OPENABLE = frozenset({"chest", "safe", "grave", "portal", "cauldron", "forge"})
BLADED = frozenset({"axe", "dagger", "shortsword", "spear", "sickle", "pike"})
HEAVY = frozenset({"pickaxe", "club", "hammer"})
CONSUMABLE_USES = frozenset({"drink", "taste"})

#: (name, predicate(noun, verb, equipped, ctx) -> bool, prior, why)
#: Order matters only for reporting; the HIGHEST matching family wins a cell.
FAMILIES: list[tuple[str, Any, float, str]] = [
    ("chop-woody-with-blade",
     lambda n, v, e, c: n in WOODY and v == "attack" and e in BLADED,
     0.95, "a blade on woody terrain is the canonical harvest in life and in games"),
    ("break-stony-with-heavy",
     lambda n, v, e, c: n in STONY and v == "attack" and e in HEAVY,
     0.95, "a pickaxe on rock/vein is the canonical mining verb"),
    ("chop-woody-barehanded",
     lambda n, v, e, c: n in WOODY and v == "attack" and e == "none",
     0.75, "slower without a tool, but this is the cell 0.45 CONFIRMED for trees"),
    ("break-stony-barehanded",
     lambda n, v, e, c: n in STONY and v == "attack" and e == "none",
     0.70, "same shape as the confirmed tree cell"),
    ("open-the-openable",
     lambda n, v, e, c: n in OPENABLE and v == "open",
     0.85, "`open` is already live (2,948 sends) and `nothing_to_open` is a real error"),
    ("speak-at-a-sealed-thing",
     lambda n, v, e, c: n in {"portal", "grave", "safe", "chest", "wall"} and v == "say",
     0.70, "a safe has a combination, a grave is spoken at, a portal is "
           "speak-friend-and-enter; we have NEVER sent `say`"),
    ("consume-a-consumable",
     lambda n, v, e, c: v == "use" and bool(CONSUMABLE_USES & set(c.get("uses", {}).get(n, ()))),
     0.80, "an item that declares drink/taste is meant to be used"),
    ("craft-with-declared-use",
     lambda n, v, e, c: v in {"brew", "smelt", "forge"} and v in c.get("uses", {}).get(n, ()),
     0.95, "the item itself declares this craft verb in `uses` — authoritative"),
    ("equip-the-equippable",
     lambda n, v, e, c: v == "equip" and n in c.get("equippable", ()),
     0.90, "declared equippable"),
    ("consume-a-non-consumable",
     lambda n, v, e, c: v == "use" and n in c.get("tiles", ()),
     0.10, "using terrain as an item is not a mechanic in anything"),
    ("attack-the-inert",
     lambda n, v, e, c: v == "attack" and n in {"floor", "path", "water", "track"},
     0.05, "hitting the ground is not a mechanic"),
]

DEFAULT_PRIOR = 0.25   # unknown pairing: worth a look eventually, not a priority

#: Verbs whose outcome plausibly varies with what is HELD. For every other verb the equip
#: axis is noise — brewing a herb does not care which sword you carry — and reporting the
#: same cell once per equippable buried the frontier under 7x duplicates on first run.
EQUIP_SENSITIVE_VERBS = frozenset({"attack", "charge", "throw", "cast"})


def prior_for(noun: str, verb: str, equipped: str, ctx: dict[str, Any]) -> tuple[float, str]:
    """The highest-scoring family that matches, or the default. PURE."""
    best = (DEFAULT_PRIOR, "no family matched — unclassified pairing")
    for name, pred, score, why in FAMILIES:
        try:
            if pred(noun, verb, equipped, ctx) and score > best[0]:
                best = (score, f"{name}: {why}")
        except Exception:                   # a malformed ctx must not break scoring
            continue
    return best


# --------------------------------------------------------------------------- #
# The tested layer, and the frontier
# --------------------------------------------------------------------------- #

def tested_cells(conn: Any, limit: int = 200000) -> dict[tuple[str, str], dict[str, Any]]:
    """What we have ALREADY tried, keyed (noun, verb), from history alone.

    Nouns are recovered from the action payload where it names one (`kind` for a buy, the
    tile under a harvest target is not recorded, so terrain verbs land under the verb with
    noun ``"*"``). Deliberately coarse: the point is to separate NEVER-TRIED from tried, not
    to reconstruct every target.
    """
    out: dict[tuple[str, str], dict[str, Any]] = {}

    def rows(sql, params=()):
        return conn.execute(sql, params).fetchall()

    def col(r, name, idx):
        return r[name] if hasattr(r, "keys") else r[idx]

    # Every verb we have EVER sent, from a DISTINCT query rather than a recent-rows window:
    # `brew` has only 474 lifetime sends and fell outside a 200k-row limit on the first run,
    # so the frontier wrongly reported brewing as never tried.
    for r in rows("SELECT DISTINCT action FROM actions_sent"):
        out.setdefault(("*", col(r, "action", 0)), {"sent": 0, "errors": Counter()})
    for r in rows(f"SELECT action, payload_json FROM actions_sent ORDER BY seq DESC "
                  f"LIMIT {int(limit)}"):
        verb = col(r, "action", 0)
        try:
            p = json.loads(col(r, "payload_json", 1) or "{}")
        except (TypeError, ValueError):
            p = {}
        noun = str(p.get("kind") or p.get("product") or "*")
        cell = out.setdefault((noun, verb), {"sent": 0, "errors": Counter()})
        cell["sent"] += 1
    for r in rows("SELECT action, reason, COUNT(*) AS n FROM action_errors "
                  "GROUP BY action, reason"):
        verb, reason = col(r, "action", 0), col(r, "reason", 1)
        n = col(r, "n", 2)
        for (noun, v), cell in out.items():
            if v == verb:
                cell["errors"][reason] += n
    return out


def frontier(nouns: Iterable[str], verbs: Iterable[str], equips: Iterable[str],
             tested: dict[tuple[str, str], dict[str, Any]], ctx: dict[str, Any],
             min_prior: float = 0.5) -> list[dict[str, Any]]:
    """High-plausibility cells we have NEVER tried, best first. PURE given its inputs."""
    out = []
    for noun in nouns:
        for verb in verbs:
            if (noun, verb) in tested or ("*", verb) in tested:
                continue                    # this verb has been exercised somewhere
            # collapse the equip axis where it cannot matter (see EQUIP_SENSITIVE_VERBS)
            axis = list(equips) if verb in EQUIP_SENSITIVE_VERBS else ["any"]
            for eq in axis:
                p, why = prior_for(noun, verb, eq if eq != "any" else "none", ctx)
                if p >= min_prior:
                    out.append({"noun": noun, "verb": verb, "equipped": eq,
                                "prior": p, "why": why})
    out.sort(key=lambda c: (-c["prior"], c["noun"], c["verb"], c["equipped"]))
    return out


#: Words to try at a sealed thing. In-world sources rank ABOVE folklore imports: a word the
#: game itself showed us is far better evidence than one borrowed from Tolkien.
FOLKLORE_WORDS = ("open", "sesame", "friend", "mellon", "xyzzy", "plugh", "please", "hello")


def say_wordlist(in_world: Iterable[str] = ()) -> list[str]:
    """The `say` depth axis: world-sourced words first, then folklore conventions."""
    seen, out = set(), []
    for w in list(in_world) + list(FOLKLORE_WORDS):
        w = str(w).strip().lower()
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def build(vocabulary: dict[str, Any], tested: dict[tuple[str, str], dict[str, Any]],
          min_prior: float = 0.5) -> dict[str, Any]:
    """Assemble the report: coverage, the frontier, and the untouched verbs."""
    nouns = sorted(set(vocabulary.get("tiles", [])) | set(vocabulary.get("items", []))
                   | set(vocabulary.get("mobs", [])))
    verbs = list(vocabulary.get("verbs_protocol", []))
    equips = ["none"] + sorted(vocabulary.get("equippable", []))
    ctx = {"uses": vocabulary.get("uses_by_kind", {}),
           "equippable": set(vocabulary.get("equippable", [])),
           "tiles": set(vocabulary.get("tiles", []))}
    fr = frontier(nouns, verbs, equips, tested, ctx, min_prior=min_prior)
    return {
        "cells_total": len(nouns) * len(verbs) * len(equips),
        "nouns": len(nouns), "verbs": len(verbs), "equips": len(equips),
        "verbs_never_sent": sorted(vocabulary.get("verbs_never_sent", [])),
        "frontier": fr,
        "frontier_size": len(fr),
        "say_words": say_wordlist(),
    }


if __name__ == "__main__":              # pragma: no cover - thin CLI
    import argparse
    import os
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vocabulary", default="tests/fixtures/vocabulary.json")
    ap.add_argument("--min-prior", type=float, default=0.5)
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()
    from . import db as _db
    voc = json.load(open(a.vocabulary))
    conn = _db.connect(_db.load_db_config(), readonly=True)
    rep = build(voc, tested_cells(conn), min_prior=a.min_prior)
    print(f"cube: {rep['nouns']} nouns x {rep['verbs']} verbs x {rep['equips']} equips "
          f"= {rep['cells_total']} cells")
    print(f"verbs NEVER sent ({len(rep['verbs_never_sent'])}): "
          f"{', '.join(rep['verbs_never_sent'])}")
    print(f"\nTHE FRONTIER — {rep['frontier_size']} untried cells at prior >= {a.min_prior}:")
    for c in rep["frontier"][:a.top]:
        print(f"  {c['prior']:.2f}  {c['noun']:>12} x {c['verb']:<12} x {c['equipped']:<12}"
              f"  {c['why'][:60]}")
