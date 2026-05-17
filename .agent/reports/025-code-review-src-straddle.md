# Code Review: src/straddle/

**Target path reviewed:** `src/straddle/` (10 modules, ~4100 lines)
**Date:** 2026-05-17
**Summary verdict:** Significant issues

---

## 🔴 Critical

### 1. `strategy.py` — `_check_stop_overshoot` uses `data.index.get_loc()` which raises `KeyError` on non-unique index

**Lines:** `strategy.py:606`
```python
prev_idx = data.index.get_loc(eval_date)
```

**Problem:** If `data` has a non-unique DatetimeIndex (e.g., duplicate dates from a corrupted parquet cache or a yfinance download glitch), `get_loc()` returns an array of positions, not an integer. The subsequent `prev_idx - 1` then produces an array, and `data.iloc[prev_idx - 1]` will either raise or return wrong rows. This silently corrupts the gap detection logic or crashes the backtest mid-run.

**Fix:**
```python
loc = data.index.get_loc(eval_date)
prev_idx = loc if isinstance(loc, int) else (loc.max() if hasattr(loc, 'max') else loc[0])
```

**Confidence:** likely

---

### 2. `strategy.py` — `run_backtest` equity curve construction double-counts P&L on roll chains

**Lines:** `strategy.py:1116-1131`
```python
for t in trades:
    marks = t.daily_marks
    if not marks or len(marks) < 2:
        if t.exit_date is not None and t.exit_date in daily_pnl.index:
            daily_pnl[t.exit_date] += t.pnl or 0.0
        continue
    for i in range(1, len(marks)):
        _, prev_val = marks[i - 1]
        this_date, this_val = marks[i]
        if this_date in daily_pnl.index:
            daily_pnl[this_date] += this_val - prev_val
```

**Problem:** When a trade exits via ROLL, its `daily_marks` include the exit day with a P&L value. Then the child trade's `daily_marks` start at `(eval_date, 0.0)` — the same date. The delta computation for the child trade on its first day is `0.0 - 0.0 = 0`, but the parent trade's last mark already captured the full exit P&L. However, the parent trade's `daily_marks` already contain the exit-day P&L as its last entry, and the delta from the penultimate day to the exit day already includes the full realized P&L. So the exit-date P&L is counted once correctly via the delta loop. But the `len(marks) < 2` fallback path adds `t.pnl` directly — if a rolled trade has fewer than 2 marks (edge case), it gets added as a lump sum, potentially double-counting if the delta loop already captured it.

More concretely: the real issue is that `daily_pnl[this_date] += this_val - prev_val` accumulates *deltas*, but `this_val` for the exit day is the *cumulative* P&L at that point. If two trades are open on the same day (portfolio mode, or single_position with overlapping dates due to a bug), their deltas are summed correctly. But in single-position mode, the `latest_open_exit` barrier should prevent overlap — yet the equity curve logic doesn't know about this and would still double-count if the barrier ever fails.

The more immediate bug: when a trade is rolled, the parent's last `daily_mark` is the exit P&L (e.g., +$200). The child trade starts with `[(eval_date, 0.0)]`. On the next day, the child's first delta is `new_val - 0.0`. But the parent's exit-day delta was `200 - prev_val`. So on the exit date, `daily_pnl[exit_date]` gets `200 - prev_val` from the parent. The child contributes 0 on that date. This is correct. But if the child trade also exits on the same date (force-close edge case), both trades add their pnl to the same date — correct in that scenario.

**The actual bug:** The fallback path for trades with `< 2` marks adds `t.pnl` as a lump sum. But if that trade's exit_date was already processed by the delta loop of a prior iteration (e.g., a trade that was part of a roll chain), the pnl gets added twice — once as a delta, once as a lump sum.

**Fix:** Remove the fallback path or guard it:
```python
for t in trades:
    marks = t.daily_marks
    if not marks or len(marks) < 2:
        continue  # Skip trades with no meaningful daily marks
    for i in range(1, len(marks)):
        ...
```

**Confidence:** speculative (requires tracing specific roll-chain edge cases)

---

### 3. `engines.py` — MarketEngine `__del__` can raise during interpreter shutdown

**Lines:** `engines.py:929-934`
```python
def __del__(self) -> None:
    """Safety measure: ensure connection is closed on garbage collection."""
    try:
        self.close()
    except Exception:
        pass
```

**Problem:** During interpreter shutdown, `self._con` may already be in a partially-destructed state. Calling `self._con.close()` can raise `AttributeError` or `TypeError` that the bare `except` swallows, but more importantly, `__del__` methods that reference other module-level objects can cause `ReferenceError: weakly-referenced object no longer exists` during shutdown. This is a known CPython issue. The `try/except` masks the problem but can still produce stderr noise or hangs.

**Fix:**
```python
def __del__(self) -> None:
    if hasattr(self, "_con") and self._con is not None:
        try:
            self._con.close()
        except Exception:
            pass
```

**Confidence:** likely

---

## 🟡 Important

### 4. `strategy.py` — `_build_vol_filter` rv_pct and ivr modes use slow Python loops

**Lines:** `strategy.py:56-59`, `65-70`
```python
for i in range(252, len(rv)):
    window = rv.iloc[max(0, i - 252):i + 1]
    pct_rank = (rv.iloc[i] > window.values).mean()
    result.iloc[i] = pct_rank > (threshold / 100.0)
```

**Problem:** This is an O(n²) operation with Python-level iteration over every trading day. For a 10-year backtest (~2500 days), this is ~2500 × 252 = 630K comparisons in a Python loop. Each iteration creates a new numpy array via slicing. This can add 5–15 seconds to backtest startup.

**Fix:** Use pandas `rolling` with a custom percentile rank:
```python
elif mode == "rv_pct":
    log_ret = np.log(prices / prices.shift(1))
    rv = log_ret.rolling(20).std() * np.sqrt(252)
    rolling_window = rv.rolling(252, min_periods=1)
    pct_rank = rolling_window.apply(
        lambda x: (x.iloc[-1] > x.iloc[:-1]).mean() if len(x) > 1 else 0.0,
        raw=False
    )
    result = pct_rank > (threshold / 100.0)
    result = result.reindex(dates, fill_value=False)
```

**Confidence:** certain

---

### 5. `data.py` — `_load_spy_from_yahoo` cache logic can create gaps when `download_start` logic is wrong

**Lines:** `data.py:83-84`
```python
download_start = min(req_start, cache_min)
download_end = max(req_end, cache_max)
```

**Problem:** When the cache has data but needs an extension (e.g., cache covers 2020–2023 but request is 2021–2024), `download_start = min(req_start, cache_min)` = 2020, and `download_end = max(req_end, cache_max)` = 2024. This downloads 2020–2024 and concatenates with the existing cache. The `concat` + `duplicated(keep="last")` dedup works, but it re-downloads 3 years of data that was already cached. This is wasteful but not incorrect.

The real issue: if the cache has a *gap* in the middle (e.g., missing a month due to a yfinance outage), the `max_gap <= pd.Timedelta(days=7)` check at line 80 passes because it only checks the *maximum* gap in the *requested range*, not whether the range is fully covered. The code returns the cached slice even if it has internal gaps.

**Fix:** Add a coverage check:
```python
expected_days = (req_end - req_start).days
actual_days = len(candidate)
if actual_days < expected_days * 0.8:  # allow ~20% for holidays
    needs_download = True
```

**Confidence:** likely

---

### 6. `api.py` — `_results` dict has no thread-safety for concurrent SSE + background task access

**Lines:** `api.py:31`, `api.py:230-236`, `api.py:412-433`

**Problem:** `_results` is a plain dict accessed from both the FastAPI event loop (SSE generator at `/backtest/{run_id}/stream`) and a background thread (`_run_backtest_task` via `background_tasks.add_task`). Python dicts are not thread-safe for concurrent read/write. The SSE generator reads `_results.get(run_id)` while the background task writes `_results[run_id]["progress"] = info`. This can cause `RuntimeError: dictionary changed size during iteration` in `_evict_results()` or silent data corruption.

**Fix:** Use `threading.Lock` or `asyncio.Lock`:
```python
import threading
_results_lock = threading.Lock()

def _get_result(run_id):
    with _results_lock:
        return _results.get(run_id)

def _update_result(run_id, info):
    with _results_lock:
        _results[run_id].update(info)
```

**Confidence:** likely

---

### 7. `portfolio.py` — `run_portfolio_backtest` cash yield compounds on `available_cash` but `available_cash` can go negative

**Lines:** `portfolio.py:465-478`
```python
if portfolio.available_cash > 0:
    ...
    portfolio.available_cash *= (1.0 + cash_daily_return)
```

**Problem:** The guard `if portfolio.available_cash > 0` prevents compounding on negative cash, but `available_cash` can become negative when a loss exceeds available cash (e.g., a violent stop-loss where the overshoot model produces a large negative pnl). The `portfolio.available_cash -= res.close_cost` at line 329 can push cash below zero. Once negative, cash yield stops accruing, which is correct. But there's no check that `available_cash` doesn't go so negative that the portfolio is effectively insolvent. The backtest continues silently, producing misleading results.

**Fix:** Add a solvency check:
```python
if portfolio.available_cash < -portfolio.starting_capital:
    # Portfolio is insolvent — force-close all positions and stop
    ...
```

**Confidence:** speculative (depends on whether this is a realistic scenario)

---

### 8. `metrics.py` — `_compute_equity_stats` annualized return uses calendar days, not trading days

**Lines:** `metrics.py:136-138`
```python
years = (
    pd.Timestamp(params["end_date"]) - pd.Timestamp(params["start_date"])
).days / 365.25
```

**Problem:** This uses calendar days to compute the annualization factor, but the Sharpe ratio uses 252 trading days. For a backtest that spans 2 years of calendar time but only ~500 trading days, the annualized return is slightly understated (by ~2% per year). More importantly, if the backtest window includes a long gap (e.g., market closure), the annualization is wrong.

**Fix:** Use trading days from the equity series:
```python
years = len(equity_series) / 252.0
```

**Confidence:** certain

---

### 9. `engines.py` — `MarketEngine.__init__` prints to stdout, breaking API/CLI consumers

**Lines:** `engines.py:541-543`, `565-568`
```python
print(f"  MarketEngine: using CDI-based IVs/deltas (daily r)")
print(f"  MarketEngine: WARNING — use_cdi_ivs=True but CDI columns not found...")
print(f"MarketEngine: connected to {db_path_str} ...")
```

**Problem:** These `print()` calls go to stdout, which breaks JSON output for CLI consumers and pollutes API server logs. They should use `logging` module or be controlled by a verbosity flag.

**Fix:**
```python
import logging
logger = logging.getLogger(__name__)
logger.info("MarketEngine: using CDI-based IVs/deltas (daily r)")
```

**Confidence:** certain

---

### 10. `runs_store.py` — Every function opens and closes a new SQLite connection

**Lines:** `runs_store.py:11-15`, and every function uses `with _connect() as conn:`

**Problem:** Each call to `upsert_run`, `get_run`, `list_runs`, etc. opens a new SQLite connection, executes one query, and closes it. Under API load (e.g., SSE polling `/backtest/{run_id}` every 250ms), this creates hundreds of connection open/close cycles per second. SQLite handles this fine for low throughput, but it's wasteful and can cause `database is locked` errors under concurrent writes.

**Fix:** Use a connection pool or a single shared connection with proper locking:
```python
_conn = None
def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(_DB_PATH))
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
    return _conn
```

**Confidence:** likely

---

## 🟢 Suggestions

### 11. `params.py` — `PARAMS` is a mutable dict that can be accidentally modified by callers

**Lines:** `params.py:336-339`
```python
PARAMS: dict = {
    **BACKTEST, **STRATEGY, **PRICING, **OVERSHOOT,
    **PORTFOLIO, **MARKET, **PAPER_TRADING,
}
```

**Problem:** Any caller that does `params = PARAMS; params["start_date"] = "2025-01-01"` mutates the global defaults for all subsequent calls. The `apply_market_preset` function correctly does `merged = dict(params)`, but callers that skip this step will corrupt the global.

**Fix:** Return a copy from a function, or use `types.MappingProxyType`:
```python
from types import MappingProxyType
PARAMS = MappingProxyType({
    **BACKTEST, **STRATEGY, **PRICING, **OVERSHOOT,
    **PORTFOLIO, **MARKET, **PAPER_TRADING,
})
```

**Confidence:** certain

---

### 12. `strategy.py` — `evaluate_trade_step` is 120+ lines and does too many things

**Lines:** `strategy.py:781-904`

**Problem:** The function handles defensive leg rolls, daily marks, iron condor vs strangle branching, stop-loss with overshoot, profit targets, 21-DTE rolls, and expiry — all in one function. This makes it hard to test individual exit conditions and hard to add new exit types.

**Fix:** Extract each exit check into its own function (already done for `_check_stop_overshoot` and `_check_21dte_roll` — do the same for profit target and expiry).

**Confidence:** certain

---

### 13. `plotting.py` — `plot_backtest` title hardcodes strategy parameters

**Lines:** `plotting.py:73-78`
```python
fig.suptitle(
    f'SPY Short Strangle Backtest  [{params["start_date"]} → {params["end_date"]}]\n'
    f"16Δ | 30–45 DTE | 50% profit | 200% stop | 21 DTE close | $50k account",
```

**Problem:** The hardcoded string "16Δ | 30–45 DTE | 50% profit | 200% stop | 21 DTE close | $50k account" doesn't reflect actual parameter values. If the user runs with `target_delta=0.10` or `initial_balance=100_000`, the chart title is wrong.

**Fix:**
```python
fig.suptitle(
    f'{params.get("market", "SPY").upper()} Short Strangle Backtest  '
    f'[{params["start_date"]} → {params["end_date"]}]\n'
    f'{params["target_delta"]*100:.0f}Δ | {params["dte_min"]}–{params["dte_max"]} DTE | '
    f'{params["profit_target_pct"]*100:.0f}% profit | {params["stop_loss_pct"]*100:.0f}% stop | '
    f'{params["manage_at_dte"]} DTE close | ${params["initial_balance"]:,.0f} account',
```

**Confidence:** certain

---

### 14. `api.py` — `BacktestResponse` model has `underlying_max_drawdown` and `underlying_calmar` fields that are never populated for non-portfolio mode

**Lines:** `api.py:158-161`
```python
underlying_max_drawdown: float
underlying_calmar: float
```

**Problem:** These fields are in the Pydantic model but the `_compute_benchmark_stats` function in `metrics.py` only returns `underlying_total_return` and `underlying_sharpe`. The `_build_metrics_response` function at `api.py:210` computes `underlying_mdd` and `underlying_calmar` locally, but these are local variables — they're passed to `MetricsResponse` correctly. However, the underlying benchmark doesn't have a meaningful "max drawdown" for a buy-and-hold strategy in the same sense as the options strategy. This is a semantic concern, not a bug.

**Confidence:** speculative

---

### 15. `engines.py` — `apply_skew` can return negative vol for extreme call deltas

**Lines:** `engines.py:118-122`
```python
distance_from_atm = 0.50 - abs(delta)
if opt == "put":
    return sigma_atm * (1.0 + put_slope * distance_from_atm)
else:
    return sigma_atm * (1.0 - call_slope * distance_from_atm)
```

**Problem:** For a call with delta very close to 0.50 (deep ITM), `distance_from_atm` approaches 0, so the adjustment is negligible. But for a call with delta close to 0 (deep OTM), `distance_from_atm ≈ 0.50`, and the call vol becomes `sigma_atm * (1.0 - call_slope * 0.50)`. With `call_slope=0.10`, this is `sigma_atm * 0.95` — fine. But if `call_slope` were set to > 2.0 (the API allows up to 2.0), the vol could go negative. The `Field(ge=0, le=2.0)` constraint in `api.py` allows `call_slope=2.0`, which would give `1.0 - 2.0 * 0.50 = 0.0` — zero vol, not negative, but degenerate.

**Fix:** Add a floor:
```python
return max(sigma_atm * (1.0 - call_slope * distance_from_atm), 0.01)
```

**Confidence:** speculative (current defaults are safe, but API allows dangerous values)

---

### 16. `data.py` — B3 loader multiplies `vix_close` by 100 but doesn't validate the source scale

**Lines:** `data.py:195`
```python
slice_df["vix_close"] = slice_df["vix_close"] * 100.0
```

**Problem:** This assumes the parquet stores `vix_close` as a decimal (0.37 = 37%). If the parquet was built with a different convention (e.g., already as percentage points), this doubles the vol and corrupts all pricing. There's no validation that the pre-multiply values are in the expected range (0.01–2.0).

**Fix:** Add a sanity check:
```python
if slice_df["vix_close"].max() > 5.0:
    raise ValueError(
        f"vix_close max={slice_df['vix_close'].max():.2f} exceeds expected decimal range. "
        f"Parquet may already store VIX as percentage points."
    )
slice_df["vix_close"] = slice_df["vix_close"] * 100.0
```

**Confidence:** likely

---

## Top 3 things to fix first

1. **Issue #6 — Thread safety of `_results` dict in `api.py`**: Concurrent SSE polling + background task writes can corrupt the dict or raise `RuntimeError`. This is a production API issue.
2. **Issue #1 — `data.index.get_loc()` on non-unique index in `strategy.py`**: Can crash mid-backtest or produce silently wrong gap detection.
3. **Issue #8 — Annualized return uses calendar days in `metrics.py`**: Systematic understatement of CAGR by ~2%/year, misleading for strategy comparison.

## Architectural concerns

- **`PARAMS` as a mutable global singleton** (Issue #11): Any module that mutates `PARAMS` corrupts state for all other callers. This is especially dangerous in the API server where multiple backtests run concurrently. Should be immutable or copy-on-read.
- **No connection pooling for SQLite** (Issue #10): `runs_store.py` opens/closes a connection per call. Under API load, this is a bottleneck waiting to happen.
- **Engines print to stdout** (Issue #9): Breaking JSON output and polluting logs. All diagnostic output should go through `logging`.
- **`_build_vol_filter` Python loop** (Issue #4): O(n²) startup cost that scales poorly with backtest length. Should be vectorized.

## Test gaps

- **No test for non-unique DatetimeIndex** in `evaluate_trade_step` (Issue #1)
- **No test for concurrent API access** to `_results` dict (Issue #6)
- **No test for `call_slope=2.0` edge case** in `apply_skew` (Issue #15)
- **No test for B3 parquet with wrong vix_close scale** (Issue #16)
- **No test for `run_backtest` equity curve with roll chains** (Issue #2)
- **`test_engines.py` exists but doesn't test `MarketEngine.get_leg_mark_with_source`** with all execution modes
- **No test for `PortfolioManager` solvency** when losses exceed capital (Issue #7)
