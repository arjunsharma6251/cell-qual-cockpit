"""Canonical Severson train / primary-test / secondary-test partition.

From the official repo's 'Load Data.ipynb': with cells ordered
batch1 + batch2 + batch3 (after exclusions and carry-over merge),
  test_ind           = even indices over batch1+batch2, plus index 83
  train_ind          = odd indices over batch1+batch2 (excluding the last)
  secondary_test_ind = all of batch3
"""

import numpy as np

N_BATCH3 = 40  # cells in batch3 after exclusions


def canonical_split(cell_keys, n_batch3=N_BATCH3):
    """Split ordered cell keys into (train, primary_test, secondary_test) lists."""
    keys = list(cell_keys)
    n = len(keys)
    n12 = n - n_batch3
    test_ind = np.hstack((np.arange(0, n12, 2), 83))
    train_ind = np.arange(1, n12 - 1, 2)
    secondary_ind = np.arange(n12, n)
    train = [keys[i] for i in train_ind]
    primary = [keys[i] for i in test_ind]
    secondary = [keys[i] for i in secondary_ind]
    assert not (set(train) & set(primary)), "train/test overlap"
    return train, primary, secondary


def report_balance(name, keys, labels):
    """Print class balance for one split."""
    y = np.array([labels[k] for k in keys])
    print(f"{name:<16s} n={len(y):3d}  pass={int(y.sum()):3d}  fail={int((1 - y).sum()):3d}  pass rate={y.mean():.2f}")
