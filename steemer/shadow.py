"""Shadow evaluation: would a candidate strategy actually DO anything?

The gap this closes, demonstrated three times in one session (2026-08-21):

* **v0.46.0** reserved forge feedstock unconditionally — correct code, full green gate,
  and live it stockpiled a shaft with no metal to forge it onto while cutting income.
* **v0.48.0** added a cohesion move scored 2.8. Live it was offered 28 times and chosen
  ZERO, losing every tick to loot-seek at 4.0. Correct code, full green gate, inert.
* **v0.48.1** fixed that — and the only way to know before waiting hours for a rare band
  was to replay it against recorded frames, which is this module.

A passing test suite proves the code does what it says. It cannot prove the behaviour ever
WINS a tick, because winning depends on the rest of the scoring ladder and on what the
world actually offers. That is a question only real frames answer.

    uv run python -m steemer.shadow --run 117 --limit 2000
    uv run python -m steemer.shadow --world mines --limit 3000

The incumbent needs no git gymnastics: it ALREADY RAN, and its per-tick reasoning is in
the `decisions` table. So this replays the working tree's strategy over the same frames and
diffs the two — what the new code would choose against what the old code actually chose.

Read the INERT list first. A branch offered many times and chosen zero times is a change
that will not do anything, however green its tests are.

**TRUST THE STRUCTURE, NOT THE COUNTS.** `new_branches`, `dropped_branches` and `inert` are
meaningful; the `shifted` numbers are NOT a prediction of live behaviour. Replay cannot
reproduce live counts, because the recorded frames were produced by a DIFFERENT action
sequence than the candidate would produce — the replayed bot accumulates a different map,
its characters are never actually moved by its own decisions, and the divergence compounds.
Expect swings of thousands in `rest` and the explore branches that have nothing to do with
the change under test. Use `shifted` to notice that something moved, never to size it.

And for a change that REMOVES actions rather than adding a branch, this diff is the wrong
instrument entirely: count the specific thing. v0.49.0 (the duplicate-purchase latch) was
verified by counting repeated `buy {same kind}` per character within INTENT_TTL — 11 of 31
live buys were duplicates, 0 under the candidate.

TWO WAYS TO GET A CONFIDENT WRONG ANSWER OUT OF THIS, both learned the hard way:

1. **WARM-UP.** A branch gated on LEARNED state does not fire until that state exists.
   v0.48.0's cohesion was judged "inert" from a sample taken 130 ticks after deploy; it
   first won at tick 461 and went on to win 349 ticks. A redeploy resets the strategy
   object, so every run has a warm-up. Never judge inertness from a window shorter than
   the warm-up of the slowest gate in the change — and if you do not know that number,
   the window is too short. :func:`verdict` refuses to rule at all below ``min_decisions``.

2. **DO NOT DIFF TWO DIFFERENT LIVE RUNS.** The incumbent tally must come from the SAME
   frames the candidate is replayed over, which is what the CLI does. Comparing run A to
   run B conflates code change with world variation, and cheerfully reports "new branches"
   like `dodging an adjacent boar` — not new code at all, just a boar that happened not to
   appear in the other window.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from typing import Any, Iterable

# Reasons carry per-tick specifics ("a wolf is 2 away", "selling meat (tier 1)"). The BRANCH
# is the phrase before the first dash/colon/paren, with numbers and character uids blanked,
# so the same branch groups across characters and ticks. Same normalisation the dashboard's
# nav explainer uses, kept here rather than imported so the analysis tool does not depend on
# the UI package.
_SPLIT = re.compile(r"\s+[—–-]\s+|[;:(]")
_UID = re.compile(r"g_[0-9a-f]+_c\d+")
_NUM = re.compile(r"\d+(\.\d+)?%?")


def branch_of(why: str) -> str:
    head = _SPLIT.split(why or "", 1)[0]
    return _NUM.sub("#", _UID.sub("a char", head)).strip().rstrip(",") or "(unlabelled)"


def tally(alternatives: Iterable[Iterable[dict[str, Any]]]) -> dict[str, dict[str, int]]:
    """{branch: {offered, chosen}} over a sequence of per-decision alternative lists."""
    offered: Counter = Counter()
    chosen: Counter = Counter()
    for alts in alternatives:
        for a in alts or ():
            b = branch_of(str(a.get("why", "")))
            offered[b] += 1
            if a.get("chosen"):
                chosen[b] += 1
    return {b: {"offered": offered[b], "chosen": chosen[b]} for b in offered}


def compare(candidate: dict[str, dict[str, int]],
            incumbent: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Diff two tallies into the three things worth acting on.

    ``inert`` is the headline: branches the candidate OFFERS but never WINS. A change whose
    branches are all inert is a change that will do nothing, and shipping it burns a
    measurement window for no information.
    """
    new = {b: v for b, v in candidate.items() if b not in incumbent}
    gone = {b: v for b, v in incumbent.items() if b not in candidate}
    inert = {b: v for b, v in candidate.items() if v["offered"] > 0 and v["chosen"] == 0}
    shifted = {}
    for b, v in candidate.items():
        if b in incumbent:
            d = v["chosen"] - incumbent[b]["chosen"]
            if d:
                shifted[b] = {"candidate": v["chosen"], "incumbent": incumbent[b]["chosen"],
                              "delta": d}
    return {"new_branches": new, "dropped_branches": gone, "inert": inert,
            "shifted": shifted,
            "candidate_decisions": sum(v["chosen"] for v in candidate.values()),
            "incumbent_decisions": sum(v["chosen"] for v in incumbent.values())}


MIN_DECISIONS = 2000     # below this the sample cannot outlast a learned gate's warm-up


def verdict(cmp: dict[str, Any], min_decisions: int = MIN_DECISIONS) -> tuple[bool, str]:
    """Would this change do anything? Returns (ok, reason).

    NOT ok when every new branch is inert — that is precisely the v0.46.0 failure. A
    candidate with no new branches at all is fine (a tuning change shifts existing ones).

    REFUSES TO RULE on a sample too small to have outlived a warm-up. This guard is the
    whole lesson of v0.48.0: cohesion was called inert on 28 offers taken 130 ticks after a
    deploy, and it first won at tick 461. An "INERT" verdict from a short window is worse
    than no verdict, because it reads as evidence rather than as ignorance.
    """
    seen = cmp["candidate_decisions"]
    if seen < min_decisions:
        return True, (f"INCONCLUSIVE: only {seen} candidate decisions (< {min_decisions}). "
                      "Too short to outlast a learned gate's warm-up — widen the window "
                      "before trusting an inert reading.")
    new = cmp["new_branches"]
    if not new:
        return True, "no new branches; this is a tuning change — check `shifted`"
    live = {b: v for b, v in new.items() if v["chosen"] > 0}
    if live:
        return True, (f"{len(live)} of {len(new)} new branch(es) win ticks: "
                      + ", ".join(f"{b} x{v['chosen']}" for b, v in sorted(
                          live.items(), key=lambda kv: -kv[1]["chosen"])[:4]))
    return False, ("EVERY new branch is INERT — offered but never chosen. It will do nothing "
                   "live. Check what outscores it before shipping.")


# --------------------------------------------------------------------------- #
# IO
# --------------------------------------------------------------------------- #

def recorded(conn: Any, run_id: int | None = None, world: str | None = None,
             limit: int = 5000) -> dict[str, dict[str, int]]:
    """The incumbent's tally, straight from what it actually chose live."""
    sql = "SELECT alternatives_json FROM decisions"
    where, params = [], []
    if run_id is not None:
        where.append("run_id=?"); params.append(run_id)
    if world:
        where.append("world=?"); params.append(world)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += f" ORDER BY seq DESC LIMIT {int(limit)}"
    rows = conn.execute(sql, tuple(params)).fetchall()

    def _alts(r):
        raw = r["alternatives_json"] if hasattr(r, "keys") else r[0]
        try:
            return json.loads(raw) if raw else []
        except (TypeError, ValueError):
            return []
    return tally(_alts(r) for r in rows)


def frames_of_run(conn: Any, run_id: int, world: str | None = None,
                  limit: int = 2000) -> list[dict[str, Any]]:
    """The newest ``limit`` frames OF ONE RUN, oldest-first.

    Deliberately not ``storage.read_frames``: that has no run filter and returns the oldest
    frames in the entire database, so the candidate would replay ancient history against the
    incumbent's most recent decisions — different frames, which is precisely the misuse
    warned about above. It produced obvious nonsense the first time this CLI was run
    (`rest` 14179 -> 7785, `pushing north` 1359 -> 9), which is the only reason it was
    caught immediately.
    """
    import json as _json
    import zlib as _zlib
    sql = "SELECT json FROM frames WHERE run_id=?"
    params: list[Any] = [run_id]
    if world:
        sql += " AND world=?"
        params.append(world)
    sql += f" ORDER BY seq DESC LIMIT {int(limit)}"
    out = []
    for row in conn.execute(sql, tuple(params)).fetchall():
        raw = row["json"] if hasattr(row, "keys") else row[0]
        if isinstance(raw, str):
            raw = raw.encode("latin-1")
        try:
            out.append(_json.loads(_zlib.decompress(raw)))
        except Exception:
            continue
    return out[::-1]


def main(argv: list[str] | None = None) -> int:      # pragma: no cover - thin CLI
    from . import db as _db
    from .bot import GuildBot
    from .storage import Storage

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run", type=int, default=None, help="incumbent run_id (default: newest)")
    ap.add_argument("--world", default=None)
    ap.add_argument("--limit", type=int, default=2000)
    ap.add_argument("--strategy", default="explorer")
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)

    src = _db.load_db_config(args.config)
    ro = _db.connect(src, readonly=True)
    run_id = args.run
    if run_id is None:
        row = ro.execute("SELECT MAX(run_id) AS r FROM runs").fetchone()
        run_id = (row["r"] if hasattr(row, "keys") else row[0])

    frames = frames_of_run(ro, run_id, world=args.world, limit=args.limit)
    if not frames:
        print(f"no frames for run {run_id}"
              + (f" world={args.world}" if args.world else ""))
        return 2
    # Incumbent decisions from the SAME run. Several characters decide per frame, so allow
    # generously more decisions than frames — but they are the same window either way.
    inc = recorded(ro, run_id=run_id, world=args.world, limit=args.limit * 8)

    mem = Storage(":memory:", commit_every=1)
    bot = GuildBot(strategy=args.strategy, storage=mem)
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 30,
                  "maps": [{"id": "vale"}, {"id": "mines"}, {"id": "spire"}]}
    n = 0
    for frame in frames:
        bot.tick = frame.get("tick", bot.tick)
        try:
            bot.on_frame(frame)
        except Exception:                    # a bad frame must not abort the evaluation
            continue
        n += 1
    rows = mem.conn.execute("SELECT alternatives_json FROM decisions").fetchall()
    cand = tally((json.loads(r[0]) if r[0] else []) for r in rows)

    cmp = compare(cand, inc)
    ok, why = verdict(cmp)
    print(f"shadow-eval: {n} frames replayed vs run #{run_id}"
          f" ({cmp['candidate_decisions']} candidate / {cmp['incumbent_decisions']} incumbent decisions)")
    print(f"\nVERDICT: {'OK' if ok else 'INERT'} — {why}\n")
    if cmp["new_branches"]:
        print("NEW branches (candidate only):")
        for b, v in sorted(cmp["new_branches"].items(), key=lambda kv: -kv[1]["chosen"]):
            flag = "   <-- INERT" if v["chosen"] == 0 else ""
            print(f"   offered {v['offered']:>6}  chosen {v['chosen']:>6}  {b}{flag}")
    if cmp["dropped_branches"]:
        print("\nDROPPED branches (incumbent only):")
        for b, v in sorted(cmp["dropped_branches"].items(), key=lambda kv: -kv[1]["chosen"])[:8]:
            print(f"   was chosen {v['chosen']:>6}  {b}")
    if cmp["shifted"]:
        print("\nBiggest shifts in existing branches:")
        for b, v in sorted(cmp["shifted"].items(), key=lambda kv: -abs(kv[1]["delta"]))[:8]:
            print(f"   {v['incumbent']:>6} -> {v['candidate']:>6}  ({v['delta']:+})  {b}")
    return 0 if ok else 1


if __name__ == "__main__":                    # pragma: no cover
    raise SystemExit(main())
