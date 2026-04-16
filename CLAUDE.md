# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SPY short strangle backtesting engine — sells monthly OTM put + call options at 16-delta, targeting 30–45 DTE, with 21-DTE roll management.

## Commands

```bash
# Install
pip install -e ".[dev,frontend,api]"

# CLI backtest
python scripts/run_backtest.py --mode synthetic --start 2024-01-01 --end 2024-12-31
python scripts/run_backtest.py --mode market
python scripts/run_backtest.py --mode synthetic --no-plot

# Streamlit UI
streamlit run frontend/app.py

# API server
python scripts/run_api.py --port 8000

# Tests
pytest tests/ -v
pytest tests/test_engines.py -v   # single test file
```

## Architecture

The data/execution flow is:

```
params.py (PARAMS dict)
  → data.py (load_market_data → Parquet cache)
  → engines.py (make_engine → SyntheticEngine | MarketEngine)
  → strategy.py (run_backtest → trades[], equity_curve)
  → metrics.py (compute_metrics)
  → plotting.py (plot_backtest)
```

**`params.py`** is the single source of truth for all strategy knobs. Four `TypedDict` sub-dicts (BACKTEST, STRATEGY, PRICING, OVERSHOOT) are merged into the flat `PARAMS` dict. All new parameters must be added here.

**`engines.py`** provides two pricing engines with a shared interface:
- `SyntheticEngine` — Black-Scholes + parametric vol skew (put_slope/call_slope). Works for any date range. Also handles gap-open pricing (DB is EOD-only).
- `MarketEngine` — Real bid/ask from SQLite DB (`data/Spy Options Database.db`, ~9.6 GB, 2008–2025). Falls back to `SyntheticEngine` for missing data.

**`strategy.py`** contains the core `Trade` dataclass and `run_backtest()` loop. Key concepts:
- `evaluate_trade_step()` — daily marking, profit/stop/roll checks
- `LegRollEvent` — defensive roll when a tested leg approaches 30Δ
- Roll chains tracked via `roll_count`, capped at `max_rolls`

**`portfolio.py`** (optional mode) — Reg-T margin accounting for multi-position laddering. Uses `calculate_reg_t_strangle_margin()`.

**`api.py`** — FastAPI with background task workers. Endpoints: `POST /backtest`, `GET /backtest/{id}`, `GET /health`.

**`data.py`** — Fetches SPY, VIX, and risk-free rate from Yahoo Finance. Maintains `market_data_master.parquet` with incremental updates. Adds a 90-day buffer before backtest start to ensure valid DTE calculations.

## Development Conventions

- All strategy parameters belong in `params.py` — never hard-code values in other modules.
- Maintain the `SyntheticEngine` / `MarketEngine` interface separation; both must implement `get_entry_marks()`, `get_daily_mark()`, and `get_gap_open_mark()`.
- Engine parity tests in `test_engines.py` must pass when touching pricing logic — synthetic and market results should remain reasonably close.
- `src/straddle/__init__.py` is a clean public API facade — keep it minimal.
- `tests/conftest.py` holds shared fixtures (`params`, `synthetic_engine`, `sample_trade`, `sample_leg_roll`) — use these in new tests rather than constructing fresh instances.
