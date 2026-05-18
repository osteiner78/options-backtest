# Phase 3 End Report — Plan 020: Improve Code Quality

## What was built

- **3a — plotting.py `plot_backtest` split**: Extracted 7 private `_plot_*` helpers from the 205-line `plot_backtest` function. Each draws one panel into a `fig.add_gridspec(4, 2)` layout. Main function reduced to ~30 lines: figure setup, 7 helper calls, tight_layout/save/show.
- **3b — portfolio.py `run_portfolio_backtest` split**: Extracted 3 private helpers from the 276-line backtest loop:
  - `_evaluate_open_positions` — daily mark, exit, and roll-continuation logic (returns updated `trade_num`)
  - `_process_laddering_entries` — vol-filter check, expiration lookup, entry pricing, and capacity check (returns updated `trade_num`)
  - `_force_close_remaining` — end-of-backtest position closure
  Main function reduced to ~80 lines. Added `PricingContext` to module-level imports.

## Test results

```
============================= 129 passed in 1.76s ==============================
```

```
python scripts/run_backtest.py --mode synthetic --no-plot
Trades executed : 59
Final balance   : $63,641.15
Total P&L       : $+13,641.15
Total return    : 27.3%
```

Results identical to Phase 1/2 baselines.

## Deviations from plan

- **3a**: Skipped the `GRUVBOX` parameter in helper signatures (not used in `plot_backtest`). Used `add_gridspec(4, 2)` and `gs[row, col]` instead of passing a `grid` object — same effect, more idiomatic matplotlib.
- **3b**: `_evaluate_open_positions` needs `underlying_close`, `vix_d`, `r_d` (not in plan's signature). Both `_evaluate_open_positions` and `_process_laddering_entries` return `trade_num` (int is immutable, must be returned). `_force_close_remaining` omits `engine`/`params`/`data` (not used).

## Follow-ups

None — Phase 3 is complete.

## Confidence rating

**certain** — 129/129 tests pass, backtest output byte-for-byte identical.
