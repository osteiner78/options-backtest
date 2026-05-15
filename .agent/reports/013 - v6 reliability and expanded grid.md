Plan 013 — v6 Reliability Validation & Expanded Grid
Date: 2026-05-14 | Target: Coding agent | Branch: b3-backtest
Context
The v5 laddering grid (Plan 012) produced Conclusion B: VRP exists but consumed by bid-ask spread. However, the project has seen wild oscillations in conclusions (v2 corrupted DB → v3 deeply negative → v4 bid_ask positive → v5 laddering negative → engine cache bug found). Before settling on Conclusion B, we need:

1. Systematic reliability checks to rule out remaining engine bugs
2. An expanded grid to find better parameter combinations and test straddle profitability

---

Pre-Flight: Commit Current State
git add -A
git commit -m "feat: v5 laddering grid, engine cache fix, mid_minus_1tick diagnosis, final report"
Uncommitted files to include:

- scripts/grid_search.py (+portfolio_mode, +exec cache fix)
- scripts/verify_position_mode.py (new)
- src/straddle/engines.py (execution modes, expiration fix)
- src/straddle/params.py (execution_mode params, volume_filter removed)
- src/straddle/portfolio.py (engine passthrough)
- src/straddle/strategy.py (engine passthrough, get_db_expiration)
- tests/test_execution_modes.py (execution mode tests)
- data/B3/v5_grid_search_laddering.parquet (new)
- data/B3/v5_grid_search_results.parquet (new)
- data/B3/v3_reproduction_results.parquet (new)
- docs/2026-05-14 - v5 confirmation results.md (new)
- research/2026-05-14 - B3 - v5 confirmation grid.ipynb (new)
- scripts/build_v5_notebook.py (new)
- .agent/plans/012 - v5 final resolution and report.md (new)

---

Phase A: Reliability Checks
Run all 6 checks. If any fail, STOP before Phase B.
A.1 — Re-run single_position v5 grid with fixed cache
The engine cache bug in grid_search.py cached by (market, start, end) ignoring execution_mode. Fix is already in place. Re-run the original v5 grid in single_position mode:
GRID = {
"target_delta": [0.16, 0.20, 0.25],
"dte_max": [30, 45],
"profit_target_pct": [0.50],
"manage_at_dte": [7, 14],
"vix_filter": ["OFF", "rv_pct:80"],
"defensive_leg_roll": [False],
"stop_loss_pct": [3.0],
"execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"],
"portfolio_mode": ["single_position"],
}
RUNS = [
("train", "bova11", "2018-01-02", "2022-12-31"),
("holdout", "bova11", "2023-01-02", "2025-11-30"),
]
Save to data/B3/v5_grid_search_singlepos_fixed.parquet.
Decision gate: Compare median Sharpe per execution_mode with v5_grid_search_results.parquet. If ±0.05 identical → cache bug didn't affect original, proceed. If >0.10 difference → original was corrupted, use fixed results as authoritative, note in report.
A.2 — Manual trade P&L verification
Pick 3 trades from the best laddering config (delta=0.16, dte=30, manage=14, vol=rv_pct:80, mid_plus_1tick) in holdout:

- One profitable trade (exit_reason=PROFIT)
- One losing trade (exit_reason=ROLLED or STOPPED)
- One breakeven trade
  For each, query the DB directly for entry and exit day data:
  conn = sqlite3.connect("data/B3/b3_options_rb3.db")

# For entry: query bid, ask, mark for both put and call at the entry strike+expiration

# For exit: query ask, mark for both legs at exit strike+expiration

# Hand-compute: entry_credit = put_bid + call_bid, close_cost = put_ask + call_ask

# P&L = (entry_credit - close_cost) \* multiplier - commissions

# Compare to engine's reported pnl

Decision gate: All 3 trades must match within R$0.01.
A.3 — SPY regression
Run original SPY backtest to confirm B3 engine changes haven't contaminated the SPY path:
params = dict(PARAMS)
params = apply_market_preset(params, "spy")
params.update({
"mode": "market", "start_date": "2023-01-01", "end_date": "2024-12-31",
"portfolio_mode": "single_position",
"cash_investment_mode": "risk_free", "cash_yield_annual": 0.0,
})
data = load_market_data("2023-01-01", "2024-12-31", market="spy")
engine = make_engine(params)
trades, eq = run_backtest(data, params, engine)
m = compute_metrics(trades, eq, params, data)

# Expected: Sharpe in [0.3, 2.0], n_trades > 30, no errors

Decision gate: Sharpe must be positive and no errors. If negative, B3 changes have broken the SPY path.
A.4 — Synthetic vs market comparison
Run best laddering config in pure synthetic mode vs market mode:

# Market mode (normal)

params_mkt = {...} # best config, mode="market", laddering

# Synthetic mode

params_syn = dict(params_mkt)
params_syn["mode"] = "synthetic"
For every trade in the market-mode run with entry_source == "synthetic", compare its P&L against the synthetic-mode's corresponding trade. Must match exactly. For entry_source == "db" trades, the difference must be explained by the spread (synthetic mode uses mid ± fill_adj, market uses bid/ask).
Decision gate: All synthetic-fallback trades match exactly. DB-source trades differ by no more than the documented spread (bid_ask → 40% median penalty vs synthetic 5% penalty).
A.5 — Trade forensics lite
For the best laddering config (holdout period), compute:

# P&L by exit reason

for reason in ['PROFIT', 'ROLLED', 'STOPPED', 'EXPIRED']:
trades_with_reason = [t for t in trades if t.exit_reason == reason]
print(f" {reason}: n={len(trades_with_reason)}, total_pnl={sum(t.pnl for t in trades_with_reason):.0f}")

# Top-3 and bottom-3 trade contribution

sorted_trades = sorted(trades, key=lambda t: t.pnl)
top3 = sum(t.pnl for t in sorted_trades[-3:])
bottom3 = sum(t.pnl for t in sorted_trades[:3])
print(f" Top 3 trades: {top3:.0f} ({top3/total_pnl*100:.1f}%)")
print(f" Bottom 3 trades: {bottom3:.0f} ({bottom3/total_pnl*100:.1f}%)")

# Entry credit distribution (DB-sourced only)

for t in db_trades:
credit = t.net_credit if t.net_credit else 0 # credit vs mark-based credit
Decision gate: If top 3 + bottom 3 explain >50% of total P&L, the strategy is driven by fat tails, not steady edge. Flag in report. If STOPPED trades are the dominant loss source, stop-loss calibration matters.
A.6 — American option sensitivity
Run best config with american_options=True vs False:
params_eu = dict(params_best)
params_eu["american_options"] = False
params_us = dict(params_best)
params_us["american_options"] = True

# Run both and compare

Decision gate: If ΔSharpe < 0.05 and Δtotal_return < 1% of initial capital → dismiss. Otherwise, flag in report.
A.7 — Summary checkpoint
Produce a simple pass/fail table:
Check Status Note
A.1 single_position repro PASS/FAIL
A.2 manual P&L PASS/FAIL
A.3 SPY regression PASS/FAIL
A.4 synthetic vs market PASS/FAIL
A.5 trade forensics INFO P&L concentration, exit reason breakdown
A.6 American options PASS/FAIL
If all PASS: Proceed to Phase B with confidence.  
If any FAIL: STOP and report to user.

---

Phase B: Expanded Grid Search (v6)
B.1 — Grid Definition
GRID = {
"target_delta": [0.12, 0.16, 0.20, 0.25, 0.30, 0.50], # adds 0.12 (thin) and 0.50 (straddle)
"dte_max": [21, 30, 45, 60], # adds 21 and 60
"profit_target_pct": [0.25, 0.50, 0.75], # restored from v3
"manage_at_dte": [5, 7, 14, 21], # adds 5 and 21
"vix_filter": ["OFF", "rv_pct:70", "rv_pct:80", "rv_pct:90"], # adds 70 and 90
"defensive_leg_roll": [True, False], # restored
"stop_loss_pct": [2.0, 3.0], # adds 2.0
"execution_mode": ["bid_ask", "mid", "mid_plus_1tick"], # drops mid_minus_1tick
"portfolio_mode": ["laddering"],
}

# 6 × 4 × 3 × 4 × 4 × 2 × 2 × 3 × 1 = 13,824 raw combos

Validity filter: manage_at_dte < DTE_MIN_BY_DTE_MAX[dte_max] where:

- dte_max=21 → dte_min ≈ 14 (manage 5, 7 valid; 14, 21 invalid)
- dte_max=30 → dte_min = 20 (manage 5, 7, 14 valid; 21 invalid)
- dte_max=45 → dte_min = 30 (all valid)
- dte_max=60 → dte_min = 45 (all valid)
  Expected valid combos: ~11,000-12,000 after filter.  
  ~22,000-24,000 backtests across 2 periods. Estimated runtime: 1-1.5 hours on 8 cores parallel, ~2-3 hours sequential.
  B.2 — Create v6 notebook
  Create research/2026-05-15 - B3 - v6 expanded grid.ipynb following the pattern of build_v5_notebook.py but for the v6 grid. Cells:
  Cell Label Description
  1 Imports matplotlib, pandas, numpy, grid_search
  2 Grid Definition GRID dict with 13,824 combos
  3 Run Config train (2018-2022), holdout (2023-2025)
  4 Execute Grid run_grid() → cached at data/B3/v6_grid_search_results.parquet
  5 Cell A Sharpe vs execution_mode boxplot (train + holdout subplots)
  6 Cell B Break-even execution level
  7 Cell C Heatmap: execution_mode × target_delta (holdout)
  8 Cell D Heatmap: dte_max × target_delta, colored by median Sharpe (holdout)
  9 Cell E Defensive leg roll comparison (same params, True vs False)
  10 Cell F Straddle (0.50Δ) vs Strangle comparison by execution mode
  11 Cell G Vol filter comparison by execution mode
  12 Cell H Stop loss comparison (2.0 vs 3.0)
  13 Cell I Train vs holdout scatter (Sharpe per config)
  14 Cell J DB coverage by period and mode
  15 Cell K Best config details (holdout) across all 3 execution modes
  Save results to data/B3/v6_grid_search_results.parquet.
  B.3 — Runtime optimization
  Use parallel workers (8 cores default in run_grid). If joblib import fails as before, fall back to sequential but warn user about estimated runtime. The notebook cell 4 should cache results so it's skippable on re-run.

---

Phase C: Update Report
Write docs/2026-05-15 - v6 final confirmation results.md incorporating:

1. Phase A reliability verification results (pass/fail table)
2. Phase B v6 expanded grid results
3. Straddle vs strangle comparison (what 0.50Δ looks like)
4. Re-affirmed or revised A/B/C/D conclusion
5. Best parameter combination identified from the broader grid

---

TODO: Part 4 — Fix complex number NaN guard
In src/straddle/engines.py, add a try/except around brentq in implied_volatility() to catch complex floats and return NaN. Already auto-filtered by iv < 2.0 check. Low priority.

---

TODO: Part 5 — Execute cleanup plan 011
Delete 22 files + 1 directory (aux/), untrack 20 from git. Full spec at .agent/plans/011 - cleanup and reorganization v2 post v4.md. Execute after v6 report is approved.

---

Definition of Done

- [ ] Current state committed
- [ ] A.1: single_position repro matches original (or replaces it)
- [ ] A.2: 3 manual trades verified to the cent
- [ ] A.3: SPY regression passes
- [ ] A.4: Synthetic vs market comparison passes
- [ ] A.5: Trade forensics lite complete
- [ ] A.6: American option sensitivity confirmed <1% impact
- [ ] A.7: All gates PASS
- [ ] B.1-B.3: v6 notebook created, grid executed (0 errors), saved to parquet
- [ ] All v6 notebook cells produce meaningful output
- [ ] C: Final report written with confirmed A/B/C/D conclusion
      Files
      File Action
      scripts/verify_single_position.py New — re-run single_position v5 grid
      data/B3/v5_grid_search_singlepos_fixed.parquet New — fixed single_position results
      research/2026-05-15 - B3 - v6 expanded grid.ipynb New — v6 notebook
      scripts/build_v6_notebook.py New — notebook generator (optional, can write inline)
      data/B3/v6_grid_search_results.parquet New — v6 grid results
      docs/2026-05-15 - v6 final confirmation results.md New — final report
      Deviations Allowed
- If Phase B runtime in sequential mode exceeds 3 hours, reduce one dimension (drop profit_target=0.25 or dte=60) and note the reduction
- If the straddle (0.50Δ) configs all fail with errors (complex number bug hitting at scale), drop them from the grid and note in report
- If A.1 shows the original single_position parquet was corrupted, use the fixed version for all comparisons and note the cache bug impact in the report
