"""Differential voltage (dV/dQ) and incremental capacity (dQ/dV) analysis.

Curves are resampled onto uniform grids and smoothed with Savitzky-Golay
before differentiating; differentiating raw logged points amplifies sensor
quantization into garbage. Window sizes are in physical units (Ah / V) so the
same settings behave consistently across chemistries and capacities.
"""

import numpy as np
from scipy.signal import find_peaks, savgol_filter

N_GRID = 800


def _uniform_resample(x, y, n=N_GRID):
    """Strictly-increasing x, linear interpolation onto a uniform grid."""
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    keep = np.concatenate(([True], np.diff(x) > 1e-9))
    x, y = x[keep], y[keep]
    grid = np.linspace(x[0], x[-1], n)
    return grid, np.interp(grid, x, y)


def _savgol(y, grid, window_phys, poly=3):
    """Savitzky-Golay with window given in grid units (Ah or V)."""
    step = grid[1] - grid[0]
    w = max(poly + 2, int(round(window_phys / step)))
    if w % 2 == 0:
        w += 1
    w = min(w, len(y) - (1 - len(y) % 2))
    return savgol_filter(y, w, poly)


def dvdq(q, v, smooth_q_ah=0.05):
    """dV/dQ on a uniform Q grid. Returns (q_grid, dV/dQ)."""
    qg, vg = _uniform_resample(q, v)
    vg = _savgol(vg, qg, smooth_q_ah)
    return qg, np.gradient(vg, qg)


def dqdv(q, v, smooth_v_v=0.025, n=N_GRID):
    """dQ/dV on a uniform V grid (charge or discharge branch).

    V must be monotone along the CC segment (sorted internally). Returns
    (v_grid, dQ/dV).
    """
    v = np.asarray(v, float)
    q = np.asarray(q, float)
    order = np.argsort(v)
    vg, qg = _uniform_resample(v[order], q[order], n)
    qg = _savgol(qg, vg, smooth_v_v)
    return vg, np.gradient(qg, vg)


def ica_peak_stats(v_grid, dqdv_curve, min_prominence_frac=0.05):
    """Peak locations and prominences of a (smoothed) ICA curve."""
    y = np.abs(np.asarray(dqdv_curve, float))
    peaks, props = find_peaks(y, prominence=min_prominence_frac * y.max())
    return {
        "peak_voltages": v_grid[peaks],
        "peak_prominences": props["prominences"],
        "n_peaks": len(peaks),
    }


def voltage_dispersion(q, v, central_frac=0.8):
    """Width (V) of the voltage window holding the central `central_frac` of charge.

    The operational meaning of 'LFP diagnostics are muted': capacity moves in a
    ~0.1 V band, so voltage barely encodes state. Staged NCA/NMC spread the
    same charge over 0.5-1 V. Computed from the raw CC segment, no smoothing.
    """
    q = np.asarray(q, float)
    v = np.asarray(v, float)
    lo = (1 - central_frac) / 2
    q_norm = (q - q[0]) / max(q[-1] - q[0], 1e-9)
    v_lo = np.interp(lo, q_norm, v)
    v_hi = np.interp(1 - lo, q_norm, v)
    return float(abs(v_hi - v_lo))
