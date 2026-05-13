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
    american_options: bool      # True → use BAW approximation for put pricing (PETR4)
    use_cdi_ivs: bool           # True → use implied_volatility_cdi / delta_cdi columns from rb3 DB


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
    # Unified vol filter (replaces VIX-only with B3-native RV/IVR modes).
    # Mode: "vix" (backward compat), "rv_pct", "ivr", "off".
    # Threshold: VIX cap for "vix", percentile for "rv_pct", min IVR for "ivr".
    "vol_filter_mode": "vix",
    "vol_filter_threshold": 35.0,
    # Defensive leg roll — default OFF (see warning in strategy.py)
    "defensive_leg_roll_enabled": False,
    "defensive_trigger_delta": 0.30,
    "leg_roll_target_delta": 0.16,
    "max_leg_rolls_per_trade": 2,
}

# ── Pricing source + model ───────────────────────────────────────────────
#
# NOTE: B3 options have ~50% bid/ask coverage at target delta. Only ~50% of
# option-day rows have bid > 0 AND ask >= bid. When DB data is unavailable
# for either leg, the entire entry falls back to SyntheticEngine (BSM +
# parametric skew). This means approximately half of trade entries are priced
# by the synthetic model. Grid search results should always be reported with
# entry_db_pct to indicate how much real market data was used.
#
PRICING: PricingParams = {
    "mode": "market",
    "options_db_path": "data/Spy Options Database.db",
    "risk_free_rate": RISK_FREE_RATE_DEFAULT,
    "put_slope": 0.30,
    "call_slope": 0.10,
    "vix_to_iv_multiplier": 1.15,  # SPY IV is typically ~15% higher than VIX
    "contract_multiplier": 100.0,  # shares per contract
    "use_cdi_ivs": False,  # True → use implied_volatility_cdi / delta_cdi columns from rb3 DB
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
        "commission_per_leg": 1.00,    # USD per leg
        "american_options": False,     # SPY options are European-style (cash-settled)
    },
    "bova11": {
        "market": "bova11",
        "market_data_source": "b3_cotahist",
        "options_db_path": "data/B3/b3_options_rb3.db",
        "calendar": "BVMF",
        "currency": "BRL",
        # vix_close for B3 is loaded as percentage points (ATM IV × 100) so
        # vix_to_iv_multiplier=1.0 and the /100 in SyntheticEngine cancel correctly.
        "vix_to_iv_multiplier": 1.00,
        "contract_multiplier": 100.0,
        "commission_per_leg": 1.00,    # R$ per leg (typical B3 retail: R$0.50–1.50)
        # Fitted from b3_options.db (2017–2026) via scripts/fit_b3_skew.py.
        # put_slope=0.743: B3 put skew is ~2.5× steeper than SPY — emerging-market
        # tail-risk demand drives strong OTM put premiums.
        # call_slope=0.031: near-flat; shifted from +0.30 (2019–2022) to −0.10
        # (2024–2026), full-sample average reflects the structural transition.
        # Slopes encode dividend effects implicitly — no separate q parameter.
        "put_slope":  0.743,
        "call_slope": 0.031,
        "american_options": False,     # BOVA11 is an ETF — options are European-style
        # BOVA11 ATM IV is typically 15–35 VIX units; cap at 50 to avoid blocking
        # most of the backtest in high-vol regimes that are normal for Brazil.
        "vix_entry_max": 50.0,
    },
    "petr4": {
        "market": "petr4",
        "market_data_source": "b3_cotahist",
        "options_db_path": "data/B3/b3_options_rb3.db",
        "calendar": "BVMF",
        "currency": "BRL",
        "vix_to_iv_multiplier": 1.00,
        "contract_multiplier": 100.0,
        "commission_per_leg": 1.00,    # R$ per leg
        # Fitted from b3_options.db (2010–2026) via scripts/fit_b3_skew.py.
        # put_slope=0.523: moderate put skew, stable at 0.40–0.66 across years.
        # call_slope=-0.057: consistently negative — PETR4 calls trade above ATM IV,
        # reflecting dividend-adjusted forward pricing and oil-price optionality.
        # Slopes encode dividend effects implicitly — no separate q parameter.
        "put_slope":  0.523,
        "call_slope": -0.057,
        # PETR4 options are American-style (B3 single-stock equity options).
        # Early exercise of puts is optimal when deep ITM, driven by the interest
        # earned on K at Brazil's high CDI rate (12–15%). The BAW approximation
        # (Barone-Adesi & Whaley 1987) is used in SyntheticEngine for put pricing.
        # Calls with q=0 have no early-exercise benefit → remain European.
        "american_options": True,
        # PETR4 ATM IV is typically 25–60 VIX units; cap at 80 to avoid blocking
        # most entries — crisis spikes (>80) are still filtered.
        "vix_entry_max": 80.0,
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
