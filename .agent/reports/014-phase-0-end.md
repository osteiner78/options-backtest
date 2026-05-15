# Phase 0 End — Bug Fixes Complete

**Date:** 2026-05-15
**Commit:** d9227b8 `[phase-0] fix all 11 bugs + 6 suggestions from code-review report 015`
**Tests:** 129 passed (22 new, 0 failed, 0 regressions)

---

## What Was Built

### Critical Fixes (Correctness)

**Bug #1 — _VOL_CACHE key (strategy.py)**
Changed cache key from `id(data)` to `(data.index[0], data.index[-1], mode, threshold)`. Added `clear_vol_cache()` and `clear_strategy_caches()` public functions exported via `__init__.py`. The original bug could silently return the wrong vol filter for a backtest when Python reused a GC'd memory address.

**Bug #2 — Force-close double-append (portfolio.py)**
Introduced `_last_res: dict[int, TradeStepResult] = {}` dict before the main loop. In the `else` branch (position still open), stores `_last_res[trade_num_open] = res`. Force-close block now uses `_last_res.get(trade_num_open)` instead of re-calling `evaluate_trade_step`. Trades that enter on the very last day are skipped (`if res is None: continue`). This eliminates the duplicate date entries in `daily_marks` that corrupted `_compute_mtm_equity`.

### Important Fixes

**Bug #3** — `except:` → `except Exception:` in `engines.py __del__`.

**Bug #4** — `risk_free_rate` field in `BacktestRequest` now has a `description` documenting it maps to `cash_yield_annual`, not the option-pricing rate.

**Bug #5 — IVR filter logic (strategy.py)**
- Fixed condition: was `ivr_val < (threshold / 100.0)` (block when IV HIGH), now `ivr_val > (1.0 - threshold / 100.0)` (block when IV LOW)
- Changed default Series from `pd.Series(True, ...)` to `pd.Series(False, ...)` — warmup period now unblocked, consistent with `rv_pct` mode

**Bug #6** — `upsert_run` SQL `label` UPDATE clause now uses `CASE WHEN excluded.label IS NULL THEN label ELSE excluded.label END`.

**Bug #7** — `runs_store._DB_PATH` anchored to `Path(__file__).resolve().parent.parent.parent / "data" / "runs.db"`.

**Bug #8** — `@model_validator(mode='after')` added to `BacktestRequest` validating `dte_min < dte_max`.

**Bug #9** — `clear_data_caches()` added to `data.py`; `clear_strategy_caches()` added to `strategy.py` (clears both `_VOL_CACHE` and `_TRADING_DAY_SETS`). All exported via `__init__.py`.

**Bug #10** — `sigma < 1e-8` guard added to `american_put_baw` (extends the existing `T < 1e-7 or r < 1e-8` guard).

**Bug #11 — apply_market_preset (params.py)**
Added optional `explicitly_set: Optional[set] = None` parameter. When provided, keys in that set are restored from `params` regardless of whether they match the SPY default. Without it, the improved fallback heuristic: non-market keys always pass through; market keys that differ from the SPY default are preserved. The original bug (market key matching SPY default being silently dropped) requires callers to pass `explicitly_set` — no existing callers needed this fix.

### Suggestions

**S1** — `vol_filter_mode` and `vol_filter_threshold` added to `StrategyParams` TypedDict.

**S2** — `"american_options": False` added to base `PRICING` dict; now present in `PARAMS` without requiring `apply_market_preset`.

**S3** — `from scipy.optimize import brentq as _brentq` moved to module-level in `engines.py`; removed local import inside `_baw_critical_put`.

**S4** — `params["cash_investment_mode"]` and `params["underlying_allocation_pct"]` changed to `.get()` with defaults in `_build_metrics_response`.

**S5** — `MetricsResponse` and `BacktestResponse` expanded to one field per line.

**S6** — Deferred (low-priority LRU eviction for `_results` dict). Noted as follow-up.

---

## Test Results

```
129 passed in 1.79s
```

New tests added:
- `TestVolCacheKey` (4 tests) — verifies cache key uses index bounds, `clear_vol_cache()` works
- `TestIvrVolFilter` (3 tests) — verifies warmup is unblocked, high-IV allows entry, low-IV blocks
- `TestForceCloseNoDuplicateMarks` (1 test) — verifies no duplicate dates in `daily_marks` after force-close
- `TestStrategyParamsTypedDict` (2 tests) — verifies `vol_filter_mode`, `vol_filter_threshold` in TypedDict
- `TestPricingDefaults` (3 tests) — verifies `american_options` in PRICING and PARAMS
- `TestApplyMarketPreset` (5 tests) — verifies market switch, non-market key preservation, `explicitly_set`
- `TestRunsStoreDBPath` (2 tests) — verifies absolute path anchored to project root
- `TestUpsertRunLabelPreservation` (2 tests) — verifies label not erased on status update

---

## Deviations from Plan

1. **Bug #11**: The plan said "Use a separate 'explicitly_set' set" without specifying a mechanism. Implemented as an optional parameter (`explicitly_set: Optional[set] = None`) with backward-compatible fallback. No existing callers needed updating — the practical footgun (market-key override equaling SPY default) doesn't arise in grid search since grid keys don't overlap with market-specific keys.

2. **S6**: Not implemented. A simple max-size trim was an option but the plan says "low priority" — deferred to follow-ups rather than adding complexity without user request.

---

## Follow-ups (noted but not in scope)

- S6: LRU or TTL eviction for `_results` dict in `api.py`
- No `clear_caches()` call added to `run_grid()` yet — plan says to do this in Phase 3's notebook cell 4. Noted here so it's not forgotten.
- `_build_vol_filter` is still O(n²) for `rv_pct` and `ivr` modes (Python loop). For large date ranges this is slow. Vectorisation would help Phase 3 grid performance but is outside Phase 0 scope.

---

## Confidence Rating: **certain**

All fixes are visible by inspection in the changed code, all new tests target the specific failure modes described in the bug report, and all 129 tests pass green.
