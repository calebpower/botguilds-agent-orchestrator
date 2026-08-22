"""How long does a character actually stay in the field, uninterrupted?

This is the denominator for every ERRAND the strategy offers. An errand — walk to that
vein, rally to the group centre, cross to that chest — is not a one-tick action: it needs
consecutive ticks in the same world to finish. Sizing one against how FAR the target is
asks the wrong question. The right question is how far we can get before the stint ends,
and that is what this measures.

Two constants have already been sized wrongly by ignoring it (VEIN_SEEK_RANGE, and the
0.72.0 cohesion rally, which was unbounded and so almost never completed). Both looked
reasonable as distances and were unreachable as errands.

A STINT is a maximal run of consecutive ticks in which one character is in one non-village
world. It ends at a return to the village, a world change, or a gap in the frame stream.

    uv run --no-sync python tools/field_stints.py [run_id ...]
"""
import collections
import json
import sys
import zlib

import steemer.db as db


def _decode(payload):
    if isinstance(payload, (bytes, bytearray)) and payload[:1] == b"x":
        payload = zlib.decompress(payload)
    return json.loads(payload)


def stints(conn, run_id: int) -> list[int]:
    """Lengths, in ticks, of every field stint any of our characters served on `run_id`."""
    # (char, tick) -> world. Built from the frames themselves rather than from a world
    # column alone: a character is in the field when it APPEARS in a field frame, which is
    # the same evidence the strategy acts on.
    where = collections.defaultdict(dict)
    cur = conn.execute("SELECT tick, world, json FROM frames WHERE run_id=? ORDER BY tick",
                       (run_id,))
    for tick, world, payload in cur.fetchall():
        if world == "village":
            continue
        for ch in _decode(payload).get("chars") or []:
            uid = ch.get("char_uid")
            if uid:
                where[uid][tick] = world

    out = []
    for uid, by_tick in where.items():
        run_len, prev_tick, prev_world = 0, None, None
        for tick in sorted(by_tick):
            world = by_tick[tick]
            contiguous = prev_tick is not None and tick == prev_tick + 1 and world == prev_world
            if contiguous:
                run_len += 1
            else:
                if run_len:
                    out.append(run_len)
                run_len = 1
            prev_tick, prev_world = tick, world
        if run_len:
            out.append(run_len)
    return out


def report(conn, run_id: int) -> dict:
    s = sorted(stints(conn, run_id))
    if not s:
        return {"run": run_id, "stints": 0}
    def pct(q):
        return s[min(len(s) - 1, int(len(s) * q / 100))]
    return {"run": run_id, "stints": len(s), "median": pct(50), "p75": pct(75),
            "p90": pct(90), "max": s[-1],
            "share_at_least_20": round(sum(1 for x in s if x >= 20) * 100 / len(s), 1),
            "share_at_least_60": round(sum(1 for x in s if x >= 60) * 100 / len(s), 1)}


def main(argv: list[str]) -> int:
    conn = db.connect(None, readonly=True)
    runs = [int(a) for a in argv[1:]]
    if not runs:
        row = conn.execute("SELECT MAX(run_id) FROM frames").fetchone()
        runs = [row[0]]
    for run_id in runs:
        r = report(conn, run_id)
        print(json.dumps(r))
        if r.get("stints"):
            print(f"  -> an errand must finish inside ~{r['median']} ticks to be worth "
                  f"starting; only {r['share_at_least_60']}% of stints reach 60.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
