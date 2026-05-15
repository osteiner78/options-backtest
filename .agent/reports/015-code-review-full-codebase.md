# Code Review: Full Codebase

**Target:** `src/straddle/` (all modules) + `tests/` + `scripts/runs_store.py`  
**Date:** 2026-05-14  
**Verdict:** significant issues — 2 correctness bugs, 1 silent data corruption bug, several API/design defects

---

## 🔴 Critical Issues

### 1. `_VOL_CACHE` uses `id(data)` as key — can silently return stale results

**File:** `src/straddle/strategy.py:19,28-29`

```python
_VOL_CACHE: dict = {}  # key: (id(data), mode, threshold) → bool Series

cache_key = (id(data), mode, threshold)
if cache_key in _VOL_CACHE:
    return _VOL_CACHE[cache_key]
```

`id()` returns the memory address of an object. Python can and does reuse addresses after garbage collection. If a prior backtest's `data` DataFrame is GC'd and a new one is allocated at the same address, the cache returns the previous filter result applied to the wrong data. The cache is also module-level global and **never cleared**, so it persists across multiple `run_backtest()` calls in the same process (e.g., grid search, the API server, Jupyter notebooks running multiple cells).

**Concrete failure scenario:** grid search runs backtest A (market=bova11, mode=rv_pct), then backtest B with a fresh `data` slice that happens to land at the same address. Backtest B gets the vol filter from backtest A.

**Fix:**
```python
# Option A: hash the data index range (cheap, sufficient uniqueness)
cache_key = (id(data), data.index[0], data.index[-1], mode, threshold)

# Option B: expose a clear function for the API/grid search caller
def clear_vol_cache() -> None:
    _VOL_CACHE.clear()
```

**Confidence:** certain (Python address reuse is documented behaviour)

---

### 2. Force-close in `run_portfolio_backtest` double-appends to `daily_marks`

**File:** `src/straddle/portfolio.py:473-484`

```python
# After the main daily loop:
for trade_num_open, pos in list(portfolio.open_positions.items()):
    t = pos.trade
    res = evaluate_trade_step(t, last_date, data, engine, params)  # ← called again
    t.exit_date = last_date
    ...
```

`evaluate_trade_step` unconditionally appends to `trade.daily_marks` at line 652 of `strategy.py`:
```python
trade.daily_marks.append((eval_date, pnl))
```

In the main simulation loop, `evaluate_trade_step` was already called for `last_date` for every open position (line 316). The force-close block then calls it **a second time** for the same date. The result is two entries with identical `eval_date` in `daily_marks`, which corrupts `_compute_mtm_equity` in `metrics.py`:

```python
df = pd.DataFrame(records).sort_values(["trade", "date"])
df["prev"] = df.groupby("trade")["mark"].shift(1).fillna(0.0)
df["delta"] = df["mark"] - df["prev"]
```

With duplicate date entries the `delta` computation is wrong — the second entry's "prev" becomes the pnl of the first entry for that date (within-day shift), producing a spurious P&L delta on the last day.

**Fix:** Do not call `evaluate_trade_step` again in force-close. Reuse the marks already computed in the final main-loop iteration:

```python
# Store the last result per trade_num during the main loop
_last_res: dict[int, TradeStepResult] = {}
# ... in the main loop else branch:
_last_res[trade_num_open] = res

# Force-close block:
for trade_num_open, pos in list(portfolio.open_positions.items()):
    t = pos.trade
    res = _last_res.get(trade_num_open)
    if res is None:
        continue  # trade entered on the very last day, no prior mark
    t.exit_date = last_date
    t.exit_dte = (t.expiration - last_date).days
    t.exit_type = "FORCE_CLOSE"
    t.pnl = res.pnl
    t.pnl_pct = res.pnl_pct
    portfolio.available_cash -= res.close_cost
    portfolio.remove_position(t.trade_num)
    trades.append(t)
```

**Confidence:** certain — the double-append is visible by inspection, and `_compute_mtm_equity` has no deduplication logic

---

### 3. Bare `except: pass` swallows all exceptions in `__del__`

**File:** `src/straddle/engines.py:912-916`

```python
def __del__(self) -> None:
    try:
        self.close()
    except:
        pass
```

This silently suppresses every possible exception including `SystemExit`, `KeyboardInterrupt`, and `MemoryError`. If `close()` raises because the connection is already closed or the object was partially initialised, the error is invisible.

**Fix:**
```python
def __del__(self) -> None:
    try:
        self.close()
    except Exception:
        pass
```

**Confidence:** certain (Python anti-pattern, `except:` vs `except Exception:`)

---

## 🟡 Important Issues

### 4. API `_PARAM_REMAP` maps `risk_free_rate → cash_yield_annual` — extremely confusing

**File:** `src/straddle/api.py:37-43`

```python
_PARAM_REMAP = {
    "pricing_mode":      "mode",
    "pricing_risk_free": "risk_free_rate",
    "risk_free_rate":    "cash_yield_annual",   # ← this
}
```

An API caller who sends `{"risk_free_rate": 0.05}` expecting to set the option-pricing risk-free rate will silently set `cash_yield_annual` (the cash return on idle portfolio funds) instead. The actual pricing rate is controlled by `pricing_risk_free`. This naming is a trap: the field that looks like the obvious one does the unexpected thing.

Additionally, `BacktestRequest` does not expose `pricing_risk_free` as a direct field either (it uses the remap), so the API documentation would need to explain this non-obvious pairing.

**Fix:** Rename the API field. At minimum, add a note in the Pydantic model:
```python
risk_free_rate: Optional[float] = Field(
    default=None, ge=0, le=0.2,
    description="Annual yield on idle cash (NOT the option-pricing rate; use pricing_risk_free for that)"
)
```

**Confidence:** certain

---

### 5. IVR vol-filter logic appears inverted

**File:** `src/straddle/strategy.py:54-61`

```python
elif mode == "ivr":
    atm_iv = data.get("vix_close", pd.Series(0, index=dates))
    result = pd.Series(True, index=dates)   # ← everything blocked by default
    for i in range(252, len(atm_iv)):
        window = atm_iv.iloc[max(0, i - 252):i + 1]
        ivr_val = (atm_iv.iloc[i] < window.values).mean()  # fraction of window ABOVE current
        result.iloc[i] = ivr_val < (threshold / 100.0)     # BLOCK when ivr_val is LOW
```

`ivr_val` = fraction of the past 252-day window with IV **above** the current IV.

- Current IV at the **80th percentile** → `ivr_val ≈ 0.20` (20% of window exceeds it) → blocked if `0.20 < threshold/100`
- Current IV at the **20th percentile** → `ivr_val ≈ 0.80` → allowed if `0.80 >= threshold/100`

This blocks entries when IV is **high**, and allows entries when IV is **low** — the opposite of what a vol-targeting short-premium strategy wants. The parameter description in `params.py` says "min IVR for 'ivr'" which implies entries should be blocked below a minimum IV level. The correct condition would be:

```python
# Block when current IV is BELOW the threshold percentile (too little premium)
result.iloc[i] = ivr_val > (1.0 - threshold / 100.0)
```

First 252 days are also completely blocked (the default `pd.Series(True, ...)` is never updated for `i < 252`), which is inconsistent with `rv_pct` mode (which starts unblocked for the same warm-up period).

**Confidence:** likely (mode is experimental; intent could differ from standard IVR semantics)

---

### 6. `upsert_run` overwrites `created_at` on every status update

**File:** `src/straddle/runs_store.py:33-50`

```python
conn.execute("""
    INSERT INTO runs (run_id, created_at, ...)
    VALUES (?, ?, ...)
    ON CONFLICT(run_id) DO UPDATE SET
        status      = excluded.status,
        label       = excluded.label,
        params_json = excluded.params_json,
        result_json = excluded.result_json
""", (run_id, datetime.now(timezone.utc).isoformat(), ...))
```

`created_at` is not in the `DO UPDATE SET` clause, so the `excluded.created_at` value (current timestamp) is **not** applied on conflict. However, `datetime.now()` is always passed as the second positional parameter and would be the `created_at` on initial insert. This is correct — `created_at` is set once at INSERT and not overwritten on UPDATE.

Actually, upon closer inspection this is fine. `ON CONFLICT DO UPDATE` for `created_at` is absent, so it keeps the original value. This issue is less severe than initially assessed.

**Revised finding (🟢):** The logic is correct but the `label` field is reset to `None` on every status update because `upsert_run(run_id, "running", params)` passes `label=None`. If a user labels a run while it's running, the label is erased when the status updates to "completed". Fix: only update label when it is not None:

```python
# In the UPDATE clause:
label = CASE WHEN excluded.label IS NULL THEN label ELSE excluded.label END,
```

**Confidence:** certain

---

### 7. `runs_store.py` uses a CWD-relative path for the SQLite database

**File:** `src/straddle/runs_store.py:8`

```python
_DB_PATH = Path("data/runs.db")
```

This resolves relative to whatever the process's current working directory is at startup. If the API server is launched from a different directory (e.g., `python -m straddle.api` from `/tmp`), the DB is created there. `engines.py` uses `Path(__file__).resolve().parent.parent.parent` to anchor paths to the project root; `runs_store.py` should do the same.

**Fix:**
```python
_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "runs.db"
```

**Confidence:** certain

---

### 8. No validation that `dte_min < dte_max` in API request

**File:** `src/straddle/api.py:55-56`

```python
dte_min: Optional[int] = Field(default=None, ge=0, le=365)
dte_max: Optional[int] = Field(default=None, ge=0, le=365)
```

If a caller sends `{"dte_min": 60, "dte_max": 30}`, the backtest runs silently with no entries (every `get_monthly_expiration` call returns `None` since no DTE falls in `[60, 30]`). The result is an empty trade list with misleading metrics rather than a clear error.

**Fix:**
```python
@model_validator(mode='after')
def check_dte_order(self) -> 'BacktestRequest':
    if self.dte_min is not None and self.dte_max is not None:
        if self.dte_min >= self.dte_max:
            raise ValueError("dte_min must be less than dte_max")
    return self
```

**Confidence:** certain

---

### 9. `_TRADING_DAY_SETS` and `_DB_LAST_CACHE` are module-level globals that never expire

**File:** `src/straddle/strategy.py:94`, `src/straddle/data.py:201`

Both caches are computed once and never invalidated. `_TRADING_DAY_SETS` is populated over 2005–2030 on first use, which is fine. `_DB_LAST_CACHE` caches the last date in the options DB — if a new DB is attached during a server session (e.g., after a data update), the stale max date is returned. These are low-risk in practice but can create subtle bugs in long-lived server processes.

**Fix:** expose `clear_caches()` functions for testing and for the API to call when the DB path changes.

**Confidence:** speculative for _DB_LAST_CACHE in practice; certain as a design smell

---

### 10. `sigma = 0` path crashes BAW American pricing

**File:** `src/straddle/engines.py:135-143`

```python
def _baw_q2(r: float, sigma: float, T: float, q: float = 0.0) -> float:
    h = 1.0 - np.exp(-r * T)
    if h < 1e-10:
        return -1e9
    M = 2.0 * r / sigma**2   # ← ZeroDivisionError if sigma=0
    N = 2.0 * (r - q) / sigma**2
```

`american_put_baw` doesn't validate `sigma > 0` before calling `_baw_q2`. `_baw_critical_put` also computes `sigma * np.sqrt(T)` in the denominator of `d1`. A zero-vol option is edge-case but can occur with corrupted data.

**Fix:**
```python
def american_put_baw(S, K, T, r, sigma, q=0.0) -> float:
    intrinsic = max(K - S, 0.0)
    if T < 1e-7 or r < 1e-8 or sigma < 1e-8:
        return max(bs_price(S, K, T, r, sigma, "put", q), intrinsic)
    ...
```

**Confidence:** certain (the code path; the practical probability of sigma=0 is low)

---

### 11. `apply_market_preset` can silently discard explicit caller overrides

**File:** `src/straddle/params.py:289-295`

```python
spy_defaults = {k: MARKET_PRESETS["spy"].get(k) for k in preset}
extras = {k: v for k, v in params.items() if k not in preset or params[k] != spy_defaults.get(k)}
merged.update({k: v for k, v in extras.items() if k not in preset})  # only non-preset extras
```

"Extras" are identified by comparing the current param value against the **SPY preset** defaults. Two failure modes:

1. A caller explicitly sets `tick_size=0.01` (same as SPY default). When switching to `bova11`, the comparison `params["tick_size"] != spy_defaults["tick_size"]` → `0.01 != 0.01` → False → not treated as an explicit override → bova11's `tick_size=0.05` wins.

2. `extras` are then filtered to only those `k not in preset`. Since `tick_size` IS in the bova11 preset, even if it made it into extras, it would be dropped by this final filter.

The intent is right (protect non-market overrides like `--start` date), but the mechanism silently drops legitimate market-key overrides.

**Confidence:** likely (by design for most cases, but the edge case is a footgun)

---

## 🟢 Suggestions

### S1. `vol_filter_mode` / `vol_filter_threshold` missing from `StrategyParams` TypedDict

**File:** `src/straddle/params.py:22-35`

These keys are present in the `STRATEGY` dict and used in `strategy.py`, but not declared in `StrategyParams`. Same for `vix_entry_max` in `STRATEGY` vs. the TypedDict. TypedDicts with `total=False` don't enforce missing keys at runtime, but IDE type-checkers and `mypy` will miss these.

---

### S2. `american_options` not in base `PARAMS` dict

**File:** `src/straddle/params.py:310-313`

```python
PARAMS: dict = {**BACKTEST, **STRATEGY, **PRICING, **OVERSHOOT, **PORTFOLIO, **MARKET, **PAPER_TRADING}
```

`american_options` is only added via `apply_market_preset`. Callers using `PARAMS` directly (e.g. in tests) get `SyntheticEngine.american = False` via the default fallback, which is correct for SPY but the omission from base `PARAMS` is inconsistent. A `"american_options": False` entry in `PRICING` would make it explicit.

---

### S3. `brentq` import inside hot function

**File:** `src/straddle/engines.py:176-177`

```python
def _baw_critical_put(...):
    ...
    from scipy.optimize import brentq as _brentq
```

Python caches module imports, but this is a dictionary lookup on every call. For PETR4 backtests with American puts, this function is called on every daily mark. Move the import to the module top level.

---

### S4. `_build_metrics_response` uses `params["cash_investment_mode"]` without `.get()`

**File:** `src/straddle/api.py:148`

```python
cash_mode = params["cash_investment_mode"]
underlying_alloc = params["underlying_allocation_pct"]
```

These are hard indexing into `params`. If `run_backtest` (non-portfolio mode) is used and these keys aren't in `params`, this raises `KeyError`. The single-position backtest path goes through `_build_metrics_response`, which then calls `cash_yield_earned` logic even though it doesn't apply. Use `.get()` with defaults.

---

### S5. `MetricsResponse` fields packed onto single lines in api.py

**File:** `src/straddle/api.py:118-129`

Multiple fields per line makes this class hard to read, extend, and diff. Standard formatting would put one field per line.

---

### S6. Global `_results` dict accumulates completed runs indefinitely

**File:** `src/straddle/api.py:30`

Completed runs are trimmed to minimal state (no payload), but the dict still grows by one entry per run. In a long-running server session this is a minor memory leak. A TTL or LRU eviction would prevent it from growing without bound.

---

## Top 3 to Fix First

1. **Issue #2** — Force-close double-appending to `daily_marks` in `run_portfolio_backtest`. This silently corrupts the MTM equity calculation for any portfolio backtest where trades remain open at the end of the window.

2. **Issue #1** — `id(data)` as vol-filter cache key. Any grid search or multi-run API session can silently apply the wrong vol filter to a backtest, producing unreproducible results.

3. **Issue #4** — `_PARAM_REMAP` naming. `risk_free_rate` → `cash_yield_annual` will confuse every API integrator. This is a correctness trap that produces no error but wrong behaviour.

---

## Architectural Concerns

- **Module-level mutable globals** (`_VOL_CACHE`, `_TRADING_DAY_SETS`, `_DB_LAST_CACHE`) make the library stateful between calls. Grid search scripts and the API server share this state across backtest runs. Consider a context object or explicit cache-clear APIs.

- **`PARAMS` dict is incomplete without `apply_market_preset`**: Several keys used by engines (`american_options`, per-market `tick_size`) are not in base `PARAMS`. Callers who skip `apply_market_preset` get silent fallback behaviour. Consider making `PARAMS` self-contained for the default (SPY) market.

- **No thread safety guarantees for the FastAPI background task + `_results` dict**: CPython's GIL makes simple dict ops effectively atomic, but compound operations (read → check → write) are not. The current architecture is safe at the scale described (one background thread per run), but documentation of this assumption would help future maintainers.

- **`vol_filter_mode` feature is undertested**: `rv_pct` and `ivr` modes have no unit tests. The IVR logic appears inverted (Issue #5), which would have been caught by a simple test confirming that low-IV periods are blocked.

---

## Untested Paths

| Area | Gap |
|------|-----|
| `american_put_baw` / `_baw_critical_put` | No unit tests verifying against known analytical values |
| `apply_market_preset` override precedence | No test for the edge case where an explicit override equals the SPY default |
| `vol_filter_mode` = `rv_pct` / `ivr` | No tests at all |
| Force-close at backtest end | Not tested in isolation (portfolio mode) |
| `_load_b3_from_parquet` / `_load_spy_from_yahoo` | No tests (Yahoo Finance / file presence skipped) |
| `run_portfolio_backtest` integration | Only unit-level portfolio tests; no end-to-end run |
| `upsert_run` label-preservation on status update | Not tested |
| `get_entry_dates` with DB-backed engine | No test that DB expiration lookup overrides calendar |
