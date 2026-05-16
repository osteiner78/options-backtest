# Refactor Scan: `src/`

**Target:** `src/straddle/` (10 modules, 4,826 lines)  
**Date:** 2026-05-15  
**Verdict tally:** 2 ✅, 3 🕐, 2 ⚠️, 3 ❌

---

## 1. ✅ God function: `evaluate_trade_step` in `strategy.py`

**What.** `evaluate_trade_step` (strategy.py:570–835, 265 lines) handles five responsibilities in one function: defensive leg rolls, daily marks with iron-condor branching, price-stop with overshoot regime classification (ORDERLY/NORMAL/VIOLENT/GAP), profit-target check, 21-DTE management and roll continuation, and expiry detection. The overshoot model alone (L676–750) is a 75-line nested block with its own data extraction from surrounding index lookups, gap-detection arithmetic, regime branches, and fill-quantity calculations.

```python
# strategy.py:570 — function signature swallows 7 params + data + engine + params dict
def evaluate_trade_step(
    trade: Trade,
    eval_date: pd.Timestamp,
    data: pd.DataFrame,
    engine,
    params: dict,
) -> TradeStepResult:
```

**Why it matters.** This function has been the source of multiple production bugs (force-close double-append, entry_db_pct scale, IVR inversion, gap fill adjustment — all documented in CLAUDE.md and research reports). Testing it requires constructing an entire trade, data frame slice, and populated params dict. A unit test of "does the overshoot model pick the right regime when daily range is 2.5%?" is impossible without dragging in the entire daily-marks pipeline. Adding a new exit type (e.g., trailing stop) would touch the inner logic of a 265-line block.

**Proposed refactor.** Extract three things:  
- **OvershootCalculator** class: takes gap/range params, returns (fill_pnl, overshoot_frac, regime). Pure function, no DataFrame dependency.  
- **ExitEvaluator** class or small functions: `_check_profit_target()`, `_check_stop_overshoot()`, `_check_21dte_roll()`, `_check_expiry()` — each returns `Optional[TradeStepResult]`.  
- Keep `evaluate_trade_step` as a ~40-line orchestrator that fetches marks and delegates to exit evaluators.

```python
# Target shape (~40 lines)
def evaluate_trade_step(trade, eval_date, data, engine, params) -> TradeStepResult:
    dte_rem, S_d, vix_d, r_d, T_d = _extract_daily_state(trade, eval_date, data, params)
    attempt_defensive_leg_roll(...)
    put_mid, call_mid, mid_d, close_cost, pnl, pnl_pct = _mark_position(...)
    trade.daily_marks.append((eval_date, pnl))
    if result := _check_stop(trade, eval_date, data, pnl, pnl_pct, dte_rem, ...):
        return result
    if result := _check_profit_target(pnl_pct, params):
        return result
    ...
```

**Effort estimate: M** (6–10 hours). The riskiest part is the overshoot model — it touches gap-open pricing, index-lookback, and regime thresholds that must produce identical results. Extract it first with a characterisation test (snapshot the current output for 20 representative scenarios, refactor, assert unchanged).

**Blast radius.** `strategy.py` (1 file), plus `portfolio.py` which calls `evaluate_trade_step` once per open position per day. 2 test files (`test_strategy.py`, `test_portfolio.py`). The function signature stays the same so callers are unaffected.

**Value vs effort verdict: ✅ Worth it now.** High value (bug hotspot, future feature blocker), manageable risk (signature-preserving internal refactor).

**Trigger to revisit:** Already triggered — 3+ bugs tracked to this function in the last two development phases.

---

## 2. ✅ SQL queries as string literals in `MarketEngine`

**What.** `MarketEngine` (engines.py:477–1003) embeds 6 distinct SQL queries as f-string literals spread across `_best_row`, `_strike_ask`, `_strike_mark`, `get_db_expiration`, `get_daily_delta`, and `find_strike_at_delta`. The CDI/non-CDI column selection logic is duplicated across these methods:

```python
# engines.py:888–889 (find_strike_at_delta)
iv_clause = "AND implied_volatility < 2.0" if self._has_underlying_col else ""
delta_col = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"

# engines.py:941–943 (_best_row) — identical logic
iv_clause = "AND implied_volatility < 2.0" if self._has_underlying_col else ""
delta_col = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
iv_where = "AND implied_volatility_cdi < 2.0" if (self._use_cdi and self._has_cdi_cols) else iv_clause
iv_col = "implied_volatility_cdi" if self._use_cdi and self._has_cdi_cols else "implied_volatility"

# engines.py:759–760 (get_daily_delta) — same pattern again
delta_col_name = "delta_cdi" if self._use_cdi and self._has_cdi_cols else "delta"
```

**Why it matters.** Adding a new column to the DB schema or changing the CDI logic requires edits in 3–4 methods. The f-string SQL is invisible to linting (no syntax checking). This pattern was flagged in report 005 ("fragile SQL column fstring") and report 004 ("market engine test coverage") as a source of silent regressions when the DB schema drifted between SPY and B3 databases.

**Proposed refactor.** Extract column-name resolution into a `_ColumnSet` dataclass computed once in `__init__`:

```python
@dataclass
class _ColumnSet:
    delta: str          # "delta" or "delta_cdi"
    iv: str             # "implied_volatility" or "implied_volatility_cdi"
    iv_clause: str      # "" or "AND implied_volatility < 2.0"
    
# __init__:
self._cols = _ColumnSet(delta=..., iv=..., iv_clause=...)
# Usage: f"SELECT {self._cols.delta} FROM options_data WHERE ..."
```

Centralise the 3 SQL query templates as module-level constants with `.format()` substitution rather than f-strings attached to method-local variables.

**Effort estimate: S** (2–3 hours). Pure internal refactor with no behavioural change. The riskiest part is verifying the column-name resolution produces identical SQL for all four combinations of `_has_underlying_col` × `_use_cdi` in the B3 RB3 database.

**Blast radius.** `engines.py` only. Callers use the public interface (`get_entry_marks`, `get_daily_mark`, etc.), which is unchanged. Tests in `test_engines.py` remain valid.

**Value vs effort verdict: ✅ Worth it now.** Quick win, already flagged twice before, makes future DB schema changes safe instead of scary.

**Trigger to revisit:** Already triggered. Do it before the next database migration.

---

## 3. 🕐 Flat `PARAMS` dict loses type safety

**What.** `params.py` defines 7 TypedDicts (`BacktestParams`, `StrategyParams`, `PricingParams`, `OvershootParams`, `PortfolioParams`, `MarketParams`, `PaperTradingParams`) and then merges them into a flat `PARAMS: dict`. Every downstream function accepts `params: dict` and accesses keys with `params.get("key", default)`. The TypedDicts are defined but never used for validation at call sites.

```python
# strategy.py — everywhere
prof = params["profit_target_pct"]
stop = params["stop_loss_pct"]
manage_at_dte = params["manage_at_dte"]

# engines.py
self.vix_iv_mult = params.get("vix_iv_mult", 1.0)
self.put_slope = params.get("put_slope", 0.30)
self.call_slope = params.get("call_slope", 0.10)

# portfolio.py
cash_yield_annual = params.get("cash_yield_annual", 0.04)
max_bpr_allocation=params.get("max_bpr_allocation", 0.30)
```

**Why it matters.** Typos in key names cause silent defaults instead of errors. Renaming a parameter requires grep-and-hope across 8 files. New contributors cannot discover the full parameter surface without reading all of `params.py`. The `apply_market_preset` function mutates the dict, making it hard to reason about which override takes precedence in long-running server processes.

**Proposed refactor.** Freeze the flat dict into a frozen dataclass or `NamedTuple` after `apply_market_preset` runs. Pass the structured object instead of `dict`:

```python
@dataclass(frozen=True)
class BacktestConfig:
    start_date: str
    end_date: str
    initial_balance: float
    commission_per_leg: float
    target_delta: float
    dte_min: int
    dte_max: int
    profit_target_pct: float
    stop_loss_pct: float
    manage_at_dte: int
    # ... all 50+ fields
```

**Effort estimate: L** (15–25 hours). Every function signature changes (`params: dict` → `config: BacktestConfig`). Every call site needs `params["key"]` → `config.key`. Tests need fixture updates. The riskiest part is the migration itself — it's a large mechanical change with potential for silent breakage if a key name differs between the dict and the dataclass.

**Blast radius.** 8 source files, 9 test files, 3 script files, the API. ~50+ call sites that unpack individual keys. This is the single largest mechanical change possible in the codebase.

**Value vs effort verdict: 🕐 Worth it eventually.** The type-safety and discoverability gain is real, but the blast radius is too large for the current level of codebase churn. Revisit when the team is adding a significant new dimension to the parameter grid (like a new market or execution mode) that would benefit from compile-time safety.

**Trigger to revisit:** When adding a 4th market preset to `MARKET_PRESETS`, or when >3 parameter names change in a single quarter.

---

## 4. 🕐 Iron condor / strangle branching duplicated across 4 locations

**What.** The pattern "if iron_condor: 4 legs / n_comm=4 / different mid calculation, else: 2 legs / n_comm=2" appears in four places:

- `build_entry` (strategy.py:264–292)
- `evaluate_trade_step` (strategy.py:631–666)
- Portfolio entry processing (portfolio.py:349–358)
- Portfolio roll handling (portfolio.py:426–435)

```python
# Duplicate pattern (4 locations)
if trade.is_iron_condor:
    n_comm = 4
    mid_close_ps = short_mid_d - long_mid_d  # 4-leg net
    close_cost = (engine.apply_fill_adj(short_mid_d, "close") 
                  - engine.apply_fill_adj(long_mid_d, "open")) * mult + 4.0 * comm
else:
    n_comm = 2
    mid_close_ps = mid_d  # 2-leg net
    close_cost = engine.apply_fill_adj(mid_d, "close") * mult + 2.0 * comm
```

**Why it matters.** Adding a new strategy type (e.g., single-leg naked put) would require hunting down every one of these branches. The fill-adjustment logic for iron condors was already corrected once (the comment at strategy.py:644–649 documents a prior incorrect implementation that "pushed both directions the same way, under-stating the close cost").

**Proposed refactor.** Move the leg-count and close-cost computation onto the `Trade` class as computed properties or a method:

```python
# On Trade dataclass
@property
def n_legs(self) -> int:
    return 4 if self.is_iron_condor else 2

def close_cost(self, engine, mult, comm, mid_d, short_mid_d, long_mid_d, dte_rem):
    """Compute close cost for this trade's structure."""
    ...
```

**Effort estimate: S** (2–3 hours). Add computed properties to the `Trade` dataclass, replace the 4 duplicated branches with calls. Same test coverage applies.

**Blast radius.** `Trade` dataclass in `strategy.py` + the 4 call sites in `strategy.py` and `portfolio.py`. 2 test files.

**Value vs effort verdict: 🕐 Worth it eventually.** Low effort but low urgency — the current duplication is bounded and the iron condor mode is not actively changing. Do it alongside the god-function refactor (#1) since they touch the same lines.

**Trigger to revisit:** When adding a 3rd strategy mode (e.g., naked put, ratio spread, or butterfly).

---

## 5. 🕐 Calendar utilities mixed into `strategy.py`

**What.** `get_monthly_expiration`, `get_entry_dates`, `get_third_friday`, `_adjust_for_holiday`, `_get_trading_day_set` (strategy.py:107–222, ~115 lines) are pure calendar utilities. They have no strategy-specific logic — they deal with 3rd-Friday expirations, holiday adjustments, and trading-day lookups. The `_TRADING_DAY_SETS` cache at L113 is a module-level global in `strategy.py`.

```python
# strategy.py:109-113
# Module-level cache: built once per calendar name, valid 2005–2030.
# Avoids creating mcal calendar objects and querying single-day schedules
# inside the hot backtest loop (get_monthly_expiration is called every
# trading day during roll management).
_TRADING_DAY_SETS: dict = {}  # calendar_name -> frozenset[pd.Timestamp]
```

**Why it matters.** Calendar logic is a reusable concern (needed by `data.py` for valid-trading-day filtering, potentially by `portfolio.py` for cooldown logic). It's currently coupled to `strategy.py`'s module namespace. The lazy-import of `pandas_market_calendars` inside `_get_trading_day_set` (L119) hides the dependency.

**Proposed refactor.** Extract to `straddle/calendar.py` (new module, ~120 lines). Expose `get_third_friday`, `get_monthly_expiration`, `get_entry_dates`, `adjust_for_holiday`. Keep the trading-day-set cache there. Re-export from `__init__.py` only if needed externally.

**Effort estimate: S** (1–2 hours). Pure extraction — move functions, update imports in `strategy.py` and `portfolio.py`. No behavioural change.

**Blast radius.** `strategy.py` (3 call sites), `portfolio.py` (2 call sites), `__init__.py` (1 export). Tests in `test_strategy.py` wrap these indirectly via `run_backtest`.

**Value vs effort verdict: 🕐 Worth it eventually.** Trivial effort but zero immediate pain — the functions are well-organised within strategy.py and aren't causing problems. Do it when someone needs calendar utilities in a 3rd module.

**Trigger to revisit:** If `data.py` or a new module needs trading-day validation, or if the `pandas_market_calendars` dependency is being reconsidered.

---

## 6. ⚠️ Module-level caches require explicit lifecycle management

**What.** `strategy.py` maintains two module-level mutable caches: `_VOL_CACHE` (L19) for vol-filter boolean Series, and `_TRADING_DAY_SETS` (L113) for trading-day frozensets. The public API exports `clear_vol_cache()` and `clear_strategy_caches()` because grid-search scripts must call them between runs to avoid stale cache hits.

```python
# strategy.py:19-24
_VOL_CACHE: dict = {}

def clear_vol_cache() -> None:
    """Clear the vol-filter cache. Call before each grid-search run."""
    _VOL_CACHE.clear()
```

The comment on L32-34 explains why an id()-based cache key was replaced: "id() reuses memory addresses after GC, which can silently return stale results across consecutive backtests." This was bug I-2 documented in the research notebook.

**Why it matters.** This is stateful design that requires caller discipline. Forgetting to call `clear_vol_cache()` between grid-search iterations produces silent wrong results. The API server's background-task workers (`_run_backtest_task` in `api.py`) share the same process — concurrent backtests with different vol-filter thresholds can collide in the cache.

**Proposed refactor.** Make the cache local to the backtest run. Option A: store it on the engine (since vol-filter data depends on the engine's date range). Option B: pass it as a context object through the `params` dict (or the BacktestConfig from item #3). Option C: use `functools.lru_cache` with a cache-key that includes the params dict hash — but the params dict is mutable, making that fragile.

Simplest approach: move `_build_vol_filter` and `_VOL_CACHE` into a small `VolFilter` class instantiated per-backtest:

```python
class VolFilter:
    def __init__(self, data, params):
        self._data = data
        self._params = params
        self._cache = {}
    
    def is_blocked(self, eval_date, vix_d) -> bool:
        ...
```

`run_backtest` creates one `VolFilter` at the top of each run. No more global state.

**Effort estimate: M** (5–7 hours). Changes the vol-filter API surface (`is_vol_blocked` becomes a method call rather than a module-level function). The riskiest part is ensuring the per-run design doesn't introduce memory leaks in the API server (long-lived process with many sequential backtests). Need to verify that the old DataFrames get GC'd.

**Blast radius.** `strategy.py` (vol-filter functions + call sites in `run_backtest` and `evaluate_trade_step`), `portfolio.py` (calls `is_vol_blocked` in the daily loop), `api.py` (server process lifecycle). Tests in `test_strategy.py` explicitly call `clear_vol_cache()` — those tests should still pass after the refactor.

**Value vs effort verdict: ⚠️ Risky (real value but high blast radius — defer unless forced).** The current design works correctly when callers follow the documented pattern. The risk of introducing a memory leak in the API server during the refactor outweighs the benefit unless there's evidence of cache-related bugs in production.

**Trigger to revisit:** If the API server shows non-deterministic results under concurrent load, or if a new developer ships a bug caused by a stale vol-filter cache.

---

## 7. ⚠️ Duplicate equity-curve construction logic

**What.** `run_backtest` (strategy.py:1044–1063) and `run_portfolio_backtest` (portfolio.py) use different equity-curve construction paths:

- **strategy.py:** Post-loop — iterates `trades[].daily_marks`, computes per-day P&L deltas, accumulates into a `pd.Series`, adds initial balance.
- **portfolio.py:** In-loop — `portfolio.record_daily_state()` appends to `portfolio.equity_curve` list-of-dicts, converted to DataFrame at L501–503.

`_compute_mtm_equity` in `metrics.py` (L166–191) builds a *third* equity curve from daily_marks, used by `compute_portfolio_metrics`. This is the same algorithm as the strategy.py post-loop builder but implemented differently (pandas groupby vs manual loop).

**Why it matters.** Three implementations of the same algorithm drift apart. The I-10 Sharpe correction bug (using initial balance instead of running equity) was present in one path but not others. If someone changes the equity-curve semantics (e.g., adding cash-yield compounding), they'd need to find and update all three.

**Proposed refactor.** Use `_compute_mtm_equity` from `metrics.py` as the single canonical equity-curve builder. Have `run_backtest` call it instead of the manual loop. Have `run_portfolio_backtest` call it instead of building its own from the portfolio ledger. This was partially done in the I-10 fix but the manual loop in `run_backtest` remains.

**Effort estimate: M** (3–5 hours). Need to verify `_compute_mtm_equity` produces identical results to the manual loop for all edge cases (trades with 0 or 1 marks, overlapping trades, force-close trades with missing dates). The riskiest part is subtle differences in how `force_close_at` trades are handled in `run_backtest`'s manual loop (L1053–1056 has a special case).

**Blast radius.** `strategy.py`, `portfolio.py`, `metrics.py`. 3 test files. All backtest output is equity-curve data — any regression is visible.

**Value vs effort verdict: ⚠️ Risky (real value but verify before touching).** Consolidation is clearly correct, but the equity curve is the single most critical output of the entire system. Characterise the current output first with a snapshot test covering all combinations of exit types, roll chains, and force-close scenarios. Only refactor once you have a safety net.

**Trigger to revisit:** When the next equity-curve bug is found, or when adding a new backtest mode that would create a 4th equity-curve path.

---

## 8. ❌ `api.py` imports private symbols from `data.py`

**What.** `api.py` imports `_DB_FIRST` and `_db_coverage_end` from `straddle.data` (L17-18 of api.py). These are private (underscore-prefixed) symbols.

```python
# api.py (inferred from exploration)
from straddle.data import _DB_FIRST, _db_coverage_end
```

**Why it matters.** Breaks encapsulation. The private prefix signals "this can change without notice." If `data.py` renames or removes these, `api.py` breaks at import time.

**Proposed refactor.** Either: make them public (remove underscore prefix) and re-export from `__init__.py`, or expose a public `get_db_coverage_info()` function in `data.py` that returns both values.

**Effort estimate: S** (<1 hour). Rename two symbols or add one function.

**Value vs effort verdict: ❌ Not worth it.** The API module is the only consumer. The private import is a slight style violation but causes zero operational pain. The symbols in question (`_DB_FIRST`, `_db_coverage_end`) are stable (the DB start date hasn't changed in years, and the coverage query is simple). No reason to touch working code for purity.

---

## 9. ❌ `_compute_trade_stats` duplicates `_compute_exit_stats` logic

**What.** `_compute_trade_stats` (metrics.py:43–79) returns a flat dict with per-exit-type counts/wins/avgs using keys like `n_p`, `wr_p`, `avg_p`. `_compute_exit_stats` (metrics.py:213–248) returns the same data as a list of dicts for frontend rendering. Both iterate over the same trades with the same filtering logic.

```python
# metrics.py:52-67 — _compute_trade_stats
def _get_stats(xt):
    ts = [t for t in trades if t.exit_type == xt]
    ...
n_p, wr_p, avg_p = _get_stats("PROFIT")
n_s, wr_s, avg_s = _get_stats("STOP")
# ... 6 exit types

# metrics.py:226-237 — _compute_exit_stats (same loop, different output format)
for xt in exit_types:
    ts = [t for t in trades if t.exit_type == xt]
    pnls = np.array([t.pnl for t in ts if t.pnl is not None])
    ...
```

**Why it matters.** Adding a new exit type means updating two functions. The duplicate iteration on large trade lists is negligible performance-wise (trades are typically < 200 per backtest).

**Proposed refactor.** Have `_compute_trade_stats` call `_compute_exit_stats` and reformat. Or vice versa.

**Effort estimate: S** (<1 hour).

**Value vs effort verdict: ❌ Not worth it.** The two functions serve different consumers (flat dict for API responses, list-of-dicts for the frontend table). Merging them would create a less convenient output shape for one consumer. The duplication is mechanical and unlikely to drift. Leave it.

---

## 10. ❌ `_run_backtest_task` has too many concerns (70-line function)

**What.** `_run_backtest_task` in `api.py` (L229–299) loads data, creates an engine, runs a backtest (branching on portfolio mode), computes metrics, serializes results to the response format, and persists to SQLite — all in one function.

**Why it matters.** Cannot unit-test the orchestration flow without an actual database and data files. The branching on `is_portfolio` creates two nearly identical code paths for trade serialization, equity curve extraction, and response building.

**Proposed refactor.** Extract data-loading, backtest-execution, metrics-computation, and response-building into separate functions. Use a small `BacktestOrchestrator` class.

**Effort estimate: M** (3–5 hours).

**Value vs effort verdict: ❌ Not worth it.** The function is linear and readable. The branching between portfolio and single-position modes is the only complexity. Extracting it would add indirection without making testing easier (you'd still need a database and engine to test it meaningfully). The integration-test coverage from actually running the API server is sufficient. Leave it alone unless the function grows beyond 100 lines.

---

## Top 3 Refactors Ranked by Value/Effort

| Rank | Item | Verdict | Effort | Why |
|------|------|---------|--------|-----|
| 1 | **Extract overshoot model from `evaluate_trade_step`** | ✅ M | 6–10h | Bug hotspot, blocks unit testing, most future features touch this |
| 2 | **Centralise SQL column-name resolution in MarketEngine** | ✅ S | 2–3h | Flagged twice before, makes DB changes safe |
| 3 | **Extract iron-condor/strangle branching onto Trade class** | 🕐 S | 2–3h | Cheap, pairs well with #1, prevents future drift |

## Do NOT Refactor

- **Flat PARAMS dict → structured object (#3):** Ideal end-state but the blast radius is too large (8 files, 50+ call sites). Wait for a natural forcing function (new market, new parameter dimension).
- **`_compute_trade_stats` / `_compute_exit_stats` consolidation (#9):** Duplication that causes zero pain. Not worth touching.
- **`_run_backtest_task` extraction (#10):** Linear, readable, well-tested by integration. Indirection would make it worse.

## Architectural Observation

This is a **pipeline architecture with a flat config bus**. `params.py` produces a flat dict, which flows through `data.py → engines.py → strategy.py → metrics.py → plotting.py`. The `portfolio.py` module is a fork off `strategy.py` that reuses `Trade`, `evaluate_trade_step`, and `build_entry` but builds a parallel execution path (`run_portfolio_backtest`).

The single biggest structural risk is that **`strategy.py` and `portfolio.py` are drifting apart** — `run_portfolio_backtest` implements its own equity-curve building, its own daily loop, its own force-close logic, and its own margin recalculation that all mirror logic in `run_backtest`/`evaluate_trade`. If strategy.py and portfolio.py continue to diverge, the next equity-curve or P&L-calculation bug will need to be fixed in two places, and the odds of missing one go up with each change.

The fix is not to merge them (they serve different purposes) but to extract shared concerns (equity-curve construction, force-close) into functions that both callers use. Item #7 (equity-curve consolidation) is the first step on that path.
