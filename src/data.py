"""Loader for the Severson/MATR dataset (three 2017-2018 batches).

Raw batch files (~9 GB total) download from data.matr.io:
  https://data.matr.io/1/api/v1/file/5c86c0b5fa2ede00015ddf66/download  (2017-05-12)
  https://data.matr.io/1/api/v1/file/5c86bf13fa2ede00015ddd82/download  (2017-06-30)
  https://data.matr.io/1/api/v1/file/5c86bd64fa2ede00015ddbb2/download  (2018-04-12)
Save into data/ under their original *_batchdata_updated_struct_errorcorrect.mat names.

Parses the raw .mat (v7.3 / HDF5) batch files into per-cell dicts matching the
structure of the official rdbraatz repo's pickles, applies that repo's
canonical cell exclusions and batch1<-batch2 carry-over merge, and computes
cycle life from the capacity-fade curve.

To keep memory and cache size sane for the early-call study, per-cycle time series other
than Qdlin are dropped, and Qdlin is kept only for cycle indices <= MAX_QDLIN_CYCLE
(the gate only needs cycles 10..100). Summary arrays are kept in full.
"""

import os
import pickle

import h5py
import numpy as np

EOL_CAPACITY_AH = 0.88  # 80% of 1.1 Ah nominal
MAX_QDLIN_CYCLE = 105   # keep a little headroom past cycle 100

BATCH_FILES = {
    "b1": "2017-05-12_batchdata_updated_struct_errorcorrect.mat",
    "b2": "2017-06-30_batchdata_updated_struct_errorcorrect.mat",
    "b3": "2018-04-12_batchdata_updated_struct_errorcorrect.mat",
}

# Canonical exclusions from rdbraatz/.../Load Data.ipynb
BATCH1_EXCLUDE = ["b1c8", "b1c10", "b1c12", "b1c13", "b1c22"]  # never reach 80%
BATCH3_EXCLUDE = ["b3c37", "b3c2", "b3c23", "b3c32", "b3c42", "b3c43"]  # noisy channels

# Cells that started in batch1 and carried over into batch2 (Load Data.ipynb)
CARRYOVER_B2_KEYS = ["b2c7", "b2c8", "b2c9", "b2c15", "b2c16"]
CARRYOVER_B1_KEYS = ["b1c0", "b1c1", "b1c2", "b1c3", "b1c4"]
CARRYOVER_ADD_LEN = [662, 981, 1060, 208, 482]

SUMMARY_KEYS = ["IR", "QC", "QD", "Tavg", "Tmin", "Tmax", "chargetime", "cycle"]
_MAT_SUMMARY_KEYS = ["IR", "QCharge", "QDischarge", "Tavg", "Tmin", "Tmax", "chargetime", "cycle"]


def load_batch(mat_path, prefix, max_qdlin_cycle=MAX_QDLIN_CYCLE):
    """Parse one .mat batch file into {cell_key: cell_dict} (slim: Qdlin only)."""
    cells = {}
    with h5py.File(mat_path, "r") as f:
        batch = f["batch"]
        n = batch["summary"].shape[0]
        for i in range(n):
            cycle_life = float(np.squeeze(f[batch["cycle_life"][i, 0]][()]))
            policy = f[batch["policy_readable"][i, 0]][()].tobytes()[::2].decode()
            summ_grp = f[batch["summary"][i, 0]]
            summary = {
                out_k: np.hstack(summ_grp[mat_k][0, :].tolist())
                for out_k, mat_k in zip(SUMMARY_KEYS, _MAT_SUMMARY_KEYS)
            }
            cyc_grp = f[batch["cycles"][i, 0]]
            n_cyc = cyc_grp["Qdlin"].shape[0]
            cycles = {}
            for j in range(min(n_cyc, max_qdlin_cycle + 1)):
                qdlin = np.hstack(f[cyc_grp["Qdlin"][j, 0]][()])
                cycles[str(j)] = {"Qdlin": qdlin}
            cells[f"{prefix}c{i}"] = {
                "cycle_life_stored": cycle_life,
                "charge_policy": policy,
                "summary": summary,
                "cycles": cycles,
            }
    return cells


def _merge_carryover(batch1, batch2):
    """Move batch2 continuation data onto the originating batch1 cells."""
    for b1k, b2k, add in zip(CARRYOVER_B1_KEYS, CARRYOVER_B2_KEYS, CARRYOVER_ADD_LEN):
        c1, c2 = batch1[b1k], batch2[b2k]
        c1["cycle_life_stored"] = c1["cycle_life_stored"] + add
        n1 = len(c1["summary"]["cycle"])
        for k in c1["summary"]:
            if k == "cycle":
                c1["summary"][k] = np.hstack((c1["summary"][k], c2["summary"][k] + n1))
            else:
                c1["summary"][k] = np.hstack((c1["summary"][k], c2["summary"][k]))
        # continuation cycles are all past MAX_QDLIN_CYCLE; nothing to merge in 'cycles'
        del batch2[b2k]


def compute_cycle_life(cell, threshold=EOL_CAPACITY_AH):
    """First cycle number where discharge capacity drops below threshold.

    Skips the first cycle (known measurement artifacts) and requires the next
    cycle to also be below threshold (or be the last cycle) to reject single
    noise dips. Most cells' logs stop AT EOL with QD still a hair above 0.88
    (0.8801-0.8809), so when no crossing exists the stored cycle_life from the
    .mat (the paper's official value, = end of log + 1) is used instead.
    """
    qd = np.asarray(cell["summary"]["QD"], dtype=float)
    cyc = np.asarray(cell["summary"]["cycle"], dtype=float)
    below = qd < threshold
    for i in range(1, len(qd)):
        if below[i] and (i == len(qd) - 1 or below[i + 1]):
            return float(cyc[i])
    stored = float(cell["cycle_life_stored"])
    return stored if np.isfinite(stored) else float("nan")


def build_dataset(data_dir, cache=True, verbose=True):
    """Load all three batches, apply exclusions + merge, compute cycle_life.

    Returns an ordered {cell_key: cell_dict} with batch1, batch2, batch3 cells
    in the canonical order (matches the paper's split indices).
    """
    cache_path = os.path.join(data_dir, "processed_slim.pkl")
    if cache and os.path.exists(cache_path):
        with open(cache_path, "rb") as fp:
            return pickle.load(fp)

    batches = {}
    for prefix, fname in BATCH_FILES.items():
        path = os.path.join(data_dir, fname)
        if verbose:
            print(f"parsing {fname} ...")
        batches[prefix] = load_batch(path, prefix)

    for k in BATCH1_EXCLUDE:
        del batches["b1"][k]
    _merge_carryover(batches["b1"], batches["b2"])
    for k in BATCH3_EXCLUDE:
        del batches["b3"][k]

    bat_dict = {**batches["b1"], **batches["b2"], **batches["b3"]}
    for key, cell in bat_dict.items():
        cell["cycle_life"] = compute_cycle_life(cell)
    if verbose:
        n = len(bat_dict)
        n1, n2, n3 = (len(batches[p]) for p in ("b1", "b2", "b3"))
        print(f"cells: {n} total (b1={n1}, b2={n2}, b3={n3})")

    if cache:
        with open(cache_path, "wb") as fp:
            pickle.dump(bat_dict, fp)
    return bat_dict
