# Code Review — `src/`

- **Target:** `src/` (full package: 10 modules)
- **Date:** 2026-05-17
- **Verdict:** Significant issues — 2 critical bugs, 8 important maintainability/correctness concerns

---

## 🔴 Critical

### C1 — API parameter remapping corrupts values when both `pricing_risk_free` and `risk_free_rate` are set

**File:** `src/straddle/api.py:54-60` and `api.py:375-377`

```python
_PARAM_REMAP = {
    "pricing_risk_free":  "risk_free_rate",
    "risk_free_rate":     "cash_yield_annual",
    # ...
}
```

The loop at lines 375–377 processes keys sequentially:

```python
for api_key, internal_key in _PARAM_REMAP.items():
    if api_key in overrides:
        overrides[internal_key] = overrides.pop(api_key)
```

**Problem:** After iteration 1 pops `pricing_risk_free` and sets `risk_free_rate`, iteration 2 finds `risk_free_rate` **now present in overrides** (it was just inserted!), pops it, and maps it to `cash_yield_annual`. The user's original `risk_free_rate` value is silently overwritten, and both the option-pricing rate and cash yield end up as the same value.

**Fix:**

```python
for api_key, internal_key in _PARAM_REMAP.items():
    if api_key in overrides:
        value = overrides.pop(api_key)
        # Only set if not already explicitly provided by the caller
        if internal_key not in overrides:
            overrides[internal_key] = value
```

Or, more robustly, process the remapping before merging into params, tracking which keys were user-provided vs. remapped:

```python
remapped: dict = {}
for api_key, internal_key in _PARAM_REMAP.items():
    if api_key in overrides:
        remapped[internal_key] = overrides.pop(api_key)
# Apply remapped keys last so explicit overrides win
overrides.update(remapped)
```
But this still has ordering issues. Best fix: eliminate the circular mapping entirely by renaming the API fields so there's no overlap (`cash_yield_annual` should be its own API field, not mapped from `risk_free_rate`).

**Confidence:** Certain

---

### C2 — `_evict_results` modifies dict during iteration

**File:** `src/straddle/api.py:41-47`

```python
while len(_results) > _RESULTS_MAX_SIZE:
    for run_id, entry in _results.items():
        if entry.get("status") not in ("pending", "running"):
            del _results[run_id]
            break
    else:
        break
```

**Problem:** Deleting from a dict while iterating over it with `items()` can raise `RuntimeError: dictionary changed size during iteration` in some Python implementations or versions. The `break` after `del` usually prevents this, but it's undefined behavior and fragile against future Python changes.

**Fix:**

```python
while len(_results) > _RESULTS_MAX_SIZE:
    to_evict = next(
        (rid for rid, entry in _results.items()
         if entry.get("status") not in ("pending", "running")),
        None,
    )
    if to_evict is None:
        break
    del _results[to_evict]
```

**Confidence:** Certain

---

## 🟡 Important

### I1 — Vol filter logic duplicated between `is_vol_blocked` and `_build_vol_filter`

**File:** `src/straddle/strategy.py:81-97` and `strategy.py:31-78`

`is_vol_blocked` (line 84–92) reimplements the VIX threshold check with the same fallback parameter chain (`vol_filter_threshold` → `vix_entry_max` → 30.0) that also appears in `_build_vol_filter` (line 50–52). If someone changes the parameter reading logic in one place, the other diverges silently.

**Fix:** Remove the inline VIX check from `is_vol_blocked` and always go through `_build_vol_filter`:

```python
def is_vol_blocked(eval_date, vix_d, params, data):
    blocked = _build_vol_filter(data, params)
    if eval_date in blocked.index:
        return bool(blocked.loc[eval_date])
    return False
```

This also ensures the cache is used for VIX mode, which `is_vol_blocked` currently bypasses. The cache miss is a minor performance concern in the hot backtest loop.

**Confidence:** Certain

---

### I2 — `calculate_reg_t_strangle_margin` hardcodes contract multiplier `100.0`

**File:** `src/straddle/portfolio.py:82-105`

Every dollar amount in this function is multiplied by `100.0` (lines 90, 91, 94, 95, 103, etc.). The `contract_multiplier` parameter exists in `params.py` (default 100.0) and is used elsewhere but not here. If a market with a different multiplier (e.g., mini contracts at 10 shares) is added, this function silently produces wrong margin values.

**Fix:** Add a `contract_multiplier` parameter:

```python
def calculate_reg_t_strangle_margin(
    underlying_price: float,
    put_strike: float,
    call_strike: float,
    put_ask_price: float,
    call_ask_price: float,
    contract_multiplier: float = 100.0,  # <-- add
) -> float:
```

Then replace all `* 100.0` with `* contract_multiplier`.

**Confidence:** Certain

---

### I3 — `_force_close_remaining` inconsistent P&L for positions without `_last_res`

**File:** `src/straddle/portfolio.py:442-456`

```python
if res is None:
    t.exit_date = last_date
    # ...
    t.pnl = 0.0
    t.pnl_pct = 0.0
    t.exit_source = "unknown"
    t.daily_marks.append((last_date, 0.0))
    portfolio.remove_position(t.trade_num)
    all_trades.append(t)
    continue
```

When a position has no `_last_res` entry (opened on the final day of the backtest, or somehow missed evaluation), it's closed with `pnl=0.0`. But `portfolio.available_cash` was **already credited** with the net credit at entry (line 430 of `_process_laddering_entries`), and is never debited. The position collected premium but reports zero P&L — cash is overstated relative to reported P&L.

**Fix:** At minimum, debit the net credit for consistency:

```python
if res is None:
    t.exit_date = last_date
    t.exit_dte = (t.expiration - last_date).days
    t.exit_type = "FORCE_CLOSE"
    t.pnl = t.net_credit  # collected premium with no opposing cost
    t.pnl_pct = 1.0 if t.net_credit else 0.0
    t.exit_source = "unknown"
    portfolio.available_cash -= t.net_credit  # reverse the entry credit
    portfolio.remove_position(t.trade_num)
    all_trades.append(t)
    continue
```

Better still, run `evaluate_trade_step` one more time for these positions rather than relying on `_last_res`.

**Confidence:** Certain

---

### I4 — `engine.close()` in `_run_backtest_task` finally can mask success as failure

**File:** `src/straddle/api.py:310-315`

```python
try:
    # ... backtest execution ...
finally:
    if hasattr(engine, "close"):
        engine.close()
except Exception as e:
    logger.error(f"Backtest {run_id} failed: {e}")
    _results[run_id].update({"status": "failed", "error": str(e)})
```

If the backtest succeeds but `engine.close()` raises (e.g., DB connection issue during close), the exception propagates to the `except` block, which marks the run as `"failed"` with only the close error message. The successful result is lost.

**Fix:** Wrap the close in its own try/except:

```python
try:
    # ... backtest execution ...
except Exception as e:
    logger.error(f"Backtest {run_id} failed: {e}")
    _results[run_id].update({"status": "failed", "error": str(e)})
    upsert_run(run_id, "failed", params, result={"error": str(e)})
finally:
    try:
        if hasattr(engine, "close"):
            engine.close()
    except Exception:
        pass
```

**Confidence:** Certain

---

### I5 — `_compute_daily_marks` mtm source tracking only counts DB days when BOTH legs are DB

**File:** `src/straddle/strategy.py:577-580`

```python
if put_src != "unknown":
    trade.mtm_total_days += 1
    if put_src == "db" and call_src == "db":
        trade.mtm_source_days += 1
```

This means if one leg prices from DB and the other falls back to synthetic, the day counts as "synthetic" in both `mtm_source_days` and `exit_db_source`. This is conservative but can materially underreport DB coverage. A market-mode backtest where 80% of put marks and 80% of call marks come from DB, but only 64% of days have *both*, would report 64% DB coverage — misleadingly low.

**Fix:** Track per-leg instead, or at minimum document this semantics clearly in the `Trade` dataclass docstring.

**Confidence:** Likely (depends on whether the user expects per-leg or combined tracking)

---

### I6 — `_compute_equity_stats` Calmar ratio division by zero

**File:** `src/straddle/metrics.py:171`

```python
"calmar": ann / abs(mdd) if mdd and mdd != 0 else 0.0,
```

`mdd` (max drawdown) is always ≤ 0 (negative), but if the equity curve is perfectly flat, `mdd == 0.0`, and `mdd and mdd != 0` is `False`, returning `0.0` — correct. However, `ann` is computed from `final / init` which for a flat curve gives `ann = 0.0`. So the result is `0.0` either way. The check is correct. This is **not a bug**, just noting the explicit guard exists.

**Confidence:** N/A (verified safe)

---

### I7 — `_get_trading_day_set` silently returns empty frozenset on error

**File:** `src/straddle/strategy.py:119-127`

```python
try:
    import pandas_market_calendars as mcal
    cal = mcal.get_calendar(calendar)
    days = cal.valid_days("2005-01-01", "2030-12-31")
    _TRADING_DAY_SETS[calendar] = frozenset(d.normalize() for d in days)
except Exception:
    _TRADING_DAY_SETS[calendar] = frozenset()
```

On import failure or calendar lookup failure, an empty frozenset is cached and never retried. Every holiday check for that calendar silently returns the original date (line 144: `if not trading_days: return date`). This means a missing `pandas_market_calendars` dependency or a typo in the calendar name results in no holiday adjustments at all — expiration dates could fall on market holidays, producing wrong DTE calculations.

**Fix:** Log a warning at minimum. Better: raise an explicit error for unknown calendars.

```python
except ImportError:
    logger.warning(
        "pandas_market_calendars not installed; holiday adjustments disabled"
    )
    _TRADING_DAY_SETS[calendar] = frozenset()
except Exception as e:
    logger.error(f"Calendar '{calendar}' lookup failed: {e}")
    _TRADING_DAY_SETS[calendar] = frozenset()
```

**Confidence:** Likely

---

### I8 — `_adjust_for_holiday` lookback capped at 7 calendar days

**File:** `src/straddle/strategy.py:148-152`

```python
for _ in range(7):
    d -= pd.Timedelta(days=1)
    if d in trading_days:
        return d
return date
```

Seven calendar days is usually sufficient, but a holiday cluster (e.g., Christmas Eve + Christmas + Boxing Day + New Year's Eve + New Year's Day, plus weekends) could span more than 7 days. In that edge case, the function returns the holiday date itself, which would pass to `get_third_friday` → `get_monthly_expiration` and produce an expiration on a non-trading day. The downstream impact is that `dte` is computed with a non-trading expiration, slightly misrepresenting the time to expiry.

**Fix:** Increase to 10 or use a while loop with a safety counter.

**Confidence:** Speculative (unlikely in practice for US/Brazil calendars)

---

## 🟢 Suggestions

### S1 — `_apply_mpl_style` blanket exception catch

**File:** `src/straddle/plotting.py:47-49`

```python
except Exception:
    pass
```

A `ValueError` from a corrupted style file would be silently swallowed. Narrow the catch to `OSError` and `FileNotFoundError`, or at least log the exception.

### S2 — `_build_vol_filter` loop could be vectorized

**File:** `src/straddle/strategy.py:54-72`

Both `rv_pct` and `ivr` modes use Python `for` loops with `iloc` indexing over potentially thousands of dates. For 20 years of daily data (~5000 rows), this is acceptable. But a pandas-native rolling apply or expanding window would be cleaner.

### S3 — Duplicate SQL patterns in `MarketEngine`

Several private methods (`_best_row`, `_strike_ask`, `_strike_mark`, `get_daily_delta`, `find_strike_at_delta`, `get_leg_mark_with_source`) construct nearly identical SELECT queries. A single `_query_options` helper that takes column names and WHERE clauses would reduce duplication and SQL injection surface area.

### S4 — `_compute_trade_stats` scans trades list 7 times

The inner `_get_stats` closure filters the full `trades` list once per exit type (6 types), plus the total scan. For typical backtests (< 1000 trades), performance is irrelevant, but a single-pass group-by would be more idiomatic (e.g., `collections.Counter` on `t.exit_type`).

### S5 — Missing type annotation on `MARKET_PRESETS`

**File:** `src/straddle/params.py:195`

`MARKET_PRESETS: dict = {...}` should be `MARKET_PRESETS: dict[str, dict] = {...}` for better IDE support.

### S6 — `_load_spy_from_yahoo` is a long method

The function mixes cache validation, YFinance download, column extraction, and gap-filling in one ~80-line method. Splitting into `_load_spy_cache`, `_download_spy_data`, and `_build_market_dataframe` would improve testability.

---

## Top 3 Things to Fix First

1. **C1 — API parameter remap corruption** (`api.py`). This is a data correctness bug that silently corrupts backtest parameters when both `pricing_risk_free` and `risk_free_rate` are set, which could happen in the Streamlit UI or API clients.

2. **C2 — Dict mutation during iteration** (`api.py`). While it doesn't crash in CPython today, it's undefined behavior and could break with any Python upgrade or alternative interpreter.

3. **I1 — Duplicate vol filter logic** (`strategy.py`). This is the most likely source of future divergence bugs — two functions implement the same logic with different code paths. Consolidate them now before they drift.

---

## Architectural Concerns

1. **Parameter flow is convoluted.** `PARAMS` is a flat dict merged from 7 TypedDicts with keys that overlap conceptually (`risk_free_rate` for pricing vs `cash_yield_annual` for portfolio yield). The API layer adds another remapping step. A dataclass-based config with clear namespaces would make it obvious which "rate" is which.

2. **`MarketEngine` ↔ `SyntheticEngine` coupling is tight.** `MarketEngine` creates a `SyntheticEngine` instance in `__init__` and delegates to it across ~8 methods for fallback. This is fine functionally, but the dependency is implicit — every new method on `SyntheticEngine` that `MarketEngine` might need requires manual wiring.

3. **The vol filter subsystem** (`_build_vol_filter`, `is_vol_blocked`, `_VOL_CACHE`) mixes data computation, caching, and query logic. Extracting it to a `VolFilter` class would encapsulate the cache and ensure single source of truth.

---

## What Should Be Tested But Isn't

1. **API parameter remapping edge cases** — specifically when `pricing_risk_free` and `risk_free_rate` are both set in a single request (the C1 bug).

2. **`_force_close_remaining` with positions opened on the last day** — verify P&L and cash consistency (the I3 issue).

3. **Holiday adjustment with non-standard calendars** (BVMF) — verify expiration dates don't fall on Brazilian holidays.

4. **BAW American put approximation** for extreme CDI rates (15%+) and very short DTE (< 5 days) — the `h < 1e-10` guard returns `-1e9` which hasn't been tested for numerical stability in `_baw_critical_put`.

5. **`_evict_results` under contention** — what happens if 1000+ simultaneous SSE streams keep all entries "running"? The `else: break` prevents infinite looping, but the dict grows unbounded. A test for the pathological case would validate the behavior.

6. **`_compute_daily_marks` partial-DB day tracking** — tests should verify that a day with one DB leg and one synthetic leg is classified as expected (currently "synthetic").

---

## Files Reviewed

- `src/straddle/__init__.py` — Public API facade, no issues
- `src/straddle/params.py` — Configuration schema, no critical issues
- `src/straddle/data.py` — Data loaders (SPY Yahoo, B3 parquet), no critical issues
- `src/straddle/engines.py` — Pricing engines (Synthetic + Market), no critical issues
- `src/straddle/strategy.py` — Core backtest loop + trade evaluation
- `src/straddle/metrics.py` — Performance metrics computation
- `src/straddle/portfolio.py` — Portfolio management + margin
- `src/straddle/plotting.py` — Matplotlib visualization
- `src/straddle/api.py` — FastAPI REST API
- `src/straddle/runs_store.py` — SQLite run history persistence
