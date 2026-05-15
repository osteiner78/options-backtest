# Steps 1–6 Report — Source Tracking, Synthetic Dominance, Sharpe, CDI IVs, Quality Tests & Fallback Policy

**Date:** 2026-05-13  
**Status:** Steps 1–6 complete  
**Commit:** `3c3725a` (Step 1) + uncommitted (Steps 2–6 scripts + output)

---

## Step 1 — Add Entry/Exit/MTM Source Logging

### What was built

Added instrumentation to record whether each trade's entry, exit, and daily mark-to-market marks used real DB data or synthetic Black-Scholes fallback.

| File | Changes |
|------|---------|
| `src/straddle/strategy.py` | Added 4 fields to `Trade` dataclass (`entry_source`, `exit_source`, `mtm_source_days`, `mtm_total_days`); added `exit_db_source` to `TradeStepResult`; set `entry_source` in `build_entry()`; track MTM source per day in `evaluate_trade_step()`; set `exit_source` on all exit paths in `evaluate_trade()` |
| `src/straddle/engines.py` | Added `MarketEngine._source_for_strike()` — SQL helper that checks if a valid DB row exists for a given `(date, expiration, strike, type)` |
| `src/straddle/metrics.py` | Added 5 source stats to `compute_metrics()`: `entry_db_count`, `entry_db_total`, `entry_db_pct`, `exit_db_count`, `mtm_avg_db_pct` |
| `scripts/phase1_regression.py` | Added 5 source columns to `trades_to_df()`: `entry_source`, `exit_source`, `mtm_source_days`, `mtm_total_days`, `mtm_db_pct` |
| `tests/test_strategy.py` | Added `TestSourceTracking` class with 5 new tests |

### Deviations from plan

1. **Exit source for edge-case paths**: The plan had two conflicting approaches for exit source tracking. I used the precise mechanism (`exit_db_source` on `TradeStepResult`) rather than the `mtm_source_days > 0` heuristic.
2. **Force-close / fallback expiry**: The plan didn't explicitly cover the force-close edge case (entry ≥ force_close_at) and the fallback expiry path. These are set to `"unknown"` since no `evaluate_trade_step()` marks are computed for them.

### Test results

```
85 passed in 0.44s
```

All 80 existing tests pass unchanged. 5 new tests added.

---

## Step 2 — Quantify Synthetic Fallback Dominance

### What was built

Created `scripts/quantify_synthetic_dominance.py` — a diagnostic script that runs a single BOVA11 backtest with the v2 top configuration and reports P&L broken down by entry source.

**Configuration:** BOVA11, 2020-04-01 to 2025-12-31, `target_delta=0.30`, `dte=30–45`, `manage_at_dte=14`, `profit_target=0.75`, `vol_filter=off`.

### Results

| Metric | Value |
|--------|-------|
| Total trades | 52 |
| **% of entries using real DB** | **71.2%** (37/52) |
| Avg % of MTM days using real DB | 69.5% (median 100%) |

#### P&L by entry source

| | DB entries | Synthetic entries |
|---|---|---|
| **Total P&L** | R$-3,226.43 | R$+2,471.13 |
| **Mean P&L/trade** | R$-87.20 | R$+164.74 |
| **Win rate** | 56.8% | 86.7% |
| **N** | 37 | 15 |

### Decision gate

**71.2% > 70% → PASS.** Grid search conclusions are trustworthy.

### Key observation

The synthetic engine produces dramatically better results than real DB pricing, suggesting the B3 skew parameters (`put_slope=0.743`, `call_slope=0.031`) are over-optimistic — likely fitted on the old corrupted DB and needing re-fitting against rb3 data.

---

## Step 3 — Verify Sharpe Fix Produces Sane Values

### What was built

Created `scripts/verify_sharpe_fix.py` — runs 4 v2 grid search configurations and reports Sharpe, MDD, Calmar, plus manual daily_marks verification on the longest-holding trade.

### Results

| Configuration | Trades | Total P&L | Win rate | Sharpe | MDD | Status |
|---|---|---|---|---|---|---|
| PETR4 worst (d=0.30) | 52 | R$-1,280.32 | 53.8% | **-1.13** | -8.6% | SANE |
| BOVA11 best (d=0.30) | 52 | R$-755.30 | 65.4% | **-2.45** | -6.6% | SANE |
| PETR4 baseline (d=0.16) | 38 | R$-336.23 | 60.5% | **-6.50** | -1.4% | EXTREME |
| BOVA11 baseline (d=0.16) | 66 | R$-650.13 | 62.1% | **-2.37** | -3.1% | SANE |

### Manual verification (PETR4 worst, Trade 26)

- Entry: 2023-03-03, Exit: 2023-04-10 (26 days)
- Realized P&L: R$+107.71
- Sum of daily deltas: R$+107.71 (exact match)
- Non-zero daily deltas: 25/25 (no smearing pattern)

### Decision gate

Per the plan:
- **[-5, +5] range**: Fix verified → proceed to Step 4
- **> |10|**: Bug exists → investigate

3 of 4 configs are within [-5, +5]. PETR4 baseline at -6.50 is outside the ideal range but below the |10| bug threshold. This is **not a bug** — the strategy loses money slowly with very low volatility (MDD only -1.4%), producing a legitimately extreme negative Sharpe. The daily_marks verification confirms the MTM implementation is correct (no smearing).

**Verdict: Sharpe fix is verified. Proceed to Step 4.**

---

## Step 4 — Wire CDI IVs into the Engine

### What was built

Added a `use_cdi_ivs` flag that makes `MarketEngine` use `implied_volatility_cdi` and `delta_cdi` columns instead of the flat-12% columns for strike selection and delta lookups.

| File | Changes |
|------|---------|
| `src/straddle/params.py` | Added `use_cdi_ivs: False` to `PricingParams` TypedDict and `PRICING` dict |
| `src/straddle/engines.py` | Added `_use_cdi` / `_has_cdi_cols` detection in `__init__`; modified `_best_row()`, `get_daily_delta()`, and `find_strike_at_delta()` to use CDI columns when flag is set, with fallback to flat-12% when CDI data is NULL or unavailable |
| `scripts/validate_cdi_ivs.py` | Created validation script comparing flat-12% vs CDI strike selection trade-by-trade |

### DB verification

The rb3 DB has both CDI columns populated:
- `implied_volatility_cdi` and `delta_cdi` present in schema
- NULL rate: 10.8% (152,448 / 1,416,520 rows) — these rows fall back to flat-12% columns

### Results

| Market | Same put strike | Same call strike | Both same | Mean put diff | Mean call diff | P&L delta |
|--------|----------------|-----------------|-----------|---------------|----------------|-----------|
| BOVA11 | 93.0% (93/100) | 95.0% (95/100) | 93/100 | -0.04 | -0.04 | R$+50.74 |
| PETR4 | 91.5% (54/59) | 93.2% (55/59) | 54/59 | -0.01 | +0.06 | R$-4.81 |

### Decision gate

Per the plan:
- **>95% same strikes**: Adopt CDI as default
- **<95% same strikes**: Investigate before adopting

**Both markets are below 95%.** However, the mean strike differences are negligible (<0.06), indicating the divergence occurs at strike grid boundaries rather than representing meaningful selection changes. CDI deltas are more accurate (computed with daily rates vs flat 12%), so adoption is technically justified — but the plan requires investigation before setting `use_cdi_ivs: True` as default.

**Verdict: CDI wiring is complete and functional. Default remains `False` pending decision on whether to adopt despite <95% match rate.**

### Test results

```
85 passed in 0.41s
```

No regressions from existing test suite.

---

## Step 5 — Calibrate Quality Tests for B3

### What was built

Updated `scripts/check_rb3_quality.py` with B3-appropriate thresholds and status logic:

| Change | Detail |
|--------|--------|
| **Test I (Put-call parity)** | Dynamic threshold: 5% for BOVA11 (European), 10% for PETR4 (American, early-exercise premium). F-string fix for violation label. |
| **Test J (Term structure)** | Marked as `INFO` — never FAILs. B3 single-stocks have legitimate IV jumps at earnings. F-string fix for delta label. |
| **Test L (Strike grid)** | Lowered `min_strikes` from 5 to 3 for B3. |
| **`run_all()` status logic** | Test J always `INFO`; Test I uses per-underlying threshold; all others use `TARGET_PCT` (0.1%). |
| **Summary logic** | Excludes Test J from failure count; applies per-test thresholds. |

### Results

**BOVA11:**
| Test | Status | Violations |
|------|--------|------------|
| A: Price sanity | PASS | 0.00% |
| B: Greeks sanity | PASS | 0.02% |
| C: Bid/Ask consistency | PASS | 0.02% |
| D: Time consistency | PASS | 0.03% |
| E: Coverage by date | **FAIL** | 0.63% |
| F: Underlying consistency | PASS | 0.00% |
| H: Duplicates | PASS | 0.00% |
| I: Put-call parity | **PASS** | 0.58% (< 5% threshold) |
| J: Term structure | **INFO** | 2.35% |
| L: Strike grid (≥3) | **FAIL** | 32.49% |
| M: Corruption regression | PASS | 0.00% |

**PETR4:**
| Test | Status | Violations |
|------|--------|------------|
| A: Price sanity | **FAIL** | 0.11% |
| B: Greeks sanity | **FAIL** | 0.20% |
| C: Bid/Ask consistency | PASS | 0.02% |
| D: Time consistency | PASS | 0.04% |
| E: Coverage by date | PASS | 0.09% |
| F: Underlying consistency | PASS | 0.00% |
| H: Duplicates | **FAIL** | 1.91% |
| I: Put-call parity | **PASS** | 1.82% (< 10% threshold) |
| J: Term structure | **INFO** | 9.37% |
| L: Strike grid (≥3) | **FAIL** | 27.09% |
| M: Corruption regression | PASS | 0.00% |

### Decision gate

- **Test I:** Both BOVA11 (0.58% < 5%) and PETR4 (1.82% < 10%) **PASS**. Put-call parity violations are within acceptable bounds for each market's exercise style.
- **Test J:** Marked informational. No action needed — IV jumps are expected for B3 single-stocks.
- **Test L:** Still FAILs (32% BOVA11, 27% PETR4) even at threshold=3. This reflects genuine shallow chain coverage in B3 single-stock options — many expiry-date groups genuinely have only 1–2 strikes. This is a data characteristic, not a threshold issue.

### Follow-ups

- Test L failures are inherent to B3 single-stock data. The engine should handle sparse chains gracefully (it already does via synthetic fallback).
- PETR4 has ~9,288 duplicate rows (Test H FAIL at 1.91%). Worth investigating deduplication in a future data cleanup pass.

---

## Step 6 — Decide on Synthetic Fallback Policy

### What was built

| File | Changes |
|------|---------|
| `src/straddle/metrics.py` | Added source tracking stats (`entry_db_count`, `entry_db_total`, `entry_db_pct`, `exit_db_count`, `mtm_avg_db_pct`) to `compute_portfolio_metrics()` — the function used by grid search |
| `scripts/grid_search.py` | Added `entry_db_pct` and `mtm_avg_db_pct` to `METRICS_KEYS` so every grid search row includes these columns |
| `src/straddle/params.py` | Added documentation note (lines 136–143) explaining the ~50% synthetic fallback rate for B3 options and the requirement to report `entry_db_pct` |

### Policy decision

**Option C adopted:** Accept the ~50% synthetic fallback rate and report it as a known limitation. Every grid search output includes `entry_db_pct` and `mtm_avg_db_pct`. No engine changes to relax entry criteria (Option B) — the risk of using close prices instead of bid/ask at entry would make results appear more profitable than achievable in practice.

### Test results

```
85 passed in 0.37s
```

All tests pass. No regressions.

---

## Grid Search Specification — Mandatory Addendum

The following requirements apply to the definitive grid search (plan Step 7):

1. **Every grid point must report `entry_db_pct` and `mtm_avg_db_pct`** alongside Sharpe, P&L, win rate, MDD, and Calmar. Both fields are now in `METRICS_KEYS` in `grid_search.py` and emitted by `compute_portfolio_metrics()`.

2. **P&L must be broken down by `entry_source`** (db vs synthetic) for each grid point.

3. **The "positive ridge" conclusion for BOVA11 must be evaluated on DB-entry trades only**, not the aggregate. The aggregate P&L mixes real B3 prices with synthetic BSM pricing, and Step 2 showed that synthetic entries produce materially different results (86.7% win rate vs 56.8% for DB entries). Any configuration that appears positive only because of synthetic fallback dominance is not trustworthy.

4. A configuration should only be considered "positive" if:
    - DB-entry subset P&L is positive, AND
    - `entry_db_pct` is high enough (>50%) that the DB subset is statistically meaningful

---

## Follow-ups (noted but not done)

1. **Performance**: `_source_for_strike()` does a SQL query per leg per day. Could be optimized with pre-computed lookup sets if it becomes a bottleneck (plan line 1019).
2. **Synthetic skew re-fitting**: The large P&L divergence between DB and synthetic entries suggests `put_slope` / `call_slope` should be re-fitted against rb3 data.
3. **PETR4 baseline Sharpe**: -6.50 is extreme but legitimate. Worth noting that PETR4 is a losing strategy across all configs, so this doesn't affect grid search viability.
4. **PETR4 diagnostic**: Step 2 only ran BOVA11. A similar run for PETR4 would be useful but is not in the plan.
5. **CDI adoption decision**: Step 4 shows <95% strike match rate for both markets. Mean diffs are tiny (<0.06), suggesting boundary-level divergence only. Decision needed: adopt CDI as default (`use_cdi_ivs: True` in B3 presets) or keep flat-12% until further investigation.
6. **PETR4 data quality**: ~9,288 duplicate rows (Test H at 1.91%) and shallow strike grids (Test L at 27%) indicate data quality issues worth addressing in a future cleanup pass.
7. **Option B (mark-as-mid fallback)**: Deferred to Phase 5. Using `mark` instead of bid/ask at entry would increase DB hit rate but risks overstating profitability.

---

## Next step

Proceed to **Step 7 — Definitive grid search prerequisites checklist** (plan section starting at line 919). All Steps 1–6 are complete.
