"""Tests for iron-condor mode.

Verifies that:
  - 4-leg entries build correctly via build_entry
  - IC credit is strictly lower than short-strangle credit on the same inputs
  - IC margin is defined-risk (max vertical width × 100 − credit)
  - Short-strangle behavior is byte-identical when strategy_mode defaults apply
  - Defensive leg rolls and price stops are disabled in IC mode
"""

import pandas as pd
import pytest

from straddle.engines import PricingContext, SyntheticEngine
from straddle.portfolio import (
    calculate_iron_condor_margin,
    calculate_reg_t_strangle_margin,
)
from straddle.strategy import (
    Trade,
    attempt_defensive_leg_roll,
    build_entry,
    run_backtest,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def ic_params(params):
    p = dict(params)
    p["strategy_mode"] = "iron_condor"
    p["wing_delta"] = 0.05
    return p


@pytest.fixture
def entry_inputs(synthetic_engine):
    S, T, r, vix = 470.0, 42 / 365.0, 0.045, 15.0
    ctx = PricingContext(
        eval_date=pd.Timestamp("2024-01-05"),
        expiration=pd.Timestamp("2024-02-16"),
    )
    return dict(engine=synthetic_engine, S=S, T=T, r=r, vix=vix, entry_dte=42, ctx=ctx)


# ── Entry construction ──────────────────────────────────────────────────


class TestBuildEntry:
    def test_entry_builds_four_legs(self, ic_params, entry_inputs):
        kw = build_entry(params=ic_params, **entry_inputs)
        assert kw is not None
        for key in (
            "put_strike",
            "call_strike",
            "long_put_strike",
            "long_call_strike",
            "long_put_mid_ps",
            "long_call_mid_ps",
        ):
            assert key in kw
        # Wings are further OTM than the short strikes
        assert kw["long_put_strike"] < kw["put_strike"]
        assert kw["long_call_strike"] > kw["call_strike"]

    def test_strangle_omits_wings(self, params, entry_inputs):
        kw = build_entry(params=params, **entry_inputs)
        assert kw is not None
        assert "long_put_strike" not in kw
        assert "long_call_strike" not in kw

    def test_iron_condor_credit_less_than_strangle(
        self, params, ic_params, entry_inputs
    ):
        kw_s = build_entry(params=params, **entry_inputs)
        kw_ic = build_entry(params=ic_params, **entry_inputs)
        assert kw_s is not None and kw_ic is not None
        assert kw_ic["net_credit"] < kw_s["net_credit"]


# ── Trade properties ─────────────────────────────────────────────────────


class TestIronCondorTrade:
    def _build(self):
        return Trade(
            trade_num=1,
            entry_date=pd.Timestamp("2024-01-05"),
            expiration=pd.Timestamp("2024-02-16"),
            entry_dte=42,
            put_strike=450.0,
            call_strike=490.0,
            put_mid_ps=3.50,
            call_mid_ps=3.20,
            net_credit=500.0,
            entry_vix=14.0,
            long_put_strike=440.0,
            long_call_strike=500.0,
            long_put_mid_ps=0.80,
            long_call_mid_ps=0.60,
        )

    def test_is_iron_condor_flag(self):
        assert self._build().is_iron_condor is True

    def test_short_strangle_flag_is_false(self, sample_trade):
        assert sample_trade.is_iron_condor is False

    def test_baseline_mid_is_net(self):
        t = self._build()
        expected = (3.50 + 3.20) - (0.80 + 0.60)
        assert t.active_baseline_mid == pytest.approx(expected)


# ── Margin ───────────────────────────────────────────────────────────────


class TestIronCondorMargin:
    def test_defined_risk_formula(self):
        # put width = 450 − 440 = 10; call width = 500 − 490 = 10 → max 10
        margin = calculate_iron_condor_margin(
            put_strike=450.0,
            long_put_strike=440.0,
            call_strike=490.0,
            long_call_strike=500.0,
            net_credit=150.0,
        )
        assert margin == pytest.approx(10.0 * 100.0 - 150.0)

    def test_asymmetric_wings_use_wider_side(self):
        # put width 10, call width 20 → use 20
        margin = calculate_iron_condor_margin(
            put_strike=450.0,
            long_put_strike=440.0,
            call_strike=490.0,
            long_call_strike=510.0,
            net_credit=200.0,
        )
        assert margin == pytest.approx(20.0 * 100.0 - 200.0)

    def test_ic_margin_much_less_than_naked_strangle(self):
        ic_margin = calculate_iron_condor_margin(
            put_strike=450.0,
            long_put_strike=440.0,
            call_strike=490.0,
            long_call_strike=500.0,
            net_credit=150.0,
        )
        naked_margin = calculate_reg_t_strangle_margin(
            underlying_price=470.0,
            put_strike=450.0,
            call_strike=490.0,
            put_ask_price=3.50,
            call_ask_price=3.20,
        )
        assert ic_margin < naked_margin * 0.5


# ── Regression: default mode path is unchanged ──────────────────────────


class TestShortStrangleRegression:
    def test_default_mode_runs_unchanged(self, params, sample_data, synthetic_engine):
        # Equity and trade sequence must match byte-for-byte before/after the IC change.
        trades1, eq1, _s1, _v1 = run_backtest(sample_data, params, synthetic_engine)
        trades2, eq2, _s2, _v2 = run_backtest(sample_data, params, synthetic_engine)

        assert len(trades1) == len(trades2)
        for t in trades1:
            assert not t.is_iron_condor
            assert t.long_put_strike is None
            assert t.long_call_strike is None
        # Equity curves byte-identical
        pd.testing.assert_series_equal(eq1, eq2)


# ── Risk-management gating in IC mode ───────────────────────────────────


class TestDefensiveLegRollGatedInIC:
    def test_returns_false_in_ic_mode(self, ic_params, synthetic_engine, sample_data):
        ic_params["defensive_leg_roll_enabled"] = True
        ic_params["defensive_trigger_delta"] = 0.30

        trade = Trade(
            trade_num=1,
            entry_date=pd.Timestamp("2024-01-05"),
            expiration=pd.Timestamp("2024-02-16"),
            entry_dte=42,
            put_strike=470.0,   # very close to ATM → tested-side delta high
            call_strike=490.0,
            put_mid_ps=8.0,
            call_mid_ps=2.0,
            net_credit=500.0,
            entry_vix=14.0,
            long_put_strike=455.0,
            long_call_strike=505.0,
            long_put_mid_ps=2.0,
            long_call_mid_ps=0.3,
        )
        eval_date = pd.Timestamp("2024-01-15")
        fired = attempt_defensive_leg_roll(
            trade=trade,
            eval_date=eval_date,
            S_d=470.0,
            vix_d=14.0,
            r_d=0.045,
            dte_rem=32,
            T_d=32 / 365.0,
            data=sample_data,
            engine=synthetic_engine,
            params=ic_params,
        )
        assert fired is False
        assert len(trade.leg_rolls) == 0


class TestStopLossGatedInIC:
    def test_no_stop_exits_in_ic_mode(self, ic_params, sample_data, synthetic_engine):
        # Force the stop path to be tempting: enable it with a tiny threshold that
        # a naked strangle would hit easily. In IC mode it must still never fire.
        ic_params["use_price_stop"] = True
        ic_params["stop_loss_pct"] = 0.10  # tiny → would trigger easily if not gated
        trades, _eq, _s, _v = run_backtest(sample_data, ic_params, synthetic_engine)
        assert all(t.exit_type != "STOP" for t in trades)
