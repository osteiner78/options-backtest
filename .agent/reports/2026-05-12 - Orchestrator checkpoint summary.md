# Project Summary — B3 Short Options Backtest Research

## 1. The Objective

You adapted a **short strangle strategy** that was already working on the S&P 500 (SPY) to test whether it could work on Brazilian B3 equity options, specifically on **BOVA11** (the Brazilian broad market ETF, equivalent to SPY) and **PETR4** (Petrobras preferred shares, Brazil's most liquid single-stock options name).

The underlying hypothesis is that **Brazil has a structural volatility risk premium (VRP)**: implied volatility systematically exceeds realized volatility, meaning option sellers should earn positive expected value over time. This is documented in the academic literature. The tastytrade-style short strangle at 16Δ / 45 DTE / 50% profit target was the implementation vehicle.

---

## 2. The Strategy (Baseline Parameters)

The starting configuration, ported from the SPY backtest:

- **Delta target:** 0.16 (sell 16Δ puts and calls)
- **DTE window:** 30–45 days to expiration at entry
- **Profit target:** 50% of initial credit
- **Management:** Roll at 21 DTE if not profitable
- **Defensive rolls:** Off (initially)
- **VIX entry filter:** ≤35 (using US VIX as proxy for Brazilian vol regime)
- **Stop loss:** None (tastytrade approach)
- **Max BPR:** 30%

---

## 3. The Research Arc

### Session 1 — Initial Results and Reality Check

**First results were negative.** Both BOVA11 and PETR4 showed losses with the baseline parameters over 2020–2025. You asked whether to throw the towel or continue.

**Why it looked paradoxical:** Brazil has the VRP, yet the strategy was losing. The diagnosis was:

- At 16Δ, you're deep in the OTM tail where the B3 vol skew is very steep — implied vol at those strikes already prices in a significant jump premium
- B3 options at 16Δ collect only 0.85–1.2% of spot (vs SPY's 1.5–2.0%), and bid-ask spreads consume 20–30% of that premium
- PETR4's "normal" IV is already 35–50%, so a 10–15% underlying move in 30 days is not a 16Δ event in practice
- The VIX filter (calibrated for SPX) does nothing useful on B3 where normal IV already exceeds 35

**Claude Code manually verified 4 trades** (2 BOVA11, 2 PETR4) to the cent, confirming the pricing pipeline is correct. The losses are genuine market behavior, not bugs.

**Decision:** Don't abandon, but recalibrate — run a grid search to find whether any parameter combination works.

### Session 2 — Grid Search v1 (Fatally Flawed)

Designed and ran a 6-dimension grid: `target_delta × dte_max × profit_target_pct × manage_at_dte × vix_filter × defensive_leg_roll`. 504 valid combinations × 4 (market × period) = 2,016 runs.

**Critical bug discovered:** The Sharpe being optimized was **dominated by buy-and-hold underlying exposure**, not the strangle strategy. With `cash_mode=UNDERLYING`, idle capital earns the underlying return, so the portfolio return matched the underlying B&H return almost exactly (BOVA11: portfolio +92.6% vs underlying +93.0%). Every Sharpe cell was ~1.03–1.06 — completely flat, because it was measuring the underlying's Sharpe with noise from the strangle overlay.

The heatmaps showed no gradients; the optimization was meaningless.

### Session 3 — Grid Search v2 (Fixed Metric)

Re-ran with `cash_mode=RISK_FREE` and `yield=0%` so the metric measures **pure strangle P&L** in isolation. Added `alpha_vs_bh` and `alpha_sharpe` columns.

**Key v2 findings** (now real, not contaminated by B&H):

| Market | Period  | Strangle Sharpe (mean) | Range          |
| ------ | ------- | ---------------------- | -------------- |
| BOVA11 | Train   | −0.23                  | −4.28 to +0.47 |
| BOVA11 | Holdout | −1.09                  | −3.30 to −0.09 |
| PETR4  | Train   | −5.07                  | −19.4 to −0.70 |
| PETR4  | Holdout | −3.19                  | −20.6 to +0.42 |

**Settled findings:**

- **PETR4:** Uniformly negative across all 504 configurations. Drop this — it's a structural problem, not a parameter problem
- **BOVA11:** Small positive ridge exists at high delta (0.30) + long DTE (45) + high profit target (75%) + VIX=OFF + no defensive rolls. Best train Sharpe: +0.47
- **Higher profit target wins:** 75% >> 50% >> 25%. On B3, exiting at 50% leaves too much premium and racks up commissions
- **Higher delta wins:** 0.30 dominates 0.20 across both markets. Thin wings don't pay enough
- **VIX filter "OFF" wins consistently:** US VIX is the wrong regime variable for B3
- **Defensive leg rolls hurt everywhere:** All top-10 configurations have `defensive_leg_roll=False`

**Note on Sharpe magnitudes:** Discovered the metric is still unreliable due to the **daily MTM bug** — with cash_mode=RISK_FREE, daily P&L is zero on non-trade days, compressing the standard deviation and producing extreme Sharpe values (PETR4 reaching −20). Rank ordering is informative but absolute values are not.

### Session 4 — Diagnostic Prompts (v3 Results)

Two focused investigations were run by Claude Code:

**Chain diagnostics (Prompt #5):**

- Confirmed chains are NOT collapsed — each roll creates a separate trade entry
- `n_trades = n_chains + n_rolls_total` (verified: 242 = 102 + 140)
- PETR4's 700–1000 "trades" = ~250-350 root chains + 450-650 rolls — legitimate, not double-counting
- **Implication:** Minimum trade filter should use `n_chains ≥ 50` not `n_trades ≥ 100`

**Defensive roll investigation (Prompt #6):**

- Implementation is **correct** — no bugs, no inverted strangles, trigger guard works
- 78 matched pairs (defensive=True vs False on same entry dates)
- **68% of pairs worse with defensive rolls enabled** (53/78)
- **Mean P&L drag: −R$11.18 per matched pair**
- **Root cause:** Trigger is too late — by the time EOD delta exceeds 0.30, observed values were 0.47–0.72. The underlying has already moved. The roll then closes the winning OTM leg early (paying ask) and opens a new leg closer to ATM (collecting bid), which gets tested next
- **Trigger rate: 92%** (231/251 trades) — on B3, defensive rolls are essentially default behavior, not an emergency response
- **This is a real B3 vs SPY finding:** B3's high vol and trending behavior makes the tastytrade defensive roll counterproductive

### Session 5 — Data Quality Investigation

After the grid searches, attention shifted to validating the underlying data source. You discovered that `b3_options.db` (your original COTAHIST-built database) had **corrupted prices**:

- Max price error: **R$499,997** (options worth R$3-7 showing as R$500,001)
- Only 55% of rows match rb3's parsed values within R$0.01
- Only 47% of IVs match within 2 vol points

The well-matched rows (168k) showed exact price agreement, confirming the parser is correct when source data is clean. The corruption came from B3's COTAHIST feed itself (~5 records with extreme values).

**Decision:** Migrate to rb3 (R package) as the source of truth.

### Session 6 — rb3 Migration (completed by Claude Code)

The coding assistant executed the migration plan:

- Fetched COTAHIST options data via rb3 R package (2017–2025)
- Built `b3_options_rb3.db` (1,416,520 rows, schema-identical to original)
- Ran 7 automated quality tests — all passed except minor benign failures (half-days, deep ITM edge cases)
- Ran sanity backtest: old DB vs rb3 DB for 2024 H1
  - **100% DB hit rate** on both
  - PETR4: nearly identical results (+R$46 vs +R$47) despite different trade paths — confirms data parity
  - BOVA11: +R$97 vs +R$227 — diverges on one roll chain from Jan 2024 entry

Engine now pointed at `b3_options_rb3.db`. Grid search results from Sessions 2–4 used the **old corrupted DB** — they need to be re-run once the engine bugs are fixed.

---

## 4. Known Bugs / Issues to Fix (Current State)

Ranked by priority:

| #   | Issue                                                                                     | Status              | Blocker?                      |
| --- | ----------------------------------------------------------------------------------------- | ------------------- | ----------------------------- |
| 1   | **Daily MTM Sharpe inflation** — P&L spread over holding days, not true daily MTM         | Not fixed           | Blocks risk-adjusted analysis |
| 2   | **Flat r=12% for IV calculation** — should use daily CDI from backtest parquets           | Not fixed           | ~0.5 vol point precision gap  |
| 3   | **Defensive leg roll not implemented** — strategy uses `defensive_leg_roll_enabled=False` | By design (finding) | No                            |
| 4   | **Single-position enforcement** — rolled trades may overlap next monthly entry            | Suspected           | Medium                        |
| 5   | **Grid search used old corrupted DB** — all v1/v2/v3 results need to be re-run on rb3 DB  | Pending             | Strategy conclusions          |
| 6   | **VIX filter is wrong for B3** — needs B3-native vol filter (IVR or IBOV RV percentile)   | Not implemented     | Next grid iteration           |

---

## 5. What the Research Has Established

**High confidence (settled):**

- PETR4 short strangles are unprofitable across all tested parameter combinations — structural, not fixable by parameter tuning
- Defensive leg rolls hurt on B3 — real finding, not a bug
- Higher profit target (75%) beats tastytrade's canonical 50% on B3
- Higher delta (0.30Δ) beats 0.16Δ — thin wings don't pay enough on B3
- VIX filter is the wrong regime variable for Brazilian markets

**Medium confidence (needs clean data + fixed Sharpe):**

- BOVA11 has a small positive ridge at high-Δ + long-DTE + high-profit-target
- This ridge may survive on clean data (rb3 DB) with fixed Sharpe calculation

**Unknown / pending:**

- Whether BOVA11 edge survives real-world execution costs
- Whether B3-native vol filter (IVR) changes the BOVA11 picture materially
- Whether the grid search results change meaningfully on rb3 DB vs corrupted old DB

---

## 6. Current Implementation Plan (in progress)

The coding agent is now executing the 5-phase plan from the migration follow-up:

- **Phase 1:** Full-period regression 2017–2025 on both old and rb3 DB (blocker — confirms or rejects data parity for long-term results)
- **Phase 2:** Fix Sharpe inflation bug (true daily MTM)
- **Phase 3:** Replace flat r=12% with daily CDI rates (already available in backtest parquets)
- **Phase 4:** Harden quality test suite (put-call parity, term structure, Bloomberg spot-check)
- **Phase 5:** Strategy improvements (defensive roll, single-position enforcement, new grid search)

The definitive grid search — using rb3 data, fixed Sharpe, daily CDI, B3-native vol filter, post-COVID train/holdout split (train: 2020-04 to 2023-12, holdout: 2024-01 to 2025-12) — has not yet been run. That is the next major milestone.

---

## 7. Key Technical Architecture (for context)

- **Engine:** `MarketEngine` queries `b3_options_rb3.db` for real chain data; falls back to `SyntheticEngine` (BSM + parametric skew) when DB row missing
- **Data pipeline:** Parquet files (OHLC + VIX proxy + CDI) drive the day loop; SQLite DB provides option chains
- **Strike selection:** `ORDER BY ABS(delta - target) ASC LIMIT 1` — closest to target delta on entry day
- **Daily MTM:** Currently using realized cash flows, not true mark-to-market (the bug)
- **Train/holdout in grid:** Previous runs used 2017-2019 train (BOVA11) and 2011-2019 train (PETR4), which are different regimes — the definitive run will use the post-COVID symmetric split

---

## 8. Where You Are Right Now

The coding agent is running the 5-phase plan. When it finishes:

1. **Check Phase 1 output** — does the full-period regression confirm rb3 data parity? If BOVA11 shows >15% P&L divergence vs old DB, investigate before proceeding
2. **Check Sharpe fix** — does the new Sharpe produce values in −2 to +2 range for BOVA11? If PETR4 still shows extreme values, the fix may not be complete
3. **Then:** Re-run the full grid search with all fixes in place and the post-COVID split — that's the definitive research result you've been building toward

The most important open question is: **after a clean grid search with real data and fixed Sharpe, does the BOVA11 positive ridge survive?** If yes, you have a viable strategy to investigate further. If no, the VRP on B3 doesn't survive transaction costs at retail scale, and the research conclusion is "don't trade short strangles on B3."
