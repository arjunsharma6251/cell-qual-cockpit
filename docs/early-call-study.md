# Early-Call Validation Study

*Can qualification verdicts be called from the first 100 cycles — honestly?*

**Question:** can data from the first ≤100 cycles flip a qualification verdict reliably and with honest confidence?

**Setup:** Severson/MATR, 124 LFP/graphite A123 cells, canonical exclusions + carry-over merge and the paper's train / primary-test / secondary-test split (41 / 43 / 40 cells). Label: pass = cycle life ≥ T = 700 (56/44 balance; no threshold adjustment needed). Features: log-ΔQ(V) statistics (Qdlin_late − Qdlin₁₀ on the shared 1000-pt voltage grid) + fade slope, QD@2, IR@2, avg charge time (first 5). Base model: standardized logistic regression — 124 cells punishes anything bigger.

## 1. Pre-registered gate run (first shot — this is the official verdict)

Model: `CalibratedClassifierCV` (isotonic, chosen over sigmoid by nested CV on train: 0.085 vs 0.198).

| Metric (combined test, n=83) | Value | Pass bar | Verdict |
|---|---|---|---|
| Balanced accuracy @ cycle 100 | **0.924** | ≥ 0.85 | ✅ clear pass |
| ECE @ cycle 100 | **0.105** | ≤ 0.10 | ❌ miss by 0.005 |

### **OFFICIAL GATE DECISION: RESCOPE** — early-call as decision support with explicit uncertainty.

Accuracy was never the problem; the confidence number missed the honesty bar by half a point. Per-split: primary test 0.895/0.094 (passes BUILD alone); secondary test 1.000/0.134 — the miss lives entirely in batch 3, whose 95% pass rate vs 41% in training is a real distribution shift.

## 2. Hardening iteration (disclosed adaptive pass)

Because the only failure was calibration, a second pass compared calibrators. **Selection used the 41 training cells only** (5-fold × 10-repeat nested CV, criterion = ECE; ties within 0.01 broken by lower variance, then simpler method — full protocol and numbers in the notebook, §5). Winner: **calibrate one isotonic map on out-of-fold scores, refit the base model on the full train split** (`EarlyVerdictModel`), replacing `CalibratedClassifierCV`'s fold-ensemble. This pass was motivated by the first test evaluation, so it is labeled adaptive and its numbers need revalidation on fresh data.

| Metric (combined test, n=83) | Pre-registered | Hardened |
|---|---|---|
| Balanced accuracy @ cycle 100 | 0.924 | **0.941** |
| ECE @ cycle 100 | 0.105 | **0.054** (0.036 ± 0.007 across 10 CV seeds) |
| Meets both BUILD bars | no | **yes** |

### **RECOMMENDATION: RESCOPE → BUILD, pending revalidation of calibration on untouched data.**

## 3. The rescoped product: intervals + "keep testing" (notebook §8)

A cross Venn-ABERS predictor wraps the same base model and emits a probability *interval* [p0, p1] per cell (distribution-free validity). Verdict rule: pass if p0 > 0.5, fail if p1 < 0.5, otherwise **keep testing**. On the combined test set (`figures/callable_curve.png`):

| Cutoff cycle | 40 | 50 | 60 | 80 | 100 |
|---|---|---|---|---|---|
| Cells callable | 76% | 67% | 72% | 75% | 76% |
| Accuracy on called | 98.4% | 98.2% | **100%** | **100%** | **100%** |

The 20 abstained cells @100 have true lives 499–1051 — precisely the band around T=700 where "keep testing" is the right answer. This is the cockpit feature in miniature: three in four cells get a confident, correct verdict at ≤100 cycles; the rest are explicitly flagged, not guessed. (CVAP's own point probability is not well calibrated at n=41 and is used only for the interval; the displayed probability comes from the hardened point model.)

## 4. Stabilization and where the early call breaks

- Combined balanced accuracy ≥ 0.85 at every cutoff except a dip at 60 (0.848/0.154); by the strict rule the verdict stabilizes at **cycle 80**, and cutoff 50 is already excellent (0.938 acc / 0.008 ECE). The cutoff-60 dip persists across every model variant tried — flagged honestly as an open question rather than smoothed over; n=83 makes single-cutoff numbers noisy (`figures/stabilization.png`).
- All four misclassifications @100 (hardened model) sit within ~190 cycles of T=700 and do not cluster by charging protocol; the CVAP abstain rule catches the ambiguous band they live in. Out-of-distribution honesty: batch 3's near-uniform pass rate means the secondary test barely exercises the fail class (2 cells) — the LFP early-call should be revalidated as new chemistries arrive.

## 5. Addendum: out-of-distribution revalidation on SNL LFP

The Sandia/SNL dataset (used in the degradation-modes study) contains 18 cells of the **same cell model** (A123 APR18650M1A, 1.1 Ah) cycled in a different lab under gentler protocols (0.5C charge vs Severson's 4–8C fast-charge policies). All 18 are true PASS at T=700 (lives 2337 to >4000 cycles) — single-class, so ECE/balanced accuracy cannot be revalidated, but a one-sided transfer check is possible on the 9 cells with usable cycle-10/100 logs:

| Model (trained on Severson only) | Severson test (in-domain) | SNL LFP (OOD) |
|---|---|---|
| Full feature set (minus IR, unavailable in SNL) | 0.946 acc / 0.068 ECE | **0/9 correct, P(pass)=0.000 on every cell** |
| ΔQ(V) statistics only | 0.905 acc / 0.043 ECE | **9/9 correct** |

The failure mode is precise: `avg_chargetime_first5` is 7–11 *minutes* in Severson (fast-charge protocols) vs ~2 *hours* at SNL's 0.5C — a protocol covariate ~50σ outside the training range that saturates the model into confident wrongness. The ΔQ(V) features — the actual electrochemical signature, computed as a within-cell difference — transfer cleanly. (Caveat: the OOD set is all-pass, so 9/9 is a necessary, not sufficient, transfer result; the 0/9 vs 9/9 contrast is the finding.)

**Consequence for the cockpit:** the production early-call should use protocol-invariant features (ΔQ(V) statistics) or, at minimum, refuse to emit a verdict when any covariate lies outside the training envelope. Confident extrapolation on protocol features is exactly the failure the KEEP-TESTING abstain rule exists to prevent — but abstention can't trigger on inputs the model was never taught to distrust.

## Reproduce

```
python -m venv .venv && .venv/bin/pip install -r requirements.txt
# place the three .mat batch files in data/ (URLs in the build brief; ~9 GB)
.venv/bin/jupyter nbconvert --to notebook --execute --inplace notebooks/early_call_study.ipynb
```

First run parses the .mat files (~2 min) into `data/processed_slim.pkl`; subsequent runs take ~3 min (the calibration bake-off dominates).
