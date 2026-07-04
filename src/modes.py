"""Degradation-mode attribution via Dahn-style electrode alignment.

Fit the CC charge branch of each diagnostic cycle as

    V(Q) = U_pe(y0 - Q/C_pe) - U_ne(x0 + Q/C_ne) + eta

with theta = [C_pe, C_ne, y0, x0, eta]: electrode capacities (Ah), start-of-
charge stoichiometries, and a lumped polarization offset. Tracking theta over
life gives the modes:

    LAM_pe = 1 - C_pe/C_pe(ref)      loss of active positive material
    LAM_ne = 1 - C_ne/C_ne(ref)      loss of active negative material
    LLI    = 1 - n_Li/n_Li(ref),     n_Li = y0*C_pe + x0*C_ne  (Ah of cyclable Li
                                     referenced to the fully-discharged state)

Closure test (out-of-branch): freeze C_pe/C_ne from the charge fit, refit only
the composition offsets + eta on the discharge branch, then compare the
model's predicted capacity-to-Vmin against the measured discharge capacity.
"""

import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from scipy.signal import savgol_filter

from .ocp_refs import CHEMISTRY_REFS

N_FIT_POINTS = 250
SIGMA_V = 0.010          # V; weight scale for the voltage residual
DVDQ_WEIGHT_FRAC = 0.15  # of median |dV/dQ|; weight scale for the derivative
TRIM_FRAC = 0.02         # trim segment ends (CV transition, deadband spikes)


def _prep_segment(q, v, n=N_FIT_POINTS):
    """Trim ends, resample onto a uniform Q grid, smooth V lightly."""
    q = np.asarray(q, float)
    v = np.asarray(v, float)
    keep = np.concatenate(([True], np.diff(q) > 1e-9))
    q, v = q[keep], v[keep]
    lo, hi = q[0] + TRIM_FRAC * (q[-1] - q[0]), q[-1] - TRIM_FRAC * (q[-1] - q[0])
    grid = np.linspace(lo, hi, n)
    vg = np.interp(grid, q, v)
    return grid, savgol_filter(vg, 15, 3)


def _v_model(theta, q, u_pe, u_ne, sign=+1):
    c_pe, c_ne, y0, x0, eta = theta
    y = y0 - sign * q / c_pe
    x = x0 + sign * q / c_ne
    return u_pe(y) - u_ne(x) + eta


def _residuals(theta, q, v, dvdq_data, sigma_d, u_pe, u_ne):
    """Joint V(Q) + dV/dQ residual. The derivative kills the eta/reference-
    bias degeneracy and lets graphite staging features anchor C_ne."""
    vm = _v_model(theta, q, u_pe, u_ne)
    dm = np.gradient(vm, q)
    return np.concatenate([(vm - v) / SIGMA_V, (dm - dvdq_data) / sigma_d])


def _bounds(q_nom):
    # electrode capacities in commercial 18650s are ~1.0-1.8x cell capacity;
    # looser bounds let the optimizer flatten the model into degenerate fits
    lo = [0.9 * q_nom, 0.9 * q_nom, 0.50, 0.00, 0.00]
    hi = [2.2 * q_nom, 2.2 * q_nom, 1.00, 0.30, 0.25]
    return lo, hi


def _prior_scales(q_nom):
    """Allowed drift per RPT (~130 cycles) before the continuity penalty bites."""
    return np.array([0.05 * q_nom, 0.05 * q_nom, 0.02, 0.02, 0.02])


def fit_charge_branch(q, v, chemistry, q_nom, x_init=None, prior=None, n_starts=8, seed=0):
    """Fit theta on a CC charge segment. Returns dict with params + rmse.

    x_init warm-starts the fit; `prior` adds a quadratic continuity penalty
    pulling toward the previous diagnostic's solution — the electrode-alignment
    problem is multimodal, and without it trajectories hop between local-minimum
    families instead of tracking slow degradation.

    An endpoint residual pins the model to the measured end-of-charge voltage
    at the full (untrimmed) CC capacity: without it, a shape-only fit can
    'explain' an aged, shorter curve without moving any parameter — the lost
    capacity itself has to be accounted for by the electrode windows.
    """
    u_pe, u_ne = CHEMISTRY_REFS[chemistry]
    q_end, v_end = float(np.asarray(q, float)[-1]), float(np.asarray(v, float)[-1])
    qg, vg = _prep_segment(q, v)
    dvdq_data = np.gradient(vg, qg)
    sigma_d = DVDQ_WEIGHT_FRAC * max(np.median(np.abs(dvdq_data)), 1e-6)

    def objective(th):
        base = _residuals(th, qg, vg, dvdq_data, sigma_d, u_pe, u_ne)
        v_end_model = _v_model(th, np.array([q_end]), u_pe, u_ne)[0]
        base = np.concatenate([base, [(v_end_model - v_end) / 0.003]])
        if prior is not None:
            base = np.concatenate([base, (np.asarray(th) - prior) / _prior_scales(q_nom)])
        return base

    lo, hi = _bounds(q_nom)
    rng = np.random.RandomState(seed)
    starts = [np.array([1.4 * q_nom, 1.3 * q_nom, 0.95, 0.02, 0.05])]
    if x_init is not None:
        starts.insert(0, np.array(x_init))
    for _ in range(n_starts - len(starts)):
        s = np.array(lo) + rng.rand(5) * (np.array(hi) - np.array(lo))
        s[2] = 0.80 + 0.19 * rng.rand()
        starts.append(s)

    best = None
    for s in starts:
        res = least_squares(objective, np.clip(s, lo, hi), bounds=(lo, hi), method="trf")
        if best is None or res.cost < best.cost:
            best = res
    c_pe, c_ne, y0, x0, eta = best.x
    vm = _v_model(best.x, qg, u_pe, u_ne)
    return {
        "C_pe": c_pe, "C_ne": c_ne, "y0": y0, "x0": x0, "eta": eta,
        "n_Li": y0 * c_pe + x0 * c_ne,
        "rmse_V": float(np.sqrt(np.mean((vm - vg) ** 2))),
        "_theta": best.x,
    }


def discharge_closure(q_dis, v_dis, fit, chemistry, v_min, q_nom):
    """Out-of-branch test: reuse C_pe/C_ne, refit offsets on discharge.

    Returns (capacity_error_frac, rmse_V): the model's capacity-to-v_min vs
    the measured discharge capacity, as a fraction of nominal.
    """
    u_pe, u_ne = CHEMISTRY_REFS[chemistry]
    q, v = _prep_segment(q_dis, v_dis)
    c_pe, c_ne = fit["C_pe"], fit["C_ne"]

    def model(th, qq):
        y0d, x0d, eta = th
        return _v_model([c_pe, c_ne, y0d, x0d, eta], qq, u_pe, u_ne, sign=-1)

    # discharge starts fully charged: cathode delithiated, anode lithiated
    y0d_guess = float(np.clip(fit["y0"] - q.max() / c_pe, 0.05, 0.95))
    x0d_guess = float(np.clip(fit["x0"] + q.max() / c_ne, 0.05, 0.95))
    res = least_squares(
        lambda th: model(th, q) - v,
        [y0d_guess, x0d_guess, -0.05],
        bounds=([0.0, 0.0, -0.4], [1.0, 1.0, 0.0]), method="trf",
    )
    # predicted capacity: where the fitted discharge model crosses v_min
    q_grid = np.linspace(0, 1.6 * q.max(), 2000)
    v_grid = model(res.x, q_grid)
    below = np.where(v_grid <= v_min)[0]
    q_pred = q_grid[below[0]] if len(below) else q_grid[-1]
    cap_err = float(abs(q_pred - q.max()) / q_nom)
    rmse = float(np.sqrt(2 * res.cost / len(q)))
    return cap_err, rmse


def fit_cell_trajectory(cell, v_min=None, verbose=False):
    """Fit every diagnostic cycle of one cell -> mode trajectory DataFrame."""
    chem = cell["chemistry"]
    q_nom = cell["nominal_capacity_Ah"]
    v_min = v_min if v_min is not None else {"NCA": 2.5, "NMC": 2.0, "LFP": 2.0, "KOKAM": 2.7}[chem]
    rows = []
    theta_prev = None
    for diag in cell["diagnostics"]:
        if "charge" not in diag:
            continue
        q, v = diag["charge"]
        if q[-1] < 0.3 * q_nom:  # partial windows can't constrain the model
            continue
        if theta_prev is None:
            fit = fit_charge_branch(q, v, chem, q_nom, n_starts=20)  # BOL anchor
        else:
            fit = fit_charge_branch(q, v, chem, q_nom, x_init=theta_prev,
                                    prior=theta_prev, n_starts=4)
        theta_prev = fit.pop("_theta")
        row = {"cycle": diag["cycle_number"], **fit}
        if "discharge" in diag:
            qd, vd = diag["discharge"]
            if qd[-1] > 0.3 * q_nom:
                cap_err, rmse_d = discharge_closure(qd, vd, fit, chem, v_min, q_nom)
                row["closure_err"] = cap_err
                row["rmse_V_dis"] = rmse_d
        rows.append(row)
        if verbose:
            print(f"  cyc {row['cycle']}: rmse={fit['rmse_V']*1000:.1f} mV")
    df = pd.DataFrame(rows).set_index("cycle").sort_index()
    if len(df):
        ref = df.iloc[0]
        df["LAM_pe"] = 1 - df["C_pe"] / ref["C_pe"]
        df["LAM_ne"] = 1 - df["C_ne"] / ref["C_ne"]
        df["LLI"] = 1 - df["n_Li"] / ref["n_Li"]
    return df
