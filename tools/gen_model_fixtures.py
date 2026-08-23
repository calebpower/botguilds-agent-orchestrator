"""Generate the sklearn-parity fixture — runs ONLY inside the training session.

Trains a deliberately tiny GBM on synthetic data, exports it through the SAME tree
serializer train_models.py uses, and records sklearn's own predict_proba outputs for a
grid of inputs. The committed fixture then lets the FreeBSD test suite prove the stdlib
walker matches sklearn to 1e-9 forever, without sklearn ever being installed there.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steemer import mlfeat  # noqa: E402
from tools.train_models import _tree_to_dict  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tests", "fixtures", "models")


def main() -> int:
    import numpy as np
    from sklearn.ensemble import GradientBoostingClassifier
    rng = np.random.default_rng(7)
    names = ["a", "b", "c"]
    X = rng.normal(size=(600, 3))
    y = ((X[:, 0] + 0.5 * X[:, 1] - X[:, 2] + rng.normal(scale=0.3, size=600)) > 0)
    gbm = GradientBoostingClassifier(n_estimators=12, max_depth=2, random_state=7)
    gbm.fit(X, y.astype(int))
    base = float(gbm._raw_predict_init(np.zeros((1, 3)))[0][0])
    trees = [_tree_to_dict(est[0], scale=gbm.learning_rate) for est in gbm.estimators_]
    os.makedirs(OUT, exist_ok=True)
    model = {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "model": "gbm_binary",
             "feature_names": names, "base_score": base, "trees": trees}
    with open(os.path.join(OUT, "death_risk.json"), "w") as fh:
        json.dump(model, fh)
    with open(os.path.join(OUT, "death_risk.meta.json"), "w") as fh:
        json.dump({"trained_at_epoch": 4102444800.0,       # pinned far future: fixtures
                   "note": "sklearn parity fixture"}, fh)  # must never go stale
    with open(os.path.join(OUT, "tiny_gbm.json"), "w") as fh:
        json.dump({"marker": True}, fh)
    grid = rng.normal(size=(50, 3))
    probs = gbm.predict_proba(grid)[:, 1]
    with open(os.path.join(OUT, "expected_scores.jsonl"), "w") as fh:
        for row, p in zip(grid, probs):
            fh.write(json.dumps({"features": dict(zip(names, map(float, row))),
                                 "expected": float(p)}) + "\n")
    print(f"[fixtures] wrote parity fixture to {OUT} ({len(grid)} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
