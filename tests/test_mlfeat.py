"""The feature/label substrate (ML Pass 1) — purity, boundaries, and honest labels.

mlfeat.py is the single source of truth imported by BOTH the Linux extractor and the
FreeBSD live scorer, so its discipline is the pipeline's discipline: pure stdlib,
deterministic, fixed feature-name tuples, and label semantics pinned at their
boundaries (an off-by-one in the death window silently poisons every model after it).
"""
import math

import pytest

from steemer import mlfeat


# ---- purity ------------------------------------------------------------------

def test_the_module_imports_no_ml_or_io_libraries():
    """The live bot imports this on FreeBSD where numpy/sklearn do not exist, and a DB
    import here would let training-side convenience leak into the scoring path. The
    import list IS the contract."""
    import sys
    banned = {"numpy", "sklearn", "scipy", "pandas"}
    loaded_by_mlfeat = set(vars(mlfeat).keys())
    for mod in banned:
        assert mod not in sys.modules or mod not in str(mlfeat.__dict__), \
            f"{mod} reachable from mlfeat"
    src = open(mlfeat.__file__).read()
    for mod in banned | {"mysql", "sqlite3", "steemer.db"}:
        assert f"import {mod}" not in src, f"mlfeat imports {mod}"


def test_features_are_deterministic():
    ch = _char()
    nf = _frame([ch], [_mob((5, 5))])
    a = mlfeat.death_risk_features(ch, nf, _PROFILES, _BAND)
    b = mlfeat.death_risk_features(ch, nf, _PROFILES, _BAND)
    assert a == b


# ---- fixtures ----------------------------------------------------------------

_PROFILES = {"wolf": {"move_rate": 0.6, "chaser_score": 0.9, "dph": 6.0,
                      "hit_rate": 0.4, "behavior": "chaser"}}
_BAND = {"next_refresh_in": 120, "undead_frac": 0.2, "melee_preds": 3.0}


def _char(pos=(3, 3), hp=20, uid="u1"):
    return {"uid": uid, "pos": pos, "hp": hp, "max_hp": 30, "stamina": 30,
            "max_stamina": 60, "statuses": [], "has_heal": True,
            "carry_used": 5, "carry_cap": 20, "level": 4,
            "stats": {"str": 2, "int": 3, "vit": 2, "end": 2, "dex": 1, "agi": 1}}


def _mob(pos, kind="wolf", eid=9):
    return {"eid": eid, "kind": kind, "pos": pos, "hp_frac": 1.0, "hit": False,
            "dormant": False, "elite": False, "statuses": []}


def _frame(chars, mobs, world="vale", tick=100):
    return {"world": world, "tick": tick, "chars": chars, "mobs": mobs}


# ---- death features ----------------------------------------------------------

def test_death_features_cover_the_declared_schema_exactly():
    f = mlfeat.death_risk_features(_char(), _frame([_char()], [_mob((4, 3))]),
                                   _PROFILES, _BAND)
    assert set(f) == set(mlfeat.DEATH_FEATURES)
    assert all(isinstance(v, float) for v in f.values())
    v = mlfeat.vector(f, mlfeat.DEATH_FEATURES)
    assert len(v) == len(mlfeat.DEATH_FEATURES) and all(math.isfinite(x) for x in v)


def test_an_UNPROFILED_mob_contributes_zeros_not_a_crash():
    """A kind the bestiary never measured must score as 'no known threat', because the
    live scorer meets new kinds before any snapshot does (Will patches mid-week)."""
    f = mlfeat.death_risk_features(_char(), _frame([_char()], [_mob((4, 3), kind="novel_beast")]),
                                   {}, _BAND)
    assert f["nearest_mob_chaser"] == 0.0 and f["nearest_mob_dph"] == 0.0
    assert f["n_mobs_w1"] == 1.0                # the mob still COUNTS as present


def test_empty_world_yields_the_distance_cap_not_infinity():
    f = mlfeat.death_risk_features(_char(), _frame([_char()], []), _PROFILES, _BAND)
    assert f["nearest_mob_dist"] == mlfeat.DIST_CAP


def test_vector_raises_on_a_missing_feature():
    """Silence here IS training/serving skew — the exact disease this module exists to
    prevent — so a hole in the dict must raise, never default."""
    with pytest.raises(KeyError):
        mlfeat.vector({"hp_frac": 1.0}, mlfeat.DEATH_FEATURES)


# ---- the death label, boundary-exact -----------------------------------------

def test_death_label_window_boundaries():
    """Positive strictly for tick < d <= tick+k. Both edges pinned:
    * at tick == d the character is already dead in the event stream — the decision
      that mattered was earlier, so the death tick itself is NOT positive;
    * at tick == d-k the death is exactly k ahead — the furthest positive."""
    idx = {"u1": [100]}
    assert mlfeat.death_label("u1", 100, idx, 15) == 0     # the death tick itself
    assert mlfeat.death_label("u1", 99, idx, 15) == 1      # one tick before
    assert mlfeat.death_label("u1", 85, idx, 15) == 1      # exactly k before
    assert mlfeat.death_label("u1", 84, idx, 15) == 0      # k+1 before
    assert mlfeat.death_label("u1", 101, idx, 15) == 0     # after death
    assert mlfeat.death_label("other", 99, idx, 15) == 0   # someone else's death


# ---- band --------------------------------------------------------------------

def test_band_danger_classes():
    assert mlfeat.band_danger_class(0.5, 0.0) == "undead"
    assert mlfeat.band_danger_class(0.0, 3.0) == "melee"
    assert mlfeat.band_danger_class(0.0, 0.0) == "calm"
    # undead dominance outranks melee density — the wizard-killing class wins ties
    assert mlfeat.band_danger_class(0.5, 9.0) == "undead"


def test_band_features_pad_a_short_history_with_calm():
    f = mlfeat.band_features("mines", ["undead"], 300)
    assert f["prev1_danger"] == float(mlfeat.DANGER_CLASSES.index("undead"))
    assert f["prev2_danger"] == float(mlfeat.DANGER_CLASSES.index("calm"))
    assert set(f) == set(mlfeat.BAND_FEATURES)


# ---- mob move classes --------------------------------------------------------

def test_mob_move_classes_are_rotation_invariant():
    """The same physical behaviour (step toward the nearest char) must classify
    identically from every approach angle — that is what the canonical rotation buys."""
    cases = [((5, 5), (6, 5), (9, 5)),     # char east, step east
             ((5, 5), (4, 5), (1, 5)),     # char west, step west
             ((5, 5), (5, 6), (5, 9)),     # char north, step north
             ((5, 5), (5, 4), (5, 1))]     # char south, step south
    for prev, nxt, char in cases:
        assert mlfeat.mob_move_class(prev, nxt, char) == "toward", (prev, nxt, char)
    for prev, nxt, char in [((5, 5), (4, 5), (9, 5)), ((5, 5), (5, 4), (5, 9))]:
        assert mlfeat.mob_move_class(prev, nxt, char) == "away"
    assert mlfeat.mob_move_class((5, 5), (5, 5), (9, 5)) == "stay"
    assert mlfeat.mob_move_class((5, 5), (5, 6), (9, 5)) == "perp_left"
    assert mlfeat.mob_move_class((5, 5), (5, 4), (9, 5)) == "perp_right"


def test_mob_features_cover_the_schema():
    f = mlfeat.mob_features(_mob((5, 5)), _frame([_char()], [_mob((5, 5))]),
                            _PROFILES["wolf"])
    assert set(f) == set(mlfeat.MOB_FEATURES)
    assert f["beh_chaser"] == 1.0 and f["chaser_score"] == 0.9


# ---- normalisation -----------------------------------------------------------

def test_normalize_keeps_the_survival_fields_bestiary_drops():
    decoded = {"world": "vale", "tick": 7, "chars": [{
        "char_uid": "u1", "pos": [1, 2], "hp": 10, "max_hp": 30, "stamina": 5,
        "max_stamina": 60, "level": 3, "stats": {"int": 2}, "carry": {"used": 1, "cap": 20},
        "inventory": [{"kind": "potion_red"}], "statuses": [{"kind": "poison"}]}],
        "visible": {"entities": [{"eid": 4, "kind": "wolf", "pos": [3, 3],
                                  "faction": "monster"}]}}
    nf = mlfeat.normalize_frame(decoded)
    ch = nf["chars"][0]
    assert ch["has_heal"] is True and ch["stamina"] == 5 and ch["max_stamina"] == 60
    assert ch["statuses"] == ["poison"] and ch["carry_cap"] == 20
    assert nf["mobs"][0]["kind"] == "wolf"     # the bestiary shape, delegated
