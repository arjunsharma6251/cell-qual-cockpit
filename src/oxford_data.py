"""Loader for the Oxford Battery Degradation Dataset 1 (Birkl & Howey 2017).

8 Kokam SLPB533459H4 pouch cells (740 mAh, LCO/NMC-blend cathode, graphite
anode) cycled at 40 C with characterisation every 100 drive cycles, including
full pseudo-OCV charge/discharge at C/18.5 (40 mA) — diagnostics-grade curves.

Cells are mapped into the same slim structure as src.snl_data so
src.modes.fit_cell_trajectory runs unchanged. Cathode reference caveat: the
Kokam blend has no vendored OCP; fits use the NMC reference as the nearest
available, which is part of what the the identifiability follow-up experiment measures.

Cite: doi:10.5287/bodleian:KO2kdmYGg and Birkl, PhD thesis, Oxford, 2017.
"""

import os
import pickle

import numpy as np
from scipy.io import loadmat

Q_NOM_AH = 0.74
V_MIN = 2.7  # Kokam SLPB533459H4 discharge cutoff


def _seg(node):
    """One branch (OCVch/OCVdc) -> (Q ascending in Ah, V)."""
    q = np.asarray(node["q"], float).ravel() / 1000.0  # mAh -> Ah
    v = np.asarray(node["v"], float).ravel()
    q = np.abs(q - q[0])
    order = np.argsort(q)
    return q[order], v[order]


def load_oxford(mat_path, cache=True, verbose=True):
    """-> {cell_id: slim dict compatible with fit_cell_trajectory}."""
    cache_path = os.path.join(os.path.dirname(mat_path), "oxford_slim.pkl")
    if cache and os.path.exists(cache_path):
        with open(cache_path, "rb") as fp:
            return pickle.load(fp)

    raw = loadmat(mat_path, simplify_cells=True)
    cells = {}
    for cell_key in sorted(k for k in raw if k.startswith("Cell")):
        diags, fade_c, fade_q = [], [], []
        for cyc_key in sorted(raw[cell_key], key=lambda s: int(s.replace("cyc", ""))):
            node = raw[cell_key][cyc_key]
            n = int(cyc_key.replace("cyc", ""))
            entry = {"cycle_number": n}
            if "OCVch" in node:
                entry["charge"] = _seg(node["OCVch"])
            if "OCVdc" in node:
                entry["discharge"] = _seg(node["OCVdc"])
                fade_c.append(n)
                fade_q.append(float(entry["discharge"][0].max()))
            if len(entry) > 1:
                diags.append(entry)
        cid = f"OX_{cell_key}"
        cells[cid] = {
            "cell_id": cid,
            "chemistry": "KOKAM",  # matched SLIDE half-cell references
            "temperature_C": 40,
            "discharge_rate_C": 0.054,  # C/18.5 diagnostics
            "nominal_capacity_Ah": Q_NOM_AH,
            "fade": (np.array(fade_c), np.array(fade_q)),
            "diagnostics": diags,
        }
        if verbose:
            print(f"{cid}: {len(diags)} pseudo-OCV diagnostics, "
                  f"fade {fade_q[0]:.3f}->{fade_q[-1]:.3f} Ah")
    if cache:
        with open(cache_path, "wb") as fp:
            pickle.dump(cells, fp)
    return cells
