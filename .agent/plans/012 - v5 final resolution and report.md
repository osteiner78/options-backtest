Plan 012 — v5 Final Resolution & Report
Date: 2026-05-14 | Target: Coding agent | Branch: b3-backtest
Context
The v5 confirmation notebook completed all 12 cells. Key results:
Mode Train median Sharpe Holdout median Sharpe (single_position)
bid_ask -0.17 +0.67
mid_minus_1tick +0.33 -0.21
mid +0.09 +0.20
mid_plus_1tick +0.09 +0.22
But the grid used single_position=True. The intended deployment mode is laddering (maximize capital utilization). Cell G re-ran the best config with laddering and got very different numbers:
Mode Laddering Sharpe N
bid_ask -0.03 165
mid_minus_1tick -0.37 173
mid +1.10 164
mid_plus_1tick +1.95 131
Goal: Resolve the single_position → laddering gap, diagnose the mid_minus_1tick anomaly, reach a final A/B/C/D conclusion, write the report.

---

Part 1: Close the laddering gap
The grid search (192 backtests) ran single_position only. We need laddering evidence at grid scale.
1.1 — Audit grid_search.py call chain
Read scripts/grid_search.py and answer:

- Does \_run_one() call run_backtest() or run_portfolio_backtest()?
- Which compute\_\* function extracts metrics?
- Is there an existing portfolio_mode parameter that could be set to "laddering"? If so, what would change?
  Document the exact call chain so the report knows what the grid numbers represent.
  1.2 — Add laddering support to grid search (if needed)
  If grid_search.py doesn't already support portfolio_mode="laddering", add it:
- Add "portfolio_mode" to GRID_DIMS in grid_search.py
- In \_run_one(), conditionally call run_portfolio_backtest() + compute_portfolio_metrics() when portfolio_mode == "laddering", otherwise run_backtest() + compute_metrics()
- Respective METRICS*KEYS must align (the two compute*\* functions return different dict keys — check and handle)
  1.3 — Re-run v5 grid in laddering mode
  Re-run the v5 grid with portfolio_mode="laddering":
  GRID = {
  "target_delta": [0.16, 0.20, 0.25],
  "dte_max": [30, 45],
  "profit_target_pct": [0.50],
  "manage_at_dte": [7, 14],
  "vix_filter": ["OFF", "rv_pct:80"],
  "defensive_leg_roll": [False],
  "stop_loss_pct": [3.0],
  "execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"],
  "portfolio_mode": ["laddering"],
  }
  RUNS = [
  ("train", "bova11", "2018-01-02", "2022-12-31"),
  ("holdout", "bova11", "2023-01-02", "2025-11-30"),
  ]

# 96 combos × 2 periods = 192 backtests

Save results to data/B3/v5_grid_search_laddering.parquet.
Expected runtime: similar to the original grid (~40 seconds). After completion, produce the same Cell B-style summary table (median Sharpe per execution mode) for the laddering grid. This is the definitive table for the report.
1.4 — Validate grid vs single backtest consistency
Pick the best laddering config from the new grid results. Re-run it as a standalone single backtest with laddering and confirm the Sharpe matches within tolerance. This validates the grid search itself is producing correct results for laddering mode.

---

Part 2: Diagnose mid_minus_1tick ordering anomaly
In both single_position and laddering, bid_ask Sharpe exceeds mid_minus_1tick, contradicting expected ordering: bid_ask < mid_minus_1tick < mid < mid_plus_1tick.
Hypotheses:

- (a) Selection bias: bid_ask requires bid > 0 on both legs. Entries where bid is missing tend to be worse days (wider spreads, higher vol). Excluding them removes the worst trades. Mid modes include these bad entries.
- (b) Small sample noise: n=24 per mode in grid. One outlier config could skew medians.
- (c) Tick penalty > bid discount: For 16Δ options with 40% median spread, mid - R$0.05 (one tick) might still be a worse price than the actual bid.
  2.1 — Trade count comparison
  From the new laddering grid results, compare mean n_trades per execution mode:
  for mode in modes:
  sub = df_laddering[df_laddering["execution_mode"] == mode]
  print(f" {mode:20s}: n_trades_mean={sub['n_trades'].mean():.0f}")
  If bid_ask has fewer trades, hypothesis (a) is supported.
  2.2 — Common-subset P&L analysis
  Run the best laddering config with ALL 4 execution modes as standalone backtests. Collect per-trade (entry_date, exit_date, pnl) for each mode. Find trades that exist in all 4 modes (same entry/exit dates). Compare mean P&L on this common subset:
  common = intersection of entry_dates across all 4 modes
  for mode in modes:
  print(f" {mode} common-trade mean P&L: {common[mode].mean():.1f}")
  If the ordering normalizes on the common subset (bid_ask < mid_minus1tick < mid < mid_plus1tick), hypothesis (a) is confirmed — it's selection bias, not a bug.
  2.3 — Entry credit comparison (if anomaly persists)
  If the ordering doesn't normalize on common subset, query the DB directly for the best config's entry dates. For each entry, compare the actual credit under each mode:
  entry_date put_strike call_strike bid mark bid_ask_credit mid_minus_1tick_credit mid_credit
  2023-01-15 ... ... 0.85 1.10 1.70 2.15 2.20
  Quantify: how often is bid > mark - tick? (i.e., how often does selling at bid give MORE credit than mid_minus1tick?) If frequently true, the mid_minus1tick mode is artificially penalized by the fixed tick adjustment on wide-spread contracts.
  2.4 — Document findings
  Add a section to the final report explaining:
- Whether the anomaly is selection bias, noise, or a real pricing dynamic
- Whether it invalidates any conclusions
- Whether bid_ask results should carry a "conditional on sufficient liquidity at entry" caveat

---

Part 3: Write Final Report
File: docs/2026-05-14 - v5 confirmation results.md
Base the conclusion on laddering results (Part 1.3 grid).
Report Structure

# B3 BOVA11 Short Strangle — v5 Confirmation Results

**Date:** 2026-05-14 | **Status:** Final

## 1. Research Question

Which conclusion does the data support?
A. VRP exists and is capturable even at bid_ask
B. VRP exists but is consumed by bid-ask spread  
C. VRP is marginal — positive at mid, negative at bid_ask
D. No capturable VRP — negative across all modes

## 2. Methodology

- Strategy, grid dimensions, periods, execution modes
- Engine: MarketEngine, CDI-based IVs, DB-aware expiration
- Key fixes: expiration mismatch, volume_filter removal
- Position mode: laddering (multiple concurrent positions, Reg-T margin)

## 3. Results — Laddering Grid [from Part 1.3]

### 3.1 Execution Sensitivity

[Median Sharpe table from laddering grid, 4 modes × 2 periods]

### 3.2 DB Coverage

[train 76%, holdout 99.6% — from Cell D]

### 3.3 Spread Cost Analysis

[40% median spread at 16Δ, 28% at 20-30Δ, 23% at 30-50Δ — from Cell F]

### 3.4 v3 vs v5 Reproduction

[v3 BOVA11 holdout median = -1.30, v5 laddering holdout median = ??? — from Cell E + Part 1.3]

### 3.5 Best Config

[Details + P&L stats across all 4 modes — from Cell G]

## 4. Issues & Caveats

### 4.1 Mid_minus_1tick ordering anomaly [from Part 2]

### 4.2 Period dependence: 2023 rescue effect

### 4.3 Train/holdout asymmetry (train negative, holdout positive)

### 4.4 Complex number bug (524 errors, edge configs only, low priority)

### 4.5 American exercise risk (34% of CALLs are AMER, not modeled)

## 5. Conclusion

**[A/B/C/D — determined by laddering grid results]**
[One-paragraph justification citing key evidence]

## 6. Appendices

- Data files, notebook, DB
  Fill-in logic for conclusion section:
  Based on laddering grid results (Part 1.3), choose the conclusion letter:
  bid_ask median mid median Conclusion Text
  > 0 >0 A VRP exists and is capturable even at bid_ask
  > ≤0 >0 B VRP exists but consumed by spread at bid_ask; capturable at mid+
  > ≤0 ≤0 C VRP marginal — positive at mid_plus_1tick, negative otherwise
  > — — D Insufficient data (only if grid fails)
  > Based on Cell G's laddering re-run, the likely answer is B, but wait for Part 1.3 grid results to confirm.

---

TODO: Part 4 — Fix complex number bug
Priority: Low (doesn't affect v5, only affects delta≥0.3 + dte≥60 edge configs)
524 errors in v3 grid. Likely cause: brentq IV solver produces complex numbers for deep ITM options with B3's high rates. Fix: add NaN guard in implied_volatility() in engines.py. The engine already filters implied_volatility < 2.0, so NaN results are naturally skipped.

---

TODO: Part 5 — Execute cleanup plan 011
Delete 22 files + 1 directory (aux/), untrack 20 files from git, keep 30 active files. Full spec at .agent/plans/011 - cleanup and reorganization v2 post v4.md. Execute only after report is written and approved.

---

Definition of Done

- [ ] Part 1.1: Grid search call chain documented
- [ ] Part 1.2: Laddering support added to grid_search.py (if needed)
- [ ] Part 1.3: Laddering grid re-run (192 backtests), saved to v5_grid_search_laddering.parquet
- [ ] Part 1.4: Best laddering config validated against standalone re-run
- [ ] Part 2.1: Trade count comparison across modes
- [ ] Part 2.2: Common-subset P&L analysis
- [ ] Part 2.3: Entry credit comparison (only if anomaly persists after 2.2)
- [ ] Part 2.4: Anomaly findings documented
- [ ] Part 3: docs/2026-05-14 - v5 confirmation results.md written
- [ ] Conclusion letter (A/B/C/D) presented and approved by user
      Files
      File Action
      scripts/grid_search.py Modify — add laddering support if absent
      scripts/verify_position_mode.py New — single_position vs laddering sanity check script
      data/B3/v5_grid_search_laddering.parquet New — laddering grid results
      docs/2026-05-14 - v5 confirmation results.md New — final report
      Deviations Allowed
- If grid_search.py already supports portfolio_mode="laddering", skip Part 1.2
- If the mid_minus_1tick anomaly disappears on common-subset P&L comparison (Part 2.2), skip Part 2.3 and document it as "selection bias confirmed"
- If the laddering grid fails to run (>10% errors), fall back to using Cell G + top-5/bottom-5 validation and note the limitation in the report
