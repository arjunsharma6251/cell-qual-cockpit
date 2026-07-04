"""Cross-lab transfer support for the early qualification call.

Two pieces, both born from the OOD finding in docs/early-call-study.md (transfer section):
- DQ_FEATURES: the protocol-invariant feature subset (within-cell DeltaQ(V)
  statistics). Protocol covariates (charge time, IR) fail catastrophically
  across labs; these transfer.
- Envelope guard: a verdict is only emitted when every input feature lies
  inside the training envelope (+/- margin). Outside it, the honest output is
  OUT-OF-ENVELOPE, not a confident number.

Also provides the Severson-style DeltaQ(V) featurizer for SNL-format cycle
pickles (per-cycle time series rather than Qdlin arrays).
"""

import pickle

import numpy as np

from .features import EPS

DQ_FEATURES = ["log_var_dq", "log_min_dq", "log_mean_dq"]
ENVELOPE_MARGIN = 0.10  # fraction of the training span allowed beyond min/max


def feature_envelope(train_df, margin=ENVELOPE_MARGIN):
    """{feature: (lo, hi)} from the training frame, widened by `margin`."""
    env = {}
    for col in train_df.columns:
        lo, hi = float(train_df[col].min()), float(train_df[col].max())
        pad = (hi - lo) * margin
        env[col] = (lo - pad, hi + pad)
    return env


def envelope_violations(row, env):
    """Feature names in `row` that fall outside the envelope."""
    return [k for k, (lo, hi) in env.items() if k in row and not (lo <= row[k] <= hi)]


def _discharge_qv(cyc, deadband=0.05, min_pts=20):
    """Discharge branch of one SNL cycle as (V ascending, Q)."""
    I = np.asarray(cyc["current_in_A"], float)
    V = np.asarray(cyc["voltage_in_V"], float)
    qd = np.asarray(cyc["discharge_capacity_in_Ah"], float)
    m = I < -deadband
    if m.sum() < min_pts:
        return None
    v, q = V[m], qd[m]
    order = np.argsort(v)
    return v[order], q[order]


def snl_dq_features(pkl_path, cyc_late=100, cyc_early=10, n_grid=1000):
    """DeltaQ(V) statistics from an SNL cell pickle, Severson-style.

    Q(V) at the early and late cycles is interpolated onto a shared voltage
    grid spanning the overlap of the two discharge branches. Returns None if
    either cycle is missing or has no usable discharge segment.
    """
    d = pickle.load(open(pkl_path, "rb"))
    cd = {c["cycle_number"]: c for c in d["cycle_data"]}
    if cyc_early not in cd or cyc_late not in cd:
        return None
    a, b = _discharge_qv(cd[cyc_early]), _discharge_qv(cd[cyc_late])
    if a is None or b is None:
        return None
    v_lo = max(a[0][0], b[0][0]) + 0.01
    v_hi = min(a[0][-1], b[0][-1]) - 0.01
    if v_hi <= v_lo:
        return None
    grid = np.linspace(v_lo, v_hi, n_grid)
    dq = np.interp(grid, *b) - np.interp(grid, *a)
    return {
        "log_var_dq": float(np.log10(np.var(dq) + EPS)),
        "log_min_dq": float(np.log10(abs(dq.min()) + EPS)),
        "log_mean_dq": float(np.log10(abs(dq.mean()) + EPS)),
    }
