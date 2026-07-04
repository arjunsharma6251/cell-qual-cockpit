# Mode Identifiability Study — earning quantitative LLI/LAM

## RESULT (2026-07-03, Oxford Battery Degradation Dataset 1)

Dahn-lab raw cycling data is not on Borealis (searched via the Dataverse API;
their JES papers publish figures, not files), so the experiment ran on the
best public diagnostics-grade set: **Oxford BDD-1** (8 Kokam 740 mAh pouch
cells, 40 °C, pseudo-OCV charge/discharge at **C/18.5 every 100 cycles**,
`doi:10.5287/bodleian:KO2kdmYGg`). Loader: `src/oxford_data.py`. Caveat by
design: the Kokam cathode is an LCO/NMC blend with no public half-cell curve;
fits used the vendored NMC811 reference — so this experiment probes data-rate
and reference-fidelity effects together.

**The pre-registered check (dominant-mode sanity, ρ ≥ 0.8 for ≥ 70% of
cells) FAILS as written: 1/8.** But the per-mode breakdown shows exactly why,
and it is not the data rate:

| Mode | trajectory ρ ≥ 0.8 | end magnitudes |
|---|---|---|
| **LLI** | **8/8** (ρ 0.92–0.98) | 0.11–0.24 vs fade 0.19–0.30 — plausible, LLI-dominant (matches Birkl) |
| **LAM_pe** | **6/8** (ρ 0.79–0.97) | 0.08–0.26 — plausible |
| LAM_ne | 0/8 (ρ −0.51–0.01) | negative ("anode grows") — unphysical |

LAM_ne is the sink that absorbs cathode-reference mismatch (fit rmse ~20 mV
vs ~5 mV with matched chemistry), and because its spurious magnitude is
largest it gets selected as "dominant," failing the gate metric.

**Refined conclusion, three-way:**
1. 0.5C aging cycles + generic refs (SNL): nothing is stable → curve
   tracking only. The P1 verdict stands for that data class.
2. C/20-class diagnostics + generic refs (Oxford): **quantitative LLI and
   LAM_pe are trustworthy**; suppress LAM_ne as reference-sensitive.
3. Trusting LAM_ne (full three-way split) requires chemistry-matched
   half-cell references — measured or vendored for the exact cathode.

Cockpit consequence: cells with diagnostics-grade slow cycles get quantitative
LLI/LAM_pe trajectories (shipped for the Oxford fleet); SNL cells keep the
qualitative hint. No goalposts moved: the pre-registered check failed and is
reported as such; the per-mode diagnosis is what ships.

## Matched references close the loop

Birkl's parametric OCV paper (JES 162 A2271, open access) tabulates its fitted
electrode parameters only in figures, but the Howey lab's **SLIDE** simulator
(github.com/Battery-Intelligence-Lab/SLIDE, BSD-3) vendors half-cell OCV
curves for the same Kokam NMC family: `Kokam_OCV_NMC.csv` / `Kokam_OCV_C.csv`,
now vendored in `refs/ocp/` with a `KOKAM` entry in `CHEMISTRY_REFS` (which
now maps chemistry → (PE, NE) reference *pair*).

Rerunning the identical pre-registered check with matched references:

| Reference set | dominant-mode sanity | LLI ρ | LAM_pe ρ | LAM_ne end |
|---|---|---|---|---|
| generic (NMC811 + Ecker graphite) | 1/8 | 0.92–0.98 | 6/8 ≥ 0.8 | −0.29…−0.13 (unphysical) |
| **matched (SLIDE Kokam pair)** | **8/8** | **1.00 ×8** | **1.00 ×8** | −0.11…+0.03 (≈0, physical) |

The three-tier conclusion is now demonstrated end-to-end on one dataset chain:
0.5C + generic → curve tracking only; C/20 + generic → LLI/LAM_pe; **C/20 +
matched → full three-way split passes the pre-registered gate**. LAM_ne ≈ 0 is
the physically correct answer for these LLI-dominant cells (Birkl's own
conclusion). The cockpit's Oxford fleet now shows all three modes with their ρ.

---

# Appendix: dataset scouting notes

P1's mode-sanity gate failed because 0.5C curves + generic half-cell references
can't identify NCA's electrode alignment. Two paths back to quantitative modes:

## Path A: slower diagnostics (preferred)
Dahn-lineage long-term pouch-cell studies run periodic C/20 checkups with dV/dQ
analysis — exactly what the electrode-alignment fitter needs.

Candidates (scouted 2026-07-03, acquisition NOT yet verified):
- **Harlow et al. 2019** (J. Electrochem. Soc. 166 A3031, open access) — the
  "benchmark" NMC532/graphite dataset; check the paper's data-availability
  statement and supplementary material.
- **Aiken et al. 2022** (J. Electrochem. Soc. 169 090517) — single-crystal
  NMC811/AG pouch cells across DOD, C-rate, voltage, temperature; chemistry
  match for the 2170/4680 family.
- **Dalhousie University Dataverse @ Borealis** (borealisdata.ca) — the lab's
  institutional repository; search "Dahn" there manually (web search could not
  confirm dataset DOIs).

## Path B: measured half-cell references
Harvested-electrode OCP data for the exact SNL cells doesn't exist publicly.
Closest substitutes: Chen 2020 (LG M50) is already vendored; the O'Regan 2022
LG M50LT parameterization adds temperature dependence if needed.

## Acceptance bar (pre-register before building)
Re-run the diagnostics mode-sanity gate (dominant-mode ρ ≥ 0.8 for ≥ 70% of cells) on
the new dataset's C/20 diagnostics. If it passes there but still fails on SNL
0.5C data, the diagnostics conclusion stands and the cockpit gains a documented
"diagnostics-grade data required" requirement instead of a model change.
