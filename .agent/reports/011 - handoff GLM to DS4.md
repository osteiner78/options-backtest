# v5 Confirmation Grid — Orchestrator Handoff Report

**Date:** 2026-05-14  
**Branch:** `b3-backtest`  
**Status:** In progress — Cell E (v3 reproduction) was running in notebook, Cells F–H not yet run

---

## Project Goal

Determine whether a short strangle VRP (volatility risk premium) exists on B3 BOVA11 and is capturable at various execution price assumptions, using grid search across execution modes (bid_ask, mid_minus_1tick, mid, mid_plus_1tick).

---

## Research Question

**Which conclusion does the data support?**
- **A)** VRP exists and is capturable even at bid_ask (most conservative)
- **B)** VRP exists but is consumed by spread (break-even between mid and bid_ask)
- **C)** VRP is marginal — positive at mid, negative at bid_ask
- **D)** No capturable VRP — negative across all execution modes

---

## What Was Done

### 1. B3 Price Validation (Part 1)
- Validated rb3 prices against B3 official bulletin
- Fixed "PUTT" vs "PUT" bug → 20/20 contracts matched
- Verdict: PARTIAL (70% within ±10%)
- All puts are EURO; 567 CALLs are AMER, 268 CALLs + 835 PUTs are EURO
- Volume ratio ~969× (rb3=turnover, B3 TradeQty=trade count)
- Report: `docs/2026-05-13 - rb3 price validation.md`

### 2. Execution Mode Implementation (v4)
- Implemented 4 execution modes in `engines.py`: bid_ask, mid_minus_1tick, mid, mid_plus_1tick
- bid_ask: sell at bid, buy at ask (most conservative real-world assumption)
- mid_minus_1tick: sell at mid - 1 tick
- mid: sell at mark (theoretical mid)
- mid_plus_1tick: sell at mid + 1 tick (optimistic)
- tick_size = 0.05 (B3 parameter)
- Removed volume_filtered (was identical to mid, correlation 1.000)

### 3. Expiration Fix (Plan 010)
- **Problem**: B3 BOVA11 used 3rd-Monday expirations before May 2021. The strategy computed 3rd-Friday dates, causing ~70% of train-period entries to fall back to synthetic pricing (5% adj vs ~40% real spread)
- **Fix**: `MarketEngine.get_db_expiration()` now queries DB for actual available expirations
- `get_monthly_expiration()` and `get_entry_dates()` accept optional `engine` parameter, passed through from `run_backtest()` and `run_portfolio_backtest()`
- Weekly expiration bug: initial `get_db_expiration()` returned weekly expirations → added `expected_month` parameter with ±5 day window filter

### 4. v5 Grid Search — Completed
- 4 execution modes × 96 combos × 2 periods = 192 backtests
- Results cached: `data/B3/v5_grid_search_results.parquet` (34,567 bytes, May 14 12:34)

### 5. v5 Notebook Cells A–D — Completed
- Cell A: Boxplots of Sharpe by execution mode  
- Cell B: Break-even analysis  
- Cell C: Heatmap of Sharpe by execution_mode × target_delta  
- Cell D: DB coverage by period and mode (fixed `*100` display)

---

## Current State of Notebook

**File:** `research/2026-05-14 - B3 - v5 confirmation grid.ipynb`

| Cell | Label | Status | Notes |
|------|-------|--------|-------|
| 0 | Context markdown | Done | |
| 1 | Imports | Done (exec=1) | |
| 2 | Grid def markdown | Done | |
| 3 | GRID dict | Done (exec=2) | 96 combos |
| 4 | Run config markdown | Done | |
| 5 | RUNS dict | Done (exec=3) | train 2018-2022, holdout 2023-2025 |
| 6 | Execute markdown | Done | |
| 7 | Load/run grid | Done (exec=4) | Cached parquet, 192 rows |
| 8 | Cell A markdown | Done | |
| 9 | Cell A code | Done (exec=5) | Boxplot figure |
| 10 | Cell B markdown | Done | |
| 11 | Cell B code | Done (exec=6) | Break-even: bid_ask is leftmost positive |
| 12 | Cell C markdown | Done | |
| 13 | Cell C code | Done (exec=7) | Heatmap figure |
| 14 | Cell D markdown | Done | |
| 15 | Cell D code | Done (exec=8) | DB coverage percentages working correctly |
| 16 | Cell E markdown | Done | |
| 17 | Cell E code | **Needs re-run** | v3 reproduction, was 8% complete |
| 18 | Cell F markdown | Not run | Spread cost analysis |
| 19 | Cell F code | Not run | |
| 20 | Cell G markdown | Not run | Per-trade P&L |
| 21 | Cell G code | Not run | |
| 22 | Cell H markdown | Not run | Period-overlap diagnostic |
| 23 | Cell H code | Not run | |

---

## Key v5 Results (Cells A–D completed)

### Cell B — Break-even Analysis
```
bid_ask               train_median=-0.1721  holdout_median=+0.6675
mid_minus_1tick       train_median=+0.3272  holdout_median=-0.2135
mid                   train_median=+0.0856  holdout_median=+0.2041
mid_plus_1tick        train_median=+0.0856  holdout_median=+0.2178

Break-even execution: bid_ask (leftmost mode with positive holdout median Sharpe)
```

### Cell D — DB Coverage
```
--- train ---
  bid_ask             : entry_db_pct=68.2%, mtm_db_pct=62.0%
  mid_minus_1tick     : entry_db_pct=71.3%, mtm_db_pct=62.5%
  mid                 : entry_db_pct=81.8%, mtm_db_pct=64.9%
  mid_plus_1tick      : entry_db_pct=83.1%, mtm_db_pct=65.4%

--- holdout ---
  bid_ask             : entry_db_pct=99.8%, mtm_db_pct=98.7%
  mid_minus_1tick     : entry_db_pct=99.3%, mtm_db_pct=98.8%
  mid                 : entry_db_pct=99.7%, mtm_db_pct=98.8%
  mid_plus_1tick      : entry_db_pct=99.6%, mtm_db_pct=98.8%

=== Global DB coverage ===
train: entry_db_pct=76.1%, mtm_db_pct=63.7%
holdout: entry_db_pct=99.6%, mtm_db_pct=98.8%
```

### Overall v5 Statistics
```
bid_ask:           holdout n=24, median_sharpe=+0.6675, positive=79.2%
mid_minus_1tick:   holdout n=24, median_sharpe=-0.2135, positive=41.7%
mid:               holdout n=24, median_sharpe=+0.2041, positive=62.5%
mid_plus_1tick:    holdout n=24, median_sharpe=+0.2178, positive=62.5%
```

---

## CRITICAL BUG: Cell E (v3 reproduction) compares apples to oranges

The original v3 grid search (`data/B3/v3_grid_search_results.parquet`) was run on **PETR4**:
```
v3 old results: market=petr4, train=2020-04-01 to 2023-12-31, holdout=2024-01-01 to 2025-12-31
v3 holdout median Sharpe: -2.3055, train median Sharpe: -1.2045
```

But Cell E (v3 reproduction) is configured to run on **BOVA11**:
```python
V3_RUNS = [
    ("v3_train", "bova11", "2020-04-01", "2023-12-31"),
    ("v3_holdout", "bova11", "2024-01-01", "2025-12-31"),
    ("v3_on_v4_holdout", "bova11", "2023-01-02", "2025-11-30"),
]
```

This means the "v3 reproduction" comparing to the documented v3 holdout Sharpe of -1.17 is comparing **BOVA11 reproduction** vs **PETR4 original**. PETR4 and BOVA11 have different volatility profiles, option liquidity, and skew parameters.

Cell E code references: `print(f"Documented v3 holdout median Sharpe: -1.17")` — this -1.17 came from PETR4, not BOVA11.

**Recommendation:** Split Cell E into two parts or change market to "petr4" for proper reproduction of v3 results. The `v3_on_v4_holdout` run (on BOVA11) is still valid for cross-comparison with v5.

---

## Uncommitted Changes

6 files have uncommitted changes (expiration fix + volume_filter removal):

```
scripts/grid_search.py        |   7 +-
src/straddle/engines.py       |  80 +++++++----------
src/straddle/params.py        |   4 +-
src/straddle/portfolio.py     |   2 +-
src/straddle/strategy.py      |  41 +++++----
tests/test_execution_modes.py | 169 ++++++++++++++++----------------
```

All 17 execution mode tests pass (`pytest tests/test_execution_modes.py -v`).

---

## Remaining Work

### 1. Fix Cell E — v3 Reproduction (CRITICAL)
- **Decide**: reproduce on PETR4 (to match documented -1.17) or BOVA11 (to match v5)?
- If PETR4: Change V3_RUNS market from "bova11" to "petr4"
- If both: Add a separate run for PETR4
- **Note**: v3 grid is 8,640 combos × 3 runs. Takes ~30-40 minutes per period.
- The cached `data/B3/v3_grid_search_results.parquet` is pre-expiration-fix (PETR4). If running on PETR4, delete this cached file first so it re-runs with the expiration fix applied.

### 2. Run Cell F — Spread Cost Analysis
- Queries DB for bid/ask/mark distribution by delta bucket and year
- Should complete in ~1 minute
- No dependencies on Cell E

### 3. Run Cell G — Per-Trade P&L for Best Config
- Finds best v5 config, runs single backtest with all 4 execution modes
- Depends on `holdout` variable from Cell 7 (already computed)
- Should complete in ~5 minutes

### 4. Run Cell H — Period-Overlap Diagnostic
- Compares v3 and v5 configs across overlapping periods
- Depends on `v3_valid` from Cell E — must run after Cell E
- Also references `best_combo` from Cell 21

### 5. Write Final Report
- `docs/2026-05-15 - v5 confirmation results.md`
- Should conclude A/B/C/D based on data
- Key evidence so far: bid_ask holdout median Sharpe = +0.67 but mid_minus_1tick is -0.21

---

## Interpretation Guidance (Preliminary)

Current v5 results suggest **Conclusion B**: VRP exists but is consumed by spread.

Evidence:
- `bid_ask` holdout Sharpe = +0.67 (positive even at most conservative execution)
- `mid_minus_1tick` holdout Sharpe = -0.21 (slightly worse than mid, which is +0.20)
- `mid` holdout Sharpe = +0.20 (positive but modest)
- `mid_plus_1tick` holdout Sharpe = +0.22 (essentially same as mid)

**Key caveats:**
1. **Train Sharpe is negative for bid_ask** (-0.17) while holdout is strongly positive (+0.67) — suggests overfitting or period-dependent behavior
2. **mid_minus_1tick is negative** in holdout (-0.21) despite mid being positive — 1 tick makes all the difference
3. **Train DB coverage is only 76%** — 24% of train entries use synthetic pricing
4. **The v3 contradiction remains unexplained**: v3 PETR4 holdout Sharpe was -2.31 (all negative), v5 BOVA11 holdout bid_ask is +0.67. Different underlying, different period, different grid.
5. **The ordering anomaly**: mid_minus_1tick (-0.21) < bid_ask (+0.67) contradicts the expected ordering. Could indicate: (a) small sample noise (n=24 per mode), (b) bid_ask selectively filters for higher-quality entries (68% DB coverage vs 83% for mid_plus_1tick), or (c) a bug.

---

## Architecture & Key Files

### Data Flow
```
params.py (PARAMS dict)
  → data.py (load_market_data → Parquet cache)
  → engines.py (make_engine → SyntheticEngine | MarketEngine)
  → strategy.py (run_backtest → trades[], equity_curve)
  → metrics.py (compute_metrics)
  → plotting.py (plot_backtest)
```

### Key Source Files

| File | Key Lines | Description |
|------|-----------|-------------|
| `src/straddle/params.py` | Full file | PARAMS schema, MARKET_PRESETS for BOVA11/PETR4, PricingParams |
| `src/straddle/engines.py` | 548-590 | `MarketEngine.__init__`, `_exec_mode`, `get_db_expiration()` |
| `src/straddle/engines.py` | 600-750 | `get_entry_marks()` — execution mode dispatch, bid/ask/mid pricing |
| `src/straddle/engines.py` | 750-900 | `get_daily_mark()`, `get_gap_open_mark()`, `get_leg_mark_with_source()` |
| `src/straddle/strategy.py` | 134 | `get_monthly_expiration()` — accepts `engine` param for DB lookup |
| `src/straddle/strategy.py` | 166 | `get_entry_dates()` — accepts `engine` param |
| `src/straddle/strategy.py` | 952 | `run_backtest()` — passes `engine=engine` to date functions |
| `src/straddle/portfolio.py` | 386 | `run_portfolio_backtest()` — passes `engine=engine` |
| `scripts/grid_search.py` | 50 | `_CHAIN_DEFAULTS` with `"chain_length_dist": ""` |
| `scripts/grid_search.py` | 257-258 | `_prepare_df()` casts `chain_length_dist` to string |
| `tests/test_execution_modes.py` | Full file | 17 tests for execution modes, DB expiration, close-side pricing |

### Data Files

| File | Description |
|------|-------------|
| `data/B3/b3_options_rb3.db` | ~9.6 GB SQLite DB with B3 options data (2008–2025) |
| `data/B3/v5_grid_search_results.parquet` | 192 rows, v5 results (May 14 12:34) |
| `data/B3/v3_grid_search_results.parquet` | 15,120 rows, v3 results on **PETR4** (May 13 19:37, pre-expiration-fix) |
| `data/B3/v4_grid_search_results.parquet` | v4 results with volume_filtered (May 14 00:39) |
| `data/B3/v3_reproduction_results.parquet` | **Does NOT exist yet** — Cell E will create this |

### BOVA11 Market Preset (defaults)
```python
market = "bova11"
underlying = "BOVA11"
currency = "BRL"
options_db_path = "data/B3/b3_options_rb3.db"
tick_size = 0.05
put_slope = 0.746  # fitted from B3 data
call_slope = 0.074  # fitted from B3 data
dte_min = 30
dte_max = 45
target_delta = 0.16
use_cdi_ivs = True
open_fill_adj = -0.05
close_fill_adj = 0.05
single_position = True
commission_per_leg = 1.0
initial_balance = 50000
execution_mode = "bid_ask"
```

### PETR4 Market Preset (defaults)
```python
market = "petr4"
underlying = "PETR4"
put_slope = 0.522
call_slope = -0.046
# (other params same as BOVA11)
```

---

## Key Technical Details

### Execution Mode Pricing Logic
- **Entry (sell side):** bid_ask→bid, mid→mark, mid_minus_1tick→mark-tick, mid_plus_1tick→mark+tick
- **Close (buy side):** bid_ask→ask, mid→mark, mid_minus_1tick→mark+tick, mid_plus_1tick→mark-tick
- This means bid_ask is the most conservative (sell low, buy high)
- mid_plus_1tick is most optimistic (sell high, buy low)
- **Asymmetry**: mid_minus_1tick sells below mid but buys above mid → slightly worse than mid on both sides

### B3 Expiration Convention
- Before May 2021: 3rd Monday of the month
- After May 2021: 3rd Friday
- `get_db_expiration()` handles both by querying the DB directly with `expected_month` filter (±5 days of calendar 3rd Friday)

### DB Coverage
- Train (2018-2022): 76.1% entry, 63.7% MTM — sparse 2018-2019 data
- Holdout (2023-2025): 99.6% entry, 98.8% MTM — nearly complete
- Entry coverage varies by execution mode: bid_ask=68.2% vs mid_plus_1tick=83.1% (bid/ask availability filters out more rows)

### Unresolved Questions
1. **Why is bid_ask holdout Sharpe +0.67 but train Sharpe -0.17?** — This reversal needs explanation. Possibly: (a) 2023-2025 was a low-vol period favorable for short vol, (b) train DB coverage gaps cause mispricing, (c) overfitting to holdout.
2. **Why does mid_minus_1tick have negative holdout Sharpe while bid_ask is positive?** — The ordering should be bid_ask < mid_minus_1tick < mid. The inversion suggests: (a) noise with small sample (n=24 per mode), or (b) selection bias — bid_ask requires bid>0, filtering out worse entries.
3. **Early exercise risk:** 34% of CALLs are AMER. Not modeled — could cause P&L leakage.
4. **v3 PETR4 vs v5 BOVA11:** Different underlyings make direct Sharpe comparison meaningless. Cell E needs to decide which underlying to use.

---

## How to Run Tests
```bash
pytest tests/test_execution_modes.py -v    # 17 tests, <1 min
pytest tests/ -v                            # Full suite
```

## How to Run the Notebook
```bash
jupyter notebook "research/2026-05-14 - B3 - v5 confirmation grid.ipynb"
```

## How to Run Grid Search
```bash
python scripts/run_backtest.py --mode market --start 2023-01-01 --end 2025-11-30
```

## Install
```bash
pip install -e ".[dev,frontend,api]"
```