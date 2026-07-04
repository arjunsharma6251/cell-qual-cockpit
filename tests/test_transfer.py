import numpy as np
import pandas as pd

from src.transfer import DQ_FEATURES, envelope_violations, feature_envelope


def test_feature_envelope_and_violations():
    df = pd.DataFrame({"a": [0.0, 1.0, 2.0], "b": [-5.0, -4.0, -3.0]})
    env = feature_envelope(df, margin=0.10)
    assert env["a"] == (-0.2, 2.2)
    assert env["b"] == (-5.2, -2.8)
    assert envelope_violations({"a": 1.0, "b": -4.0}, env) == []
    assert envelope_violations({"a": 5.0, "b": -4.0}, env) == ["a"]
    assert set(envelope_violations({"a": -1.0, "b": 0.0}, env)) == {"a", "b"}


def test_dq_features_are_protocol_invariant_subset():
    from src.features import FEATURE_NAMES
    assert set(DQ_FEATURES) <= set(FEATURE_NAMES)
    assert all("dq" in f for f in DQ_FEATURES)
