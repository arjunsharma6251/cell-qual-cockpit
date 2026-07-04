"""Early-cycle features: DeltaQ(V) statistics plus a small set of auxiliaries.

Qdlin is discharge capacity interpolated onto a fixed shared voltage grid, so
Qdlin[late] - Qdlin[early] is a well-defined DeltaQ(V) vector (Severson 2019).
Cycle-dict keys are 0-based row indices ('0' = first cycle); the one-cycle
offset vs. the paper's 1-based numbering is immaterial and applied uniformly.
"""

import numpy as np
import pandas as pd

EPS = 1e-12

FEATURE_NAMES = [
    "log_var_dq",
    "log_min_dq",
    "log_mean_dq",
    "fade_slope",
    "qd_cycle2",
    "avg_chargetime_first5",
    "ir_cycle2",
]


def delta_q_features(cell, cyc_late=100, cyc_early=10):
    """DeltaQ(V) = Qdlin[late] - Qdlin[early] on the shared voltage grid."""
    q_late = np.asarray(cell["cycles"][str(cyc_late)]["Qdlin"])
    q_early = np.asarray(cell["cycles"][str(cyc_early)]["Qdlin"])
    dq = q_late - q_early
    return {
        "log_var_dq": np.log10(np.var(dq) + EPS),
        "log_min_dq": np.log10(np.abs(dq.min()) + EPS),
        "log_mean_dq": np.log10(np.abs(dq.mean()) + EPS),
    }


def aux_features(cell, cutoff=100):
    """Small auxiliary set from summary data up to the cutoff cycle."""
    summ = cell["summary"]
    qd = np.asarray(summ["QD"], dtype=float)
    cyc = np.asarray(summ["cycle"], dtype=float)
    ct = np.asarray(summ["chargetime"], dtype=float)
    ir = np.asarray(summ["IR"], dtype=float)

    m = (cyc >= 2) & (cyc <= cutoff)
    slope = np.polyfit(cyc[m], qd[m], 1)[0]
    return {
        "fade_slope": slope,
        "qd_cycle2": qd[cyc == 2][0],
        "avg_chargetime_first5": float(np.mean(ct[(cyc >= 1) & (cyc <= 5)])),
        "ir_cycle2": ir[cyc == 2][0],
    }


def featurize(bat_dict, cutoff=100, cyc_early=10):
    """Feature DataFrame (index = cell key) using data up to `cutoff` cycles."""
    rows = {}
    for key, cell in bat_dict.items():
        row = {}
        row.update(delta_q_features(cell, cyc_late=cutoff, cyc_early=cyc_early))
        row.update(aux_features(cell, cutoff=cutoff))
        rows[key] = row
    return pd.DataFrame.from_dict(rows, orient="index")[FEATURE_NAMES]
