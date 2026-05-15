# Plan 016 Phase 1 Start Report

**Date:** 2026-05-15  
**Branch:** b3-backtest  
**Plan:** `.agent/plans/016-i10-sharpe-impact-measurement.md`

## Scope Confirmed

Phase 1 measures the impact of the I-10 Sharpe fix (commit `1db7e66`) on 5 key configs
from the v7 BOVA11 and PETR4 grids. The fix changed `_compute_sharpe_from_daily_pnl` in
`metrics.py` from `daily_ret = daily_pnl / init` (constant initial-balance denominator)
to `equity.pct_change()` (running-equity denominator). Both parquets in `data/B3/` were
generated before this fix.

## Pre-Work Observations

- I-10 fix is confirmed in `src/straddle/metrics.py:194–202` (current code uses `pct_change()`).
- Old Sharpe values extracted from parquets match plan's stated values exactly:
  - 25Δ BOVA11 train: 0.908, holdout: 1.292  
  - 16Δ BOVA11 holdout: 1.883  
  - 12Δ BOVA11 mid_plus_1tick holdout: 11.557  
  - 25Δ PETR4 train: 0.613, holdout: 1.211
- Plan's stated PETR4 "old" values aren't given — extracted above for reference.
- No ambiguities or inconsistencies found in the plan.

## Next Step

Run 5 standalone backtests with the current (fixed) code via
`scripts/measure_sharpe_impact.py`, compare against parquet old values, and populate
the ΔSharpe table to trigger the Phase 2 decision gate.
