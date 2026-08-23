"""Train the three models from extracted features — runs ONLY in the reaper session.

Temporal split BY RUN (train oldest ~70% / calibration 10% / held-out newest 20%): the
deployment-realistic direction, and the discipline mob_predict.evaluate never had (its
published 0.81/0.892 scored a bestiary built from the same frames it predicted).

Every model must beat its baseline on the held-out runs or it is NOT exported — a losing
model is a finding, not a deliverable. Baselines share the split and the code path:
  death  — a constants-shaped heuristic score, AUC-ranked;
  band   — per-(world) climatology from the train runs, Brier-scored;
  mob    — the class-space reduction of steemer.mob_predict's rule (chaser & move_rate
           >= 0.5 -> "toward", else "stay"), which is exactly what predict() does once
           tile geometry is collapsed into the canonical classes.

Exports follow steemer/models.py's conventions exactly (left is x[f] <= t; binary GBM =
base + sum(trees) through sigmoid then isotonic steps; multiclass trees[stage][class]).
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steemer import mlfeat  # noqa: E402

PRIMARY_K = "y15"
MIN_TEST_POSITIVES = 300
MIN_BAND_REFRESHES = 200
MIN_MOB_PAIRS = 200
MIN_CAL_POSITIVES = 150


def _load_rows(feat_dir: str, model: str) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for path in sorted(glob.glob(os.path.join(feat_dir, f"run_*.{model}.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            header = json.loads(fh.readline())
            if header.get("schema_version") != mlfeat.FEATURE_SCHEMA_VERSION:
                continue
            out[header["run_id"]] = [json.loads(l) for l in fh]
    return out


def _split(run_ids: list[int]) -> tuple[list[int], list[int], list[int]]:
    n = len(run_ids)
    a, b = int(n * 0.7), int(n * 0.8)
    return run_ids[:a], run_ids[a:b], run_ids[b:]


def _tree_to_dict(tree, node=0, scale=1.0):
    import numpy as np  # noqa
    t = tree.tree_
    if t.children_left[node] == -1:
        return {"v": float(t.value[node].ravel()[0]) * scale}
    return {"f": int(t.feature[node]), "t": float(t.threshold[node]),
            "l": _tree_to_dict(tree, t.children_left[node], scale),
            "r": _tree_to_dict(tree, t.children_right[node], scale)}


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def _meta(split, metrics, baselines, extra=None) -> dict:
    m = {"trained_at_epoch": time.time(), "git_sha": _git_sha(),
         "schema_version": mlfeat.FEATURE_SCHEMA_VERSION,
         "split": {"train": split[0], "cal": split[1], "test": split[2]},
         "metrics": metrics, "baselines": baselines}
    if extra:
        m.update(extra)
    return m


def _auc(scores: list[float], labels: list[int]) -> float:
    pairs = sorted(zip(scores, labels))
    pos = sum(labels)
    neg = len(labels) - pos
    if not pos or not neg:
        return float("nan")
    rank_sum = 0.0
    i = 0
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0      # 1-based average rank across the tie group
        rank_sum += avg_rank * sum(1 for k in range(i, j) if pairs[k][1] == 1)
        i = j
    return (rank_sum - pos * (pos + 1) / 2.0) / (pos * neg)


def _ece(scores, labels, bins=10) -> float:
    tot = len(scores)
    e = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, s in enumerate(scores) if lo <= s < hi or (b == bins - 1 and s == 1.0)]
        if not idx:
            continue
        conf = sum(scores[i] for i in idx) / len(idx)
        acc = sum(labels[i] for i in idx) / len(idx)
        e += (len(idx) / tot) * abs(conf - acc)
    return e


def _heuristic_death_score(f: dict) -> float:
    """The constants, restated as a rank score — the floor the model must beat."""
    s = 0.0
    s += (1.0 - f["hp_frac"]) * 3.0
    s += f["dot_active"] * 2.0
    s += (1.0 if f["n_mobs_w1"] > 0 else 0.0) * 2.0
    s += min(f["n_mobs_w3"], 4) * 0.5
    s += (0.0 if f["has_heal"] else 1.0)
    s += (1.0 if f["depth_y"] > 12 and not f["has_heal"] else 0.0)
    return s


def train_death(rows_by_run, out_dir):
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression
    runs = sorted(rows_by_run)
    tr, ca, te = _split(runs)
    def xyw(ids):
        X, y, w = [], [], []
        for rid in ids:
            for r in rows_by_run[rid]:
                X.append(mlfeat.vector(r["f"], mlfeat.DEATH_FEATURES))
                y.append(r[PRIMARY_K])
                w.append(r["w"])
        return X, y, w
    Xtr, ytr, wtr = xyw(tr)
    Xca, yca, _ = xyw(ca)
    Xte, yte, _ = xyw(te)
    if sum(yte) < MIN_TEST_POSITIVES:
        return {"refused": f"held-out positives {sum(yte)} < {MIN_TEST_POSITIVES}"}
    gbm = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=7)
    gbm.fit(Xtr, ytr, sample_weight=wtr)
    lr = gbm.learning_rate
    base = float(gbm._raw_predict_init([[0.0] * len(mlfeat.DEATH_FEATURES)])[0][0]) \
        if hasattr(gbm, "_raw_predict_init") else 0.0
    trees = [_tree_to_dict(est[0], scale=lr) for est in gbm.estimators_]
    raw = lambda X: [_sigmoid_raw(base + sum(_walk_py(t, x) for t in trees)) for x in X]
    cal = None
    pca = raw(Xca)
    if sum(yca) >= MIN_CAL_POSITIVES:
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(pca, yca)
        xs = sorted(set(float(v) for v in iso.X_thresholds_))
        cal = {"x": xs, "y": [float(iso.predict([v])[0]) for v in xs]}
    pte = raw(Xte)
    if cal:
        pte = [_apply_cal(p, cal) for p in pte]
    hte = [_heuristic_death_score(dict(zip(mlfeat.DEATH_FEATURES, x))) for x in Xte]
    metrics = {"auc": _auc(pte, yte), "ece": _ece(pte, yte),
               "test_positives": int(sum(yte)), "test_rows": len(yte),
               "recall_at_fpr10": _recall_at_fpr(pte, yte, 0.10)}
    baselines = {"heuristic_auc": _auc(hte, yte)}
    ok = (not math.isnan(metrics["auc"])
          and metrics["auc"] > baselines["heuristic_auc"] + 0.03
          and metrics["ece"] <= 0.05)
    model = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "gbm_binary",
             "feature_names": list(mlfeat.DEATH_FEATURES), "base_score": base,
             "trees": trees, "calibration": cal}
    result = {"metrics": metrics, "baselines": baselines, "accepted": ok}
    if ok:
        _export(out_dir, "death_risk", model, _meta((tr, ca, te), metrics, baselines))
    return result


def _sigmoid_raw(z):
    return 1.0 / (1.0 + math.exp(-max(-60, min(60, z))))


def _walk_py(node, x):
    while "v" not in node:
        node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
    return node["v"]


def _apply_cal(p, cal):
    from bisect import bisect_right
    i = bisect_right(cal["x"], p) - 1
    return cal["y"][max(0, min(i, len(cal["y"]) - 1))]


def _recall_at_fpr(scores, labels, fpr):
    neg = sorted((s for s, l in zip(scores, labels) if l == 0), reverse=True)
    if not neg:
        return float("nan")
    thr = neg[max(0, int(len(neg) * fpr) - 1)]
    pos = [s for s, l in zip(scores, labels) if l == 1]
    return sum(1 for s in pos if s > thr) / len(pos) if pos else float("nan")


def train_band(rows_by_run, out_dir):
    from sklearn.linear_model import LogisticRegression
    runs = sorted(rows_by_run)
    tr, ca, te = _split(runs)
    tr = tr + ca                       # logistic needs no separate calibration slice
    def xy(ids):
        X, y = [], []
        for rid in ids:
            for r in rows_by_run[rid]:
                X.append(mlfeat.vector(r["f"], mlfeat.BAND_FEATURES))
                y.append(r["y"])
        return X, y
    Xtr, ytr = xy(tr)
    Xte, yte = xy(te)
    if len(yte) < MIN_BAND_REFRESHES:
        return {"refused": f"held-out refreshes {len(yte)} < {MIN_BAND_REFRESHES}"}
    classes = sorted(set(ytr) | set(yte))
    lr = LogisticRegression(max_iter=1000)
    lr.fit(Xtr, ytr)
    order = list(lr.classes_)
    def brier(prob_rows, ys):
        tot = 0.0
        for pr, yv in zip(prob_rows, ys):
            for ci, c in enumerate(order):
                tot += (pr[ci] - (1.0 if yv == c else 0.0)) ** 2
        return tot / len(ys)
    pte = lr.predict_proba(Xte)
    counts = {c: ytr.count(c) for c in order}
    n = len(ytr)
    clim = [[counts[c] / n for c in order]] * len(yte)
    metrics = {"brier": brier(pte.tolist(), yte), "test_refreshes": len(yte)}
    baselines = {"climatology_brier": brier(clim, yte)}
    ok = metrics["brier"] < baselines["climatology_brier"]
    model = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "logistic",
             "feature_names": list(mlfeat.BAND_FEATURES), "classes": order,
             "coef": [[float(v) for v in row] for row in lr.coef_],
             "intercept": [float(v) for v in lr.intercept_]}
    result = {"metrics": metrics, "baselines": baselines, "accepted": ok,
              "classes": classes}
    if ok:
        _export(out_dir, "band_forecast", model, _meta((tr, [], te), metrics, baselines))
    return result


def train_mob(rows_by_run, out_dir):
    from sklearn.ensemble import GradientBoostingClassifier
    runs = sorted(rows_by_run)
    tr, ca, te = _split(runs)
    tr = tr + ca
    def xy(ids):
        X, y = [], []
        for rid in ids:
            for r in rows_by_run[rid]:
                X.append(mlfeat.vector(r["f"], mlfeat.MOB_FEATURES))
                y.append(r["y"])
        return X, y
    Xtr, ytr = xy(tr)
    Xte, yte = xy(te)
    if len(yte) < MIN_MOB_PAIRS:
        return {"refused": f"held-out pairs {len(yte)} < {MIN_MOB_PAIRS}"}
    gbm = GradientBoostingClassifier(n_estimators=60, max_depth=3, random_state=7)
    gbm.fit(Xtr, ytr)
    order = list(gbm.classes_)
    pred = gbm.predict(Xte)
    acc = sum(1 for p, yv in zip(pred, yte) if p == yv) / len(yte)
    moved = [(p, yv) for p, yv in zip(pred, yte) if yv != "stay"]
    toward_moved = sum(1 for p, yv in moved if p == yv == "toward") / \
        max(1, sum(1 for _, yv in moved if yv == "toward"))
    # rule baseline: the class-space reduction of mob_predict.predict
    def rule(x):
        f = dict(zip(mlfeat.MOB_FEATURES, x))
        return "toward" if f["beh_chaser"] and f["move_rate"] >= 0.5 else "stay"
    rp = [rule(x) for x in Xte]
    racc = sum(1 for p, yv in zip(rp, yte) if p == yv) / len(yte)
    rtoward = sum(1 for p, yv in zip(rp, yte) if p == yv == "toward") / \
        max(1, sum(1 for yv in yte if yv == "toward"))
    lr = gbm.learning_rate
    base = [float(v) for v in
            gbm._raw_predict_init([[0.0] * len(mlfeat.MOB_FEATURES)])[0]] \
        if hasattr(gbm, "_raw_predict_init") else [0.0] * len(order)
    trees = [[_tree_to_dict(stage[k], scale=lr) for k in range(len(order))]
             for stage in gbm.estimators_]
    metrics = {"exact": acc, "toward_recall": toward_moved, "test_pairs": len(yte)}
    baselines = {"rule_exact": racc, "rule_toward_recall": rtoward}
    ok = acc > racc and toward_moved > rtoward
    model = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "gbm_multiclass",
             "feature_names": list(mlfeat.MOB_FEATURES), "classes": order,
             "base_scores": base, "trees": trees}
    result = {"metrics": metrics, "baselines": baselines, "accepted": ok}
    if ok:
        _export(out_dir, "mob_move", model, _meta((tr, [], te), metrics, baselines))
    return result


# ---------------------------------------------------------------------------
# batch 2 (operator-picked 2026-08-23): three binary GBMs + two aggregation tables
# ---------------------------------------------------------------------------

MIN_STINT_POSITIVES = 300      # here "positive" is the RARER class, whichever it is
MIN_MOVEFAIL_BOUNCES = 300
MIN_INCOME_POSITIVES = 300
MIN_DPH_SAMPLES = 30           # per kind; below this the tail is unobserved
MIN_REGROWTH_REVISITS = 200    # per bucket; hazard over fewer is noise


def _train_binary(rows_by_run, out_dir, *, name, features, label_key,
                  baseline_fn, baseline_name, min_minority):
    """The shared shape of stint/movefail/income: temporal split, small GBM, isotonic
    calibration, and a baseline that fights back. The floor applies to the MINORITY
    class of the held-out runs — an AUC over 12 positives is a coin decorated with
    decimals, whichever way the labels lean."""
    from sklearn.ensemble import GradientBoostingClassifier
    from sklearn.isotonic import IsotonicRegression
    runs = sorted(rows_by_run)
    tr, ca, te = _split(runs)
    def xy(ids):
        X, y = [], []
        for rid in ids:
            for r in rows_by_run[rid]:
                X.append(mlfeat.vector(r["f"], features))
                y.append(r[label_key])
        return X, y
    Xtr, ytr = xy(tr)
    Xca, yca = xy(ca)
    Xte, yte = xy(te)
    minority = min(sum(yte), len(yte) - sum(yte))
    if minority < min_minority:
        return {"refused": f"held-out minority class {minority} < {min_minority}"}
    if len(set(ytr)) < 2:
        return {"refused": "single-class training set"}
    gbm = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=7)
    gbm.fit(Xtr, ytr)
    lr = gbm.learning_rate
    base = float(gbm._raw_predict_init([[0.0] * len(features)])[0][0])         if hasattr(gbm, "_raw_predict_init") else 0.0
    trees = [_tree_to_dict(est[0], scale=lr) for est in gbm.estimators_]
    raw = lambda X: [_sigmoid_raw(base + sum(_walk_py(t, x) for t in trees)) for x in X]
    cal = None
    pca = raw(Xca)
    if min(sum(yca), len(yca) - sum(yca)) >= MIN_CAL_POSITIVES:
        iso = IsotonicRegression(out_of_bounds="clip")
        iso.fit(pca, yca)
        xs = sorted(set(float(v) for v in iso.X_thresholds_))
        cal = {"x": xs, "y": [float(iso.predict([v])[0]) for v in xs]}
    pte = raw(Xte)
    if cal:
        pte = [_apply_cal(p, cal) for p in pte]
    bte = [baseline_fn(dict(zip(features, x))) for x in Xte]
    metrics = {"auc": _auc(pte, yte), "ece": _ece(pte, yte),
               "test_rows": len(yte), "test_positives": int(sum(yte)),
               "recall_at_fpr10": _recall_at_fpr(pte, yte, 0.10)}
    baselines = {baseline_name: _auc(bte, yte)}
    ok = (not math.isnan(metrics["auc"])
          and metrics["auc"] > baselines[baseline_name] + 0.03
          and metrics["ece"] <= 0.05)
    model = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "gbm_binary",
             "feature_names": list(features), "base_score": base,
             "trees": trees, "calibration": cal}
    result = {"metrics": metrics, "baselines": baselines, "accepted": ok}
    if ok:
        _export(out_dir, name, model, _meta((tr, ca, te), metrics, baselines))
    return result


def train_stint(rows_by_run, out_dir):
    # baseline: stint_age alone — the static "median stint is 10-12" rule's whole
    # information content. Sign: older stints end sooner -> survival DECREASES with
    # age, so the baseline score for y=1 (survives) is -stint_age.
    return _train_binary(
        rows_by_run, out_dir, name="stint_survival",
        features=mlfeat.STINT_FEATURES, label_key="y",
        baseline_fn=lambda f: -f["stint_age"], baseline_name="age_only_auc",
        min_minority=MIN_STINT_POSITIVES)


def train_movefail(rows_by_run, out_dir):
    # baseline: stamina alone (the live heuristic's variable) — lower stamina, more
    # bounces, so the score for y=1 (bounced) is -stamina_frac.
    return _train_binary(
        rows_by_run, out_dir, name="move_fail",
        features=mlfeat.MOVEFAIL_FEATURES, label_key="y",
        baseline_fn=lambda f: -f["stamina_frac"], baseline_name="stamina_only_auc",
        min_minority=MIN_MOVEFAIL_BOUNCES)


def train_income(rows_by_run, out_dir):
    # baseline: greedy line-of-sight — items visible within 6 IS the current policy.
    return _train_binary(
        rows_by_run, out_dir, name="income_spot",
        features=mlfeat.INCOME_FEATURES, label_key="y",
        baseline_fn=lambda f: f["n_items_w6"], baseline_name="items_w6_auc",
        min_minority=MIN_INCOME_POSITIVES)


def build_tables(feat_dir, out_dir):
    """The two aggregation artifacts: dph distributions and the regrowth hazard.
    Merged from RAW per-run samples (quantiles are computed only here); no split —
    these are descriptive tables with sample floors, not predictive models."""
    dmg_by_kind: dict[str, list] = {}
    revisit: dict[str, int] = {}
    flips: dict[str, int] = {}
    n_runs = 0
    for path in sorted(glob.glob(os.path.join(feat_dir, "run_*.aggr.jsonl.gz"))):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            header = json.loads(fh.readline())
            if header.get("schema_version") != mlfeat.FEATURE_SCHEMA_VERSION:
                continue
            n_runs += 1
            for line in fh:
                d = json.loads(line)
                for smp in d.get("dmg") or []:
                    dmg_by_kind.setdefault(smp["kind"], []).append(
                        (smp["drop"], smp["elite"]))
                rg = d.get("regrowth") or {}
                for b, n in (rg.get("revisit") or {}).items():
                    revisit[b] = revisit.get(b, 0) + n
                for b, n in (rg.get("flip") or {}).items():
                    flips[b] = flips.get(b, 0) + n
    q = lambda v, p: v[min(len(v) - 1, int(len(v) * p))] if v else None
    dph = {}
    for kind, samples in sorted(dmg_by_kind.items()):
        if len(samples) < MIN_DPH_SAMPLES:
            continue
        drops = sorted(d for d, _ in samples)
        base = sorted(d for d, e in samples if not e)
        elite = sorted(d for d, e in samples if e)
        dph[kind] = {
            "n": len(samples), "p50": q(drops, 0.5), "p90": q(drops, 0.9),
            "max_seen": drops[-1],
            "elite_p50": q(elite, 0.5) if len(elite) >= MIN_DPH_SAMPLES else None,
            "base_p50": q(base, 0.5) if base else None,
        }
    hazard = {}
    for b in sorted(revisit):
        if revisit[b] >= MIN_REGROWTH_REVISITS:
            hazard[b] = {"revisits": revisit[b], "flips": flips.get(b, 0),
                         "p_flip": flips.get(b, 0) / revisit[b]}
    results = {}
    if dph:
        _export(out_dir, "dph_profile",
                {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "table",
                 "kinds": dph},
                _meta(([], [], []), {"kinds": len(dph)}, {},
                      extra={"runs_merged": n_runs}))
        results["dph_profile"] = {"accepted": True, "metrics": {
            "kinds": len(dph),
            "total_samples": sum(v["n"] for v in dph.values())}}
    else:
        results["dph_profile"] = {"refused": "no kind reached the sample floor"}
    if hazard:
        _export(out_dir, "terrain_regrowth",
                {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "table",
                 "buckets": hazard},
                _meta(([], [], []), {"buckets": len(hazard)}, {},
                      extra={"runs_merged": n_runs}))
        results["terrain_regrowth"] = {"accepted": True, "metrics": {
            b: v["p_flip"] for b, v in hazard.items()}}
    else:
        results["terrain_regrowth"] = {"refused": "no bucket reached the revisit floor"}
    return results


def _export(out_dir, name, model, meta):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{name}.json"), "w") as fh:
        json.dump(model, fh)
    with open(os.path.join(out_dir, f"{name}.meta.json"), "w") as fh:
        json.dump(meta, fh, indent=1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    results = {}
    for name, fn in (("death_risk", train_death), ("band_forecast", train_band),
                     ("mob_move", train_mob), ("stint_survival", train_stint),
                     ("move_fail", train_movefail), ("income_spot", train_income)):
        rows = _load_rows(a.features, {"death_risk": "death", "band_forecast": "band",
                                       "mob_move": "mob", "stint_survival": "stint",
                                       "move_fail": "movefail",
                                       "income_spot": "income"}[name])
        if not rows:
            results[name] = {"refused": "no feature files"}
            continue
        results[name] = fn(rows, a.out)
        print(f"[train] {name}: {json.dumps(results[name].get('metrics'))} "
              f"vs {json.dumps(results[name].get('baselines'))} "
              f"accepted={results[name].get('accepted')}")
    results.update(build_tables(a.features, a.out))
    with open(os.path.join(a.out, "eval.json"), "w") as fh:
        json.dump(results, fh, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
