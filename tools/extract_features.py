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

    def __init__(self, run_id: int, deaths: dict[str, list[int]], profiles: dict):
        self.run_id = run_id
        self.deaths = deaths
        self.profiles = profiles
        self.rows = {"death": [], "mob": [], "band_raw": []}
        self._last_mob: dict[int, tuple[int, tuple, tuple | None]] = {}
        self.counts = {"death_pos": 0, "death_neg": 0, "mob": 0}

    def feed(self, decoded: dict) -> None:
        if decoded.get("world") == "village":
            return
        nframe = mlfeat.normalize_frame(decoded)
        tick = nframe["tick"]
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
    all_runs = [r["run_id"] for r in conn.execute(
        "SELECT DISTINCT run_id FROM frames ORDER BY run_id").fetchall()]
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
        marker = os.path.join(a.out, f"run_{rid:04d}.death.jsonl.gz")
        if os.path.exists(marker):
            summary["runs"][rid] = {"cached": True}
            continue
        deaths = death_index(conn, rid, guild)          # BEFORE the stream: one conn rule
        ex = RunExtractor(rid, deaths, profiles)
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
        summary["runs"][rid] = {
            "frames": n_frames,
            "death_events_ours": sum(len(v) for v in deaths.values()),
            "death_rows_pos": ex.counts["death_pos"],
            "death_rows_neg": ex.counts["death_neg"],
            "mob_pairs": ex.counts["mob"],
        }
        print(f"[extract] run {rid}: {summary['runs'][rid]}")
    if a.summary:
        os.makedirs(os.path.dirname(a.summary) or ".", exist_ok=True)
        with open(a.summary, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
