Plan 015 — Post-v7 Follow-up Investigations
Date: 2026-05-15 | Target: Coding agent | Branch: b3-backtest

Context
v7 is complete and the report is written. Five follow-up items were identified in the post-v7 review:

1. The force-close P&L fix was committed AFTER the v7 grid and commission sensitivity runs ran — those results may have minutely wrong P&L for force-closed trades.
2. The recommended 25Δ config leaves material edge on the table vs 16Δ — 16Δ needs a targeted deep-dive as a practical compromise.
3. Six rows share identical Sharpe=11.557057 to 6 decimal places — benign (non-differentiating parameters), but should be documented.
4. PETR4 has 8+ years of DB data and the engine fixes may change the prior "not profitable" conclusion.
5. No stress-scenario analysis has been done — the worst continuous 6-month window could reveal hidden tail risk.

---

Phase 1: Force-close P&L Fix — Impact Assessment

The fix (7aa889e) moved force-close P&L from always-0.00 to computed from net_credit - close_cost. This commit came after:
- Phase 3: v7 refined grid (06c71d2) — 5,376 backtests
- Phase 4: Commission sensitivity (ecedbd9) — 90 backtests
But before:
- Phase 6: Period robustness (fe273d8) — 225 backtests

Step 1.1 — Quantify materiality
Run the recommended 25Δ config standalone with the fix applied. Count force-closed trades and their P&L contribution. The v6 report showed 3 of 118 trades (2.5%) were force-closed.

Action:
```python
params = dict(PARAMS)
apply_market_preset(params, "bova11")
params.update({
    "mode": "market", "start_date": "2023-01-02", "end_date": "2025-11-30",
    "target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50,
    "manage_at_dte": 14, "vix_filter": "OFF",
    "stop_loss_pct": 2.0, "execution_mode": "mid",
    "portfolio_mode": "laddering",
})
data = load_market_data("2023-01-02", "2025-11-30", market="bova11")
engine = make_engine(params)
trades, eq = run_portfolio_backtest(data, params, engine)
# Report: n_force_closed, % of total trades, total P&L from force-closed trades
```

Step 1.2 — Decision gate
- If force-closed trades are <5% of total AND their P&L contribution <2%: document and move on. No re-run needed.
- If force-closed trades are >5%: re-run the v7 grid with the fix. Also re-run commission sensitivity runs.

---

Phase 2: 16Δ Compromise Deep-dive

The grid shows 16Δ offers median holdout Sharpe ~0.44 at mid (vs 0.50 for 25Δ) but the best 16Δ configs reach Sharpe 1.88. The gap between 16Δ and 25Δ in the top configs is meaningful. The concern is execution: 16Δ strikes may be harder to fill at mid than 25Δ.

Step 2.1 — Select and run best 16Δ config
From v7 Cell K (stability rank), best 16Δ mid config:
```
target_delta: 0.16, dte_max: 21, profit_target_pct: 0.50,
manage_at_dte: 14, vix_filter: rv_pct:70 or rv_pct:80,
stop_loss_pct: 3.0, execution_mode: mid
```
Run standalone in train + holdout. Save full trade list to CSV.

Step 2.2 — Liquidity check
For every 16Δ trade in holdout, query DB for entry-day bid/ask/mark on both legs. Compute spread/mark per leg and (spread × 100) / premium_received. Compare against 25Δ config's spread ratios. Key metric: what fraction of 16Δ entries have spread/mark > 30%?

Step 2.3 — Manual P&L verification (5 trades)
Pick 2 PROFIT, 1 ROLLED, 1 21DTE, 1 FORCE_CLOSE. Verify against DB marks within R$0.01.

Step 2.4 — Compare equity curves and metrics
Side-by-side 16Δ vs 25Δ: Sharpe, total_return, max_drawdown, win_rate, calmar, n_trades, avg_premium, avg_hold_days. Overlay equity curves.

Step 2.5 — Commission sensitivity for 16Δ
Test at baseline, 2×, 3× commission. Does it survive?

Step 2.6 — Verdict
Is 16Δ practicably tradable at mid? What is the expected Sharpe degradation if 30% of fills happen at bid instead of mid?

Decision gate: if 16Δ spread/mark > 35% on average, recommend against and skip equity curve comparison — the strikes are too illiquid.

---

Phase 3: Document Identical Sharpe Rows

The v7 grid has 6 rows with identical values to 6 decimal places (Sharpe=11.557057, n_trades=90, total_return=0.04472, max_drawdown=-0.000691) for configs with {manage_at_dte ∈ {5,7,14}} × {stop_loss_pct ∈ {2.0,3.0}} at 12δ/dte30/pt25%/rv_pct:80/mid_plus_1tick. Not a bug — all trades exit at profit_target before reaching manage_at_dte or stop_loss.

Step 3.1 — Quantify degeneracy across the full v7 grid
For each (target_delta, dte_max, profit_target_pct, vix_filter, execution_mode) tuple, count unique result rows across manage_at_dte × stop_loss_pct = 8 combinations. Report what fraction of grid cells are degenerate.

Step 3.2 — Add Cell L to v7 notebook
Explain the degeneracy with a summary table. Note that manage_at_dte and stop_loss_pct become redundant when profit_target is tight relative to DTE and delta.

---

Phase 4: PETR4 Analysis

PETR4 DB: 961,869 rows, 2,231 trading days (2017-01-02 to 2025-12-23). Engine fixes from Phase 0 may change the prior "not profitable" conclusion.

Step 4.1 — Quick pilot
Run 3 best BOVA11 configs × 3 execution modes × 2 periods = 18 backtests:
```
configs = [
    {"target_delta": 0.25, "dte_max": 21, "profit_target_pct": 0.50, "manage_at_dte": 14, "vix_filter": "OFF"},
    {"target_delta": 0.20, "dte_max": 21, "profit_target_pct": 0.50, "manage_at_dte": 14, "vix_filter": "rv_pct:80"},
    {"target_delta": 0.16, "dte_max": 21, "profit_target_pct": 0.50, "manage_at_dte": 14, "vix_filter": "rv_pct:70"},
]
```
Train: 2018-2022, Holdout: 2023-2025. Report median Sharpe per execution mode.

Step 4.2 — Decision gate
- If mid holdout median > 0: run full v7 grid (2,688 combos × 2 periods = 5,376 backtests).
- If bid_ask ≤ -0.50 AND mid ≤ -0.20 AND mid_plus_1tick ≤ 0.10: skip full grid, document that PETR4 VRP is not capturable even with fixes.

Step 4.3 — Full PETR4 grid (if pilot positive)
Same grid spec as BOVA11 v7. Save to `data/B3/v7_petr4_grid_search_results.parquet`. Notebook: `research/2026-05-15 - B3 - v7 PETR4 grid.ipynb`.

Step 4.4 — PETR4-specific considerations
- PETR4 is a stock, not ETF → dividend yield. B3 preset sets `dividend_yield=0.0` — verify appropriateness.
- American exercise: BAW pricing enabled. The v6 report showed ΔSharpe=0 for BOVA11 (ETF), but PETR4 puts may have meaningful early exercise value. Flag divergence.
- Single-stock vs index vol premium may differ meaningfully.

---

Phase 5: Max-Drawdown Stress Scenarios

3-year Sharpe masks potential catastrophic 6-month windows.

Step 5.1 — Worst 6-month rolling windows
For recommended 25Δ (mid), 16Δ (mid), and 12Δ (mid_plus_1tick):
- Compute 6-month (120-trading-day) rolling P&L windows
- Report worst 3 windows by total P&L and return
- Compute max intra-window MTM drawdown

Step 5.2 — Gap-event stress
Find all dates where MTM equity dropped >5% in a single day. For each:
- Which configs held open positions?
- Was it a gap-through (stop couldn't prevent)?
- Actual P&L vs overshoot-model estimate

Step 5.3 — Report
Table: worst 3 six-month windows per config with P&L, return, max intra-window MTM drawdown.

---

Definition of Done

- [ ] Phase 1: Force-close materiality quantified; re-run needed? documented
- [ ] Phase 2: 16Δ standalone run, liquidity check, 5 trades verified, equity curve vs 25Δ
- [ ] Phase 3: Degeneracy quantified, Cell L added to v7 notebook
- [ ] Phase 4: PETR4 pilot (18 backtests); full grid if pilot positive
- [ ] Phase 5: Worst 6-month windows + gap-event stress, reported

---

Files

| File | Action |
|------|--------|
| `.agent/reports/017 - post-v7 follow-up results.md` | New — consolidated follow-up report |
| `research/2026-05-15 - B3 - v7 refined grid.ipynb` | Edit — add Cell L (degeneracy) |
| `research/2026-05-15 - B3 - v7 PETR4 grid.ipynb` | New — PETR4 grid notebook (if pilot positive) |
| `data/B3/v7_petr4_grid_search_results.parquet` | New — PETR4 grid results (if pilot positive) |
| `data/B3/v7_16delta_deep_dive.csv` | New — full trade list for 16Δ config |
| `data/B3/v7_stress_scenarios.csv` | New — worst 6-month window results |

---

Deviations Allowed

- Phase 4 full grid: if runtime exceeds 3 hours, reduce dte_max to [21, 30, 45].
- Phase 2: if 16Δ spread/mark > 35% on average, skip equity curve comparison and recommend against 16Δ.
- Phase 4 pilot: if severely negative, skip full grid — PETR4 VRP is not capturable.
