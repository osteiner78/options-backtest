"""Pricing engines: SyntheticEngine, MarketEngine, and make_engine factory.

Two engines share the same interface consumed by ``run_backtest``:

- **SyntheticEngine** — Black-Scholes pricing using VIX as ATM vol and a
  parametric equity-smirk skew.
- **MarketEngine** — Real bid/ask/mark from the SQLite options database
  (2008–2025), with per-leg synthetic fallback on missing data.

Gap-open pricing always uses SyntheticEngine in both modes — the DB is
EOD-only, so intraday stop modelling is always synthetic.
"""

from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm

from straddle.data import validate_market_mode_dates


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
    """Return a skew-adjusted implied vol for a single leg (equity smirk model).

    SPY options exhibit a pronounced reverse skew ("smirk"): OTM puts are bid
    up significantly above ATM vol due to tail-risk demand, while OTM calls
    trade near or slightly below ATM vol. The previous symmetric slope applied
    the same multiplier to both legs — incorrect because |put_delta| == |call_delta|
    at 0.16, making the adjustment identical. This function uses separate slopes:

        put_slope  = 0.30  →  16Δ put : vol * (1 + 0.30 * 0.34) ≈ vol * 1.10
        call_slope = 0.10  →  16Δ call: vol * (1 - 0.10 * 0.34) ≈ vol * 0.97

    Args:
        sigma_atm:   ATM vol (VIX / 100 at entry, or daily VIX mark).
        delta:       Absolute delta of the leg (0.0–1.0).
        opt:         "put" or "call" — selects which slope to apply.
        put_slope:   Skew slope for put legs (default 0.30).
        call_slope:  Skew slope for call legs (default 0.10).
    Returns:
        Skew-adjusted implied vol.
    """
    distance_from_atm = 0.50 - abs(delta)
    if opt == "put":
        return sigma_atm * (1.0 + put_slope * distance_from_atm)
    else:
        return sigma_atm * (1.0 - call_slope * distance_from_atm)


# ── SyntheticEngine ──────────────────────────────────────────────────────

class SyntheticEngine:
    """Black-Scholes pricing engine for the short-strangle backtest.

    Encapsulates all synthetic pricing so run_backtest is agnostic to the
    pricing source. Three public methods mirror the three call-sites in the
    backtest loop::

        get_entry_marks   -- strikes and per-share mids at trade open
        get_daily_mark    -- EOD strangle mid during the hold period
        get_gap_open_mark -- strangle mid at the open on gap days
                             (always BS; the DB is EOD-only)

    The engine is constructed once from PARAMS and is stateless thereafter.
    MarketEngine shares the same interface so run_backtest never needs to
    know which engine is active.
    """

    uses_real_fills = False  # synthetic: fill_adj applied by run_backtest

    def __init__(self, params: dict) -> None:
        self.delta = params["target_delta"]
        self.put_slope = params.get("put_slope", 0.30)
        self.call_slope = params.get("call_slope", 0.10)
        self.r_default = params.get("risk_free_rate", 0.045)
        self.gap_mult = params.get("gap_vix_multiplier", 3.0)
        self.vix_iv_mult = params.get("vix_to_iv_multiplier", 1.0)

    def get_entry_marks(
        self, S: float, T: float, r: float, vix: float, **_kwargs
    ) -> tuple:
        """Compute 16-delta strikes and per-share mids at trade entry.

        Args:
            S:   SPY close on entry date
            T:   Time to expiry in years (entry_dte / 365)
            r:   Risk-free rate for this date
            vix: VIX close on entry date

        Returns:
            (put_strike, call_strike, put_mid_ps, call_mid_ps, used_market_data)
            Per-share mids before fill adjustment; caller applies o_adj.
        """
        sigma = (vix / 100.0) * self.vix_iv_mult
        sigma_put = apply_skew(
            sigma, self.delta, "put", self.put_slope, self.call_slope
        )
        sigma_call = apply_skew(
            sigma, self.delta, "call", self.put_slope, self.call_slope
        )
        put_k = strike_from_delta(S, T, r, sigma_put, self.delta, "put")
        call_k = strike_from_delta(S, T, r, sigma_call, self.delta, "call")
        put_mid = bs_price(S, put_k, T, r, sigma_put, "put")
        call_mid = bs_price(S, call_k, T, r, sigma_call, "call")
        return put_k, call_k, put_mid, call_mid, False  # used_market_data=False

    def get_daily_mark(
        self,
        put_k: float,
        call_k: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        **_kwargs,
    ) -> float:
        """Combined per-share strangle mid at EOD during the hold period.

        Args:
            put_k / call_k: strikes fixed at entry
            S_d:            SPY close on eval_date
            dte_rem:        Calendar days remaining to expiry
            vix_d:          VIX close on eval_date
            r_d:            Risk-free rate on eval_date

        Returns:
            mid_d -- put_mid + call_mid, per share (no fill adj, no commission)
        """
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        T_d = max(dte_rem / 365.0, 1e-7)
        sigma_put = apply_skew(
            sigma_d, self.delta, "put", self.put_slope, self.call_slope
        )
        sigma_call = apply_skew(
            sigma_d, self.delta, "call", self.put_slope, self.call_slope
        )
        return bs_price(S_d, put_k, T_d, r_d, sigma_put, "put") + bs_price(
            S_d, call_k, T_d, r_d, sigma_call, "call"
        )

    def get_daily_delta(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        **_kwargs,
    ) -> float:
        """Per-leg delta on eval_date (used by defensive leg roll trigger check)."""
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        T_d = max(dte_rem / 365.0, 1e-7)
        sigma_skewed = apply_skew(
            sigma_d, self.delta, opt, self.put_slope, self.call_slope
        )
        return bs_delta(S_d, strike, T_d, r_d, sigma_skewed, opt)

    def get_leg_mark(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        **_kwargs,
    ) -> float:
        """Per-share BS mid for a single leg (no fill adj, no commission)."""
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        T_d = max(dte_rem / 365.0, 1e-7)
        sigma_skewed = apply_skew(
            sigma_d, self.delta, opt, self.put_slope, self.call_slope
        )
        return bs_price(S_d, strike, T_d, r_d, sigma_skewed, opt)

    def find_strike_at_delta(
        self,
        S_d: float,
        T_d: float,
        r_d: float,
        vix_d: float,
        target_delta: float,
        opt: str,
        **_kwargs,
    ) -> tuple:
        """Return (strike, per-share mid) for a new leg at target_delta."""
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        sigma_skewed = apply_skew(
            sigma_d, self.delta, opt, self.put_slope, self.call_slope
        )
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
    ) -> float:
        """Per-share strangle mid priced at the open on a gap day.

        Always Black-Scholes -- the DB is EOD-only, so this method is
        identical in synthetic and market modes.

        VIX is scaled from the prior close to approximate opening vol::

            vix_open = vix_prev * (1 + gap_vix_multiplier * |gap_pct|)

        Args:
            spy_open:     SPY open price on the gap day
            vix_prev_raw: Prior day VIX sigma (vix_close / 100.0)
            gap_pct:      |spy_open - spy_prev_close| / spy_prev_close
            put_k / call_k: strikes
            T_d:          Time to expiry in years
            r_open:       Risk-free rate at the open
        """
        vix_open_sigma = (
            vix_prev_raw * (1.0 + self.gap_mult * gap_pct)
        ) * self.vix_iv_mult
        sigma_put = apply_skew(
            vix_open_sigma, self.delta, "put", self.put_slope, self.call_slope
        )
        sigma_call = apply_skew(
            vix_open_sigma, self.delta, "call", self.put_slope, self.call_slope
        )
        return bs_price(spy_open, put_k, T_d, r_open, sigma_put, "put") + bs_price(
            spy_open, call_k, T_d, r_open, sigma_call, "call"
        )


# ── MarketEngine ─────────────────────────────────────────────────────────

class MarketEngine:
    """Real-data pricing engine backed by the SQLite options database.

    Strike selection: row with delta closest to +-target_delta for each leg.
    Only rows with mark > 0, ask >= bid, and volume > 0 are considered.

    Falls back to SyntheticEngine when:
      - The date predates the DB (< 2008-01-02)
      - No valid row exists for the requested date / expiration / strike
      - The DB file cannot be opened

    get_gap_open_mark always delegates to SyntheticEngine -- gap pricing
    requires intraday vol estimates that the EOD-only DB cannot provide.

    Note:
        The caller is responsible for calling ``close()`` when done,
        especially if running multiple backtests in a loop.
    """

    _DB_START = pd.Timestamp("2008-01-02")
    uses_real_fills = True  # market: bid at entry, ask at close; fill_adj bypassed

    def __init__(self, params: dict) -> None:
        import sqlite3 as _sqlite3

        # Validate date range early to avoid silent synthetic fallback
        validate_market_mode_dates(params["start_date"], params["end_date"])

        self._synth = SyntheticEngine(params)
        db_path = params.get("db_path", "data/Spy Options Database.db")
        self._con = _sqlite3.connect(db_path, check_same_thread=False)
        self._con.row_factory = _sqlite3.Row
        self.delta = params["target_delta"]
        print(f"MarketEngine: connected to {db_path}")

    # ── public interface ────────────────────────────────────────────────

    def get_entry_marks(
        self,
        S: float,
        T: float,
        r: float,
        vix: float,
        entry_date: pd.Timestamp = None,
        expiration: pd.Timestamp = None,
    ) -> tuple:
        """Nearest-delta strike and mark from DB at entry.

        The extra keyword arguments (entry_date, expiration) are used by
        MarketEngine; SyntheticEngine ignores them via **kwargs compatibility
        handled at the call site.
        """
        if entry_date is None or expiration is None or entry_date < self._DB_START:
            return self._synth.get_entry_marks(S, T, r, vix)  # used_market_data=False

        date_str = entry_date.strftime("%Y-%m-%d")
        exp_str = expiration.strftime("%Y-%m-%d")

        put_row = self._best_row(date_str, exp_str, "put", -self.delta)
        call_row = self._best_row(date_str, exp_str, "call", +self.delta)

        if put_row is None or call_row is None:
            # No valid DB row -- fall back to synthetic
            return self._synth.get_entry_marks(S, T, r, vix)  # used_market_data=False

        return (
            float(put_row["strike"]),
            float(call_row["strike"]),
            float(put_row["bid"]),  # sell at bid (most conservative)
            float(call_row["bid"]),  # sell at bid (most conservative)
            True,  # used_market_data=True
        )

    def get_daily_mark(
        self,
        put_k: float,
        call_k: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        eval_date: pd.Timestamp = None,
        expiration: pd.Timestamp = None,
    ) -> float:
        """Sum of put and call ask prices from DB on eval_date.

        Ask = cost to buy back each leg (most conservative close fill).
        Falls back per-leg to synthetic BS if a strike is missing.
        """
        if eval_date is None or eval_date < self._DB_START:
            return self._synth.get_daily_mark(put_k, call_k, S_d, dte_rem, vix_d, r_d)

        date_str = eval_date.strftime("%Y-%m-%d")
        exp_str = expiration.strftime("%Y-%m-%d") if expiration else None

        put_mark = self._strike_ask(date_str, exp_str, "put", put_k)
        call_mark = self._strike_ask(date_str, exp_str, "call", call_k)

        # Per-leg synthetic fallback
        if put_mark is None:
            sigma_d = vix_d / 100.0
            T_d = max(dte_rem / 365.0, 1e-7)
            sigma_put = apply_skew(
                sigma_d,
                self.delta,
                "put",
                self._synth.put_slope,
                self._synth.call_slope,
            )
            put_mark = bs_price(S_d, put_k, T_d, r_d, sigma_put, "put")

        if call_mark is None:
            sigma_d = vix_d / 100.0 
            T_d = max(dte_rem / 365.0, 1e-7)
            sigma_call = apply_skew(
                sigma_d,
                self.delta,
                "call",
                self._synth.put_slope,
                self._synth.call_slope,
            )
            call_mark = bs_price(S_d, call_k, T_d, r_d, sigma_call, "call")

        return float(put_mark) + float(call_mark)

    def get_gap_open_mark(
        self,
        spy_open: float,
        vix_prev_raw: float,
        gap_pct: float,
        put_k: float,
        call_k: float,
        T_d: float,
        r_open: float,
    ) -> float:
        """Always synthetic -- DB is EOD-only."""
        return self._synth.get_gap_open_mark(
            spy_open, vix_prev_raw, gap_pct, put_k, call_k, T_d, r_open
        )

    def get_daily_delta(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        eval_date=None,
        expiration=None,
        **_kwargs,
    ) -> float:
        """Per-leg delta from DB on eval_date; falls back to synthetic BS."""
        if eval_date is None or eval_date < self._DB_START or expiration is None:
            return self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt)
        date_str = eval_date.strftime("%Y-%m-%d")
        exp_str = expiration.strftime("%Y-%m-%d")
        cur = self._con.execute(
            """SELECT delta FROM options_data
               WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
               AND mark > 0 LIMIT 1""",
            (date_str, exp_str, opt, strike),
        )
        row = cur.fetchone()
        if row and row["delta"] is not None:
            return float(row["delta"])
        return self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt)

    def get_leg_mark(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        eval_date=None,
        expiration=None,
        **_kwargs,
    ) -> float:
        """Ask price for one leg from DB (buy-to-close fill); falls back to synthetic."""
        if eval_date is None or eval_date < self._DB_START or expiration is None:
            return self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt)
        date_str = eval_date.strftime("%Y-%m-%d")
        exp_str = expiration.strftime("%Y-%m-%d")
        cur = self._con.execute(
            """SELECT ask FROM options_data
               WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
               AND mark > 0 AND ask >= bid LIMIT 1""",
            (date_str, exp_str, opt, strike),
        )
        row = cur.fetchone()
        if row and row["ask"] is not None and row["ask"] > 0:
            return float(row["ask"])
        return self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt)

    def find_strike_at_delta(
        self,
        S_d: float,
        T_d: float,
        r_d: float,
        vix_d: float,
        target_delta: float,
        opt: str,
        eval_date=None,
        expiration=None,
        **_kwargs,
    ) -> tuple:
        """Return (strike, bid) for the DB row whose delta is closest to target_delta.
        Uses bid for sell-to-open. Falls back to synthetic if no DB row.
        """
        if eval_date is None or eval_date < self._DB_START or expiration is None:
            return self._synth.find_strike_at_delta(
                S_d, T_d, r_d, vix_d, target_delta, opt
            )
        date_str = eval_date.strftime("%Y-%m-%d")
        exp_str = expiration.strftime("%Y-%m-%d")
        # puts: delta is negative in DB; calls: positive
        signed_target = -target_delta if opt == "put" else target_delta
        cur = self._con.execute(
            """SELECT strike, bid FROM options_data
               WHERE date = ? AND expiration = ? AND type = ?
               AND mark > 0 AND ask >= bid AND volume > 0
               ORDER BY ABS(delta - ?) ASC LIMIT 1""",
            (date_str, exp_str, opt, signed_target),
        )
        row = cur.fetchone()
        if row and row["bid"] is not None and row["bid"] > 0:
            return float(row["strike"]), float(row["bid"])
        return self._synth.find_strike_at_delta(S_d, T_d, r_d, vix_d, target_delta, opt)

    def close(self) -> None:
        """Close the DB connection. Call when done if running in a loop."""
        if hasattr(self, "_con"):
            self._con.close()

    def __del__(self) -> None:
        """Safety measure: ensure connection is closed on garbage collection."""
        try:
            self.close()
        except:
            pass

    # ── private helpers ─────────────────────────────────────────────────

    def _best_row(self, date_str: str, exp_str: str, opt: str, target_delta: float):
        """Return the options_data row whose delta is closest to target_delta.

        Excludes rows where mark <= 0, ask < bid, or volume == 0.
        """
        cur = self._con.execute(
            """
            SELECT strike, mark, bid, ask, delta, implied_volatility, volume
            FROM options_data
            WHERE date = ? AND expiration = ? AND type = ?
              AND mark > 0 AND ask >= bid AND volume > 0
            ORDER BY ABS(delta - ?) ASC
            LIMIT 1
            """,
            (date_str, exp_str, opt, target_delta),
        )
        return cur.fetchone()

    def _strike_ask(self, date_str: str, exp_str: Optional[str], opt: str, strike: float):
        """Return the ask for an exact (date, expiration, strike) row, or None.

        Ask = what you pay to buy back a leg at close (most conservative fill).
        No cross-expiration fallback: a price from a different expiration is for
        a different option and could silently corrupt daily P&L marks.
        Callers handle None by falling back to synthetic BS for that leg.
        """
        if not exp_str:
            return None
        cur = self._con.execute(
            """
            SELECT ask FROM options_data
            WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
              AND mark > 0 AND ask >= bid
            LIMIT 1
            """,
            (date_str, exp_str, opt, strike),
        )
        row = cur.fetchone()
        return float(row["ask"]) if row else None


# ── Factory ──────────────────────────────────────────────────────────────

def make_engine(params: dict):
    """Factory: return MarketEngine or SyntheticEngine based on PRICING mode."""
    if params.get("mode", "synthetic") == "market":
        return MarketEngine(params)
    return SyntheticEngine(params)
