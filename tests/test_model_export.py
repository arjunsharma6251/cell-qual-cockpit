"""Parity: the exported-JSON scoring path must match the sklearn model.

The TRY IT tab scores cells in the browser from the JSON export. This test
re-implements that scorer in pure Python (same pseudocode as app.js: scale ->
dot -> isotonic interpolation; per-fold PAVA for the Venn-ABERS interval) and
checks it against EarlyVerdictModel / cvap_predict on real feature vectors.
Requires the built bundle + Severson data; skips otherwise.
"""

import json
import os

import numpy as np
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLE = os.path.join(ROOT, "app", "static", "cockpit_data.json")
DATA = os.path.join(ROOT, "data", "processed_slim.pkl")

needs_data = pytest.mark.skipif(
    not (os.path.exists(BUNDLE) and os.path.exists(DATA)),
    reason="bundle or Severson data not present")


def score_point(m, x):
    """Mirror of the JS point scorer: scale -> linear -> isotonic interp."""
    z = sum((xi - mu) / sc * w for xi, mu, sc, w in zip(x, m["mean"], m["scale"], m["coef"])) + m["intercept"]
    xs, ys = m["iso_x"], m["iso_y"]
    if z <= xs[0]:
        return ys[0]
    if z >= xs[-1]:
        return ys[-1]
    i = np.searchsorted(xs, z) - 1
    t = (z - xs[i]) / (xs[i + 1] - xs[i]) if xs[i + 1] != xs[i] else 0.0
    return ys[i] + t * (ys[i + 1] - ys[i])


def pava(xs, ys):
    """Isotonic regression via pool-adjacent-violators; ties on x averaged
    first (sklearn's behavior). Returns fitted value per input point."""
    order = np.argsort(xs, kind="stable")
    xs_s, ys_s = np.asarray(xs)[order], np.asarray(ys)[order]
    ux, inv = np.unique(xs_s, return_inverse=True)
    uy = np.array([ys_s[inv == i].mean() for i in range(len(ux))])
    uw = np.array([(inv == i).sum() for i in range(len(ux))], dtype=float)
    vals, wts, idx = [], [], []
    for y, w in zip(uy, uw):
        vals.append(y); wts.append(w); idx.append(1)
        while len(vals) > 1 and vals[-2] >= vals[-1]:
            v = (vals[-2] * wts[-2] + vals[-1] * wts[-1]) / (wts[-2] + wts[-1])
            wts[-2] += wts[-1]; idx[-2] += idx[-1]
            vals.pop(); wts.pop(); idx.pop()
            vals[-1] = v
    fitted_u = np.repeat(vals, idx)
    return fitted_u, ux


def venn_abers(fold, s):
    """Mirror of the JS interval scorer for one fold and one test score."""
    out = []
    for label in (0, 1):
        xs = fold["cal_scores"] + [s]
        ys = fold["cal_labels"] + [label]
        fitted, ux = pava(xs, ys)
        out.append(float(fitted[np.searchsorted(ux, s)]))
    return out  # [p0, p1]


def fold_score(fold, x):
    return sum((xi - mu) / sc * w for xi, mu, sc, w in zip(x, fold["mean"], fold["scale"], fold["coef"])) + fold["intercept"]


@needs_data
def test_export_matches_sklearn():
    import sys
    sys.path.insert(0, ROOT)
    from src.calibration import cvap_predict
    from src.data import build_dataset
    from src.features import featurize
    from src.labels import make_labels
    from src.model import EarlyVerdictModel
    from src.split import canonical_split
    from src.transfer import DQ_FEATURES

    m = json.load(open(BUNDLE))["qual"]["model"]
    bd = build_dataset(os.path.join(ROOT, "data"), verbose=False)
    labels, _ = make_labels(bd, threshold=700, verbose=False)
    train, primary, secondary = canonical_split(bd.keys())
    feats = featurize(bd, cutoff=100)[DQ_FEATURES]
    X_tr = feats.loc[train].values
    y_tr = np.array([labels[k] for k in train])
    X_te = feats.loc[primary + secondary].values

    ref = EarlyVerdictModel().fit(X_tr, y_tr)
    p_ref = ref.predict_proba(X_te)[:, 1]
    p_json = np.array([score_point(m["point"], x) for x in X_te])
    assert np.max(np.abs(p_ref - p_json)) < 1e-6

    _, p0_ref, p1_ref = cvap_predict(X_tr, y_tr, X_te[:10], seed=0)
    for i in range(10):
        p0s, p1s = [], []
        for fold in m["cvap"]:
            p0, p1 = venn_abers(fold, fold_score(fold, X_te[i]))
            p0s.append(p0); p1s.append(p1)
        assert abs(np.mean(p0s) - p0_ref[i]) < 1e-6
        assert abs(np.mean(p1s) - p1_ref[i]) < 1e-6
