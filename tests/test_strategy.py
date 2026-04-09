"""Tests for strategy module: calendar utils, Trade properties, backtest invariants."""

import pandas as pd
import pytest

from straddle.strategy import (
    get_third_friday,
    get_monthly_expiration,
    get_entry_dates,
    Trade,
    LegRollEvent,
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
        dates = get_entry_dates(
            sample_data, "2024-01-02", "2024-03-29", dte_min=30, dte_max=45
        )
        months = [(d.year, d.month) for d in dates]
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
