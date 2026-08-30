"""Comb every backup archive: stream frames, decode blobs, per-run summary JSONL.
Resumable: skips run_ids already present in the output file."""
import base64, gzip, json, os, sys, zlib
from collections import Counter

ARCH = "/mnt/nas/truenas.chack.internal/samba_share/MemberFiles/CAL/archives/bots/bot_guilds/steemer"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archives_summary.jsonl")

done = set()
if os.path.exists(OUT):
    with open(OUT) as f:
        for line in f:
            try:
                done.add(json.loads(line)["run_id"])
            except Exception:
                pass

files = sorted(f for f in os.listdir(ARCH) if f.endswith(".frames.jsonl.gz"))
out = open(OUT, "a")
for fname in files:
    path = os.path.join(ARCH, fname)
    try:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            header = json.loads(f.readline())
            rid = header.get("run_id")
            if rid in done:
                continue
            s = {"run_id": rid, "file": fname,
                 "git_sha": header.get("git_sha"),
                 "version": header.get("strategy_version"),
                 "started_at": header.get("started_at"),
                 "stopped_at": header.get("stopped_at"),
                 "note": header.get("note")}
            frames = 0
            tick_lo = tick_hi = None
            wall_lo = wall_hi = None
            worlds = Counter()
            ev = Counter()
            our_deaths = []
            xp_total = 0
            gold_first = gold_last = gold_max = None
            uids = set()
            max_level = 0
            level_holder = None
            max_int = 0
            tile_kinds = Counter()
            fielded_samples = 0
            fielded_pos = 0
            for line in f:
                try:
                    row = json.loads(line)
                    blob = zlib.decompress(base64.b64decode(row["z"]))
                    fr = json.loads(blob)
                except Exception:
                    ev["_decode_error"] += 1
                    continue
                frames += 1
                tk = row.get("tick")
                if tk is not None:
                    tick_lo = tk if tick_lo is None else min(tick_lo, tk)
                    tick_hi = tk if tick_hi is None else max(tick_hi, tk)
                ra = row.get("received_at")
                if ra:
                    wall_lo = ra if wall_lo is None else min(wall_lo, ra)
                    wall_hi = ra if wall_hi is None else max(wall_hi, ra)
                worlds[row.get("world") or "?"] += 1
                g = fr.get("guild") or {}
                if "gold" in g:
                    if gold_first is None:
                        gold_first = g["gold"]
                    gold_last = g["gold"]
                    gold_max = g["gold"] if gold_max is None else max(gold_max, g["gold"])
                if row.get("world") == "village":
                    bw = g.get("chars_by_world") or {}
                    fielded_samples += 1
                    if sum(len(v) for v in bw.values()):
                        fielded_pos += 1
                for c in fr.get("chars") or []:
                    u = c.get("char_uid")
                    if u:
                        uids.add(u)
                    lv = c.get("level") or 0
                    if lv > max_level:
                        max_level, level_holder = lv, u
                    stats = c.get("stats") or {}
                    if (stats.get("int") or 0) > max_int:
                        max_int = stats["int"]
                for e in fr.get("events") or []:
                    k = e.get("kind") or "?"
                    ev[k] += 1
                    if k == "xp":
                        xp_total += 1
                    if k == "death" and e.get("guild_id") == "g_cd0e2a":
                        our_deaths.append({"uid": e.get("char_uid"),
                                           "tick": row.get("tick"),
                                           "world": row.get("world")})
                vis = fr.get("visible") or {}
                for t in vis.get("tiles") or []:
                    if isinstance(t, (list, tuple)) and len(t) > 2:
                        tile_kinds[t[2]] += 1
                    elif isinstance(t, dict):
                        tile_kinds[t.get("kind") or "?"] += 1
            s.update({
                "frames": frames, "tick_lo": tick_lo, "tick_hi": tick_hi,
                "wall_lo": wall_lo, "wall_hi": wall_hi,
                "worlds": dict(worlds),
                "events": dict(ev.most_common(30)),
                "xp": xp_total,
                "our_deaths": our_deaths[:50],
                "our_death_count": len(our_deaths),
                "gold_first": gold_first, "gold_last": gold_last, "gold_max": gold_max,
                "unique_chars": len(uids), "max_level": max_level,
                "max_level_holder": level_holder, "max_int": max_int,
                "duty": (fielded_pos / fielded_samples) if fielded_samples else None,
                "tile_kinds": dict(tile_kinds.most_common(30)),
            })
            out.write(json.dumps(s) + "\n")
            out.flush()
            print(f"run {rid}: {frames} frames ok", flush=True)
    except Exception as e:
        print(f"FAIL {fname}: {type(e).__name__} {e}", flush=True)
print("comb done")
