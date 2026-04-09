# SPY Short Strangle Backtest

Backtesting engine for the **SPY short strangle** strategy — selling monthly OTM put + call options at 16-delta, targeting 30–45 DTE.

## Strategy Overview

| Parameter | Default | Description |
|---|---|---|
| **Delta** | 16Δ | Sell 16-delta put + 16-delta call |
| **DTE Range** | 30–45 | Days to expiration at entry |
| **Profit Target** | 50% | Close when P&L ≥ 50% of net premium |
| **Stop Loss** | 200% | Close when P&L ≤ -200% of net premium |
| **21-DTE Management** | Roll for credit | Roll the strangle at 21 DTE |
| **Single Position** | Yes | Skip new entries while a chain is open |
| **VIX Filter** | Enabled | Skip entries when VIX > 35 |

## Quick Start

### Install

```bash
cd straddle-backtest
pip install -e ".[dev,frontend,api]"
```

### Run CLI

```bash
# Synthetic mode (Black-Scholes)
python scripts/run_backtest.py --mode synthetic --start 2024-01-01 --end 2024-12-31

# Market mode (real options data from SQLite DB)
python scripts/run_backtest.py --mode market

# Skip plot generation
python scripts/run_backtest.py --mode synthetic --no-plot
```

### Run Streamlit Frontend

```bash
streamlit run frontend/app.py
```

### Run API Server

```bash
python scripts/run_api.py --port 8000

# Test it:
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/backtest \
  -H "Content-Type: application/json" \
  -d '{"mode":"synthetic","start_date":"2024-01-01","end_date":"2024-03-31"}'
```

### Run Tests

```bash
pytest tests/ -v
```

## Architecture

```
straddle-backtest/
├── src/straddle/
│   ├── __init__.py      # Public API facade
│   ├── params.py        # PARAMS dict, TypedDict schemas, defaults
│   ├── data.py          # load_market_data(), parquet cache, date validation
│   ├── engines.py       # SyntheticEngine, MarketEngine, make_engine()
│   ├── strategy.py      # Trade, run_backtest(), calendar utils, leg rolls
│   ├── metrics.py       # compute_metrics() with SPY benchmark stats
│   ├── plotting.py      # plot_backtest(), plot_engine_comparison()
│   └── api.py           # FastAPI REST API
├── scripts/
│   ├── run_backtest.py  # CLI entry point
│   └── run_api.py       # API server entry point
├── frontend/
│   └── app.py           # Streamlit web UI
├── tests/
│   ├── conftest.py      # Shared fixtures
│   ├── test_engines.py  # BS math, engine parity
│   ├── test_strategy.py # Calendar, Trade, backtest invariants
│   └── test_metrics.py  # Metrics computation
├── data/
│   └── Spy Options Database.db  # SQLite options DB (market mode)
└── pyproject.toml
```

### Module Boundaries

- **`params.py`** — All tunable knobs. Four sub-dicts (BACKTEST, STRATEGY, PRICING, OVERSHOOT) merged into flat `PARAMS`.
- **`data.py`** — Yahoo Finance data loading with parquet caching. No dependency on `PARAMS`.
- **`engines.py`** — Pricing engines. `SyntheticEngine` (Black-Scholes) and `MarketEngine` (SQLite DB). Shared interface.
- **`strategy.py`** — Trade mechanics: entry/exit, roll management, defensive leg rolls.
- **`metrics.py`** — Performance metrics: Sharpe, drawdown, win rate, SPY benchmark.
- **`plotting.py`** — Visualization: equity curve, P&L charts, VIX regime.

### Pricing Modes

| Mode | Description |
|---|---|
| **`synthetic`** | Black-Scholes using VIX as ATM vol + parametric skew. Works for any date range. |
| **`market`** | Real bid/ask from SQLite options DB (2008–2025). Falls back to synthetic for gap-open pricing and post-2025 dates. |

## Parameters Reference

### BACKTEST
| Key | Default | Description |
|---|---|---|
| `start_date` | 2021-01-01 | Backtest start |
| `end_date` | 2025-11-30 | Backtest end |
| `initial_balance` | 50,000 | Starting account balance |
| `commission_per_leg` | 1.00 | $/contract/leg |

### STRATEGY
| Key | Default | Description |
|---|---|---|
| `target_delta` | 0.16 | Strike selection delta |
| `dte_min` / `dte_max` | 30 / 45 | Acceptable DTE range |
| `profit_target_pct` | 0.50 | Close at 50% of premium |
| `stop_loss_pct` | 2.00 | Close at -200% of premium |
| `manage_at_dte` | 21 | DTE for end-of-life management |
| `roll_for_credit` | True | Roll at manage_at_dTE |
| `max_rolls` | 3 | Max consecutive rolls |
| `single_position` | True | No overlapping trades |
| `vix_entry_filter_enabled` | True | VIX-conditional entry |
| `vix_entry_max` | 35.0 | Max VIX for entry |
| `defensive_leg_roll_enabled` | False | Defensive leg roll (OFF by default) |

### PRICING
| Key | Default | Description |
|---|---|---|
| `mode` | market | `synthetic` or `market` |
| `db_path` | data/Spy Options Database.db | SQLite DB path |
| `risk_free_rate` | 0.045 | Fallback rate |
| `put_slope` / `call_slope` | 0.30 / 0.10 | Vol skew slopes |

## License

Private project — not for distribution.
