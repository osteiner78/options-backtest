# Code Review: src/straddle/

**Target path reviewed:** `src/straddle/`  
**Date:** 2026-05-17  
**Summary verdict:** Significant issues (one critical B3-only engine bug, several portfolio-mode bookkeeping gaps, and param-wiring oversights)

---

## 🔴 Critical

### 1. `engines.py` — `_iv_where` inverted, causing B3 MarketEngine to select stale quotes

**Quoted lines:**
```python
552:         self._iv_where = f"AND {self._iv_col} < 2.0" if self._has_underlying_col else ""
```

**Problem:** The docstring says the filter should "skip deep-OTM rows with implausibly low IV (< 2.0)", but the SQL fragment `AND iv_col < 2.0` **keeps** only rows with IV below 2.0 — the exact opposite. For B3 markets (where `_has_underlying_col` is True) this means `MarketEngine._best_row` and `find_strike_at_delta` will preferentially select the stalest, most illiquid quotes instead of rejecting them. If B3 IV is stored as percentage points (e.g. 25 = 25%), the filter keeps only rows with IV < 2%, which are almost exclusively bad prints.

**Fix:**
```diff
-        self._iv_where = f"AND {self._iv_col} < 2.0" if self._has_underlying_col else ""
+        self._iv_where = f"AND {self._iv_col} >= 2.0" if self._has_underlying_col else ""
```

**Confidence:** certain

---

## 🟡 Important

### 2. `data.py` — yfinance non-MultiIndex fallback silently aliases all data to SPY

**Quoted lines:**
```python
97:         if not raw.empty:
98:             if isinstance(raw.columns, pd.MultiIndex):
99:                 spy_raw = raw.xs("SPY", axis=1, level=1)
100:                 vix_raw = raw.xs("^VIX", axis=1, level=1)
101:                 irx_raw = raw.xs("^IRX", axis=1, level=1)
102:             else:
103:                 spy_raw = vix_raw = irx_raw = raw
```

**Problem:** The `else` branch is a defensive fallback, but if `yf.download` ever returns a flat-column DataFrame (bug, network hiccup, ticker delisting), VIX and IRX become exact aliases of SPY. The backtest would silently use SPY close for VIX and risk-free rate, corrupting every subsequent pricing decision. This is a classic "fail-deadly" fallback.

**Fix:**
```python
            else:
                raise ValueError(
                    f"Expected MultiIndex columns from yfinance, got {type(raw.columns)}. "
                    f"Tickers may be missing or yfinance behavior changed."
                )
```

**Confidence:** likely

---

### 3. `portfolio.py` — `entry_cooldown_days` param is defined but never wired to `PortfolioManager`

**Quoted lines:**
```python
182:     entry_cooldown_days: int = 3  # minimum trading days between new entries
```

**Problem:** `params.py` exposes `entry_cooldown_days` in `PORTFOLIO`, but `run_portfolio_backtest` instantiates `PortfolioManager` without passing it:

```python
271:         portfolio = PortfolioManager(
272:             starting_capital=params.get("initial_balance", 50_000),
273:             max_bpr_allocation=params.get("max_bpr_allocation", 0.30),
274:         )
```

Users who change the param expect the backtest to respect it; it is silently ignored and hardcoded to 3.

**Fix:**
```diff
 @dataclass
 class PortfolioManager:
     starting_capital: float = 50_000.0
     max_bpr_allocation: float = 0.30
+    entry_cooldown_days: int = 3
```

And in `run_portfolio_backtest`:
```diff
         portfolio = PortfolioManager(
             starting_capital=params.get("initial_balance", 50_000),
             max_bpr_allocation=params.get("max_bpr_allocation", 0.30),
+            entry_cooldown_days=params.get("entry_cooldown_days", 3),
         )
```

**Confidence:** certain

---

### 4. `portfolio.py` — trades entered (or rolled) on the final backtest day are silently dropped

**Quoted lines:**
```python
484:                 res = _last_res.get(trade_num_open)
485:                 if res is None:
486:                     continue
```

**Problem:** During end-of-backtest force-close, the loop skips any open position that lacks a `_last_res` entry. A position entered on the very last day (or rolled onto the last day) was never evaluated by `evaluate_trade_step`, so it has no `_last_res`. It is never closed, never appended to `trades`, and disappears from all metrics (trade count, win rate, P&L).

**Fix:** Handle the missing-`res` case explicitly rather than skipping:
```python
                res = _last_res.get(trade_num_open)
                if res is None:
                    # Trade entered on last day — no marks available, close at zero P&L
                    t.exit_date = last_date
                    t.exit_dte = (t.expiration - last_date).days
                    t.exit_type = "FORCE_CLOSE"
                    t.pnl = 0.0
                    t.pnl_pct = 0.0
                    t.exit_source = "unknown"
                    t.daily_marks.append((last_date, 0.0))
                    portfolio.remove_position(t.trade_num)
                    trades.append(t)
                    continue
```

**Confidence:** certain

---

### 5. `portfolio.py` — entry margin calculation uses bid instead of ask for market mode

**Quoted lines:**
```python
414:                     actual_bpr = calculate_margin(
415:                         new_trade,
416:                         underlying_close,
417:                         put_ask=engine.apply_fill_adj(kw["put_mid_ps"], "close"),
418:                         call_ask=engine.apply_fill_adj(kw["call_mid_ps"], "close"),
419:                     )
```

**Problem:** `kw["put_mid_ps"]` in market mode is the **bid** (see `MarketEngine.get_entry_marks`). For Reg-T margin, the ask is required because it represents the worst-case cost to buy back the short. Using bid understates margin, especially in wide-spread regimes. The daily mark path (line 378) correctly uses `res.put_mid_d`, which comes from `get_leg_mark_with_source(buy_or_sell="buy")` and returns the ask. So entry BPR is artificially lower than day-1 BPR, potentially allowing an entry that immediately exceeds capacity.

**Fix:** Store the ask alongside the bid in `Trade` (or query it separately for margin), or at minimum use `get_leg_mark(..., buy_or_sell="buy")` to fetch the ask for the computed strikes before calling `calculate_margin`.

**Confidence:** certain

---

### 6. `metrics.py` — portfolio Calmar mixes total-equity CAGR with options-only MDD

**Quoted lines:**
```python
419:         ann = float(results.get("ann", 0.0))
420:         mdd = float(results.get("mdd", 0.0))
421:         results["calmar"] = ann / abs(mdd) if mdd and mdd != 0 else 0.0
```

**Problem:** `results["ann"]` comes from `_compute_equity_stats` called on `equity_df["total_equity"]` (includes cash yield). But `results["mdd"]` was just overwritten at line 418 by `_compute_mdd_from_daily_pnl`, which uses the options-only MTM curve. Dividing a total-return numerator by an options-only denominator produces a meaningless ratio.

**Fix:** Recompute `ann` from the same options-only equity curve used for MDD, or compute two separate Calmar ratios (total and options-only) and label them clearly.

**Confidence:** certain

---

### 7. `api.py` — `apply_market_preset` invoked without `explicitly_set`, triggering documented footgun

**Quoted lines:**
```python
382:     params = apply_market_preset(params, market)
```

**Problem:** `apply_market_preset`'s docstring explicitly warns that without `explicitly_set`, "market keys that equal the SPY default are silently dropped." Example: a user sets `american_options=False` (matching the SPY preset) and then switches to `petr4` (preset `True`). The explicit override is dropped because its value happens to match the SPY default.

**Fix:** Track which keys the caller explicitly provided (e.g. from `overrides.keys()`) and pass them as `explicitly_set`:
```python
    explicitly_set = set(overrides.keys())
    params = apply_market_preset(params, market, explicitly_set=explicitly_set)
```

**Confidence:** certain

---

### 8. `plotting.py` — engine comparison matches trades by ordinal index instead of date

**Quoted lines:**
```python
276:     n = min(len(roots_syn), len(roots_mkt))
...
279:     syn_put_k = [ts.put_strike for ts in roots_syn[:n]]
280:     mkt_put_k = [tm.put_strike for tm in roots_mkt[:n]]
```

**Problem:** If synthetic and market runs skip different months (e.g., market mode lacks DB data for one month), the Nth root trade in each list corresponds to a different calendar month. The comparison chart then misaligns strikes and credits, making deltas look like engine noise when they are actually date mismatches.

**Fix:** Match by `entry_date` using a dict or merge, and only compare trades with the same entry date:
```python
    syn_by_date = {t.entry_date: t for t in roots_syn}
    mkt_by_date = {t.entry_date: t for t in roots_mkt}
    common_dates = sorted(set(syn_by_date) & set(mkt_by_date))
```

**Confidence:** certain

---

### 9. `portfolio.py` — `calculate_iron_condor_margin` can return negative margin

**Quoted lines:**
```python
114:     return max(put_width, call_width) * 100.0 - net_credit
```

**Problem:** If a pricing bug or data quirk causes `net_credit > max_width * 100`, the function returns a negative number. Margin should never be negative; the floor is zero.

**Fix:**
```diff
-    return max(put_width, call_width) * 100.0 - net_credit
+    return max(max(put_width, call_width) * 100.0 - net_credit, 0.0)
```

**Confidence:** certain

---

### 10. `data.py` — B3 `vix_close` can remain all-NaN, causing downstream `float('nan')` or comparison bugs

**Quoted lines:**
```python
181:         if "vix_close" in slice_df.columns:
182:             slice_df["vix_close"] = slice_df["vix_close"].ffill().bfill()
183:             slice_df["vix_close"] = slice_df["vix_close"] * 100.0
```

**Problem:** `ffill().bfill()` on an all-NaN series still yields all-NaN. Multiplying by 100 preserves NaN. Later, `strategy.py` line 1063 does `float(row["vix_close"])`, producing `nan`. `is_vol_blocked` then compares `nan > threshold`, which is always `False`, silently disabling the vol filter for those dates. A more explicit failure would be preferable.

**Fix:** Add a guard after ffill:
```python
        if "vix_close" in slice_df.columns:
            slice_df["vix_close"] = slice_df["vix_close"].ffill().bfill()
            if slice_df["vix_close"].isna().all():
                raise ValueError(f"vix_close is all-NaN for {market} in the requested range.")
            slice_df["vix_close"] = slice_df["vix_close"] * 100.0
```

**Confidence:** likely

---

### 11. `api.py` — CORS middleware allows all origins unconditionally

**Quoted lines:**
```python
25: app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
```

**Problem:** `allow_origins=["*"]` with `allow_credentials=True` is a security anti-pattern. If this API is ever exposed beyond localhost, it permits cross-origin authenticated requests from any domain.

**Fix:** Restrict to known origins, or at minimum read from an environment variable:
```python
import os
allow_origins = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:8501").split(",")
app.add_middleware(CORSMiddleware, allow_origins=allow_origins, ...)
```

**Confidence:** certain

---

### 12. `plotting.py` — chart title hardcodes strategy parameters regardless of actual `params`

**Quoted lines:**
```python
74:         f"16Δ | 30–45 DTE | 50% profit | 200% stop | 21 DTE close | $50k account",
```

**Problem:** If the user runs with 10Δ, 60% profit target, or a $100k account, the saved PNG still claims 16Δ / 50% / $50k. This misleads anyone reviewing saved artifacts.

**Fix:** Format the title from `params`:
```python
        f'{params.get("target_delta", 0.16)*100:.0f}Δ | '
        f'{params["dte_min"]}-{params["dte_max"]} DTE | '
        f'{params["profit_target_pct"]*100:.0f}% profit | ...'
```

**Confidence:** certain

---

## 🟢 Suggestion

### 13. `__init__.py` — `calculate_margin` imported but omitted from `__all__`

**Quoted lines:**
```python
33: from straddle.portfolio import (
34:     PortfolioManager,
35:     calculate_margin,
...
40: __all__ = [
...
60:     "PortfolioManager",
61:     "calculate_reg_t_strangle_margin",
62:     "calculate_iron_condor_margin",
63:     "run_portfolio_backtest",
64:     "plot_portfolio_backtest",
65: ]
```

**Problem:** `calculate_margin` is imported but not re-exported, making it inaccessible via `from straddle import calculate_margin` despite being a useful public utility.

**Fix:** Add `"calculate_margin",` to `__all__`.

**Confidence:** certain

---

### 14. `strategy.py` — vol-filter percentile windows include the current day, biasing ranks slightly downward

**Quoted lines:**
```python
57:             window = rv.iloc[max(0, i - 252):i + 1]
58:             pct_rank = (rv.iloc[i] > window.values).mean()
```

**Problem:** `window` includes `rv.iloc[i]`, so the comparison `rv.iloc[i] > window.values` is guaranteed at least one `False` (the element vs itself). In a flat vol regime this pushes `pct_rank` to 0 instead of 0.5. The bias is tiny (~0.4%) but unnecessary.

**Fix:** Exclude the current observation:
```python
            window = rv.iloc[max(0, i - 252):i]
```

**Confidence:** certain

---

### 15. `engines.py` — f-string SQL interpolation is fragile

**Quoted lines:**
```python
952:             f"""
953:             SELECT strike, mark, bid, ask, {self._delta_col} AS delta,
...
961:               {self._iv_where}
962:             ORDER BY ABS({self._delta_col} - ?) ASC
```

**Problem:** Column names are currently derived from trusted DB schema introspection, but the pattern is a latent SQL injection vector. If any future refactor allows user input to influence column selection, it becomes exploitable. Using bound parameters for identifiers (or at least a strict allow-list) is safer.

**Fix:** Validate columns against a fixed allow-list before interpolation:
```python
_ALLOWED_COLS = {"delta", "delta_cdi", "implied_volatility", "implied_volatility_cdi"}
assert self._delta_col in _ALLOWED_COLS
```

**Confidence:** speculative

---

### 16. `api.py` — `/config` endpoint uses legacy `db_path` key instead of `options_db_path`

**Quoted lines:**
```python
325:     db_path = PARAMS.get("db_path", "data/Spy Options Database.db")
```

**Problem:** `PARAMS` merged dict contains `options_db_path`, not `db_path`. The fallback string is therefore always used, making the coverage-end check slightly misleading even though `_db_coverage_end` handles missing files gracefully.

**Fix:**
```diff
-    db_path = PARAMS.get("db_path", "data/Spy Options Database.db")
+    db_path = PARAMS.get("options_db_path", "data/Spy Options Database.db")
```

**Confidence:** certain

---

### 17. `portfolio.py` — dead code block

**Quoted lines:**
```python
289:         if "vix_entry_filter_enabled" in params:
290:             pass  # handled by is_vol_blocked for backward compat
```

**Problem:** No-op block with no side effects. Should be removed to reduce clutter.

**Fix:** Delete lines 289-290.

**Confidence:** certain

---

### 18. `metrics.py` — `entry_db_total` is a trivial alias for `len(trades)`

**Quoted lines:**
```python
371:     results["entry_db_total"] = len(trades)
372:     results["entry_db_pct"] = entry_db_count / len(trades) * 100.0 if trades else 0.0
```

**Problem:** `entry_db_total` is always identical to `entry_db_count / entry_db_pct * 100`, making it redundant API surface.

**Fix:** Remove `entry_db_total` from the metrics dict, or rename it to `n_trades` for clarity.

**Confidence:** speculative

---

## Top 3 Things to Fix First

1. **Invert `_iv_where` in `engines.py`** (Critical, Issue #1). This is a one-line change with outsized impact on B3 backtest validity. Every B3 run using the market engine is currently selecting the wrong quotes.
2. **Wire `entry_cooldown_days` into `PortfolioManager`** (Issue #3). Users are already changing this param; the fact that it is ignored breaks trust in the parameter system.
3. **Fix last-day trade dropping in portfolio force-close** (Issue #4). Silent data loss in metrics is worse than a crash because it goes unnoticed.

---

## Architectural Concerns

1. **Module-level mutable caches (`_VOL_CACHE`, `_TRADING_DAY_SETS`)** make the strategy module non-reentrant and leak memory in long-lived server processes. The existing `clear_*` helpers are easy to forget. A cleaner approach is to attach caches to the engine or a `BacktestContext` object that is destroyed with each run.

2. **Single `evaluate_trade_step` shared between single-position and portfolio modes** is becoming a seam for bugs. Portfolio mode needs to mutate `trade` state (defensive leg rolls, daily marks) while also managing a separate `PortfolioManager` ledger. The divergence in lifecycle management (e.g., force-close logic) suggests the two modes should either fully share a state machine or fully diverge, rather than the current halfway house.

3. **F-string SQL in `MarketEngine`** is safe today because all interpolated values are hard-coded or derived from DB introspection, but it is a latent security liability. A small wrapper that binds identifiers via an allow-list would eliminate this class of risk permanently.

---

## Testing Gaps

The following issues would be caught by straightforward tests but are currently unprotected:

- **B3 market engine strike selection** (Issue #1): A test asserting that `_best_row` never returns a row with `implied_volatility < 2.0` for B3 would have caught the inverted filter immediately.
- **Portfolio last-day edge cases** (Issue #4): A test with a one-day backtest window, or a window where a roll fires on the final day, should assert that all positions appear in the returned `trades` list.
- **Param wiring validation** (Issue #3): A test that patches `params["entry_cooldown_days"]` to 99 and asserts no second trade enters within 99 days would catch the hardcoding.
- **Entry margin ask-vs-bid semantics** (Issue #5): A test comparing `PortfolioPosition.current_bpr` on entry day vs day 1 should be equal (or entry should be higher, never lower).
- **`apply_market_preset` edge case** (Issue #7): A test that passes `american_options=False` with `market="petr4"` and verifies the final param is `False`.
- **Data integrity on yfinance flat columns** (Issue #2): A mock test injecting a flat-column DataFrame should raise, not alias.

---

*End of review.*
