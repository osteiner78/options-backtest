"""Tests for params module: TypedDict completeness, PRICING defaults, apply_market_preset."""

import pytest

from straddle.params import PARAMS, PRICING, MARKET_PRESETS, apply_market_preset, StrategyParams


class TestStrategyParamsTypedDict:
    """vol_filter_mode and vol_filter_threshold must be declared in StrategyParams (S1)."""

    def test_vol_filter_mode_in_typeddict(self):
        hints = StrategyParams.__annotations__
        assert "vol_filter_mode" in hints

    def test_vol_filter_threshold_in_typeddict(self):
        hints = StrategyParams.__annotations__
        assert "vol_filter_threshold" in hints


class TestPricingDefaults:
    """american_options should be in the base PRICING dict (S2)."""

    def test_american_options_in_pricing(self):
        assert "american_options" in PRICING

    def test_american_options_default_is_false(self):
        assert PRICING["american_options"] is False

    def test_american_options_in_params(self):
        assert "american_options" in PARAMS


class TestApplyMarketPreset:
    """apply_market_preset priority rules (Bug #11)."""

    def test_switches_to_bova11(self):
        params = dict(PARAMS)
        result = apply_market_preset(params, "bova11")
        assert result["market"] == "bova11"
        assert result["calendar"] == "BVMF"
        assert result["currency"] == "BRL"

    def test_non_market_key_always_preserved(self):
        """start_date is not a market-preset key — it must always pass through."""
        params = dict(PARAMS)
        params["start_date"] = "2019-01-02"
        result = apply_market_preset(params, "bova11")
        assert result["start_date"] == "2019-01-02"

    def test_market_key_override_with_explicitly_set(self):
        """With explicitly_set, even a market-preset key override is preserved."""
        params = dict(PARAMS)
        params["tick_size"] = 0.01  # same as SPY default but explicit
        result = apply_market_preset(params, "bova11", explicitly_set={"tick_size"})
        assert result["tick_size"] == 0.01  # bova11 default is 0.05

    def test_market_key_override_differs_from_spy_default(self):
        """Without explicitly_set, a key different from SPY default is preserved."""
        params = dict(PARAMS)
        params["tick_size"] = 0.10  # different from SPY default (0.05 or 0.01)
        result = apply_market_preset(params, "bova11")
        assert result["tick_size"] == 0.10

    def test_unknown_market_raises(self):
        with pytest.raises(ValueError, match="Unknown market"):
            apply_market_preset(dict(PARAMS), "nasdaq")
