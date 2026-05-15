# 001 — Missing Fill Adjustment for Synthetic Fallback in MarketEngine

**Status:** resolved

## Symptom

Market mode backtests with synthetic fallback entries (50% of B3 trades) systematically
overstated P&L. A sample trade (BOVA11, 2023-03-07 entry) showed `pnl=77.61` when the
correct value was `67.61` — an overstatement of R$10.00 (14.8%).

## Root Cause

`MarketEngine.apply_fill_adj()` is a no-op because it assumes real DB bid/ask already
capture trading spread. However, three methods fall back to `SyntheticEngine` when DB
data is unavailable:
- `get_entry_marks()` — returns raw BS mids (entry credit miss -5%)
- `get_leg_mark_with_source()` — returns raw BS mids (close cost miss +5%)
- `get_daily_mark()` — returns raw BS mids (close cost miss +5%)

The caller (`build_entry`, `evaluate_trade_step`) then calls `engine.apply_fill_adj()`
which is a no-op, so the fill adjustment is entirely lost.

## Fix Applied (engines.py)

Three changes:

1. **`get_leg_mark_with_source` (both fallback paths):** Apply `self._synth.apply_fill_adj()`
   with direction based on `buy_or_sell`:
   ```python
   synth = self._synth.apply_fill_adj(synth, "open" if buy_or_sell == "sell" else "close")
   ```

2. **`get_entry_marks` synthetic fallback:** Apply entry fill adjustment to the combined
   mid, then scale individual leg mids proportionally:
   ```python
   adj_combined = self._synth.apply_fill_adj(pm + cm, "open")
   factor = adj_combined / (pm + cm) if (pm + cm) > 0 else 1.0
   return pk, ck, pm * factor, cm * factor, False
   ```

3. **`get_daily_mark` per-leg fallback:** Apply close-side fill adjustment:
   ```python
   put_mark = self._synth.apply_fill_adj(put_mark, "close")
   ```

## Verification

- All 85 existing tests pass unchanged
- Manual reconciliation: Market mode Trade 3 (BOVA11, 2023-03-07, fully synthetic) now
  produces `net_credit=131.78, pnl=67.61` — matching the pure synthetic engine exactly
- DB-data trades are unaffected (fill adj only applied on synthetic fallback branches)

## Related Issues

- Bug 002: fill adjustment incorrectly also applied to intrinsic value at expiry
- Follow-up: consider making `apply_fill_adj` consistent across engines rather than
  baking it into the fallback paths
