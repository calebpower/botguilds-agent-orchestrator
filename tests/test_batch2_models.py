"""Batch 2 (operator-picked): stint survival, move-fail, income spot, dph table,
regrowth hazard — label boundaries, attribution rules, floors, and reachability.

Horizon literals (15, 30) and the shadow cadence (5) are DUPLICATED here as literals and
pinned — the hygiene ratchet forbids sizing fixtures from the constants under test.
"""
import gzip
import json
import math
import os
import time

import pytest

from tools.extract_features import RunExtractor, _keep_negative, _gap_bucket
from tools.train_models import build_tables
from steemer import mlfeat, models

STINT_H = 15
INCOME_W = 30
CADENCE = 5


def test_the_pinned_literals_still_match():
    from tools import extract_features as ef
    from steemer.bot import SHADOW_EVERY
    assert mlfeat.STINT_HORIZON == STINT_H
    assert ef.INCOME_H == INCOME_W
    assert SHADOW_EVERY == CADENCE


def _frame(tick, chars=(), mobs=(), tiles=(), items=(), world="vale"):
    return {"world": world, "tick": tick,
            "chars": [{"char_uid": u, "eid": e, "pos": list(p), "hp": hp, "max_hp": 30,
                       "stamina": 30, "max_stamina": 60, "level": 2, "stats": {},
                       "carry": {"used": 0, "cap": 20}, "inventory": [], "statuses": []}
                      for u, e, p, hp in chars],
            "visible": {"entities": [{"eid": e, "kind": k, "pos": list(p),
                                      "faction": "monster"} for e, k, p in mobs],
                        "tiles": [list(t) for t in tiles],
                        "items": [{"pos": list(p)} for p in items], "gold": []},
            "next_refresh": {"in_ticks": 500}}


def _kept_tick(uid, lo=5, hi=3000):
    for t in range(lo, hi):
        if _keep_negative(uid, t):
            return t
    raise AssertionError("no sampled tick in range")


# ---------------------------------------------------------------------------
# stint labels
# ---------------------------------------------------------------------------

def _stint_rows(end_tick):
    """One char fielded contiguously from 0 to end_tick, then gone (run ends)."""
    ex = RunExtractor(1, {}, {})
    for t in range(0, end_tick + 1):
        ex.feed(_frame(t, chars=[("c1", 7, (3, 3), 20)]))
    return {r["tick"]: r for r in ex.finalize_batch2()["stint"]}


def test_stint_label_boundary_is_at_exactly_the_horizon():
    """y=1 iff the stint survives >= 15 MORE ticks. Same sampled tick, two runs whose
    only difference is one tick of stint length — the label must flip. Kills `>` vs
    `>=` at the boundary AND any off-by-one in stint-end bookkeeping."""
    t0 = _kept_tick("c1")
    at_horizon = _stint_rows(t0 + STINT_H)
    one_short = _stint_rows(t0 + STINT_H - 1)
    assert at_horizon[t0]["y"] == 1, "survives exactly 15 more -> must label 1"
    assert one_short[t0]["y"] == 0, "survives 14 more -> must label 0"


def test_a_village_gap_starts_a_new_stint():
    """The char vanishes for 10 ticks (village trip): stint_age must RESET, not span
    the gap. Read back through the recorded feature, not the internals."""
    uid = "c1"
    ex = RunExtractor(1, {}, {})
    for t in range(0, 40):
        ex.feed(_frame(t, chars=[(uid, 7, (3, 3), 20)]))
    for t in range(50, 90):
        ex.feed(_frame(t, chars=[(uid, 7, (3, 3), 20)]))
    rows = ex.finalize_batch2()["stint"]
    after_gap = [r for r in rows if 50 <= r["tick"] < 90]
    assert after_gap, "sampling left no row in the second stint"
    for r in after_gap:
        assert r["f"]["stint_age"] == r["tick"] - 50, \
            f"stint_age spans the village gap at tick {r['tick']}"


# ---------------------------------------------------------------------------
# move-fail labels
# ---------------------------------------------------------------------------

def test_movefail_labels_bounce_move_and_silence():
    """Three consecutive outcomes for one char: a successful move (y=0), a
    server-confirmed bounce (y=1), and a stationary tick with no bounce event
    (NO row — resting is not a failed move)."""
    ex = RunExtractor(1, {}, {}, movefails={(7, 12)})
    ex.feed(_frame(10, chars=[("c1", 7, (3, 3), 20)]))
    ex.feed(_frame(11, chars=[("c1", 7, (3, 4), 20)]))   # moved -> row(t=10, y=0)
    ex.feed(_frame(12, chars=[("c1", 7, (3, 4), 20)]))   # bounced -> row(t=11, y=1)
    ex.feed(_frame(13, chars=[("c1", 7, (3, 4), 20)]))   # still, no event -> no row
    rows = {r["tick"]: r["y"] for r in ex.rows["movefail"]}
    assert rows == {10: 0, 11: 1}, rows


def test_movefail_features_come_from_the_state_BEFORE_the_attempt():
    """The row for tick t must carry tick-t features (decision-time), not the
    post-move state — assert via depth_y, which changes with the move itself."""
    ex = RunExtractor(1, {}, {})
    ex.feed(_frame(10, chars=[("c1", 7, (3, 3), 20)]))
    ex.feed(_frame(11, chars=[("c1", 7, (3, 9), 20)]))
    (row,) = ex.rows["movefail"]
    assert row["f"]["depth_y"] == 3.0, "features leaked from after the move"


# ---------------------------------------------------------------------------
# income labels
# ---------------------------------------------------------------------------

def test_income_label_window_boundary():
    """A pickup at t+30 counts; at t+31 it does not. Kills `<=` vs `<` on the
    window's far edge (the label is (t, t+30], mirroring the death-window pin)."""
    t0 = _kept_tick("c1")
    def rows_with_pickup_at(dt):
        ex = RunExtractor(1, {}, {}, pickups={7: [t0 + dt]})
        for t in range(0, t0 + dt + 2):
            ex.feed(_frame(t, chars=[("c1", 7, (3, 3), 20)]))
        return {r["tick"]: r for r in ex.finalize_batch2()["income"]}
    assert rows_with_pickup_at(INCOME_W)[t0]["y"] == 1
    assert rows_with_pickup_at(INCOME_W + 1)[t0]["y"] == 0


# ---------------------------------------------------------------------------
# dph attribution
# ---------------------------------------------------------------------------

def test_dph_samples_only_on_a_CLEAN_single_adjacent_hit():
    """hp drops by 5 with exactly one adjacent wolf -> one (wolf, 5) sample; the same
    drop with TWO adjacent kinds is unattributable and must record NOTHING."""
    ex = RunExtractor(1, {}, {})
    ex.feed(_frame(10, chars=[("c1", 7, (3, 3), 20)], mobs=[(90, "wolf", (3, 4))]))
    ex.feed(_frame(11, chars=[("c1", 7, (3, 3), 15)], mobs=[(90, "wolf", (3, 4))]))
    assert ex.counts["dmg_samples"] == 1
    (sample,) = ex.finalize_batch2()["dmg"]
    assert (sample["kind"], sample["drop"]) == ("wolf", 5)
    ex2 = RunExtractor(1, {}, {})
    ex2.feed(_frame(10, chars=[("c1", 7, (3, 3), 20)],
                    mobs=[(90, "wolf", (3, 4)), (91, "bat", (4, 3))]))
    ex2.feed(_frame(11, chars=[("c1", 7, (3, 3), 15)],
                    mobs=[(90, "wolf", (3, 4)), (91, "bat", (4, 3))]))
    assert ex2.counts["dmg_samples"] == 0, "ambiguous hit was attributed anyway"


# ---------------------------------------------------------------------------
# regrowth hazard bookkeeping
# ---------------------------------------------------------------------------

def test_regrowth_counts_exposure_and_flips_separately():
    """A remembered-FLOOR tile revisited as floor is exposure without a flip; revisited
    as tree it is exposure AND a flip; a remembered-TREE tile contributes neither.
    Without the denominator the table is a flip count, not a hazard — that was the
    first draft's defect, so the denominator is the thing this test pins."""
    ex = RunExtractor(1, {}, {})
    ex.feed(_frame(0, tiles=[(1, 1, "floor", 0, 0), (2, 2, "floor", 0, 0),
                             (3, 3, "tree", 0, 0)]))
    ex.feed(_frame(10, tiles=[(1, 1, "floor", 0, 0), (2, 2, "tree", 0, 0),
                              (3, 3, "floor", 0, 0)]))
    rg = ex.finalize_batch2()["regrowth"]
    assert rg["revisit"] == {"0-50": 2}, rg
    assert rg["flip"] == {"0-50": 1}, rg


def test_gap_buckets_cover_the_line():
    assert [_gap_bucket(g) for g in (1, 50, 51, 200, 201, 1000, 1001)] == \
        ["0-50", "0-50", "51-200", "51-200", "201-1000", "201-1000", "1000+"]


# ---------------------------------------------------------------------------
# table building (sklearn-free) — floors and hazard math
# ---------------------------------------------------------------------------

def _write_aggr(dirpath, rid, dmg, regrowth):
    path = os.path.join(dirpath, f"run_{rid:04d}.aggr.jsonl.gz")
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"run_id": rid,
                             "schema_version": mlfeat.FEATURE_SCHEMA_VERSION,
                             "frames": 1}) + "\n")
        fh.write(json.dumps({"dmg": dmg, "regrowth": regrowth}) + "\n")


def test_build_tables_merges_runs_and_honours_the_floors(tmp_path):
    """20 wolf samples in each of two runs merge to 40 (over the 30 floor) while 10 bat
    samples stay under it; a 100-revisit bucket is refused while 250 passes with the
    exact flips/revisits ratio. Merging ACROSS runs is the point — per-run the wolf
    would have been dropped too."""
    feat, out = str(tmp_path / "f"), str(tmp_path / "m")
    os.makedirs(feat)
    wolf = [{"kind": "wolf", "drop": d % 7 + 1, "elite": False} for d in range(20)]
    bat = [{"kind": "bat", "drop": 2, "elite": False} for _ in range(10)]
    _write_aggr(feat, 1, wolf + bat, {"revisit": {"0-50": 150}, "flip": {"0-50": 15}})
    _write_aggr(feat, 2, wolf, {"revisit": {"0-50": 100, "51-200": 100},
                                "flip": {"0-50": 10}})
    res = build_tables(feat, out)
    with open(os.path.join(out, "dph_profile.json")) as fh:
        dph = json.load(fh)
    assert set(dph["kinds"]) == {"wolf"}, "the per-kind floor failed across runs"
    assert dph["kinds"]["wolf"]["n"] == 40
    with open(os.path.join(out, "terrain_regrowth.json")) as fh:
        rg = json.load(fh)
    assert set(rg["buckets"]) == {"0-50"}, "an under-floor bucket was published"
    assert rg["buckets"]["0-50"] == {"revisits": 250, "flips": 25, "p_flip": 0.1}
    assert res["dph_profile"]["accepted"] and res["terrain_regrowth"]["accepted"]


# ---------------------------------------------------------------------------
# scorer + table loader
# ---------------------------------------------------------------------------

@pytest.fixture()
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MODELS_DIR", str(tmp_path))
    models.reset_cache()
    yield tmp_path
    models.reset_cache()


def _deploy(mdir, name, model):
    with open(os.path.join(mdir, f"{name}.json"), "w") as fh:
        json.dump({"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, **model}, fh)
    with open(os.path.join(mdir, f"{name}.meta.json"), "w") as fh:
        json.dump({"trained_at_epoch": time.time()}, fh)


def _stint_tree(threshold=10.0):
    return {"model": "gbm_binary", "feature_names": list(mlfeat.STINT_FEATURES),
            "base_score": 0.0,
            "trees": [{"f": list(mlfeat.STINT_FEATURES).index("stint_age"),
                       "t": threshold, "l": {"v": 2.0}, "r": {"v": -2.0}}]}


def test_score_stint_walks_its_artifact(mdir):
    _deploy(mdir, "stint_survival", _stint_tree())
    f = {k: 0.0 for k in mlfeat.STINT_FEATURES}
    lo = models.score_stint({**f, "stint_age": 3.0})
    hi_age = models.score_stint({**f, "stint_age": 30.0})
    assert abs(lo - 1 / (1 + math.exp(-2))) < 1e-9
    assert abs(hi_age - 1 / (1 + math.exp(2))) < 1e-9


def test_load_table_accepts_tables_and_refuses_everything_else(mdir):
    _deploy(mdir, "dph_profile", {"model": "table", "kinds": {"wolf": {"p50": 4}}})
    _deploy(mdir, "stint_survival", _stint_tree())
    t = models.load_table("dph_profile")
    assert t and t["kinds"]["wolf"]["p50"] == 4
    assert models.load_table("stint_survival") is None, \
        "a GBM artifact leaked through the table loader"
    assert models.load_table("no_such_table") is None


# ---------------------------------------------------------------------------
# shadow reachability: stint scores flow WITHOUT a death-risk artifact deployed
# ---------------------------------------------------------------------------

def _bot(storage=None):
    from steemer.bot import GuildBot
    b = GuildBot(strategy="explorer", storage=storage)
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    return b


def _bot_frame(tick):
    tiles = [[x, y, "floor", 0, 0] for x in range(5) for y in range(5)]
    return {"world": "vale", "tick": tick, "events": [],
            "chars": [{"char_uid": "c1", "eid": 7, "pos": [2, 2], "hp": 30,
                       "max_hp": 30, "stamina": 40, "max_stamina": 56, "level": 3,
                       "stats": {}, "gifts": [], "statuses": [], "spells": [],
                       "carry": {"used": 0, "cap": 20}, "inventory": [],
                       "equipment": {"hand": {"kind": "club"}}}],
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def test_stint_shadow_reaches_intel_and_the_age_actually_advances(mdir, tmp_path):
    """death_risk stays ABSENT (as live today, where it was rejected): stint scores must
    still flow. And the LAST score must reflect a grown stint_age crossing the tree's
    threshold — if the bot's stint bookkeeping is broken (age stuck at 0) every score
    stays on the young side and this fails."""
    from steemer.storage import Storage
    _deploy(mdir, "stint_survival", _stint_tree(threshold=10.0))
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("sha", "test/0")
    bot = _bot(storage=st)
    for t in range(500, 516):          # ages 0..15; cadence 5 -> scored at 500/505/510/515
        bot.tick = t
        bot.on_frame(_bot_frame(t))
    st.conn.commit()
    rows = [json.loads(r[0]) for r in st.conn.execute(
        "SELECT payload_json FROM intel WHERE kind='model_score' ORDER BY seq").fetchall()]
    stint_rows = [r for r in rows if r["model"] == "stint_survival"]
    assert stint_rows, "no stint score reached intel without a death_risk artifact"
    young = 1 / (1 + math.exp(-2))
    old = 1 / (1 + math.exp(2))
    assert abs(stint_rows[0]["scores"]["c1"] - round(young, 4)) < 1e-6
    assert abs(stint_rows[-1]["scores"]["c1"] - round(old, 4)) < 1e-6, \
        f"stint_age never crossed the threshold: {stint_rows}"
