Plan 014 — v7 Final Validation & Refined Grid
Date: 2026-05-15 | Target: Coding agent | Branch: b3-backtest

Context
v6 (24,192 laddering backtests) confirmed: VRP exists at mid/mid_plus_1tick, consumed at bid_ask. 85% of configs positive in both train+holdout for mid_plus_1tick. Code review (report 015) found 2 critical bugs, 7 important issues, 6 suggestions. Cell J display bug confirmed (entry_db_pct ~100× too small). Before deploying capital, we need: (1) bug-free engine, (2) refined grid without poor performers, (3) period robustness across multiple windows, (4) 10-trade manual P&L verification.

---

Phase 0: Fix All Code-Review Bugs

Fix all 12 issues from report 015. Order matters — #1 and #2 must be fixed before any grid runs.

Bug #1 — \_VOL_CACHE uses id(data) as key (strategy.py:19,28-29)

- Replace cache key with (data.index[0], data.index[-1], mode, threshold)
- Add clear_vol_cache() function
- Call clear_vol_cache() at start of run_grid()

Bug #2 — Force-close double-appends to daily_marks (portfolio.py:473-484)

- Store last TradeStepResult per trade_num during main loop
- In force-close block, reuse stored result instead of calling evaluate_trade_step again
- Set exit_date, exit_dte, exit_type, pnl, pnl_pct from stored result
- Remove the re-evaluation call entirely

Bug #3 — Bare except: pass in **del** (engines.py:912-916)

- Change `except:` to `except Exception:`

Bug #4 — \_PARAM_REMAP naming confusion (api.py:37-43)

- Add description field to BacktestRequest documenting the mapping
- Add comment explaining risk_free_rate → cash_yield_annual mapping

Bug #5 — IVR vol-filter logic inverted (strategy.py:54-61)

- Fix condition: block when IVR is LOW (too little premium), not HIGH
- Change `result.iloc[i] = ivr_val < (threshold / 100.0)` to `result.iloc[i] = ivr_val > (1.0 - threshold / 100.0)`
- Change initial default from `pd.Series(True, ...)` to `pd.Series(False, ...)` so first 252 days are unblocked (consistent with rv_pct behavior)

Bug #6 — upsert_run erases label on status update (runs_store.py:33-50)

- Change label UPDATE clause to: `label = CASE WHEN excluded.label IS NULL THEN label ELSE excluded.label END`

Bug #7 — CWD-relative DB path (runs_store.py:8)

- Change `_DB_PATH = Path("data/runs.db")` to `_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "runs.db"`

Bug #8 — Missing dte_min < dte_max validation (api.py:55-56)

- Add model_validator to BacktestRequest: if dte_min and dte_max are both set, dte_min must be < dte_max

Bug #9 — Module-level globals never expire (strategy.py:94, data.py:201)

- Add clear_caches() function to both modules
- Document for API callers

Bug #10 — sigma=0 crashes BAW (engines.py:135-143)

- Add early return in american_put_baw: if T < 1e-7 or r < 1e-8 or sigma < 1e-8, return max(bs_price, intrinsic)
- Same for american_call_baw if it exists

Bug #11 — apply_market_preset discards overrides matching SPY defaults (params.py:289-295)

- Track which keys were explicitly passed by caller, compare against those rather than SPY defaults
- Use a separate "explicitly_set" set to determine which params are user overrides

Suggestions:

- S1: Add vol_filter_mode, vol_filter_threshold, vix_entry_max to StrategyParams TypedDict
- S2: Add "american_options": False to PRICING dict
- S3: Move `from scipy.optimize import brentq` to module top level in engines.py
- S4: Use .get() with defaults for cash_investment_mode and underlying_allocation_pct in api.py
- S5: Expand MetricsResponse fields to one-per-line
- S6: Add TTL or LRU eviction for \_results dict in api.py (low priority)

Verification: After all fixes, run pytest tests/ -v. All passing tests must still pass. No new regressions.

---

Phase 1: Fix Cell J Display Bug

The v6 parquet field `entry_db_pct` shows ~0.5% instead of ~50%.

Investigation:

- Check how entry_db_pct is computed in the grid search (scripts/grid_search.py)
- The value is likely stored as a fraction (0.50) when it should be a percentage (50.0), or vice versa
- Check the notebook Cell J formatting vs the raw stored value

Fix:

- Ensure entry_db_pct is stored as a percentage (0-100 range) consistently
- Update the notebook Cell J display to show the value correctly
- Verify: for BOVA11 holdout, entry_db_pct should be ~50% (i.e., ~50% of entries come from the DB)

---

Phase 2: Investigate Sharpe=11.73 Config

The 12Δ config has holdout Sharpe=11.73. Before the v7 grid, verify this is not a data artifact.

Step 2.1 — Standalone run
Run the Sharpe=11.73 config as a single backtest:
params = {
"target_delta": 0.12,
"dte_max": 30,
"profit_target_pct": 0.25,
"manage_at_dte": 7, # any value; all equivalent at this profit_target
"vix_filter": "rv_pct:80",
"defensive_leg_roll": False,
"stop_loss_pct": 2.0,
"execution_mode": "mid_plus_1tick",
"portfolio_mode": "laddering",
}

# Holdout: 2023-01-02 to 2025-11-30

Inspect: number of trades, average premium per trade, average hold days, win rate, equity curve shape, max drawdown.

Step 2.2 — Cross-mode comparison
Run the same config in bid_ask and mid modes. Expected: Sharpe sequence bid_ask < mid < mid_plus_1tick.

Step 2.3 — Liquidity check
For the 12Δ trades:

- Query DB for the actual bid/ask at entry for each trade
- Compute: (bid_ask_spread / premium_received) to get spread-as-fraction-of-premium
- If average spread > 50% of premium → the config is economically unviable (cannot realistically fill at mid)
- Compare to the 16Δ config's spread fraction

Step 2.4 — Verdict
If liquidity check shows 12Δ is unviable, flag in v7 report as "statistically profitable but practically untradeable" and recommend 16Δ as the practical best. If viable, keep it.

---

Phase 3: v7 Refined Grid

Based on v6 insights, drop poorly differentiating dimensions and poor performers.

GRID = {
"target_delta": [0.12, 0.16, 0.20, 0.25], # drop 30Δ (poor), drop 50Δ/straddle (poor)
"dte_max": [21, 30, 45, 60], # keep all — DTE Pareto is meaningful
"profit_target_pct": [0.25, 0.50], # drop 0.75 (little differentiation)
"manage_at_dte": [5, 7, 14, 21], # keep all for DTE interaction
"vix_filter": ["OFF", "rv_pct:70", "rv_pct:80", "rv_pct:90"], # keep all
"defensive_leg_roll": [False], # dropped (ΔSharpe ±0.03, negligible)
"stop_loss_pct": [2.0, 3.0], # keep both
"execution_mode": ["bid_ask", "mid", "mid_plus_1tick"],
"portfolio_mode": ["laddering"],
}

# 4 × 4 × 2 × 4 × 4 × 1 × 2 × 3 × 1 = 3,072 raw combos

# Validity filter drops manage_at_dte ≥ dte_min for short DTE windows

# Estimated valid combos: ~2,300

# Backtests: ~2,300 × 2 periods = ~4,600

RUNS = [
("train", "bova11", "2018-01-02", "2022-12-30"),
("holdout", "bova11", "2023-01-02", "2025-11-30"),
]

Save to data/B3/v7_grid_search_results.parquet.

Create notebook: research/2026-05-15 - B3 - v7 refined grid.ipynb

Cells (same structure as v6, adapted for v7):

1. Imports
2. Grid definition (v7)
3. Run config (train + holdout periods)
4. Execute grid (with clear_vol_cache() call before grid start)
5. Cell A: Sharpe by execution_mode (boxplot, train + holdout)
6. Cell B: Break-even execution level
7. Cell C: Execution mode × target_delta heatmap (holdout)
8. Cell D: DTE × target_delta heatmap (holdout)
9. Cell E: Profit target comparison (0.25 vs 0.50)
10. Cell F: Vol filter comparison
11. Cell G: Stop loss comparison (2.0 vs 3.0)
12. Cell H: Train vs holdout scatter (Sharpe per config)
13. Cell I: DB coverage (with fixed entry_db_pct display)
14. Cell J: Best config details across all 3 execution modes
15. Cell K: Config stability rank — sort configs by min(train_sharpe, holdout_sharpe)

---

Phase 4: Commission Sensitivity

For the top 5 configs from Phase 3, test three commission levels × 3 execution modes × 2 periods.

Commission levels:

- baseline: current commission (R$2.00 per trade, per params)
- double: R$4.00 per trade
- triple: R$6.00 per trade

5 configs × 3 modes × 3 commissions × 2 periods = 90 backtests

Report: table of Sharpe vs commission level per config, and the commission level at which mid execution flips negative.

---

Phase 5: Manual P&L Verification (10 Trades)

Select 10 trades from the best laddering config (holdout period):

- 3 PROFIT exits
- 3 ROLLED exits
- 2 21DTE/exercise exits
- 2 FORCE_CLOSE exits

For each trade:

1. Query DB directly for entry and exit day prices (bid, ask, mark for both put and call)
2. Hand-compute P&L using the execution_mode formula
3. Compare to engine's reported pnl and pnl_pct
4. All 10 must match within R$0.01

This is an expansion from the 3-trade verification in Phase A. The additional trade types (ROLLED, FORCE_CLOSE) verify the roll and force-close logic works correctly at the individual trade level.

---

Phase 6: Period Robustness

For the top 15 configs from Phase 3 (ranked by min(train_sharpe, holdout_sharpe)):

5 rolling 3-year windows:

1. 2015-01-02 to 2017-12-29
2. 2016-01-04 to 2018-12-31
3. 2018-01-02 to 2020-12-31
4. 2020-01-02 to 2022-12-30
5. 2022-01-03 to 2024-12-31

For each config × window, run in all 3 execution modes:
15 configs × 5 windows × 3 modes = 225 backtests

Report: for each execution mode, what fraction of config-window pairs are profitable (Sharpe > 0). Target:

- bid_ask: expected < 50%
- mid: expected > 50%
- mid_plus_1tick: expected > 70%

Also report: median Sharpe across all config-window pairs per mode.

Note: requires DB coverage for 2015-2017 window. If DB coverage is < 30% for this period, synthetic engine will dominate and the results should be flagged as synthetic-dominant. Check entry_db_pct for each window.

---

Phase 7: Final Report

Write docs/2026-05-15 - v7 final confirmation results.md containing:

1. Executive summary (confirmed/revised conclusion)
2. Bug fixes summary (what was wrong, what was fixed, impact assessment)
3. Cell J display fix confirmation
4. Sharpe=11.73 investigation verdict
5. v7 refined grid results (all cells A-K)
6. Commission sensitivity analysis
7. 10-trade manual P&L verification results
8. Period robustness results
9. Final recommendation: which config(s) to deploy, at what execution mode, with what caveats
10. Known remaining issues and limitations

---

Definition of Done

- [ ] Phase 0: All 12 bugs fixed, all existing tests pass, no new regressions
- [ ] Phase 1: Cell J entry_db_pct displays correctly as percentage (0-100)
- [ ] Phase 2: Sharpe=11.73 verdict documented (viable or untradeable)
- [ ] Phase 3: v7 grid executed (0 complex-number errors), saved to parquet, notebook complete
- [ ] Phase 4: Commission sensitivity table produced (90 backtests)
- [ ] Phase 5: 10 trades verified within R$0.01
- [ ] Phase 6: 225 period-robustness backtests complete, profitability fractions computed
- [ ] Phase 7: Final report written with confirmed conclusion and deployment recommendation

---

Deviations Allowed

- If Phase 2 shows 12Δ is dramatically untradeable (spread > 80% of premium), skip it in Phase 6's top-15 and use the next-highest delta config
- If the 2015-2017 window has < 30% DB coverage, flag it in the report and use a shorter window (2016-2018) if possible
- If any Phase 0 bug fix breaks existing tests, STOP and report before proceeding
- If v7 grid runtime exceeds 3 hours (sequential), reduce dte_max to [30, 45] and add a note about the dropped dimension
