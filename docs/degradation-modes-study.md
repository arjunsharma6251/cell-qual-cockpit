# Degradation-Mode Engine — Validation Study

**Question:** can periodic 0.5C diagnostic cycles support honest LLI / LAM_pe / LAM_ne attribution on Tesla-relevant chemistries (NCA, NMC), while quantifying why LFP diagnostics are muted?

**Setup:** Sandia/SNL dataset (Preger et al. 2020, double-attribution license), 61 commercial 18650 cells — 22 NCA (Panasonic NCR18650B, Tesla chemistry match #1), 21 NMC (LG HG2, LiNi0.84Mn0.06Co0.10), 18 LFP (A123) — across 15/25/35 °C and 0.5–3C discharge. Engine: ICA/DVA curve tracking (`src/dva.py`) + Dahn-style electrode-alignment fits of each diagnostic cycle against cited half-cell references (NCA: Kim 2011; NMC811: Chen 2020; LFP: Afshar 2017; graphite: Ecker 2015), with joint V + dV/dQ residuals, an endpoint-capacity consistency term, and a continuity prior along each cell's trajectory (`src/modes.py`).

## Gate result

| Check | Criterion | Result | Verdict |
|---|---|---|---|
| Fade closure | cap-reconstruction err ≤ 3% nominal, ≥ 80% of NCA+NMC | **100%** of cells | ✅ |
| Mode sanity | dominant mode ρ ≥ 0.8, ≥ 70% of NCA+NMC | **37%** | ❌ |
| Chemistry contrast | NCA/NMC V-dispersion ≥ 3× LFP | **3.25×** (0.51/0.64 V vs 0.16 V) | ✅ |
| Condition systematics | ≥ 2 known Preger trends reproduced | **2 of 3** | ✅ |

### **DECISION: RESCOPE** — ship the diagnostics panel as **ICA/DVA curve tracking + fade closure**, not quantitative LLI/LAM numbers.

Per the pre-registered rule (closure holds, contrast holds, sanity fails → RESCOPE to ICA-tracking). The electrode-model fits reconstruct capacity beautifully (median error 1.5% of nominal for NCA/NMC) and the curves themselves are diagnostic gold — but the *decomposition* into LLI/LAM is not trajectory-stable enough to put a number in front of an engineer.

## Where mode attribution breaks (the real teardown)

- **NCA is the hard case, for a physical reason.** Its 0.5C charge curve is nearly featureless (broad structureless dQ/dV — see `figures/p1_ica_chemistry.png`), so the electrode-alignment problem is multimodal: several (window, offset) combinations fit within a few mV. Five stabilization variants were tried — joint dV/dQ residuals, physical capacity bounds, continuity priors at two strengths, a voltage-anchored 4-parameter reduction, an emulated BOL-derived reference frame — none achieved ρ ≥ 0.8 on the reference cell (`figures/p1_mode_trajectories.png`, right panel: LAM_ne sawtooths ±20% between RPT groups while rmse stays ≤ 10 mV). Only 36% of NCA cells pass sanity. Literature does attribute NCA modes, but from C/20–C/25 curves with half-cell references measured on harvested electrodes — neither available here. That's the honest boundary of this dataset, not a bug to hide.
- **NMC is the success case** (left panel): clear staging features → coherent LLI + LAM_pe accumulation (~6% each at 530 cycles), and LAM_pe-dominant attribution (12 of 21 cells) consistent with high-nickel cathode degradation expectations. Still only 38% pass the strict ρ ≥ 0.8 bar — the trajectories are right-shaped but noisy at RPT-group boundaries.
- **LFP behaves exactly as advertised**: closure fails for 72% of cells and attribution magnitudes are unreliable (LLI estimates ~3× measured fade) — the quantified confirmation of "flat 3.3 V plateau → muted diagnostics" that motivates the chemistry-aware design.
- **Systematics disclosure:** the original check encoded two trends backwards from memory; after verifying against the paper itself, the corrected checks confirm LFP degrading 3.3× faster at 35 °C than 15 °C and NMC improving with temperature (ρ = −0.75). NCA's counterintuitive fade-decreases-with-rate finding did **not** reproduce in our fade-at-cycle-250 metric (ρ = +0.57) — reported, not smoothed over.

## What this means for the cockpit

The diagnostics panel ships: per-cell ICA/DVA curve evolution, voltage-dispersion chemistry awareness, fade-closure QC, and condition systematics — with mode attribution demoted to a qualitative "dominant mode" hint (shown with its ρ) rather than quantitative percentages. A follow-up could earn the numbers back with C/20 RPT data or measured half-cell references.

**Post-script:** that follow-up happened and confirmed the diagnosis quantitatively — on Oxford BDD-1's C/18.5 diagnostics, LLI/LAM_pe stabilize with generic references, and with chemistry-matched half-cell references the full three-way split passes this report's pre-registered sanity gate on 8/8 cells. See `docs/mode-identifiability-study.md`.

## Reproduce

```
# data: Zenodo record 19688272 -> SNL.zip -> data/snl/SNL/*.pkl (115 MB)
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/degradation_modes_study.ipynb
```

First fleet evaluation ~3 min (cached thereafter in `data/p1_fleet_results.pkl`).
