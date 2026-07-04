"""Loader for the Sandia/SNL dataset (BatteryLife processed pickles).

Each pickle is one cell: metadata + `cycle_data`, a list of per-cycle time
series. Most cycles are logged coarsely (~80 samples); periodic diagnostic
cycles at 0.5C are dense (~1200 samples) and drive the DVA/ICA engine.

Cell IDs encode test conditions: SNL_18650_{chem}_{T}C_{dod_lo}-{dod_hi}_
{charge_rate}-{discharge_rate}C_{replicate}.
"""

import glob
import os
import pickle
import re

import numpy as np

DENSE_POINTS_MIN = 300   # samples; separates diagnostic from aging cycles
SEG_POINTS_MIN = 100     # minimum samples for a usable CC segment
CURRENT_DEADBAND_A = 0.05

_ID_RE = re.compile(
    r"SNL_18650_(?P<chem>[A-Z]+)_(?P<temp>\d+)C_(?P<dod_lo>\d+)-(?P<dod_hi>\d+)_"
    r"(?P<c_chg>[\d.]+)-(?P<c_dis>[\d.]+)C_(?P<rep>\w+)$"
)


def parse_cell_id(cell_id):
    """Decode chemistry / temperature / DOD window / rates from a cell id."""
    m = _ID_RE.match(cell_id)
    if not m:
        raise ValueError(f"unparseable cell_id: {cell_id}")
    g = m.groupdict()
    return {
        "chemistry": g["chem"],
        "temperature_C": int(g["temp"]),
        "dod_lo": int(g["dod_lo"]),
        "dod_hi": int(g["dod_hi"]),
        "charge_rate_C": float(g["c_chg"]),
        "discharge_rate_C": float(g["c_dis"]),
        "replicate": g["rep"],
    }


def _cc_segments(cyc):
    """CC charge and CC discharge segments of one cycle as (Q, V) arrays.

    Charge: positive current, before the CV taper (current within 10% of the
    median charge current). Discharge: negative current. Q is the segment's
    own capacity counter, re-zeroed at segment start.
    """
    I = np.asarray(cyc["current_in_A"], float)
    V = np.asarray(cyc["voltage_in_V"], float)
    qc = np.asarray(cyc["charge_capacity_in_Ah"], float)
    qd = np.asarray(cyc["discharge_capacity_in_Ah"], float)

    out = {}
    chg = I > CURRENT_DEADBAND_A
    if chg.sum() >= SEG_POINTS_MIN:
        i_med = np.median(I[chg])
        cc = chg & (I > 0.9 * i_med)
        q, v = qc[cc], V[cc]
        order = np.argsort(q)
        out["charge"] = (q[order] - q[order][0], v[order])
    dis = I < -CURRENT_DEADBAND_A
    if dis.sum() >= SEG_POINTS_MIN:
        q, v = qd[dis], V[dis]
        order = np.argsort(q)
        out["discharge"] = (q[order] - q[order][0], v[order])
    return out


def load_cell(path):
    """One cell pickle -> slim dict: conditions, fade series, diagnostics."""
    raw = pickle.load(open(path, "rb"))
    cond = parse_cell_id(raw["cell_id"])
    fade_cycles, fade_qd = [], []
    diagnostics = []
    last_sig = None
    for cyc in raw["cycle_data"]:
        qd = cyc["discharge_capacity_in_Ah"]
        if len(qd):
            fade_cycles.append(cyc["cycle_number"])
            fade_qd.append(max(qd))
        if len(cyc["voltage_in_V"]) > DENSE_POINTS_MIN:
            # the source pickles contain byte-identical duplicated cycles
            sig = (len(cyc["voltage_in_V"]), float(np.sum(cyc["voltage_in_V"])),
                   float(np.sum(cyc["charge_capacity_in_Ah"])))
            if sig == last_sig:
                continue
            last_sig = sig
            segs = _cc_segments(cyc)
            if segs:
                segs["cycle_number"] = cyc["cycle_number"]
                diagnostics.append(segs)
    return {
        "cell_id": raw["cell_id"],
        **cond,
        "nominal_capacity_Ah": raw["nominal_capacity_in_Ah"],
        "fade": (np.array(fade_cycles), np.array(fade_qd)),
        "diagnostics": diagnostics,
    }


def load_snl(data_dir="data/snl/SNL", cache=True, verbose=True):
    """Load all SNL cells into {cell_id: slim dict}, cached."""
    cache_path = os.path.join(os.path.dirname(data_dir.rstrip("/")), "snl_slim.pkl")
    if cache and os.path.exists(cache_path):
        with open(cache_path, "rb") as fp:
            return pickle.load(fp)
    cells = {}
    for path in sorted(glob.glob(os.path.join(data_dir, "*.pkl"))):
        cell = load_cell(path)
        cells[cell["cell_id"]] = cell
        if verbose:
            print(f"{cell['cell_id']}: {len(cell['diagnostics'])} diagnostic cycles")
    if cache:
        with open(cache_path, "wb") as fp:
            pickle.dump(cells, fp)
    return cells
