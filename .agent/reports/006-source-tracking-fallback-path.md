# 006 — Redundant Source Tracking Queries in Dead Fallback Path

**Status:** resolved

## Symptom

`evaluate_trade_step` (strategy.py) had a branching code path: if `get_leg_mark_with_source`
existed (MarketEngine), use the merged marks+source query; otherwise (SyntheticEngine),
call `get_leg_mark` + separate `_source_for_strike` queries. The separate path did 2
extra DB queries per leg per day. While `SyntheticEngine` never hit the second path
(`_source_for_strike` is MarketEngine-only), the branching logic was dead code for
synthetic mode and fragile for any future engine.

## Root Cause

`SyntheticEngine` lacked `get_leg_mark_with_source` — it only had `get_leg_mark`.
The `hasattr` check in `evaluate_trade_step` created two code paths with different
source tracking behavior (MarketEngine = merged, SyntheticEngine = separate).

## Fix Applied

1. **`SyntheticEngine.get_leg_mark_with_source`** (engines.py): New method added for
   interface parity. Returns `(bs_mid, "synthetic")` — always synthetic source.
   `get_leg_mark` now delegates to `get_leg_mark_with_source`.

2. **`evaluate_trade_step`** (strategy.py): Removed the `hasattr` branch. Now always
   calls `engine.get_leg_mark_with_source()`.

3. **Test update** (test_strategy.py): Renamed `test_synthetic_backtest_exit_source_unknown`
   → `test_synthetic_backtest_exit_source_synthetic`. Now correctly asserts `exit_source == "synthetic"`.

## Verification

- All 90 tests pass
- Synthetic mode no longer has a dead code path for source tracking
- `_source_for_strike` remains in MarketEngine for potential external use (private method)

## Follow-ups

- `_source_for_strike` is now unused in strategy.py but kept for external callers
