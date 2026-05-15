# Code Review — Full Codebase

**Target:** `src/straddle/` + `tests/` + `scripts/` + `apps/streamlit-ui/`  
**Date:** 2026-05-15  
**Reviewer:** Claude Sonnet 4.6 (senior-engineer review)  
**Summary Verdict:** **Minor Issues** — No critical bugs found in the production path. Several important issues around error-handling gaps, thread-safety footguns, silent data-corruption edge cases, and meaningful test gaps. The financial logic and fill-accounting are carefully implemented; the most dangerous risks are operational rather than algorithmic.

---

## Table of Contents

1. [Critical Issues](#1-critical-issues)
2. [Important Issues](#2-important-issues)
3. [Suggestions](#3-suggestions)
4. [Test Coverage Assessment](#4-test-coverage-assessment)
5. [Top 3 Fixes](#5-top-3-to-fix-first)
6. [Architectural Concerns](#6-architectural-concerns)

---

## 1. Critical Issues

None found with certainty. The two closest candidates are demoted to Important because they require unusual conditions to trigger.

---

## 2. Important Issues

### I-1. Thread-safety: shared SQLite connection with `check_same_thread=False`

**File:** `src/straddle/engines.py:520`

```python
self._con = _sqlite3.connect(db_path_str, check_same_thread=False)
```

The `MarketEngine` holds a single `sqlite3.Connection` opened with `check_same_thread=False`. In the API (`api.py`), each `/backtest` request creates a new `MarketEngine` in a background thread (via `BackgroundTasks.add_task`). If two requests use the same DB path, each gets its own connection — that's fine. But within a single engine instance, if grid_search's `_worker_cache` reuses the same engine object across multiple `joblib` workers running concurrently (loky spawns separate processes, so this is actually safe with loky), this is a latent hazard if anyone switches `backend="threading"`. The issue is moot with loky but the code is fragile.

**More concretely:** `grid_search.py:207–213` mutates `engine._exec_mode` after pulling it from a shared cache:

```python
data, engine = _worker_cache[cache_key]
# Ensure engine uses this combo's execution_mode
engine._exec_mode = exec_mode
engine.uses_real_fills = (exec_mode == "bid_ask")
```

With `loky` (separate processes), this mutation is in a subprocess copy and is harmless. But `_worker_cache` is a module-level dict and any future switch to threading would produce a data race between combos that differ only in `execution_mode`. There is no lock.

**Confidence:** Certain the design is fragile; currently not buggy with loky.

**Fix:** Either (a) create a fresh engine per combo, or (b) add a `contextmanager`-based lock if threading is ever adopted, or (c) document the loky-only guarantee explicitly.

---

### I-2. `_run_backtest_task` silently drops `failed` error to SQLite but `_results` dict is the source of truth for the API

**File:** `src/straddle/api.py:295–298`

```python
    except Exception as e:
        logger.error(f"Backtest {run_id} failed: {e}")
        _results[run_id].update({"status": "failed", "error": str(e)})
        upsert_run(run_id, "failed", params)    # ← result=None, error not persisted
```

`upsert_run` is called with `result=None`, so the error string is never persisted to SQLite. The error is only stored in `_results` (in-memory). When the server restarts, or when `GET /backtest/{id}` reads from SQLite (line 377), the `error` field is null even though the run failed. A client polling after a server restart sees `status="failed"` with no error message.

**Confidence:** Certain — the error is swallowed by the persistence layer.

**Fix:**

```python
    except Exception as e:
        logger.error(f"Backtest {run_id} failed: {e}")
        _results[run_id].update({"status": "failed", "error": str(e)})
        upsert_run(run_id, "failed", params, result={"error": str(e)})
```

Then in `get_backtest_result`, the `result.get("error")` call (line 383) already surfaces it correctly.

---

### I-3. `_build_vol_filter` loop is O(n²) for `rv_pct` and `ivr` modes

**File:** `src/straddle/strategy.py:52–72`

```python
elif mode == "rv_pct":
    for i in range(252, len(rv)):
        window = rv.iloc[max(0, i - 252):i + 1]
        pct_rank = (rv.iloc[i] > window.values).mean()
        result.iloc[i] = pct_rank > (threshold / 100.0)
```

For a 5-year backtest (~1260 trading days) this loop runs 1008 iterations, each constructing and comparing a 252-element numpy array. That's ~250k comparisons. For the grid search with hundreds of combos, this function is called once per unique `(index, mode, threshold)` tuple (the cache helps), but under a fresh grid-search start or when `vol_filter_threshold` varies per combo, the cache misses multiply. For `n=2000` days this is 2M comparisons per miss, which is slow.

**Confidence:** Certain the O(n²) issue exists; impact depends on grid size.

**Fix:** Vectorise using `scipy.stats.rankdata` or a rolling rank:

```python
elif mode == "rv_pct":
    rv_roll = rv.rolling(252)
    result = pd.Series(False, index=dates)
    # ranks[i] = fraction of window where rv[i] > historical
    result = rv_roll.apply(
        lambda w: (w[-1] > w[:-1]).mean(), raw=True
    ) > (threshold / 100.0)
    result = result.fillna(False)
```

The `rolling.apply` approach is still O(n·w) but eliminates the Python-level loop overhead; alternatively use `rolling.rank()` introduced in pandas 1.4.

---

### I-4. `run_backtest.py` prints stale `final_balance` that diverges from `equity_curve`

**File:** `scripts/run_backtest.py:87–89`

```python
final_balance = params["initial_balance"] + sum(t.pnl for t in trades if t.pnl)
total_return = (final_balance - params["initial_balance"]) / params["initial_balance"]
```

The printed `final_balance` sums raw trade P&Ls, which ignores the equity curve's daily MTM construction. The equity curve built in `run_backtest` accumulates daily delta-marks; the printed number sums terminal P&Ls directly. These can differ when trades overlap in time (they don't in `single_position=True`, but do when `single_position=False`). More concretely, `metrics["final"]` already contains the authoritative equity curve final value, so re-computing from scratch here creates a discrepancy in the printed output.

**Confidence:** Certain mismatch exists; magnitude depends on params.

**Fix:**

```python
final_balance = float(equity_curve.iloc[-1]) if not equity_curve.empty else params["initial_balance"]
total_return = (final_balance - params["initial_balance"]) / params["initial_balance"]
```

---

### I-5. `apply_market_preset` silently drops explicit overrides when `explicitly_set=None` and value equals SPY default

**File:** `src/straddle/params.py:309–319`

The docstring acknowledges this:

> *"silently drops overrides whose value happens to equal the SPY default (a known edge-case footgun)"*

The API (`api.py:364–365`) calls:

```python
params.update(overrides)      # caller values applied
params = apply_market_preset(params, market)  # preset may re-clobber them
```

Since `overrides` have already been merged into `params`, and `apply_market_preset` uses the SPY-comparison heuristic (no `explicitly_set`), a caller who explicitly passes `tick_size=0.01` for a BOVA11 backtest will have it silently reverted to `0.05`. The test `test_params.py:50–55` covers the `explicitly_set` path but the API never uses it.

**Confidence:** Certain — the API path uses the fallback heuristic, not `explicitly_set`.

**Fix:** In `api.py`, pass `explicitly_set=set(overrides.keys())` (the keys the request provided):

```python
explicitly_set = set(req.model_dump(exclude_none=True).keys())
# ... apply remapping ...
params = apply_market_preset(params, market, explicitly_set=explicitly_set)
```

---

### I-6. `strategy.py` `evaluate_trade` fallback expiry path doesn't append to `daily_marks`

**File:** `src/straddle/strategy.py:905–928`

The fallback path (loop ends without an exit — trade held to expiration) computes intrinsic-value P&L but never calls `trade.daily_marks.append(...)` for the expiration day. Every other exit path appends via `evaluate_trade_step` which always appends to `daily_marks` before checking exits. This means the last-day mark is missing from the equity curve computation.

```python
# Fallback: loop ended without an intra-period exit
last = data.index[data.index <= expiration][-1]
S_e = float(data.loc[last, "underlying_close"])
intr = max(trade.active_put_strike - S_e, 0.0) + ...
# ← no daily_marks.append here!
```

The equity curve builder in `run_backtest` reads `daily_marks` exclusively:

```python
for i in range(1, len(marks)):
    _, prev_val = marks[i - 1]
    this_date, this_val = marks[i]
    if this_date in daily_pnl.index:
        daily_pnl[this_date] += this_val - prev_val
```

When the fallback path fires, `trade.pnl` is set but the equity curve never reflects it — the P&L is lost from the daily curve. Trades via this path are rare (they require the loop to iterate past expiration without any exit condition firing, which the EXPIRY check on line 813 should normally catch), but it can happen if `expiration` is not in `data.index`.

**Confidence:** Likely — rare but real gap; the EXPIRY check fires before expiration only when `eval_date >= expiration`, which requires the expiration itself to be a trading day in `data`.

**Fix:** Append to `daily_marks` in the fallback path:

```python
trade.daily_marks.append((last, pnl))  # add after computing pnl, before return
trade.exit_date = expiration
...
```

---

### I-7. `portfolio.py` `run_portfolio_backtest` uses `available_cash` including unrealized premium for margin checks

**File:** `src/straddle/portfolio.py:359, 437`

When a new trade enters, the net credit is added immediately to `available_cash`:

```python
portfolio.available_cash += kw["net_credit"]
```

The BPR capacity check (`can_enter_new_trade`) compares `utilized_bpr` against `starting_capital * max_bpr_allocation`. The `available_cash` is also used for cash yield calculations (step 4, line 461). This means unrealized premium from all open positions is already in `available_cash` (correctly), but the BPR gate uses only `utilized_bpr` vs. a fixed fraction of `starting_capital`. As positions lose money, their Reg-T margin requirement grows (call it $X), `utilized_bpr` grows, but `available_cash` also decreases because the close cost exceeds the original credit — the two are inconsistent until a position is closed. The net effect is that the portfolio may allow new entries even when cash is effectively depleted, because `utilized_bpr` doesn't account for unrealized losses in the margin test.

This is a known simplification (the comment says "acceptable because the Reg-T formula only uses premium as a small component") but it is structurally unsound for large adverse moves.

**Confidence:** Certain design limitation; acceptable for simulation purposes but should be documented explicitly.

---

### I-8. `data.py` max gap check uses 7-day threshold, misses holiday-extended weekends

**File:** `src/straddle/data.py:80`

```python
if pd.isna(max_gap) or max_gap <= pd.Timedelta(days=7):
    return candidate.copy()
```

A 7-day threshold is intended to catch data gaps (e.g., missing trading days from partial downloads) while allowing for long weekends and U.S. market holidays. However, the threshold is loose: a missing entire week of market data (5 trading days = 7 calendar days) would pass this check. More precisely, if `yfinance` returns a DataFrame with a missing week (e.g., due to a rate-limit failure that was silently swallowed), the cache is considered valid. This could silently corrupt backtests with a 5-trading-day data gap.

**Confidence:** Speculative — requires a yfinance failure that corrupts the parquet; in practice the download retries.

**Fix:** Reduce the threshold to `pd.Timedelta(days=5)` (max calendar gap for a long-weekend Monday holiday) and log a warning if the gap exceeds 3 days.

---

### I-9. `_PARAM_REMAP` in `api.py` maps `risk_free_rate` → `cash_yield_annual`, silently ignoring option pricing rate

**File:** `src/straddle/api.py:37–43`

```python
_PARAM_REMAP = {
    "pricing_mode":      "mode",
    "pricing_risk_free": "risk_free_rate",
    "risk_free_rate":    "cash_yield_annual",
    ...
}
```

The `risk_free_rate` API field maps to `cash_yield_annual` (the yield on idle cash). The separate `pricing_risk_free` maps to the actual BS risk-free rate. This naming is non-obvious and the field description warns about it (`api.py:65–68`). The footgun: if a caller passes `risk_free_rate=0.10` intending to set the option-pricing rate (Brazil CDI), they actually set the cash yield and the BS rate stays at the PARAMS default of 4.5%. This affects the synthetic engine's option pricing. The field-level description is correct but the naming is confusing for API consumers.

**Confidence:** Certain design issue; not a bug if documentation is followed.

**Fix:** Rename the API field to `cash_yield_rate` in `BacktestRequest` and update `_PARAM_REMAP`. Add a deprecation alias if backward compat is needed.

---

### I-10. `metrics.py` `_compute_sharpe_from_daily_pnl` uses `init` (initial balance) as denominator — wrong for compounding accounts

**File:** `src/straddle/metrics.py:198`

```python
def _compute_sharpe_from_daily_pnl(daily_pnl: pd.Series, init: float) -> float:
    daily_ret = daily_pnl / init
```

Dividing daily dollar P&L by the *initial* balance produces returns denominated in "% of initial capital". For a compounding account that has grown significantly, this understates returns in the late period and overstates them in a drawdown. The standard is to divide by the current running equity (i.e., use percentage returns from the equity series). This function is only used by `compute_portfolio_metrics` (not `compute_metrics` which correctly uses `equity_series.pct_change()`), so it introduces a systematic downward bias in portfolio-mode Sharpe for successful accounts.

**Confidence:** Certain conceptual error; magnitude depends on how much the account grows.

**Fix:**

```python
def _compute_sharpe_from_daily_pnl(daily_pnl: pd.Series, init: float) -> float:
    # Build equity and compute percentage returns
    equity = init + daily_pnl.cumsum()
    daily_ret = equity.pct_change().dropna()
    if daily_ret.std(ddof=1) <= 0:
        return 0.0
    return float(daily_ret.mean() / daily_ret.std(ddof=1) * np.sqrt(252))
```

---

## 3. Suggestions

### S-1. `engines.py` `get_entry_marks` — `ctx=None` default argument

**File:** `src/straddle/engines.py:276`

```python
def get_entry_marks(
    self, S: float, T: float, r: float, vix: float, ctx: PricingContext = None
) -> tuple:
```

Using mutable-default `None` and then checking `if ctx else None` is the right pattern, but the type hint should be `Optional[PricingContext]`. This is cosmetic but affects static analysis tools.

**Confidence:** Certain style issue.

---

### S-2. `strategy.py` — `evaluate_trade` force-close computes `pnl=0.0` for trades entered on the last day

**File:** `src/straddle/strategy.py:870–877`

```python
if trade.entry_date >= force_close_at:
    trade.pnl = 0.0
    trade.pnl_pct = 0.0
```

A trade entered on the last day is force-closed at P&L = 0. This is labeled "close flat" in the comment, but in reality the position has positive unrealized value (the premium hasn't been earned yet). A more accurate approach would be to price it at mid using the engine. The current approach is conservative and avoids a double-count, but it slightly understates returns in portfolio mode.

**Confidence:** Speculative — depends on how many trades fall on the last day and what their unrealized value is.

---

### S-3. `plotting.py` — `plt.show()` in library code

**File:** `src/straddle/plotting.py:250`

```python
plt.tight_layout(rect=[0, 0, 1, 0.98])
plt.savefig(output_path, dpi=150, bbox_inches="tight")
plt.show()
```

`plt.show()` blocks execution in non-interactive contexts (e.g., API or CI). The script caller (`run_backtest.py`) doesn't have a `--no-show` flag (only `--no-plot` skips the entire chart). In a server context this could hang.

**Fix:** Move `plt.show()` to the CLI script or guard it with `if sys.stdin.isatty()`.

---

### S-4. `grid_search.py` — `_compute_chain_diagnostics` is O(n²) for large trade lists

**File:** `scripts/grid_search.py:153–178`

```python
matches = [tr for tr in trades if tr.trade_num == child_num]
```

For each chain member, it scans the entire `trades` list looking for the child by `trade_num`. This is O(trades × chain_depth). For a 5-year portfolio backtest with many rolls this could be O(trades²).

**Fix:** Pre-build the index dict (already done in `_compute_chain_stats` in `metrics.py` — reuse that pattern):

```python
by_num = {t.trade_num: t for t in trades}
child = by_num.get(child_num)
```

---

### S-5. `api.py` — CORS wildcard `allow_origins=["*"]` with `allow_credentials=True`

**File:** `src/straddle/api.py:25`

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, ...)
```

The combination of `allow_origins=["*"]` and `allow_credentials=True` is rejected by browsers (CORS spec disallows credential-bearing cross-origin requests to wildcard origins). This is likely a configuration that was never tested with browser-credential flows (cookies/auth headers). If credentials are not needed, `allow_credentials=False` is correct. If credentials are needed, specify explicit origins.

**Confidence:** Certain browser rejection; currently harmless if the API is only called without credentials from the Streamlit UI.

---

### S-6. `streamlit-ui/app.py` — References non-existent `spy_close` and `spy_total_return` keys

**File:** `apps/streamlit-ui/app.py:432–437, 426, 450`

```python
spy_window = data.loc[..., "spy_close"]   # no such column — should be "underlying_close"
metrics.get("spy_total_return", 0)         # no such key — should be "underlying_total_return"
metrics.get("spy_sharpe", 0)              # no such key — should be "underlying_sharpe"
```

The data schema uses `underlying_close` throughout (see `data.py`), and `compute_metrics` returns `underlying_total_return` / `underlying_sharpe` (see `metrics.py:362`). These references produce silent zero-fallbacks (via `.get(key, 0)`) and an empty `spy_window` (falling into the `else` branch at line 439), so the SPY benchmark rows in the UI always show 0%. This is a UI display bug, not a financial calculation error.

**Confidence:** Certain — the key names are wrong; any SPY comparison metric in the Streamlit UI is broken.

**Fix:**

```python
spy_window = data.loc[..., "underlying_close"]
metrics.get("underlying_total_return", 0)
metrics.get("underlying_sharpe", 0)
```

---

### S-7. `app.py` — `spy_allocation_pct` vs `underlying_allocation_pct` naming mismatch

**File:** `apps/streamlit-ui/app.py:133–139, 320`

The Streamlit UI reads from `PARAMS.get("spy_allocation_pct", 0.40)` and writes `"spy_allocation_pct"` into the params dict:

```python
p["spy_allocation_pct"] = float(spy_allocation_pct) / 100.0
```

But the engine reads `params.get("underlying_allocation_pct", ...)` (see `portfolio.py:295`). The key names don't match. The Streamlit UI silently passes 0.0 to the blend allocation.

**Confidence:** Certain — the keys differ; `underlying_allocation_pct` is what the engine reads.

**Fix:** Change line 320 to:

```python
p["underlying_allocation_pct"] = float(spy_allocation_pct) / 100.0
```

---

### S-8. `data.py` — `_load_spy_from_yahoo` doesn't flush `master_df` when `master_df.empty` after download

**File:** `src/straddle/data.py:123`

```python
return master_df.loc[req_start:req_end].copy()
```

If `needs_download=True` and the download returns an empty DataFrame (e.g., yfinance outage, rate limit), `raw.empty` is True (line 97), the `if not raw.empty:` block is skipped, `master_df` remains empty, and line 123 returns an empty DataFrame without raising. The caller (`run_backtest`) will fail silently on the first `.loc[eval_date]` call.

**Confidence:** Certain logic gap; requires yfinance failure.

**Fix:** Add a guard after the download block:

```python
if master_df.empty:
    raise RuntimeError(
        f"Failed to download market data for {download_start.date()}–{download_end.date()}. "
        "Check yfinance connectivity."
    )
```

---

### S-9. `conftest.py` `sample_data` — VIX can go negative

**File:** `tests/conftest.py:68`

```python
"vix_close": 14.0 + np.random.randn(len(dates)) * 2.0,
```

With seed 42, `np.random.randn` values range from about -3 to +3 (σ=1), so `vix_close` could occasionally be ~8. But with a different seed or long runs, this could produce negative VIX values, which would propagate into `sigma = vix_d / 100.0` → negative BS vol → `nan` in `bs_price` → silent NaN propagation in the entire trade evaluation. The fixture should clamp:

```python
"vix_close": np.maximum(14.0 + np.random.randn(len(dates)) * 2.0, 5.0),
```

**Confidence:** Speculative with seed=42; certain for some seeds.

---

### S-10. `engines.py` — `_baw_critical_put` uses a hardcoded `hi=K-1e-6` bracket that fails when `K < 1e-6`

**File:** `src/straddle/engines.py:175`

```python
lo, hi = 1e-6, K - 1e-6
```

For very low-priced options (e.g., a cheap B3 option worth R$0.001), `K` could be less than `2e-6`, making `lo >= hi`. `brentq` would then raise a `ValueError` which is caught by the broad `except Exception: S_star = K * 0.5`. The fallback is documented and conservative, but the bracket construction is fragile.

**Confidence:** Certain for `K < 2e-6`; in practice PETR4 options have `K >= R$10` so this never fires.

---

## 4. Test Coverage Assessment

### What's covered well
- Black-Scholes primitives: exhaustive edge-case coverage (T=0, deep ITM/OTM, zero vol)
- `apply_skew`, `strike_from_delta`: mathematically verified
- `SyntheticEngine` core interface: determinism, entry/daily/delta methods
- Calendar utilities: `get_third_friday`, holiday adjacency, DTE range
- `Trade` properties: all `active_*` properties with and without leg rolls
- `calculate_reg_t_strangle_margin`: formula verification including minimum floor
- `PortfolioManager` accounting: BPR accumulation, capacity gate, cooldown
- Vol filter cache key correctness (bug-fix regression)
- Iron condor: entry construction, margin, stop/defensive gating
- `MarketEngine` execution modes: all 4 modes, bid/ask/mark selection, zero-bid fallback
- `runs_store`: DB path anchoring, label preservation

### Gaps worth addressing

**G-1. No test for `evaluate_trade_step` directly.** The function contains the most complex financial logic (overshoot model, gap pricing, 21-DTE roll, FORCE_CLOSE) but is only tested indirectly through `run_backtest`. A direct unit test with synthetic data that forces specific exit types would catch regressions early. Particularly missing: the STOP exit with each overshoot regime (ORDERLY/NORMAL/VIOLENT/GAP).

**G-2. No test for `evaluate_trade` force-close at end of backtest window.** `test_strategy.py` has `TestChainAccounting` but the `force_close_at` path (when `expiration > end_ts`) is untested. This is where Issue I-6 lurks.

**G-3. No test for negative net_credit guard in `build_entry`.** The function returns `None` when `net_credit <= 0`. There's no test that verifies this guard fires under conditions where it should (very low-vol, high commission relative to premium).

**G-4. No test for `is_vol_blocked` with the `rv_pct` or `ivr` mode in a full backtest.** `TestIvrVolFilter` tests `_build_vol_filter` in isolation but not the integration with `run_backtest`.

**G-5. `compute_portfolio_metrics` has no unit tests.** The function is complex (Sharpe from MTM, chain stats, BPR utilization). `test_portfolio.py` tests `PortfolioManager` accounting and the full integration via `run_portfolio_backtest`, but `compute_portfolio_metrics` itself is not unit-tested.

**G-6. No test for the Streamlit `build_params()` function.** The S-6 and S-7 bugs (wrong key names) would have been caught by a simple test asserting that `build_params()` produces a dict with `underlying_allocation_pct` and that the data schema uses `underlying_close`.

**G-7. No test for `data.py` empty download handling.** Mocking yfinance to return an empty DataFrame and verifying that the loader raises (not silently returns empty) would catch Issue S-8.

**G-8. No test for `apply_market_preset` with the API path (no `explicitly_set`).** The test `test_params.py` covers `explicitly_set={"tick_size"}` but not the case where the API path drops an explicit override that matches the SPY default (Issue I-5).

---

## 5. Top 3 to Fix First

### 1. `S-6` + `S-7` — Streamlit UI broken metric keys (30-minute fix, user-visible)

The SPY benchmark column always shows 0% in the Streamlit UI because `spy_close`, `spy_total_return`, and `spy_sharpe` don't exist. Combined with the `spy_allocation_pct` vs `underlying_allocation_pct` mismatch, the blend cash mode is also broken. These are silent failures — the UI doesn't error, it just shows wrong numbers. Fix: rename 4 strings in `app.py`.

### 2. `I-2` — API `failed` error not persisted to SQLite (1-hour fix, operational)

When a backtest fails, the error is stored in-memory only. After any server restart or pod replacement, the error is gone: clients see `status="failed"` with no reason. This is especially painful for long-running B3 market-mode backtests. Fix: pass `result={"error": str(e)}` to `upsert_run`.

### 3. `I-10` — Portfolio-mode Sharpe denominator (2-hour fix, affects research validity)

`_compute_sharpe_from_daily_pnl` divides by `init` instead of running equity, producing a systematically biased (too low) Sharpe for portfolio-mode results. All published PETR4/BOVA11 grid search Sharpe numbers in portfolio mode are affected. Fix: use `(init + daily_pnl.cumsum()).pct_change()` as the return series.

---

## 6. Architectural Concerns

### A-1. Dual equity curve construction

The codebase has two separate equity curve construction paths:
- `run_backtest` builds `equity_curve` from `daily_marks` delta-sums (the canonical MTM series)
- `compute_portfolio_metrics` calls `_compute_mtm_equity` which rebuilds the same series from `daily_marks` independently
- `run_backtest.py` (CLI) computes `final_balance` a third way (sum of terminal P&Ls)

These three paths can yield slightly different numbers for the same backtest. The `_compute_mtm_equity` function in `metrics.py` and the equity-builder in `run_backtest` are logically identical but are separate implementations. A single authoritative function passed around (rather than two implementations of the same loop) would eliminate drift.

### A-2. `_worker_cache` in `grid_search.py` is a mutable global that outlives individual runs

The module-level `_worker_cache` dict stores `(data, engine)` pairs keyed by `(market, start_date, end_date)`. Since `engine` holds an open SQLite connection, if the script is interrupted without calling `_close_worker_cache()`, the connections are never explicitly closed (they rely on `__del__`). More significantly, the engine's `_exec_mode` is mutated between combos (Issue I-1), which is only safe because loky uses separate processes. This design makes it easy to introduce a subtle cross-combo contamination bug if the execution model changes.

### A-3. No rate limiting or authentication on the API

`api.py` exposes `/backtest` with `allow_origins=["*"]`. A single client could trigger dozens of concurrent long-running backtests (each a background thread/task). There's no concurrency cap, rate limiting, or API key. For internal tooling this is acceptable; for any external exposure it's a denial-of-service vector.

### A-4. `PARAMS` is a module-level mutable dict

All downstream code does `dict(PARAMS)` to get a copy, which is the correct pattern. However, if any module-level code (e.g., a test or a Streamlit re-run) inadvertently calls `PARAMS["key"] = value`, it silently mutates the global default for the rest of the process lifetime. Consider using `types.MappingProxyType(PARAMS)` to make it immutable, or at least add a comment warning against mutation.

### A-5. The `MarketEngine` / `SyntheticEngine` interface is good but not formalized

Both engines implement the same 7 methods (`get_entry_marks`, `get_daily_mark`, `get_daily_delta`, `get_leg_mark`, `get_leg_mark_with_source`, `find_strike_at_delta`, `get_gap_open_mark`) plus `apply_fill_adj` and `uses_real_fills`. There is no ABC or Protocol that enforces this contract. Adding a `typing.Protocol` for `PricingEngine` would allow mypy to catch any new engine implementation that's missing a method, and would make the interface explicit for future contributors.

---

## Summary Table

| ID   | Severity   | Module           | Issue                                                         | Confidence   |
|------|------------|------------------|---------------------------------------------------------------|--------------|
| I-1  | Important  | grid_search.py   | `engine._exec_mode` mutation on cached object (fragile)       | Certain      |
| I-2  | Important  | api.py           | Failed run error not persisted to SQLite                      | Certain      |
| I-3  | Important  | strategy.py      | O(n²) loop in `_build_vol_filter` for rv_pct/ivr modes       | Certain      |
| I-4  | Important  | run_backtest.py  | `final_balance` printed diverges from equity curve            | Certain      |
| I-5  | Important  | api.py/params.py | `apply_market_preset` silently drops explicit API overrides   | Certain      |
| I-6  | Important  | strategy.py      | Fallback expiry path missing `daily_marks.append`             | Likely       |
| I-7  | Important  | portfolio.py     | Portfolio cash/margin inconsistency on adverse moves          | Certain      |
| I-8  | Important  | data.py          | 7-day max-gap threshold too loose for detecting missing weeks  | Speculative  |
| I-9  | Important  | api.py           | `risk_free_rate` API field name misleading / maps wrong key   | Certain      |
| I-10 | Important  | metrics.py       | Portfolio Sharpe denominator uses init balance not running eq  | Certain      |
| S-1  | Suggestion | engines.py       | `Optional[PricingContext]` type hint missing                  | Certain      |
| S-2  | Suggestion | strategy.py      | Force-close on last-day trade closes at P&L=0 (not mid)       | Speculative  |
| S-3  | Suggestion | plotting.py      | `plt.show()` in library code blocks non-interactive contexts  | Certain      |
| S-4  | Suggestion | grid_search.py   | `_compute_chain_diagnostics` O(n²) chain traversal            | Certain      |
| S-5  | Suggestion | api.py           | CORS wildcard + credentials=True is browser-rejected          | Certain      |
| S-6  | Suggestion | app.py           | Wrong metric keys: `spy_close`, `spy_total_return`, `spy_sharpe` | Certain  |
| S-7  | Suggestion | app.py           | `spy_allocation_pct` written but `underlying_allocation_pct` read | Certain  |
| S-8  | Suggestion | data.py          | Empty yfinance download returns silently instead of raising   | Certain      |
| S-9  | Suggestion | conftest.py      | VIX fixture can produce negative values with unlucky seeds    | Speculative  |
| S-10 | Suggestion | engines.py       | BAW bracket `lo, hi = 1e-6, K-1e-6` fails when K < 2e-6      | Certain      |
