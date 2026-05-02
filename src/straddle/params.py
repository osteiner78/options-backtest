"""PARAMS schema, defaults, and validation.

All tunable knobs for the short strangle backtest are defined here.
The sub-dicts provide a human-facing interface; the merged PARAMS dict
is the machine interface used by all downstream functions.
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
    options_db_path: str
    risk_free_rate: float
    put_slope: float
    call_slope: float
    vix_to_iv_multiplier: float
    contract_multiplier: float  # shares per contract (100 for both US and B3 equity options)
    dividend_yield: float       # continuous dividend yield q (0.0 = standard BS)


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
    cash_investment_mode: str         # "risk_free" | "underlying" | "blend"
    underlying_allocation_pct: float  # underlying fraction for "blend" mode


class MarketParams(TypedDict, total=False):
    market: str               # "spy" | "bova11" | "petr4"
    market_data_source: str   # "yahoo" | "b3_cotahist"
    calendar: str             # "NYSE" | "BVMF"
    currency: str             # "USD" | "BRL"


class PaperTradingParams(TypedDict, total=False):
    paper_db_path: str
    paper_config_path: str


# ── Constants ───────────────────────────────────────────────────────────

RISK_FREE_RATE_DEFAULT = 0.045


# ── Backtest infrastructure ─────────────────────────────────────────────

BACKTEST: BacktestParams = {
    "start_date": "2021-01-01",
    "end_date": "2025-11-30",
    "initial_balance": 50_000,
    "commission_per_leg": 1.00,  # $1/contract/leg → $2 open + $2 close = $4/round-trip
    "vix_low": 15,
    "vix_high": 25,
}

# ── Strategy rules ───────────────────────────────────────────────────────

STRATEGY: StrategyParams = {
    "strategy_mode": "short_strangle",
    "wing_delta": 0.05,
    "target_delta": 0.16,
    "dte_min": 30,
    "dte_max": 45,
    "profit_target_pct": 0.50,
    "stop_loss_pct": 2.00,
    "open_fill_adj": -0.05,
    "close_fill_adj": +0.05,
    "use_price_stop": False,
    "manage_at_dte": 21,
    "roll_for_credit": True,
    "max_rolls": 3,
    "roll_dte_max": 60,
    "single_position": True,
    "vix_entry_filter_enabled": True,
    "vix_entry_max": 35.0,
    # Defensive leg roll — default OFF (see warning in strategy.py)
    "defensive_leg_roll_enabled": False,
    "defensive_trigger_delta": 0.30,
    "leg_roll_target_delta": 0.16,
    "max_leg_rolls_per_trade": 2,
}

# ── Pricing source + model ───────────────────────────────────────────────

PRICING: PricingParams = {
    "mode": "market",
    "options_db_path": "data/Spy Options Database.db",
    "risk_free_rate": RISK_FREE_RATE_DEFAULT,
    "put_slope": 0.30,
    "call_slope": 0.10,
    "vix_to_iv_multiplier": 1.15,  # SPY IV is typically ~15% higher than VIX
    "contract_multiplier": 100.0,  # shares per contract
}

# ── Stop-loss overshoot model ────────────────────────────────────────────

OVERSHOOT: OvershootParams = {
    "overshoot_orderly": 0.25,
    "overshoot_normal": 0.50,
    "overshoot_violent": 0.80,
    "range_threshold_orderly": 0.015,
    "range_threshold_violent": 0.030,
    "gap_vix_multiplier": 3.0,
}

# ── Portfolio / laddering ────────────────────────────────────────────────

PORTFOLIO: PortfolioParams = {
    "max_bpr_allocation": 0.30,
    "cash_yield_annual": 0.04,
    "entry_cooldown_days": 3,
    "cash_investment_mode": "underlying",
    "underlying_allocation_pct": 0.40,
}

# ── Market selector ──────────────────────────────────────────────────────

MARKET: MarketParams = {
    "market": "spy",
    "market_data_source": "yahoo",
    "calendar": "NYSE",
    "currency": "USD",
}

# ── Per-market presets ───────────────────────────────────────────────────
# apply_market_preset() merges one of these into params before running.

MARKET_PRESETS: dict = {
    "spy": {
        "market": "spy",
        "market_data_source": "yahoo",
        "options_db_path": "data/Spy Options Database.db",
        "calendar": "NYSE",
        "currency": "USD",
        "vix_to_iv_multiplier": 1.15,
        "contract_multiplier": 100.0,
        "commission_per_leg": 1.00,   # USD per leg
        "dividend_yield": 0.0,        # kept at 0 — existing SPY results unchanged
    },
    "bova11": {
        "market": "bova11",
        "market_data_source": "b3_cotahist",
        "options_db_path": "data/B3/b3_options.db",
        "calendar": "BVMF",
        "currency": "BRL",
        "vix_to_iv_multiplier": 1.00,   # vix_close for B3 IS the actual ATM IV
        "contract_multiplier": 100.0,
        "commission_per_leg": 1.00,     # R$ per leg (typical B3 retail: R$0.50–1.50)
        # Fitted from b3_options.db (2017–2026) via scripts/fit_b3_skew.py.
        # put_slope=0.743: B3 put skew is ~2.5× steeper than SPY — emerging-market
        # tail-risk demand drives strong OTM put premiums.
        # call_slope=0.031: near-flat; shifted from +0.30 (2019–2022) to −0.10
        # (2024–2026), full-sample average reflects the structural transition.
        "put_slope":  0.743,
        "call_slope": 0.031,
        # dividend_yield=0.0 — correct for both market mode and current synthetic mode:
        #
        # Market mode: MarketEngine uses real COTAHIST bid/ask directly; dividends
        # are already priced in by the market. The stored delta is only used for
        # approximate 16Δ strike selection (error ~0.002, negligible). No correction
        # needed.
        #
        # Synthetic mode: vix_close was extracted from market prices using q=0, so
        # using q=0 here keeps the vol input and the model convention consistent.
        # More importantly, the fitted put_slope/call_slope were derived from real
        # market prices that already reflect dividends — they encode the dividend
        # effect implicitly. Setting q>0 alongside a q=0-derived vix_close would
        # double-count the dividend and cause systematic mispricing.
        #
        # To properly enable q>0 in synthetic mode, rebuild vix_close with
        # dividend-adjusted IV (set dividend_yield in build_b3_parquets.py and
        # rerun), then refit the skew slopes from the adjusted IV surface.
        "dividend_yield": 0.0,
    },
    "petr4": {
        "market": "petr4",
        "market_data_source": "b3_cotahist",
        "options_db_path": "data/B3/b3_options.db",
        "calendar": "BVMF",
        "currency": "BRL",
        "vix_to_iv_multiplier": 1.00,
        "contract_multiplier": 100.0,
        "commission_per_leg": 1.00,     # R$ per leg
        # Fitted from b3_options.db (2010–2026) via scripts/fit_b3_skew.py.
        # put_slope=0.523: moderate put skew, stable at 0.40–0.66 across years.
        # call_slope=-0.057: consistently negative — PETR4 calls trade above ATM IV,
        # reflecting dividend-adjusted forward pricing and oil-price optionality.
        # Note: the negative call_slope directly encodes the dividend effect: with
        # a lower dividend-adjusted forward, OTM calls appear cheaper vs ATM,
        # so the fitted slope is negative. No separate q parameter needed.
        "put_slope":  0.523,
        "call_slope": -0.057,
        # See bova11 comment above — same reasoning applies.
        # PETR4 actual yield varies widely (5–40% in 2022–2023) making a fixed q
        # a poor approximation; the fitted slopes are more robust.
        "dividend_yield": 0.0,
    },
}


def apply_market_preset(params: dict, market: str) -> dict:
    """Merge per-market defaults into params. Call before make_engine/load_market_data.

    Priority (lowest → highest):
      1. base PARAMS defaults
      2. market preset (calendar, currency, db path, vix multiplier, etc.)
      3. explicit caller overrides (CLI flags, API request fields)

    Because params usually starts as dict(PARAMS), which already contains
    market-specific defaults for "spy", the preset must override it so
    that switching to "bova11" correctly sets BRL, BVMF, etc.

    Keys that the caller set *after* the initial PARAMS merge (i.e. explicit
    CLI/API overrides like --start or --mode) are preserved via `extras`.
    """
    preset = MARKET_PRESETS.get(market)
    if preset is None:
        raise ValueError(f"Unknown market {market!r}. Valid: {list(MARKET_PRESETS)}")
    # Keys in params that differ from SPY-market PARAMS are explicit overrides
    spy_defaults = {k: MARKET_PRESETS["spy"].get(k) for k in preset}
    extras = {k: v for k, v in params.items() if k not in preset or params[k] != spy_defaults.get(k)}
    merged = dict(params)          # 1. base (includes PARAMS defaults)
    merged.update(preset)          # 2. preset wins over PARAMS defaults
    merged.update({k: v for k, v in extras.items() if k not in preset})  # 3. non-market explicit overrides
    merged["market"] = market      # always stamp the resolved market
    return merged


# ── Paper trading runtime files ─────────────────────────────────────────

PAPER_TRADING: PaperTradingParams = {
    "paper_db_path": "data/paper_trades.db",
    "paper_config_path": "data/paper_config.json",
}

# ── Merge into a single flat dict for backward compatibility ─────────────
# All downstream functions read from PARAMS.
# Sub-dicts are the human-facing interface; PARAMS is the machine interface.

PARAMS: dict = {
    **BACKTEST, **STRATEGY, **PRICING, **OVERSHOOT,
    **PORTFOLIO, **MARKET, **PAPER_TRADING,
}
