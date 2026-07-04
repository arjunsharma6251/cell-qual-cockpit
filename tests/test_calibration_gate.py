import numpy as np
import pytest

from src.calibration import BetaCalibrator, abstain_call, cvap_predict, oof_calibrated_probs
from src.gate import decide, expected_calibration_error
from src.model import EarlyVerdictModel


def test_ece_hand_computed():
    y = np.array([1, 1, 0, 0])
    p = np.array([0.9, 0.8, 0.2, 0.1])
    # each point sits alone in its bin; per-bin |acc-conf| = .1,.2,.2,.1 -> mean .15
    assert expected_calibration_error(y, p) == pytest.approx(0.15)


def test_ece_perfect_confidence():
    y = np.array([1, 1, 0, 0])
    p = np.array([1.0, 1.0, 0.001, 0.001])
    assert expected_calibration_error(y, p) < 0.01


def test_decide_boundaries():
    assert decide(0.85, 0.10) == "BUILD"
    assert decide(0.86, 0.15) == "RESCOPE"
    assert decide(0.80, 0.05) == "RESCOPE"
    assert decide(0.74, 0.05) == "KILL"
    assert decide(0.90, 0.25) == "KILL"


def test_abstain_call_three_way():
    p0 = np.array([0.6, 0.1, 0.3])
    p1 = np.array([0.9, 0.4, 0.7])
    assert list(abstain_call(p0, p1)) == [1, 0, -1]


def test_beta_calibrator_monotone_and_bounded():
    rng = np.random.RandomState(0)
    p_raw = rng.uniform(0.02, 0.98, 400)
    y = (rng.rand(400) < p_raw).astype(float)
    cal = BetaCalibrator().fit(p_raw, y)
    grid = np.linspace(0.02, 0.98, 50)
    out = cal.predict(grid)
    assert np.all((out >= 0) & (out <= 1))
    assert np.all(np.diff(out) >= -1e-6)  # monotone for a,b >= 0
    # near-calibrated input should stay near the identity
    assert np.max(np.abs(out - grid)) < 0.15


def _separable(n=60, seed=0):
    rng = np.random.RandomState(seed)
    y = np.repeat([0, 1], n // 2)
    X = rng.normal(0, 1, (n, 3)) + 2.5 * y[:, None]
    return X, y


def test_oof_calibrated_probs_separable():
    X, y = _separable()
    Xt, yt = _separable(seed=1)
    p = oof_calibrated_probs(X, y, Xt, method="isotonic")
    assert ((p >= 0.5).astype(int) == yt).mean() >= 0.95


def test_cvap_intervals_ordered_and_cover_point():
    X, y = _separable()
    Xt, _ = _separable(seed=2)
    p, p0, p1 = cvap_predict(X, y, Xt, n_splits=5)
    assert np.all(p0 <= p1 + 1e-9)
    assert np.all((p >= 0) & (p <= 1))


def test_early_verdict_model_roundtrip():
    X, y = _separable(n=80)
    Xt, yt = _separable(n=80, seed=3)
    m = EarlyVerdictModel().fit(X, y)
    proba = m.predict_proba(Xt)
    assert proba.shape == (80, 2)
    assert np.allclose(proba.sum(axis=1), 1)
    assert (m.predict(Xt) == yt).mean() >= 0.95
