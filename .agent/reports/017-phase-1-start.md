# Phase 1 Start — Plan 017: Pre-Paper-Trading Validation Steps 1, 2, 6

**Date:** 2026-05-15

## Scope

Three pre-paper-trading checks:
- **Step 1** — B3 Bulletin Validation: re-run existing `validate_b3_prices.py` (already built and functional; produced PARTIAL verdict on 2026-05-13)
- **Step 2** — Extended Commission Sensitivity: create `scripts/extended_commission_sensitivity.py` (new)
- **Step 6** — PETR4 Period Robustness: create `scripts/petr4_period_robustness.py` (new)

## Pre-work observations

1. `validate_b3_prices.py` already exists and the plan's template is compatible in logic but differs in detail. The existing script correctly handles the B3 fetcher API (keyword args, "PUTT" type mapping) and has already been run with a PARTIAL verdict. I will re-run it.

2. Two critical bugs in the plan's Step 2/6 code were identified and will be fixed during implementation:
   - `run_portfolio_backtest` returns 4 values (`trades, equity_df, portfolio, n_blocked`); the plan unpacks only 2.
   - Parameter `commission_per_contract` doesn't exist; the actual key is `commission_per_leg`.

3. All required data files exist: `b3_options_rb3.db` (266 MB), `v7_petr4_grid_search_results.parquet`, `v7_grid_search_results.parquet`.

## Confidence

Certain — no ambiguities remain after clarification.
