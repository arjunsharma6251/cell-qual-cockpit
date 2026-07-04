"""Calibrated classifiers for the early-qualification verdict.

Logistic regression + CV calibration. 124 cells punishes anything bigger.
The calibrated probability IS the product here.

Two variants:
- make_model: sklearn CalibratedClassifierCV (fold-ensemble). Used for the
  pre-registered gate run; kept for comparison.
- EarlyVerdictModel (default for the hardened pipeline): calibrate a single
  map on out-of-fold scores, refit the base model on the full train split,
  apply the map to its test scores. Selected 'isotonic' by 5-fold x 10-repeat
  nested CV on the training split only (see early_call_study.ipynb section 4).
"""

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .calibration import BetaCalibrator, _oof_scores
from scipy.special import expit


def make_model(method="isotonic", cv=5, C=1.0, random_state=0):
    """Standardize -> logistic regression -> CV-calibrated probabilities."""
    base = LogisticRegression(C=C, max_iter=5000, random_state=random_state)
    return Pipeline(
        [
            ("scaler", StandardScaler()),
            ("clf", CalibratedClassifierCV(base, method=method, cv=cv)),
        ]
    )


class EarlyVerdictModel:
    """OOF-calibrated logistic regression with a sklearn-like interface."""

    def __init__(self, method="isotonic", n_splits=5, seed=0):
        self.method = method
        self.n_splits = n_splits
        self.seed = seed

    def fit(self, X, y):
        scores, self.base_ = _oof_scores(np.asarray(X), np.asarray(y),
                                         n_splits=self.n_splits, seed=self.seed)
        if self.method == "isotonic":
            self.cal_ = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
            self.cal_.fit(scores, y)
        elif self.method == "beta":
            self.cal_ = BetaCalibrator().fit(expit(scores), np.asarray(y))
        else:
            raise ValueError(self.method)
        return self

    def predict_proba(self, X):
        s = self.base_.decision_function(np.asarray(X))
        p1 = self.cal_.predict(expit(s) if self.method == "beta" else s)
        return np.column_stack([1 - p1, p1])

    def predict(self, X):
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)
