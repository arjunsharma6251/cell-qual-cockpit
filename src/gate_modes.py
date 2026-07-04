"""Degradation-modes study evaluation: fleet-wide mode attribution + the four checks."""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from .dva import voltage_dispersion
from .modes import fit_cell_trajectory

CLOSURE_TOL = 0.03          # fade closure: median |cap err| <= 3% nominal
CLOSURE_CELL_FRAC = 0.80    # ... for >= 80% of NCA+NMC cells
RHO_MIN = 0.8               # mode sanity: dominant mode |spearman rho| >= 0.8
RHO_CELL_FRAC = 0.70        # ... for >= 70% of NCA+NMC cells
CONTRAST_MIN = 3.0          # NCA/NMC voltage dispersion >= 3x LFP


def evaluate_cell(cell):
    """Fit one cell's trajectory and reduce it to gate-relevant numbers."""
    df = fit_cell_trajectory(cell)
    out = {
        "cell_id": cell["cell_id"],
        "chemistry": cell["chemistry"],
        "temperature_C": cell["temperature_C"],
        "discharge_rate_C": cell["discharge_rate_C"],
        "n_diags": len(df),
    }
    cyc, qd = cell["fade"]
    out["fade_frac"] = float(1 - qd[-1] / qd[0]) if len(qd) else np.nan
    out["fade_per_kcycle"] = float(out["fade_frac"] / max(cyc[-1] - cyc[0], 1) * 1000)
    # fade at a fixed cycle count: comparable across cells with unequal test
    # lengths (whole-log rates are confounded by post-knee acceleration)
    out["fade_at_250"] = (
        float(1 - np.interp(250, cyc, qd) / qd[0]) if len(cyc) and cyc[-1] >= 250 else np.nan
    )
    diags = [d for d in cell["diagnostics"] if "charge" in d]
    if diags:
        out["v_dispersion"] = voltage_dispersion(*diags[0]["charge"])
    if len(df) >= 4:
        out["rmse_mV_med"] = float(df["rmse_V"].median() * 1000)
        if "closure_err" in df:
            out["closure_med"] = float(df["closure_err"].median())
        for mode in ["LLI", "LAM_pe", "LAM_ne"]:
            out[f"{mode}_end"] = float(df[mode].iloc[-1])
            out[f"rho_{mode}"] = float(spearmanr(df.index, df[mode]).statistic)
        ends = {m: abs(out[f"{m}_end"]) for m in ["LLI", "LAM_pe", "LAM_ne"]}
        dominant = max(ends, key=ends.get)
        out["dominant_mode"] = dominant
        out["rho_dominant"] = abs(out[f"rho_{dominant}"])
    return out, df


def gate_checks(fleet):
    """The four pre-registered checks on the fleet summary DataFrame."""
    hi_ni = fleet[fleet["chemistry"].isin(["NCA", "NMC"])]
    checks = {}

    ok = (hi_ni["closure_med"] <= CLOSURE_TOL)
    checks["fade_closure"] = {
        "frac_ok": float(ok.mean()), "need": CLOSURE_CELL_FRAC,
        "pass": bool(ok.mean() >= CLOSURE_CELL_FRAC),
    }
    ok = (hi_ni["rho_dominant"] >= RHO_MIN)
    checks["mode_sanity"] = {
        "frac_ok": float(ok.mean()), "need": RHO_CELL_FRAC,
        "pass": bool(ok.mean() >= RHO_CELL_FRAC),
    }
    disp = fleet.groupby("chemistry")["v_dispersion"].mean()
    ratio = float(min(disp.get("NCA", np.nan), disp.get("NMC", np.nan)) / disp.get("LFP", np.nan))
    checks["chemistry_contrast"] = {"ratio": ratio, "need": CONTRAST_MIN,
                                    "pass": bool(ratio >= CONTRAST_MIN)}

    # systematics from the measured fade series (attribution-independent).
    # Expected trends verified against Preger et al. 2020 (the original
    # pre-registration encoded two of them backwards from memory — disclosed
    # in docs/degradation-modes-study.md):
    # (a) LFP fade rate increases with temperature (15C < 35C)
    # (b) NCA fade decreases with increasing discharge rate
    # (c) NMC fade decreases with increasing temperature
    trends = {}
    lfp = fleet[fleet["chemistry"] == "LFP"].groupby("temperature_C")["fade_at_250"].mean()
    if 15 in lfp.index and 35 in lfp.index:
        trends["lfp_35C_vs_15C"] = float(lfp[35] / lfp[15])
    nca25 = fleet[(fleet["chemistry"] == "NCA") & (fleet["temperature_C"] == 25)].dropna(subset=["fade_at_250"])
    if nca25["discharge_rate_C"].nunique() >= 2:
        trends["nca_rate_fade_rho"] = float(
            spearmanr(nca25["discharge_rate_C"], nca25["fade_at_250"]).statistic)
    nmc = fleet[fleet["chemistry"] == "NMC"].dropna(subset=["fade_at_250"])
    if nmc["temperature_C"].nunique() >= 2:
        trends["nmc_temp_fade_rho"] = float(
            spearmanr(nmc["temperature_C"], nmc["fade_at_250"]).statistic)
    n_confirmed = sum([trends.get("lfp_35C_vs_15C", 0) > 1.0,
                       trends.get("nca_rate_fade_rho", 0) < -0.3,
                       trends.get("nmc_temp_fade_rho", 0) < -0.3])
    checks["condition_systematics"] = {**trends, "n_confirmed": n_confirmed,
                                       "pass": bool(n_confirmed >= 2)}
    return checks


def decide_p1(checks):
    """BUILD / RESCOPE / KILL for the diagnostics panel, per the study plan."""
    if all(c["pass"] for c in checks.values()):
        return "BUILD"
    if checks["chemistry_contrast"]["pass"]:
        return "RESCOPE"
    return "KILL"
