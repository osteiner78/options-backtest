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


class TestMarketEngineFillAdj:
    """Verify that MarketEngine applies fill adjustment on synthetic fallback."""

    @pytest.fixture
    def market_engine(self, params):
        """MarketEngine with BOVA11 preset, or Skip if DB unavailable."""
        from straddle.engines import MarketEngine
        from straddle.params import apply_market_preset
        params = apply_market_preset(dict(params), "bova11")
        params["mode"] = "market"
        params["use_cdi_ivs"] = False
        try:
            engine = MarketEngine(params)
            yield engine
            engine.close()
        except (FileNotFoundError, Exception) as e:
            pytest.skip(f"MarketEngine unavailable: {e}")

    @pytest.fixture
    def synth(self, params):
        from straddle.engines import SyntheticEngine
        from straddle.params import apply_market_preset
        params = apply_market_preset(dict(params), "bova11")
        return SyntheticEngine(params)

    # ── DB marks are untouched ───────────────────────────────────────────
    def test_db_marks_unchanged_by_adj(self, market_engine):
        """When DB has valid data, marks come from DB directly (no fill adj)."""
        from straddle.engines import PricingContext
        import pandas as pd
        ctx = PricingContext(
            eval_date=pd.Timestamp("2023-01-03"),
            expiration=pd.Timestamp("2023-02-17"),
        )
        mark, src = market_engine.get_leg_mark_with_source(
            93.0, 100.0, 45, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="buy"
        )
        assert src == "db"
        assert mark > 0

    # ── Synthetic fallback applies close adj (buy) ───────────────────────
    def test_synthetic_fallback_close_adj(self, market_engine, synth):
        """Synthetic fallback marks for buy-side get close fill adj (+5%)."""
        from straddle.engines import PricingContext
        import pandas as pd
        # Use a date before DB_START to force synthetic fallback
        ctx = PricingContext(
            eval_date=pd.Timestamp("2005-01-03"),  # pre-2008
            expiration=pd.Timestamp("2005-02-18"),
        )
        mark, src = market_engine.get_leg_mark_with_source(
            93.0, 100.0, 45, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="buy"
        )
        assert src == "synthetic"
        synth_mid = synth.get_leg_mark(93.0, 100.0, 45, 20.0, 0.12, "put", ctx=ctx)
        expected = synth.apply_fill_adj(synth_mid, "close")
        assert mark == pytest.approx(expected, rel=1e-6)

    # ── Synthetic fallback applies open adj (sell) ───────────────────────
    def test_synthetic_fallback_open_adj(self, market_engine, synth):
        """Synthetic fallback marks for sell-side get open fill adj (-5%)."""
        from straddle.engines import PricingContext
        import pandas as pd
        ctx = PricingContext(
            eval_date=pd.Timestamp("2005-01-03"),
            expiration=pd.Timestamp("2005-02-18"),
        )
        mark, src = market_engine.get_leg_mark_with_source(
            93.0, 100.0, 45, 20.0, 0.12, "put", ctx=ctx, buy_or_sell="sell"
        )
        assert src == "synthetic"
        synth_mid = synth.get_leg_mark(93.0, 100.0, 45, 20.0, 0.12, "put", ctx=ctx)
        expected = synth.apply_fill_adj(synth_mid, "open")
        assert mark == pytest.approx(expected, rel=1e-6)

    # ── Entry synthetic fallback applies adj ─────────────────────────────
    def test_entry_synthetic_fallback_adj(self, market_engine, synth):
        """Synthetic-fallback entry applies open fill adj to combined credit."""
        from straddle.engines import PricingContext
        import pandas as pd
        ctx = PricingContext(
            eval_date=pd.Timestamp("2005-01-03"),
            expiration=pd.Timestamp("2005-02-18"),
            target_delta=0.16,
        )
        S, T, r, vix = 100.0, 45 / 365.0, 0.12, 20.0
        pk, ck, pm, cm, used_db = market_engine.get_entry_marks(S, T, r, vix, ctx=ctx)
        assert used_db is False

        # Pure synthetic entry should match
        pk_s, ck_s, pm_s, cm_s, _ = synth.get_entry_marks(S, T, r, vix, ctx=ctx)
        adj_combined = synth.apply_fill_adj(pm_s + cm_s, "open")
        assert (pm + cm) == pytest.approx(adj_combined, rel=1e-6)

    # ── apply_fill_adj is no-op for DB-sourced marks ─────────────────────
    def test_apply_fill_adj_noop(self, market_engine):
        """MarketEngine.apply_fill_adj is a no-op (bid/ask embeds spread)."""
        assert market_engine.apply_fill_adj(2.0, "open") == 2.0
        assert market_engine.apply_fill_adj(2.0, "close") == 2.0
