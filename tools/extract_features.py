"""Extract training rows from recorded runs — one ordered pass per run, never per-death.

Runs INSIDE the reaper training session (Linux, DB reachable as the SELECT-only
`reaper_ro` user via reaper_db.toml); nothing here executes on the live bot. The pure
feature/label logic lives in ``steemer/mlfeat.py`` — this file is only the streamer, the
sampling policy, and the file format, mirroring the bestiary three-layer split
(pure core / normalise / DB adapter).

Anti-patterns this file exists to avoid, named:
  * per-death range queries (14,896 deaths x window = 14,896 round trips): the death
    index is preloaded per run and labels are computed from it directly;
  * the world-wide event stream counted as ours: every death is filtered through the
    guild id (the attribution module's founding lesson);
  * interleaving statements on a streaming connection: all per-run lookups happen
    BEFORE the frame stream starts (``execute_stream`` contract, steemer/db.py).

Usage (inside the session; reaper_db.toml syncs in as a git-ignored file):
    uv run --group train python tools/extract_features.py \
        --db reaper_db.toml --out $REAPER_CACHE_FEAT/v1 \
        --summary $REAPER_OUT/extract_summary.json --runs latest:40
    # one-off, before first extraction:
    uv run --group train python tools/extract_features.py \
        --db reaper_db.toml --build-profiles 150-165 --out models
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steemer import db, mlfeat, protocol  # noqa: E402
from steemer.strategy.explorer import THREAT_KINDS, WILDLIFE_SAFE  # noqa: E402

K_HORIZONS = (10, 15, 30)          # death-label windows; 15 is the primary (postmortem window)
STINT_END_WINDOW = 15              # ticks-before-stint-end kept unsampled (the minority class)
INCOME_H = 30                      # pickup-within horizon
NEG_KEEP_1_IN = 5                  # negatives kept 1-in-5, weight 5.0 (positives all kept)
MOB_PAIR_MAX_GAP = 3               # matches mob_predict.evaluate's pairing rule


def _decode(raw):
    raw = raw.encode("latin-1") if isinstance(raw, str) else raw
    return protocol.decode(raw)


def _is_melee_predator(kind: str) -> bool:
    """The explorer's rule, restated: hostile, not undead, not passive wildlife."""
    return kind not in THREAT_KINDS and kind not in WILDLIFE_SAFE


def _keep_negative(uid: str, tick: int) -> bool:
    """Deterministic 1-in-N sampling — hash, not random, so extraction is replayable."""
    h = hashlib.blake2s(f"{uid}:{tick}".encode(), digest_size=4).digest()
    return int.from_bytes(h, "big") % NEG_KEEP_1_IN == 0


def our_guild_id(conn) -> str:
    from steemer import attribution
    g = attribution.our_guild_id(conn)
    if not g:
        raise SystemExit("cannot derive our guild id — refusing to extract unattributed")
    return g


def death_index(conn, run_id: int, guild: str) -> dict[str, list[int]]:
    idx: dict[str, list[int]] = {}
    for row in conn.execute(
            "SELECT tick, payload_json FROM events WHERE run_id=? AND kind='death'",
            (run_id,)).fetchall():
        d = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str) \
            else row["payload_json"]
        if d.get("guild_id") == guild and d.get("char_uid"):
            idx.setdefault(d["char_uid"], []).append(row["tick"])
    return idx


GAP_BUCKETS = ((50, "0-50"), (200, "51-200"), (1000, "201-1000"))


def _gap_bucket(gap: int) -> str:
    for edge, name in GAP_BUCKETS:
        if gap <= edge:
            return name
    return "1000+"


def band_inputs(nframe, next_refresh_in) -> dict:
    mobs = nframe["mobs"]
    undead = sum(1 for m in mobs if m["kind"] in THREAT_KINDS)
    melee = sum(1 for m in mobs if _is_melee_predator(m["kind"]))
    return {"next_refresh_in": next_refresh_in,
            "undead_frac": (undead / len(mobs)) if mobs else 0.0,
            "melee_preds": float(melee)}


class RunExtractor:
    """Pure-ish core: consumes decoded frames in order, emits example rows.

    DB-free by design (frames arrive as dicts) so the whole labelling path is
    unit-testable — and cross-checkable against postmortem.reconstruct_trace, the
    independent implementation of "what did this character's last ticks look like"."""

    def __init__(self, run_id: int, deaths: dict[str, list[int]], profiles: dict,
                 movefails: set | None = None, pickups: dict | None = None):
        self.run_id = run_id
        self.deaths = deaths
        self.profiles = profiles
        self.movefails = movefails or set()      # {(eid, tick)} — server-confirmed bounces
        self.pickups = pickups or {}             # eid -> sorted [ticks] of pickup/gold events
        self.rows = {"death": [], "mob": [], "band_raw": [],
                     "movefail": [], "stint_buf": [], "income_buf": []}
        self._last_mob: dict[int, tuple[int, tuple, tuple | None]] = {}
        self._prev: dict[str, tuple] = {}        # uid -> (tick, pos, eid, feats)
        self._stint: dict[str, list] = {}        # uid -> [start_tick, last_tick]
        self._stint_ends: dict[str, list[int]] = {}
        self._seen_tiles: set = set()
        self._dmg: dict[str, list] = {}          # kind -> [(drop, elite)]
        self._chp: dict[str, tuple] = {}         # uid -> (hp, adjacent-hostiles snapshot)
        self._tile_kind: dict[tuple, tuple] = {} # (w,x,y) -> (kind, tick) last sighting
        # regrowth hazard needs BOTH numerator and denominator: flips walkable->solid,
        # over all revisits of a remembered-walkable tile, bucketed by sighting gap
        self.regrowth: dict[str, dict] = {"revisit": {}, "flip": {}}
        self.regrowth_flips: list[dict] = []
        self.counts = {"death_pos": 0, "death_neg": 0, "mob": 0, "movefail": 0,
                       "stint": 0, "income": 0, "dmg_samples": 0, "flips": 0}

    def feed(self, decoded: dict) -> None:
        if decoded.get("world") == "village":
            return
        nframe = mlfeat.normalize_frame(decoded)
        tick = nframe["tick"]
        world = nframe["world"]
        # --- tile bookkeeping: freshness for movefail, kind flips for regrowth ---
        for t in (decoded.get("visible") or {}).get("tiles") or []:
            key = (world, t[0], t[1])
            prev = self._tile_kind.get(key)
            if prev is not None:
                gap = tick - prev[1]
                was_walkable = prev[0] not in ("wall", "water", "tree", "bush", "rock",
                                               "vein", "fence", "chest", "chest_open")
                if was_walkable and gap > 0:
                    b = _gap_bucket(gap)
                    self.regrowth["revisit"][b] = self.regrowth["revisit"].get(b, 0) + 1
                    now_solid = t[2] in ("tree", "bush", "rock", "vein", "wall", "water")
                    if prev[0] != t[2] and now_solid:
                        self.regrowth["flip"][b] = self.regrowth["flip"].get(b, 0) + 1
                        self.regrowth_flips.append({"kind": t[2], "gap": gap})
                        self.counts["flips"] += 1
            self._tile_kind[key] = (t[2], tick)
            self._seen_tiles.add(key)
        nr = (decoded.get("next_refresh") or {}).get("in_ticks")
        band = band_inputs(nframe, nr)
        self.rows["band_raw"].append(
            (tick, nframe["world"], band["undead_frac"], band["melee_preds"], nr))
        # --- death-risk rows ---
        for ch in nframe["chars"]:
            labels = {f"y{k}": mlfeat.death_label(ch["uid"], tick, self.deaths, k)
                      for k in K_HORIZONS}
            positive = any(labels.values())
            if not positive and not _keep_negative(ch["uid"], tick):
                continue
            feats = mlfeat.death_risk_features(ch, nframe, self.profiles, band)
            self.rows["death"].append({
                "uid": ch["uid"], "tick": tick, "f": feats, **labels,
                "w": 1.0 if positive else float(NEG_KEEP_1_IN)})
            self.counts["death_pos" if positive else "death_neg"] += 1
        # --- batch 2: stints, move-fail, income, damage samples ---
        items = {tuple(i["pos"]) for i in (decoded.get("visible") or {}).get("items") or []
                 if i.get("pos")}
        gold = {tuple(g["pos"]) for g in (decoded.get("visible") or {}).get("gold") or []
                if g.get("pos")}
        chests = {k[1:] for k, v in self._tile_kind.items()
                  if k[0] == world and v[0] == "chest"}
        eid_by_uid = {c.get("char_uid"): c.get("eid")
                      for c in decoded.get("chars") or [] if c.get("char_uid")}
        nr = (decoded.get("next_refresh") or {}).get("in_ticks")
        band2 = band_inputs(nframe, nr)
        for ch in nframe["chars"]:
            uid = ch["uid"]
            st = self._stint.get(uid)
            if st is None or tick - st[1] > 1:
                if st is not None:
                    self._stint_ends.setdefault(uid, []).append(st[1])
                st = self._stint[uid] = [tick, tick]
            st[1] = tick
            stint_age = tick - st[0]
            # stint rows: UNIFORM 1-in-5 sample (both classes alike, weight 1.0 —
            # with median stints of 10-12 ticks neither label is safely "the minority",
            # so no class-asymmetric downsampling; labelled at finalize)
            if _keep_negative(uid, tick):
                self.rows["stint_buf"].append(
                    {"uid": uid, "tick": tick,
                     "f": mlfeat.stint_features(ch, nframe, self.profiles, band2,
                                                stint_age)})
            # income rows: buffered, labelled at finalize from the pickup index
            if _keep_negative(uid, tick):
                self.rows["income_buf"].append(
                    {"uid": uid, "eid": eid_by_uid.get(uid), "tick": tick,
                     "f": mlfeat.income_features(
                         ch, nframe, items, gold, chests,
                         len(items) / 500.0,       # frame-wide item density, normalised
                         nr if isinstance(nr, int) else 0)})
            # move-fail rows: label from the PREVIOUS tick's attempt outcome
            prev = self._prev.get(uid)
            if prev is not None and tick - prev[0] == 1:
                ptick, ppos, peid, pfeats = prev
                # a bounce may be stamped on the attempt tick or the processing tick;
                # accept either, but CONSUME the event so one bounce can never label
                # two consecutive attempts (the first draft double-counted here)
                key = (peid, tick) if (peid, tick) in self.movefails else                     ((peid, ptick) if (peid, ptick) in self.movefails else None)
                bounced = key is not None
                if key is not None:
                    self.movefails.discard(key)
                moved = tuple(ch["pos"]) != ppos
                if bounced or moved:
                    self.rows["movefail"].append(
                        {"uid": uid, "tick": ptick, "f": pfeats,
                         "y": 1 if bounced else 0})
                    self.counts["movefail"] += 1
            fresh = (world, ch["pos"][0], ch["pos"][1]) in self._seen_tiles
            self._prev[uid] = (tick, tuple(ch["pos"]), eid_by_uid.get(uid),
                               mlfeat.movefail_features(ch, nframe, fresh))
            # damage attribution (bestiary's clean-single-adjacent rule, distributions)
            prev_hp = self._chp.get(uid)
            adj = [m for m in nframe["mobs"]
                   if abs(m["pos"][0] - ch["pos"][0]) + abs(m["pos"][1] - ch["pos"][1]) <= 1]
            if prev_hp is not None and ch.get("hp") is not None                     and prev_hp[0] is not None and ch["hp"] < prev_hp[0]                     and len(prev_hp[1]) == 1:
                kind, elite = prev_hp[1][0]
                self._dmg.setdefault(kind, []).append(
                    (prev_hp[0] - ch["hp"], elite))
                self.counts["dmg_samples"] += 1
            self._chp[uid] = (ch.get("hp"), [(m["kind"], bool(m.get("elite")))
                                             for m in adj])
        # --- mob-move rows (consecutive-observation pairing, gap <= 3) ---
        for m in nframe["mobs"]:
            prev = self._last_mob.get(m["eid"])
            here_chars = nframe["chars"]
            nearest = min(here_chars, key=lambda c: mlfeat._manhattan(m["pos"], c["pos"])) \
                if here_chars else None
            if prev is not None:
                ptick, ppos, pfeats_ctx = prev
                if 0 < tick - ptick <= MOB_PAIR_MAX_GAP and pfeats_ctx is not None:
                    pfeats, pnearest = pfeats_ctx
                    label = mlfeat.mob_move_class(ppos, m["pos"], pnearest)
                    self.rows["mob"].append({"eid": m["eid"], "kind": m["kind"],
                                             "tick": ptick, "f": pfeats, "y": label})
                    self.counts["mob"] += 1
            ctx = None
            if nearest is not None:
                ctx = (mlfeat.mob_features(m, nframe, self.profiles.get(m["kind"]) or {}),
                       nearest["pos"])
            self._last_mob[m["eid"]] = (tick, m["pos"], ctx)

    def finalize_batch2(self) -> dict:
        """Label the buffered rows now the run's full timeline is known, and build the
        two aggregation tables."""
        # close open stints at their last-seen tick
        for uid, st in self._stint.items():
            self._stint_ends.setdefault(uid, []).append(st[1])
        stint_rows = []
        for r in self.rows["stint_buf"]:
            ends = self._stint_ends.get(r["uid"], [])
            end = min((e for e in ends if e >= r["tick"]), default=None)
            if end is None:
                continue
            y = 1 if (end - r["tick"]) >= mlfeat.STINT_HORIZON else 0
            stint_rows.append({"uid": r["uid"], "tick": r["tick"], "f": r["f"], "y": y})
        self.counts["stint"] = len(stint_rows)
        income_rows = []
        for r in self.rows["income_buf"]:
            ticks = self.pickups.get(r["eid"], [])
            y = 1 if any(r["tick"] < t <= r["tick"] + INCOME_H for t in ticks) else 0
            income_rows.append({"uid": r["uid"], "tick": r["tick"], "f": r["f"], "y": y})
        self.counts["income"] = len(income_rows)
        # RAW damage samples per kind — quantiles are computed by the TRAINER after
        # merging runs (per-run quantiles cannot be merged; that was the first draft's
        # mistake). Same for regrowth: raw bucket counts, hazard computed downstream.
        dmg = [{"kind": k, "drop": d, "elite": e}
               for k, samples in self._dmg.items() for d, e in samples]
        return {"stint": stint_rows, "income": income_rows, "dmg": dmg,
                "regrowth": self.regrowth}

    def band_rows(self) -> list[dict]:
        """Post-pass: segment the run's per-frame band inputs at refresh boundaries
        (next_refresh_in jumping UP starts a new cycle), classify each segment, and emit
        one example per transition with the previous four classes as history."""
        out = []
        segs: dict[str, list[list]] = {}
        for tick, world, uf, mp, nr in self.rows["band_raw"]:
            ws = segs.setdefault(world, [])
            if not ws or (nr is not None and ws[-1][-1] is not None
                          and nr > ws[-1][-1] + 1):
                ws.append([tick, [], [], nr])
            seg = ws[-1]
            seg[1].append(uf); seg[2].append(mp); seg[3] = nr
        for world, ws in segs.items():
            classes = [mlfeat.band_danger_class(sum(s[1]) / len(s[1]),
                                                sum(s[2]) / len(s[2]))
                       for s in ws if s[1]]
            for i in range(1, len(classes)):
                hist = list(reversed(classes[max(0, i - 4):i]))
                out.append({"world": world, "run": self.run_id,
                            "f": mlfeat.band_features(world, hist, 0),
                            "y": classes[i]})
        return out


def _cache_valid(marker: str, conn, rid: int) -> bool:
    """A cached extraction is trusted only if its header's frame count still matches the
    DB — a file cached while the run was live (before the closed-runs-only rule) is a
    partial that must self-heal, not a fact."""
    try:
        with gzip.open(marker, "rt", encoding="utf-8") as fh:
            header = json.loads(fh.readline())
        n = conn.execute("SELECT COUNT(*) FROM frames WHERE run_id=?", (rid,)).fetchone()[0]
        return header.get("frames") == n and             header.get("schema_version") == mlfeat.FEATURE_SCHEMA_VERSION
    except Exception:
        return False


def write_rows(path: str, header: dict, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps(header) + "\n")
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def pick_runs(conn, spec: str) -> list[int]:
    """CLOSED runs only. Run #178 was live during the first full extraction and grew a
    death between the index read and the gate check — a moving denominator, the same
    mid-run-measurement lesson the claims ledger already taught (iter 95). A live run is
    not yet a fact."""
    all_runs = [r["run_id"] for r in conn.execute(
        "SELECT DISTINCT f.run_id FROM frames f JOIN runs r ON r.run_id = f.run_id "
        "WHERE r.stopped_at IS NOT NULL ORDER BY f.run_id").fetchall()]
    if spec == "all":
        return all_runs
    if spec.startswith("latest:"):
        return all_runs[-int(spec.split(":")[1]):]
    if "-" in spec:
        lo, hi = (int(x) for x in spec.split("-"))
        return [r for r in all_runs if lo <= r <= hi]
    return [int(spec)]


def build_profiles(conn, spec: str, out_dir: str) -> str:
    """Freeze the bestiary over the given runs into models/bestiary_snapshot.json —
    the SAME table training features and live scoring must both read."""
    from steemer import bestiary
    frames = []
    for rid in pick_runs(conn, spec):
        for row in conn.execute(
                "SELECT json FROM frames WHERE run_id=? AND world<>'village' "
                "ORDER BY seq ASC", (rid,)).fetchall():
            try:
                frames.append(bestiary.normalize_frame(_decode(row["json"])))
            except Exception:
                continue
    kinds = bestiary.build_bestiary(frames)
    snap = {k: {"move_rate": v.get("move_rate") or 0.0,
                "chaser_score": v.get("chaser_score") or 0.0,
                "dph": v.get("est_dmg_per_hit") or 0.0,
                "hit_rate": v.get("hit_rate") or 0.0,
                "behavior": v.get("behavior") or "insufficient_data"}
            for k, v in kinds.items()}
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "bestiary_snapshot.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"schema_version": mlfeat.FEATURE_SCHEMA_VERSION,
                   "profile_runs": spec, "git_sha": git_sha(), "kinds": snap}, fh, indent=1)
    print(f"[profiles] {len(snap)} kinds -> {path}")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="reaper_db.toml")
    ap.add_argument("--out", default="out/features")
    ap.add_argument("--summary")
    ap.add_argument("--runs", default="latest:40")
    ap.add_argument("--profiles", default="models/bestiary_snapshot.json")
    ap.add_argument("--build-profiles", dest="build_profiles")
    a = ap.parse_args(argv)

    cfg = db.load_db_config(a.db)
    conn = db.connect(cfg, readonly=True)
    if a.build_profiles:
        build_profiles(conn, a.build_profiles, a.out)
        return 0

    with open(a.profiles, encoding="utf-8") as fh:
        snap = json.load(fh)
    if snap.get("schema_version") != mlfeat.FEATURE_SCHEMA_VERSION:
        raise SystemExit("bestiary snapshot schema mismatch — rebuild profiles")
    profiles = snap["kinds"]
    guild = our_guild_id(conn)
    summary = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "git_sha": git_sha(),
               "guild": guild, "runs": {}}
    for rid in pick_runs(conn, a.runs):
        # the aggr file is written LAST, so it doubles as the completion marker: a
        # batch-1 cache (death/band/mob only) fails this check and re-extracts to gain
        # the batch-2 row files rather than silently starving those trainers
        marker = os.path.join(a.out, f"run_{rid:04d}.death.jsonl.gz")
        aggr_marker = os.path.join(a.out, f"run_{rid:04d}.aggr.jsonl.gz")
        if all(os.path.exists(m) and _cache_valid(m, conn, rid)
               for m in (marker, aggr_marker)):
            summary["runs"][rid] = {"cached": True}
            continue
        deaths = death_index(conn, rid, guild)          # BEFORE the stream: one conn rule
        movefails = set()
        for row in conn.execute(
                "SELECT tick, payload_json FROM events WHERE run_id=? AND kind='move_failed'",
                (rid,)).fetchall():
            d = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str)                 else row["payload_json"]
            if d.get("eid") is not None:
                movefails.add((d["eid"], row["tick"]))
        pickups: dict[int, list[int]] = {}
        for row in conn.execute(
                "SELECT tick, payload_json FROM events WHERE run_id=? "
                "AND kind IN ('pickup','gold')", (rid,)).fetchall():
            d = json.loads(row["payload_json"]) if isinstance(row["payload_json"], str)                 else row["payload_json"]
            if d.get("eid") is not None:
                pickups.setdefault(d["eid"], []).append(row["tick"])
        for v in pickups.values():
            v.sort()
        ex = RunExtractor(rid, deaths, profiles, movefails=movefails, pickups=pickups)
        n_frames = 0
        for row in conn.execute_stream(
                "SELECT tick, json FROM frames WHERE run_id=? ORDER BY seq ASC", (rid,)):
            try:
                ex.feed(_decode(row["json"]))
                n_frames += 1
            except Exception:
                continue
        header = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "run_id": rid,
                  "git_sha": git_sha(), "frames": n_frames}
        write_rows(marker, header, ex.rows["death"])
        write_rows(os.path.join(a.out, f"run_{rid:04d}.mob.jsonl.gz"),
                   header, ex.rows["mob"])
        write_rows(os.path.join(a.out, f"run_{rid:04d}.band.jsonl.gz"),
                   header, ex.band_rows())
        b2 = ex.finalize_batch2()
        write_rows(os.path.join(a.out, f"run_{rid:04d}.stint.jsonl.gz"),
                   header, b2["stint"])
        write_rows(os.path.join(a.out, f"run_{rid:04d}.movefail.jsonl.gz"),
                   header, ex.rows["movefail"])
        write_rows(os.path.join(a.out, f"run_{rid:04d}.income.jsonl.gz"),
                   header, b2["income"])
        write_rows(os.path.join(a.out, f"run_{rid:04d}.aggr.jsonl.gz"),
                   header, [{"dmg": b2["dmg"], "regrowth": b2["regrowth"]}])
        summary["runs"][rid] = {
            "frames": n_frames,
            "death_events_ours": sum(len(v) for v in deaths.values()),
            "death_rows_pos": ex.counts["death_pos"],
            "death_rows_neg": ex.counts["death_neg"],
            "mob_pairs": ex.counts["mob"],
            "stint_rows": ex.counts["stint"], "movefail_rows": ex.counts["movefail"],
            "income_rows": ex.counts["income"], "dmg_samples": ex.counts["dmg_samples"],
            "regrowth_flips": ex.counts["flips"],
        }
        print(f"[extract] run {rid}: {summary['runs'][rid]}")
    if a.summary:
        os.makedirs(os.path.dirname(a.summary) or ".", exist_ok=True)
        with open(a.summary, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
