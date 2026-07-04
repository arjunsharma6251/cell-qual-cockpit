import os

import numpy as np
import pytest

MAT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "oxford", "Oxford_Battery_Degradation_Dataset_1.mat")


@pytest.mark.skipif(not os.path.exists(MAT), reason="Oxford dataset not downloaded")
def test_oxford_loader_shapes():
    from src.oxford_data import load_oxford

    cells = load_oxford(MAT, verbose=False)
    assert len(cells) == 8
    one = cells["OX_Cell1"]
    assert one["nominal_capacity_Ah"] == pytest.approx(0.74)
    d = one["diagnostics"][0]
    q, v = d["charge"]
    assert len(q) > 1000  # pseudo-OCV at C/18.5 is densely sampled
    assert np.all(np.diff(q) >= 0)
    assert 2.6 < v.min() < 3.2 and 4.0 < v.max() <= 4.25
    cyc, qd = one["fade"]
    assert qd[0] > qd[-1] > 0.4  # cells fade but stay well above zero
