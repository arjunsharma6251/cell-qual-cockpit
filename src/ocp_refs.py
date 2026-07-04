"""Half-cell open-circuit-potential references, per chemistry.

Sources (all via PyBaMM parameter sets, files vendored in refs/ocp/):
- graphite + NMC811: Chen et al. 2020, J. Electrochem. Soc. 167 080534 (LG M50).
- NCA: Kim et al. 2011 (PyBaMM NCA_Kim2011 dataset).
- LFP: Afshar et al. 2017 (arXiv:1709.03970) closed form, via PyBaMM Prada2013.

Approximations carried honestly: the graphite reference is the LG M50 blend
(contains SiOx) applied to all three cells' pure-graphite anodes, and 0.5C
curves are not true OCV. We track *changes* in fitted parameters over life,
which is far less sensitive to reference bias than absolute values.
"""

import os

import numpy as np

_REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "refs", "ocp")


def _load_csv(name):
    rows = []
    with open(os.path.join(_REF_DIR, name), encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            a, b = line.split(",")
            rows.append((float(a), float(b)))
    arr = np.array(sorted(rows))
    return arr[:, 0], arr[:, 1]


def _interp_extrap(x, xp, fp):
    """np.interp with linear extrapolation using edge slopes (flat clipping
    kills optimizer gradients at the stoichiometry limits)."""
    y = np.interp(x, xp, fp)
    lo, hi = x < xp[0], x > xp[-1]
    if lo.any():
        s = (fp[1] - fp[0]) / (xp[1] - xp[0])
        y[lo] = fp[0] + s * (x[lo] - xp[0])
    if hi.any():
        s = (fp[-1] - fp[-2]) / (xp[-1] - xp[-2])
        y[hi] = fp[-1] + s * (x[hi] - xp[-1])
    return y


_GR_CHEN_X, _GR_CHEN_U = _load_csv("graphite_LGM50_ocp_Chen2020.csv")
_GR_ECK_X, _GR_ECK_U = _load_csv("graphite_ocp_Ecker2015.csv")
_NMC_X, _NMC_U = _load_csv("nmc_LGM50_ocp_Chen2020.csv")
_NCA_X, _NCA_U = _load_csv("nca_ocp_Kim2011_data.csv")
# matched Kokam half-cell curves (SLIDE, Battery Intelligence Lab, BSD-3) —
# same manufacturer NMC family as the Oxford BDD-1 cells
_KOK_PE_X, _KOK_PE_U = _load_csv("Kokam_OCV_NMC.csv")
_KOK_NE_X, _KOK_NE_U = _load_csv("Kokam_OCV_C.csv")


def u_graphite(x):
    """Default anode reference: Ecker2015 pure graphite. The SNL cells all use
    graphite anodes; the Chen2020 blend (SiOx) misfits the low-SOC knee."""
    return _interp_extrap(np.asarray(x, float), _GR_ECK_X, _GR_ECK_U)


def u_graphite_chen(x):
    return _interp_extrap(np.asarray(x, float), _GR_CHEN_X, _GR_CHEN_U)


def u_nmc811(y):
    return _interp_extrap(np.asarray(y, float), _NMC_X, _NMC_U)


def u_nca(y):
    return _interp_extrap(np.asarray(y, float), _NCA_X, _NCA_U)


def u_lfp(y):
    """Afshar et al. 2017 closed form (as used by PyBaMM Prada2013)."""
    y = np.asarray(y, float)
    return 3.4077 - 0.020269 * y + 0.5 * np.exp(-150 * y) - 0.9 * np.exp(-30 * (1 - y))


def u_kokam_pe(y):
    return _interp_extrap(np.asarray(y, float), _KOK_PE_X, _KOK_PE_U)


def u_kokam_ne(x):
    return _interp_extrap(np.asarray(x, float), _KOK_NE_X, _KOK_NE_U)


# chemistry -> (positive-electrode, negative-electrode) reference pair.
# Generic chemistries share the Ecker graphite; KOKAM uses matched curves —
# the difference is decisive (docs/mode-identifiability-study.md: dominant-mode sanity 1/8 -> 8/8).
CHEMISTRY_REFS = {
    "NCA": (u_nca, u_graphite),
    "NMC": (u_nmc811, u_graphite),
    "LFP": (u_lfp, u_graphite),
    "KOKAM": (u_kokam_pe, u_kokam_ne),
}
