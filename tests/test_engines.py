"""Tests for pricing engines: Black-Scholes primitives, SyntheticEngine, apply_skew."""

import numpy as np
import pandas as pd
import pytest

from straddle.engines import (
    bs_price,
    bs_delta,
    strike_from_delta,
    apply_skew,
    SyntheticEngine,
)


# ── Black-Scholes primitives ─────────────────────────────────────────────

class TestBSPrice:
    """bs_price should return correct values for known inputs."""

    def test_call_at_the_money(self):
        # ATM call with T=1, r=0, sigma=0.2 → price ≈ 0.08 * S
        price = bs_price(S=100.0, K=100.0, T=1.0, r=0.0, sigma=0.2, opt="call")
        assert 7.0 < price < 9.0  # ~7.97

    def test_put_at_the_money(self):
        price = bs_price(S=100.0, K=100.0, T=1.0, r=0.0, sigma=0.2, opt="put")
        assert 7.0 < price < 9.0  # put-call parity, same as call when r=0

    def test_call_deep_itm(self):
        # Deep ITM call ≈ S - K
        price = bs_price(S=100.0, K=50.0, T=0.01, r=0.0, sigma=0.2, opt="call")
        assert 49.0 < price < 51.0

    def test_put_deep_itm(self):
        price = bs_price(S=50.0, K=100.0, T=0.01, r=0.0, sigma=0.2, opt="put")
        assert 49.0 < price < 51.0

    def test_call_otm_near_expiry(self):
        price = bs_price(S=100.0, K=110.0, T=0.001, r=0.0, sigma=0.2, opt="call")
        assert price < 0.01  # essentially worthless

    def test_put_otm_near_expiry(self):
        price = bs_price(S=100.0, K=90.0, T=0.001, r=0.0, sigma=0.2, opt="put")
        assert price < 0.01

    def test_zero_expiry_itm_call(self):
        price = bs_price(S=100.0, K=90.0, T=0.0, r=0.0, sigma=0.2, opt="call")
        assert price == 10.0

    def test_zero_expiry_itm_put(self):
        price = bs_price(S=90.0, K=100.0, T=0.0, r=0.0, sigma=0.2, opt="put")
        assert price == 10.0


class TestBSDelta:
    """bs_delta should return correct delta values."""

    def test_call_atm_delta(self):
        delta = bs_delta(S=100.0, K=100.0, T=1.0, r=0.0, sigma=0.2, opt="call")
        assert 0.5 < delta < 0.6  # ATM call delta ≈ 0.53

    def test_put_atm_delta(self):
        delta = bs_delta(S=100.0, K=100.0, T=1.0, r=0.0, sigma=0.2, opt="put")
        assert -0.6 < delta < -0.4  # ATM put delta ≈ -0.47

    def test_call_deep_itm_delta(self):
        delta = bs_delta(S=100.0, K=50.0, T=0.01, r=0.0, sigma=0.2, opt="call")
        assert delta > 0.99

    def test_put_deep_itm_delta(self):
        delta = bs_delta(S=50.0, K=100.0, T=0.01, r=0.0, sigma=0.2, opt="put")
        assert delta < -0.99

    def test_call_deep_otm_delta(self):
        delta = bs_delta(S=100.0, K=150.0, T=0.01, r=0.0, sigma=0.2, opt="call")
        assert delta < 0.01

    def test_put_deep_otm_delta(self):
        delta = bs_delta(S=100.0, K=50.0, T=0.01, r=0.0, sigma=0.2, opt="put")
        assert delta > -0.01


class TestStrikeFromDelta:
    """strike_from_delta should compute strikes that achieve target delta."""

    def test_16_delta_call(self):
        K = strike_from_delta(
            S=100.0, T=1.0, r=0.0, sigma=0.2, target_delta=0.16, opt="call"
        )
        # Verify the resulting delta is close to 0.16
        delta = bs_delta(S=100.0, K=K, T=1.0, r=0.0, sigma=0.2, opt="call")
        assert abs(delta - 0.16) < 0.02  # within 2% due to rounding

    def test_16_delta_put(self):
        K = strike_from_delta(
            S=100.0, T=1.0, r=0.0, sigma=0.2, target_delta=0.16, opt="put"
        )
        delta = bs_delta(S=100.0, K=K, T=1.0, r=0.0, sigma=0.2, opt="put")
        assert abs(delta - (-0.16)) < 0.02

    def test_rounded_to_increment(self):
        K = strike_from_delta(
            S=100.0, T=1.0, r=0.0, sigma=0.2, target_delta=0.16, opt="call",
            increment=5.0,
        )
        assert K % 5.0 == 0.0


class TestApplySkew:
    """apply_skew should adjust vol correctly for put and call legs."""

    def test_put_skew_increases_vol(self):
        sigma = apply_skew(sigma_atm=0.20, delta=0.16, opt="put")
        assert sigma > 0.20  # OTM puts have higher vol

    def test_call_skew_decreases_vol(self):
        sigma = apply_skew(sigma_atm=0.20, delta=0.16, opt="call")
        assert sigma < 0.20  # OTM calls have lower vol

    def test_atm_no_adjustment(self):
        # At delta=0.50, distance_from_atm = 0, so no adjustment
        sigma_put = apply_skew(sigma_atm=0.20, delta=0.50, opt="put")
        sigma_call = apply_skew(sigma_atm=0.20, delta=0.50, opt="call")
        assert sigma_put == 0.20
        assert sigma_call == 0.20

    def test_put_skew_magnitude(self):
        # 16Δ put: distance = 0.50 - 0.16 = 0.34
        # sigma = 0.20 * (1 + 0.30 * 0.34) = 0.20 * 1.102 = 0.2204
        sigma = apply_skew(sigma_atm=0.20, delta=0.16, opt="put", put_slope=0.30)
        assert abs(sigma - 0.2204) < 0.001

    def test_call_skew_magnitude(self):
        # 16Δ call: distance = 0.34
        # sigma = 0.20 * (1 - 0.10 * 0.34) = 0.20 * 0.966 = 0.1932
        sigma = apply_skew(sigma_atm=0.20, delta=0.16, opt="call", call_slope=0.10)
        assert abs(sigma - 0.1932) < 0.001


# ── SyntheticEngine ──────────────────────────────────────────────────────

class TestSyntheticEngine:
    """SyntheticEngine should produce deterministic, reasonable outputs."""

    def test_get_entry_marks(self, synthetic_engine, params):
        """Entry marks should return strikes and per-share mids."""
        S = 470.0
        T = 42 / 365.0
        r = 0.045
        vix = 14.0

        put_k, call_k, put_mid, call_mid, used_db = synthetic_engine.get_entry_marks(
            S, T, r, vix
        )
        assert put_k < S < call_k  # OTM strikes
        assert put_mid > 0
        assert call_mid > 0
        assert used_db is False

    def test_get_daily_mark(self, synthetic_engine, params):
        """Daily mark should return a reasonable position value."""
        S = 470.0
        T = 42 / 365.0
        r = 0.045
        vix = 14.0
        put_k, call_k, put_mid, call_mid, _ = synthetic_engine.get_entry_marks(
            S, T, r, vix
        )

        mark = synthetic_engine.get_daily_mark(
            put_k=put_k,
            call_k=call_k,
            S_d=S,
            dte_rem=42,
            vix_d=vix,
            r_d=r,
        )
        # At entry conditions, mark should be close to the entry mid
        entry_mid = put_mid + call_mid
        assert abs(mark - entry_mid) < entry_mid * 0.05

    def test_get_daily_delta(self, synthetic_engine):
        """Delta should be negative for puts, positive for calls."""
        put_delta = synthetic_engine.get_daily_delta(
            strike=450.0, S_d=470.0, dte_rem=42, vix_d=14.0, r_d=0.045, opt="put"
        )
        call_delta = synthetic_engine.get_daily_delta(
            strike=490.0, S_d=470.0, dte_rem=42, vix_d=14.0, r_d=0.045, opt="call"
        )
        assert put_delta < 0
        assert call_delta > 0

    def test_engine_parity(self, synthetic_engine):
        """Running the same inputs twice should yield identical results."""
        S = 470.0
        T = 42 / 365.0
        r = 0.045
        vix = 14.0

        result1 = synthetic_engine.get_entry_marks(S, T, r, vix)
        result2 = synthetic_engine.get_entry_marks(S, T, r, vix)
        assert result1 == result2
