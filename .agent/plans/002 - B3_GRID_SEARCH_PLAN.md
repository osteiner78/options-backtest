# B3 Parameter Grid Search

## Context

Manual verification (4 of 4 trades reconciled to the cent) confirmed the B3 backtest is mechanically correct. Default params (target_delta 0.16, dte 30–45, profit 50%, no leg rolls, vix filter at 35) produce negative Sharpe for both BOVA11 (-0.16) and PETR4 (-0.17). The open question: are these defaults a *bad* parameterisation for B3 markets, or is the volatility-risk-premium structurally insufficient at any settings?

Approach: grid-search 6 strategy dimensions across BOVA11 and PETR4, using the **pre-COVID 2011/2017–2019 period as the train window** and **2020-04 onward as a holdout that includes both the post-COVID recovery and the recent regime**. The user explicitly excluded the March 2020 BOVA crash (-45%) from train because no 16Δ short strangle survives it; the holdout *includes* this regime so we can see how train-optimal configs behave when the world changes underneath them.

If top configs in train are also positive in holdout → strategy works for B3 (pick the best, ship it). If top train configs are scattered or top configs collapse in holdout → the ranking is noise / the strategy is regime-dependent / B3 has insufficient VRP — that's the answer, with evidence.

A note on regime: the holdout window (April 2020 → Dec 2025) is **not regime-matched** to the pre-2020 train window — different rate environments (Selic 2% → 13.75%), different vol regimes, different macro. Some Sharpe degradation in holdout is expected from regime change alone. The plan therefore separates two questions: *which configs rank consistently?* (signal) vs *which configs survive the regime shift?* (robustness).

---

## Architecture: single notebook + tiny worker module

The user prefers a single notebook end-to-end. The only constraint that breaks pure-notebook is process-based parallelisation: `ProcessPoolExecutor` with spawn semantics (macOS default) cannot pickle functions defined in a notebook cell. The minimal compromise is one tiny helper file containing the worker function, imported by the notebook.

```
research/B3 - parameter grid search.ipynb       ← entry point, narrative, all charts
scripts/grid_search.py                          ← worker + grid runner ONLY
data/B3/grid_search_results.parquet             ← grid output, single dataframe
```

Notebook cell layout:
1. **Imports + setup** — pathlib, pandas, numpy, matplotlib, joblib (or concurrent.futures), `from scripts.grid_search import run_grid`
2. **Grid definition** — explicit dict of dimensions and values
3. **Period definitions** — train + holdout date ranges per market
4. **Run grid (train)** — call `run_grid(grid_def, market="bova11", period=train_dates)` then same for PETR4. Saves to parquet
5. **Run grid (holdout)** — same, holdout dates, appended to same parquet with `period` column
6. **Load results** — `pd.read_parquet(...)`
7. **Sanity checks** — total runs, runs flagged for n<50, summary stats
8. **Heatmap (a)** — Sharpe by `target_delta × dte_max`, mean over other dims
9. **Heatmap (b)** — Sharpe by `profit_target × manage_at_dte`, mean over other dims
10. **Scatter (c)** — n_trades vs Sharpe, color = total_return, n=50 vertical line
11. **Top configs** — top 10 by train Sharpe per market with all params printed
12. **Holdout validation** — train-Sharpe vs holdout-Sharpe scatter, diagonal y=x line, top-10 configs labeled
13. **Conclusions** — narrative cell

All charts are matplotlib, inline (`%matplotlib inline`), saved with `plt.savefig()` to `data/B3/grid_*.png` for the record.

---

## Grid specification

| Dimension              | Values                  | Engine param                                        |
|------------------------|-------------------------|-----------------------------------------------------|
| `target_delta`         | 0.20, 0.25, 0.30        | `target_delta`                                      |
| `dte_max`              | 21, 30, 45              | `dte_max` (pairs with `dte_min` below)              |
| `profit_target_pct`    | 0.25, 0.50, 0.75        | `profit_target_pct`                                 |
| `manage_at_dte`        | 10, 14, 21              | `manage_at_dte`                                     |
| `vix_filter`           | 25, 30, 35, OFF         | sets `vix_entry_filter_enabled` + `vix_entry_max`   |
| `defensive_leg_roll`   | True, False             | `defensive_leg_roll_enabled`                        |

**`dte_min` derivation** (not a free dimension; paired with `dte_max`):
- `dte_max=21` → `dte_min=15` (1-week window before management)
- `dte_max=30` → `dte_min=20`
- `dte_max=45` → `dte_min=30` (current default window width)

**Validity constraint** — `manage_at_dte < dte_min` is required (trade must have ≥1 day before management kicks in). Invalid combinations are dropped *before dispatch*, not silently failed:
- (`dte_max=21`, `manage=21`) → invalid
- (`dte_max=30`, `manage=21`) → invalid
- All other combinations valid

After filtering: **3 × 3 × 7 valid (dte_max, manage_at_dte) pairs × 4 × 2 = 504 combinations per market** (down from raw 648). With 2 periods × 2 markets = **2,016 runs total**. Parallelised across cores ≈ ~10 minutes wall-clock.

**`vix_filter=OFF` encoding**: `vix_entry_filter_enabled=False`, `vix_entry_max=999`. Other values: `vix_entry_filter_enabled=True`, `vix_entry_max=value`.

**Held constant across all runs** (per user spec): `commission_per_leg`, `contract_multiplier`, `max_bpr_allocation=0.30`, `roll_for_credit=True`, `max_rolls=3`, `entry_cooldown_days`, `cash_investment_mode="underlying"`, `portfolio_mode="laddering"`, `pricing_mode="market"`, `strategy_mode="short_strangle"`. All BOVA11/PETR4-specific values (`put_slope`, `call_slope`, `american_options`, `calendar`, `currency`, `commission`, `options_db_path`) come from `apply_market_preset()` and are not overridden.

---

## Periods (the user's proposal, lightly adapted)

| Market   | Train period            | Holdout period          |
|----------|-------------------------|-------------------------|
| BOVA11   | 2017-01-01 → 2019-12-31 | 2020-04-01 → 2025-12-01 |
| PETR4    | 2011-01-01 → 2019-12-31 | 2020-04-01 → 2025-12-01 |

BOVA11 starts at 2017 because earlier years are too thin (this is already the existing `BOVA11_MIN_YEAR=2015` guardrail in the DB build script; 2015–2016 has sparse 16Δ coverage). PETR4 has reliable data from 2011 onward.

The April 1, 2020 holdout start cleanly excludes the March 2020 crash from both train *and* the holdout's first month, so the holdout starts mid-recovery rather than mid-collapse.

The notebook cell that defines these dates puts both market+period tuples into a single `RUNS` list that is iterated in cell 4/5.

---

## `scripts/grid_search.py` — module structure

The module is intentionally minimal. Two top-level functions plus one private worker:

```python
def _run_one(market: str, period: tuple[str, str], param_overrides: dict) -> dict:
    """Pickle-safe worker. Mirrors api.py::_run_backtest_task lines 185-201
    so numerical results are identical to a CLI/API run with the same params.
    Returns: a dict containing the param overrides plus selected metrics."""

def run_grid(
    grid_def: dict,                  # e.g. {"target_delta": [0.20, 0.25, 0.30], ...}
    runs: list[tuple[str, str, tuple[str,str]]],  # [(label, market, (start, end))]
    n_workers: int = -1,
    output_path: Path = Path("data/B3/grid_search_results.parquet"),
) -> pd.DataFrame:
    """Enumerate the cross-product, validate (manage<dte_min, etc.),
    dispatch to workers, collect results, save parquet, return DF."""
```

`_run_one` body, exactly mirroring `src/straddle/api.py:185-201` (see Explore agent finding #4):

```python
params = dict(PARAMS)
params = apply_market_preset(params, market)
params["start_date"] = period[0]
params["end_date"]   = period[1]
params["mode"]       = "market"
params.update(param_overrides)         # grid dims override preset
data   = load_market_data(params["start_date"], params["end_date"], market=market)
engine = make_engine(params)
try:
    trades, equity_df, _, _ = run_portfolio_backtest(data, params, engine)
    metrics = compute_portfolio_metrics(trades, equity_df, params, data)
finally:
    engine.close()
return {
    **param_overrides,
    "market": market, "period_label": label,
    "n_trades":          metrics.get("n", 0),
    "total_return":      metrics.get("tot", 0.0),
    "annualized_return": metrics.get("ann", 0.0),
    "sharpe":            metrics.get("sharpe", 0.0),
    "max_drawdown":      metrics.get("mdd", 0.0),
    "calmar":            metrics.get("calmar", 0.0),
    "win_rate":          metrics.get("wr_chain", 0.0),
    "underlying_return": metrics.get("underlying_total_return", 0.0),
    "underlying_sharpe": metrics.get("underlying_sharpe", 0.0),
}
```

**Reused functions** (no reimplementation):
- `straddle.params.apply_market_preset` — applies BOVA11/PETR4 presets including the recent VIX-scale fix
- `straddle.params.PARAMS` — base defaults
- `straddle.data.load_market_data` — handles B3 parquet loading with VIX scaling
- `straddle.engines.make_engine` — opens MarketEngine with SQLite connection
- `straddle.run_portfolio_backtest` — laddering portfolio backtest
- `straddle.metrics.compute_portfolio_metrics` — all needed metrics keys confirmed by Explore agent

**Parallelisation**: `joblib.Parallel(n_jobs=-1, backend="loky")` rather than raw `concurrent.futures.ProcessPoolExecutor`. Joblib's loky backend handles the spawn/pickle dance correctly when called from a notebook on macOS, where the default `spawn` start-method otherwise breaks closures. If joblib isn't already in the env, fall back to `ProcessPoolExecutor` with the worker function imported from `scripts.grid_search` (which is fine since `_run_one` is module-level and pickle-safe).

**tqdm**: yes, wrap the parallel iteration. `joblib_progress` (Python pkg) or just print every 50 runs to stdout from inside `_run_one`. The grid is small enough that even silent execution finishes in under 15 min.

---

## Analysis cells (notebook)

### Heatmap (a) — Sharpe by `target_delta × dte_max`

```python
df_train = df.query("period_label == 'train' and market == 'bova11'")
pivot = df_train.pivot_table(values="sharpe", index="target_delta", columns="dte_max", aggfunc="mean")
fig, ax = plt.subplots(figsize=(6, 4))
im = ax.imshow(pivot, cmap="RdYlGn", vmin=-1, vmax=1, aspect="auto")
# annotate cells with value, ticks from pivot.index/columns, colorbar
```

Repeat for PETR4. **Two figures**, one per market. Same template for heatmap (b) with `profit_target × manage_at_dte`.

Cells where `manage_at_dte` was filtered out (no data) display as NaN — `imshow` renders those grey, with annotation "n/a".

### Scatter (c) — n_trades vs Sharpe

```python
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
for ax, market in zip(axes, ["bova11", "petr4"]):
    df_m = df.query("period_label == 'train' and market == @market")
    sc = ax.scatter(df_m["n_trades"], df_m["sharpe"], c=df_m["total_return"],
                    cmap="RdYlGn", vmin=-0.5, vmax=0.5, s=18, alpha=0.7)
    ax.axvline(50, ls="--", c="grey", lw=0.8, label="n=50 reliability cutoff")
    ax.axhline(0, ls=":",  c="black", lw=0.5)
    ax.set_xlabel("n_trades"); ax.set_ylabel("Sharpe")
    ax.set_title(market.upper() + " — train"); ax.legend(loc="lower right")
fig.colorbar(sc, ax=axes, label="Total return", shrink=0.8)
```

### Top-N table — printed, not plotted

```python
top10 = (df.query("period_label=='train' and market=='bova11' and n_trades >= 50")
           .nlargest(10, "sharpe")[["sharpe","calmar","total_return","n_trades",
                                    "target_delta","dte_max","profit_target_pct",
                                    "manage_at_dte","vix_filter","defensive_leg_roll"]])
print(top10.to_string(index=False))
```

### Holdout validation — train vs holdout Sharpe scatter

```python
train_df  = df.query("period_label=='train' and market==@market and n_trades>=50")
hold_df   = df.query("period_label=='holdout' and market==@market and n_trades>=50")
joined    = train_df.merge(hold_df, on=GRID_DIMS, suffixes=("_train","_holdout"))

fig, ax = plt.subplots(figsize=(7,7))
ax.scatter(joined["sharpe_train"], joined["sharpe_holdout"], alpha=0.5, s=15)
lim = max(abs(joined[["sharpe_train","sharpe_holdout"]].values).max(), 1)
ax.plot([-lim, lim], [-lim, lim], ls="--", c="grey", label="y = x (no degradation)")
ax.axhline(0, ls=":", c="black", lw=0.5); ax.axvline(0, ls=":", c="black", lw=0.5)
# label the top 10 train configs
top = joined.nlargest(10, "sharpe_train")
for _, r in top.iterrows():
    ax.annotate(f"d={r.target_delta} dte={r.dte_max}",
                (r.sharpe_train, r.sharpe_holdout), fontsize=8)
ax.set_xlabel("Sharpe (train)"); ax.set_ylabel("Sharpe (holdout)")
```

This is the diagnostic chart for "is the ranking real or noise?". Points clustered on or above the diagonal → robust. Points scattered or below the diagonal → overfitting / regime change.

---

## Output files

| File                                          | Purpose                                       |
|-----------------------------------------------|-----------------------------------------------|
| `scripts/grid_search.py`                      | New. Worker + grid runner.                    |
| `research/B3 - parameter grid search.ipynb`   | New. Notebook end-to-end.                     |
| `data/B3/grid_search_results.parquet`         | New. Single dataframe, one row per (market, period, config). |
| `data/B3/grid_heatmap_*.png`                  | New (5 files). Charts also saved to disk.     |

`scripts/grid_search.py` is added to `.gitignore`-safe paths (it's a normal source file, just lives in `scripts/` next to the existing `b3_parser.py`, `build_b3_options_db.py`, etc.).

The parquet is small (~6 columns × 2,016 rows × ~8 metrics ≈ 100 KB). It's checkpointed at the end of each market+period segment so a crash mid-run doesn't lose finished work.

---

## What is NOT changing

- `src/straddle/*` is read-only for this work. No refactor of `params.py`, `strategy.py`, `engines.py`, `metrics.py`, `data.py`. The user's preliminary plan's "Phase 1 — Refactor for grid search" is **unnecessary**: the Explore agent confirmed the params dict is already the sole control input, so `_run_one` simply varies the dict.
- The terminal UI is untouched.
- The bug fixes from the prior code review (#2 equity/option merge, #3 volume filter consistency, #4 contract_multiplier consistency) are **not** included in this plan. They're queued separately and won't change grid outputs (none affect numerical results given current data + presets).

---

## Verification

1. **Smoke test (self-equivalence, NOT CLI-equivalence)**: pick one valid grid combo (e.g. target_delta=0.20, dte_max=45, profit_target_pct=0.50, manage_at_dte=21, vix_filter="OFF", defensive_leg_roll=False) on BOVA11 train. Call `_run_one(...)` and *separately* call `run_portfolio_backtest` + `compute_portfolio_metrics` directly with the same params (mirroring `api.py::_run_backtest_task` lines 185–201). Assert numerical equality on `n_trades`, `sharpe`, `total_return`, `calmar` within 1e-9. **This proves the worker is a faithful wrapper around the canonical laddering pipeline.** Do NOT compare against `scripts/run_backtest.py` — the CLI is hardcoded to single-position mode (`run_backtest`), while the grid uses laddering (`run_portfolio_backtest`); they are different strategies and equivalence is impossible.
2. **Validity filter**: assert that the dispatched grid has zero rows where `manage_at_dte >= dte_min`. Print the count of dropped combos.
3. **n<50 flag**: after grid completes, print configs where `n_trades < 50`. These are excluded from the heatmap aggregations and grayed out in the scatter.
4. **Holdout join**: assert that `joined` (train ⨝ holdout on all grid dims) contains every valid config (no silent drops from the merge).
5. **Re-run idempotency**: deleting `data/B3/grid_search_results.parquet` and re-running cells 4-5 produces a byte-identical (or nearly so — float drift only) output. Confirms no hidden state.

---

## Critical files (summary)

| Path                                                  | Action |
|-------------------------------------------------------|--------|
| `scripts/grid_search.py`                              | **create**: ~120 lines, worker + dispatcher |
| `research/B3 - parameter grid search.ipynb`           | **create**: ~12 cells per the layout above |
| `data/B3/grid_search_results.parquet`                 | **created at runtime** by the notebook |
| `data/B3/grid_*.png`                                  | **created at runtime** by the notebook |
| `src/straddle/*`                                      | **read-only** — reused, not modified |
| `apps/terminal-ui/*`                                  | **read-only** — out of scope |
