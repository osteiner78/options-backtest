"""Tests for MarketEngine execution modes (bid_ask, mid, mid_minus_1tick,
mid_plus_1tick).

Uses an in-memory SQLite DB with known data to keep tests fast and deterministic.
"""

import sqlite3
import tempfile
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from straddle.engines import MarketEngine, SyntheticEngine, PricingContext
from straddle.params import PARAMS, apply_market_preset

# BOVA11-like test data: realistic prices with known bid/ask/mark/volume
_TEST_ROWS = [
    # date, expiration, type, strike, mark, bid, ask, volume, delta, iv
    # Standard put/call at 16-delta for entry tests
    ("2024-01-05", "2024-02-16", "put", 112.0, 1.20, 1.10, 1.30, 1000, -0.17, 0.22),
    ("2024-01-05", "2024-02-16", "call", 132.0, 0.80, 0.70, 0.90, 1000, 0.17, 0.18),
    # Alternative strikes for different delta targets
    ("2024-01-05", "2024-02-16", "put", 110.0, 1.00, 0.90, 1.10, 100, -0.13, 0.20),
    ("2024-01-05", "2024-02-16", "call", 134.0, 0.60, 0.50, 0.70, 100, 0.12, 0.16),
    # Zero-bid row for bid_ask fallback test
    ("2024-01-05", "2024-02-16", "put", 115.0, 0.90, 0.00, 1.00, 1000, -0.14, 0.20),
    ("2024-01-05", "2024-02-16", "call", 135.0, 0.40, 0.00, 0.60, 1000, 0.14, 0.16),
]

EXPIRY = "2024-02-16"


def _make_test_db() -> str:
    """Create an in-memory SQLite DB and dump it to a temp file so MarketEngine
    can open it as a file-based DB (check_same_thread=False requires a file)."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE options_data (
            date TEXT, expiration TEXT, type TEXT, strike REAL,
            underlying TEXT, mark REAL, bid REAL, ask REAL,
            volume INTEGER, delta REAL, implied_volatility REAL
        )
    """)
    for row in _TEST_ROWS:
        conn.execute(
            "INSERT INTO options_data VALUES (?, ?, ?, ?, 'bova11', ?, ?, ?, ?, ?, ?)",
            row,
        )
    conn.commit()

    # Dump to temp file
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    disk = sqlite3.connect(path)
    conn.backup(disk)
    disk.close()
    conn.close()
    return path


def _make_params(exec_mode: str, db_path: str) -> dict:
    """Create params dict for a MarketEngine with given execution mode."""
    params = dict(PARAMS)
    params = apply_market_preset(params, "bova11")
    params["mode"] = "market"
    params["start_date"] = "2024-01-01"
    params["end_date"] = "2024-01-31"
    params["options_db_path"] = db_path
    params["execution_mode"] = exec_mode
    params["tick_size"] = 0.05
    params["use_cdi_ivs"] = False
    return params


class TestBidAskMode:
    def test_bid_ask_uses_bid_to_sell(self):
        """Entry price = bid for bid_ask mode."""
        db_path = _make_test_db()
        try:
            params = _make_params("bid_ask", db_path)
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
                target_delta=0.16,
            )
            S, T, r, vix = 120.0, 42 / 365.0, 0.12, 20.0
            pk, ck, pp, cp, used_db = engine.get_entry_marks(S, T, r, vix, ctx=ctx)
            assert used_db is True
            # put_row bid = 1.10, call_row bid = 0.70
            assert pp == pytest.approx(1.10)
            assert cp == pytest.approx(0.70)
            engine.close()
        finally:
            os.unlink(db_path)

    def test_bid_ask_zero_bid_falls_back(self):
        """When bid is zero, bid_ask mode falls back to synthetic."""
        db_path = _make_test_db()
        try:
            params = _make_params("bid_ask", db_path)
            params["target_delta"] = 0.14  # match zero-bid rows (put 115 delta=-0.14, call 135 delta=0.14)
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
                target_delta=0.14,
            )
            S, T, r, vix = 120.0, 42 / 365.0, 0.12, 20.0
            pk, ck, pp, cp, used_db = engine.get_entry_marks(S, T, r, vix, ctx=ctx)
            # Zero bid rows → should fall back to synthetic (used_db=False)
            assert used_db is False
            engine.close()
        finally:
            os.unlink(db_path)


class TestMidMode:
    def test_mid_uses_mark(self):
        """Entry price = mark for mid mode."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
                target_delta=0.16,
            )
            S, T, r, vix = 120.0, 42 / 365.0, 0.12, 20.0
            pk, ck, pp, cp, used_db = engine.get_entry_marks(S, T, r, vix, ctx=ctx)
            assert used_db is True
            # put_row mark = 1.20, call_row mark = 0.80
            assert pp == pytest.approx(1.20)
            assert cp == pytest.approx(0.80)
            engine.close()
        finally:
            os.unlink(db_path)


class TestMidMinusOneTick:
    def test_mid_minus_1tick_below_mid(self):
        """Entry price = mark - tick for mid_minus_1tick."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid_minus_1tick", db_path)
            params["tick_size"] = 0.05
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
                target_delta=0.16,
            )
            S, T, r, vix = 120.0, 42 / 365.0, 0.12, 20.0
            pk, ck, pp, cp, used_db = engine.get_entry_marks(S, T, r, vix, ctx=ctx)
            assert used_db is True
            # put_mark = 1.20 - 0.05 = 1.15, call_mark = 0.80 - 0.05 = 0.75
            assert pp == pytest.approx(1.15)
            assert cp == pytest.approx(0.75)
            engine.close()
        finally:
            os.unlink(db_path)

    def test_mid_minus_1tick_floor(self):
        """Entry price floors at 0.01 for mid_minus_1tick when mark < tick."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid_minus_1tick", db_path)
            params["tick_size"] = 5.00  # mark is 1.20 and 0.80
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
                target_delta=0.16,
            )
            S, T, r, vix = 120.0, 42 / 365.0, 0.12, 20.0
            pk, ck, pp, cp, used_db = engine.get_entry_marks(S, T, r, vix, ctx=ctx)
            assert used_db is True
            assert pp == pytest.approx(0.01)  # floored
            assert cp == pytest.approx(0.01)  # floored
            engine.close()
        finally:
            os.unlink(db_path)


class TestMidPlusOneTick:
    def test_mid_plus_1tick_above_mid(self):
        """Entry price = mark + tick for mid_plus_1tick."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid_plus_1tick", db_path)
            params["tick_size"] = 0.05
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
                target_delta=0.16,
            )
            S, T, r, vix = 120.0, 42 / 365.0, 0.12, 20.0
            pk, ck, pp, cp, used_db = engine.get_entry_marks(S, T, r, vix, ctx=ctx)
            assert used_db is True
            # put_mark = 1.20 + 0.05 = 1.25, call_mark = 0.80 + 0.05 = 0.85
            assert pp == pytest.approx(1.25)
            assert cp == pytest.approx(0.85)
            engine.close()
        finally:
            os.unlink(db_path)


class TestCloseSideExecution:
    def test_bid_ask_close_uses_ask(self):
        """Close leg mark uses ask for bid_ask mode."""
        db_path = _make_test_db()
        try:
            params = _make_params("bid_ask", db_path)
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
            )
            mark, src = engine.get_leg_mark_with_source(
                112.0, 120.0, 42, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="buy"
            )
            assert src == "db"
            # ask = 1.30
            assert mark == pytest.approx(1.30)
            engine.close()
        finally:
            os.unlink(db_path)

    def test_mid_close_uses_mark(self):
        """Close leg mark uses mark for mid mode."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
            )
            mark, src = engine.get_leg_mark_with_source(
                112.0, 120.0, 42, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="buy"
            )
            assert src == "db"
            # mark = 1.20
            assert mark == pytest.approx(1.20)
            engine.close()
        finally:
            os.unlink(db_path)

    def test_mid_minus_close_uses_mark_plus_tick(self):
        """Close leg mark uses mark+tick for mid_minus_1tick (mirrors entry)."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid_minus_1tick", db_path)
            params["tick_size"] = 0.05
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
            )
            mark, src = engine.get_leg_mark_with_source(
                112.0, 120.0, 42, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="buy"
            )
            assert src == "db"
            # mark = 1.20 + 0.05 = 1.25
            assert mark == pytest.approx(1.25)
            engine.close()
        finally:
            os.unlink(db_path)

    def test_mid_plus_close_uses_mark_minus_tick(self):
        """Close leg mark uses mark-tick for mid_plus_1tick (mirrors entry)."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid_plus_1tick", db_path)
            params["tick_size"] = 0.05
            engine = MarketEngine(params)
            ctx = PricingContext(
                eval_date=pd.Timestamp("2024-01-05"),
                expiration=pd.Timestamp(EXPIRY),
            )
            mark, src = engine.get_leg_mark_with_source(
                112.0, 120.0, 42, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="buy"
            )
            assert src == "db"
            # mark = 1.20 - 0.05 = 1.15
            assert mark == pytest.approx(1.15)
            engine.close()
        finally:
            os.unlink(db_path)

    def test_sell_side_unaffected_by_exec_mode(self):
        """Sell side (buy_or_sell='sell') always uses bid regardless of exec mode."""
        db_path = _make_test_db()
        try:
            for mode in ["bid_ask", "mid", "mid_minus_1tick", "mid_plus_1tick"]:
                params = _make_params(mode, db_path)
                params["tick_size"] = 0.05
                engine = MarketEngine(params)
                ctx = PricingContext(
                    eval_date=pd.Timestamp("2024-01-05"),
                    expiration=pd.Timestamp(EXPIRY),
                )
                mark, src = engine.get_leg_mark_with_source(
                    112.0, 120.0, 42, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="sell"
                )
                # sell side always uses bid = 1.10
                assert mark == pytest.approx(1.10), f"Mode {mode} failed"
                engine.close()
        finally:
            os.unlink(db_path)


class TestDBExpiration:
    """Verify that MarketEngine.get_db_expiration returns actual DB expirations."""

    def test_db_expiration_finds_valid_dte(self):
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            result = engine.get_db_expiration("2024-01-05", 30, 60)
            assert result == pd.Timestamp("2024-02-16")
            engine.close()
        finally:
            os.unlink(db_path)

    def test_db_expiration_returns_none_if_no_match(self):
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            result = engine.get_db_expiration("2024-01-05", 100, 120)
            assert result is None
            engine.close()
        finally:
            os.unlink(db_path)

    def test_db_expiration_with_expected_month(self):
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            expected = pd.Timestamp("2024-02-16")
            result = engine.get_db_expiration("2024-01-05", 20, 60, expected_month=expected)
            assert result == pd.Timestamp("2024-02-16")
            engine.close()
        finally:
            os.unlink(db_path)

    def test_db_expiration_expected_month_filters_far_expirations(self):
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            expected_march = pd.Timestamp("2024-03-15")
            result = engine.get_db_expiration("2024-01-05", 30, 80, expected_month=expected_march)
            assert result is None
            engine.close()
        finally:
            os.unlink(db_path)


class TestExpirationResolution:
    """Verify that get_monthly_expiration uses DB when engine is provided."""

    def test_calendar_fallback_when_no_engine(self):
        from straddle.strategy import get_monthly_expiration
        entry = pd.Timestamp("2024-01-05")
        result = get_monthly_expiration(entry, 30, 60, calendar="BVMF")
        assert result == pd.Timestamp("2024-02-16")

    def test_db_overrides_calendar(self):
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            from straddle.strategy import get_monthly_expiration
            entry = pd.Timestamp("2024-01-05")
            result = get_monthly_expiration(entry, 30, 60, calendar="BVMF", engine=engine)
            assert result == pd.Timestamp("2024-02-16")
            engine.close()
        finally:
            os.unlink(db_path)
