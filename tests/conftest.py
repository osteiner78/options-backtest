"""Shared fixtures for straddle backtest tests."""

import pytest
import pandas as pd
import numpy as np

from straddle.params import PARAMS
from straddle.engines import SyntheticEngine
from straddle.strategy import Trade, LegRollEvent


@pytest.fixture
def params():
    """Default PARAMS dict for tests."""
    return dict(PARAMS)


@pytest.fixture
def synthetic_engine(params):
    """A SyntheticEngine instance with default params."""
    return SyntheticEngine(params)


@pytest.fixture
def sample_trade():
    """A minimal Trade object for testing properties and accounting."""
    return Trade(
        trade_num=1,
        entry_date=pd.Timestamp("2024-01-05"),
        expiration=pd.Timestamp("2024-02-16"),
        entry_dte=42,
        put_strike=450.0,
        call_strike=490.0,
        put_mid_ps=3.50,
        call_mid_ps=3.20,
        net_credit=630.0,  # (3.50 + 3.20) * 0.95 * 100 - 2
        entry_vix=14.0,
    )


@pytest.fixture
def sample_leg_roll():
    """A sample LegRollEvent."""
    return LegRollEvent(
        event_date=pd.Timestamp("2024-01-15"),
        side="call",
        old_strike=490.0,
        new_strike=495.0,
        close_cost_ps=1.20,
        new_credit_ps=1.50,
        net_credit_dollar=28.0,
        trigger_delta=0.30,
    )


@pytest.fixture
def sample_data():
    """Minimal market data DataFrame for unit tests (no yfinance calls)."""
    dates = pd.bdate_range("2024-01-02", "2024-03-29")
    np.random.seed(42)
    spy_close = 470.0 + np.cumsum(np.random.randn(len(dates)) * 2.0)
    return pd.DataFrame(
        {
            "spy_open": spy_close + np.random.randn(len(dates)) * 0.5,
            "spy_high": spy_close + np.abs(np.random.randn(len(dates)) * 1.5),
            "spy_low": spy_close - np.abs(np.random.randn(len(dates)) * 1.5),
            "spy_close": spy_close,
            "vix_close": 14.0 + np.random.randn(len(dates)) * 2.0,
            "risk_free_rate": 0.045,
        },
        index=dates,
    )
