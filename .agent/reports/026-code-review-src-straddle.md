# Code Review: src/straddle/

**Target**: `src/straddle/` (strategy.py, engines.py, data.py, params.py, metrics.py, portfolio.py, api.py, plotting.py, runs_store.py, __init__.py)
**Date**: 2026-05-17
**Verdict**: **significant issues** — one confirmed P&L bug in force-close path, plus thread-safety and correctness concerns

---

## Issues

### 1. 🔴 Force-close P&L is always 0 in single-position mode

**File**: `strategy.py:970-976`
**Confidence**: certain

When `evaluate_trade()` force-closes a trade at `force_close_at`, it reads `res.pnl` from the `TradeStepResult`. But for non-exited trades, `TradeStepResult.pnl` defaults to `0.0` — it is only populated for exited trades (PROFIT, STOP, 21DTE, EXPIRY). The actual unrealized P&L is available as `trade.net_credit - res.close_cost`, which is exactly what `portfolio.py:522` computes correctly.

```python
# strategy.py:970-976 — BUG: res.pnl is 0.0 for non-exited trades
if force_close_at is not None and eval_date == force_close_at:
    trade.exit_date = eval_date
    trade.exit_dte = (expiration - eval_date).days
    trade.exit_type = "FORCE_CLOSE"
    trade.pnl = res.pnl          # ← always 0.0
    trade.pnl_pct = res.pnl_pct  # ← always 0.0
    trade.exit_source = res.exit_db_source
    return trade, None
```

**Fix**:
```python
    trade.pnl = round(trade.net_credit - res.close_cost, 2)
    trade.pnl_pct = trade.pnl / trade.net_credit if trade.net_credit else 0.0
```

**Impact**: Any trade whose expiration extends past the backtest end date gets P&L=0 in metrics. The equity curve (built from `daily_marks`) is unaffected, but trade-level stats (win rate, avg P&L, exit-type breakdown) are wrong for force-closed trades.

---

### 2. 🔴 Dict mutation during iteration in `_evict_results`

**File**: `api.py:41-46`
**Confidence**: certain

```python
def _evict_results() -> None:
    while len(_results) > _RESULTS_MAX_SIZE:
        for run_id, entry in _results.items():
            if entry.get("status") not in ("pending", "running"):
                del _results[run_id]   # ← mutating dict during .items() iteration
                break
        else:
            break
```

`del _results[run_id]` modifies the dict while iterating over `_results.items()`. In CPython 3, this can raise `RuntimeError: dictionary changed size during iteration`. The `break` immediately follows, so the iterator is abandoned before `next()` is called — making this safe in practice on CPython. However, it is undefined per the language spec and will break under alternative implementations or future Python versions.

**Fix**:
```python
def _evict_results() -> None:
    while len(_results) > _RESULTS_MAX_SIZE:
        evict_id = None
        for run_id, entry in _results.items():
            if entry.get("status") not in ("pending", "running"):
                evict_id = run_id
                break
        if evict_id is None:
            break
        del _results[evict_id]
```

---

### 3. 🟡 Global mutable `_VOL_CACHE` survives across backtests in long-lived server

**File**: `strategy.py:19`
**Confidence**: likely

```python
_VOL_CACHE: dict = {}  # key: (index[0], index[-1], mode, threshold) → bool Series
```

In the API server, the cache key includes `index[0]` and `index[-1]`. If two backtest requests use different date ranges against the same data DataFrame, the cache will have different keys and work correctly. But if the same date range is used with different `vol_filter_threshold` values (e.g. during a grid search), the old entries persist indefinitely, wasting memory.

More importantly, `clear_vol_cache()` must be called explicitly. If a user changes `vol_filter_mode` between requests, stale cached results will be served because the cache key does not include the mode string in a way that distinguishes `vix` from `rv_pct` outcomes — actually it does (`mode` is in the key). So the cache is correct but grows without bound.

**Fix**: Consider using `functools.lru_cache` with a bounded size, or clearing `_VOL_CACHE` in `run_backtest()` / `run_portfolio_backtest()` at the start.

---

### 4. 🟡 `_TRADING_DAY_SETS` cache is never invalidated

**File**: `strategy.py:113`
**Confidence**: likely

```python
_TRADING_DAY_SETS: dict = {}  # calendar_name -> frozenset[pd.Timestamp]
```

This cache is built once and never cleared. If the `clear_strategy_caches()` function is called (which clears it), but in practice the cache grows per calendar name and never shrinks. Since there are typically only 1-2 calendars (NYSE, BVMF), this is a minor memory concern. The real problem would arise if the cache were populated with a calendar object that had wrong valid-day ranges, but the current code uses fixed date ranges (2005-2030), so this is benign.

**Fix**: Low priority, but the 2005-2030 range in `_get_trading_day_set` is hardcoded. If backtests are run for dates outside this range, trading-day adjustment will silently fail.

---

### 5. 🟡 `plotting.py:250` calls `plt.show()` unconditionally

**File**: `plotting.py:250`
**Confidence**: certain

```python
plt.savefig(output_path, dpi=150, bbox_inches="tight")
plt.show()
```

In a headless server or CI environment, `plt.show()` will raise or hang. The backtest CLI script calls `plot_backtest()` which calls this. If `--no-plot` is passed, this function isn't called, but the unconditional `plt.show()` is still wrong for a library function.

**Fix**:
```python
plt.savefig(output_path, dpi=150, bbox_inches="tight")
if plt.isinteractive():
    plt.show()
plt.close(fig)
```

---

### 6. 🟡 `plotting.py:73-75` hardcodes strategy parameters in title

**File**: `plotting.py:73-75`
**Confidence**: certain

```python
f'SPY Short Strangle Backtest  [{params["start_date"]} → {params["end_date"]}]\n'
f"16Δ | 30–45 DTE | 50% profit | 200% stop | 21 DTE close | $50k account",
```

The subtitle hardcodes `16Δ`, `30–45 DTE`, `50% profit`, `200% stop`, etc., even though all these values are available in `params`. If the user changes `target_delta` or `profit_target_pct`, the title will be wrong.

**Fix**: Derive from `params`:
```python
f'{params["target_delta"]*100:.0f}Δ | {params["dte_min"]}–{params["dte_max"]} DTE | '
f'{params["profit_target_pct"]*100:.0f}% profit | {params["stop_loss_pct"]*100:.0f}% stop | '
f'{params["manage_at_dte"]} DTE close | ${params["initial_balance"]:,.0f} account'
```

---

### 7. 🟡 Iron condor daily-mark close cost uses wrong fill-adj label

**File**: `strategy.py:838-855`
**Confidence**: likely

```python
if trade.is_iron_condor:
    long_put_mid_d = engine.get_leg_mark(
        trade.long_put_strike, S_d, dte_rem, vix_d, r_d, "put",
        ctx=ctx, buy_or_sell="sell",
    )
    long_call_mid_d = engine.get_leg_mark(
        trade.long_call_strike, S_d, dte_rem, vix_d, r_d, "call",
        ctx=ctx, buy_or_sell="sell",
    )
    long_mid_d = long_put_mid_d + long_call_mid_d
    mid_d = short_mid_d - long_mid_d
    _mult = params.get("contract_multiplier", 100.0)
    if dte_rem > 0:
        close_cost = (
            engine.apply_fill_adj(short_mid_d, "close")
            - engine.apply_fill_adj(long_mid_d, "open")   # ← uses "open" adj
        ) * _mult + 4.0 * comm
```

The `apply_fill_adj(long_mid_d, "open")` applies the "sell-to-open" adjustment (`mid * 0.95`). When closing long legs, you sell them — you receive less, which IS conservative. The semantics are correct mathematically (you receive less = net cost is higher), but the label is misleading: "open" suggests opening a position rather than closing one.

The confusion is that `apply_fill_adj` labels refer to the *direction of the fill* not the *position action*: "open" = "I receive less credit" and "close" = "I pay more debit". For selling to close a long, you receive less credit, which maps to "open" adjustment.

**Impact**: The math is correct. This is a readability/maintainability concern, not a bug. The naming convention should be documented or renamed (e.g., "credit_adj" / "debit_adj").

---

### 8. 🟡 `data.py` parquet cache has no file-level locking

**File**: `data.py:118-124`
**Confidence**: likely

```python
master_df = pd.concat([master_df, new_data])
master_df = master_df[~master_df.index.duplicated(keep="last")].sort_index()
master_df["risk_free_rate"] = (
    master_df["risk_free_rate"].ffill().bfill().fillna(RISK_FREE_RATE_DEFAULT)
)
master_df = master_df.dropna(subset=["underlying_close", "vix_close"])
master_df.to_parquet(cache_path)
```

Two concurrent API requests that both trigger a cache refresh will both read, merge, and write the parquet file. The last writer wins, but one writer's partial state could be read by the other. In practice, cache refreshes are rare (only when the date range extends), but in a server handling parallel requests, this could produce a corrupted cache file.

**Fix**: Use a file lock (e.g., `filelock` package) or write to a temp file and atomically rename.

---

### 9. 🟡 SQL column names interpolated into queries

**File**: `engines.py:563, 783-786, 910-916`
**Confidence**: likely

Column names like `self._delta_col` and `self._iv_col` are interpolated into SQL via f-strings:
```python
cur = self._con.execute(
    f"""SELECT {self._delta_col} AS delta FROM options_data ...""",
    params,
)
```

These are validated against `_ALLOWED_COLS` in `__init__`, so SQL injection is impossible. However, the pattern of interpolating column names is fragile — a future developer removing the whitelist check would create a vulnerability.

**Fix**: This is acceptable given the whitelist. Document the invariant more prominently, or use a parameterized approach where the allowed columns are mapped to template strings.

---

### 10. 🟡 `_compute_mtm_equity` daily P&L may double-count force-close trades

**File**: `metrics.py:185-200`
**Confidence**: speculative

```python
for t in trades:
    marks = getattr(t, "daily_marks", []) or []
    for date, mark in marks:
        records.append({"date": date, "trade": t.trade_num, "mark": mark})

df = pd.DataFrame(records).sort_values(["trade", "date"])
df["prev"] = df.groupby("trade")["mark"].shift(1).fillna(0.0)
df["delta"] = df["mark"] - df["prev"]
```

When a trade is force-closed with `pnl=0.0` (bug #1 above), the last entry in `daily_marks` will have the correct P&L delta, so the equity curve from `_compute_mtm_equity` will be correct while `trade.pnl` is wrong. This means the equity curve and trade-level metrics will disagree for force-closed trades.

**Fix**: This resolves itself once bug #1 is fixed.

---

### 11. 🟡 `_build_vol_filter` assigns Series values via `.iloc[i]`

**File**: `strategy.py:56-59, 64-70`
**Confidence**: likely

```python
result = pd.Series(False, index=dates)
for i in range(252, len(rv)):
    window = rv.iloc[max(0, i - 252):i + 1]
    pct_rank = (rv.iloc[i] > window.values).mean()
    result.iloc[i] = pct_rank > (threshold / 100.0)
```

This pattern triggers `SettingWithCopyWarning` in some pandas versions and is O(n²) for the `rv_pct` and `ivr` modes. For a 252-day lookback on 5,000+ trading days, this creates 4,750 slicing operations each creating a new array.

**Fix**: Use vectorized operations or numpy for the percentile-rank computation. For the `rv_pct` mode:
```python
rv_ranked = rv.rolling(252, min_periods=252).rank(pct=True)
result = rv_ranked > (threshold / 100.0)
```
This is both faster and avoids the iloc-assignment pattern.

---

### 12. 🟡 `MarketEngine.__init__` prints to stdout

**File**: `engines.py:541-568`
**Confidence**: certain

```python
print(f"  MarketEngine: using CDI-based IVs/deltas (daily r)")
...
print(f"  MarketEngine: WARNING — use_cdi_ivs=True but CDI columns not found ...")
...
print(f"MarketEngine: connected to {db_path_str} ...")
```

Three `print()` calls in `__init__`. In a server context, these go to the server's stdout (typically suppressed or logged to a file). The warning about missing CDI columns should use `logging.warning()` at minimum.

**Fix**: Replace all `print()` calls with `logging.info()` / `logging.warning()`. The project already uses `logging` in `api.py`.

---

### 13. 🟡 `_db_coverage_end` opens SQLite connection per call (cached, but not invalidated)

**File**: `data.py:219-245`
**Confidence**: likely

```python
_DB_LAST_CACHE: dict[str, pd.Timestamp] = {}

def _db_coverage_end(db_path: Optional[str] = None) -> pd.Timestamp:
    ...
    if db_path in _DB_LAST_CACHE:
        return _DB_LAST_CACHE[db_path]
```

The cache is keyed by `db_path` string, so different DBs get different cache entries. But if the DB is updated (new data appended), the cached date will be stale. The `clear_data_caches()` function exists to invalidate this, but it must be called explicitly.

In the API's `/config` endpoint, `_db_coverage_end` is called on every request. After the first call, it's cached forever.

**Fix**: Add a TTL or check the file modification time.

---

### 14. 🟢 `_PARAM_REMAP` is confusing about `risk_free_rate`

**File**: `api.py:54-60`
**Confidence**: certain

```python
_PARAM_REMAP = {
    "pricing_risk_free": "risk_free_rate",
    "risk_free_rate":    "cash_yield_annual",
}
```

The API field `risk_free_rate` maps to `cash_yield_annual`, not the option-pricing `risk_free_rate`. The second field `pricing_risk_free` maps to `risk_free_rate` (the pricing parameter). The `BacktestRequest` model documents this on line 83-85, but the mapping is counterintuitive and easy to mix up.

**Fix**: Rename API fields to `cash_yield_annual` and `pricing_risk_free` to avoid overloading "risk_free_rate". This is a breaking API change, so version accordingly.

---

### 15. 🟢 `evaluate_trade_step` ignores `attempt_defensive_leg_roll` return value

**File**: `strategy.py:814-815`
**Confidence**: speculative

```python
attempt_defensive_leg_roll(
    trade, eval_date, S_d, vix_d, r_d, dte_rem, T_d, data, engine, params
)
```

The return value (True if a roll fired) is discarded. The code continues to compute daily marks using the potentially-updated `trade.active_*_strike` fields. This is correct since the marks are computed after the roll, but it would be cleaner to explicitly handle the roll-fired case (for example, to skip profit/stop checks on the same day the roll fired, or to log the event).

**Impact**: No functional bug. If a roll fires and the updated position immediately triggers a profit target or stop on the same day, both events are processed. This is a design decision.

---

### 16. 🟢 `runs_store.py` creates a new SQLite connection per operation

**File**: `runs_store.py:11-15`
**Confidence**: certain

```python
def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn
```

Every call to `upsert_run`, `get_run`, `list_runs`, etc. creates a new connection, executes, and closes via `with` context manager. SQLite has limited write concurrency, and cross-process write contention will cause `OperationalError: database is locked` errors.

**Fix**: Use a connection pool or a single persistent connection with a threading lock. For the expected load (a few backtests per minute), this is fine, but for production with concurrent workers, it needs attention.

---

### 17. 🟢 `plotting.py:41` uses `plt.style.use` at import time

**File**: `plotting.py:41`
**Confidence**: certain

```python
plt.style.use("seaborn-v0_8-whitegrid")
```

This modifies global matplotlib state at import time. If `seaborn-v0_8-whitegrid` is not available (older matplotlib), this raises `OSError`. It also affects any other matplotlib usage in the same process.

**Fix**: Move the style setting into `plot_backtest()` rather than module-level, and add a try/except:
```python
try:
    plt.style.use("seaborn-v0_8-whitegrid")
except OSError:
    pass
```

---

### 18. 🟢 `strategy.py:182` `get_monthly_expiration` max month loop is arbitrary

**File**: `strategy.py:168`
**Confidence**: speculative

```python
for mo in range(0, 5):
```

The loop checks months 0 through 4 ahead. If `dte_min > 150`, no monthly expiration will ever be found (since 5 months ≈ 150 days). This is an edge case that's unlikely with the default `dte_min=30`, but the hardcoded 5 could miss valid expirations for unusual parameter configurations.

**Fix**: Make the loop bound proportional to `dte_max`, or raise a clear error when no expiration is found within the scan range.

---

### 19. 🟢 Hardcoded `_RESULTS_MAX_SIZE = 1000` in api.py

**File**: `api.py:30`
**Confidence**: certain

```python
_RESULTS_MAX_SIZE = 1000
```

This limits in-memory results to 1000 entries but has no configuration mechanism. For heavy usage, this could evict running tasks if > 1000 backtests are started concurrently (extremely unlikely but possible in an automated pipeline).

**Fix**: Make this configurable via environment variable or constructor parameter.

---

### 20. 🟢 `portfolio.py` Roll BPR calculation uses fill-adj twice

**File**: `portfolio.py:342-355`
**Confidence**: speculative

```python
put_ask_mark = engine.get_leg_mark(
    nt.put_strike, underlying_close, nt.entry_dte, vix_d, r_d, "put",
    ctx=_roll_ctx, buy_or_sell="buy",
)
...
new_bpr = calculate_margin(
    nt,
    underlying_close,
    put_ask=engine.apply_fill_adj(put_ask_mark, "close"),
    call_ask=engine.apply_fill_adj(call_ask_mark, "close"),
)
```

`get_leg_mark` with `buy_or_sell="buy"` already returns the ask (for market mode) or mid+ask_adj (for other modes). Then `apply_fill_adj(..., "close")` applies another +5% adjustment on top. For synthetic mode, `get_leg_mark` returns the raw BS mid (ignoring buy_or_sell), so `apply_fill_adj(mid, "close")` gives `mid * 1.05` — correct for margin estimation (conservative). For market mode, `get_leg_mark` returns the ask, and `apply_fill_adj(ask, "close")` is a no-op (MarketEngine.apply_fill_adj returns the input unchanged) — so you get raw ask, which is correct.

The synthetic-path `get_leg_mark` ignoring `buy_or_sell` means the BPR estimate for synthetic mode may be too low (using mid*1.05 instead of a proper ask estimate). This is a minor conservatism issue, not a bug.

---

## Summary

### Top 3 Things to Fix First

1. **Bug #1 (force-close P&L = 0)**: `strategy.py:970-976` — force-closed trades report P&L as 0.0 in single-position mode. This corrupts trade-level metrics (win rate, avg P&L, exit-type breakdown) for any trade that expires after the backtest end date. Fix: compute pnl as `trade.net_credit - res.close_cost` instead of `res.pnl`.

2. **Bug #2 (dict mutation during iteration)**: `api.py:41-46` — `_evict_results` deletes from `_results` dict while iterating. Fix: collect the key first, then delete outside the loop.

3. **Issue #8 (parquet cache race)**: `data.py:118-124` — concurrent cache writes can corrupt the parquet file. Fix: add file locking or use atomic writes.

### Architectural Concerns

- **Global mutable caches** (`_VOL_CACHE`, `_TRADING_DAY_SETS`, `_DB_LAST_CACHE`, `_results`) in `strategy.py`, `data.py`, and `api.py` create hidden coupling between runs. In a long-lived server process, stale or unbounded caches are a growing risk. Consider using a cache manager class with TTL and bounded size.

- **Fill-adjustment semantics** are spread across `strategy.py` and `engines.py` with labels "open"/"close" that conflate position action with fill direction. The iron-condor close-cost code uses `apply_fill_adj(long_mid, "open")` when the position is being *closed*, which is mathematically correct but semantically confusing. A rename to "credit_adj"/"debit_adj" would reduce cognitive load.

- **Test coverage for force-close paths** is apparently absent — the P&L bug in force-close has existed without detection, suggesting no integration test covers the end-of-backtest truncation scenario.

### Things That Should Be Tested But Aren't

- Force-close P&L correctness (trade whose expiration > backtest end_date)
- `_evict_results` under concurrent load (two simultaneous backtests completing)
- `MarketEngine` fallback paths: what happens when every leg falls back to synthetic?
- Iron condor daily mark computation (close_cost, pnl_pct) in both synthetic and market modes
- Portfolio mode + roll continuation: margin recalculation for rolled trades when the engine has real (DB) vs synthetic fills
- `_build_vol_filter` O(n²) performance with large date ranges (>10 years)