# Phase 1 Complete — Entry Cooldown Sensitivity Script

**Date:** 2026-05-18 | **Plan:** 022 — entry_cooldown_sensitivity

## What was built

- `scripts/run_cooldown_sensitivity.py` — standalone grid runner for 5 cooldowns × 3 DTE windows × 2 periods = 30 backtests against BOVA11 market data. Fixed base: 25Δ/pt50%/manage14/OFF/stop2.0/mid/laddering.
- `data/B3/v7_cooldown_sensitivity.parquet` — output: 30 rows, 0 errors, 15 columns including BPR utilization metrics.

## Test results

```
129 passed in 1.73s
```

All existing tests pass. No engine or library changes.

## Deviations from plan

1. Fixed `apply_market_preset` call to capture return value (`params = apply_market_preset(params, "bova11")`) since the function returns a new dict rather than mutating.
2. Added `engine = None` initialization before try block to prevent `NameError` in the finally clause if `make_engine` fails.

## Verified

- `avg_bpr_util` and `peak_bpr_util` returned as percentages (0–100) from `compute_portfolio_metrics` — ranges from ~10% to ~78% across the grid, confirming the plan's capital efficiency premise.
- `cooldown=5` and `cooldown=7` produce identical results for `dte_max=21`, confirming saturation (only one entry per expiration cycle at those cooldowns).
- No error rows — all 30 backtests completed successfully.

## Key preliminary results (holdout)

| Cooldown | dte21 IR | dte30 IR | dte45 IR |
|----------|----------|----------|----------|
| 1        | 1.11     | 1.13     | 0.27     |
| 2        | 1.11     | 1.03     | 0.25     |
| 3        | **1.43** | 1.33     | 0.22     |
| 5        | 1.78     | 1.32     | 0.27     |
| 7        | 1.78     | **1.45** | 0.38     |

IR peaks at different cooldowns for different DTE windows — dte30/cooldown=7 hits 1.45, dte21/cooldown=5-7 hits 1.78 (but only 71 trades, 15% BPR util).

## Confidence: certain
