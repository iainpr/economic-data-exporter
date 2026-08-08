import sys

import pandas as pd

from economic_data_exporter.services.analysis import descriptive_statistics, growth_rate


def test_core_analysis_does_not_require_quantecon(sample_result) -> None:
    before = sample_result.data.copy(deep=True)
    sys.modules.pop("quantecon", None)
    stats = descriptive_statistics(sample_result.data)
    derived = growth_rate(sample_result.data, method="percent_change")
    pd.testing.assert_frame_equal(sample_result.data, before)
    assert not stats.empty
    assert "derived_value" in derived.columns
    assert "quantecon" not in sys.modules


def test_optional_quantecon_isolated_when_unavailable(sample_result) -> None:
    from economic_data_exporter.exceptions import ValidationError
    from economic_data_exporter.services.analysis import markov_regime_analysis

    before = sample_result.data.copy(deep=True)
    try:
        markov_regime_analysis(sample_result.data, bins=2)
    except ValidationError:
        pass
    pd.testing.assert_frame_equal(sample_result.data, before)
