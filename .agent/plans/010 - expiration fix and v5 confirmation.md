# Agent Task: Fix B3 Expiration Mismatch + Remove volume_filtered + v5 Confirmation Grid

## Context

The v4 execution sensitivity analysis revealed two critical bugs and one ineffective feature:

1. **B3 expiration mismatch (blocking):** The strategy computes 3rd-Friday expiration dates using `get_third_friday()`, but B3 BOVA11 options used 3rd-Monday expirations before May 2021. Since `_best_row()` requires an exact match on `expiration` in the SQL query, ~70% of train-period (2018-2022) entries fall back to the SyntheticEngine with its 5% fill adjustment — an 8x underestimate of the real ~40% spread. This makes train-period comparisons between execution modes unreliable. Holdout (2023-2025) is 90% DB because post-switch 3rd-Friday matches.

2. **volume_filtered mode is ineffective:** The volume threshold (12,900 = 50th percentile of all DB volumes) is always exceeded by the liquid 16-delta options that `_best_row()` selects. Volume_filtered produces results identical to `mid` (correlation = 1.000). This adds complexity without information — remove it.

3. **v3 vs v4 contradiction unexplained:** v3 BOVA11 holdout median Sharpe = -1.17 (99.3% negative), v4 bid_ask holdout = +0.38. The explanation is unclear — different grid parameters, different holdout periods (v4 adds 2023), and different train coverage (30% vs unknown). A reproduction cell is needed.

This plan fixes bug #1, removes #2, and adds reproduction + confirmation cells for #3.

---

## Part 1: Fix B3 Expiration Mismatch

### What you're building

A DB-aware expiration resolution that queries the options database for available monthly expirations instead of computing them from a calendar convention. This eliminates the 3rd-Monday / 3rd-Friday mismatch entirely.

### Step 1.1 — Add `get_db_expiration()` to `MarketEngine`

**File: `src/straddle/engines.py`**

Add a new method to `MarketEngine`:

```python
def get_db_expiration(self, date_str: str, dte_min: int, dte_max: int) -> Optional[pd.Timestamp]:
    """Return the nearest monthly expiration available in the DB for a given date
    with DTE in [dte_min, dte_max].
    
    Queries actual DB expirations directly, avoiding the 3rd-Monday/3rd-Friday
    convention mismatch that causes 70% synthetic fallback for B3 pre-2021 data.
    
    Must be called after MarketEngine.__init__() (needs self._con).
    """
    und_clause, und_val = self._und_filter()
    params = [date_str]
    if und_val is not None:
        params.append(und_val)
    cur = self._con.execute(
        f"""SELECT DISTINCT expiration FROM options_data
           WHERE date = ?
           {und_clause}
           AND mark > 0
           ORDER BY expiration""",
        params,
    )
    rows = cur.fetchall()
    if not rows:
        return None
    
    eval_date = pd.Timestamp(date_str)
    for row in rows:
        exp = pd.Timestamp(row["expiration"])
        dte = (exp - eval_date).days
        if dte_min <= dte <= dte_max:
            return exp
    return None
```

### Step 1.2 — Make `get_monthly_expiration` and `get_entry_dates` engine-aware

**File: `src/straddle/strategy.py`**

The current flow is:
1. `get_entry_dates()` calls `get_monthly_expiration()` -> returns 3rd-Friday date
2. The 3rd-Friday date is passed as `PricingContext(expiration=...)` to the engine
3. Engine queries `WHERE expiration = <3rd-Friday date>` -> no match for B3 pre-2021

The fix: when in `market` mode with a `MarketEngine`, pass the engine to `get_monthly_expiration` so it can query the DB for the actual expiration. When no engine is available (synthetic mode), fall back to 3rd-Friday calculation.

**Modify `get_monthly_expiration()` signature** to accept an optional `engine` parameter:

```python
def get_monthly_expiration(
    entry: pd.Timestamp,
    dte_min: int,
    dte_max: int,
    calendar: str = "NYSE",
    engine=None,  # MarketEngine for DB-based expiration lookup
) -> Optional[pd.Timestamp]:
    """Nearest monthly expiration with DTE in [dte_min, dte_max].
    
    If a MarketEngine is provided, queries the DB for actual available
    expirations (handles B3 convention changes like 3rd Monday -> 3rd Friday).
    Otherwise, falls back to 3rd-Friday calculation with holiday adjustment.
    """
    if engine is not None and hasattr(engine, 'get_db_expiration'):
        result = engine.get_db_expiration(
            entry.strftime("%Y-%m-%d"), dte_min, dte_max
        )
        if result is not None:
            return result
        # Fall through to calendar-based if DB returns nothing
    
    # Calendar-based fallback (original logic unchanged)
    for mo in range(0, 5):
        # ... existing 3rd-Friday logic ...
```

**Modify `get_entry_dates()`** similarly — add an optional `engine` parameter and pass it through to `get_monthly_expiration()`:

```python
def get_entry_dates(
    data: pd.DataFrame,
    start_date: str,
    end_date: str,
    dte_min: int,
    dte_max: int,
    calendar: str = "NYSE",
    engine=None,  # pass MarketEngine for DB expiration lookup
) -> List[Tuple[pd.Timestamp, pd.Timestamp]]:
```

### Step 1.3 — Update `run_backtest()` and `run_portfolio_backtest()` to pass engine

**File: `src/straddle/strategy.py`**

In `run_backtest()`, the engine is already created before `get_entry_dates()` is called. Pass it through:

```python
entry_dates = get_entry_dates(
    data, params["start_date"], params["end_date"],
    params["dte_min"], params["dte_max"],
    params.get("calendar", "NYSE"),
    engine=engine,  # NEW
)
```

Also update the roll logic (line ~738) that calls `get_monthly_expiration()`:

```python
new_exp = get_monthly_expiration(
    eval_date, params.get("dte_min", 30), _roll_dte_max,
    params.get("calendar", "NYSE"),
    engine=engine,  # NEW
)
```

**File: `src/straddle/portfolio.py`**

Same change — pass `engine` to `get_monthly_expiration()` calls in the laddering logic (around line 386 and any other call sites).

### Step 1.4 — Update `grid_search.py` worker

In `scripts/grid_search.py`, the `_run_one()` function creates the engine but currently doesn't pass it to `get_entry_dates`. Since `run_backtest()` and `run_portfolio_backtest()` are the entry points that call `get_entry_dates` internally, this should be handled automatically if Step 1.3 is done correctly — just verify the engine is threaded through.

### Step 1.5 — Add tests

**File: `tests/test_execution_modes.py`** (add to existing file)

```python
class TestDBExpiration:
    """Verify that MarketEngine.get_db_expiration returns actual DB expirations."""
    
    def test_db_expiration_finds_valid_dte(self):
        """Given a date and DTE range, find the correct monthly expiration."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            # 2024-01-05 + DTE 30-60 -> should find 2024-02-16
            result = engine.get_db_expiration("2024-01-05", 30, 60)
            assert result == pd.Timestamp("2024-02-16")
            engine.close()
        finally:
            os.unlink(db_path)
    
    def test_db_expiration_returns_none_if_no_match(self):
        """If no expiration exists in DTE range, return None."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            # 2024-01-05 + DTE 100-120 -> no expiration in test data
            result = engine.get_db_expiration("2024-01-05", 100, 120)
            assert result is None
            engine.close()
        finally:
            os.unlink(db_path)


class TestExpirationResolution:
    """Verify that get_monthly_expiration uses DB when engine is provided."""
    
    def test_calendar_fallback_when_no_engine(self):
        """Without engine, falls back to 3rd-Friday calculation."""
        from straddle.strategy import get_monthly_expiration
        entry = pd.Timestamp("2024-01-05")
        result = get_monthly_expiration(entry, 30, 60, calendar="BVMF")
        # 3rd Friday of Feb 2024 = Feb 16
        assert result == pd.Timestamp("2024-02-16")
    
    def test_db_overrides_calendar(self):
        """When engine is provided, DB expiration takes precedence."""
        db_path = _make_test_db()
        try:
            params = _make_params("mid", db_path)
            engine = MarketEngine(params)
            from straddle.strategy import get_monthly_expiration
            entry = pd.Timestamp("2024-01-05")
            result = get_monthly_expiration(entry, 30, 60, calendar="BVMF", engine=engine)
            # Should return 2024-02-16 (from test DB)
            assert result == pd.Timestamp("2024-02-16")
            engine.close()
        finally:
            os.unlink(db_path)
```

### Step 1.6 — Verify coverage improvement

After implementing the fix, run a quick diagnostic:

```python
from straddle.params import PARAMS, apply_market_preset
from straddle.data import load_market_data
from straddle.engines import make_engine
from straddle import run_portfolio_backtest

params = dict(PARAMS)
params = apply_market_preset(params, "bova11")
params.update({
    "mode": "market",
    "start_date": "2018-01-02",
    "end_date": "2022-12-31",
    "execution_mode": "bid_ask",
    "use_cdi_ivs": True,
})

data = load_market_data("2018-01-02", "2022-12-31", market="bova11")
engine = make_engine(params)
trades, eq, _, _ = run_portfolio_backtest(data, params, engine)

db_pct = sum(1 for t in trades if t.entry_source == "db") / len(trades) * 100
print(f"Train DB coverage: {db_pct:.1f}% (was 30% before fix)")
engine.close()
```

The target is >85% DB coverage for train and >90% for holdout.

---

## Part 2: Remove `volume_filtered` Execution Mode

### Step 2.1 — Remove from `params.py`

**File: `src/straddle/params.py`**

- Remove `volume_filter_min_pct` from `PricingParams` TypedDict
- Remove `"volume_filter_min_pct": 0.50` from `PRICING` defaults
- Remove `"volume_filter_min_pct"` values from all 3 `MARKET_PRESETS` (spy, bova11, petr4)

Keep `execution_mode` and `tick_size` in `PricingParams` and defaults (they're still needed for the other 4 modes). Update docstring:

```python
execution_mode: str    # "bid_ask" | "mid_minus_1tick" | "mid" | "mid_plus_1tick"
```

### Step 2.2 — Remove from `engines.py`

**File: `src/straddle/engines.py`**

In `MarketEngine.__init__()`:
- Remove `self._volume_filter_min_pct = ...`
- Remove `self._daily_vol_threshold = 0.0` and the `if self._exec_mode == "volume_filtered"` block
- Remove the `_compute_volume_threshold()` method entirely
- Change `self.uses_real_fills = self._exec_mode in ("bid_ask", "volume_filtered")` to `self.uses_real_fills = self._exec_mode == "bid_ask"`

In `MarketEngine.get_entry_marks()`:
- Remove the `elif exec_mode == "volume_filtered":` block (the volume check and mark pricing that follows)

### Step 2.3 — Remove from `tests/test_execution_modes.py`

- Remove `TestVolumeFiltered` class (3 test methods)
- Remove `"volume_filtered"` from `TestCloseSideExecution.test_sell_side_unaffected_by_exec_mode`'s mode list (change from 5 modes to 4)

### Step 2.4 — Remove from `grid_search.py`

- If `"volume_filtered"` is explicitly handled in `_apply_grid_overrides()`, remove it. If it's just a string pass-through, no code change needed.

---

## Part 3: v5 Confirmation Grid (New Notebook)

### What you're building

A new notebook `research/2026-05-15 - B3 - v5 confirmation grid.ipynb` that:

1. Re-runs the v4 grid **with the expiration fix** to measure its impact
2. Adds a v3 reproduction cell to explain the Sharpe contradiction
3. Adds a holdout-only diagnostic for 100% DB-priced trades
4. Produces the final report

### Step 3.1 — Create the notebook with these cells

**Cell 0 — Markdown: Context**
```
# B3 v5 — Confirmation Grid (Expiration Fix + v3 Reproduction)

Fixes applied:
1. B3 BOVA11 options used 3rd-Monday expirations before May 2021. The strategy
   computed 3rd-Friday dates, causing 70% of train-period entries to fall back
   to synthetic pricing (5% adj vs 40% real spread). Now fixed: MarketEngine
   queries the DB for actual available expirations via get_db_expiration().
2. volume_filtered mode removed (was identical to mid — global percentile
   threshold of 12,900 was always exceeded by liquid 16-delta options).
3. v3 reproduction cell added to explain Sharpe contradiction.
```

**Cell 1 — Imports** (same as v4)

**Cell 2 — v5 Grid Definition** (same as v4 minus volume_filtered)
```python
GRID = {
    "target_delta": [0.16, 0.20, 0.25],
    "dte_max": [30, 45],
    "profit_target_pct": [0.50],
    "manage_at_dte": [7, 14],
    "vix_filter": ["OFF", "rv_pct:80"],
    "defensive_leg_roll": [False],
    "stop_loss_pct": [3.0],
    "execution_mode": ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"],
}
# 3 x 2 x 1 x 2 x 2 x 1 x 1 x 4 = 96 combos x 2 periods = 192 backtests
```

**Cell 3 — Run configuration** (same as v4)
```python
RUNS = [
    ("train", "bova11", "2018-01-02", "2022-12-31"),
    ("holdout", "bova11", "2023-01-02", "2025-11-30"),
]
```

**Cell 4 — Execute grid search** (cached if results exist)
```python
RESULTS_PATH = OUT_DIR / "v5_grid_search_results.parquet"
# ... same execution logic as v4, saving to v5 path ...
```

**Cell 5 — Cell A: Sharpe vs execution_mode boxplot** (same format as v4)

**Cell 6 — Cell B: Break-even execution level** (4 modes only)

**Cell 7 — Cell C: Sharpe heatmap by execution_mode x target_delta** (same as v4)

**Cell 8 — Cell D: Entry DB coverage by period and mode**
Replaces the volume_filter skip rate cell. Show `entry_db_pct` and `mtm_avg_db_pct` by period:
```python
modes = ["bid_ask", "mid_minus_1tick", "mid", "mid_plus_1tick"]
for period in ["train", "holdout"]:
    for mode in modes:
        sub = df[(df["period_label"] == period) & (df["execution_mode"] == mode)]
        print(f"  {period} {mode:20s}: entry_db_pct={sub['entry_db_pct'].mean():.1f}%, "
              f"mtm_db_pct={sub['mtm_avg_db_pct'].mean():.1f}%")
```
**Key question:** did train-period entry_db_pct improve from 30% to >85%?

**Cell 9 — Cell E: v3 Reproduction Cell**
Run the EXACT v3 configuration with the current codebase to compare:
```python
V3_GRID = {
    "target_delta": [0.16, 0.20, 0.25, 0.30, 0.50],
    "dte_max": [21, 30, 45, 60],
    "profit_target_pct": [0.25, 0.50, 0.75],
    "manage_at_dte": [7, 10, 14, 21],
    "vix_filter": ["OFF", "rv_pct:70", "rv_pct:80", "rv_pct:90", "ivr:30", "ivr:50"],
    "defensive_leg_roll": [True, False],
    "stop_loss_pct": [1.5, 2.0, 3.0],
    "execution_mode": ["bid_ask"],  # v3 was bid_ask only
}

# v3 original periods
V3_RUNS = [
    ("v3_train", "bova11", "2020-04-01", "2023-12-31"),
    ("v3_holdout", "bova11", "2024-01-01", "2025-12-31"),
]

# Also: v3 grid on v4's holdout period (to isolate period effect)
V3_ON_V4_PERIOD = [
    ("v3_on_v4_period", "bova11", "2023-01-02", "2025-11-30"),
]
```

Print:
- v3 reproduction holdout (2024-2025) median Sharpe vs documented -1.17
- v3 config on v4 period (2023-2025) median Sharpe
- This isolates whether the difference is period selection or code changes

**Cell 10 — Cell F: Spread cost analysis** (same as v4 Cell E — query DB for ask-bid/mark)

**Cell 11 — Cell G: Per-trade P&L for best config** (4 modes only)

**Cell 12 — Cell H: Period-overlap diagnostic**
Compare v5 holdout (2023-2025) vs v3 holdout (2024-2025) for the SAME parameter set to isolate the period effect.

### Step 3.2 — Run the notebook

```bash
cd /Users/oliversteiner/Documents/code/options-backtest
jupyter nbconvert --to notebook --execute "research/2026-05-15 - B3 - v5 confirmation grid.ipynb"
```

---

## Part 4: Final Report

### Step 4.1 — Write `docs/2026-05-15 - v5 confirmation results.md`

Include:

1. **Part 1 PARTIAL verdict** with caveat: 70% mark match rate, strike mismatches account for most discrepancies, all puts are EURO, 34% of calls are AMER (early exercise risk not modeled)
2. **Expiration fix impact**: Before (30% train DB) -> After (target >85% train DB)
3. **v3 reproduction results**: Confirm or refute the Sharpe contradiction
4. **Break-even execution level** (from Cell B)
5. **Spread cost** (median ~40% at 16-delta from Cell F)
6. **Volume filter removed** (was identical to mid — ineffective global threshold)
7. **Research conclusion** (A/B/C/D per plan rubric):
   - **A:** "VRP exists and is capturable at mid or better execution (limit orders)."
   - **B:** "VRP exists but is fully consumed by bid-ask spread at current B3 liquidity levels."
   - **C:** "VRP does not appear to exist even at mid-price — strategy is structurally unviable."
   - **D:** "Insufficient data to conclude — see caveats."

---

## Definition of done

- [ ] `MarketEngine.get_db_expiration()` added and tested
- [ ] `get_monthly_expiration()` accepts optional `engine` parameter, uses DB when available
- [ ] `get_entry_dates()` accepts optional `engine` parameter
- [ ] `run_backtest()` and `run_portfolio_backtest()` pass engine to expiration functions
- [ ] Train-period `entry_db_pct` improved from 30% to >85%
- [ ] `volume_filtered` mode removed from params, engine, tests, and notebook
- [ ] All existing tests pass (~104 tests)
- [ ] v5 grid search notebook created with 4 execution modes x 96 combos = 192 backtests
- [ ] v3 reproduction cell runs on v3's exact dates and grid
- [ ] v3 reproduction results compared to documented v3 values (holdout median Sharpe ~ -1.17)
- [ ] Period-overlap diagnostic cell compares same config on different holdout periods
- [ ] `docs/2026-05-15 - v5 confirmation results.md` written with conclusion A/B/C/D

---

## Deviations allowed

- If the expiration fix does not significantly improve DB coverage (e.g., stays below 80%), investigate whether `_best_row()` has additional matching issues beyond expiration date.
- If v3 reproduction holdout Sharpe is dramatically different from -1.17 even with the same codebase, suspect changes to other parameters (e.g., `use_cdi_ivs`, `open_fill_adj`) and document the differences.
- If v5 grid search shows all holdout Sharpe values are negative (including mid), the research conclusion is C.
- If the expiration fix changes holdout results significantly (vs v4), note that v4 results are invalidated and v5 is the authoritative run.
