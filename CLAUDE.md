# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project Overview

B3 short strangle backtesting engine — sells monthly OTM put + call options at
12–25Δ on BOVA11 (ETF) and PETR4 (single stock), targeting 21–60 DTE, with
21-DTE roll management. Mid-price execution, laddering mode, Reg-T margin accounting.

**Database:** `data/B3/b3_options_rb3.db` (SQLite, BOVA11 + PETR4, 2015–2025,
~9.6 GB). Uses CDI-based implied volatilities and deltas. American-style pricing
(BAW approximation) enabled for PETR4; European-style (BSM) for BOVA11.

## Commands

```bash
pip install -e ".[dev,frontend,api]"
pytest tests/ -v
python scripts/run_backtest.py --mode market --market bova11
python scripts/run_v7_grid.py --n-workers 4
```

## Architecture

```
params.py (PARAMS dict + B3 market presets)
  → data.py (load_market_data → COTAHIST parquet / Yahoo Finance)
  → engines.py (make_engine → SyntheticEngine | MarketEngine)
  → strategy.py (run_backtest → trades[], equity_curve)
     → portfolio.py (run_portfolio_backtest → laddering mode)
  → metrics.py (compute_metrics / compute_portfolio_metrics)
  → plotting.py (plot_backtest)
```

## Key Concepts

- **Two engines** share identical interface: `SyntheticEngine` (BSM + parametric vol skew)
  and `MarketEngine` (real bid/ask from SQLite DB, falls back to synthetic).
- **B3 presets** in `params.py` override SPY defaults (CDI rates, BVMF calendar,
  BRL currency, calibrated skew slopes, tick_size=0.05).
- **Laddering mode** via `run_portfolio_backtest` — Reg-T margin, entry cooldown,
  concurrent positions per expiry.
- **Metrics:** Information ratio (primary, for config comparison), true Sharpe
  (CDI-subtracted, for transparency), Calmar ratio, DB source tracking %.
- **Information Ratio:** The grid search Sharpe values are technically information
  ratios (excess-over-zero). The Brazilian risk-free rate (CDI, 10-13%)
  exceeds the strategy's absolute return (2-3%), making the standard Sharpe
  negative for most configs. See the definitive notebook methodology section.

## Definitive Research

`research/2026-05-15 - B3 - definitive research report.ipynb` — all findings,
executed cells, charts. Recommended config: 25Δ/dte21/pt50%/OFF/mid/laddering.

## Code Quality

- Review 027 applied: all print() → logging, named constants extracted, long
  functions split, dead code removed, duplicated blocks extracted to helpers.
- 129 tests pass at `pytest tests/ -v`.
- All known bugs from code reviews 015–027 are fixed or documented as immaterial.
