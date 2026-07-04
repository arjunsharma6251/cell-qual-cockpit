"""Early-call study evaluation: balanced accuracy, ECE, stabilization sweep."""

import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import balanced_accuracy_score

from .features import featurize
from .model import make_model

CUTOFFS = [40, 50, 60, 80, 100]

ACC_BUILD, ACC_RESCOPE_FLOOR = 0.85, 0.75
ECE_BUILD, ECE_RESCOPE_CEIL = 0.10, 0.20


def expected_calibration_error(y_true, p_pred, n_bins=10):
    """Expected calibration error over equal-width confidence bins."""
    y_true = np.asarray(y_true, dtype=float)
    p_pred = np.asarray(p_pred, dtype=float)
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p_pred > lo) & (p_pred <= hi)
        if m.sum() == 0:
            continue
        conf = p_pred[m].mean()
        acc = y_true[m].mean()
        ece += (m.sum() / len(p_pred)) * abs(acc - conf)
    return ece


def evaluate(model, X, y):
    """Balanced accuracy + ECE (+ raw probabilities) for one eval set."""
    p = model.predict_proba(X)[:, 1]
    yhat = (p >= 0.5).astype(int)
    return {
        "balanced_acc": balanced_accuracy_score(y, yhat),
        "ece": expected_calibration_error(np.asarray(y), p),
        "p": p,
        "yhat": yhat,
    }


def _xy(feats, labels, keys):
    X = feats.loc[keys].values
    y = np.array([labels[k] for k in keys])
    return X, y


def fit_and_evaluate(bat_dict, labels, train_keys, eval_sets, cutoff=100, model_factory=make_model):
    """Featurize at `cutoff`, fit calibrated model on train, evaluate each set.

    eval_sets: {name: [cell keys]}. Returns {name: metrics dict} plus the
    fitted model and feature frame under '_model' / '_features'.
    """
    feats = featurize(bat_dict, cutoff=cutoff)
    X_tr, y_tr = _xy(feats, labels, train_keys)
    model = model_factory()
    model.fit(X_tr, y_tr)
    out = {}
    for name, keys in eval_sets.items():
        X, y = _xy(feats, labels, keys)
        out[name] = evaluate(model, X, y)
        out[name]["keys"] = list(keys)
        out[name]["y"] = y
    out["_model"] = model
    out["_features"] = feats
    return out


def stabilization_sweep(bat_dict, labels, train_keys, eval_sets, cutoffs=CUTOFFS, model_factory=make_model):
    """Refit/evaluate with data cut off at each cycle count in `cutoffs`."""
    results = {}
    for cutoff in cutoffs:
        results[cutoff] = fit_and_evaluate(
            bat_dict, labels, train_keys, eval_sets, cutoff=cutoff, model_factory=model_factory
        )
    return results


def decide(balanced_acc, ece):
    """BUILD / RESCOPE / KILL per the early-call study criteria."""
    if balanced_acc >= ACC_BUILD and ece <= ECE_BUILD:
        return "BUILD"
    if balanced_acc >= ACC_RESCOPE_FLOOR and ece <= ECE_RESCOPE_CEIL:
        return "RESCOPE"
    return "KILL"


def reliability_diagram(y_true, p_pred, n_bins=10, ax=None, title="Reliability diagram"):
    """Predicted probability vs empirical pass rate, with bin counts."""
    y_true = np.asarray(y_true, dtype=float)
    p_pred = np.asarray(p_pred, dtype=float)
    bins = np.linspace(0, 1, n_bins + 1)
    centers, accs, counts = [], [], []
    for lo, hi in zip(bins[:-1], bins[1:]):
        m = (p_pred > lo) & (p_pred <= hi)
        if m.sum() == 0:
            continue
        centers.append(p_pred[m].mean())
        accs.append(y_true[m].mean())
        counts.append(int(m.sum()))
    if ax is None:
        _, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color="gray", lw=1, label="perfect")
    ax.plot(centers, accs, "o-", color="tab:blue", label="model")
    for x_, y_, c_ in zip(centers, accs, counts):
        ax.annotate(str(c_), (x_, y_), textcoords="offset points", xytext=(5, -10), fontsize=8)
    ax.set_xlabel("predicted P(pass)")
    ax.set_ylabel("empirical pass rate")
    ax.set_title(title)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.legend()
    return ax


def stabilization_plot(sweep_results, eval_name, ax=None):
    """Balanced accuracy and ECE vs cutoff cycle for one eval set."""
    cutoffs = sorted(sweep_results.keys())
    accs = [sweep_results[c][eval_name]["balanced_acc"] for c in cutoffs]
    eces = [sweep_results[c][eval_name]["ece"] for c in cutoffs]
    if ax is None:
        _, ax = plt.subplots(figsize=(6, 4))
    ax.plot(cutoffs, accs, "o-", color="tab:blue", label="balanced acc")
    ax.axhline(ACC_BUILD, ls="--", color="tab:green", lw=1, label=f"BUILD acc >= {ACC_BUILD}")
    ax.set_xlabel("cutoff cycle (data available)")
    ax.set_ylabel("balanced accuracy", color="tab:blue")
    ax.set_ylim(0.4, 1.02)
    ax2 = ax.twinx()
    ax2.plot(cutoffs, eces, "s-", color="tab:red", label="ECE")
    ax2.axhline(ECE_BUILD, ls="--", color="tab:orange", lw=1, label=f"BUILD ECE <= {ECE_BUILD}")
    ax2.set_ylabel("ECE", color="tab:red")
    ax2.set_ylim(0, 0.5)
    ax.set_title(f"Verdict stabilization ({eval_name})")
    lines1, labels1 = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax.legend(lines1 + lines2, labels1 + labels2, loc="lower right", fontsize=8)
    return ax
