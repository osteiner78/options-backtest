# Code Review: `src/`

**Target:** `src/straddle/` (10 modules, ~5,000 lines)  
**Date:** 2026-05-15  
**Verdict:** Significant issues — two critical bugs in metrics code affect Sharpe accuracy; several important maintainability concerns.

---

## 🔴 Critical

### 1. `_compute_sharpe_from_daily_pnl` omits risk-free rate subtraction

**File:** `src/straddle/metrics.py:194-202`

```python
def _compute_sharpe_from_daily_pnl(daily_pnl: pd.Series, init: float) -> float:
    if len(daily_pnl) < 2:
        return 0.0
    equity = init + daily_pnl.cumsum()
    daily_ret = equity.pct_change().dropna()
    if daily_ret.std(ddof=1) <= 0:
        return 0.0
    return float(daily_ret.mean() / daily_ret.std(ddof=1) * np.sqrt(252))
```

The Sharpe formula here is `mean(ret) / std(ret) * sqrt(252)` — this is an information ratio, not a Sharpe ratio. Compare with `_compute_equity_stats` (line 142-146) which correctly does:

```python
rf_daily = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT) / 252
sharpe = float((daily_pct.mean() - rf_daily) / daily_pct.std(ddof=1) * np.sqrt(252))
```

`_compute_sharpe_from_daily_pnl` is called by `compute_portfolio_metrics` (line 388) to override the equity-curve Sharpe. The grid search uses `compute_portfolio_metrics` when `portfolio_mode="laddering"` — which is the v7 grid search mode. For B3 markets with ~10% CDI, the missing subtraction overstates Sharpe by approximately:

- Daily: mean(ret) vs mean(ret) - 0.0004 (10% / 252)
- Annualized: ~0.06 Sharpe units (varies with vol)

**This affects all v7 portfolio-mode Sharpes stored in `v7_grid_search_results.parquet`.** The I-10 correction applied post-grid may compensate for this, but the code itself still produces wrong values for any future runs.

**Fix:**

```python
def _compute_sharpe_from_daily_pnl(
    daily_pnl: pd.Series, init: float, rf_annual: float = 0.045
) -> float:
    if len(daily_pnl) < 2:
        return 0.0
    equity = init + daily_pnl.cumsum()
    daily_ret = equity.pct_change().dropna()
    if daily_ret.std(ddof=1) <= 0:
        return 0.0
    rf_daily = rf_annual / 252.0
    return float((daily_ret.mean() - rf_daily) / daily_ret.std(ddof=1) * np.sqrt(252))
```

And at the call site (`compute_portfolio_metrics` line 388):

```python
rf = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT)
results["sharpe"] = _compute_sharpe_from_daily_pnl(daily_pnl, init, rf)
```

**Confidence:** Certain. The formula is objectively wrong — standard Sharpe definition requires excess returns over the risk-free rate.

---

### 2. `_compute_equity_stats` uses hardcoded risk-free rate, not data-driven daily values

**File:** `src/straddle/metrics.py:127-163`

```python
def _compute_equity_stats(equity_series: pd.Series, params: dict) -> Dict:
    ...
    rf_daily = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT) / 252
    ...
    sharpe = float((daily_pct.mean() - rf_daily) / daily_pct.std(ddof=1) * np.sqrt(252))
```

The function uses `params.get("risk_free_rate", ...)` which for B3 markets is always 0.045 (the US default — `RISK_FREE_RATE_DEFAULT`). The B3 MARKET_PRESETS (`params.py:208,239`) do NOT set `risk_free_rate`. Meanwhile, the data DataFrame has a `risk_free_rate` column with actual daily CDI values (~10-14% annually).

Compare with `_compute_benchmark_stats` (line 36-38) which correctly uses data-driven rates:

```python
_rf = data.loc[_daily.index, "risk_free_rate"] / 252
underlying_sharpe = float(
    ((_daily - _rf).mean() / _daily.std(ddof=1)) * np.sqrt(252)
)
```

The root cause is that `_compute_equity_stats` doesn't receive the `data` DataFrame — it only gets `equity_series` and `params`. The function contract needs expanding.

**Fix:** Add `data: pd.DataFrame = None` parameter, and use data-driven rates when available:

```python
def _compute_equity_stats(equity_series, params, data=None):
    ...
    if data is not None and "risk_free_rate" in data.columns:
        rf_series = data.loc[daily_pct.index, "risk_free_rate"]
        rf_daily = rf_series / 252.0
    else:
        rf_daily = params.get("risk_free_rate", RISK_FREE_RATE_DEFAULT) / 252.0
    ...
```

Update call sites in both `compute_metrics` (line 315) and `compute_portfolio_metrics` (line 378) to pass `data`.

**Confidence:** Certain. The benchmark and strategy Sharpe use different risk-free rate sources, and for B3 markets the difference is ~5-8 percentage points annual.

---

## 🟡 Important

### 3. `evaluate_trade` fallback expiry path duplicates intrinsic calculation

**File:** `src/straddle/strategy.py:973-998`

This fallback path computes expiry intrinsic value and commissions identically to the `dte_rem == 0` branches in `evaluate_trade_step` (lines 850, 857). The duplication covers iron condor branching (lines 979-985) and commission handling (lines 983-988).

The fallback only triggers when the daily evaluation loop never executes (entry date IS the last trading day and no step iteration occurs). It's a narrow edge case, but the duplication means any change to expiry handling in `evaluate_trade_step` must be mirrored here.

**Proposed fix:** Extract `_compute_expiry_pnl(trade, underlying_close, params)` as a shared function, or delegate to `evaluate_trade_step` with `dte_rem=0`.

**Confidence:** Likely. Edge case, but the duplication is real and could cause silent drift.

---

### 4. `_check_21dte_roll` 21DTE exit pnl/pnl_pct rounding inconsistency

**File:** `src/straddle/strategy.py:771-772`

```python
pnl=round(trade.net_credit - close_cost, 2),
pnl_pct=(trade.net_credit - close_cost) / trade.net_credit,
```

`pnl` is rounded to 2 decimal places but `pnl_pct` is computed from the un-rounded value. This means `pnl_pct != pnl / trade.net_credit` in some cases (e.g., if `close_cost` has fractional cents). Other exit paths (STOP, PROFIT, EXPIRY in `evaluate_trade_step`) have the same pattern:

```python
# evaluate_trade_step lines 877, 893
pnl=round(pnl, 2), pnl_pct=pnl_pct
```

Here `pnl_pct` was computed BEFORE rounding at line 859. The inconsistency means downstream consumers can't reliably compute `pnl == round(pnl_pct * trade.net_credit, 2)`.

**Proposed fix:** Compute pnl_pct from the rounded pnl, or don't round pnl:

```python
fill_pnl_r = round(fill_pnl, 2)
pnl=fill_pnl_r,
pnl_pct=fill_pnl_r / trade.net_credit,
```

**Confidence:** Likely. Observable in output data but unlikely to affect practical decisions (rounding difference is at most 0.5 cent on pnl_pct).

---

### 5. Module-level caches create side-channel coupling in API server

**File:** `src/straddle/strategy.py:19,113` and `src/straddle/data.py:201`

Three module-level mutable caches exist:
- `_VOL_CACHE: dict` (strategy.py:19) — vol-filter boolean Series
- `_TRADING_DAY_SETS: dict` (strategy.py:113) — trading-day frozensets
- `_DB_LAST_CACHE: dict` (data.py:201) — DB coverage end dates

The API server (`api.py`) is a long-lived FastAPI process. Multiple concurrent backtest requests with different parameters (e.g., different VIX thresholds, different calendars) share these caches in the same process. The vol-filter cache key uses `(data.index[0], data.index[-1], mode, threshold)` — if two concurrent backtests use the same date range but different data, the first cache hit could return wrong results for the second.

The trading-day-set cache keyed by calendar name is safer (calendars are deterministic). The DB-last-date cache is keyed by db_path and read-only.

**Proposed fix:** Already flagged in refactor scan #6. Move caches into a per-backtest context object rather than module-level globals.

**Confidence:** Likely for vol-filter cache in concurrent scenario; speculative for actual production impact (API server probably processes backtests sequentially in background tasks).

---

### 6. Equity curve building drops marks outside backtest window

**File:** `src/straddle/strategy.py:1129`

```python
if this_date in daily_pnl.index:
    daily_pnl[this_date] += this_val - prev_val
```

For trades that extend beyond `end_date` (force-closed at end_date), intermediate marks between `end_date` and the true exit date are silently dropped. The total P&L is still correct (the final contribution is captured), but the *distribution* of P&L across days is distorted — all remaining P&L delta is attributed to the last in-range day rather than spread across actual days. This inflates the daily volatility on the final day and affects drawdown computation.

**Proposed fix:** Clamp processed marks to the backtest window rather than silently dropping out-of-window dates. Accumulate out-of-window P&L deltas and add to the last in-range day.

**Confidence:** Certain for the behavior; low for practical impact (affects last day's contribution only).

---

## 🟢 Suggestion

### 7. `_compute_mtm_equity` uses defensive `getattr` when field is always present

**File:** `src/straddle/metrics.py:178`

```python
marks = getattr(t, "daily_marks", []) or []
```

`Trade` is a dataclass with `daily_marks` as a required field (default_factory=list, strategy.py:353). The `getattr` with default suggests the field might be missing, but it's always initialized. Remove the defensive pattern for clarity:

```python
marks = t.daily_marks or []
```

**Confidence:** Certain. Dataclass invariant is guaranteed.

---

### 8. `_build_metrics_response` guards against `years=0` with arbitrary 0.01 minimum

**File:** `src/straddle/api.py:195`

```python
if years <= 0: years = 0.01
```

If `start_date == end_date`, years=0, and `years=0.01` produces `ann = (1 + tot) ** 100 - 1` — wildly wrong annualization. A better approach:

```python
if years <= 0:
    return MetricsResponse(..., annualized_return=0.0, ...)
```

**Confidence:** Certain. Edge case only (start==end), but current behavior is silently wrong.

---

### 9. `_load_b3_from_parquet` silently truncates end_date when outside coverage

**File:** `src/straddle/data.py:160-165`

```python
if req_end > data_end:
    print(f"WARNING: ...")
    req_end = data_end
```

This prints a warning to stdout but doesn't raise or return an error. In the API server, stdout output goes to the server log which may not be monitored. The caller receives silently truncated data with no programmatic indication.

**Proposed fix:** Return a result with a flag, or raise on strict mode, or at minimum use `logging.warning()` instead of `print()`.

**Confidence:** Likely. Could cause confusion when backtest output shows fewer trades than expected.

---

## Top 3 to Fix First

1. **🔴 `_compute_sharpe_from_daily_pnl` missing risk-free rate** — Fix is 3 lines. Impact: all v7 portfolio-mode Sharpes in the parquet are wrong. Recompute and verify against research notebook's I-10 corrected values.

2. **🔴 `_compute_equity_stats` hardcoded risk-free rate** — Add `data` parameter. Impact: single-position mode Sharpes for B3 markets use wrong rate. Fix in tandem with #1.

3. **🟡 `evaluate_trade` fallback expiry duplication** — Extract shared function. Impact: prevents future drift; low risk because edge case is rare.

---

## Architectural Concerns

1. **Two Sharpe computation paths have diverged.** `_compute_equity_stats` correctly subtracts risk-free rate but uses hardcoded value. `_compute_sharpe_from_daily_pnl` uses running-equity denominator (I-10 fix applied) but omits risk-free rate entirely. Both are used by different metrics functions. Neither is fully correct for all modes. A single canonical Sharpe function that: (a) uses data-driven daily risk-free rates, (b) computes from running equity, and (c) is used by both `compute_metrics` and `compute_portfolio_metrics` — this would eliminate both bugs and the duplication permanently.

2. **The risk-free rate handling is inconsistent across the codebase.** `RISK_FREE_RATE_DEFAULT = 0.045` is the US default. B3 market presets don't override it. The data layer provides correct daily values but the metrics layer ignores them. The strategy layer (`evaluate_trade_step`) correctly uses daily values via `row_d.get("risk_free_rate", r_default)`. This three-way inconsistency is a symptom of the flat `params` dict (#3 in refactor scan) — there's no single way to get the risk-free rate.

---

## Untested Areas

- **`_check_stop_overshoot` with gap detection** — No unit test exercises the `prev_idx == 0` (first entry in data) edge case or the `gap_pnl_dollar <= trigger_pnl_dollar` (GAP regime) path.
- **`_check_21dte_roll` with vol-filter blocking** — No test verifies roll is correctly gated by `is_vol_blocked`.
- **`_compute_mtm_equity` with trades that have missing `daily_marks`** — The `[] or []` guard suggests this was once possible, but no test exercises it.
- **Concurrent API backtest requests** — No test verifies that `_VOL_CACHE` and `_TRADING_DAY_SETS` don't collide between concurrent runs.
