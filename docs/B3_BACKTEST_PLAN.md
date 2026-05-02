# B3 (Brazil) Options Backtest Extension — Implementation Plan

## Context

The backtest currently runs only on SPY data (Yahoo Finance for OHLC/VIX/risk-free, a SQLite options DB for real bid/ask). The goal is to extend it to also support Brazilian equity-option underlyings — initially **BOVA11** (iShares Ibovespa ETF) and **PETR4** (Petrobras) — reusing all strategy logic with minimal changes.

Raw B3 data is in `data/B3/COTAHIST_A*.TXT` (annual files in B3's fixed-width layout). Parsing utilities already exist in `research/B3 - VRP harvesting research.ipynb` and produce per-underlying parquet files (`{bova,petr}_backtest.parquet` for OHLC + ATM IV + CDI, `options_{bova,petr}.parquet` for the full options chain with bid/ask/delta/IV).

The intended outcome is a single strategy/engine codebase that runs on either market via a `market` selector in the terminal UI / CLI / API. B3 data feeds the existing engine as a drop-in dataset after a one-time refactor to generic column names, so the strategy never needs to know which underlying it is trading.

### Decisions taken during interview

| # | Decision | Rationale |
|---|---|---|
| Q2 | **Market mode for B3 via SQLite** mirroring the SPY DB schema | Lets `MarketEngine` be reused unchanged; only `db_path` differs |
| Q3 | **Refactor `spy_*` → `underlying_*`** across the codebase | Generic names; small one-time blast-radius change |
| Q4 | **B3 (BVMF) calendar** for B3 runs, NYSE for SPY | Correct holiday handling for 3rd-Friday expiry rolls |
| Q5 | **Defer dividends, American-style pricing, per-market skew** | Out of scope for v1; documented as TODOs |
| — | **Frontend = terminal-ui only** (Streamlit out of scope) | Per user: focus only on `apps/terminal-ui/` |
| — | **`vix_to_iv_multiplier=1.0` for B3** | `vix_close` for B3 IS the actual ATM IV (no scaling) |

---

## Milestones

The work splits into six milestones. M1–M2 are data-only (no production code changes). M3 is a behaviour-preserving refactor. M4–M5 add the new feature. M6 verifies.

```
M1: Expand & validate B3 source data         ──► confidence in the data
M2: Build B3 options SQLite                   ──► drop-in MarketEngine source
M3: Refactor spy_* → underlying_* (no-op)     ──► generic column names
M4: Wire up `market` parameter (backend)      ──► engine/CLI/API support B3
M5: Terminal-UI integration                   ──► user can select market in UI
M6: Verification & rollout                    ──► SPY regression + B3 e2e
```

---

## M1 — Expand & validate B3 source data

**Goal**: Have multi-year B3 data + an explicit data-quality report we trust before building anything downstream.

**Output**: COTAHIST files for all desired years on disk; refreshed `bova_backtest.parquet`, `petr_backtest.parquet`, `options_bova.parquet`, `options_petr.parquet`; a QA report (markdown/HTML) saved alongside the notebook.

### M1.1 Add more historical COTAHIST years
- User drops additional `COTAHIST_AYYYY.TXT` files into `data/B3/`.
- Re-run the multi-year cells of `research/B3 - VRP harvesting research.ipynb` (`build_backtest_df` + per-underlying parses). The notebook already iterates all files in the directory; no code change needed.

### M1.2 Data-quality pass — new notebook `research/B3 - data quality checks.ipynb`

A standalone QA notebook producing a single report. Sections:

1. **Cross-source price reconciliation** *(user-requested)*
   - Compare COTAHIST equity close vs Yahoo `BOVA11.SA` / `PETR4.SA` per trading day. Flag rows where `|diff| / yahoo > 0.5%`.
   - Compare synthetic ATM IV (`compute_daily_atm_iv`) vs **IVBR** (B3 official, June 2024+) and **VXEWZ** (Yahoo, longer history). Plot all three on one chart.
   - Spot-check 5–10 high-volume contracts on specific dates against OpLab / TradingView / B3 bulletins (manual visual check).
2. **Coverage** — for each (date, expiration), count distinct strikes per side; verify ≤16Δ strikes exist on both sides during the strategy's DTE window.
3. **Spread sanity** — distribution of `(ask − bid) / mid`; flag `ask < bid` and spread > 100%.
4. **Delta monotonicity** — within (date, expiration, type), strike vs delta should be monotonic; non-monotonic rows indicate stale quotes.
5. **Put-call parity** — `C − P ≈ S − K·e^(−rT)` for ATM rows; flag large residuals.
6. **IV smile shape** — plot IV vs strike per expiration; should be a smile/smirk.
7. **Coverage gaps** — list (year, month) cells with no valid 16Δ pair in 30–45 DTE.
8. **Round-trip cost simulation** — replay a sample 16Δ strangle entry/exit (bid in, ask out) per month; report median round-trip cost vs synthetic mid.

**Exit criteria for M1**: User reviews the QA report and signs off that B3 data is trustworthy enough to proceed.

---

## M2 — Build B3 options SQLite

**Goal**: A single SQLite DB that `MarketEngine` can consume with no schema-aware changes beyond `db_path`.

**Output**: `data/b3_options.db` and `scripts/build_b3_options_db.py` (a one-shot conversion script).

### M2.1 Schema

Mirror `Spy Options Database.db` with one addition — an `underlying` column so a single DB holds both BOVA11 and PETR4:

```sql
CREATE TABLE options_data (
    date TEXT,
    expiration TEXT,
    type TEXT,                  -- 'call' | 'put'
    strike REAL,
    underlying TEXT,            -- 'BOVA11' | 'PETR4'   (NEW vs SPY DB)
    mark REAL,
    bid REAL,
    ask REAL,
    volume INTEGER,
    delta REAL,
    implied_volatility REAL,
    PRIMARY KEY (date, expiration, type, strike, underlying)
);
CREATE INDEX idx_lookup ON options_data(date, expiration, type, underlying);
```

### M2.2 Conversion script `scripts/build_b3_options_db.py`
- Read `options_bova.parquet` and `options_petr.parquet`.
- Map parquet columns → DB columns (`mid_price` → `mark`, `iv` → `implied_volatility`, `volume_brl` is dropped, `qty` becomes `volume`).
- Bulk insert via `executemany` in transactions.
- Verify row counts match parquet; spot-check a few `(date, expiration, strike, type, underlying)` lookups for parity.

**Exit criteria for M2**: `data/b3_options.db` exists; spot-check queries return identical values to the parquet.

---

## M3 — Refactor `spy_*` → `underlying_*` (behaviour-preserving)

**Goal**: Generic column / metric / parameter names everywhere. **Zero behaviour change for SPY runs** — this milestone must produce byte-identical SPY backtest results.

### M3.1 Backend
| File | Lines | Change |
|---|---|---|
| `src/straddle/data.py` | 31, 105–108, 120 | Rename DataFrame columns; bump cache filename to `market_data_master_v2.parquet` to avoid silent stale-cache reads |
| `src/straddle/strategy.py` | 472, 558–581, 772, 854 | Rename column reads |
| `src/straddle/engines.py` | 270, 289, 291, 304–314, 439, 450 | Rename `spy_open` parameter throughout |
| `src/straddle/portfolio.py` | 294, 301, 338, 370, 393, 408, 442, 455, 548 | Rename column reads + `prev_spy_close` |
| `src/straddle/plotting.py` | 91 | Rename column read |
| `src/straddle/metrics.py` | 19, 23, 30, 35, 38, 41 | Rename column reads + return keys (`spy_total_return` → `underlying_total_return`, `spy_sharpe` → `underlying_sharpe`) |
| `src/straddle/api.py` | 119–161, 203–204, 236, 337 | Rename Pydantic fields + column reads |
| `src/straddle/paper_trading/delta_calculator.py` | 105 | Rename column read |

`paper_trading/ibkr_client.py` keeps `spy_close` method names — IBKR side is SPY-specific in current scope (TODO when paper trading is extended to B3).

### M3.2 Terminal UI
| File | Lines | Change |
|---|---|---|
| `apps/terminal-ui/src/store.js` | 30–31 | Rename `cash_investment_mode: 'spy'` enum → `'underlying'`; rename `spy_allocation_pct` → `underlying_allocation_pct` |
| `apps/terminal-ui/src/components/sidebar/parameter-sections.js` | 94–99 | Update enum options + labels (`'spy'` → `'underlying'`, "SPY split" → "underlying split", tooltip) |
| `apps/terminal-ui/src/components/charts/ChartArea.js` | 23, 27, 235, 382, 442, 541 | Swap data keys: `metrics.spy_total_return` → `metrics.underlying_total_return`, `spy_pnl` → `underlying_pnl`, `cum_spy` → `cum_underlying` (literal text labels stay "SPY" until M5) |
| `apps/terminal-ui/src/components/perf/PerformanceBar.js` | 76–145 | Replace `metrics.spy_*`, `cagr_cash_spy`, `ret_cash_spy` with `metrics.underlying_*` |

### M3.3 Sanity check
- `pytest tests/ -v` must remain green.
- Run a SPY backtest end-to-end (CLI + terminal-ui) and confirm metrics dict matches a saved pre-refactor baseline.

**Exit criteria for M3**: SPY backtest is bit-for-bit identical; tests pass.

---

## M4 — Wire up `market` parameter (backend)

**Goal**: A single `market` knob switches the entire data pipeline (data source, calendar, currency, contract multiplier, vol-to-IV scaling). SPY remains the default; BOVA11/PETR4 become available.

### M4.1 Params schema (`src/straddle/params.py`)

Add a new sub-dict + per-market presets:

```python
class MarketParams(TypedDict, total=False):
    market: str                  # "spy" | "bova11" | "petr4"
    market_data_source: str      # "yahoo" | "b3_cotahist"
    options_db_path: str
    calendar: str                # "NYSE" | "BVMF"
    contract_multiplier: float   # 100 for both US and B3 equity options
    currency: str                # "USD" | "BRL"

MARKET_PRESETS = {
    "spy":    {"market_data_source": "yahoo",       "options_db_path": "data/Spy Options Database.db", "calendar": "NYSE", "currency": "USD", "vix_to_iv_multiplier": 1.15},
    "bova11": {"market_data_source": "b3_cotahist", "options_db_path": "data/b3_options.db",           "calendar": "BVMF", "currency": "BRL", "vix_to_iv_multiplier": 1.00},
    "petr4":  {"market_data_source": "b3_cotahist", "options_db_path": "data/b3_options.db",           "calendar": "BVMF", "currency": "BRL", "vix_to_iv_multiplier": 1.00},
}

def apply_market_preset(params: dict, market: str) -> dict: ...
```

Drop `db_path` (renamed to `options_db_path`); `commission_per_leg` is now denominated in `currency`.

### M4.2 Data layer (`src/straddle/data.py`)
- `load_market_data(start_date, end_date, market='spy', cache_dir=None)`: dispatch on `market`.
- `_load_b3_from_parquet(market, ...)` reads `data/B3/{market}_backtest.parquet` (produced by the notebook's `build_backtest_df`) and returns the same generic schema (`underlying_open/high/low/close, vix_close, risk_free_rate`). Validate the parquet's date coverage.
- `validate_market_mode_dates` takes `market` and queries the right DB.

### M4.3 Engine (`src/straddle/engines.py`)
- Read `params["options_db_path"]` (rename from `db_path`).
- Detect the `underlying` column at connect time; when present, add `WHERE underlying = ?` to all queries with `params["market"]` as the bind value. SPY DB (no `underlying` column) keeps working unchanged.
- `make_engine(params)` and `SyntheticEngine` are unchanged — already generic.

### M4.4 Strategy (`src/straddle/strategy.py`)
- `_adjust_for_holiday` (line 46–63): use `params["calendar"]` instead of hard-coded NYSE.
- Pass calendar through `get_monthly_expiration` and `get_entry_dates`.
- Replace hard-coded `100.0` multipliers (line 159, 165, plus a sweep of `* 100` in `strategy.py` and `portfolio.py`) with `params["contract_multiplier"]`.

### M4.5 CLI (`scripts/run_backtest.py`)
- Add `--market {spy,bova11,petr4}` (default `spy`).
- Apply `apply_market_preset(params, market)` before running.

### M4.6 API (`src/straddle/api.py`)
- Add `market: str = "spy"` to `BacktestRequest`.
- Apply preset before launching the background task.
- Extend `/config` enums to include `market`.
- Response model uses generic `underlying_*` field names (already from M3).

**Exit criteria for M4**: `run_backtest.py --market bova11 --mode market` produces a valid trade log and equity curve.

---

## M5 — Terminal-UI integration

**Goal**: User picks the market from the sidebar; UI labels, currency formatting, and benchmark name update everywhere.

### M5.1 Store (`apps/terminal-ui/src/store.js`)
- Add `market: 'spy'` to `defaultParams`.
- Add `'market'` to `ENUM_FIELDS`.
- Persist via the existing `localStorage` flow.

### M5.2 Sidebar (`apps/terminal-ui/src/components/sidebar/parameter-sections.js`)

Add a market row at the top of the BACKTEST section:

```js
{ key: 'market', label: 'market', color: 'amber',
  transform: v => String(v).toUpperCase(),
  options: ['spy', 'bova11', 'petr4'],
  tooltip: 'Underlying market. SPY (US): Yahoo + SPY options DB. BOVA11 / PETR4 (B3): COTAHIST + B3 options DB.' },
```

Update the cash-investment "underlying" label/tooltip to reference the active market name (display only).

### M5.3 Topbar (`apps/terminal-ui/src/components/topbar/TopBar.js:21`)
Brand text becomes reactive: `▸ ${market.toUpperCase()} BACKTEST`.

### M5.4 Charts (`apps/terminal-ui/src/components/charts/ChartArea.js`)
- Replace all literal `"SPY"` strings in legends, tooltips, and series labels with `market.toUpperCase()`.
- `fmtPnl` switches between `$` and `R$` based on `params.currency`.

### M5.5 Performance bar (`apps/terminal-ui/src/components/perf/PerformanceBar.js`)
- Row labels `"  o/w SPY"` and `"SPY B&H"` become `\`  o/w ${market.toUpperCase()}\`` and `\`${market.toUpperCase()} B&H\``.

### M5.6 API client (`apps/terminal-ui/src/api/...`)
- Include `market` in the POST payload to `/backtest`.

**No structural changes** to charts, layout, tabs, or trade log — only labels, data keys, and the new sidebar row.

**Exit criteria for M5**: Switching `market` in the sidebar and clicking Run renders correct labels, currency symbol, and benchmark for each of SPY / BOVA11 / PETR4.

---

## M6 — Verification & rollout

### M6.1 SPY regression (must be byte-identical)
```bash
pytest tests/ -v
python scripts/run_backtest.py --mode market --market spy --start 2021-01-01 --end 2024-12-31
# Compare metrics dict to pre-M3 saved baseline.
```

### M6.2 BOVA11 synthetic smoke
```bash
python scripts/run_backtest.py --mode synthetic --market bova11 --start 2024-01-01 --end 2025-12-31
```
Expect: trades > 0, equity curve flat-or-positive, no NaNs.

### M6.3 BOVA11 market mode (post-M2)
```bash
python scripts/run_backtest.py --mode market --market bova11 --start 2024-01-01 --end 2025-12-31
```
Compare avg P&L vs synthetic; market should show wider spreads and lower realized credit.

### M6.4 PETR4 market mode
Same as M6.3 with `--market petr4`.

### M6.5 Terminal-UI smoke
```bash
python scripts/run_api.py --port 8000     # backend
cd apps/terminal-ui && npm run dev         # frontend
```
- Switch market between SPY / BOVA11 / PETR4 in the sidebar.
- For each: click Run; confirm topbar brand updates, currency symbol switches `$ ↔ R$`, B&H label uses the active ticker, no console errors, equity curve renders, trade log populates.

### M6.6 Cross-source spot-check
Pick one BOVA11 trade from the backtest output; look up actual closing prices on TradingView / OpLab for entry and exit dates; confirm rounding-level match.

---

## Open TODOs (deferred)

- Refit `put_slope` / `call_slope` per market from parsed B3 data (Q5).
- Implement American-style pricing for PETR4 single-stock options (early-exercise bias near ex-dividend).
- Model ex-dividend dates for PETR4 (high-dividend payer).
- Per-market default `commission_per_leg` (B3 retail ≈ R$0.50–R$1.50 per contract).
- Extend paper trading layer beyond SPY (`paper_trading/ibkr_client.py` keeps SPY-specific methods).
- Streamlit UI is intentionally out of scope; will diverge after M3's column rename. Either retire it or update in a follow-up.

---

## Critical files (summary)

| File | Milestone | Change |
|---|---|---|
| `research/B3 - VRP harvesting research.ipynb` | M1 | Re-run with new years (no code change) |
| `research/B3 - data quality checks.ipynb` *(new)* | M1 | QA + cross-source reconciliation |
| `scripts/build_b3_options_db.py` *(new)* | M2 | Parquet → SQLite |
| `data/b3_options.db` *(new)* | M2 | Generated |
| `src/straddle/data.py` | M3, M4 | Column rename + B3 loader |
| `src/straddle/strategy.py` | M3, M4 | Column rename + calendar + multiplier |
| `src/straddle/engines.py` | M3, M4 | Column rename + `options_db_path` + `underlying` filter |
| `src/straddle/portfolio.py` | M3 | Column rename |
| `src/straddle/metrics.py` | M3 | Column + key rename |
| `src/straddle/plotting.py` | M3 | Column rename |
| `src/straddle/api.py` | M3, M4 | Field rename + `market` request param |
| `src/straddle/params.py` | M4 | `MarketParams` + presets + `contract_multiplier` |
| `src/straddle/paper_trading/delta_calculator.py` | M3 | Column rename |
| `apps/terminal-ui/src/store.js` | M3, M5 | Rename `spy_allocation_pct`; add `market` enum |
| `apps/terminal-ui/src/components/sidebar/parameter-sections.js` | M3, M5 | Rename cash mode option; add market row |
| `apps/terminal-ui/src/components/topbar/TopBar.js` | M5 | Dynamic brand from `params.market` |
| `apps/terminal-ui/src/components/charts/ChartArea.js` | M3, M5 | Rename data keys; dynamic labels + currency |
| `apps/terminal-ui/src/components/perf/PerformanceBar.js` | M3, M5 | Rename metric reads; dynamic row labels |
| `scripts/run_backtest.py` | M4 | `--market` flag |
