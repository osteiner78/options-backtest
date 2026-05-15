# Plan 013 — Phase A Start Report
Date: 2026-05-14

## Scope understood

Phase A runs 6 reliability checks before the v6 expanded grid (Phase B). All checks are automated:
A.1 re-runs the v5 grid with the fixed engine cache; A.2 verifies 3 trades against raw DB queries;
A.3 runs a SPY regression; A.4 compares synthetic vs market modes; A.5 profiles exit-reason P&L;
A.6 tests American option sensitivity. A.7 is the pass/fail summary.

## Pre-work observations

1. **A.1 mode resolved**: `v5_grid_search_results.parquet` is laddering (committed grid_search.py
   hard-codes `portfolio_mode="laddering"`; no `portfolio_mode` column in the parquet confirms this).
   The plan's single_position grid would compare apples-to-oranges. Per user decision (Option B):
   A.1 will run **both** modes (laddering + single_position) with the fixed cache — 384 backtests
   total (~2 min). Laddering results → cache bug test vs original. Single_position → new baseline.

2. **A.3 code fix**: Plan's snippet uses `trades, eq = run_backtest(...)` but `run_backtest` returns
   a 4-tuple. Will use `trades, eq, _, _ = run_backtest(...)`.

3. **v5_grid_search_laddering.parquet already exists** (192 rows, laddering, fixed cache).
   A.1 laddering run output will be saved as `v5_grid_search_laddering_fixed.parquet` so both are
   available for comparison. The existing laddering file was generated with the same fixed-cache code.

4. **Pre-flight commit**: Committing all 15 files listed in the plan (excluding `.opencode/`).

## Files to create in Phase A

- `scripts/verify_single_position.py` — A.1 grid runs + comparison
- `scripts/phase_a_checks.py` — A.2 through A.6 checks + A.7 summary
- `data/B3/v5_grid_search_singlepos_fixed.parquet` — A.1 single_position output
- `data/B3/v5_grid_search_laddering_fixed.parquet` — A.1 laddering output (cache bug test)
