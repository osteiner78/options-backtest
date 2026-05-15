# Phase End Report — Plan 017: Steps 1, 2, 6

**Date:** 2026-05-15

## What was built

### Step 1 — B3 Bulletin Validation
- Re-ran existing `scripts/validate_b3_prices.py` (already built, correctly handles B3 fetcher API)
- Result: **PARTIAL** verdict — 20/20 contracts matched (100%), 70% mark-vs-last within ±10%, median diff 0.0%
- Output: `output/validation/validation_targets.csv`, `validation_comparison.csv`
- Report: `docs/2026-05-15 - rb3 price validation.md`
- BOVA11 exercise style: PUTs are EURO (European), CALLs are mixed AMER/EURO — existing codebase assumes European

### Step 2 — Extended Commission Sensitivity
- Created `scripts/extended_commission_sensitivity.py`
- 288 backtests: 5 BOVA11 + 3 PETR4 configs × 3 modes × 6 multipliers × 2 periods
- Key findings:
  - BOVA11 holdout mid: all 5 configs positive at 5× commission; 20d/rv_pct:80 stays positive at 7×
  - PETR4 holdout mid: all 3 configs positive at 3×, none at 5×
  - At 10× commission, only mid_plus_1tick remains positive for both markets
- Output: `output/commission_extended/bova11_commission_extended.csv`, `petr4_commission_extended.csv`
- Report: `docs/2026-05-15 - extended commission sensitivity.md`

### Step 6 — PETR4 Period Robustness
- Created `scripts/petr4_period_robustness.py`
- 225 backtests: 15 top configs from v7 parquet × 5 windows × 3 modes
- Key findings:
  - Overall (mid): 80.0% configs positive across all windows
  - Data-rich windows (2018-2024): **97.8%** configs positive at mid (exceeds BOVA11's 78.7%)
  - mid_plus_1tick: 98.7% positive overall
  - Recommended config (25d/dte21/pt50%/OFF) positive at mid in ALL data-rich windows
  - Conclusion: PETR4 is **as robust as BOVA11**
- Output: `output/petr4_robustness/petr4_robustness_results.csv`
- Report: `docs/2026-05-15 - PETR4 period robustness.md`

## Test results

```
129 passed in 1.77s
```

All existing tests pass. No regressions.

## Deviations from plan

1. **`apply_market_preset` return value** (Steps 2, 6): The plan's code calls `apply_market_preset(params, market)` without capturing the return value, but the function returns a new dict (does NOT mutate in-place). Fixed by using `params = apply_market_preset(dict(PARAMS), market)`.

2. **`run_portfolio_backtest` unpacking** (Steps 2, 6): The function returns `Tuple[List[Trade], pd.DataFrame, PortfolioManager, int]` (4 values), but the plan unpacks only 2. Fixed with `trades, eq, *_ = run_portfolio_backtest(...)`.

3. **`commission_per_contract` → `commission_per_leg`** (Step 2): The actual parameter name in `portfolio.py` and `strategy.py` is `commission_per_leg`, not `commission_per_contract`.

4. **Used existing validate script** (Step 1): `scripts/validate_b3_prices.py` already existed with a better implementation (correct keyword args, "PUTT" mapping). Re-ran it rather than recreating from the plan template.

5. **Added missing required params**: `dte_min` from `DTE_MIN_BY_DTE_MAX`, `use_price_stop: True`, `single_position: False` (needed for laddering mode).

## Follow-ups

- Step 2: BOVA11 baseline commission is R$1.00/leg (per the bova11 preset), not R$2.00 as mentioned in the plan. The multipliers relative to R$2.00 are effectively half the plan's expectations. Verify with user whether R$1.00/leg is correct for institutional B3 commissions.
- Step 6: The 2015-2017 and 2016-2018 windows have low DB coverage (25-43%) — results there are synthetic-dominant and less reliable, flagged in the report.

## Confidence

**certain** — All steps completed, all outputs generated, all tests pass, all identified bugs fixed.
