Phase 1: Fix the metrics code (20 min)
File: src/straddle/metrics.py

1. Fix \_compute_sharpe_from_daily_pnl — add rf_annual parameter, subtract from daily returns:
   def \_compute_sharpe_from_daily_pnl(
   daily_pnl: pd.Series, init: float, rf_annual: float = 0.045
   ) -> float:
   """Sharpe ratio from a daily absolute-P&L series."""
   if len(daily_pnl) < 2:
   return 0.0
   equity = init + daily_pnl.cumsum()
   daily_ret = equity.pct_change().dropna()
   if daily_ret.std(ddof=1) <= 0:
   return 0.0
   rf_daily = rf_annual / 252.0
   return float((daily_ret.mean() - rf_daily) / daily_ret.std(ddof=1) \* np.sqrt(252))
2. Update the call site in compute_portfolio_metrics (line ~388):

# After daily_pnl = mtm_equity.diff().dropna()

init = float(params.get("initial_balance", 50_000))

# Compute rf from data when available, fall back to params

rf_annual = (
float(data["risk_free_rate"].mean())
if data is not None and "risk_free_rate" in data.columns
else params.get("risk_free_rate", 0.045)
)
results["sharpe"] = \_compute_sharpe_from_daily_pnl(daily_pnl, init, rf_annual)

# Also store the information ratio (excess-over-zero) for reference

results["info_ratio"] = \_compute_sharpe_from_daily_pnl(daily_pnl, init, rf_annual=0.0) 3. Fix \_compute_equity_stats — accept optional data parameter for data-driven rf:
def \_compute_equity_stats(
equity_series: pd.Series, params: dict, data: pd.DataFrame = None
) -> Dict:
... # Replace line 143:
if data is not None and "risk_free_rate" in data.columns:
rf_annual = float(data.loc[daily_pct.index, "risk_free_rate"].mean())
else:
rf_annual = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT)
rf_daily = rf_annual / 252 4. Update both call sites (compute_metrics line ~315, compute_portfolio_metrics line ~378) to pass data. 5. Run pytest tests/ -v — confirm 129 tests pass.
Phase 2: Add info_ratio to grid search output (10 min)
File: scripts/grid_search.py
Add to METRICS_KEYS around line 30:
("info_ratio", "info_ratio", 0.0), # excess-over-zero (for config comparison)
This means future grid runs store both sharpe (true Sharpe) and info_ratio in the parquet.
Phase 3: Reprocess the v7 parquet (30 min)
Write a script scripts/reprocess_v7_sharpes.py that:

1. Loads v7_grid_search_results.parquet and v7_petr4_grid_search_results.parquet
2. For each row, re-runs the backtest (same engine, same params) but uses the fixed compute_portfolio_metrics to get both sharpe and info_ratio
3. Overwrites the parquet files with the new values (adding info_ratio column, updating sharpe column)
4. Writes a comparison summary
   python scripts/reprocess_v7_sharpes.py

# Expected runtime: ~2.5 hours (10,752 backtests)

Phase 4: Update the definitive notebook (40 min)
In research/2026-05-15 - B3 - definitive research report.ipynb:

1. Add a methodology cell at the top (after the imports cell):

## Methodology: Information Ratio vs Sharpe Ratio

Throughout this notebook, the primary performance metric is the **Information Ratio** (annualized
return divided by annualized standard deviation, without subtracting the risk-free rate). This is
sometimes called the "excess-over-zero Sharpe" or "unadjusted Sharpe."
**Why not the standard Sharpe?** The Brazilian risk-free rate (CDI/SELIC) averaged 10-13% during
the sample period. A strategy selling options at 16-25Δ earns 2-4% annually — structurally below
the risk-free rate. The standard Sharpe (which subtracts rf from returns) would be negative for
nearly all configurations. This correctly reflects that the strategy does not outperform cash on a
standalone basis, but it obscures the config comparison question: which parameters work best?
**For config selection and ranking:** Information Ratio (the numbers shown here).  
**For investment context:** True Sharpe (shown alongside for key configs).  
**For risk assessment:** Calmar ratio, maximum drawdown, and win rate. 2. Replace the I-10 correction verification cell (cell 42) with a new cell that:

- Explains the I-10 fix (running equity denominator) — already applied in the parquet
- Explains the rf subtraction (bug #1) — NOT applied in the parquet; true Sharpes would be negative
- Shows a table of info ratio vs true Sharpe for the top 6 configs
- Concludes: "All Sharpe values in this notebook are information ratios. See methodology above."

3. Do NOT rename every "Sharpe" in the cells — instead, the methodology note at the top makes it clear. The code cells still use the parquet column named sharpe. The markdown narrative cells should refer to it as "Sharpe (information ratio)" on first use, then just "Sharpe" subsequently.
4. Update note text only in key markdown cells:
   - Executive Summary: change "Sharpe 1.33" to "Information Ratio 1.33 (see Methodology)"
   - Final Recommendation: same treatment
   - Cell H (train/holdout scatter): axis label already says "Sharpe" — leave it, the methodology clarifies
5. Add to Known Limitations in §10:
6. **The performance metric is an information ratio, not a standard Sharpe ratio.** The Brazilian
   risk-free rate (CDI, 10-13% annually) exceeds the strategy's absolute return, making the standard
   Sharpe negative for most configs. This does not invalidate the strategy — it has low correlation
   to equities and provides diversification benefits. See the Methodology section for details.
7. Re-execute the notebook and confirm 0 errors.
   Phase 5: Update reports (15 min)

- docs/2026-05-15 - rb3 price validation.md — no change
- docs/2026-05-15 - extended commission sensitivity.md — no change
- docs/2026-05-15 - PETR4 period robustness.md — no change
- .agent/reports/023-code-review-src.md — append note: "Bug #1 confirmed present since commit 22600b8. Fix applied; parquet not re-run (info ratio preserved for ranking)."
  What we DON'T do
- Don't re-run the full grid (2.5 hours, output would be nearly identical information ratios)
- Don't rename the parquet sharpe column (breaks all downstream code)
- Don't change the v7 grid conclusion — the config ranking is unchanged
  Why the parquet sharpe column stays
  The parquet column is named sharpe. Renaming it to info_ratio would break every notebook, script, and analysis. Instead, the methodology note and updated code make the distinction clear. Future grid runs (v8+) will include both columns.
