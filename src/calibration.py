"""Small-sample calibration methods beyond CalibratedClassifierCV.

Everything here consumes out-of-fold (OOF) scores from the same scaled
logistic-regression base model, so methods differ only in how the score ->
probability map is fit:

- 'sigmoid' / 'isotonic': fit on OOF scores (ensemble=False equivalent).
- 'beta': three-parameter beta calibration (Kull et al. 2017), fit by bounded
  MLE — parametric, so more sample-efficient than isotonic at n~40.
- CVAP: cross Venn-ABERS predictor (Vovk & Petej 2014) — per test cell,
  isotonic calibration is refit with that cell forced to label 0 and then 1,
  giving a probability interval [p0, p1] with distribution-free validity.
  Fold intervals are merged with the paper's geometric-mean rule.

The interval drives the abstain rule: call pass if p0 > 0.5, fail if
p1 < 0.5, otherwise 'keep testing'.
"""

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

EPS = 1e-6


def _base_model(C=1.0, random_state=0):
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression(C=C, max_iter=5000, random_state=random_state)),
        ]
    )


def _oof_scores(X, y, n_splits=5, seed=0):
    """Out-of-fold decision scores (log-odds) plus a full-train model."""
    scores = np.zeros(len(y), dtype=float)
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    for tr, va in skf.split(X, y):
        m = _base_model(random_state=seed)
        m.fit(X[tr], y[tr])
        scores[va] = m.decision_function(X[va])
    full = _base_model(random_state=seed)
    full.fit(X, y)
    return scores, full


class BetaCalibrator:
    """p_cal = sigmoid(a*ln(p) - b*ln(1-p) + c), a,b >= 0 (Kull et al. 2017)."""

    def fit(self, p, y):
        p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
        y = np.asarray(y, float)
        f1, f2 = np.log(p), -np.log(1 - p)

        def nll(theta):
            a, b, c = theta
            z = a * f1 + b * f2 + c
            q = np.clip(expit(z), EPS, 1 - EPS)
            return -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))

        res = minimize(nll, x0=[1.0, 1.0, 0.0], bounds=[(0, None), (0, None), (None, None)],
                       method="L-BFGS-B")
        self.a_, self.b_, self.c_ = res.x
        return self

    def predict(self, p):
        p = np.clip(np.asarray(p, float), EPS, 1 - EPS)
        return expit(self.a_ * np.log(p) + self.b_ * (-np.log(1 - p)) + self.c_)


def oof_calibrated_probs(X_tr, y_tr, X_te, method="isotonic", n_splits=5, seed=0):
    """Calibrate on OOF scores, refit base on full train, map test scores."""
    scores, full = _oof_scores(X_tr, y_tr, n_splits=n_splits, seed=seed)
    s_te = full.decision_function(X_te)
    if method == "isotonic":
        cal = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        cal.fit(scores, y_tr)
        return cal.predict(s_te)
    if method == "sigmoid":
        lr = LogisticRegression(max_iter=5000)
        lr.fit(scores.reshape(-1, 1), y_tr)
        return lr.predict_proba(s_te.reshape(-1, 1))[:, 1]
    if method == "beta":
        cal = BetaCalibrator().fit(expit(scores), y_tr)
        return cal.predict(expit(s_te))
    raise ValueError(method)


def ensemble_probs(X_tr, y_tr, X_te, method="isotonic", n_seeds=10, n_splits=5):
    """Average one calibrated model per CV seed — cuts calibration variance."""
    ps = [oof_calibrated_probs(X_tr, y_tr, X_te, method=method, n_splits=n_splits, seed=s)
          for s in range(n_seeds)]
    return np.mean(ps, axis=0)


def _venn_abers_interval(cal_scores, cal_y, test_scores):
    """IVAP: per test score s, isotonic refit with (s, 0) then (s, 1)."""
    p0 = np.empty(len(test_scores))
    p1 = np.empty(len(test_scores))
    for i, s in enumerate(test_scores):
        for label, out in ((0, p0), (1, p1)):
            iso = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            iso.fit(np.append(cal_scores, s), np.append(cal_y, label))
            out[i] = iso.predict([s])[0]
    return p0, p1


def cvap_predict(X_tr, y_tr, X_te, n_splits=5, seed=0):
    """Cross Venn-ABERS: per-fold IVAP intervals, geometric-mean merge.

    Returns (p, p0_mean, p1_mean): merged point probability and the
    arithmetic-mean interval bounds for display.
    """
    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    p0s, p1s = [], []
    for tr, cal in skf.split(X_tr, y_tr):
        m = _base_model(random_state=seed)
        m.fit(X_tr[tr], y_tr[tr])
        p0, p1 = _venn_abers_interval(m.decision_function(X_tr[cal]), y_tr[cal],
                                      m.decision_function(X_te))
        p0s.append(p0)
        p1s.append(p1)
    p0s, p1s = np.array(p0s), np.array(p1s)
    gm_p1 = np.exp(np.mean(np.log(np.clip(p1s, EPS, 1)), axis=0))
    gm_q0 = np.exp(np.mean(np.log(np.clip(1 - p0s, EPS, 1)), axis=0))
    p = gm_p1 / (gm_q0 + gm_p1)
    return p, p0s.mean(axis=0), p1s.mean(axis=0)


def abstain_call(p0, p1):
    """Verdict from an interval: 1/0 when it clears 0.5, -1 = keep testing."""
    p0, p1 = np.asarray(p0), np.asarray(p1)
    out = np.full(len(p0), -1, dtype=int)
    out[p0 > 0.5] = 1
    out[p1 < 0.5] = 0
    return out
