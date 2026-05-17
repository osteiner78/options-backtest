Phase 1 — Safe Cleanup (15 min, near-zero risk)
1a. Erase 9 temporary comments
In each file, replace the comment with nothing or with a concise permanent version:
File Lines Current (first few words)
strategy.py 32-33 id() reuses memory addresses after GC...
strategy.py 606-608 get_loc() can return an array/slice...
portfolio.py 300-303 Tracks the last TradeStepResult...
portfolio.py 492-496 Label "FORCE_CLOSE" distinguishes...
portfolio.py 501-505 Trade entered on the very last day...
data.py 55-56 v2 cache uses generic...
data.py 190-195 B3 vix_close is stored as a decimal...
engines.py 547-549 Avoids duplicated delta_cdi/delta...
plotting.py 10 Merged from the notebook's \_C (cell 13)...
1b. Replace 12 print() calls with logging
In each of engines.py, data.py, plotting.py:

- Add import logging; logger = logging.getLogger(**name**) near the top
- Replace print(f"...") → logger.info("...") or logger.warning("...") as appropriate
- Remove plotting.py:367 (print() with empty line)
  1c. Add named constants for magic numbers
  Add to the top of each file (or a shared \_constants block):
  File Constant Value
  strategy.py \_TRADING_DAYS_PER_YEAR = 252 252
  strategy.py \_MONTHLY_SCAN_WINDOW = 5 5
  strategy.py \_ENTRY_SCAN_DAYS = 15 15
  engines.py \_MIN_T = 1e-7 1e-7
  engines.py \_MIN_IV_FLOOR = 0.01 0.01
  engines.py \_D1_CLIP_BOUNDS = (-50.0, 50.0) -50, 50
  engines.py \_EXPIRY_MATCH_TOLERANCE = 5 5
  data.py \_DTE_BUFFER_DAYS = 90 90
  data.py \_MAX_CACHE_GAP_DAYS = 7 7
  portfolio.py \_REG_T_UNDERLYING_PCT = 0.20 0.20
  portfolio.py \_REG_T_MIN_FLOOR_PCT = 0.10 0.10
  metrics.py Use RISK_FREE_RATE_DEFAULT (already imported)
  1d. Delete dead code
  File Lines
  engines.py 1026-1044
  portfolio.py 33, 153, 248, 539
  Phase 1 checkpoint
  pytest tests/ -v # must pass 129/129
  python scripts/run_backtest.py --mode synthetic --no-plot # must not crash

---

Phase 2 — Extract Duplicated Blocks (20 min, low risk)
2a. metrics.py — extract _compute_source_tracking_stats(trades)
The 16-line block at lines 358-374 (repeated verbatim at 450-466) becomes:
def \_compute_source_tracking_stats(trades: list) -> dict:
entry_db_count = sum(1 for t in trades if getattr(t, 'entry_source', 'unknown') == 'db')
exit_db_count = sum(
1 for t in trades
if t.exit_type is not None and getattr(t, 'exit_source', 'unknown') == 'db'
)
mtm_db_pct_list = []
for t in trades:
total = getattr(t, 'mtm_total_days', 0)
source_days = getattr(t, 'mtm_source_days', 0)
if total > 0:
mtm_db_pct_list.append(source_days / total)
return {
"entry_db_count": entry_db_count,
"entry_db_total": len(trades),
"entry_db_pct": entry_db_count / len(trades) * 100.0 if trades else 0.0,
"exit_db_count": exit_db_count,
"mtm_avg_db_pct": float(np.mean(mtm_db_pct_list)) * 100.0 if mtm_db_pct_list else 0.0,
}
Replace both call sites with results.update(\_compute_source_tracking_stats(trades)).
2b. portfolio.py — extract \_compute_close_mid_and_commissions(trade)
The duplicated mid_close_ps / n_comm logic (lines 356-365 and 443-451) becomes:
def \_compute_close_mid_and_commissions(
put_mid_ps: float, call_mid_ps: float,
long_put_mid_ps: Optional[float] = None,
long_call_mid_ps: Optional[float] = None,
) -> tuple[float, int]:
if long_put_mid_ps is not None and long_call_mid_ps is not None:
return (
put_mid_ps + call_mid_ps - long_put_mid_ps - long_call_mid_ps,
4, # 4 legs = 4 commissions
)
return (put_mid_ps + call_mid_ps, 2)
2c. engines.py — extract \_synthetic_fallback_entry(...) in get_entry_marks
The 3 repeated blocks (lines 631-635, 646-651, 661-664) become a single private method:
def \_synthetic_fallback_entry(
self, S: float, T: float, r: float, vix: float, delta: float, ctx
) -> tuple[float, float, float, float]:
pk, ck, pm, cm, _ = self.\_synth.get*entry_marks(S, T, r, vix, delta, ctx)
adj_combined = self.\_synth.apply_fill_adj(pm + cm, "open")
factor = adj_combined / (pm + cm) if (pm + cm) > 0 else 1.0
return pk, ck, pm * factor, cm \_ factor
Replace the 3 call sites with pk, ck, pm, cm = self.\_synthetic_fallback_entry(S, T, r, vix, delta, ctx).
Phase 2 checkpoint
pytest tests/ -v # must pass 129/129

---

Phase 3 — Split Long Functions (30 min, medium risk — STOP HERE if unsure)
3a. plotting.py — split plot*backtest (205 lines → 7 helpers)
The existing # 1. Equity curve, # 2. P&L per trade, etc. comments indicate natural split points. Extract each numbered section into a private \_plot*\* function that takes (fig, grid, data, trades, params, GRUVBOX) and draws into the grid. The main function becomes ~30 lines:
def plot_backtest(trades, equity_curve, data, params, output_path=None):
fig = plt.figure(figsize=(16, 22))
gs = fig.add_gridspec(...)
ax_equity = \_plot_equity_curve(fig, gs, equity_curve, data, params)
ax_pnl = \_plot_pnl_bars(fig, gs, trades)
ax_cum = \_plot_cumulative_pnl(fig, gs, trades)
ax_hist = \_plot_return_histogram(fig, gs, trades)
ax_exit_count = \_plot_exit_type_count(fig, gs, trades, EXIT_COLORS)
ax_exit_avg = \_plot_exit_avg_pnl(fig, gs, trades, EXIT_COLORS)
\_plot_vix_overlay(fig, gs, data, params) # ... save + show
3b. portfolio.py — split run_portfolio_backtest (285 lines → 4 helpers + 80-line main)
Extract into private functions in the same file:
def \_evaluate_open_positions(
eval_date, portfolio, engine, params, data, daily_trading_dates,
\_last_res, all_trades, \_day_idx, \_total_days, progress_callback,
) -> None: ...
def \_process_laddering_entries(
eval_date, portfolio, engine, params, data, daily_trading_dates,
vix_d, r_d, trade_num, \_vol_blocked_exps, all_trades,
) -> int: # returns updated trade_num
def \_force_close_remaining(
last_date, portfolio, engine, params, data,
\_last_res, all_trades,
) -> None: ...
Phase 3 checkpoint
pytest tests/ -v # must pass 129/129

# Also run a quick end-to-end backtest:

python scripts/run_backtest.py --mode synthetic --no-plot
⚠️ If Phase 3 tests fail, REVERT and skip. Do not debug in-place.

---

Phase 4 — Optional Deep Clean (defer if uncertain)
Item File What
Split evaluate_trade_step (124 lines) strategy.py Extract \_compute_daily_marks(...) helper for lines 820-865
Split attempt_defensive_leg_roll (150 lines) strategy.py Extract \_find_defensive_roll_strikes(...)
Split MarketEngine.**init** (74 lines) engines.py Extract \_detect_db_schema()
Move plt.style.use from module scope into functions plotting.py Add try/except, call inside plot_backtest and plot_engine_comparison
Add plt.show() guard (if interactive) plotting.py Prevents hang in headless environments
Fix variable naming inconsistencies strategy.py row→row_d, closed→completed_trade, latest_open_exit→chain_close_date
