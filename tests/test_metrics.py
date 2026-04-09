"""Tests for metrics computation."""

import numpy as np
import pandas as pd
import pytest

from straddle.metrics import compute_metrics
from straddle.strategy import Trade


class TestComputeMetrics:
    """compute_metrics should return a complete, self-contained metrics dict."""

    def test_returns_all_expected_keys(self, sample_trade, params, sample_data):
        sample_trade.exit_date = pd.Timestamp("2024-02-16")
        sample_trade.exit_type = "PROFIT"
        sample_trade.pnl = 315.0
        sample_trade.pnl_pct = 0.50
        sample_trade.daily_marks = [
            (sample_trade.entry_date, 0.0),
            (sample_trade.exit_date, 315.0),
        ]
        equity_curve = pd.Series(
            {sample_trade.exit_date: params["initial_balance"] + 315.0}
        )

        metrics = compute_metrics([sample_trade], equity_curve, params, sample_data)

        expected_keys = {
            "n", "init", "final", "tot", "ann", "sharpe", "mdd", "calmar",
            "wr", "avg_pnl", "avg_pct", "max_streak",
            "n_p", "wr_p", "avg_p",
            "n_s", "wr_s", "avg_s",
            "n_d", "wr_d", "avg_d",
            "n_e", "wr_e", "avg_e",
            "n_r", "wr_r", "avg_r",
            "n_chains", "wr_chain", "avg_chain",
            "spy_total_return", "spy_sharpe",
        }
        assert expected_keys.issubset(set(metrics.keys()))

    def test_empty_trades_returns_empty_dict(self, params, sample_data):
        metrics = compute_metrics([], pd.Series(dtype=float), params, sample_data)
        assert metrics == {}

    def test_win_rate_calculation(self, params, sample_data):
        trades = []
        for i in range(4):
            t = Trade(
                trade_num=i + 1,
                entry_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp("2024-02-16"),
                entry_dte=42,
                put_strike=450.0,
                call_strike=490.0,
                put_mid_ps=3.50,
                call_mid_ps=3.20,
                net_credit=630.0,
                entry_vix=14.0,
                exit_date=pd.Timestamp("2024-02-16"),
                exit_type="PROFIT" if i < 3 else "STOP",
                pnl=315.0 if i < 3 else -1260.0,
                pnl_pct=0.50 if i < 3 else -2.00,
                daily_marks=[
                    (pd.Timestamp("2024-01-05"), 0.0),
                    (pd.Timestamp("2024-02-16"), 315.0 if i < 3 else -1260.0),
                ],
            )
            trades.append(t)

        equity_curve = pd.Series({pd.Timestamp("2024-02-16"): 50000.0})
        metrics = compute_metrics(trades, equity_curve, params, sample_data)

        assert metrics["n"] == 4
        assert metrics["wr"] == 0.75  # 3 out of 4

    def test_spy_benchmark_included(self, sample_trade, params, sample_data):
        sample_trade.exit_date = pd.Timestamp("2024-02-16")
        sample_trade.exit_type = "PROFIT"
        sample_trade.pnl = 315.0
        sample_trade.pnl_pct = 0.50
        sample_trade.daily_marks = [
            (sample_trade.entry_date, 0.0),
            (sample_trade.exit_date, 315.0),
        ]
        equity_curve = pd.Series(
            {sample_trade.exit_date: params["initial_balance"] + 315.0}
        )

        metrics = compute_metrics([sample_trade], equity_curve, params, sample_data)

        assert "spy_total_return" in metrics
        assert "spy_sharpe" in metrics
        assert isinstance(metrics["spy_total_return"], float)
        assert isinstance(metrics["spy_sharpe"], float)
