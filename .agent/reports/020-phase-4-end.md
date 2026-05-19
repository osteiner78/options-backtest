# Phase 4 End Report — Plan 020: Improve Code Quality

## What was built

- **4a — `_compute_daily_marks` helper**: Extracted the 46-line daily marks block from `evaluate_trade_step` into a standalone helper. Returns `(pnl, pnl_pct, close_cost, exit_db_source, mid_d, put_mid_d, call_mid_d, ctx)`. Main function now calls it in 3 lines.
- **4b — `_find_defensive_roll_strikes` helper**: Extracted delta reading, tested-side determination, close-mark, new-strike finding, ATM validation, and net-credit check from `attempt_defensive_leg_roll` into a focused helper. Returns a 10-tuple on success or `None`. Main function reduced from 150 to ~70 lines.
- **4c — `_detect_db_schema` method**: Extracted schema detection (PRAGMA table_info, CDI columns, delta/IV column resolution, IV where filter) from `MarketEngine.__init__` into `_detect_db_schema()`. Init now calls `self._detect_db_schema()`.
- **4d — `_apply_mpl_style()`**: Removed module-level `plt.style.use("seaborn-v0_8-whitegrid")` and replaced with a try/except-guarded function called at the start of `plot_backtest` and `plot_engine_comparison`.
- **4e — `_show_if_interactive()` guard**: Replaced bare `plt.show()` calls with a function that checks `matplotlib.get_backend() != "agg"` before calling `plt.show()`. Prevents hangs in headless environments.
- **4f — Variable renaming**: `row` → `row_d`, `closed` → `completed_trade`, `latest_open_exit` → `chain_close_date` in `run_backtest`. All 3 names are now self-documenting.

## Test results

```
============================= 129 passed in 1.80s ==============================
```

```
python scripts/run_backtest.py --mode synthetic --no-plot
Trades executed : 59
Final balance   : $63,641.15
Total P&L       : $+13,641.15
Total return    : 27.3%
```

Results identical to Phase 1 baseline.

## Deviations from plan

- **4a**: Added `mid_d`, `put_mid_d`, `call_mid_d`, `ctx` to helper return tuple — needed by downstream exit checks (overshoot, profit, 21DTE, expiry, non-exit result).
- **4b**: Added `new_credit_ps` and `tested_side` to helper return tuple — needed by the execute block (LegRollEvent and baseline mid recomputation).

## Follow-ups

None — all 4 phases complete.

## Confidence rating

**certain** — 129/129 tests pass, backtest output byte-for-byte identical across all phases.
