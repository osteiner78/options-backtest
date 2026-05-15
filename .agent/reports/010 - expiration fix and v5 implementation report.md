# Implementation Report: Expiration Fix, Volume Filter Removal, and v5 Confirmation Grid

**Date:** 2026-05-14  
**Plan:** `.agent/plans/010 - expiration fix and v5 confirmation.md`  
**Branch:** `b3-backtest`

---

## Part 1: Fix B3 Expiration Mismatch

### Problem
B3 BOVA11 options used 3rd-Monday expirations before May 2021. The strategy computed 3rd-Friday dates via `get_third_friday()`, causing `_best_row()` to return no match for ~70% of train-period (2018-2022) entries. These fell back to `SyntheticEngine` with 5% fill adjustment — an 8x underestimate of real ~40% spread.

### Changes

#### 1.1 `MarketEngine.get_db_expiration()` — `src/straddle/engines.py:558`
New method that queries the DB for actual available monthly expirations. Searches `SELECT DISTINCT expiration` for rows matching the eval date and underlying filter, then returns the first expiration with DTE in `[dte_min, dte_max]`. Returns `None` if no valid expiration exists.

```python
def get_db_expiration(self, date_str: str, dte_min: int, dte_max: int) -> Optional[pd.Timestamp]:
```

#### 1.2 `get_monthly_expiration()` — `src/straddle/strategy.py:134`
Added optional `engine` parameter. When a `MarketEngine` is provided (detected via `hasattr(engine, 'get_db_expiration')`), queries the DB first. Falls back to 3rd-Friday calendar calculation as before.

#### 1.3 `get_entry_dates()` — `src/straddle/strategy.py:154`
Added optional `engine` parameter, passed through to `get_monthly_expiration()`.

#### 1.4 `run_backtest()` — `src/straddle/strategy.py:947`
Passes `engine=engine` to both `get_entry_dates()` and the roll-logic call to `get_monthly_expiration()`.

#### 1.5 `run_portfolio_backtest()` — `src/straddle/portfolio.py:386`
Passes `engine=engine` to `get_monthly_expiration()`.

#### 1.6 `scripts/grid_search.py:309`
Added missing keys (`stop_loss_pct`, `execution_mode`) to the self-equivalence smoke test `COMBO` dict.

### New Tests — `tests/test_execution_modes.py`

| Test | Class | Description |
|------|-------|-------------|
| `test_db_expiration_finds_valid_dte` | `TestDBExpiration` | Returns correct expiration for known date+range |
| `test_db_expiration_returns_none_if_no_match` | `TestDBExpiration` | Returns `None` when no expiration in range |
| `test_calendar_fallback_when_no_engine` | `TestExpirationResolution` | Falls back to 3rd-Friday when no engine provided |
| `test_db_overrides_calendar` | `TestExpirationResolution` | DB expiration takes precedence over calendar |

---

## Part 2: Remove `volume_filtered` Execution Mode

### Problem
`volume_filtered` mode used a global volume percentile threshold (12,900 at 50th percentile). The liquid 16-delta options always exceeded this threshold, making volume_filtered identical to `mid` (correlation = 1.000). It added complexity without information.

### Changes

#### 2.1 `src/straddle/params.py`
- Removed `volume_filter_min_pct: float` from `PricingParams` TypedDict
- Removed `"volume_filter_min_pct": 0.50` from `PRICING` defaults
- Updated `execution_mode` docstring to 4 values: `"bid_ask" | "mid_minus_1tick" | "mid" | "mid_plus_1tick"`

#### 2.2 `src/straddle/engines.py`
- Removed `self._volume_filter_min_pct` and `self._daily_vol_threshold` from `MarketEngine.__init__()`
- Removed `_compute_volume_threshold()` method entirely
- Changed: `self.uses_real_fills = self._exec_mode in ("bid_ask", "volume_filtered")` → `self.uses_real_fills = self._exec_mode == "bid_ask"`
- Removed `volume_filtered` elif block from `get_entry_marks()`
- Cleaned up docstring references in `get_daily_mark()` and `get_leg_mark_with_source()`

#### 2.3 `tests/test_execution_modes.py`
- Removed `TestVolumeFiltered` class (3 test methods)
- Removed `test_volume_filtered_close_uses_mark` from `TestCloseSideExecution`
- Removed `"volume_filtered"` from mode list in `test_sell_side_unaffected_by_exec_mode`
- Removed `volume_filter_min_pct` from `_make_params()`
- Cleaned up `_TEST_ROWS` comment referencing volume filter threshold

---

## Part 3: v5 Confirmation Grid Notebook

### Generated using `scripts/build_v5_notebook.py`

**Output:** `research/2026-05-15 - B3 - v5 confirmation grid.ipynb` (24 cells)

| Cell | Label | Description |
|------|-------|-------------|
| 0 | Context | v5 context: expiration fix, volume_filter removed, v3 reproduction |
| 1 | Imports | matplotlib, pandas, numpy, grid_search imports |
| 2 | Grid Definition | 4 execution modes, 96 combos × 2 = 192 backtests |
| 3 | Run Config | train (2018-2022), holdout (2023-2025) |
| 4 | Execute/Load | Cached parquet, 4-category ordered Categorical |
| 5 | Cell A | Sharpe vs execution_mode boxplot (2-panel) |
| 6 | Cell B | Break-even execution level (4 modes only) |
| 7 | Cell C | Sharpe heatmap: execution_mode × target_delta |
| 8 | Cell D | **NEW**: Entry DB coverage by period and mode (replaces volume_filter skip rate) |
| 9 | Cell E | **NEW**: v3 Reproduction — runs v3's exact grid + periods, compares documented -1.17 Sharpe |
| 10 | Cell F | Spread cost analysis (ask-bid/mark by delta bucket and year) |
| 11 | Cell G | Per-trade P&L for best config (4 modes only) |
| 12 | Cell H | **NEW**: Period-overlap diagnostic — isolates period effect from code differences |

### v5 Grid vs v4

| Dimension | v4 | v5 |
|-----------|-----|-----|
| Execution modes | 5 (incl. volume_filtered) | 4 |
| Combos per period | 120 | 96 |
| Total backtests | 240 | 192 |
| volume_filtered | Present | **Removed** |
| Expiration resolution | 3rd-Friday only | **DB-aware** (`get_db_expiration`) |

---

## Test Results

```
============================= 105 passed in 1.38s ==============================
```

Self-equivalence check (`scripts/grid_search.py`):
```
OK  worker == direct: n_trades=221  sharpe=-1.3106
```

---

## Files Modified

| File | Changes |
|------|---------|
| `src/straddle/engines.py` | +`get_db_expiration()`, -`_compute_volume_threshold()`, -`volume_filtered` block, cleaned comments |
| `src/straddle/strategy.py` | `get_monthly_expiration()` + `get_entry_dates()` accept `engine` param, `run_backtest()` passes engine |
| `src/straddle/portfolio.py` | `run_portfolio_backtest()` passes engine to `get_monthly_expiration()` |
| `src/straddle/params.py` | Removed `volume_filter_min_pct` from TypedDict and defaults |
| `tests/test_execution_modes.py` | -3 volume_filtered tests, +4 DB expiration tests, cleanup |
| `scripts/grid_search.py` | Added missing COMBO keys for self-equivalence check |
| `scripts/build_v5_notebook.py` | **New** — generates v5 confirmation grid notebook |
| `research/2026-05-15 - B3 - v5 confirmation grid.ipynb` | **New** — 24-cell v5 confirmation grid notebook |

## Files NOT Modified (by design)

| File | Reason |
|------|--------|
| `scripts/build_v4_notebook.py` | Documents v4 "before" state — preserved for historical reference |
| `scripts/validate_b3_prices.py` | Unrelated to these changes |
| Other test files | No changes needed |

---

## Caveats & Deviations

1. **Entry DB coverage target**: The plan targets >85% train DB coverage. Actual coverage depends on real B3 DB data and bid/ask availability. The expiration fix ensures expiration dates match, but `_best_row()` may still return `None` if no valid row exists (bid ≤ 0, mark ≤ 0, etc.).

2. **grid_search.py COMBO fix**: The self-equivalence smoke test was missing `stop_loss_pct` and `execution_mode` keys since before this work — fixed as a side effect of verifying the engine threading.

3. **v3 reproduction**: The v3 reproduction cell runs a large grid (5×4×3×4×6×2×3×1 = 8,640 combos × 3 periods = 25,920 backtests). This may take hours to execute. The notebook is structured so this cell can be skipped if results are already cached at `v3_reproduction_results.parquet`.
