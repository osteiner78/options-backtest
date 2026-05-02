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

def bs_price(S: float, K: float, T: float, r: float, sigma: float, opt: str,
             q: float = 0.0) -> float:
    """Merton (1973) European option price with continuous dividend yield q.

    q=0.0 (default) reduces to standard Black-Scholes. opt: 'call' or 'put'.
    """
    if T <= 1e-7:
        return max(S - K, 0.0) if opt == "call" else max(K - S, 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    disc_q = np.exp(-q * T)
    disc_r = np.exp(-r * T)
    if opt == "call":
        return float(S * disc_q * norm.cdf(d1) - K * disc_r * norm.cdf(d2))
    return float(K * disc_r * norm.cdf(-d2) - S * disc_q * norm.cdf(-d1))


def bs_delta(S: float, K: float, T: float, r: float, sigma: float, opt: str,
             q: float = 0.0) -> float:
    """Black-Scholes delta with continuous dividend yield q (put delta is negative)."""
    if T <= 1e-7:
        return (1.0 if S > K else 0.0) if opt == "call" else (-1.0 if S < K else 0.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    disc_q = np.exp(-q * T)
    if opt == "call":
        return float(disc_q * norm.cdf(d1))
    return float(disc_q * (norm.cdf(d1) - 1.0))


def strike_from_delta(
    S: float,
    T: float,
    r: float,
    sigma: float,
    target_delta: float,
    opt: str,
    increment: float = 1.0,
    q: float = 0.0,
) -> float:
    """Analytically compute the strike that achieves target_delta, rounded to increment.

    With continuous dividend yield q the delta is e^(-qT)*N(d1) for calls and
    e^(-qT)*(N(d1)-1) for puts, so target_delta is adjusted before inversion.
    """
    adj = target_delta * np.exp(q * T)  # reverse the e^(-qT) discount on delta
    d1 = norm.ppf(adj) if opt == "call" else norm.ppf(1.0 - adj)
    K = S * np.exp(-d1 * sigma * np.sqrt(T) + (r - q + 0.5 * sigma**2) * T)
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
        self.r_default = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT)
        self.gap_mult = params.get("gap_vix_multiplier", 3.0)
        self.vix_iv_mult = params.get("vix_to_iv_multiplier", 1.0)
        self.o_adj = params.get("open_fill_adj", -0.05)
        self.c_adj = params.get("close_fill_adj", 0.05)
        self.q = params.get("dividend_yield", 0.0)  # continuous dividend yield

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
        sigma, _ = self._get_sigma_t(vix, int(T * 365))
        target_delta = (ctx.target_delta if ctx else None) or self.delta
        sigma_put = apply_skew(
            sigma, target_delta, "put", self.put_slope, self.call_slope
        )
        sigma_call = apply_skew(
            sigma, target_delta, "call", self.put_slope, self.call_slope
        )
        put_k = strike_from_delta(S, T, r, sigma_put, target_delta, "put", q=self.q)
        call_k = strike_from_delta(S, T, r, sigma_call, target_delta, "call", q=self.q)
        put_mid = bs_price(S, put_k, T, r, sigma_put, "put", self.q)
        call_mid = bs_price(S, call_k, T, r, sigma_call, "call", self.q)
        return put_k, call_k, put_mid, call_mid, False  # used_market_data=False

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
        """Combined per-share strangle mid at EOD during the hold period.

        Args:
            put_k / call_k: strikes fixed at entry
            S_d:            SPY close on eval_date
            dte_rem:        Calendar days remaining to expiry
            vix_d:          VIX close on eval_date
            r_d:            Risk-free rate on eval_date
            ctx:            Optional PricingContext

        Returns:
            mid_d -- put_mid + call_mid, per share (no fill adj, no commission)
        """
        sigma_d, T_d = self._get_sigma_t(vix_d, dte_rem)

        # Estimate current deltas using ATM vol to pick the right skew zone
        d_put_est = bs_delta(S_d, put_k, T_d, r_d, sigma_d, "put", self.q)
        d_call_est = bs_delta(S_d, call_k, T_d, r_d, sigma_d, "call", self.q)

        sigma_put = apply_skew(
            sigma_d, d_put_est, "put", self.put_slope, self.call_slope
        )
        sigma_call = apply_skew(
            sigma_d, d_call_est, "call", self.put_slope, self.call_slope
        )
        return bs_price(S_d, put_k, T_d, r_d, sigma_put, "put", self.q) + bs_price(
            S_d, call_k, T_d, r_d, sigma_call, "call", self.q
        )

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
        """Per-leg delta on eval_date (used by defensive leg roll trigger check)."""
        sigma_d, T_d = self._get_sigma_t(vix_d, dte_rem)
        # Estimate delta for skew lookup
        d_est = bs_delta(S_d, strike, T_d, r_d, sigma_d, opt, self.q)
        sigma_skewed = apply_skew(
            sigma_d, d_est, opt, self.put_slope, self.call_slope
        )
        return bs_delta(S_d, strike, T_d, r_d, sigma_skewed, opt, self.q)

    def get_leg_mark(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        ctx: PricingContext = None,
        buy_or_sell: str = "buy",
    ) -> float:
        """Per-share BS mid for a single leg (no fill adj, no commission).

        ``buy_or_sell`` is accepted for API parity with MarketEngine but ignored
        here — synthetic mode returns the raw BS mid and the caller applies the
        fill adjustment in the correct direction.
        """
        sigma_d, T_d = self._get_sigma_t(vix_d, dte_rem)
        d_est = bs_delta(S_d, strike, T_d, r_d, sigma_d, opt, self.q)
        sigma_skewed = apply_skew(
            sigma_d, d_est, opt, self.put_slope, self.call_slope
        )
        return bs_price(S_d, strike, T_d, r_d, sigma_skewed, opt, self.q)

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
        # Pick right skew based on target_delta zone
        sigma_skewed = apply_skew(
            sigma_d, target_delta, opt, self.put_slope, self.call_slope
        )
        strike = strike_from_delta(S_d, T_d, r_d, sigma_skewed, target_delta, opt, q=self.q)
        mark = bs_price(S_d, strike, T_d, r_d, sigma_skewed, opt, self.q)
        return strike, mark

    def get_gap_open_mark(
        self,
        underlying_open: float,
        vix_prev_raw: float,
        gap_pct: float,
        put_k: float,
        call_k: float,
        T_d: float,
        r_open: float,
        ctx: PricingContext = None,
    ) -> float:
        """Per-share strangle mid priced at the open on a gap day.

        Always Black-Scholes -- the DB is EOD-only, so this method is
        identical in synthetic and market modes.

        VIX is scaled from the prior close to approximate opening vol::

            vix_open = vix_prev * (1 + gap_vix_multiplier * |gap_pct|)

        Args:
            underlying_open: Underlying open price on the gap day
            vix_prev_raw:    Prior day VIX sigma (vix_close / 100.0)
            gap_pct:         |underlying_open - prev_close| / prev_close
            put_k / call_k:  strikes
            T_d:             Time to expiry in years
            r_open:          Risk-free rate at the open
            ctx:             Optional PricingContext
        """
        vix_open_sigma = (
            vix_prev_raw * (1.0 + self.gap_mult * gap_pct)
        ) * self.vix_iv_mult

        # Estimate actual current deltas at the gap-open price, mirroring
        # get_daily_mark — using the static entry delta (0.16) is wrong when
        # a leg has moved significantly (e.g. from 0.16Δ to 0.45Δ on a crash).
        d_put_est = bs_delta(underlying_open, put_k, T_d, r_open, vix_open_sigma, "put", self.q)
        d_call_est = bs_delta(underlying_open, call_k, T_d, r_open, vix_open_sigma, "call", self.q)

        sigma_put = apply_skew(
            vix_open_sigma, d_put_est, "put", self.put_slope, self.call_slope
        )
        sigma_call = apply_skew(
            vix_open_sigma, d_call_est, "call", self.put_slope, self.call_slope
        )
        return bs_price(underlying_open, put_k, T_d, r_open, sigma_put, "put", self.q) + bs_price(
            underlying_open, call_k, T_d, r_open, sigma_call, "call", self.q
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
        from pathlib import Path

        # Accept options_db_path (new) or db_path (legacy) for backward compat
        db_path_raw = params.get(
            "options_db_path",
            params.get("db_path", "data/Spy Options Database.db"),
        )
        # Resolve relative to project root even when run from apps/
        db_path = Path(db_path_raw)
        if not db_path.is_absolute():
            root = Path(__file__).resolve().parent.parent.parent
            db_path = root / db_path_raw

        db_path_str = str(db_path)
        market = params.get("market", "spy")

        # Validate date range early to avoid silent synthetic fallback
        validate_market_mode_dates(
            params["start_date"], params["end_date"], db_path_str, market=market
        )

        self._synth = SyntheticEngine(params)
        self._con = _sqlite3.connect(db_path_str, check_same_thread=False)
        self._con.row_factory = _sqlite3.Row
        self.delta = params["target_delta"]
        self._market = market

        # Detect whether this DB has the `underlying` column (B3 DB) or not (SPY DB)
        cols = {
            row[1]
            for row in self._con.execute("PRAGMA table_info(options_data)").fetchall()
        }
        self._has_underlying_col = "underlying" in cols

        print(
            f"MarketEngine: connected to {db_path_str} "
            f"(market={market}, underlying_filter={self._has_underlying_col})"
        )

    def apply_fill_adj(self, mid_ps: float, side: str) -> float:
        """Market mode: fill adjustment is already baked into bid/ask selection.
        Returns mid_ps as is. (Synthetic fallback still uses its own adj).
        """
        return mid_ps

    # ── public interface ────────────────────────────────────────────────

    def get_entry_marks(
        self,
        S: float,
        T: float,
        r: float,
        vix: float,
        ctx: PricingContext = None,
    ) -> tuple:
        """Nearest-delta strike and mark from DB at entry."""
        if ctx is None or ctx.eval_date is None or ctx.expiration is None or ctx.eval_date < self._DB_START:
            return self._synth.get_entry_marks(S, T, r, vix, ctx)  # used_market_data=False

        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")

        target_delta = ctx.target_delta or self.delta
        put_row = self._best_row(date_str, exp_str, "put", -target_delta)
        call_row = self._best_row(date_str, exp_str, "call", +target_delta)

        if put_row is None or call_row is None:
            # No valid DB row -- fall back to synthetic
            return self._synth.get_entry_marks(S, T, r, vix, ctx)  # used_market_data=False

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
        ctx: PricingContext = None,
    ) -> float:
        """Sum of put and call ask prices from DB on eval_date.

        Ask = cost to buy back each leg (most conservative close fill).
        Falls back per-leg to synthetic BS if a strike is missing.
        """
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START:
            return self._synth.get_daily_mark(put_k, call_k, S_d, dte_rem, vix_d, r_d, ctx)

        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d") if ctx.expiration else None

        put_mark = self._strike_ask(date_str, exp_str, "put", put_k)
        call_mark = self._strike_ask(date_str, exp_str, "call", call_k)

        # Per-leg synthetic fallback
        if put_mark is None:
            put_mark = self._synth.get_leg_mark(put_k, S_d, dte_rem, vix_d, r_d, "put", ctx)

        if call_mark is None:
            call_mark = self._synth.get_leg_mark(call_k, S_d, dte_rem, vix_d, r_d, "call", ctx)

        return float(put_mark) + float(call_mark)

    def get_gap_open_mark(
        self,
        underlying_open: float,
        vix_prev_raw: float,
        gap_pct: float,
        put_k: float,
        call_k: float,
        T_d: float,
        r_open: float,
        ctx: PricingContext = None,
    ) -> float:
        """Always synthetic -- DB is EOD-only."""
        return self._synth.get_gap_open_mark(
            underlying_open, vix_prev_raw, gap_pct, put_k, call_k, T_d, r_open, ctx
        )

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
        """Per-leg delta from DB on eval_date; falls back to synthetic BS."""
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            return self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        und_clause, und_val = self._und_filter()
        params = [date_str, exp_str, opt, strike]
        if und_val is not None:
            params.append(und_val)
        cur = self._con.execute(
            f"""SELECT delta FROM options_data
               WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
               {und_clause} AND mark > 0 LIMIT 1""",
            params,
        )
        row = cur.fetchone()
        if row and row["delta"] is not None:
            return float(row["delta"])
        return self._synth.get_daily_delta(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)

    def get_leg_mark(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        ctx: PricingContext = None,
        buy_or_sell: str = "buy",
    ) -> float:
        """Close-side mark for one leg from the DB.

        ``buy_or_sell`` selects which side of the book to quote:
          * "buy"  → ask  (cost to buy the leg — use when buying back a short or opening a long)
          * "sell" → bid  (credit received when selling — use when selling a long or opening a short)

        Falls back to the synthetic BS mid if no DB row is found.
        """
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            return self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        col = "bid" if buy_or_sell == "sell" else "ask"
        und_clause, und_val = self._und_filter()
        params = [date_str, exp_str, opt, strike]
        if und_val is not None:
            params.append(und_val)
        cur = self._con.execute(
            f"""SELECT {col} FROM options_data
               WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
               {und_clause} AND mark > 0 AND ask >= bid LIMIT 1""",
            params,
        )
        row = cur.fetchone()
        if row and row[col] is not None and row[col] > 0:
            return float(row[col])
        return self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)

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
        """Return (strike, bid) for the DB row whose delta is closest to target_delta.
        Uses bid for sell-to-open. Falls back to synthetic if no DB row.
        """
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            return self._synth.find_strike_at_delta(
                S_d, T_d, r_d, vix_d, target_delta, opt, ctx
            )
        date_str = ctx.eval_date.strftime("%Y-%m-%d")
        exp_str = ctx.expiration.strftime("%Y-%m-%d")
        # puts: delta is negative in DB; calls: positive
        signed_target = -target_delta if opt == "put" else target_delta
        und_clause, und_val = self._und_filter()
        iv_clause = "AND implied_volatility < 2.0" if self._has_underlying_col else ""
        params = [date_str, exp_str, opt]
        if und_val is not None:
            params.append(und_val)
        params.append(signed_target)
        cur = self._con.execute(
            f"""SELECT strike, bid FROM options_data
               WHERE date = ? AND expiration = ? AND type = ?
               {und_clause}
               AND mark > 0 AND ask >= bid AND volume > 0
               AND delta IS NOT NULL {iv_clause}
               ORDER BY ABS(delta - ?) ASC LIMIT 1""",
            params,
        )
        row = cur.fetchone()
        if row and row["bid"] is not None and row["bid"] > 0:
            return float(row["strike"]), float(row["bid"])
        return self._synth.find_strike_at_delta(S_d, T_d, r_d, vix_d, target_delta, opt, ctx)

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

    def _und_filter(self) -> str:
        """Return the SQL fragment and bind value for the underlying filter.

        Returns ("AND underlying = ?", self._market) when the DB has the
        underlying column (B3 DB), or ("", None) for the SPY DB.
        """
        if self._has_underlying_col:
            return "AND underlying = ?", self._market
        return "", None

    def _best_row(self, date_str: str, exp_str: str, opt: str, target_delta: float):
        """Return the options_data row whose delta is closest to target_delta.

        Excludes rows where mark <= 0, ask < bid, volume == 0, or delta IS NULL.
        For B3: also filters implied_volatility < 2.0 to remove stale deep-OTM quotes.
        """
        und_clause, und_val = self._und_filter()
        iv_clause = "AND implied_volatility < 2.0" if self._has_underlying_col else ""
        params = [date_str, exp_str, opt]
        if und_val is not None:
            params.append(und_val)
        params.append(target_delta)
        cur = self._con.execute(
            f"""
            SELECT strike, mark, bid, ask, delta, implied_volatility, volume
            FROM options_data
            WHERE date = ? AND expiration = ? AND type = ?
              {und_clause}
              AND mark > 0 AND ask >= bid AND volume > 0
              AND delta IS NOT NULL
              {iv_clause}
            ORDER BY ABS(delta - ?) ASC
            LIMIT 1
            """,
            params,
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
        und_clause, und_val = self._und_filter()
        params = [date_str, exp_str, opt, strike]
        if und_val is not None:
            params.append(und_val)
        cur = self._con.execute(
            f"""
            SELECT ask FROM options_data
            WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
              {und_clause}
              AND mark > 0 AND ask >= bid
            LIMIT 1
            """,
            params,
        )
        row = cur.fetchone()
        return float(row["ask"]) if row else None


# ── Factory ──────────────────────────────────────────────────────────────

def make_engine(params: dict):
    """Factory: return MarketEngine or SyntheticEngine based on PRICING mode."""
    if params.get("mode", "synthetic") == "market":
        return MarketEngine(params)
    return SyntheticEngine(params)
