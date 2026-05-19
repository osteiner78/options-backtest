# 021 — Phase 1 Start Report

**Date:** 2026-05-18  
**Status:** Starting Phase 1 (API updates)

## Scope

Update `src/straddle/api.py` to accept grid v7 parameter names (`execution_mode`, `vix_filter`, `defensive_leg_roll`) alongside the deprecated internal names. Add `info_ratio` passthrough to `MetricsResponse`. No changes outside this file in Phase 1.

## Pre-work observations

- `params.py:58` lists `execution_mode` valid values as `"bid_ask" | "mid_minus_1tick" | "mid" | "mid_plus_1tick"`, but grid v7 only uses `bid_ask`, `mid`, `mid_plus_1tick`. Pattern will match grid v7 set.
- `_translate_vix_filter` will mirror `_apply_vol_filter` from `scripts/grid_search.py` but only for `OFF` and `rv_pct:` modes (ivr dropped per user clarification).
- `info_ratio` is already computed by `compute_metrics` and `compute_portfolio_metrics` at `metrics.py:420`; just needs `MetricsResponse` field + `_build_metrics_response` passthrough.
- `/config` endpoint enums dict should include `execution_mode` for the UI.

## Issues resolved

- Pattern: `rv_pct` only (no `ivr:`), matching v7 grid search.
- `info_ratio` field added to `MetricsResponse` model and builder.

All issues flagged pre-implementation have been clarified by the user.
