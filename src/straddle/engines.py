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


# ── American option pricing (Barone-Adesi & Whaley 1987) ────────────────────
#
# Used for PETR4 single-stock options (american_options=True).
# Calls with q=0 are never exercised early → remain European.
# Puts benefit from early exercise when deep ITM: the holder can exercise and
# earn interest on K at Brazil's CDI rate (12–15%), which is significant.
#
# The approximation expresses the American put as:
#   P_American = P_European + A₂ * (S/S*)^q₂   when S > S*
#   P_American = K - S                           when S ≤ S* (exercise now)
#
# where q₂ < 0 is a characteristic exponent and S* is the critical stock price
# below which immediate exercise is optimal.

def _baw_q2(r: float, sigma: float, T: float, q: float = 0.0) -> float:
    """Negative characteristic exponent for BAW American put approximation."""
    h = 1.0 - np.exp(-r * T)
    if h < 1e-10:
        return -1e9  # near-zero T: correction vanishes
    M = 2.0 * r / sigma**2
    N = 2.0 * (r - q) / sigma**2
    return (-(N - 1.0) - np.sqrt((N - 1.0)**2 + 4.0 * M / h)) / 2.0


def _baw_critical_put(
    K: float, T: float, r: float, sigma: float, q: float, q2: float,
) -> float:
    """Critical stock price S* for BAW American put via Brent's method.

    S* is the largest S where immediate exercise is optimal.
    Smooth-pasting + value-matching (BAW 1987 eq. 17) give:

        g(S) = (K − S) − p_eu(S) − (S/q₂)·[1 − e^{−qT}·N(−d₁(S))] = 0

    With q₂ < 0, the term (S/q₂)·[1−…] is always negative, so:
        g(0⁺) ≈ K·(1−e^{−rT}) > 0
        g(K)  ≈ −p_eu(K) − K/q₂·(1−N(−d₁(K))) < 0
    → exactly one root in (0, K). Brent's method is robust here (no
    gradient needed, bracket is always valid for r > 0).
    """
    disc_q = np.exp(-q * T)

    def g(S: float) -> float:
        if S <= 0:
            return K
        d1    = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
        nd1_neg = norm.cdf(-d1)
        p_eu  = bs_price(S, K, T, r, sigma, "put", q)
        # (S/q₂)·(1−…) < 0 because q₂ < 0
        correction = (1.0 - disc_q * nd1_neg) * S / q2
        return (K - S) - p_eu - correction

    # Bracket: g(ε) > 0, g(K-ε) < 0 for any r > 0, q2 < 0
    lo, hi = 1e-6, K - 1e-6
    try:
        from scipy.optimize import brentq as _brentq
        S_star = _brentq(g, lo, hi, xtol=1e-6, maxiter=200)
    except Exception:
        S_star = K * 0.5  # fallback: mid-point, very conservative
    return float(S_star)


def american_put_baw(
    S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0
) -> float:
    """Barone-Adesi & Whaley (1987) approximation for American put price.

    The American put is always worth at least max(K−S, 0) (intrinsic value).
    The BAW approximation adds a smooth early-exercise premium above the
    European price for S near and below S*.

    For high interest rates (Brazil CDI 12–15%) and short maturities the
    characteristic exponent |q₂| ≫ 1, making the BAW correction very sharp.
    In that regime the approximation degenerates gracefully to the tight lower
    bound max(p_eu, K−S), which is exact at the exercise boundary.
    """
    intrinsic = max(K - S, 0.0)
    p_eu = bs_price(S, K, T, r, sigma, "put", q)

    # Guard: no meaningful early exercise without time or positive rates
    if T < 1e-7 or r < 1e-8:
        return max(p_eu, intrinsic)

    q2 = _baw_q2(r, sigma, T, q)
    if q2 >= 0.0:
        return max(p_eu, intrinsic)  # no early exercise (shouldn't occur for r>0)

    S_star = _baw_critical_put(K, T, r, sigma, q, q2)

    if S <= S_star:
        return intrinsic  # immediate exercise dominates

    d1_star = (np.log(S_star / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    A2 = -(S_star / q2) * (1.0 - np.exp(-q * T) * norm.cdf(-d1_star))
    # Always enforce intrinsic lower bound — BAW can slightly understate deep ITM
    return float(max(p_eu + A2 * (S / S_star)**q2, intrinsic))


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
        # q=0.0 is always correct here: vix_close was extracted from market prices
        # using q=0 BS; using any other value would create a vol-level inconsistency.
        # Dividend effects are captured implicitly in the fitted put/call slopes.
        self.q = 0.0
        # American put pricing via BAW approximation (PETR4 single-stock options).
        # Calls with q=0 have no early-exercise benefit and remain European.
        self.american = params.get("american_options", False)

    def _get_sigma_t(self, vix_d: float, dte_rem: int) -> Tuple[float, float]:
        """Central helper for volatility scaling and time-to-expiry conversion."""
        sigma_d = (vix_d / 100.0) * self.vix_iv_mult
        T_d = max(dte_rem / 365.0, 1e-7)
        return sigma_d, T_d

    def _put_price(self, S: float, K: float, T: float, r: float, sigma: float) -> float:
        """Price a put using American (BAW) or European (BS) model per self.american."""
        if self.american:
            return american_put_baw(S, K, T, r, sigma, self.q)
        return bs_price(S, K, T, r, sigma, "put", self.q)

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
        put_mid = self._put_price(S, put_k, T, r, sigma_put)
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
        return self._put_price(S_d, put_k, T_d, r_d, sigma_put) + bs_price(
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
        if opt == "put":
            return self._put_price(S_d, strike, T_d, r_d, sigma_skewed)
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
        if opt == "put":
            mark = self._put_price(S_d, strike, T_d, r_d, sigma_skewed)
        else:
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
        return self._put_price(underlying_open, put_k, T_d, r_open, sigma_put) + bs_price(
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
        self._use_cdi = params.get("use_cdi_ivs", False)

        # Detect whether this DB has the `underlying` column (B3 DB) or not (SPY DB)
        cols = {
            row[1]
            for row in self._con.execute("PRAGMA table_info(options_data)").fetchall()
        }
        self._has_underlying_col = "underlying" in cols

        # Detect CDI columns for B3 RB3 database
        self._has_cdi_cols = False
        if self._use_cdi:
            if "implied_volatility_cdi" in cols and "delta_cdi" in cols:
                self._has_cdi_cols = True
                print(f"  MarketEngine: using CDI-based IVs/deltas (daily r)")
            else:
                print(f"  MarketEngine: WARNING — use_cdi_ivs=True but CDI columns not found in DB, falling back to flat-12%")
                self._use_cdi = False

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
        delta_col_name = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
        und_clause, und_val = self._und_filter()
        params = [date_str, exp_str, opt, strike]
        if und_val is not None:
            params.append(und_val)
        cur = self._con.execute(
            f"""SELECT {delta_col_name} AS delta FROM options_data
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
        result = self.get_leg_mark_with_source(
            strike, S_d, dte_rem, vix_d, r_d, opt, ctx=ctx, buy_or_sell=buy_or_sell
        )
        return result[0]

    def get_leg_mark_with_source(
        self,
        strike: float,
        S_d: float,
        dte_rem: int,
        vix_d: float,
        r_d: float,
        opt: str,
        ctx: PricingContext = None,
        buy_or_sell: str = "buy",
    ) -> tuple[float, str]:
        """Close-side mark for one leg, plus source tracking ('db' or 'synthetic').

        Returns (mark, source) where source indicates whether the price came
        from the DB or synthetic fallback. Merges the previously separate
        ``get_leg_mark`` + ``_source_for_strike`` into a single DB query.
        """
        if ctx is None or ctx.eval_date is None or ctx.eval_date < self._DB_START or ctx.expiration is None:
            synth = self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
            return synth, "synthetic"
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
            return float(row[col]), "db"
        synth = self._synth.get_leg_mark(strike, S_d, dte_rem, vix_d, r_d, opt, ctx)
        return synth, "synthetic"

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
        delta_col = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
        iv_where = "AND implied_volatility_cdi < 2.0" if (self._use_cdi and self._has_cdi_cols) else iv_clause
        params = [date_str, exp_str, opt]
        if und_val is not None:
            params.append(und_val)
        params.append(signed_target)
        cur = self._con.execute(
            f"""SELECT strike, bid FROM options_data
               WHERE date = ? AND expiration = ? AND type = ?
               {und_clause}
               AND mark > 0 AND ask >= bid AND volume > 0
               AND {delta_col} IS NOT NULL {iv_where}
               ORDER BY ABS({delta_col} - ?) ASC LIMIT 1""",
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
        When use_cdi_ivs=True, uses delta_cdi / implied_volatility_cdi columns.
        """
        und_clause, und_val = self._und_filter()
        iv_clause = "AND implied_volatility < 2.0" if self._has_underlying_col else ""
        delta_col = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
        iv_where = "AND implied_volatility_cdi < 2.0" if (self._use_cdi and self._has_cdi_cols) else iv_clause
        use_cdi = self._use_cdi and self._has_cdi_cols
        params = [date_str, exp_str, opt]
        if und_val is not None:
            params.append(und_val)
        params.append(target_delta)
        cur = self._con.execute(
            f"""
            SELECT strike, mark, bid, ask, {delta_col} AS delta,
                   CASE WHEN {use_cdi} THEN implied_volatility_cdi ELSE implied_volatility END AS implied_volatility,
                   volume
            FROM options_data
            WHERE date = ? AND expiration = ? AND type = ?
              {und_clause}
              AND mark > 0 AND ask >= bid AND volume > 0
              AND {delta_col} IS NOT NULL
              {iv_where}
            ORDER BY ABS({delta_col} - ?) ASC
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

    def _source_for_strike(
        self, date_str: str, exp_str: Optional[str], opt: str, strike: float
    ) -> str:
        """Return 'db' if a valid row exists in the DB for this strike, else 'synthetic'."""
        if date_str is None or exp_str is None:
            return "synthetic"
        und_clause, und_val = self._und_filter()
        params = [date_str, exp_str, opt, strike]
        if und_val is not None:
            params.append(und_val)
        cur = self._con.execute(
            f"""SELECT 1 FROM options_data
               WHERE date = ? AND expiration = ? AND type = ? AND strike = ?
                 {und_clause}
                 AND mark > 0 AND ask >= bid
               LIMIT 1""",
            params,
        )
        return "db" if cur.fetchone() else "synthetic"


# ── Factory ──────────────────────────────────────────────────────────────

def make_engine(params: dict):
    """Factory: return MarketEngine or SyntheticEngine based on PRICING mode."""
    if params.get("mode", "synthetic") == "market":
        return MarketEngine(params)
    return SyntheticEngine(params)
