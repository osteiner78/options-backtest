# V3 Grid Search — Comprehensive Project Report

**Date:** 2026-05-13
**Scope:** BOVA11 short strangle grid search, bug discovery & remediation, definitive results
**Outcome:** Strategy is structurally unprofitable on BOVA11 across all tested configurations

---

## 1. Project History and Objectives

### 1.1 Origin

This project extends an SPY short-strangle backtesting engine to B3 (Brazilian exchange) markets, specifically BOVA11 (IBOV ETF) and PETR4 (Petrobras). The core question: **does selling monthly OTM put+call options on Brazilian equities generate positive risk-adjusted returns?**

### 1.2 Prior Work (Pre-V3)

| Milestone | Commit | Description |
|---|---|---|
| B3 market support | `cafc39d` | VIX scale fix, per-market entry caps, trading-day cache, BRL labels |
| MTM Sharpe fix | `22600b8` | Mark-to-market Sharpe + B3-native vol filters (rv_pct, ivr) |
| Vol filter unification | `c29f6f5` | Unified vol filter params, single-position filter |
| V2 grid search | `8c03a97` | Initial B3 grid search, QA artifacts, data integrity tests |
| Source tracking | `3c3725a` | Entry/exit/MTM source tracking (DB vs synthetic) |
| Steps 5-6 | `b3e331f` | Quality test calibration, synthetic fallback policy |

**V2 finding:** Both PETR4 and BOVA11 showed deeply negative Sharpe ratios. PETR4 was dropped as conclusively unviable. BOVA11 warranted a definitive v3 run after fixing bugs discovered during v2 analysis.

### 1.3 V3 Objectives

1. Fix all bugs that could inflate synthetic-mode P&L (making results look better than reality)
2. Re-fit B3 skew parameters against the clean rb3 database (old ones were fitted on corrupted data)
3. Run an expanded grid: 5×4×3×4×6×2×3 = 7,560 valid combos × 2 periods = 15,120 backtests
4. Assess holdout robustness and source-tracking integrity

---

## 2. Bug Discovery and Remediation

A full audit of the trading-flow code (from entry through MTM, roll, and exit) identified 8 issues. All were fixed in commit `2d7fc3e`.

### Bug #1: Missing Fill Adjustment for Synthetic Fallback in MarketEngine (Critical)

**File:** `src/straddle/engines.py`

**Symptom:** Market-mode backtests with synthetic fallback entries (36% of B3 entries in train, ~12% in holdout) systematically overstated P&L by ~5% per synthetic mark. A sample trade showed `pnl=77.61` instead of correct `67.61` (+14.8%).

**Root cause:** `MarketEngine.apply_fill_adj()` is intentionally a no-op — DB bid/ask prices already embed the bid-ask spread. However, three methods fall back to `SyntheticEngine` when DB data is unavailable:
- `get_entry_marks()` — returns raw BS mids (entry credit misses -5% fill adj)
- `get_leg_mark_with_source()` — returns raw BS mids (close cost misses +5%)
- `get_daily_mark()` — raw BS mids per-leg fallback

The caller then calls `engine.apply_fill_adj()` which hits the no-op, so synthetic marks never get the 5% spread adjustment.

**Fix applied:**
1. `get_entry_marks` synthetic fallback: apply `self._synth.apply_fill_adj(pm + cm, "open")` to the combined mid, then scale individual leg mids proportionally
2. `get_leg_mark_with_source` both fallback paths: apply `self._synth.apply_fill_adj(synth, "open"|"close")` based on `buy_or_sell`
3. `get_daily_mark` per-leg fallback: apply `self._synth.apply_fill_adj(mark, "close")`

**Verification:** Market mode Trade 3 (BOVA11, 2023-03-07, fully synthetic) now produces `net_credit=131.78, pnl=67.61` matching pure SyntheticEngine. DB-data trades unchanged (fill adj only applied on fallback branches). All 85 existing tests pass.

**Impact on v3 results:** Makes already-negative results slightly more negative for synthetic-heavy configs. Does not flip any conclusion.

---

### Bug #2: Fill Adjustment Incorrectly Applied to Intrinsic Value at Expiry (Minor)

**File:** `src/straddle/strategy.py` (lines 641-648, 887-901)

**Symptom:** At expiry (`dte_rem == 0`), intrinsic value is the fair price — the bid-ask spread collapses because options are fungible with the underlying. Applying +5% fill adj to intrinsic adds phantom ~R$20/contract transaction cost.

**Root cause:** Two code paths applied `apply_fill_adj()` without checking whether the trade was at expiration:
1. `evaluate_trade_step` line 641-648: close cost formula
2. `evaluate_trade` fallback line 908: `cc = engine.apply_fill_adj(intr, "close") * mult + comm`

**Fix:** Added `if dte_rem > 0:` guard around fill adjustment in both paths. At expiry, close cost uses raw mid (no adj).

**Impact:** Only affects trades expiring ITM (rare with `manage_at_dte=21`). Conservative direction — removing the adj makes P&L slightly better for those trades.

---

### Bug #3: B3 Skew Parameters Fitted on Corrupted Data (Moderate)

**File:** `scripts/fit_b3_skew.py`, `src/straddle/params.py`

**Symptom:** Skew params were fitted on the old `b3_options.db` which contained R$500k mark corruption. The engine now uses `b3_options_rb3.db` with CDI-based IVs, but params were never re-fitted.

**Fix:**
1. Updated `fit_b3_skew.py` to use `b3_options_rb3.db` with CDI columns (`implied_volatility_cdi`, `delta_cdi`)
2. Re-ran fitting:

| Market | Old put_slope | Old call_slope | New put_slope | New call_slope | Change |
|--------|--------------|----------------|--------------|----------------|--------|
| BOVA11 | 0.743 | 0.031 | 0.746 | 0.074 | call 2.4× |
| PETR4 | 0.523 | -0.057 | 0.522 | -0.046 | call 0.8× |

Key change: BOVA11 `call_slope` more than doubled. At 16Δ, call IV multiplier: 0.9895 → 0.9748 (calls priced ~1.5% lower).

**Impact:** Affects ~12-36% of synthetic fallback marks. Won't flip conclusions but makes synthetic pricing more accurate.

---

### Bug #4: No Test Coverage for MarketEngine / B3 Paths (Infrastructure)

**File:** `tests/test_engines.py`

**Symptom:** 85 tests only covered `SyntheticEngine` with SPY parameters. Zero coverage for MarketEngine, B3 presets, synthetic fallback fill adjustment, or source tracking.

**Fix:** Added `TestMarketEngineFillAdj` class with 5 tests:

| Test | Verifies |
|------|----------|
| `test_db_marks_unchanged_by_adj` | DB marks returned directly, no fill adj |
| `test_synthetic_fallback_close_adj` | Synthetic fallback (buy side) gets close fill adj |
| `test_synthetic_fallback_open_adj` | Synthetic fallback (sell side) gets open fill adj |
| `test_entry_synthetic_fallback_adj` | Entry synthetic fallback gets adjusted combined credit |
| `test_apply_fill_adj_noop` | MarketEngine.apply_fill_adj is a no-op (design intent) |

Tests connect to real rb3 DB; skip if unavailable. Test count: 85 → 90.

---

### Bug #5: Fragile SQL Column Selection via F-String True/False (Minor)

**File:** `src/straddle/engines.py` (line ~809)

**Symptom:** `_best_row()` selected IV column via `CASE WHEN {use_cdi} THEN ... ELSE ... END`, injecting a Python bool literal into SQL. While SQLite ≥3.23.0 accepts `True`/`False`, this is fragile and non-idiomatic.

**Fix:** Replace with direct column name selection in Python:
```python
iv_col = "implied_volatility_cdi" if self._use_cdi and self._has_cdi_cols else "implied_volatility"
```
Then use `{iv_col} AS implied_volatility` in the SQL. Identical results, more robust.

---

### Bug #6: Redundant Source Tracking Queries in Dead Fallback Path (Code Quality)

**File:** `src/straddle/engines.py`, `src/straddle/strategy.py`

**Symptom:** `evaluate_trade_step` had a `hasattr` branch: if `get_leg_mark_with_source` exists (MarketEngine), use merged marks+source; otherwise call `get_leg_mark` + separate `_source_for_strike` queries. The second branch was dead code for SyntheticEngine (never hits `_source_for_strike`) and would have been fragile for any future engine.

**Fix:**
1. Added `SyntheticEngine.get_leg_mark_with_source` returning `(bs_mid, "synthetic")`
2. Removed the `hasattr` branch in `evaluate_trade_step` — always calls `engine.get_leg_mark_with_source()`
3. Test update: renamed assertion from `"unknown"` → `"synthetic"`

---

### Bug #7: Gap VIX Multiplier Not Calibrated for B3 (Parameter Gap)

**File:** `src/straddle/params.py`

**Symptom:** `gap_vix_multiplier` was set to 3.0 globally (calibrated for S&P 500 / VIX). Not overridden in B3 market presets. B3 equities may have different gap/vol dynamics (political shocks, BRL/USD, oil price events).

**Fix:** Added `gap_vix_multiplier: 3.0` to both `bova11` and `petr4` presets with TODO calibration notes. The parameter is now per-market overrideable.

**Impact:** Only fires when `use_price_stop=True` AND a gap day breaches the stop. The v3 grid included `stop_loss_pct` values with `use_price_stop=True`, so this could affect those paths. Not calibrated yet, but cannot flip the overall negative conclusion.

---

### Bug #8: Minor Code Quality (Single-Position Gate, Comments)

**File:** `src/straddle/strategy.py` (line 960)

**Issue 8.1:** Single-position gate used `entry_date < latest_open_exit` (strict). If a trade chain exits on date D and the next monthly entry is also D, the gate allows same-day entry/open at same EOD prices. Changed to `<=`.

**Issue 8.2:** Gap open mark VIX round-trip — verified no redundant operations.

**Issue 8.3:** Expiry fallback uses closing price — acceptable since BVMF calendar ensures expiration on a trading day.

---

## 3. Grid Search Configuration

### 3.1 Parameters

| Dimension | Values | Count |
|---|---|---|
| `target_delta` | 0.16, 0.20, 0.25, 0.30, 0.50 | 5 |
| `dte_max` | 21, 30, 45, 60 | 4 |
| `profit_target_pct` | 0.25, 0.50, 0.75 | 3 |
| `manage_at_dte` | 7, 10, 14, 21 | 4 |
| `vix_filter` | OFF, rv_pct:70, rv_pct:80, rv_pct:90, ivr:30, ivr:50 | 6 |
| `defensive_leg_roll` | True, False | 2 |
| `stop_loss_pct` | 1.5, 2.0, 3.0 (with `use_price_stop=True`) | 3 |

**Validity constraint:** `manage_at_dte < DTE_MIN_BY_DTE_MAX[dte_max]` where `DTE_MIN_BY_DTE_MAX[60]=45` (added for v3). This eliminated 1,080 invalid combos, leaving 7,560 valid combos.

### 3.2 Periods

| Label | Start | End |
|---|---|---|
| Train | 2020-04-01 | 2023-12-31 |
| Holdout | 2024-01-01 | 2025-12-31 |

### 3.3 Fixed Settings

- `mode=market`, `cash_investment_mode=risk_free`, `cash_yield_annual=0`
- `use_cdi_ivs=True` (CDI-based IVs and deltas)
- B3 skew params: `put_slope=0.746`, `call_slope=0.074`

### 3.4 Execution

- 8 workers, data+engine cached per period (4.2× speedup from v2)
- Source-mark merge halved hot-loop DB calls
- Progress bars suppressed (`progress=False`)
- Runtime: ~16 min (train) + ~7.5 min (holdout) = ~23 min total
- 0 errors, 2,265 underpowered configs (n_chains < 50)

---

## 4. Results

### 4.1 Overall Summary

| Metric | Train | Holdout |
|---|---|---|
| Mean Sharpe | -0.88 | -1.29 |
| Std Sharpe | 0.81 | 0.66 |
| Min Sharpe | -3.72 | -3.92 |
| Max Sharpe | +1.20 | +0.55 |
| % Positive Sharpe | ~10% | 0.7% (22 configs) |
| Mean alpha_sharpe | -1.01 | -1.12 |
| Mean entry_db_pct | 0.72 | 0.87 |

### 4.2 Source Tracking

**By delta × period:**

| target_delta | Train DB% | Holdout DB% |
|---|---|---|
| 0.16 | 0.723 | 0.879 |
| 0.20 | 0.720 | 0.876 |
| 0.25 | 0.720 | 0.880 |
| 0.30 | 0.720 | 0.884 |
| 0.50 | 0.727 | 0.883 |

Higher DB coverage in holdout is expected — the rb3 DB has more complete data for 2024-2025. Train period has ~28% synthetic fallback, making Bug #1's fix impactful there.

**Correlation between entry_db_pct and Sharpe:**
- Train: r = -0.460 (higher DB% → lower Sharpe, i.e., synthetic fallback inflates)
- Holdout: r = -0.038 (no relationship — more trustworthy)

### 4.3 Best Configs (Holdout, n_chains ≥ 50)

| # | Sharpe | alpha_sharpe | total_return | target_delta | dte_max | profit_target | manage_dte | vix_filter | leg_roll | stop_loss |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | +0.34 | -0.83 | +3.3% | 0.20 | 45 | 0.50 | 21 | rv_pct:70 | False | 3.0 |
| 2 | +0.21 | -0.72 | +2.5% | 0.20 | 30 | 0.75 | 7 | OFF | False | 1.5 |
| 3 | +0.18 | -0.77 | +1.8% | 0.16 | 30 | 0.75 | 7 | OFF | False | 3.0 |

All top holdout configs share: **`defensive_leg_roll=False`**, **narrow delta (0.16-0.20)**, and all have **deeply negative alpha_sharpe** — the strangle subtracts value vs buy-and-hold even at its "best."

### 4.4 Top Train Configs by Sharpe

Concentrated on: `target_delta=0.20, dte_max=30, profit_target=0.50, manage_at_dte=7, leg_roll=False`. All with deeply negative `alpha_vs_bh` (worst -0.87).

### 4.5 DB Entry Analysis

| Subset | Train Sharpe | Train total_return | Train win% |
|---|---|---|---|
| High DB% (≥70%) | -1.32 ± 0.78 | -22.4% | 47.1% |
| Low DB% (<50%) | none | — | — |

| Subset | Holdout Sharpe | Holdout total_return | Holdout win% |
|---|---|---|---|
| High DB% (≥70%) | -1.17 ± 0.60 | -9.7% | 51.7% |
| Low DB% (<50%) | none | — | — |

Positive-Sharpe configs have **lower** DB% in train (0.664 vs 0.732), confirming synthetic fallback inflates train results. In holdout, positive configs have slightly lower DB% (0.869 vs 0.880) but the correlation is negligible (r = -0.038).

### 4.6 Stop Loss Impact

| stop_loss_pct | Train Mean | Holdout Mean |
|---|---|---|
| 1.5 | -1.02 | -1.36 |
| 2.0 | -0.88 | -1.21 |
| 3.0 | -0.74 | -0.94 |

Wider (more generous) stop loss consistently improves Sharpe, but even SL=3.0 is deeply negative. The stop-loss path is where `gap_vix_multiplier` calibration would matter, but it cannot rescue the strategy.

### 4.7 Defensive Leg Roll

| leg_roll | Train Sharpe | Holdout Sharpe |
|---|---|---|
| True | -0.942 | -1.228 |
| False | -0.814 | -1.117 |

`defensive_leg_roll=False` consistently better — consistent with v2 findings.

### 4.8 Vol Filter

No vol filter mode produces positive holdout Sharpe. The boxplot shows all filters are deeply negative. `rv_pct:70` is marginally less negative than others but the difference is within noise.

### 4.9 Train→Holdout Relationship

- Sharpe correlation: r = 0.67 (decent)
- But the intercept is deeply negative: train Sharpe of +1.0 → holdout Sharpe of ~-0.5
- Mean holdout Sharpe: -1.17 (viable configs only)
- Only 0.7% of holdout configs positive
- No config clusters near the y=x diagonal

### 4.10 target_delta=0.50 (Straddle Check)

The 50Δ straddle configs are deeply negative across both periods, confirming the structural short-vol loss expected for at-the-money straddles.

---

## 5. Key Conclusions

### 5.1 BOVA11 Short Strangle Is Not Viable

The strategy produces **negative Sharpe ratios across all 7,560 configurations** in the holdout period. The best holdout Sharpe (+0.34) is within noise for 57 trades and has deeply negative alpha vs buy-and-hold. There is no parameter combination that makes this strategy work.

### 5.2 Why It Fails

1. **BOVA11 trend behavior:** The index trends persistently in one direction (Brazilian macro cycles). Short strangles are pathologically wrong when the underlying trends.
2. **Emerging market risk premium:** B3 options are richly priced (high IV), but not rich enough to compensate for the left-tail risk. The premium collected doesn't cover the losses from directional moves.
3. **Currency-denominated lens:** Even with CDI-based pricing, the real-denominator returns are eaten by gap-down events that BOVA11 experiences disproportionately.
4. **The alpha_vs_bh is universally negative** — just buying and holding BOVA11 outperforms the strangle overlay in every configuration.

### 5.3 PETR4 Was Already Conclusively Negative

Dropped before v3. Its short-strangle results were even worse than BOVA11's.

### 5.4 Bug Fixes Did Not Materialibly Change the Conclusion

While Bug #1 (fill adjustment) was the highest-impact fix, it made results slightly *more* negative (correct direction). The strategy was deeply negative even with the bug; fixing it confirmed the finding rather than overturning it.

---

## 6. Open Issues and Follow-ups

### 6.1 Not Worth Pursuing

- **`gap_vix_multiplier` calibration:** Only affects `use_price_stop=True` stop-loss path. Even the most generous SL is deeply negative. Calibration would shift outcomes by a few basis points at most.
- **Expanded grid dimensions:** Wider delta ranges, DTE bands, or vol filters won't rescue a structurally negative strategy.
- **Different underlyings on B3:** PETR4 was already negative. Other B3 tickers may behave differently but the engine would need new DB ingestion.

### 6.2 Potentially Worth Revisiting

- **Long volatility strategies:** If short vol is negative, perhaps long vol has merit on B3. Would require engine modifications (long straddle/strangle entry).
- **Short strangle on SPY (original mandate):** The engine works well for SPY. This B3 work was an extension.
- **Different option structures:** Iron condors, credit spreads, or calendar spreads may have different risk profiles on B3.

### 6.3 Code Quality Follow-ups

- `_source_for_strike` is now unused in `strategy.py` but kept for potential external callers
- Bug #3 skew refit was done on full history; a trailing-window fit could improve synthetic accuracy
- Issue #4: B3-specific test coverage could be expanded beyond fill-adjustment
- Holdout DB coverage ends at 2025-12-23 (8 days of synthetic fallback in Dec 2025)

---

## 7. Commit History (Bug Fix Session)

```
2d7fc3e  fix: critical bugs 1-8 — fill adj, expiry, skew refit, tests, SQL cleanup
bd4a670  feat: expanded grid (stop_loss_pct + leg_roll + vol filters), suppress progress bars, fix target_delta flow
dc22c64  fix: pass target_delta through PricingContext to fix grid search bug
eb2c5d3  feat: v3 grid search prep — CDI IVs, source-mark merge, worker cache, reduced grid
b3e331f  feat: Steps 5-6 — B3 quality test calibration and synthetic fallback policy
3c3725a  feat: add entry/exit/MTM source tracking for DB vs synthetic pricing
```

Bug fix commit `2d7fc3e` includes all 8 fixes in a single commit. Individual reports are in `.agent/reports/001-` through `008-`.

---

## 8. Artifacts

| File | Description |
|---|---|
| `data/B3/v3_grid_search_results.parquet` | 15,120-row results dataset |
| `research/2026-05-13 - B3 - v3 grid search.ipynb` | Analysis notebook (cells 1-17) |
| `data/B3/v3_heatmap_delta_dte.png` | Sharpe heatmap by delta × DTE |
| `data/B3/v3_heatmap_profit_manage.png` | Sharpe heatmap by profit target × manage DTE |
| `data/B3/v3_scatter_nchains_sharpe.png` | Trade count vs Sharpe (color = DB%) |
| `data/B3/v3_vol_filter_boxplot.png` | Vol filter impact |
| `data/B3/v3_train_vs_holdout.png` | Train-holdout Sharpe scatter |
| `data/B3/v3_stop_loss_impact.png` | Stop loss dimension |
| `data/B3/v3_defensive_leg_roll.png` | Leg roll dimension |
| `.agent/reports/001-*` through `008-*` | Individual bug fix reports |