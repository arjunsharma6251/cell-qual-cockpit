"""Pass/fail labels from cycle life against a spec threshold."""

import numpy as np

DEFAULT_THRESHOLD = 700  # cycles; near the empirical median -> balanced classes


def make_labels(bat_dict, threshold=DEFAULT_THRESHOLD, auto_adjust=True, verbose=True):
    """Label each cell pass (1) if cycle_life >= threshold, else fail (0).

    If the class balance is worse than 40/60, move the threshold to the
    empirical median cycle life (rounded to 10) and report the change.
    Returns (labels: {key: 0/1}, threshold_used).
    """
    lives = {k: c["cycle_life"] for k, c in bat_dict.items()}
    lives_arr = np.array(list(lives.values()), dtype=float)
    if np.isnan(lives_arr).any():
        bad = [k for k, v in lives.items() if np.isnan(v)]
        raise ValueError(f"cells with undefined cycle_life: {bad}")

    def balance(t):
        p = float(np.mean(lives_arr >= t))
        return p

    t = threshold
    p = balance(t)
    if auto_adjust and not (0.40 <= p <= 0.60):
        t_new = int(round(np.median(lives_arr) / 10.0) * 10)
        if verbose:
            print(f"T={t}: pass rate {p:.2f} outside 40/60 -> adjusting to median T={t_new}")
        t = t_new
        p = balance(t)
    if verbose:
        n = len(lives_arr)
        print(f"threshold T={t}: pass={int(p * n)} fail={n - int(p * n)} (pass rate {p:.2f})")

    labels = {k: int(v >= t) for k, v in lives.items()}
    return labels, t
