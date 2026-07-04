import numpy as np
import pytest

from src.features import FEATURE_NAMES, aux_features, delta_q_features, featurize
from src.labels import make_labels
from src.split import canonical_split


def synthetic_cell(seed=0, n_cycles=110):
    rng = np.random.RandomState(seed)
    base = np.linspace(0, 1.05, 1000)
    cycles = {str(i): {"Qdlin": base + rng.normal(0, 1e-4, 1000)} for i in range(n_cycles)}
    cyc = np.arange(1, n_cycles + 1, dtype=float)
    summary = {
        "cycle": cyc,
        "QD": 1.08 - 0.0005 * cyc,
        "chargetime": np.full(n_cycles, 10.0),
        "IR": np.full(n_cycles, 0.015),
    }
    return {"cycles": cycles, "summary": summary}


def test_delta_q_features_known_variance():
    cell = synthetic_cell()
    delta = np.full(1000, -0.02)
    cell["cycles"]["100"]["Qdlin"] = cell["cycles"]["10"]["Qdlin"] + delta
    f = delta_q_features(cell, cyc_late=100, cyc_early=10)
    assert f["log_mean_dq"] == pytest.approx(np.log10(0.02), abs=1e-3)
    assert f["log_min_dq"] == pytest.approx(np.log10(0.02), abs=1e-3)


def test_aux_features_values():
    f = aux_features(synthetic_cell(), cutoff=100)
    assert f["fade_slope"] == pytest.approx(-0.0005, rel=1e-3)
    assert f["qd_cycle2"] == pytest.approx(1.08 - 0.001, rel=1e-6)
    assert f["avg_chargetime_first5"] == pytest.approx(10.0)
    assert f["ir_cycle2"] == pytest.approx(0.015)


def test_featurize_columns_ordered():
    df = featurize({"a": synthetic_cell(0), "b": synthetic_cell(1)}, cutoff=100)
    assert list(df.columns) == FEATURE_NAMES
    assert list(df.index) == ["a", "b"]


def test_make_labels_balanced_case():
    bd = {f"c{i}": {"cycle_life": float(v)} for i, v in enumerate(range(100, 1100, 100))}
    labels, T = make_labels(bd, threshold=700, verbose=False)
    assert T == 700
    assert sum(labels.values()) == 4  # lives 700..1000 pass


def test_make_labels_auto_adjusts_when_unbalanced():
    lives = [1000] * 8 + [100, 200]
    bd = {f"c{i}": {"cycle_life": float(v)} for i, v in enumerate(lives)}
    labels, T = make_labels(bd, threshold=700, verbose=False)
    assert T == 1000  # moved to empirical median
    assert all(labels[f"c{i}"] == int(lives[i] >= T) for i in range(10))


def test_canonical_split_sizes_and_disjointness():
    keys = [f"cell{i}" for i in range(124)]
    train, primary, secondary = canonical_split(keys, n_batch3=40)
    assert (len(train), len(primary), len(secondary)) == (41, 43, 40)
    assert not set(train) & set(primary)
    assert not set(train) & set(secondary)
    assert not set(primary) & set(secondary)
