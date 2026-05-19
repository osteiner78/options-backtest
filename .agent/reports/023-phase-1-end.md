# Phase 1 Complete — DTE30 Deep-Dive Script

**Date:** 2026-05-18 | **Plan:** 023 — dte30_cooldown_deep_dive

## What was built

`scripts/run_dte30_deep_dive.py` — standalone grid runner for 5 cooldowns × 3 manage_at_dte × 2 profit_targets × 2 periods = 60 backtests against BOVA11. Fixed base: 25Δ/dte30/OFF/stop2.0/mid/laddering.

`data/B3/v7_dte30_deep_dive.parquet` — output: 60 rows, 0 errors, 15 columns.

## Test results

```
129 passed in 1.79s
```

## Key preliminary finding

Best min(IR_train, IR_holdout) = 0.63 (dte30/cd=3/mgr=14/pt=50%). No config exceeds 1.20 stability threshold. Phase 3 (period robustness) will not be triggered.

## Deviations from plan

Same two fixes as Plan 022: `apply_market_preset` return value capture and `engine = None` initialization.

## Confidence: certain
