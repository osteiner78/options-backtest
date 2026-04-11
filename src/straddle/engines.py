"""Pricing engines: SyntheticEngine, MarketEngine, and make_engine factory.

Two engines share the same interface consumed by ``run_backtest``:

- **SyntheticEngine** — Black-Scholes pricing using VIX as ATM vol and a
  parametric equity-smirk skew.
- **MarketEngine** — Real bid/ask/mark from the SQLite options database
  (2008–2025), with per-leg synthetic fallback on missing data.

Gap-open pricing always uses SyntheticEngine in both modes — the DB is
EOD-only, so intraday stop modelling is always synthetic.
"""

from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm

from straddle.data import validate_market_mode_dates
from straddle.params import RISK_FREE_RATE_DEFAULT


# ── Pricing Context ──────────────────────────────────────────────────────

@dataclass
class PricingContext:
    """Optional metadata for engine lookups (dates, expirations)."""
    eval_date: Optional[pd.Timestamp] = None
    expiration: Optional[pd.Timestamp] = None
    target_delta: Optional[float] = None # can override default engine delta


# ── Black-Scholes primitives ─────────────────────────────────────────────

def bs_price(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    """Black-Scholes European option price. opt: 'call' or 'put'."""
    if T <= 1e-7:
        return max(S - K, 0.0) if opt == "call" else max(K - S, 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if opt == "call":
        return float(S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2))
    return float(K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1))


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, opt: str) -> float:
    """Black-Scholes delta (put delta is negative)."""
    if T <= 1e-7:
        return (1.0 if S > K else 0.0) if opt == "call" else (-1.0 if S < K else 0.0)
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    return float(norm.cdf(d1) if opt == "call" else norm.cdf(d1) - 1.0)


def strike_from_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta: float,
    opt: str,
    increment: float = 1.0,
) -> float:
    """Analytically compute the strike that achieves target_delta, rounded to increment."""
    d1 = norm.ppf(target_delta) if opt == "call" else norm.ppf(1.0 - target_delta)
    K = S * np.exp(-d1 * sigma * np.sqrt(T) + (r + 0.5 * sigma**2) * T)
    return round(K / increment) * increment


def apply_skew(
    sigma_atm: float,
    delta: float,
    opt: str,
    put_slope: float = 0.30,
    call_slope: float = 0.10,
) -> float:
    """Return a skew-adjusted implied vol for a single leg (equity smirk model)."""
    distance_from_atm = 0.50 - abs(delta)
    if opt == "put":
        return sigma_atm * (1.0 + put_slope * distance_from_atm)
    else:
        return sigma_atm * (1.0 - call_slope * distance_from_atm)


# ── SyntheticEngine ──────────────────────────────────────────────────────

class SyntheticEngine:
    """Black-Scholes pricing engine for the short-strangle backtest."""

    uses_real_fills = False

    def __init__(self, params: dict) -> None:
        self.delta = params["target_delta"]
        self.put_slope = params.get("put_slope", 0.30)
        self.call_slope = params.get("call_slope", 0.10)
        self.r_default = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT)
        self.gap_mult = params.get("gap_vix_multiplier", 3.0)
        self.vix_iv_mult = params.get("vix_to_iv_multiplier", 1.0)
        self.o_adj = params.get("open_fill_adj", -0.05)
        self.c_adj = params.get("close_fill_adj", 0.05)

    def _get_sigma_t(self, vix_d: float, dte_rem: int) -> Tuple[float, float]:
        """Central helper for volatility scaling and time-to-expiry conversion."""
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        T_d = max(dte_rem / 365.0, 1e-7)
        return sigma_d, T_d

    def apply_fill_adj(self, mid_ps: float, side: str) -> float:
        """Apply synthetic fill adjustment. side: 'open' or 'close'."""
        if side == "open":
            return mid_ps * (1.0 + self.o_adj)
        return mid_ps * (1.0 + self.c_adj)

    def get_entry_marks(
        self, S: float, T: float, r: float, vix: float, ctx: PricingContext = None
    ) -> tuple:
        """Compute 16-delta strikes and per-share mids at trade entry."""
        sigma = (vix / 100.0) * self.vix_iv_mult
        target_delta = (ctx.target_delta if ctx else None) or self.delta
        sigma_put = apply_skew(sigma, target_delta, "put", self.put_slope, self.call_slope)
        sigma_call = apply_skew(sigma, target_delta, "call", self.put_slope, self.call_slope)
        put_k = strike_from_delta(S, T, r, sigma_put, target_delta, "put")
        call_k = strike_from_delta(S, T, r, sigma_call, target_delta, "call")
        put_mid = bs_price(S, put_k, T, r, sigma_put, "put")
        call_mid = bs_price(S, call_k, T, r, sigma_call, "call")
        return put_k, call_k, put_mid, call_mid, False

    def get_daily_mark(
        self,
        put_k: float,
        call_k: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        ctx: PricingContext = None,
    ) -> float:
        """Combined per-share strangle mid at EOD during the hold period."""
        sigma_d, T_d = self._get_sigma_t(vix_d, dte_rem)
        d_put_est = bs_delta(S_d, put_k, T_d, r_d, sigma_d, "put")
        d_call_est = bs_delta(S_d, call_k, T_d, r_d, sigma_d, "call")
        sigma_put = apply_skew(sigma_d, d_put_est, "put", self.put_slope, self.call_slope)
        sigma_call = apply_skew(sigma_d, d_call_est, "call", self.put_slope, self.call_slope)
        return bs_price(S_d, put_k, T_d, r_d, sigma_put, "put") + bs_price(S_d, call_k, T_d, r_d, sigma_call, "call")

    def get_daily_delta(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        ctx: PricingContext = None,
    ) -> float:
        """Per-leg delta on eval_date."""
        sigma_d, T_d = self._get_sigma_t(vix_d, dte_rem)
        d_est = bs_delta(S_d, strike, T_d, r_d, sigma_d, opt)
        sigma_skewed = apply_skew(sigma_d, d_est, opt, self.put_slope, self.call_slope)
        return bs_delta(S_d, strike, T_d, r_d, sigma_skewed, opt)

    def get_leg_mark(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        ctx: PricingContext = None,
    ) -> float:
        """Per-share BS mid for a single leg."""
        sigma_d, T_d = self._get_sigma_t(vix_d, dte_rem)
        d_est = bs_delta(S_d, strike, T_d, r_d, sigma_d, opt)
        sigma_skewed = apply_skew(sigma_d, d_est, opt, self.put_slope, self.call_slope)
        return bs_price(S_d, strike, T_d, r_d, sigma_skewed, opt)

    def find_strike_at_delta(
        self,
        S_d: float,
        T_d: float,
        r_d: float,
        vix_d: float,
        target_delta: float,
        opt: str,
        ctx: PricingContext = None,
    ) -> tuple:
        """Return (strike, per-share mid) for a new leg at target_delta."""
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        sigma_skewed = apply_skew(sigma_d, target_delta, opt, self.put_slope, self.call_slope)
        strike = strike_from_delta(S_d, T_d, r_d, sigma_skewed, target_delta, opt)
        mark = bs_price(S_d, strike, T_d, r_d, sigma_skewed, opt)
        return strike, mark

    def get_gap_open_mark(
        self,
        spy_open: float,
        vix_prev_raw: float,
        gap_pct: float,
        put_k: float,
        call_k: float,
        T_d: float,
        r_open: float,
        ctx: PricingContext = None,
    ) -> float:
        """Per-share strangle mid priced at the open on a gap day."""
        vix_open_sigma = (vix_prev_raw * (1.0 + self.gap_mult * gap_pct)) * self.vix_iv_mult
        target_delta = (ctx.target_delta if ctx else None) or self.delta
        sigma_put = apply_skew(vix_open_sigma, target_delta, "put", self.put_slope, self.call_slope)
        sigma_call = apply_skew(vix_open_sigma, target_delta, "call", self.put_slope, self.call_slope)
        return bs_price(spy_open, put_k, T_d, r_open, sigma_put, "put") + bs_price(spy_open, call_k, T_d, r_open, sigma_call, "call")


# ── MarketEngine ─────────────────────────────────────────────────────────

class MarketEngine:
    """Real-data pricing engine backed by the SQLite options database."""

    _DB_START = pd.Timestamp("2008-01-02")
    uses_real_fills = True

    def __init__(self, params: dict) -> None:
        import sqlite3 as _sqlite3
        validate_market_mode_dates(params["start_date"], params["end_date"])
        self._synth = SyntheticEngine(params)
        db_path = params.get("db_path", "data/Spy Options Database.db")
        self._con = _sqlite3.connect(db_path, check_same_thread=False)
        self._con.row_factory = _sqlite3.Row
        self.delta = params["target_delta"]
        print(f"MarketEngine: connected to {db_path}")

    def apply_fill_adj(self, mid_ps: float, side: str) -> float:
        """Market mode: fill adjustment is already baked into bid/ask selection."""
        return mid_ps

    # ── public interface ────────────────────────────────────────────────

    def get_entry_marks(self, S: float, T: float, r: float, vix: float, ctx: PricingContext = None) -> tuple:
        """Nearest-delta strike and mark from DB at entry."""
        if ctx is None or ctx.eval_date is None or ctx.expiration is None or ctx.eval_date < self._DB_START:
            return self._synth.get_entry_marks(S, T, r, vix, ctx)

        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        target_delta = ctx.target_delta or self.delta
        put_row = self._best_row(date_str, exp_str, "put", -target_delta)
        call_row = self._best_row(date_str, exp_str, "call", +target_delta)

        if put_row is None or call_row is None:
            return self._synth.get_entry_marks(S, T, r, vix, ctx)

        return (float(put_row["strike"]), float(call_row["strike"]), float(put_row["bid"]), float(call_row["bid"]), True)

    def get_daily_mark(self, put_k: float, call_k: float, S_d: float, dte_rem: int, vix_d: float, r_d: float, ctx: PricingContext = None) -> float:
        """Sum of put and call ask prices from DB on eval_date."""
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START:
            return self._synth.get_daily_mark(put_k, call_k, S_d, dte_rem, vix_d, r_d, ctx)

        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d") if ctx.expiration else None
        put_mark = self._strike_ask(date_str, exp_str, "put", put_k)
        call_mark = self._strike_ask(date_str, exp_str, "call", call_k)

        if put_mark is None:
            put_mark = self._synth.get_leg_mark(put_k, S_d, dte_rem, vix_d, r_d, "put", ctx)
        if call_mark is None:
            call_mark = self._synth.get_leg_mark(call_k, S_d, dte_rem, vix_d, r_d, "call", ctx)

        return float(put_mark) + float(call_mark)

    def get_gap_open_mark(self, spy_open: float, vix_prev_raw: float, gap_pct: float, put_k: float, call_k: float, T_d: float, r_open: float, ctx: PricingContext = None) -> float:
        """Always synthetic -- DB is EOD-only."""
        return self._synth.get_gap_open_mark(spy_open, vix_prev_raw, gap_pct, put_k, call_k, T_d, r_open, ctx)

    def get_daily_delta(self, strike: float, S_d: float, dte_rem: int, vix_d: float, r_d: float, opt: str, ctx: PricingContext = None) -> float:
        """Per-leg delta from DB on eval_date; falls back to synthetic BS."""
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            return self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        cur = self._con.execute(
            "SELECT delta FROM options_data WHERE date = ? AND expiration = ? AND type = ? AND strike = ? AND mark > 0 LIMIT 1",
            (date_str, exp_str, opt, strike),
        )
        row = cur.fetchone()
        return float(row["delta"]) if (row and row["delta"] is not None) else self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)

    def get_leg_mark(self, strike: float, S_d: float, dte_rem: int, vix_d: float, r_d: float, opt: str, ctx: PricingContext = None) -> float:
        """Ask price for one leg from DB; falls back to synthetic."""
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            return self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        cur = self._con.execute(
            "SELECT ask FROM options_data WHERE date = ? AND expiration = ? AND type = ? AND strike = ? AND mark > 0 AND ask >= bid LIMIT 1",
            (date_str, exp_str, opt, strike),
        )
        row = cur.fetchone()
        return float(row["ask"]) if (row and row["ask"] is not None and row["ask"] > 0) else self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)

    def find_strike_at_delta(self, S_d: float, T_d: float, r_d: float, vix_d: float, target_delta: float, opt: str, ctx: PricingContext = None) -> tuple:
        """Return (strike, bid) for the DB row whose delta is closest to target_delta."""
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            return self._synth.find_strike_at_delta(S_d, T_d, r_d, vix_d, target_delta, opt, ctx)
        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        signed_target = -target_delta if opt == "put" else target_delta
        cur = self._con.execute(
            "SELECT strike, bid FROM options_data WHERE date = ? AND expiration = ? AND type = ? AND mark > 0 AND ask >= bid AND volume > 0 ORDER BY ABS(delta - ?) ASC LIMIT 1",
            (date_str, exp_str, opt, signed_target),
        )
        row = cur.fetchone()
        return (float(row["strike"]), float(row["bid"])) if (row and row["bid"] is not None and row["bid"] > 0) else self._synth.find_strike_at_delta(S_d, T_d, r_d, vix_d, target_delta, opt, ctx)

    def close(self) -> None:
        if hasattr(self, "_con"):
            self._con.close()

    def __del__(self) -> None:
        try: self.close()
        except: pass

    def _best_row(self, date_str: str, exp_str: str, opt: str, target_delta: float):
        cur = self._con.execute(
            "SELECT strike, mark, bid, ask, delta, implied_volatility, volume FROM options_data WHERE date = ? AND expiration = ? AND type = ? AND mark > 0 AND ask >= bid AND volume > 0 ORDER BY ABS(delta - ?) ASC LIMIT 1",
            (date_str, exp_str, opt, target_delta),
        )
        return cur.fetchone()

    def _strike_ask(self, date_str: str, exp_str: Optional[str], opt: str, strike: float):
        if not exp_str: return None
        cur = self._con.execute(
            "SELECT ask FROM options_data WHERE date = ? AND expiration = ? AND type = ? AND strike = ? AND mark > 0 AND ask >= bid LIMIT 1",
            (date_str, exp_str, opt, strike),
        )
        row = cur.fetchone()
        return float(row["ask"]) if row else None


# ── Factory ──────────────────────────────────────────────────────────────

def make_engine(params: dict):
    if params.get("mode", "synthetic") == "market":
        return MarketEngine(params)
    return SyntheticEngine(params)
