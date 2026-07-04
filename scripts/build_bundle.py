"""Precompute the cockpit data bundle from the gated P0/P1 pipelines.

Everything the frontend shows is computed here, once, into
app/static/cockpit_data.json. No model fitting at request time.
"""

import json
import os
import pickle
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import glob

from src.calibration import cvap_predict, abstain_call
from src.data import build_dataset
from src.dva import dqdv, dvdq, voltage_dispersion
from src.features import featurize
from src.labels import make_labels
from src.model import EarlyVerdictModel
from src.snl_data import load_snl
from src.split import canonical_split
from src.transfer import DQ_FEATURES, feature_envelope, envelope_violations, snl_dq_features

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "static", "cockpit_data.json")
CUTOFFS = [40, 50, 60, 80, 100]


def _ds(x, y, n=150):
    """Downsample a series to <= n points."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) <= n:
        idx = np.arange(len(x))
    else:
        idx = np.linspace(0, len(x) - 1, n).astype(int)
    return [round(float(v), 4) for v in x[idx]], [round(float(v), 4) for v in y[idx]]


def build_qualification():
    bd = build_dataset(os.path.join(ROOT, "data"), verbose=False)
    labels, T = make_labels(bd, threshold=700, verbose=False)
    train, primary, secondary = canonical_split(bd.keys())
    split_of = {}
    for k in train:
        split_of[k] = "train"
    for k in primary:
        split_of[k] = "primary"
    for k in secondary:
        split_of[k] = "secondary"

    # production model: protocol-invariant DeltaQ(V) features only — the full
    # feature set fails 0/9 across labs (docs/early-call-study.md (transfer section))
    feats = featurize(bd, cutoff=100)[DQ_FEATURES]
    X_tr = feats.loc[train].values
    y_tr = np.array([labels[k] for k in train])
    model = EarlyVerdictModel().fit(X_tr, y_tr)
    envelope = feature_envelope(feats.loc[train])

    # export the model for in-browser scoring (TRY IT tab): scaler + logistic
    # coefficients + the isotonic map's knots + per-fold CVAP calibration sets
    from sklearn.model_selection import StratifiedKFold

    from src.calibration import _base_model

    def _pipe_params(pipe):
        sc, lr = pipe.named_steps["scaler"], pipe.named_steps["clf"]
        return {"mean": [round(float(v), 8) for v in sc.mean_],
                "scale": [round(float(v), 8) for v in sc.scale_],
                "coef": [round(float(v), 8) for v in lr.coef_[0]],
                "intercept": round(float(lr.intercept_[0]), 8)}

    cvap_folds = []
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    for tr_idx, cal_idx in skf.split(X_tr, y_tr):
        m = _base_model(random_state=0)
        m.fit(X_tr[tr_idx], y_tr[tr_idx])
        cvap_folds.append({
            **_pipe_params(m),
            "cal_scores": [round(float(v), 8) for v in m.decision_function(X_tr[cal_idx])],
            "cal_labels": [int(v) for v in y_tr[cal_idx]],
        })
    model_export = {
        "features": DQ_FEATURES,
        "point": {**_pipe_params(model.base_),
                  "iso_x": [round(float(v), 8) for v in model.cal_.X_thresholds_],
                  "iso_y": [round(float(v), 8) for v in model.cal_.y_thresholds_]},
        "cvap": cvap_folds,
    }

    # sample CSV for the TRY IT tab: a real cross-lab cell's discharge branches
    sample_path = os.path.join(ROOT, "app", "static", "sample_cell.csv")
    sample_src = os.path.join(ROOT, "data", "snl", "SNL", "SNL_18650_LFP_25C_0-100_0.5-1C_a.pkl")
    if os.path.exists(sample_src):
        import pickle as _pkl
        _raw = _pkl.load(open(sample_src, "rb"))
        with open(sample_path, "w") as fp:
            fp.write("cycle,voltage_v,discharge_capacity_ah\n")
            for cyc in _raw["cycle_data"]:
                if cyc["cycle_number"] not in (10, 100):
                    continue
                I = np.asarray(cyc["current_in_A"], float)
                V = np.asarray(cyc["voltage_in_V"], float)
                Q = np.asarray(cyc["discharge_capacity_in_Ah"], float)
                m = I < -0.05
                for v, q in zip(V[m], Q[m]):
                    fp.write(f"{cyc['cycle_number']},{v:.5f},{q:.6f}\n")

    test_keys = primary + secondary
    p_all = {k: float(p) for k, p in zip(feats.index, model.predict_proba(feats.values)[:, 1])}
    _, p0i, p1i = cvap_predict(X_tr, y_tr, feats.loc[test_keys].values, seed=0)
    call = abstain_call(p0i, p1i)
    interval = {k: (float(a), float(b), int(c)) for k, a, b, c in zip(test_keys, p0i, p1i, call)}

    callable_curve = []
    evidence = {k: [] for k in test_keys}
    for cutoff in CUTOFFS:
        f = featurize(bd, cutoff=cutoff)[DQ_FEATURES]
        Xa = f.loc[train].values
        m_c = EarlyVerdictModel().fit(Xa, y_tr)
        pc = m_c.predict_proba(f.loc[test_keys].values)[:, 1]
        _, a, b = cvap_predict(Xa, y_tr, f.loc[test_keys].values, seed=0)
        c = abstain_call(a, b)
        yb = np.array([labels[k] for k in test_keys])
        called = c != -1
        callable_curve.append({
            "cutoff": cutoff,
            "called_frac": round(float(called.mean()), 3),
            "acc_on_called": round(float(np.mean(c[called] == yb[called])), 3) if called.any() else None,
        })
        for k, pv, av, bv, cv in zip(test_keys, pc, a, b, c):
            evidence[k].append({"cutoff": cutoff, "p": round(float(pv), 3),
                                "lo": round(float(av), 3), "hi": round(float(bv), 3),
                                "call": int(cv)})

    # cross-lab transfer cells: SNL LFP, same A123 cell model, different lab
    transfer_cells = []
    snl_slim = load_snl(os.path.join(ROOT, "data", "snl", "SNL"), verbose=False)
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "snl", "SNL", "SNL_18650_LFP_*.pkl"))):
        ft = snl_dq_features(path)
        if ft is None:
            continue
        cid = os.path.basename(path).replace(".pkl", "")
        viol = envelope_violations(ft, envelope)
        X = np.array([[ft[c] for c in DQ_FEATURES]])
        p = float(model.predict_proba(X)[:, 1][0])
        _, a, b = cvap_predict(X_tr, y_tr, X, seed=0)
        c = int(abstain_call(a, b)[0])
        verdict = "out-of-envelope" if viol else {1: "pass", 0: "fail", -1: "keep-testing"}[c]
        slim = snl_slim[cid]
        cyc, qd = _ds(*slim["fade"], 150)
        transfer_cells.append({
            "id": cid, "split": "transfer", "policy": "SNL 0.5C chg / " + f"{slim['discharge_rate_C']}C dis",
            "cycle_life": None, "label": 1, "p_pass": round(p, 3),
            "p_lo": round(float(a[0]), 3), "p_hi": round(float(b[0]), 3),
            "verdict": verdict, "violations": viol,
            "fade": {"cycle": cyc, "qd": qd},
        })

    cells = []
    for k, cell in bd.items():
        cyc, qd = _ds(cell["summary"]["cycle"], cell["summary"]["QD"], 150)
        row = {
            "id": k,
            "split": split_of.get(k, "?"),
            "cycle_life": round(float(cell["cycle_life"])),
            "label": int(labels[k]),
            "policy": cell["charge_policy"],
            "p_pass": round(p_all[k], 3),
            "fade": {"cycle": cyc, "qd": qd},
        }
        if k in interval:
            a, b, c = interval[k]
            row.update({"p_lo": round(a, 3), "p_hi": round(b, 3),
                        "verdict": {1: "pass", 0: "fail", -1: "keep-testing"}[c],
                        "evidence": evidence[k]})
        else:
            row["verdict"] = "train"
        cells.append(row)

    return {
        "threshold": T,
        "gate": {
            "prereg": {"acc": 0.924, "ece": 0.105, "decision": "RESCOPE"},
            "hardened": {"acc": 0.941, "ece": 0.054, "decision": "BUILD-pending"},
            "production": {"acc": 0.905, "ece": 0.043, "features": "dQ(V)-only",
                           "ood": "9/9 SNL LFP transfer (full set: 0/9)"},
        },
        "envelope": {k: [round(v[0], 4), round(v[1], 4)] for k, v in envelope.items()},
        "model": model_export,
        "callable_curve": callable_curve,
        "cells": cells + transfer_cells,
    }


def build_diagnostics():
    cells = load_snl(os.path.join(ROOT, "data", "snl", "SNL"), verbose=False)
    fleet_path = os.path.join(ROOT, "data", "p1_fleet_results.pkl")
    fleet = pickle.load(open(fleet_path, "rb"))["fleet"]

    out_cells = []
    for cid, cell in cells.items():
        cyc, qd = _ds(*cell["fade"], 150)
        diags = [d for d in cell["diagnostics"] if "charge" in d]
        picks = [diags[0], diags[len(diags) // 2], diags[-1]] if len(diags) >= 3 else diags
        ica, dva_c = [], []
        for d in picks:
            vg, ic = dqdv(*d["charge"])
            v_s, ic_s = _ds(vg, ic, 250)
            ica.append({"cycle": int(d["cycle_number"]), "v": v_s, "dqdv": ic_s})
            qg, dv = dvdq(*d["charge"])
            q_s, dv_s = _ds(qg, dv, 250)
            dva_c.append({"cycle": int(d["cycle_number"]), "q": q_s, "dvdq": dv_s})
        f = fleet.loc[cid]
        out_cells.append({
            "id": cid,
            "chemistry": cell["chemistry"],
            "temperature_C": cell["temperature_C"],
            "discharge_rate_C": cell["discharge_rate_C"],
            "nominal_Ah": cell["nominal_capacity_Ah"],
            "fade": {"cycle": cyc, "qd": qd},
            "fade_frac": round(float(f["fade_frac"]), 3),
            "v_dispersion": round(float(f["v_dispersion"]), 3),
            "ica": ica,
            "dva": dva_c,
            "mode_hint": {
                "dominant": f.get("dominant_mode"),
                "rho": round(float(f["rho_dominant"]), 2) if np.isfinite(f.get("rho_dominant", np.nan)) else None,
                "closure_med": round(float(f["closure_med"]), 3) if np.isfinite(f.get("closure_med", np.nan)) else None,
            },
        })

    # Oxford fleet: C/18.5 pseudo-OCV diagnostics earn quantitative LLI/LAM_pe
    # trajectories (docs/mode-identifiability-study.md); LAM_ne is suppressed as reference-sensitive
    ox_mat = os.path.join(ROOT, "data", "oxford", "Oxford_Battery_Degradation_Dataset_1.mat")
    if os.path.exists(ox_mat):
        from scipy.stats import spearmanr

        from src.modes import fit_cell_trajectory
        from src.oxford_data import V_MIN, load_oxford

        for cid, cell in load_oxford(ox_mat, verbose=False).items():
            df = fit_cell_trajectory(cell, v_min=V_MIN)
            cyc, qd = _ds(*cell["fade"], 100)
            diags = [d for d in cell["diagnostics"] if "charge" in d]
            picks = [diags[0], diags[len(diags) // 2], diags[-1]]
            ica, dva_c = [], []
            for d in picks:
                vg, ic = dqdv(*d["charge"])
                v_s, ic_s = _ds(vg, ic, 250)
                ica.append({"cycle": int(d["cycle_number"]), "v": v_s, "dqdv": ic_s})
                qg, dv = dvdq(*d["charge"])
                q_s, dv_s = _ds(qg, dv, 250)
                dva_c.append({"cycle": int(d["cycle_number"]), "q": q_s, "dvdq": dv_s})
            mcyc, lli = _ds(df.index.values, df["LLI"].values, 100)
            _, lampe = _ds(df.index.values, df["LAM_pe"].values, 100)
            _, lamne = _ds(df.index.values, df["LAM_ne"].values, 100)
            out_cells.append({
                "id": cid, "chemistry": "KOKAM", "temperature_C": 40,
                "discharge_rate_C": None, "diag_rate": "C/18.5",
                "nominal_Ah": cell["nominal_capacity_Ah"],
                "fade": {"cycle": cyc, "qd": qd},
                "fade_frac": round(float(1 - cell["fade"][1][-1] / cell["fade"][1][0]), 3),
                "v_dispersion": round(float(voltage_dispersion(*diags[0]["charge"])), 3),
                "ica": ica, "dva": dva_c,
                "modes": {
                    "cycle": mcyc, "LLI": lli, "LAM_pe": lampe, "LAM_ne": lamne,
                    "rho_LLI": round(float(spearmanr(df.index, df["LLI"]).statistic), 2),
                    "rho_LAM_pe": round(float(spearmanr(df.index, df["LAM_pe"]).statistic), 2),
                    "rho_LAM_ne": round(float(spearmanr(df.index, df["LAM_ne"]).statistic), 2),
                },
                "mode_hint": {"dominant": "LLI", "rho": round(float(spearmanr(df.index, df["LLI"]).statistic), 2),
                              "closure_med": round(float(df["closure_err"].median()), 3)},
            })

    return {
        "gate": {
            "fade_closure": {"pass": True, "frac_ok": 1.0},
            "mode_sanity": {"pass": False, "frac_ok": 0.372},
            "chemistry_contrast": {"pass": True, "ratio": 3.25},
            "condition_systematics": {"pass": True, "n_confirmed": 2},
            "decision": "RESCOPE",
        },
        "cells": out_cells,
    }


if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    bundle = {"generated": "2026-07-03", "qual": build_qualification(), "diag": build_diagnostics()}
    with open(OUT, "w") as fp:
        json.dump(bundle, fp)
    print(f"wrote {OUT} ({os.path.getsize(OUT) / 1e6:.1f} MB)")
    print(f"qualification cells: {len(bundle['qual']['cells'])}  diagnostics cells: {len(bundle['diag']['cells'])}")
