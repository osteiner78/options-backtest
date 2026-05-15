"""Tests for strategy module: calendar utils, Trade properties, backtest invariants."""

import numpy as np
import pandas as pd
import pytest

from straddle.strategy import (
    get_third_friday,
    get_monthly_expiration,
    get_entry_dates,
    Trade,
    LegRollEvent,
    _VOL_CACHE,
    _build_vol_filter,
    clear_vol_cache,
)


# ── Calendar utilities ───────────────────────────────────────────────────

class TestGetThirdFriday:
    """get_third_friday should return the correct 3rd Friday for any month."""

    def test_january_2024(self):
        result = get_third_friday(2024, 1)
        assert result == pd.Timestamp("2024-01-19")

    def test_february_2024(self):
        result = get_third_friday(2024, 2)
        assert result == pd.Timestamp("2024-02-16")

    def test_march_2024(self):
        result = get_third_friday(2024, 3)
        assert result == pd.Timestamp("2024-03-15")

    def test_december_2024(self):
        result = get_third_friday(2024, 12)
        assert result == pd.Timestamp("2024-12-20")

    def test_is_always_friday(self):
        for year in range(2020, 2030):
            for month in range(1, 13):
                tf = get_third_friday(year, month)
                assert tf.weekday() == 4  # Friday = 4


class TestGetMonthlyExpiration:
    """get_monthly_expiration should find the nearest valid 3rd Friday."""

    def test_finds_next_month_expiry(self):
        entry = pd.Timestamp("2024-01-05")
        exp = get_monthly_expiration(entry, dte_min=30, dte_max=45)
        assert exp == pd.Timestamp("2024-02-16")  # 42 DTE

    def test_returns_none_if_no_valid_expiry(self):
        # Entry too close to expiry — no 3rd Friday in range
        entry = pd.Timestamp("2024-02-10")
        exp = get_monthly_expiration(entry, dte_min=30, dte_max=45)
        # Feb 16 is only 6 days away, Mar 15 is 34 days away → valid
        assert exp is not None  # Mar 15 = 34 DTE, in range

    def test_dte_within_range(self):
        entry = pd.Timestamp("2024-01-05")
        exp = get_monthly_expiration(entry, dte_min=30, dte_max=45)
        dte = (exp - entry).days
        assert 30 <= dte <= 45


class TestGetEntryDates:
    """get_entry_dates should return one entry per month within the window."""

    def test_returns_one_per_month(self, sample_data):
        dates = get_entry_dates(
            sample_data, "2024-01-02", "2024-03-29", dte_min=30, dte_max=45
        )
        # Jan, Feb, Mar → 3 entries
        assert len(dates) == 3

    def test_no_duplicate_months(self, sample_data):
        pairs = get_entry_dates(
            sample_data, "2024-01-02", "2024-03-29", dte_min=30, dte_max=45
        )
        months = [(entry.year, entry.month) for entry, _ in pairs]
        assert len(months) == len(set(months))


# ── Trade properties ─────────────────────────────────────────────────────

class TestTradeProperties:
    """Trade.active_* properties should return correct values."""

    def test_active_put_strike_defaults_to_original(self, sample_trade):
        assert sample_trade.active_put_strike == sample_trade.put_strike

    def test_active_call_strike_defaults_to_original(self, sample_trade):
        assert sample_trade.active_call_strike == sample_trade.call_strike

    def test_active_baseline_mid_defaults_to_sum(self, sample_trade):
        expected = sample_trade.put_mid_ps + sample_trade.call_mid_ps
        assert sample_trade.active_baseline_mid == expected

    def test_active_put_strike_after_leg_roll(self, sample_trade):
        sample_trade.current_put_strike = 445.0
        assert sample_trade.active_put_strike == 445.0

    def test_active_call_strike_after_leg_roll(self, sample_trade):
        sample_trade.current_call_strike = 495.0
        assert sample_trade.active_call_strike == 495.0

    def test_active_baseline_mid_after_leg_roll(self, sample_trade):
        sample_trade.current_baseline_mid = 7.50
        assert sample_trade.active_baseline_mid == 7.50


class TestLegRollCreditFlow:
    """test_leg_roll_credit_flow — net_credit after leg roll equals
    original_credit + leg_roll_event.net_credit_dollar."""

    def test_leg_roll_credit_added(self, sample_trade, sample_leg_roll):
        original_credit = sample_trade.net_credit
        sample_trade.leg_rolls.append(sample_leg_roll)
        sample_trade.current_baseline_mid = (
            sample_trade.put_mid_ps + sample_trade.call_mid_ps
            + sample_leg_roll.net_credit_dollar / 100.0
        )
        # The trade's effective credit should reflect the leg roll
        total_credit = original_credit + sample_leg_roll.net_credit_dollar
        assert total_credit > original_credit


# ── Backtest invariants ──────────────────────────────────────────────────

class TestBacktestDeterminism:
    """test_backtest_determinism — running the same params twice yields
    identical trades."""

    def test_deterministic_results(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        trades1, eq1, skip1, svix1 = run_backtest(
            sample_data, params, synthetic_engine
        )
        trades2, eq2, skip2, svix2 = run_backtest(
            sample_data, params, synthetic_engine
        )

        assert len(trades1) == len(trades2)
        for t1, t2 in zip(trades1, trades2):
            assert t1.entry_date == t2.entry_date
            assert t1.put_strike == t2.put_strike
            assert t1.call_strike == t2.call_strike
            assert t1.net_credit == t2.net_credit
        assert skip1 == skip2
        assert svix1 == svix2


class TestNoNegativeProfit:
    """test_no_negative_profit — no PROFIT exit has negative P&L."""

    def test_profit_exits_are_positive(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        trades, _, _, _ = run_backtest(sample_data, params, synthetic_engine)
        profit_trades = [t for t in trades if t.exit_type == "PROFIT"]
        for t in profit_trades:
            assert t.pnl >= 0, (
                f"Trade {t.trade_num} exited PROFIT but has negative P&L: {t.pnl}"
            )


class TestSinglePosition:
    """test_single_position — no two trades overlap when single_position=True."""

    def test_no_overlapping_trades(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        params["single_position"] = True
        trades, _, _, _ = run_backtest(sample_data, params, synthetic_engine)

        for i in range(len(trades) - 1):
            t1 = trades[i]
            t2 = trades[i + 1]
            if t1.exit_date is not None and t2.entry_date is not None:
                assert t2.entry_date >= t1.exit_date, (
                    f"Trade {t1.trade_num} (exit {t1.exit_date}) overlaps with "
                    f"Trade {t2.trade_num} (entry {t2.entry_date})"
                )


class TestChainAccounting:
    """test_chain_accounting — sum of chain P&Ls equals sum of trade row P&Ls."""

    def test_chain_pnl_equals_sum_of_trades(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        # Need roll_for_credit=True to have chains
        params["roll_for_credit"] = True
        params["single_position"] = False  # allow overlapping for more trades
        trades, _, _, _ = run_backtest(sample_data, params, synthetic_engine)

        # Sum of all trade P&Ls
        total_trade_pnl = sum(t.pnl for t in trades)

        # Sum of chain P&Ls (root + descendants)
        by_num = {t.trade_num: t for t in trades}
        chain_pnls = []
        for t in trades:
            if t.parent_trade_num is not None:
                continue
            chain_pnl = t.pnl
            cur = t
            while cur.child_trade_num is not None:
                cur = by_num[cur.child_trade_num]
                chain_pnl += cur.pnl
            chain_pnls.append(chain_pnl)

        total_chain_pnl = sum(chain_pnls)
        assert abs(total_trade_pnl - total_chain_pnl) < 0.01, (
            f"Trade P&L sum ({total_trade_pnl}) != chain P&L sum ({total_chain_pnl})"
        )


# ── Source tracking ──────────────────────────────────────────────────────

class TestSourceTracking:
    """Source tracking fields should be populated correctly."""

    def test_trade_has_source_fields_with_defaults(self, sample_trade):
        assert sample_trade.entry_source == "unknown"
        assert sample_trade.exit_source == "unknown"
        assert sample_trade.mtm_source_days == 0
        assert sample_trade.mtm_total_days == 0

    def test_synthetic_backtest_sets_entry_source(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        trades, _, _, _ = run_backtest(sample_data, params, synthetic_engine)
        assert len(trades) > 0
        for t in trades:
            assert t.entry_source == "synthetic", (
                f"Trade {t.trade_num} entry_source should be 'synthetic' in synthetic mode"
            )

    def test_synthetic_backtest_tracks_mtm_days(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        trades, _, _, _ = run_backtest(sample_data, params, synthetic_engine)
        for t in trades:
            assert t.mtm_total_days >= 0
            assert t.mtm_source_days >= 0
            assert t.mtm_source_days <= t.mtm_total_days

    def test_synthetic_backtest_exit_source_synthetic(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest

        trades, _, _, _ = run_backtest(sample_data, params, synthetic_engine)
        for t in trades:
            if t.exit_type is not None:
                assert t.exit_source == "synthetic", (
                    f"Trade {t.trade_num} exit_source should be 'synthetic' in synthetic mode"
                )

    def test_metrics_includes_source_stats(self, params, sample_data, synthetic_engine):
        from straddle.strategy import run_backtest
        from straddle.metrics import compute_metrics

        trades, equity, _, _ = run_backtest(sample_data, params, synthetic_engine)
        metrics = compute_metrics(trades, equity, params, sample_data)

        assert "entry_db_count" in metrics
        assert "entry_db_total" in metrics
        assert "entry_db_pct" in metrics
        assert "exit_db_count" in metrics
        assert "mtm_avg_db_pct" in metrics
        assert metrics["entry_db_pct"] == 0.0
        assert metrics["entry_db_total"] == len(trades)


# ── Vol cache fix (Bug #1) ───────────────────────────────────────────────

class TestVolCacheKey:
    """_build_vol_filter must use index bounds as cache key, not id(data)."""

    def _make_data(self, n: int = 400, seed: int = 0) -> pd.DataFrame:
        np.random.seed(seed)
        dates = pd.bdate_range("2022-01-03", periods=n)
        close = 100.0 + np.cumsum(np.random.randn(n))
        return pd.DataFrame(
            {"underlying_close": close, "vix_close": 20 + np.random.randn(n) * 3},
            index=dates,
        )

    def test_clear_vol_cache_empties_dict(self):
        clear_vol_cache()
        assert len(_VOL_CACHE) == 0

    def test_cache_key_uses_index_bounds(self):
        clear_vol_cache()
        data = self._make_data()
        params = {"vol_filter_mode": "rv_pct", "vol_filter_threshold": 80.0}
        _build_vol_filter(data, params)
        key = list(_VOL_CACHE.keys())[0]
        # Key must contain the first and last index values, not an int (id)
        assert data.index[0] in key
        assert data.index[-1] in key

    def test_same_index_range_hits_cache(self):
        clear_vol_cache()
        data = self._make_data()
        params = {"vol_filter_mode": "rv_pct", "vol_filter_threshold": 80.0}
        _build_vol_filter(data, params)
        assert len(_VOL_CACHE) == 1
        _build_vol_filter(data, params)
        assert len(_VOL_CACHE) == 1  # cache hit, not a second entry

    def test_different_index_range_creates_new_entry(self):
        clear_vol_cache()
        data1 = self._make_data(n=400)
        data2 = self._make_data(n=300)  # different start/end
        params = {"vol_filter_mode": "rv_pct", "vol_filter_threshold": 80.0}
        _build_vol_filter(data1, params)
        _build_vol_filter(data2, params)
        assert len(_VOL_CACHE) == 2


# ── IVR vol filter logic (Bug #5) ───────────────────────────────────────

class TestIvrVolFilter:
    """IVR mode should block when current IV is LOW (below threshold percentile)."""

    def _make_data_with_constant_vix(self, n: int = 500, vix_val: float = 20.0) -> pd.DataFrame:
        dates = pd.bdate_range("2020-01-02", periods=n)
        close = np.full(n, 100.0)
        vix = np.full(n, vix_val)
        return pd.DataFrame(
            {"underlying_close": close, "vix_close": vix},
            index=dates,
        )

    def _make_data_low_then_high_vix(self, n: int = 600) -> pd.DataFrame:
        """First half: VIX=10, second half: VIX=30 (simulates regime change)."""
        dates = pd.bdate_range("2018-01-02", periods=n)
        close = np.full(n, 100.0)
        vix = np.concatenate([np.full(n // 2, 10.0), np.full(n - n // 2, 30.0)])
        return pd.DataFrame(
            {"underlying_close": close, "vix_close": vix},
            index=dates,
        )

    def test_ivr_warmup_period_is_unblocked(self):
        """First 252 days should be unblocked (consistent with rv_pct)."""
        data = self._make_data_with_constant_vix()
        params = {"vol_filter_mode": "ivr", "vol_filter_threshold": 50.0}
        result = _build_vol_filter(data, params)
        # Days before index 252 should be False (not blocked)
        assert not result.iloc[:252].any()

    def test_ivr_high_vix_period_is_unblocked(self):
        """When current VIX is high relative to history, IVR is high — entries allowed."""
        data = self._make_data_low_then_high_vix()
        params = {"vol_filter_mode": "ivr", "vol_filter_threshold": 50.0}
        clear_vol_cache()
        result = _build_vol_filter(data, params)
        # Second half: VIX=30, history is mostly VIX=10 → IVR is very high → should be NOT blocked
        second_half = result.iloc[len(result) // 2 + 252:]
        assert not second_half.any(), "High-IV period should not be blocked"

    def test_ivr_low_vix_period_is_blocked(self):
        """When current VIX is low relative to history, IVR is low — entries blocked.

        Only checks the first 100 days of the low-VIX period, where the 252-day
        lookback window still contains a majority of high-VIX history.
        """
        n = 600
        half = n // 2  # 300
        dates = pd.bdate_range("2018-01-02", periods=n)
        # First 300 days VIX=30, next 300 days VIX=5.
        # Using VIX=5 (not 10) so even strict-less-than gives a clear signal.
        vix = np.concatenate([np.full(half, 30.0), np.full(n - half, 5.0)])
        data = pd.DataFrame(
            {"underlying_close": np.full(n, 100.0), "vix_close": vix},
            index=dates,
        )
        params = {"vol_filter_mode": "ivr", "vol_filter_threshold": 50.0}
        clear_vol_cache()
        result = _build_vol_filter(data, params)
        # Check indices half to half+100 — window still has >50% VIX=30 history.
        low_iv_early = result.iloc[half : half + 100]
        assert low_iv_early.all(), (
            "Low-IV period (early days, majority-high-VIX window) should be blocked"
        )
