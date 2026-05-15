# Plan 015 — Phase 1 Start Report

**Date:** 2026-05-15  
**Branch:** b3-backtest  
**Plan:** `.agent/plans/015-post-v7-follow-up-investigations.md`

## Scope Confirmation

Five post-v7 follow-up investigations across 5 phases:
1. Force-close P&L fix materiality (did the Phase 5 fix affect v7 grid results?)
2. 16Δ compromise deep-dive (liquidity, equity curve, commission sensitivity)
3. Document identical Sharpe rows (degeneracy analysis + Cell L in v7 notebook)
4. PETR4 analysis (pilot 18 backtests, full grid if pilot positive)
5. Worst 6-month rolling window stress scenarios

## Pre-work Observations

- All referenced functions exist: `apply_market_preset`, `run_portfolio_backtest` (returns 4-tuple, not 2 — plan pseudocode will be corrected), `load_market_data`, `make_engine`.
- DB columns confirmed as `bid`, `ask`, `mark` for Phase 2 liquidity queries.
- v7 notebook has 31 cells (0–30); Cell L will be appended as cells 31–32 (markdown + code).
- `data/B3/` directory exists for output files.
- v7 grid results at `data/B3/v7_grid_search_results.parquet`.

## Phase 1 Plan

Run the recommended 25Δ/dte21/pt50%/mid/laddering BOVA11 config for the holdout period (2023-01-02 to 2025-11-30). Count force-closed trades and their P&L contribution to determine if the v7 grid needs to be re-run.

Decision gate: <5% force-closed trades AND <2% P&L contribution → document and proceed. Otherwise re-run grid.
