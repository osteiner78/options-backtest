"""PARAMS schema, defaults, and validation.

All tunable knobs for the SPY short strangle backtest are defined here.
The four sub-dicts (BACKTEST, STRATEGY, PRICING, OVERSHOOT) provide a
human-facing interface; the merged PARAMS dict is the machine interface
used by all downstream functions.
"""

from typing import TypedDict


# ── TypedDict for type hints ─────────────────────────────────────────────

class BacktestParams(TypedDict, total=False):
    start_date: str
    end_date: str
    initial_balance: float
    commission_per_leg: float
    vix_low: float
    vix_high: float


class StrategyParams(TypedDict, total=False):
    strategy_mode: str          # "short_strangle" | "iron_condor"
    wing_delta: float           # long-leg delta for iron condor wings (e.g. 0.05)
    target_delta: float
    dte_min: int
    dte_max: int
    profit_target_pct: float
    stop_loss_pct: float
    open_fill_adj: float
    close_fill_adj: float
    use_price_stop: bool
    manage_at_dte: int
    roll_for_credit: bool
    max_rolls: int
    roll_dte_max: int
    single_position: bool
    vix_entry_filter_enabled: bool
    vix_entry_max: float
    defensive_leg_roll_enabled: bool
    defensive_trigger_delta: float
    leg_roll_target_delta: float
    max_leg_rolls_per_trade: int


class PricingParams(TypedDict, total=False):
    mode: str
    db_path: str
    risk_free_rate: float
    put_slope: float
    call_slope: float
    vix_to_iv_multiplier: float


class OvershootParams(TypedDict, total=False):
    overshoot_orderly: float
    overshoot_normal: float
    overshoot_violent: float
    range_threshold_orderly: float
    range_threshold_violent: float
    gap_vix_multiplier: float


class PortfolioParams(TypedDict, total=False):
    max_bpr_allocation: float
    cash_yield_annual: float
    entry_cooldown_days: int
    cash_investment_mode: str   # "risk_free" | "spy" | "blend"
    spy_allocation_pct: float   # SPY fraction for "blend" mode


# ── Constants ───────────────────────────────────────────────────────────

RISK_FREE_RATE_DEFAULT = 0.045


# ── Backtest infrastructure ─────────────────────────────────────────────

BACKTEST: BacktestParams = {
    "start_date": "2021-01-01",
    "end_date": "2025-11-30",
    "initial_balance": 50_000,
    "commission_per_leg": 1.00,  # $1/contract/leg → $2 open + $2 close = $4/round-trip
    "vix_low": 15,  # regime reporting thresholds (not used in backtest logic)
    "vix_high": 25,
}

# ── Strategy rules ───────────────────────────────────────────────────────

STRATEGY: StrategyParams = {
    # Strategy variant: "short_strangle" sells a naked put + call.
    # "iron_condor" additionally buys long wings at wing_delta to cap tail risk,
    # turning the trade into a defined-risk spread.
    "strategy_mode": "short_strangle",
    "wing_delta": 0.05,  # long-leg delta for iron condor wings (5Δ default)
    "target_delta": 0.16,  # sell 16Δ put + 16Δ call
    "dte_min": 30,  # acceptable DTE window for expiry selection
    "dte_max": 45,
    "profit_target_pct": 0.50,  # close when P&L >= 50% of net premium
    "stop_loss_pct": 2.00,  # close when P&L <= -200% of net premium
    # Execution cost assumptions — applied to mid in both pricing modes.
    # Set to 0 in market mode if you prefer to use raw DB bid/ask directly.
    "open_fill_adj": -0.05,  # receive mid × (1 − 0.05) = 95% of mid
    "close_fill_adj": +0.05,  # pay    mid × (1 + 0.05) = 105% of mid
    # 21-DTE roll management
    "use_price_stop": False,  # False = no price stop (canonical tastytrade); True = legacy stop_loss_pct + overshoot
    "manage_at_dte": 21,  # DTE threshold for end-of-life management (roll or flat close)
    "roll_for_credit": True,  # True = roll the whole strangle at manage_at_dte; False = close flat
    "max_rolls": 3,  # maximum consecutive rolls per original position
    "roll_dte_max": 60,  # wider DTE window for roll target (at 21 DTE the next 3rd Friday is ~49 DTE)
    "single_position": True,  # True = skip new monthly entry while a prior chain is still open
    # VIX-conditional entry filter — applies to both new monthly entries AND
    # 21-DTE roll continuations. When VIX > vix_entry_max at the 21-DTE
    # management date, the position is closed flat instead of rolled.
    "vix_entry_filter_enabled": True,
    "vix_entry_max": 35.0,  # skip entries/rolls when entry-day VIX close exceeds this
    # Defensive leg roll
    # WARNING: 0.30 trigger is too aggressive for systematic use. Backtesting 2010-2024 shows
    # it fires ~13x/year and HURTS returns (-17% vs +15%) because rolling the untested leg
    # toward ATM during a trending move creates compounding losses on reversal (see Feb 2020).
    # The tastytrade rule is discretionary. Set to False for the baseline strategy.
    "defensive_leg_roll_enabled": False,  # default OFF — see warning above
    "defensive_trigger_delta": 0.30,  # |delta| on tested side that triggers roll of the untested leg
    "leg_roll_target_delta": 0.16,  # delta for the new untested leg (matches entry delta)
    "max_leg_rolls_per_trade": 2,  # max leg rolls total per trade (put + call combined)
}

# ── Pricing source + model ───────────────────────────────────────────────

PRICING: PricingParams = {
    # "market"    → use real bid/ask/mark from the SQLite options DB
    # "synthetic" → compute everything via Black-Scholes (use for post-2025 simulation)
    "mode": "market",
    "db_path": "data/Spy Options Database.db",
    # Synthetic model parameters.
    # In market mode these are still used for gap-open stop pricing
    # (DB is EOD-only, so overnight gaps always fall back to BS).
    "risk_free_rate": RISK_FREE_RATE_DEFAULT,  # fallback when ^IRX data unavailable
    "put_slope": 0.30,  # 16Δ put skew: vol × (1 + 0.30 × Δ) ≈ vol × 1.10
    "call_slope": 0.10,  # 16Δ call skew: vol × (1 + 0.10 × Δ) ≈ vol × 1.03
    "vix_to_iv_multiplier": 1.15,  # SPY IV is typically ~15% higher than VIX
}

# ── Stop-loss overshoot model ────────────────────────────────────────────

OVERSHOOT: OvershootParams = {
    # When a stop triggers intraday, the actual fill is worse than the -200% trigger.
    # The blend fraction controls how far toward the EOD/open mark the fill lands.
    # Regime is determined by SPY daily range / prev close.
    "overshoot_orderly": 0.25,  # range < 1.5%
    "overshoot_normal": 0.50,  # 1.5% ≤ range < 3.0%
    "overshoot_violent": 0.80,  # range ≥ 3.0%
    "range_threshold_orderly": 0.015,
    "range_threshold_violent": 0.030,
    # On gap days VIX at the open is higher than the prior close.
    # vix_open = vix_prev × (1 + gap_vix_multiplier × |gap_pct|)
    # e.g. 2% gap → +6% VIX, 5% gap → +15% VIX.
    "gap_vix_multiplier": 3.0,
}

# ── Portfolio / laddering ────────────────────────────────────────────────

PORTFOLIO: PortfolioParams = {
    "max_bpr_allocation": 0.30,  # max 30% of starting capital as margin usage
    "cash_yield_annual": 0.04,  # 4% annual risk-free rate on uninvested cash
    "entry_cooldown_days": 3,  # minimum trading days between new entries
    "cash_investment_mode": "spy",  # "risk_free" | "spy" | "blend"
    "spy_allocation_pct": 0.40,   # SPY fraction when cash_investment_mode="blend"
}

# ── Merge into a single flat dict for backward compatibility ─────────────
# All downstream cells (run_backtest, compute_metrics, plot) read from PARAMS.
# The sub-dicts are the human-facing interface; PARAMS is the machine interface.

PARAMS: dict = {**BACKTEST, **STRATEGY, **PRICING, **OVERSHOOT, **PORTFOLIO}
