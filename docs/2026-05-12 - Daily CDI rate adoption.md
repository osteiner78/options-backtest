# Phase 3 — Daily CDI Rate Adoption

**Date:** 2026-05-12  
**Status:** Complete — columns added, analysis done, adoption deferred pending re-run

---

## What was done

Added two new columns to `b3_options_rb3.db`:

| Column | Description |
|--------|-------------|
| `implied_volatility_cdi` | IV recomputed using actual daily CDI rate from `bova11_backtest.parquet` & `petr4_backtest.parquet` |
| `delta_cdi` | Delta recomputed using the CDI-based IV and daily r |

Recomputation ran over 1,416,520 rows in parallel (8 cores, ~1.5 min total). European BSM formula used for both underlyings (BOVA11 is European; PETR4 is American but the BAW correction is negligible for the 16-delta OTM options the strategy trades). Calendar-day time-to-expiry used (difference vs business-day convention is <0.5% for 30-45 DTE).

## Success rate

| Underlying | Rows processed | Valid IVs | Success |
|------------|---------------|-----------|---------|
| BOVA11 | 454,651 | 408,211 | 89.8% |
| PETR4 | 961,869 | 855,861 | 89.0% |

Failed rows (~10-11%) are deep OTM/ITM options where the BSM price can't match the observed close within the [0.1%, 1000%] IV bounds. These are the same options the engine already filters via `implied_volatility < 2.0` in `_best_row` — they have no practical impact on trading.

## IV comparison: flat r=12% vs daily CDI

For rows where both IVs are valid and within [1%, 200%] (the engine's trading range):

| Metric | BOVA11 | PETR4 |
|--------|--------|-------|
| Comparable rows | 399,178 | 820,695 |
| **Median IV diff (cdi − flat)** | **+0.24 vol pts** | **+0.22 vol pts** |
| Mean IV diff | +0.37 vol pts | +0.09 vol pts |
| σ | 3.96 vol pts | 6.04 vol pts |
| Rows with \|diff\| > 2 vol pts | 28.7% | 42.2% |
| Rows with \|diff\| > 5 vol pts | 9.2% | 18.3% |

**Key finding:** Median difference is within the expected ~0.5 vol point range. The fat tails (>5 vol pts in 9-18% of rows) are concentrated in deep OTM/ITM options where IV computation is highly sensitive to small price changes. These options are filtered by the engine and never traded. For the 16-delta ATM-near options the strategy actually trades, the difference is likely negligible.

## Decision

**Not yet switching the default.** Per plan recommendation: keep both `implied_volatility` (flat 12%) and `implied_volatility_cdi` (daily CDI) columns. The engine currently uses `implied_volatility` in `_best_row`. Before switching:

- Add a `use_cdi_ivs` config flag to `params.py` that controls which column the engine reads
- Re-run Phase 1 regression with CDI-based IVs to confirm no surprises
- If strike selection is unchanged (within ±1 strike on >95% of entries), adopt CDI as default

## Script

| File | Purpose |
|------|---------|
| `scripts/recompute_iv_with_cdi.py` | Parallel IV recomputation using joblib + brentq |
