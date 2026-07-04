import numpy as np
import pytest

from src.dva import dqdv, dvdq, ica_peak_stats, voltage_dispersion
from src.modes import _v_model, fit_charge_branch
from src.ocp_refs import CHEMISTRY_REFS, u_graphite, u_kokam_ne, u_kokam_pe, u_lfp, u_nca, u_nmc811


def test_dvdq_constant_slope():
    q = np.linspace(0, 1, 600)
    v = 3.0 + 0.5 * q
    qg, dv = dvdq(q, v)
    mid = slice(100, -100)
    assert np.allclose(dv[mid], 0.5, atol=0.02)


def test_dqdv_constant_slope():
    q = np.linspace(0, 1, 600)
    v = 3.0 + 0.5 * q
    vg, ic = dqdv(q, v)
    mid = slice(100, -100)
    assert np.allclose(ic[mid], 2.0, atol=0.1)


def test_voltage_dispersion_sloped_vs_plateau():
    q = np.linspace(0, 1, 500)
    sloped = voltage_dispersion(q, 3.0 + 0.5 * q)
    plateau = voltage_dispersion(q, 3.3 + 0.01 * q)
    assert sloped == pytest.approx(0.4, abs=0.01)  # central 80% of a 0.5 V span
    assert plateau < 0.01
    assert sloped / plateau > 10


def test_ica_peak_stats_finds_peak():
    v = np.linspace(3.0, 4.0, 500)
    curve = 1.0 + 5.0 * np.exp(-((v - 3.5) ** 2) / (2 * 0.03**2))
    stats = ica_peak_stats(v, curve)
    assert stats["n_peaks"] >= 1
    assert any(abs(pv - 3.5) < 0.05 for pv in stats["peak_voltages"])


def test_ocp_references_physical_ranges():
    # probe each reference within its tabulated domain (outside it, linear
    # extrapolation is deliberate and unphysical by design)
    x = np.linspace(0.05, 0.95, 50)
    assert np.all((u_graphite(x) > 0.0) & (u_graphite(x) < 1.5))
    y_nmc = np.linspace(0.30, 0.95, 50)
    assert np.all((u_nmc811(y_nmc) > 3.0) & (u_nmc811(y_nmc) < 4.8))
    assert np.all(u_nca(np.linspace(0.40, 0.95, 50)) > 2.9)
    assert np.all((u_lfp(x) > 2.0) & (u_lfp(x) < 3.6))
    y_kok = np.linspace(0.35, 0.95, 50)
    assert np.all((u_kokam_pe(y_kok) > 3.0) & (u_kokam_pe(y_kok) < 4.6))
    assert np.all((u_kokam_ne(np.linspace(0.05, 0.95, 50)) >= 0.0))
    assert set(CHEMISTRY_REFS) == {"NCA", "NMC", "LFP", "KOKAM"}
    assert all(len(pair) == 2 for pair in CHEMISTRY_REFS.values())


def test_fit_charge_branch_roundtrip_nmc():
    """The fitter must recover parameters from a curve the model itself generated."""
    theta = [4.2, 3.9, 0.95, 0.03, 0.08]
    q = np.linspace(0.0, 2.4, 400)
    v = _v_model(theta, q, u_nmc811, u_graphite)
    fit = fit_charge_branch(q, v, "NMC", q_nom=3.0, n_starts=8)
    assert fit["rmse_V"] < 0.005
    assert fit["C_pe"] == pytest.approx(theta[0], rel=0.2)
    assert fit["C_ne"] == pytest.approx(theta[1], rel=0.2)
