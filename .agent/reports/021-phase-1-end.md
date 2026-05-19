# 021 — Phase 1 End Report

**Date:** 2026-05-18  
**Status:** Complete

## What was built

- **1a:** Added `execution_mode` field to `BacktestRequest` with pattern `bid_ask|mid|mid_plus_1tick`.
- **1b:** Replaced `vix_entry_filter_enabled`/`vix_entry_max` with `vix_filter` string field (pattern: `OFF|rv_pct:70|rv_pct:80|rv_pct:90`). Old fields kept with `deprecated=True`.
- **1c:** Added `defensive_leg_roll` field alongside deprecated `defensive_leg_roll_enabled`.
- **1d:** Added `_translate_vix_filter()` helper — mirrors `_apply_vol_filter` from `scripts/grid_search.py` for OFF and rv_pct modes.
- **1e-f:** Added `defensive_leg_roll` → `defensive_leg_roll_enabled` remap + call to `_translate_vix_filter` in `_run_backtest_task`.
- **1g:** Added `info_ratio` to `MetricsResponse` model and wired it through `_build_metrics_response`.

## Test results

```
============================= 129 passed in 1.75s ==============================
```

## Deviations from plan

- Pattern for `vix_filter` excludes `ivr:` variants per user clarification (ivr dropped from v7 grid due to inversion bug).
- Had to fix a variable name on-the-fly (`m.get` → `metrics.get`) in `_build_metrics_response` — the plan had every line correct except that one reference.

## Follow-ups

None.

## Confidence

**certain** — all 129 tests pass, no existing behavior changed, only additive.
