"""The extractor's honesty (ML Pass 1): guild filtering, sampling, and the cross-oracle.

The RunExtractor core is deliberately DB-free (frames arrive as dicts), so everything
about labelling is testable here — and the one thing that cannot be faked, agreement
with `postmortem.reconstruct_trace` on real recorded deaths, runs as a gate-only
cross-check against the live corpus (skips where the DB credential file is absent,
exactly like the reaper connectivity canary).
"""
import json
import os

import pytest

from tools.extract_features import (RunExtractor, death_index, band_inputs,
                                    NEG_KEEP_1_IN, _keep_negative)
from steemer import mlfeat


class _Conn:
    """Rows for death_index, shaped like steemer.db rows."""
    def __init__(self, rows):
        self._rows = rows
    def execute(self, sql, params=()):
        return self
    def fetchall(self):
        return self._rows


def _ev(tick, char_uid, guild):
    return {"tick": tick,
            "payload_json": json.dumps({"kind": "death", "char_uid": char_uid,
                                        "guild_id": guild})}


def test_the_death_index_keeps_ONLY_our_guild():
    """The events stream is world-wide, and 'death queries count rivals' is a documented
    historical attribution error. Feed a mixed stream: rival deaths must vanish. The
    self-test of the oracle: with the filter broken this count EXPLODES (3 vs 1), so the
    assertion cannot pass vacuously."""
    rows = [_ev(10, "g_us_c1", "g_us"),
            _ev(11, "g_them_c9", "g_them"),
            _ev(12, "g_other_c2", "g_other")]
    idx = death_index(_Conn(rows), 1, "g_us")
    assert idx == {"g_us_c1": [10]}
    total = sum(len(v) for v in idx.values())
    assert total == 1, f"guild filter admitted rivals: {idx}"


def _decoded(tick, chars=(), mobs=(), world="vale"):
    return {"world": world, "tick": tick,
            "chars": [{"char_uid": u, "pos": list(p), "hp": 20, "max_hp": 30,
                       "stamina": 30, "max_stamina": 60, "level": 2, "stats": {},
                       "carry": {"used": 0, "cap": 20}, "inventory": [], "statuses": []}
                      for u, p in chars],
            "visible": {"entities": [{"eid": e, "kind": k, "pos": list(p),
                                      "faction": "monster"} for e, k, p in mobs]},
            "next_refresh": {"in_ticks": 500}}


def test_positives_are_never_downsampled():
    """Every tick within K of a death is kept regardless of the 1-in-N hash — losing
    positives to sampling would starve the minority class the model exists to find."""
    deaths = {"g_us_c1": [110]}
    ex = RunExtractor(1, deaths, {})
    for t in range(95, 110):
        ex.feed(_decoded(t, chars=[("g_us_c1", (3, 3))]))
    pos_rows = [r for r in ex.rows["death"] if r["y15"] == 1]
    assert len(pos_rows) == 15, f"positives lost to sampling: {len(pos_rows)}/15"
    assert all(r["w"] == 1.0 for r in pos_rows)


def test_negatives_carry_the_sampling_weight():
    ex = RunExtractor(1, {}, {})
    for t in range(1000):
        ex.feed(_decoded(t, chars=[("g_us_c1", (3, 3))]))
    negs = ex.rows["death"]
    assert 0 < len(negs) < 1000, "sampling did nothing (or ate everything)"
    assert all(r["w"] == float(NEG_KEEP_1_IN) for r in negs)
    # deterministic: same inputs, same kept set
    assert [_keep_negative("g_us_c1", t) for t in range(50)] == \
           [_keep_negative("g_us_c1", t) for t in range(50)]


def test_mob_pairs_respect_the_gap_rule():
    """Pairing follows mob_predict.evaluate's contract (0 < delta <= 3); a re-sighting
    after a longer gap is a NEW track, not a move observation."""
    ex = RunExtractor(1, {}, {"wolf": {"move_rate": 1, "chaser_score": 1,
                                       "dph": 1, "hit_rate": 1, "behavior": "chaser"}})
    ex.feed(_decoded(10, chars=[("g_us_c1", (9, 5))], mobs=[(7, "wolf", (5, 5))]))
    ex.feed(_decoded(11, chars=[("g_us_c1", (9, 5))], mobs=[(7, "wolf", (6, 5))]))
    assert ex.counts["mob"] == 1
    assert ex.rows["mob"][0]["y"] == "toward"
    ex.feed(_decoded(20, chars=[("g_us_c1", (9, 5))], mobs=[(7, "wolf", (9, 9))]))
    assert ex.counts["mob"] == 1, "a 9-tick gap was paired as a move"


def test_village_frames_are_ignored():
    ex = RunExtractor(1, {"g_us_c1": [5]}, {})
    ex.feed(_decoded(4, chars=[("g_us_c1", (3, 3))], world="village"))
    assert not ex.rows["death"]


# ---- the cross-oracle: extractor labels vs postmortem, on the real corpus ------

CREDS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "reaper_db.toml")


@pytest.mark.skipif(not os.path.exists(CREDS), reason="no DB credentials synced")
def test_labels_agree_with_reconstruct_trace_on_real_deaths():
    """Two independent implementations of 'this character was alive at tick T and died
    at tick D': the extractor's preloaded index vs postmortem.reconstruct_trace's frame
    walk. Sampled real deaths from the latest closed run; they agree or the extractor
    is wrong. (Gate + workstation both reach the DB; skips only where the secret is
    absent.)"""
    from steemer import db, postmortem, attribution
    conn = db.connect(db.load_db_config(CREDS), readonly=True)
    guild = attribution.our_guild_id(conn)
    rid = conn.execute(
        "SELECT run_id FROM runs WHERE stopped_at IS NOT NULL "
        "ORDER BY run_id DESC LIMIT 1").fetchone()[0]
    idx = death_index(conn, rid, guild)
    if not idx:
        pytest.skip(f"run {rid} had no deaths of ours")
    checked = 0
    for uid, ticks in list(idx.items())[:5]:
        for dt in ticks[:1]:
            trace = postmortem.reconstruct_trace(conn, rid, uid, dt, window=15)
            for t in trace:
                # every tick postmortem saw the char ALIVE inside the window must be a
                # positive under the same-window label
                if t["tick"] < dt:
                    assert mlfeat.death_label(uid, t["tick"], idx, 15) == 1, \
                        f"{uid}@{t['tick']} (death {dt}) labelled negative"
                    checked += 1
    assert checked > 0, "cross-check matched no ticks — the oracle never fired"


@pytest.mark.skipif(not os.path.exists(CREDS), reason="no DB credentials synced")
def test_pick_runs_refuses_the_LIVE_run():
    """Run #178 grew a death between the extractor's index read and the gate check — a
    moving denominator. Only closed runs are facts; the newest (live) run must be absent
    from every extraction plan."""
    from steemer import db
    from tools.extract_features import pick_runs
    conn = db.connect(db.load_db_config(CREDS), readonly=True)
    live = conn.execute(
        "SELECT run_id FROM runs WHERE stopped_at IS NULL ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    if live is None:
        pytest.skip("no live run right now")
    assert live[0] not in pick_runs(conn, "all"), \
        f"the live run {live[0]} was offered for extraction"


def test_a_stale_partial_cache_is_not_trusted(tmp_path):
    """Run #178 was cached mid-flight (before the closed-runs rule existed): its header
    says N frames while the closed run holds more. _cache_valid must reject it so the
    partial self-heals on the next extraction — and accept the file once counts match."""
    import gzip
    from tools.extract_features import _cache_valid
    from steemer import mlfeat as mf
    marker = tmp_path / "run_0178.death.jsonl.gz"
    with gzip.open(marker, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema_version": mf.FEATURE_SCHEMA_VERSION,
                             "run_id": 178, "frames": 100}) + "\n")

    class _C:
        def __init__(self, n): self.n = n
        def execute(self, sql, params=()): return self
        def fetchone(self): return (self.n,)

    assert _cache_valid(str(marker), _C(100), 178) is True
    assert _cache_valid(str(marker), _C(150), 178) is False, \
        "a partial cache from a then-live run was trusted"
    assert _cache_valid(str(tmp_path / "absent.gz"), _C(100), 178) is False
